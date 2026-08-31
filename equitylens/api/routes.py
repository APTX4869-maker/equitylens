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
