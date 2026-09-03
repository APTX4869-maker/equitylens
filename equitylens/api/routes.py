"""REST API routes — /api/v1/* (docs/07_API_CONTRACT.md)."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from equitylens.config import RAW_DIR
from equitylens.domain.companies import get_company
from equitylens.metrics.engine import MetricEngine
from equitylens.storage.duckdb_store import DuckDBStore

router = APIRouter(prefix="/api/v1")


def _store() -> DuckDBStore:
    s = DuckDBStore()
    s.connect()
    s.init_schema()
    return s


def _resolve_company(ticker: str):
    try:
        return get_company(ticker)
    except KeyError as exc:
        raise HTTPException(404, f"Unsupported or unknown ticker {ticker!r} (V0.x supports AAPL, MSFT)") from exc


def _facts_endpoint(store, company_id: str, metrics: list[str], frequency: str,
                    limit: int | None, view: str) -> list[dict]:
    engine = MetricEngine(store)
    out: list[dict] = []

    passthrough = ("REVENUE", "GROSS_PROFIT", "OPERATING_INCOME", "NET_INCOME",
                   "OPERATING_CASH_FLOW", "CAPITAL_EXPENDITURES", "DILUTED_EPS",
                   "BASIC_EPS", "DILUTED_WEIGHTED_AVG_SHARES", "BASIC_WEIGHTED_AVG_SHARES",
                   "PRETAX_INCOME", "INCOME_TAX_EXPENSE", "COST_OF_REVENUE")
    for m in metrics:
        if m in passthrough:
            points = engine.compute(m, company_id, frequency=frequency, limit=None, view=view)
            for p in points:
                prov = _provenance_ref(store, company_id, m,
                                       [p.canonical_fact_id] if p.canonical_fact_id else (p.input_fact_ids or []),
                                       p.period_end)
                out.append({
                    "metric": m,
                    "period": p.period_label,
                    "period_type": "Q_STANDALONE" if p.fiscal_quarter else "FY",
                    "fiscal_year": p.fiscal_year,
                    "fiscal_quarter": p.fiscal_quarter,
                    "period_end": p.period_end,
                    "value": p.value,
                    "unit": p.unit,
                    "status": p.status,
                    "canonical_fact_id": p.canonical_fact_id,
                    "provenance": prov,
                    "input_fact_ids": p.input_fact_ids or [],
                })
        else:
            # instant or direct canonical facts: latest-restated per period key
            facts = store.query(
                """
                SELECT canonical_fact_id, canonical_metric, period_type, fiscal_year,
                       fiscal_quarter, period_start, period_end, instant_date, value, unit,
                       status, mapping_rule_id, mapping_version, source_raw_fact_ids,
                       as_known_at, source_document_id
                FROM canonical_fact
                WHERE company_id = ? AND canonical_metric = ?
                ORDER BY fiscal_year, fiscal_quarter
                """,
                [company_id, m],
            )
            seen: dict[tuple, dict] = {}
            for f in facts:
                key = (f["fiscal_year"], f["fiscal_quarter"], f["period_type"])
                if key not in seen or (f.get("as_known_at") or "") > (seen[key].get("as_known_at") or ""):
                    seen[key] = f
            items = sorted(seen.values(), key=lambda f: (f["fiscal_year"] or 0, f["fiscal_quarter"] or 0))
            for f in items:
                out.append({
                    "metric": m,
                    "period": (f"FY{f['fiscal_year']}Q{f['fiscal_quarter']}" if f["fiscal_quarter"]
                               else f"FY{f['fiscal_year']}"),
                    "period_type": f["period_type"],
                    "fiscal_year": f["fiscal_year"],
                    "fiscal_quarter": f["fiscal_quarter"],
                    "period_start": f["period_start"],
                    "period_end": f["period_end"],
                    "instant_date": f["instant_date"],
                    "value": f["value"],
                    "unit": f["unit"],
                    "status": f["status"],
                    "canonical_fact_id": f["canonical_fact_id"],
                    "provenance": _provenance_ref_for_fact(store, f),
                    "input_fact_ids": json.loads(f["source_raw_fact_ids"] or "[]"),
                })
    if limit:
        out = out[-limit:]
    return out


def _provenance_ref_for_fact(store, f: dict) -> dict:
    raw_ids = json.loads(f.get("source_raw_fact_ids") or "[]")
    prov = {
        "source_document_id": f.get("source_document_id"),
        "provider": "SEC",
        "form_type": None,
        "accession_number": None,
        "filed_at": f.get("as_known_at"),
        "source_url": None,
        "concept": None,
        "unit": f.get("unit"),
        "mapping_version": f.get("mapping_version"),
        "formula_id": f.get("mapping_rule_id") if f.get("status") == "CALCULATED" else None,
        "status": f.get("status"),
    }
    if raw_ids:
        rows = store.query(
            f"SELECT raw_fact_id, concept, form_type, accession_number, filed_at, "
            f"source_document_id FROM raw_fact WHERE raw_fact_id IN ({','.join(['?'] * len(raw_ids))})",
            raw_ids,
        )
        if rows:
            r = rows[0]
            prov["concept"] = r["concept"]
            prov["form_type"] = r["form_type"]
            prov["accession_number"] = r["accession_number"]
            if r.get("filed_at"):
                prov["filed_at"] = r["filed_at"]
            if r.get("source_document_id"):
                src = store.query_one(
                    "SELECT source_url, fetched_at FROM source_document WHERE source_document_id = ?",
                    [r["source_document_id"]],
                )
                if src:
                    prov["source_url"] = src["source_url"]
                    prov["fetched_at"] = src["fetched_at"]
    return prov


def _provenance_ref(store, company_id, metric, input_ids, period_end) -> dict:
    if not input_ids:
        return {"status": None}
    f = store.query_one(
        "SELECT * FROM canonical_fact WHERE canonical_fact_id = ?", [input_ids[0]]
    )
    if not f:
        return {"status": None}
    return _provenance_ref_for_fact(store, f)


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/companies/{ticker}")
def company(ticker: str):
    company = _resolve_company(ticker)
    store = _store()
    cik = company.cik
    docs = store.query(
        "SELECT document_type, fetched_at, content_sha256, local_path, source_document_id "
        "FROM source_document WHERE company_id = ? ORDER BY fetched_at DESC LIMIT 5",
        [cik],
    )
    freshness = {}
    for d in docs:
        freshness[d["document_type"]] = {
            "fetched_at": d["fetched_at"],
            "sha256": d["content_sha256"][:16],
            "source_document_id": d["source_document_id"],
        }
    # enrich from the cached submissions snapshot (identity metadata only)
    sic_description = website = None
    subs_path = RAW_DIR / "sec" / cik / "submissions.json"
    if subs_path.exists():
        try:
            subs = json.loads(subs_path.read_text())
            sic_description = subs.get("sicDescription")
            website = subs.get("website")
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "ticker": company.ticker,
        "cik": company.cik,
        "name": company.name,
        "exchange": company.exchange,
        "fiscal_year_end": company.fiscal_year_end,
        "sic_description": sic_description,
        "website": website,
        "source_freshness": freshness,
    }


@router.get("/companies/{ticker}/facts")
def facts(
    ticker: str,
    metrics: str = Query("REVENUE,NET_INCOME", description="comma-separated canonical metrics"),
    frequency: str = Query("quarterly", pattern="^(annual|quarterly|ttm)$"),
    limit: int | None = Query(None, ge=1, le=100),
    view: str = Query("latest_restated", pattern="^(latest_restated|point_in_time)$"),
):
    company = _resolve_company(ticker)
    metric_list = [m.strip().upper() for m in metrics.split(",") if m.strip()]
    store = _store()
    if view == "point_in_time":
        raise HTTPException(501, "point_in_time view is not implemented yet in V0.1")
    data = _facts_endpoint(store, company.cik, metric_list, frequency, limit, view)
    return {"ticker": ticker, "frequency": frequency, "view": view, "facts": data}


@router.get("/companies/{ticker}/metrics")
def metrics(
    ticker: str,
    metrics: str = Query("REVENUE_GROWTH_YOY,GROSS_MARGIN,OPERATING_MARGIN,NET_MARGIN,FCF,FCF_MARGIN,NET_DEBT",
                        description="comma-separated derived metrics"),
    frequency: str = Query("quarterly", pattern="^(annual|quarterly|ttm)$"),
    limit: int | None = Query(None, ge=1, le=200),
):
    company = _resolve_company(ticker)
    engine = MetricEngine(_store())
    out = []
    for m in metrics.split(","):
        m = m.strip().upper()
        if not m:
            continue
        points = engine.compute(m, company.cik, frequency=frequency, limit=limit)
        for p in points:
            out.append({
                "metric": m,
                "period": p.period_label,
                "value": p.value,
                "unit": p.unit,
                "status": p.status,
                "formula_id": p.formula_id,
                "formula_version": p.formula_version,
                "input_fact_ids": p.input_fact_ids or [],
                "canonical_fact_id": p.canonical_fact_id,
                "fiscal_year": p.fiscal_year,
                "fiscal_quarter": p.fiscal_quarter,
                "period_end": p.period_end,
            })
    return {"ticker": ticker, "frequency": frequency, "metrics": out}


@router.get("/companies/{ticker}/segments")
def segments(
    ticker: str,
    kind: str = Query("segment", pattern="^(segment|product)$"),
    frequency: str = Query("annual", pattern="^(annual|quarterly)$"),
    limit: int | None = Query(None, ge=1, le=50),
):
    from equitylens.api.segments_service import get_segments

    company = _resolve_company(ticker)
    try:
        return get_segments(_store(), company.ticker, kind=kind, frequency=frequency, limit=limit)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/companies/{ticker}/overview")
def overview(ticker: str, mode: str = Query("latest_restated")):
    company = _resolve_company(ticker)
    store = _store()
    engine = MetricEngine(store)
    cik = company.cik

    kpis = {}
    for m in ("REVENUE", "OPERATING_CASH_FLOW", "CAPITAL_EXPENDITURES"):
        pts = engine.compute(m, cik, frequency="quarterly")
        if pts:
            series = [(p.period_end or "", p.value) for p in pts if p.value is not None]
            # TTM = trailing 4 standalone quarters
            last4 = [v for _, v in series[-4:]]
            if len(last4) == 4:
                kpis[f"TTM_{m}"] = {"value": sum(last4), "unit": "USD", "periods": [p for p, _ in series[-4:]]}
            latest = series[-1][1] if series else None
            kpis[f"{m}_LATEST"] = {"value": latest, "unit": "USD"}
    for m in ("GROSS_MARGIN", "OPERATING_MARGIN", "NET_MARGIN", "FCF_MARGIN"):
        pts = engine.compute(m, cik, frequency="quarterly")
        if pts and pts[-1].value is not None:
            kpis[m] = {"value": pts[-1].value, "unit": "ratio", "period": pts[-1].period_label}
    for m in ("FCF",):
        pts = engine.compute(m, cik, frequency="quarterly")
        series = [(p.period_end or "", p.value) for p in pts if p.value is not None]
        if len(series) >= 4:
            kpis["TTM_FCF"] = {"value": sum(v for _, v in series[-4:]), "unit": "USD"}
    nd = engine.compute("NET_DEBT", cik, frequency="quarterly")
    if nd:
        kpis["NET_DEBT"] = {"value": nd[-1].value, "unit": "USD", "period": nd[-1].period_label}

    trend = {}
    for m, key in (("REVENUE", "revenue"), ("REVENUE_GROWTH_YOY", "revenueGrowth"),
                   ("GROSS_MARGIN", "grossMargin"), ("OPERATING_MARGIN", "opMargin"),
                   ("FCF", "fcf")):
        try:
            pts = engine.compute(m, cik, frequency="quarterly")
        except ValueError:
            continue
        trend[key] = {
            "label": m,
            "values": [p.value for p in pts],
            "periods": [p.period_label for p in pts],
        }

    # latest fiscal period
    latest = store.query_one(
        "SELECT fiscal_year, fiscal_quarter, period_end FROM canonical_fact "
        "WHERE company_id = ? AND period_type = 'Q_STANDALONE' AND fiscal_quarter IS NOT NULL "
        "ORDER BY fiscal_year DESC, fiscal_quarter DESC LIMIT 1",
        [cik],
    )
    return {
        "ticker": ticker,
        "latest_period": latest,
        "kpis": kpis,
        "trend": trend,
        "provenance_available": True,
    }


@router.get("/provenance/{entity_id}")
def provenance(entity_id: str, depth: int = Query(3, ge=1, le=6)):
    store = _store()
    node = _build_provenance(store, entity_id, depth, set())
    if node is None:
        raise HTTPException(404, f"Unknown entity {entity_id}")
    return {"entity_id": entity_id, "kind": node["kind"], "tree": node}


def _build_provenance(store, entity_id: str, depth: int, visited: set) -> dict | None:
    if depth <= 0 or entity_id in visited:
        return None
    visited = visited | {entity_id}
    cf = store.query_one("SELECT * FROM canonical_fact WHERE canonical_fact_id = ?", [entity_id])
    if cf:
        raw_ids = json.loads(cf.get("source_raw_fact_ids") or "[]")
        parents = []
        for rid in raw_ids:
            p = _build_provenance(store, rid, depth - 1, visited)
            if p:
                parents.append(p)
            else:
                raw = store.query_one("SELECT * FROM raw_fact WHERE raw_fact_id = ?", [rid])
                if raw:
                    parents.append(_raw_node(store, raw, depth - 1, visited))
        return {
            "entity_id": entity_id,
            "kind": "canonical_fact",
            "label": cf.get("canonical_metric"),
            "fields": {
                "metric": cf.get("canonical_metric"),
                "period_type": cf.get("period_type"),
                "fiscal_year": cf.get("fiscal_year"),
                "fiscal_quarter": cf.get("fiscal_quarter"),
                "period_end": cf.get("period_end"),
                "value": cf.get("value"),
                "unit": cf.get("unit"),
                "status": cf.get("status"),
                "mapping_rule_id": cf.get("mapping_rule_id"),
                "mapping_version": cf.get("mapping_version"),
                "source_document_id": cf.get("source_document_id"),
            },
            "parents": parents,
        }
    raw = store.query_one("SELECT * FROM raw_fact WHERE raw_fact_id = ?", [entity_id])
    if raw:
        return _raw_node(store, raw, depth, visited)
    src = store.query_one("SELECT * FROM source_document WHERE source_document_id = ?", [entity_id])
    if src:
        return {
            "entity_id": entity_id,
            "kind": "source_document",
            "label": src.get("document_type"),
            "fields": {
                "provider": src.get("provider"),
                "document_type": src.get("document_type"),
                "form_type": src.get("form_type"),
                "accession_number": src.get("accession_number"),
                "source_url": src.get("source_url"),
                "filed_at": src.get("filed_at"),
                "fetched_at": src.get("fetched_at"),
                "content_sha256": src.get("content_sha256"),
                "local_path": src.get("local_path"),
            },
            "parents": [],
        }
    return None


def _raw_node(store, raw: dict, depth: int, visited: set) -> dict:
    src = store.query_one("SELECT * FROM source_document WHERE source_document_id = ?",
                          [raw.get("source_document_id")])
    parents = []
    if src:
        p = _build_provenance(store, src.get("source_document_id"), depth - 1, visited)
        if p:
            parents.append(p)
    return {
        "entity_id": raw.get("raw_fact_id"),
        "kind": "raw_fact",
        "label": f"{raw.get('taxonomy')}:{raw.get('concept')}",
        "fields": {
            "taxonomy": raw.get("taxonomy"),
            "concept": raw.get("concept"),
            "unit": raw.get("unit"),
            "raw_value": raw.get("raw_value"),
            "start_date": raw.get("start_date"),
            "end_date": raw.get("end_date"),
            "instant_date": raw.get("instant_date"),
            "form_type": raw.get("form_type"),
            "accession_number": raw.get("accession_number"),
            "filed_at": raw.get("filed_at"),
            "source_document_id": raw.get("source_document_id"),
        },
        "parents": parents,
    }


@router.get("/sources/{source_document_id}")
def source(source_document_id: str):
    store = _store()
    row = store.query_one(
        "SELECT * FROM source_document WHERE source_document_id = ?", [source_document_id]
    )
    if not row:
        raise HTTPException(404, f"Unknown source document {source_document_id}")
    return row


@router.get("/companies/{ticker}/management")
def management(ticker: str):
    from equitylens.domain.management_score import capital_allocation, management_scorecard

    company = _resolve_company(ticker)
    store = _store()
    cik = company.cik

    execs = store.query(
        """WITH latest_comp AS (
             SELECT c.executive_id, c.fiscal_year AS latest_year,
                    c.total_compensation AS latest_total,
                    ROW_NUMBER() OVER (PARTITION BY c.executive_id ORDER BY c.fiscal_year DESC) AS rn
             FROM executive_compensation c
           )
           SELECT e.name, e.title, e.executive_id, l.latest_year, l.latest_total
           FROM executive e
           LEFT JOIN latest_comp l ON l.executive_id = e.executive_id AND l.rn = 1
           WHERE e.company_id = ?
           ORDER BY l.latest_total DESC NULLS LAST""",
        [cik],
    )
    comp = store.query(
        """SELECT e.name, c.fiscal_year, c.salary, c.stock_awards, c.non_equity_incentive,
                  c.all_other, c.total_compensation
           FROM executive_compensation c JOIN executive e ON e.executive_id = c.executive_id
           WHERE c.company_id = ? ORDER BY c.fiscal_year DESC, e.name""",
        [cik],
    )
    board = store.query(
        """SELECT name, occupation, age, director_since, independent FROM board_member
           WHERE company_id = ? ORDER BY name""",
        [cik],
    )
    insider = store.query(
        """SELECT insider_name, officer_title, transaction_date, transaction_code, security_title,
                  shares, price_per_share, shares_owned_after, filed_at, accession_number, source_url
           FROM insider_transaction WHERE company_id = ?
           ORDER BY transaction_date DESC LIMIT 20""",
        [cik],
    )
    alloc = capital_allocation(store, cik)
    scorecard = management_scorecard(store, cik, ticker)

    leaders = []
    for e in execs:
        leaders.append({
            "name": e["name"], "title": e["title"],
            "latest_fy": e["latest_year"],
            "total_compensation": e["latest_total"],
            "source": "DEF 14A",
        })
    independent = [b for b in board if (b["independent"] or "").lower() in ("yes", "true", "1", "independent", "independen")]
    governance = {
        "board_size": len(board),
        "independent_count": len(independent),
        "director_sources": ["DEF 14A"],
        "avg_comp_committee": None,
    }
    alignment = {}
    if alloc.get("latest"):
        l = alloc["latest"]
        alignment = {
            "gross_buybacks": l.get("gross_buybacks"),
            "sbc": l.get("sbc"),
            "net_buybacks": l.get("net_buybacks"),
            "dividends": l.get("dividends"),
            "share_count_5y_change": alloc.get("summary", {}).get("share_count_5y_change"),
        }
    return {
        "ticker": ticker,
        "leaders": leaders,
        "compensation_table": comp,
        "board": [dict(b, **{"source": "DEF 14A"}) for b in board],
        "governance": governance,
        "capital_allocation": alloc,
        "shareholder_alignment": alignment,
        "insider_transactions": insider,
        "scorecard": scorecard,
        "promises": {"items": [], "status": "PENDING_M7", "note": "Promise Tracker 数据模型已就绪；Earnings-call 证据解析属 M7"},
        "watch_items": _management_watch_items(ticker, alloc, scorecard),
    }


def _management_watch_items(ticker: str, alloc: dict, scorecard: dict) -> list[dict]:
    items = []
    summary = alloc.get("summary") or {}
    latest = alloc.get("latest") or {}
    fc, cc = summary.get("fcf_cagr"), summary.get("capex_cagr")
    if fc is not None and cc is not None and cc > fc:
        items.append({
            "topic": "资本开支增速高于自由现金流",
            "signal": f"FCF CAGR {fc*100:.1f}% vs CapEx CAGR {cc*100:.1f}%",
            "next_check": "下一份 10-K/10-Q",
        })
    sc5 = summary.get("share_count_5y_change")
    if sc5 is not None and sc5 > 0:
        items.append({"topic": "股本净增长", "signal": f"5 年稀释股本 +{sc5*100:.1f}%", "next_check": "10-K 股本表"})
    if scorecard.get("overall_score") is None:
        items.append({
            "topic": "管理层评分证据不足",
            "signal": f"证据覆盖率 {scorecard['coverage']*100:.0f}%（需 ≥{scorecard['minimum_coverage']*100:.0f}%）",
            "next_check": "接入 DEF 14A 更多章节与 Earnings Call（M7）",
        })
    return items[:5]


@router.get("/companies/{ticker}/valuation/default")
def valuation_default(ticker: str):
    from equitylens.valuation.service import default_valuation

    company = _resolve_company(ticker)
    return default_valuation(_store(), company.cik, company.ticker)


@router.post("/companies/{ticker}/valuation/run")
def valuation_run(ticker: str, payload: dict):
    from equitylens.valuation.service import run_custom

    company = _resolve_company(ticker)
    try:
        return run_custom(_store(), company.cik, company.ticker, payload)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/companies/{ticker}/valuation/reverse-dcf")
def valuation_reverse(ticker: str, payload: dict):
    from equitylens.valuation.service import reverse_dcf

    company = _resolve_company(ticker)
    if "target_price" not in payload:
        raise HTTPException(400, "target_price is required (market quote or user input)")
    return reverse_dcf(_store(), company.cik, company.ticker, payload)


@router.get("/companies/{ticker}/valuation/runs")
def valuation_runs(ticker: str, limit: int = 10):
    company = _resolve_company(ticker)
    rows = _store().query(
        "SELECT valuation_run_id, model_version, run_at, assumption_set_id, warnings_json "
        "FROM valuation_run WHERE company_id = ? ORDER BY run_at DESC LIMIT ?",
        [company.cik, limit],
    )
    return {"ticker": ticker, "runs": rows}


@router.get("/companies/{ticker}/market/quote")
def market_quote(ticker: str):
    """Latest synced quote + deterministic derived market facts (M8).

    Reads only the local store; a missing sync is an explicit UNAVAILABLE
    state with the command hint — never a fabricated price.
    """
    from equitylens.market.service import quote_block

    company = _resolve_company(ticker)
    return quote_block(_store(), company.cik, company.ticker)


@router.get("/companies/{ticker}/risks")
def company_risks(ticker: str):
    from equitylens.domain.risks import risk_signals

    company = _resolve_company(ticker)
    return risk_signals(_store(), company.cik, company.ticker)


@router.get("/companies/{ticker}/moat")
def company_moat(ticker: str):
    """Moat evidence from SEC numbers only; qualitative gaps are explicit (M8.5)."""
    from equitylens.domain.moat import moat_signals

    company = _resolve_company(ticker)
    return moat_signals(_store(), company.cik, company.ticker)


@router.post("/research/ask")
def research_ask(payload: dict):
    """Evidence-first research Q&A (deterministic engine; LLM pluggable later)."""
    from equitylens.research.engine import ask

    ticker = (payload.get("ticker") or "AAPL").upper()
    question = payload.get("question") or ""
    if not question.strip():
        raise HTTPException(400, "question is required")
    company = _resolve_company(ticker)
    return ask(_store(), company.cik, company.ticker, question)


@router.get("/companies/{ticker}/promises")
def company_promises(ticker: str):
    """Promise Tracker data model (items pending Earnings-call evidence, M7.5)."""
    company = _resolve_company(ticker)
    rows = _store().query(
        "SELECT promise_id, promise_text, normalized_claim, verification_metrics, "
        "verification_deadline, status, speaker, statement_date, source_evidence_id "
        "FROM management_promise WHERE company_id = ? ORDER BY statement_date DESC",
        [company.cik],
    )
    return {
        "ticker": ticker,
        "status": "READY",
        "sample_note": "数据模型已就绪；Earnings-call/prepared-remarks 证据解析在后续版本启用",
        "items": rows,
        "delivery_rate": None,
    }
