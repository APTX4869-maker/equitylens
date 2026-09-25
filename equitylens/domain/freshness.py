"""Data freshness service (M8.6): per-module as-of dates from the local store.

Every module reports what data it holds and when it was last refreshed, so the
UI can say "data as of X" instead of silently serving stale facts. Missing
modules are explicit (not synced), never replaced with older fallback data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Per-module staleness windows (calendar days before the module is flagged stale)
STALE_AFTER_DAYS = {
    "sec_financials": 200,   # between filings quarters are quiet
    "segments": 200,
    "management": 365,       # DEF 14A is annual
    "market_quote": 7,       # quotes should be refreshed at least weekly
    "valuation_runs": 400,
}
FINANCIAL_FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A"}


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


def _status(days: int | None, threshold: int, missing_hint: str) -> dict:
    if days is None:
        return {"status": "missing", "detail": missing_hint, "days_ago": None}
    stale = days > threshold
    return {"status": "stale" if stale else "ok",
            "detail": f"{days} 天前更新（超过 {threshold} 天视为过期）" if stale else f"{days} 天前更新",
            "days_ago": days}


def freshness(
    store,
    company_id: str,
    ticker: str,
    *,
    source_documents: list[dict] | None = None,
    canonical_facts: list[dict] | None = None,
) -> dict:
    modules: list[dict] = []

    # ---- SEC financial facts: latest filing date + last ingest ----
    if source_documents is None:
        filings = store.query(
            """SELECT form_type, MAX(COALESCE(filed_at, published_at)) AS latest FROM source_document
               WHERE company_id = ? AND form_type IN ('10-K', '10-Q', '10-K/A', '10-Q/A')
               GROUP BY form_type ORDER BY latest DESC""",
            [company_id],
        )
        ingest = store.query_one(
            "SELECT MAX(finished_at) AS at FROM ingestion_run WHERE company_id = ? AND status = 'ok'",
            [company_id],
        )
    else:
        grouped: dict[str, str] = {}
        for document in source_documents:
            form_type = document.get("form_type")
            disclosed_at = document.get("filed_at") or document.get("published_at")
            if form_type in FINANCIAL_FORMS and disclosed_at:
                latest = grouped.get(form_type)
                grouped[form_type] = max(str(disclosed_at), latest or "")
        filings = [
            {"form_type": form_type, "latest": latest}
            for form_type, latest in grouped.items()
        ]
        if not filings and canonical_facts:
            disclosed_dates = [
                str(fact.get("as_known_at"))
                for fact in canonical_facts
                if fact.get("as_known_at")
                and _days_ago(fact.get("as_known_at")) is not None
            ]
            if disclosed_dates:
                form_types = [
                    str(document["form_type"])
                    for document in source_documents
                    if document.get("form_type") in FINANCIAL_FORMS
                ]
                filings.append({
                    "form_type": form_types[-1] if form_types else "SEC filing",
                    "latest": max(disclosed_dates),
                })
        filings.sort(key=lambda item: item["latest"], reverse=True)
        ingest = None
    # SEC financial age is the latest applicable FILED/PUBLISHED disclosure, never
    # the ingestion completion time (D10): a fresh ingest must not refresh an old
    # filing.
    latest_filing = filings[0] if filings else None
    base = latest_filing["latest"] if latest_filing else None
    detail = (f"最近披露 {latest_filing['form_type']} "
              f"{str(latest_filing['latest'])[:10]}" if latest_filing else "未同步（运行 equitylens sync）")
    if ingest and ingest.get("at"):
        detail += f"；最近一次同步完成 {str(ingest['at'])[:19]}"
    days = _days_ago(base)
    st = _status(days, STALE_AFTER_DAYS["sec_financials"], detail)
    modules.append({"key": "sec_financials", "label": "SEC 财务事实", "as_of": str(base)[:10] if base else None,
                    "detail": detail, "status": st["status"], "days_ago": st["days_ago"]})

    # ---- segments ----
    if source_documents is None:
        seg_docs = store.query_one(
            "SELECT MAX(COALESCE(filed_at, published_at)) AS at FROM source_document "
            "WHERE company_id = ? AND document_type = 'FILING_DOCUMENT' "
            "AND form_type IN ('10-K','10-Q','10-K/A','10-Q/A')",
            [company_id],
        )
        seg_at = seg_docs["at"] if seg_docs and seg_docs.get("at") else None
    else:
        fact_dates_by_document: dict[str, list[str]] = {}
        for fact in canonical_facts or []:
            document_id = fact.get("source_document_id")
            disclosed_at = fact.get("as_known_at")
            if document_id and disclosed_at and _days_ago(disclosed_at) is not None:
                fact_dates_by_document.setdefault(str(document_id), []).append(str(disclosed_at))
        segment_dates = [
            str(disclosed_at)
            for document in source_documents
            if document.get("document_type") == "FILING_DOCUMENT"
            and document.get("form_type") in FINANCIAL_FORMS
            for disclosed_at in [
                document.get("filed_at")
                or document.get("published_at")
                or max(fact_dates_by_document.get(str(document.get("source_document_id")), []), default=None)
            ]
            if disclosed_at
        ]
        seg_at = max(segment_dates) if segment_dates else None
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
    from equitylens.market.age import quote_observation_status

    quote = store.latest_market_quote(company_id)
    if quote:
        provider = quote.get("provider") or ""
        try:
            from equitylens.market.sources import get_config
            meta = get_config().providers.get(provider)
            provider_label = meta.label if meta is not None else provider
        except Exception:
            provider_label = provider
        # Staleness is judged by the provider-reported OBSERVATION time (shared
        # with quote comparison), never the fetch/replay time (D10).
        age = quote_observation_status(str(quote.get("observed_at") or ""))
        module_status = "ok" if age["status"] == "ok" else "stale"
        modules.append({"key": "market_quote", "label": "行情快照", "as_of": age["as_of"],
                        "detail": (f"{provider_label} ${quote['price']:.2f} · "
                                   f"{quote['observed_at']} · {age['detail']}"),
                        "status": module_status, "days_ago": age["days_ago"]})
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
