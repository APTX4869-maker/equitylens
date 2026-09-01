"""API integration tests against the golden fixture database.

These verify the /api/v1 contract (docs/07) returns REAL canonical data with
provenance — no mock values anywhere in the financial endpoints.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from equitylens.api.main import app
from equitylens.storage.duckdb_store import DuckDBStore


@pytest.fixture()
def client(company_db, monkeypatch):
    """Point the API at the golden fixture DB (built by the session fixture)."""
    monkeypatch.setattr("equitylens.api.routes.DuckDBStore", lambda: company_db)
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200


def test_company_identity(client):
    r = client.get("/api/v1/companies/AAPL")
    assert r.status_code == 200
    d = r.json()
    assert d["cik"] == "0000320193"
    assert d["name"] == "Apple Inc."
    assert d["source_freshness"], "source freshness must be present"


def test_facts_are_real_and_provenanced(client):
    r = client.get(
        "/api/v1/companies/AAPL/facts",
        params={"metrics": "REVENUE", "frequency": "annual"},
    )
    assert r.status_code == 200
    facts = r.json()["facts"]
    assert facts, "no facts returned"
    fy2025 = [f for f in facts if f["fiscal_year"] == 2025 and f["period_type"] == "FY"]
    assert fy2025 and fy2025[0]["value"] == pytest.approx(416_161_000_000, rel=1e-9)
    prov = fy2025[0]["provenance"]
    assert prov["source_url"] and "data.sec.gov" in prov["source_url"]
    assert prov["concept"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert prov["accession_number"]
    assert prov["form_type"] == "10-K"


def test_quarterly_cashflow_standalone_not_ytd(client):
    r = client.get(
        "/api/v1/companies/AAPL/facts",
        params={"metrics": "OPERATING_CASH_FLOW", "frequency": "quarterly"},
    )
    facts = r.json()["facts"]
    by_period = {f["period"]: f for f in facts}
    q2 = by_period.get("FY2026Q2")
    assert q2 is not None
    assert q2["value"] == pytest.approx(28_702_000_000, rel=1e-9)
    assert q2["status"] == "CALCULATED"
    assert q2["provenance"]["formula_id"] == "standalone_quarter.ytd_diff.v1"


def test_metrics_have_formula_and_inputs(client):
    r = client.get(
        "/api/v1/companies/MSFT/metrics",
        params={"metrics": "GROSS_MARGIN,REVENUE_GROWTH_YOY", "frequency": "quarterly", "limit": 4},
    )
    assert r.status_code == 200
    metrics = r.json()["metrics"]
    assert metrics
    gm = [m for m in metrics if m["metric"] == "GROSS_MARGIN"]
    assert gm and gm[-1]["formula_id"] == "gross_margin.v1"
    assert len(gm[-1]["input_fact_ids"]) == 2
    assert all(m["value"] is not None for m in metrics)


def test_overview_kpis_and_trends(client):
    r = client.get("/api/v1/companies/AAPL/overview")
    assert r.status_code == 200
    d = r.json()
    assert d["latest_period"]["fiscal_year"] >= 2025
    assert d["kpis"]["TTM_REVENUE"]["value"] == pytest.approx(466_823_000_000, rel=1e-6)
    assert len(d["trend"]["revenue"]["values"]) >= 8


def test_provenance_recursive_lineage(client):
    r = client.get("/api/v1/companies/AAPL/facts", params={"metrics": "REVENUE", "frequency": "annual"})
    cf_id = r.json()["facts"][0]["canonical_fact_id"]
    r = client.get(f"/api/v1/provenance/{cf_id}")
    assert r.status_code == 200
    tree = r.json()["tree"]
    kinds = {tree["kind"]}
    for p in tree["parents"]:
        kinds.add(p["kind"])
        for g in p.get("parents", []):
            kinds.add(g["kind"])
    assert kinds == {"canonical_fact", "raw_fact", "source_document"}


def test_sources_endpoint(client):
    r = client.get("/api/v1/companies/AAPL/facts", params={"metrics": "REVENUE", "frequency": "annual"})
    doc_id = r.json()["facts"][0]["provenance"]["source_document_id"]
    r = client.get(f"/api/v1/sources/{doc_id}")
    assert r.status_code == 200
    assert r.json()["source_url"].startswith("https://data.sec.gov")


def test_unsupported_ticker_404(client):
    r = client.get("/api/v1/companies/ZZZZ")
    assert r.status_code in (400, 404)


def test_segments_annual_aapl(client):
    r = client.get("/api/v1/companies/AAPL/segments", params={"frequency": "annual"})
    assert r.status_code == 200
    d = r.json()
    assert d["profit_disclosed"] is False
    assert d["total_revenue"] == pytest.approx(416_161_000_000, rel=1e-6)
    names = {s["name"] for s in d["segments"]}
    assert {"美洲", "欧洲", "大中华区", "日本", "亚太其他"} <= names
    am = next(s for s in d["segments"] if s["name"] == "美洲")
    assert am["latest"]["value"] == pytest.approx(178_353_000_000, rel=1e-9)
    assert am["share"] == pytest.approx(178_353 / 416_161, rel=1e-6)
    assert am["profitability"]["status"] == "NOT_DISCLOSED"
    assert am["sources"], "segment must carry source documents"


def test_segments_quarterly_msft_with_profit(client):
    r = client.get("/api/v1/companies/MSFT/segments", params={"frequency": "quarterly"})
    assert r.status_code == 200
    d = r.json()
    assert d["profit_disclosed"] is True
    cloud = next(s for s in d["segments"] if s["name"] == "智能云")
    # FY2026 Q4 derived from FY - YTD_9M
    q4 = [p for p in cloud["series"] if p["period"] == "FY2026Q4"]
    assert q4 and q4[0]["status"] == "CALCULATED"
    assert cloud["profitability"]["status"] == "DISCLOSED"
    assert cloud["profitability"]["value"] == pytest.approx(13_753_000_000, rel=1e-9)


def test_segments_product_view_aapl(client):
    r = client.get("/api/v1/companies/AAPL/segments", params={"kind": "product", "frequency": "annual"})
    assert r.status_code == 200
    d = r.json()
    iphone = next(s for s in d["segments"] if s["name"] == "iPhone")
    assert iphone["latest"]["value"] == pytest.approx(209_586_000_000, rel=1e-9)
