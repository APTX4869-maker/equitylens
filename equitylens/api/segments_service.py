"""Segments API query service (M4).

Builds segment series from segment_fact rows:
- latest-restated selection (max source filing date) per (segment, metric, period)
- quarterly series derives Q4 = FY - YTD_9M when the issuer only reports Q1-Q3
  in 10-Qs (same YTD-chain rule as canonical facts)
- profitability is DISCLOSED only when the issuer actually discloses it
  (MSFT does; AAPL does not -> NOT_DISCLOSED, never estimated)
"""

from __future__ import annotations

import json

from equitylens.normalization.segments import SegmentConfigRegistry

FREQ_ORDER = {"Q_STANDALONE": 0, "FY": 1, "YTD_6M": 2, "YTD_9M": 3, "INSTANT": 4}


def _latest_per_row(rows: list[dict]) -> list[dict]:
    """latest-restated: keep the row from the most recently filed document."""
    best: dict[tuple, dict] = {}
    for r in rows:
        key = (r["segment_name_reported"], r["metric_name"], r["fiscal_year"],
               r["fiscal_quarter"], r["period_type"])
        if key not in best or (r.get("filed_at") or "") > (best[key].get("filed_at") or ""):
            best[key] = r
    return list(best.values())


def get_segments(
    store,
    ticker: str,
    kind: str = "segment",
    frequency: str = "annual",
    limit: int | None = None,
    *,
    published_rows: list[dict] | None = None,
    published_config=None,
) -> dict:
    company_cik = None
    from equitylens.domain.companies import get_company

    company_cik = get_company(ticker, store=store).cik
    config = published_config or SegmentConfigRegistry().get(ticker)
    if config is None:
        raise ValueError(f"No segment mapping configured for {ticker}")

    if published_rows is None:
        rows = store.query(
            """SELECT sf.*, sd.form_type, sd.filed_at, sd.accession_number, sd.source_url
               FROM segment_fact sf
               JOIN source_document sd ON sd.source_document_id = sf.source_document_id
               WHERE sf.company_id = ? AND sf.segment_kind = ?
               ORDER BY sd.filed_at""",
            [company_cik, kind],
        )
    else:
        rows = [row for row in published_rows if row.get("segment_kind") == kind]
    for r in rows:
        if r.get("source_raw_fact_ids"):
            try:
                r["input_ids"] = json.loads(r["source_raw_fact_ids"])
            except (TypeError, json.JSONDecodeError):
                r["input_ids"] = []
        else:
            r["input_ids"] = []
    rows = _latest_per_row(rows)

    # group by segment
    segments: dict[str, dict] = {}
    for r in rows:
        name = r["segment_name_canonical"] or r["segment_name_reported"]
        seg = segments.setdefault(name, {
            "name": name,
            "reported_name": r["segment_name_reported"],
            "kind": r["segment_kind"],
            "revenue": {},
            "profit": {},
            "sources": {},
        })
        if r["metric_name"] == "REVENUE":
            seg["revenue"][(r["fiscal_year"], r["fiscal_quarter"], r["period_type"])] = r
            seg["sources"][(r["fiscal_year"], r["fiscal_quarter"], r["period_type"])] = {
                "source_document_id": r["source_document_id"],
                "form_type": r["form_type"],
                "accession_number": r["accession_number"],
                "filed_at": str(r["filed_at"])[:10] if r.get("filed_at") else None,
                "source_url": r["source_url"],
            }
        elif r["metric_name"] == "OPERATING_INCOME":
            seg["profit"][(r["fiscal_year"], r["fiscal_quarter"], r["period_type"])] = r

    profit_disclosed = config.profit_concept is not None
    out: list[dict] = []
    for name, seg in sorted(segments.items()):
        if frequency == "quarterly":
            series = _quarterly_series(seg["revenue"], store)
        else:
            series = _annual_series(seg["revenue"])
        latest = series[-1] if series else None
        share = growth = None
        if latest and latest.get("value") is not None:
            share = latest["value"] / _total_revenue(segments, frequency) if _total_revenue(segments, frequency) else None
            prev = _year_ago(series)
            if prev and prev.get("value"):
                growth = latest["value"] / prev["value"] - 1.0
        # profitability
        profitability = {"status": "NOT_DISCLOSED", "value": None}
        if profit_disclosed:
            p = _latest_profit(seg["profit"], frequency)
            if p:
                profitability = {"status": "DISCLOSED", "value": p["value"],
                                 "period": f"FY{p['fiscal_year']}" + (f"Q{p['fiscal_quarter']}" if p.get("fiscal_quarter") else "")}
        out.append({
            "name": name,
            "reported_name": seg["reported_name"],
            "kind": seg["kind"],
            "series": series,
            "latest": latest,
            "share": share,
            "growth_yoy": growth,
            "profitability": profitability,
            "sources": _latest_sources(seg["sources"]),
        })

    total = _total_revenue(segments, frequency)
    return {
        "ticker": ticker,
        "frequency": frequency,
        "kind": kind,
        "profit_disclosed": profit_disclosed,
        "total_revenue": total,
        "segments": out,
    }


