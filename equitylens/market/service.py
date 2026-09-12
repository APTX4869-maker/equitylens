"""Market quote sync service + deterministic derived blocks (API-facing).

Flow: sync_quotes() fetches quotes through the configured provider chain,
snapshots the raw payload (SHA-256) under data/raw/market/{ticker}/ and appends
a market_quote row. API read paths (quote_block, valuation_market_block) only
read the store; when nothing is synced they return an explicit UNAVAILABLE
state with a hint to run `equitylens sync-quotes`, never a fabricated price.

Derived values are deterministic formulas over stored facts:
  - market_cap: provider-reported market cap (kept verbatim, USD)
  - pe_ttm.v1     : market_cap / trailing-4-quarter net income (metric engine TTM)
  - price_vs_fair.v1 : (price / fair_value_per_share - 1)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from equitylens.config import RAW_DIR
from equitylens.domain.companies import get_company
from equitylens.market.model import ProviderError, ProviderQuote
from equitylens.market.providers import (
    PROVIDERS, NasdaqProvider, TencentProvider, parse_nasdaq_snapshot,
    parse_tencent_body, snapshot_bytes,
)
from equitylens.market.sources import get_config
from equitylens.storage.duckdb_store import DuckDBStore
from equitylens.storage.raw_store import save_snapshot

PE_FORMULA = "pe_ttm.v1"
PRICE_VS_FAIR_FORMULA = "price_vs_fair.v1"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fetch_time_from_snapshot_name(name: str) -> str | None:
    """Recover the original fetch time encoded in a snapshot filename like
    'nasdaq_20260903T140349Z.json' (D10: replay must not rewrite fetched_at)."""
    import re

    m = re.search(r"(\d{8}T\d{6}Z)", name)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return dt.replace(microsecond=0).isoformat()
    except ValueError:
        return None


# Replay parsers keyed by provider for --no-fetch
_REPLAY = {
    "nasdaq": lambda snap, ticker: parse_nasdaq_snapshot(snap, ticker),
    "tencent": lambda snap, ticker: parse_tencent_body(
        (snap.get("body") or ""), ticker, request_url=snap.get("request_url", ""), raw=snap),
}


@dataclass
class SyncReport:
    company: str = ""
    quotes: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def line(self) -> str:
        parts = [f"{self.company}: "]
        parts.append(", ".join(
            f"{q['provider']}={q['price']} ({q['observed_at']})" for q in self.quotes
        ) or "no quotes")
        if self.warnings:
            parts.append(" warnings=" + "; ".join(self.warnings))
        return "".join(parts)


def fetch_quote(ticker: str, provider_name: str | None = None) -> ProviderQuote:
    """Fetch one quote walking the configured provider chain."""
    cfg = get_config()
    order = [provider_name] if provider_name else list(cfg.active_providers)
    last_err: str | None = None
    for name in order:
        provider = PROVIDERS.get(name)
        if provider is None:
            last_err = f"unknown provider {name!r}"
            continue
        try:
            symbol = cfg.symbol_for(ticker, name)
            quote = provider.fetch(ticker, symbol)  # type: ignore[attr-defined]
            if quote.price <= 0:
                raise ProviderError(f"{name}: non-positive price")
            return quote
        except (ProviderError, KeyError, ValueError) as exc:
            last_err = f"{name}: {exc}"
    raise ProviderError(f"all providers failed for {ticker}: {last_err}")


def sync_quotes(tickers: list[str], fetch: bool = True, store: DuckDBStore | None = None,
                raw_dir=RAW_DIR, provider_name: str | None = None) -> list[SyncReport]:
    """Fetch (or replay) and persist quotes for each ticker. Appends rows; never overwrites."""
    store = store or DuckDBStore()
    store.connect()
    store.init_schema()  # idempotent: dev DBs created before M8 need market_quote etc.
    reports: list[SyncReport] = []
    for ticker in tickers:
        company = get_company(ticker, store=store)
        report = SyncReport(company=f"{ticker} {company.name}")
        if fetch:
            try:
                quote = fetch_quote(ticker, provider_name)
                report.quotes.append(
                    _persist_one(
                        store, company.cik, company.security_id, ticker, quote, raw_dir
                    )
                )
            except ProviderError as exc:
                report.warnings.append(str(exc))
        else:
            replayed = _replay_latest(
                store, company.cik, company.security_id, ticker, raw_dir, provider_name
            )
            report.quotes.extend(replayed)
            if not replayed:
                report.warnings.append("no local snapshots to replay (run without --no-fetch first)")
        reports.append(report)
    return reports


def _persist_one(
    store: DuckDBStore,
    company_id: str,
    security_id: str | None,
    ticker: str,
    quote: ProviderQuote,
    raw_dir,
) -> dict:
    content = snapshot_bytes(quote)
    snap_dir = raw_dir / "market" / ticker
    _, sha = save_snapshot(snap_dir, f"{quote.provider}_{_utc_compact()}.json", content)
    row = quote.to_row(company_id, sha, _now(), security_id=security_id)
    store.insert_market_quote(row)
    return {"provider": quote.provider, "price": quote.price, "observed_at": quote.observed_at}


def _replay_latest(
    store: DuckDBStore,
    company_id: str,
    security_id: str | None,
    ticker: str,
    raw_dir,
    provider_name: str | None,
) -> list[dict]:
    """Re-parse the most recent snapshot file per provider and append rows."""
    import json

    cfg = get_config()
    order = [provider_name] if provider_name else list(cfg.active_providers)
    out: list[dict] = []
    snap_dir = raw_dir / "market" / ticker
    if not snap_dir.exists():
        return out
    for name in order:
        files = sorted(snap_dir.glob(f"{name}_*.json"), key=lambda p: p.stat().st_mtime)
        if not files:
            continue
        snap = json.loads(files[-1].read_text())
        parser = _REPLAY.get(name)
        if parser is None:
            continue
        try:
            quote = parser(snap, ticker)
            fetched_at = _fetch_time_from_snapshot_name(files[-1].name) or _now()
            row = quote.to_row(
                company_id, None, fetched_at, security_id=security_id
            )
            store.insert_market_quote(row)
            out.append({"provider": name, "price": quote.price, "observed_at": quote.observed_at})
        except ProviderError as exc:
            out.append({"provider": name, "error": str(exc)})
    return out


# ------------------------------------------------------------- read paths ---

def latest_quote_row(
    store: DuckDBStore, company_id: str, security_id: str | None = None
) -> dict | None:
    return store.latest_market_quote(company_id, security_id)


def _reason_no_sync(ticker: str) -> str:
    return f"行情未同步：先运行 equitylens sync-quotes {ticker}（本地快照模式，不伪造价格）"


def quote_block(
    store: DuckDBStore,
    company_id: str,
    ticker: str,
    security_id: str | None = None,
) -> dict:
    """GET /market/quote body: quote + deterministic derived market facts."""
    cfg = get_config()
    row = latest_quote_row(store, company_id, security_id)
    if row is None:
        return {"status": "UNAVAILABLE", "configured": bool(cfg.active_providers),
                "synced": False, "reason": _reason_no_sync(ticker)}
    quote = {
        "observation_id": row["quote_id"],
        "price": row["price"], "currency": row["currency"],
        "observed_at": row["observed_at"], "provider": row["provider"],
        "provider_label": _provider_label(cfg, row["provider"]),
        "name": row["name"], "prev_close": row["prev_close"],
        "source_label": row["source_label"], "source_url": row["source_url"],
        "fetched_at": str(row["fetched_at"] or "")[:19],
    }
    from equitylens.market.age import quote_observation_status

    age = quote_observation_status(str(row.get("observed_at") or ""))
    status = "OK" if age["status"] == "ok" else "STALE"
    derived = _derived(store, company_id, row)
    return {"status": status,
            "stale": age["status"] != "ok",
            "stale_reason": age["detail"] if age["status"] != "ok" else None,
            "quote_age_days": age["days_ago"],
            "configured": True, "synced": True,
            "quote": quote, "derived": derived}


def _provider_label(cfg, provider: str) -> str:
    meta = cfg.providers.get(provider)
    return meta.label if meta is not None else provider


def _derived(store: DuckDBStore, company_id: str, row: dict) -> dict:
    from equitylens.metrics.engine import MetricEngine

    derived: dict = {}
    if row.get("market_cap"):
        mcap = float(row["market_cap"])
        derived["market_cap"] = mcap
        engine = MetricEngine(store)
        try:
            ni = engine.current("NET_INCOME", company_id, frequency="ttm")
            if ni.status != "OK":
                derived.update(
                    pe_ttm=None,
                    pe_ttm_status=ni.status,
                    pe_ttm_reason=ni.missing_reason,
                )
            elif ni.value is None or ni.value <= 0:
                derived.update(
                    pe_ttm=None,
                    pe_ttm_status="UNSUPPORTED",
                    pe_ttm_reason="TTM 净利润为负或零，P/E 不适用",
                )
            else:
                derived["pe_ttm"] = round(mcap / float(ni.value), 2)
                derived["pe_ttm_status"] = "OK"
                derived["pe_ttm_formula"] = PE_FORMULA
                derived["pe_ttm_evidence"] = {
                    "market_cap_source": f"market_quote:{row['provider']}:{row['observed_at']}",
                    "ni_ttm_evidence_ids": ni.input_fact_ids or [],
                    "ni_ttm_period": ni.period_label,
                }

            fcf = engine.current("FCF", company_id, frequency="ttm")
            if fcf.status != "OK":
                derived.update(
                    pfcf_ttm=None,
                    fcf_yield_ttm=None,
                    pfcf_ttm_status=fcf.status,
                    pfcf_ttm_reason=fcf.missing_reason,
                )
            elif fcf.value is None or fcf.value <= 0:
                derived.update(
                    pfcf_ttm=None,
                    fcf_yield_ttm=None,
                    pfcf_ttm_status="UNSUPPORTED",
                    pfcf_ttm_reason="TTM 自由现金流为负或零，P/FCF 不适用",
                )
            else:
                fcf_val = float(fcf.value)
                derived["pfcf_ttm"] = round(mcap / fcf_val, 2)
                derived["fcf_yield_ttm"] = round(fcf_val / mcap, 4)
                derived["pfcf_ttm_status"] = "OK"
                derived["pfcf_ttm_formula"] = "pfcf_ttm.v1"
                derived["fcf_yield_ttm_formula"] = "fcf_yield_ttm.v1"
                derived["pfcf_ttm_evidence"] = {
                    "market_cap_source": f"market_quote:{row['provider']}:{row['observed_at']}",
                    "fcf_ttm_evidence_ids": fcf.input_fact_ids or [],
                    "fcf_ttm_period": fcf.period_label,
                }
        except ValueError as exc:
            derived.update(
                pe_ttm=None,
                pe_ttm_status="ERROR",
                pe_ttm_reason=str(exc),
                pfcf_ttm=None,
                fcf_yield_ttm=None,
                pfcf_ttm_status="ERROR",
                pfcf_ttm_reason=str(exc),
            )
    return derived


def valuation_market_block(store: DuckDBStore, company_id: str, ticker: str,
                           fair_value_per_share: float | None,
                           security_id: str | None = None) -> dict:
    """Market block embedded in valuation responses (compares price vs fair)."""
    block = quote_block(store, company_id, ticker, security_id)
    if block["status"] == "OK" and fair_value_per_share:
        premium = (float(block["quote"]["price"]) / float(fair_value_per_share) - 1.0)
        block["derived"] = dict(block.get("derived") or {})
        block["derived"]["price_vs_fair_pct"] = round(premium * 100.0, 2)
        block["derived"]["price_vs_fair_formula"] = PRICE_VS_FAIR_FORMULA
        block["derived"]["fair_value_per_share"] = round(float(fair_value_per_share), 2)
    return block
