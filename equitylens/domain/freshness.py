"""Data freshness service (M8.6): per-module as-of dates from the local store.

Every module reports what data it holds and when it was last refreshed, so the
UI can say "data as of X" instead of silently serving stale facts. Missing
modules are explicit (not synced), never replaced with older fallback data.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

# Per-module staleness windows (calendar days before the module is flagged stale)
STALE_AFTER_DAYS = {
    "sec_financials": 200,   # between filings quarters are quiet
    "segments": 200,
    "management": 365,       # DEF 14A is annual
    "market_quote": 7,       # quotes should be refreshed at least weekly
    "valuation_runs": 400,
}


def _days_ago(ts) -> int | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)  # DuckDB TIMESTAMP is naive UTC
    except ValueError:
        return None
    return max(0, (datetime.now(timezone.utc) - dt).days)


def _parse_observed_at(s: str) -> datetime | None:
    """Parse a provider-reported observation time (e.g. 'Sep 3, 2026 9:58 AM ET'
    or '2026-09-03 09:58:41') to a naive datetime. Returns None if unparseable."""
    if not s:
        return None
    s = s.strip()
    s = re.sub(r"\s+(ET|PT|CT|MT)\s*$", "", s)
    for fmt in ("%b %d, %Y %I:%M %p", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _status(days: int | None, threshold: int, missing_hint: str) -> dict:
    if days is None:
        return {"status": "missing", "detail": missing_hint, "days_ago": None}
    stale = days > threshold
    return {"status": "stale" if stale else "ok",
            "detail": f"{days} 天前更新（超过 {threshold} 天视为过期）" if stale else f"{days} 天前更新",
            "days_ago": days}


def freshness(store, company_id: str, ticker: str) -> dict:
    modules: list[dict] = []

    # ---- SEC financial facts: latest filing date + last ingest ----
    filings = store.query(
        """SELECT form_type, MAX(COALESCE(filed_at, published_at)) AS latest FROM source_document
           WHERE company_id = ? AND form_type IN ('10-K', '10-Q')
           GROUP BY form_type ORDER BY latest DESC""",
        [company_id],
    )
    ingest = store.query_one(
        "SELECT MAX(finished_at) AS at FROM ingestion_run WHERE company_id = ? AND status = 'ok'",
        [company_id],
    )
    base = ingest["at"] if ingest and ingest.get("at") else None
    for f in filings:
        if base is None or (f["latest"] and str(f["latest"]) > str(base)):
            base = f["latest"]
    latest_filing = filings[0] if filings else None
    detail = (f"最近披露 {latest_filing['form_type']} "
              f"{str(latest_filing['latest'])[:10]}" if latest_filing else "未同步（运行 equitylens sync）")
    days = _days_ago(base)
    st = _status(days, STALE_AFTER_DAYS["sec_financials"], detail)
    modules.append({"key": "sec_financials", "label": "SEC 财务事实", "as_of": str(base)[:10] if base else None,
                    "detail": detail, "status": st["status"], "days_ago": st["days_ago"]})

    # ---- segments ----
    seg_docs = store.query_one(
        "SELECT MAX(COALESCE(filed_at, fetched_at)) AS at FROM source_document "
        "WHERE company_id = ? AND document_type = 'FILING_DOCUMENT' AND form_type IN ('10-K','10-Q')",
        [company_id],
    )
    seg_at = seg_docs["at"] if seg_docs and seg_docs.get("at") else None
    st = _status(_days_ago(seg_at), STALE_AFTER_DAYS["segments"],
                 "无分部 filing 文档（运行 equitylens sync-segments）")
    modules.append({"key": "segments", "label": "分部数据", "as_of": str(seg_at)[:10] if seg_at else None,
                    "detail": st["detail"], "status": st["status"], "days_ago": st["days_ago"]})

    # ---- management: governance is driven by the annual proxy (DEF 14A), not by
    # frequent Form 4 insider filings — a new Form 4 must not mask an old proxy.
    proxy = store.query_one(
        "SELECT MAX(filed_at) AS at FROM source_document WHERE company_id = ? AND form_type = 'DEF 14A'",
        [company_id],
    )
    f4 = store.query_one(
        "SELECT MAX(filed_at) AS at FROM source_document WHERE company_id = ? AND form_type = '4'",
        [company_id],
    )
    proxy_at = proxy["at"] if proxy and proxy.get("at") else None
    f4_at = f4["at"] if f4 and f4.get("at") else None
    st = _status(_days_ago(proxy_at), STALE_AFTER_DAYS["management"],
                 "无代理声明（运行 equitylens sync-management）")
    detail = st["detail"]
    if f4_at is not None:
        detail += f"（最新 Form 4 {str(f4_at)[:10]}）"
    modules.append({"key": "management", "label": "管理层/治理", "as_of": str(proxy_at)[:10] if proxy_at else None,
                    "detail": detail, "status": st["status"], "days_ago": st["days_ago"]})

    # ---- market quote ----
    quote = store.latest_market_quote(company_id)
    if quote:
        provider = quote.get("provider") or ""
        try:
            from equitylens.market.sources import get_config
            meta = get_config().providers.get(provider)
            provider_label = meta.label if meta is not None else provider
        except Exception:
            provider_label = provider
        # Staleness is judged by the provider-reported OBSERVATION time, not the
        # fetch/replay time — a 30-day-old quote replayed today is still stale.
        obs = _parse_observed_at(str(quote.get("observed_at") or ""))
        if obs is not None:
            obs = obs.replace(tzinfo=timezone.utc)
            if obs > datetime.now(timezone.utc):
                st = {"status": "stale", "detail": "观察时间在未来（异常）", "days_ago": None}
                as_of = obs.isoformat()
            else:
                days = (datetime.now(timezone.utc) - obs).days
                st = _status(days, STALE_AFTER_DAYS["market_quote"], "")
                as_of = obs.strftime("%Y-%m-%d")
        else:
            qat = str(quote["fetched_at"] or "")[:19]
            st = _status(_days_ago(qat), STALE_AFTER_DAYS["market_quote"], "")
            as_of = qat[:10]
            st["detail"] = f"{st['detail']}（观察时间无法解析）"
        modules.append({"key": "market_quote", "label": "行情快照", "as_of": as_of,
                        "detail": (f"{provider_label} "
                                   f"${quote['price']:.2f} · {quote['observed_at']}"),
                        "status": st["status"], "days_ago": st["days_ago"]})
    else:
        modules.append({"key": "market_quote", "label": "行情快照", "as_of": None,
                        "detail": "行情未同步（运行 equitylens sync-quotes）",
                        "status": "missing", "days_ago": None})

    # ---- valuation runs ----
    vr = store.query_one(
        "SELECT MAX(run_at) AS at FROM valuation_run WHERE company_id = ?", [company_id])
    vr_at = vr["at"] if vr and vr.get("at") else None
    st = _status(_days_ago(vr_at), STALE_AFTER_DAYS["valuation_runs"], "尚无估值运行记录")
    modules.append({"key": "valuation_runs", "label": "估值运行", "as_of": str(vr_at)[:19] if vr_at else None,
                    "detail": st["detail"], "status": st["status"], "days_ago": st["days_ago"]})

    stale = [m for m in modules if m["status"] in ("stale", "missing")]
    return {
        "ticker": ticker,
        "modules": modules,
        "stale_modules": [m["key"] for m in stale],
        "hint": ("以下模块数据较旧或缺失："
                 + "、".join(m["label"] for m in stale)
                 + "。可在终端运行对应 sync 命令刷新。" if stale else None),
    }