def _annual_series(revenue: dict) -> list[dict]:
    items = []
    for (fy, fq, ptype), r in revenue.items():
        if ptype != "FY":
            continue
        items.append({
            "period": f"FY{fy}",
            "fiscal_year": fy,
            "fiscal_quarter": None,
            "value": r["value"],
            "status": r["status"],
            "source_document_id": r.get("source_document_id"),
        })
    items.sort(key=lambda x: x["fiscal_year"] or 0)
    return items


def _quarterly_series(revenue: dict, store) -> list[dict]:
    """Standalone quarters; derive Q4 = FY - YTD_9M when missing."""
    items: dict[tuple, dict] = {}
    ytd9: dict[int, dict] = {}
    fy: dict[int, dict] = {}
    for (fy_, fq, ptype), r in revenue.items():
        if ptype == "Q_STANDALONE" and fq:
            items[(fy_, fq)] = {
                "period": f"FY{fy_}Q{fq}", "fiscal_year": fy_, "fiscal_quarter": fq,
                "value": r["value"], "status": r["status"],
                "source_document_id": r.get("source_document_id"),
            }
        elif ptype == "YTD_9M":
            ytd9[fy_] = r
        elif ptype == "FY":
            fy[fy_] = r
    for year, r in fy.items():
        if (year, 4) not in items and year in ytd9:
            q3 = items.get((year, 3))
            y = ytd9[year]
            if y.get("value") is not None:
                items[(year, 4)] = {
                    "period": f"FY{year}Q4", "fiscal_year": year, "fiscal_quarter": 4,
                    "value": r["value"] - y["value"],
                    "status": "CALCULATED",
                    "source_document_id": r.get("source_document_id"),
                }
    return [items[k] for k in sorted(items, key=lambda k: (k[0] or 0, k[1] or 0))]


def _year_ago(series: list[dict]) -> dict | None:
    if len(series) < 2:
        return None
    if series[-1].get("fiscal_quarter") is None:
        return series[-2] if series[-2].get("fiscal_year") == series[-1].get("fiscal_year", 0) - 1 else None
    q = series[-1]
    for s in series[-8:]:
        if s["fiscal_year"] == (q["fiscal_year"] or 0) - 1 and s["fiscal_quarter"] == q["fiscal_quarter"]:
            return s
    return None


def _latest_profit(profit: dict, frequency: str) -> dict | None:
    candidates = []
    for (fy, fq, ptype), r in profit.items():
        if frequency == "annual" and ptype == "FY":
            candidates.append(r)
        elif frequency == "quarterly" and ptype == "Q_STANDALONE":
            candidates.append(r)
    if not candidates:
        return None
    return max(candidates, key=lambda r: ((r["fiscal_year"] or 0), (r["fiscal_quarter"] or 0)))


def _total_revenue(segments: dict, frequency: str) -> float | None:
    """Sum of latest-revenue across segments (per chosen frequency)."""
    total = 0.0
    for seg in segments.values():
        s = _annual_series(seg["revenue"]) if frequency == "annual" else _quarterly_series(seg["revenue"], None)
        if s and s[-1].get("value") is not None:
            total += s[-1]["value"]
    return total or None


def _latest_sources(sources: dict) -> list[dict]:
    seen: dict[str, dict] = {}
    for s in sources.values():
        seen[s["source_document_id"]] = s
    return list(seen.values())[-3:]
