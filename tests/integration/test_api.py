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
