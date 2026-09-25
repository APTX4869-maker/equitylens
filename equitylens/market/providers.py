"""Market quote providers: Nasdaq (primary) and Tencent (fallback).

Each provider normalizes its raw HTTP body into one ProviderQuote. Parsing is
pure (payload in → quote out) so `--no-fetch` can replay saved snapshots.
All providers here are non-authorized public feeds: source_label and
source_url are carried through to the UI and every quote is snapshotted.
"""

from __future__ import annotations

import json
import re

import httpx

from equitylens.market.model import ProviderError, ProviderQuote
from equitylens.market.sources import get_config

_HTTP = {"timeout": httpx.Timeout(10.0), "follow_redirects": True}
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36")


def _money(raw: object) -> float | None:
    """Parse '$326.265', '4,760,475,574,200', '0.33%' style tokens."""
    if raw is None:
        return None
    s = str(raw).strip().replace("$", "").replace(",", "").replace("%", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _find(payload: dict, path: list[str]) -> dict | None:
    node = payload
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node if isinstance(node, dict) else None


# ---------------------------------------------------------------- Nasdaq ---

class NasdaqProvider:
    name = "nasdaq"
    QUOTE_PATH = "/api/quote/{sym}/info?assetclass=stocks"
    SUMMARY_PATH = "/api/quote/{sym}/summary?assetclass=stocks"

    def fetch(self, ticker: str, symbol: str) -> ProviderQuote:
        cfg = get_config()
        meta = cfg.providers["nasdaq"]
        base = meta.endpoint.rstrip("/")
        info_url = base + self.QUOTE_PATH.format(sym=symbol)
        sum_url = base + self.SUMMARY_PATH.format(sym=symbol)
        headers = {"User-Agent": _UA, "Accept": "application/json"}
        try:
            with httpx.Client(**_HTTP) as client:
                r1 = client.get(info_url, headers=headers)
                r1.raise_for_status()
                r2 = client.get(sum_url, headers=headers)
                r2.raise_for_status()
            info = r1.json()
            summary = r2.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"nasdaq request failed: {exc}") from exc

        primary = _find(info, ["data", "primaryData"]) or {}
        summary_data = _find(summary, ["data", "summaryData"]) or {}
        price = _money(primary.get("lastSalePrice"))
        if price is None:
            raise ProviderError("nasdaq: no lastSalePrice in payload")
        mcap = _money((summary_data.get("MarketCap") or {}).get("value"))
        prev = _money((summary_data.get("PreviousClose") or {}).get("value"))
        raw = {"request_url": info_url, "info": info, "summary": summary}
        return ProviderQuote(
            ticker=ticker, provider=self.name, price=price,
            observed_at=str(primary.get("lastTradeTimestamp") or "").strip(),
            name=str((info.get("data") or {}).get("companyName") or ticker),
            prev_close=prev, market_cap=mcap,
            source_label=meta.label,
            source_url=info_url,
            raw_payload=raw,
        )


def parse_nasdaq_snapshot(snapshot: dict, ticker: str) -> ProviderQuote:
    """Replay a saved raw snapshot without touching the network."""
    info = snapshot.get("info") or {}
    summary = snapshot.get("summary") or {}
    primary = _find(info, ["data", "primaryData"]) or {}
    summary_data = _find(summary, ["data", "summaryData"]) or {}
    price = _money(primary.get("lastSalePrice"))
    if price is None:
        raise ProviderError("nasdaq snapshot: no lastSalePrice")
    mcap = _money((summary_data.get("MarketCap") or {}).get("value"))
    prev = _money((summary_data.get("PreviousClose") or {}).get("value"))
    return ProviderQuote(
        ticker=ticker, provider="nasdaq", price=price,
        observed_at=str(primary.get("lastTradeTimestamp") or "").strip(),
        name=str((info.get("data") or {}).get("companyName") or ticker),
        prev_close=prev, market_cap=mcap,
        source_label=(get_config().providers["nasdaq"]).label,
        source_url=snapshot.get("request_url", ""),
        raw_payload=snapshot,
    )


# ---------------------------------------------------------------- Tencent ---

class TencentProvider:
    name = "tencent"

    def fetch(self, ticker: str, symbol: str) -> ProviderQuote:
        cfg = get_config()
        meta = cfg.providers["tencent"]
        url = meta.endpoint.rstrip("/") + f"/q={symbol}"
        try:
            with httpx.Client(**_HTTP) as client:
                r = client.get(url)
                r.raise_for_status()
            body = r.content.decode(meta.encoding, errors="replace")
        except (httpx.HTTPError, UnicodeDecodeError) as exc:
            raise ProviderError(f"tencent request failed: {exc}") from exc
        raw = {"request_url": url, "body": body}
        return parse_tencent_body(body, ticker, request_url=url, raw=raw)


def parse_tencent_body(body: str, ticker: str, request_url: str = "", raw: dict | None = None) -> ProviderQuote:
    """Parse the `v_usAAPL="200~...";` payload.

    Field layout (split on '~', 0-based): 3=price, 4=prev close, 5=open,
    30=timestamp (provider-local), 33=high, 34=low, 35=currency,
    39=PE(TTM, informational), 44=market cap in 亿 USD, 46=company name.
    """
    m = re.search(r'="([^"]+)"', body)
    if not m:
        raise ProviderError("tencent: no quote payload found")
    f = m.group(1).split("~")

    def pick(idx: int) -> float | None:
        if idx >= len(f) or f[idx] in ("", "0.00"):
            return None
        try:
            return float(f[idx])
        except ValueError:
            return None

    price = pick(3)
    if price is None:
        raise ProviderError("tencent: no current price in payload")
    mcap_yi = pick(44)
    mcap = mcap_yi * 1e8 if mcap_yi else None
    name = f[46] if len(f) > 46 else ticker
    meta = get_config().providers["tencent"]
    quote = ProviderQuote(
        ticker=ticker, provider="tencent", price=price,
        observed_at=f[30] if len(f) > 30 else "",
        name=name, prev_close=pick(4), open_price=pick(5),
        high=pick(33), low=pick(34), market_cap=mcap,
        currency=f[35] if len(f) > 35 and f[35] else "USD",
        source_label=meta.label,
        source_url=request_url,
        raw_payload=raw or {"request_url": request_url, "body": body},
    )
    return quote


# ---------------------------------------------------------------- registry ---

PROVIDERS: dict[str, object] = {
    "nasdaq": NasdaqProvider(),
    "tencent": TencentProvider(),
}


def snapshot_bytes(quote: ProviderQuote) -> bytes:
    """Serialize the verbatim payload to bytes for the raw snapshot store."""
    payload = quote.raw_payload or {}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
