"""API integration tests against the golden fixture database.

These verify the /api/v1 contract (docs/07) returns REAL canonical data with
provenance — no mock values anywhere in the financial endpoints.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from equitylens.api.main import app
from equitylens.storage.duckdb_store import DuckDBStore


@pytest.fixture()
def client(company_db, monkeypatch):
    """Point the API at the golden fixture DB (built by the session fixture)."""
    monkeypatch.setattr("equitylens.api.routes.DuckDBStore", lambda: company_db)
    monkeypatch.setattr(
        "equitylens.market.age._now_utc",
        lambda: datetime(2026, 9, 4, tzinfo=timezone.utc),
    )
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


def test_derived_metrics_have_own_identity_and_unit(client):
    """D09: derived results carry their own unit and a provenance root of all
    inputs — they must not impersonate the last input fact's identity/unit."""
    r = client.get("/api/v1/companies/AAPL/metrics",
                   params={"metrics": "REVENUE", "frequency": "ttm", "limit": 1})
    m = r.json()["metrics"][-1]
    assert m["value"] == pytest.approx(466_823_000_000, rel=1e-6)
    assert m["unit"] == "USD"
    assert m["canonical_fact_id"] is None  # derived, not the last quarter
    assert len(m["input_fact_ids"]) == 4  # all four inputs expandable
    assert m["frequency"] == "ttm"
    assert m["status"] == "OK"
    assert m["period_start"]
    assert m["period_end"]
    assert m["missing_reason"] is None

    r = client.get("/api/v1/companies/AAPL/metrics",
                   params={"metrics": "GROSS_MARGIN", "frequency": "quarterly", "limit": 1})
    gm = r.json()["metrics"][-1]
    assert gm["unit"] == "ratio"  # a ratio must not inherit USD
    assert gm["canonical_fact_id"] is None
    assert len(gm["input_fact_ids"]) == 2

    r = client.get("/api/v1/companies/MSFT/metrics",
                   params={"metrics": "NET_DEBT", "frequency": "quarterly"})
    nd = r.json()["metrics"][-1]
    assert nd["unit"] == "USD"
    assert len(nd["input_fact_ids"]) >= 4  # full add/subtract bridge


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
    assert d["kpis"]["TTM_REVENUE"]["result_id"].startswith("derived.v2.")
    assert d["kpis"]["TTM_REVENUE"]["metric"] == "REVENUE"
    assert d["trend"]["grossMargin"]["unit"] == "ratio"
    assert len(d["trend"]["revenue"]["values"]) >= 8
    provenance = client.get(f"/api/v1/provenance/{d['kpis']['TTM_REVENUE']['result_id']}")
    assert provenance.status_code == 200
    assert provenance.json()["tree"]["fields"]["value"] == pytest.approx(466_823_000_000, rel=1e-6)


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


def test_management_endpoint_aapl(client):
    r = client.get("/api/v1/companies/AAPL/management")
    assert r.status_code == 200
    d = r.json()
    tim = next(l for l in d["leaders"] if l["name"] == "Tim Cook")
    assert tim["total_compensation"] == pytest.approx(74_294_811, rel=1e-9)
    assert d["governance"]["board_size"] == 9
    assert d["capital_allocation"]["latest"]["gross_buybacks"] == pytest.approx(90_711_000_000, rel=1e-9)
    assert d["scorecard"]["overall_score"] is None  # evidence coverage below threshold
    assert d["insider_transactions"], "Form 4 transactions present"
    assert d["promises"]["status"] == "PENDING_M7"


def test_management_endpoint_msft(client):
    r = client.get("/api/v1/companies/MSFT/management")
    d = r.json()
    satya = next(l for l in d["leaders"] if l["name"] == "Satya Nadella")
    assert satya["total_compensation"] == pytest.approx(96_496_790, rel=1e-9)


def test_market_quote_endpoint_ok_with_derived(client):
    """Synced quotes come back with source + deterministic derived facts."""
    r = client.get("/api/v1/companies/AAPL/market/quote")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "OK"
    assert d["quote"]["source_url"].startswith("https://api.nasdaq.com")
    assert d["quote"]["observed_at"], "provider-reported observation time present"
    assert d["derived"]["market_cap"] > 0
    assert d["derived"]["pe_ttm"] > 0
    assert d["derived"]["pe_ttm_formula"] == "pe_ttm.v1"


def test_market_quote_in_valuation_default(client):
    r = client.get("/api/v1/companies/AAPL/valuation/default")
    d = r.json()
    market = d["market"]
    assert market["status"] == "OK"
    assert market["quote"]["price"] > 0
    assert "price_vs_fair_pct" in market["derived"]


def test_default_valuation_exposes_complete_assumption_metadata(client):
    response = client.get("/api/v1/companies/AAPL/valuation/default")
    assert response.status_code == 200
    body = response.json()
    inputs = body["assumptions"]["inputs"]
    meta = body["assumptions"]["meta"]
    assert set(inputs) <= set(meta)
    assert meta["revenue_growth"]["version"]
    assert meta["revenue_growth"]["reason"]
    assert meta["op_margin_end"]["rule"]
    assert meta["terminal_growth"]["source_type"] == "config_assumption"
    assert meta["shares"]["basis"] == "FY diluted weighted-average shares"
    for key in ("bear", "base", "bull"):
        scenario = body["scenarios"][key]
        assert scenario["story"]
        assert isinstance(scenario["changed_fields"], list)
        assert "capex_pct" in scenario["inputs"]
        assert "terminal_roic" in scenario["inputs"]


def test_user_override_metadata_clears_fact_identity_and_share_basis_guess(client):
    response = client.post(
        "/api/v1/companies/AAPL/valuation/run",
        json={"persist": False, "assumptions": {"shares": 10, "wacc": 0.12}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["assumptions"]["inputs"]["share_basis_label"] == "user-supplied share count"
    assert body["assumptions"]["meta"]["shares"]["basis"] == "user-supplied share count"
    for field in ("shares", "wacc"):
        item = body["assumptions"]["meta"][field]
        assert item["source_type"] == "user_override"
        assert item["source_ids"] == []
        assert item["version"] == "user-input.v1"


@pytest.mark.parametrize("bad", [
    {"tax_rate": 1.5},
    {"op_margin_end": 2.0},
    {"revenue_growth": [-1.2, -1.2, -1.2, -1.2, -1.2]},
    {"revenue_growth": [0.05, 0.05]},
    {"terminal_roic": 0.0},
])
def test_valuation_run_invalid_input_400_no_write(client, company_db, bad):
    """V01: invalid inputs return a structured client error and write nothing."""
    before = company_db.query("SELECT count(*) n FROM valuation_run")[0]["n"]
    r = client.post("/api/v1/companies/AAPL/valuation/run", json={"assumptions": bad})
    assert r.status_code == 400
    after = company_db.query("SELECT count(*) n FROM valuation_run")[0]["n"]
    assert after == before


def test_valuation_response_fingerprints_complete_executed_inputs(client):
    """V03/V05: the response carries a deterministic fingerprint of the COMPLETE
    executed inputs, recomputable from the returned input object; a WACC-only
    change must change it."""
    from equitylens.valuation.service import valuation_input_fingerprint

    a = client.post("/api/v1/companies/AAPL/valuation/run",
                    json={"persist": False, "assumptions": {"wacc": 0.10}}).json()
    b = client.post("/api/v1/companies/AAPL/valuation/run",
                    json={"persist": False, "assumptions": {"wacc": 0.11}}).json()
    assert a["ticker"] == "AAPL"
    assert a["input_fingerprint"] != b["input_fingerprint"]
    assert a["input_fingerprint"] == valuation_input_fingerprint(a["assumptions"]["inputs"])
    # every editable field is present in the complete input object
    for k in ("revenue_base", "revenue_growth", "op_margin_start", "op_margin_end",
              "tax_rate", "da_pct", "capex_pct", "nwc_pct", "wacc",
              "terminal_growth", "terminal_roic", "net_cash", "shares"):
        assert k in a["assumptions"]["inputs"]


def test_valuation_run_structured_error_body(client, company_db):
    """V01: a domain validation error returns {"error": {code, field, message}}
    (not a bare string) and writes no run."""
    before = company_db.query("SELECT count(*) n FROM valuation_run")[0]["n"]
    r = client.post("/api/v1/companies/AAPL/valuation/run",
                    json={"persist": False, "assumptions": {"capex_pct": -0.2}})
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == "INVALID_ASSUMPTION"
    assert body["error"]["field"] == "capex_pct"
    assert body["error"]["message"]
    after = company_db.query("SELECT count(*) n FROM valuation_run")[0]["n"]
    assert after == before


def test_default_valuation_does_not_persist_run(client, company_db):
    """V05: GET /default is a preview and must not add a valuation_run."""
    before = company_db.query("SELECT count(*) n FROM valuation_run")[0]["n"]
    r = client.get("/api/v1/companies/AAPL/valuation/default")
    assert r.status_code == 200
    after = company_db.query("SELECT count(*) n FROM valuation_run")[0]["n"]
    assert after == before


def test_saved_run_reads_back_verbatim(client):
    """V05: a saved run can be read back with its persisted inputs/output."""
    r = client.post("/api/v1/companies/AAPL/valuation/run",
                    json={"persist": True, "assumptions": {"wacc": 0.12}})
    assert r.status_code == 200
    run_id = r.json()["valuation_run_id"]
    assert run_id
    detail = client.get(f"/api/v1/companies/AAPL/valuation/runs/{run_id}")
    assert detail.status_code == 200
    d = detail.json()
    assert d["assumptions"]["inputs"]["wacc"] == pytest.approx(0.12)
    assert d["output"]["fair_value_per_share"] == pytest.approx(
        r.json()["result"]["fair_value_per_share"])


def test_saved_run_reads_back_full_scenarios_sensitivity(client, company_db):
    """V05: a saved run persists the complete executed inputs, fingerprint,
    scenarios, sensitivity, and model-quality block — read back verbatim."""
    r = client.post("/api/v1/companies/AAPL/valuation/run",
                    json={"persist": True, "assumptions": {"wacc": 0.12}})
    assert r.status_code == 200
    body = r.json()
    run_id = body["valuation_run_id"]
    assert run_id

    detail = client.get(f"/api/v1/companies/AAPL/valuation/runs/{run_id}")
    assert detail.status_code == 200
    d = detail.json()
    assert d["status"] == "complete"
    assert d["input_fingerprint"] == body["input_fingerprint"]
    # every scenario status/output, sensitivity cells, and model-quality survive
    assert d["scenarios"]["base"]["result"] is not None
    assert d["scenarios"]["bear"]["result"]["fair_value_per_share"] == pytest.approx(
        body["scenarios"]["bear"]["result"]["fair_value_per_share"])
    assert d["sensitivity"]["rows"], "sensitivity cells persisted"
    assert d["model_quality"]["terminal_value_share"] is not None
    assert d["model_version"] == "fcff_dcf.v2"
    assert d["output"]["terminal_forecast"] == body["result"]["terminal_forecast"]
    source_ids = d["assumptions"].get("source_fact_ids")
    assert source_ids, "complete run must freeze the canonical fact identities used"
    assert source_ids["revenue_base"]
    assert source_ids["op_margin"]
    assert source_ids["shares"]
    frozen_ids = sorted({fact_id for ids in source_ids.values() for fact_id in ids})
    resolved = company_db.query(
        f"SELECT canonical_fact_id FROM canonical_fact WHERE canonical_fact_id IN "
        f"({','.join('?' for _ in frozen_ids)})",
        frozen_ids,
    )
    assert {row["canonical_fact_id"] for row in resolved} == set(frozen_ids)


def test_legacy_run_reads_as_incomplete(client, company_db):
    """V05: a historical v1 run without the new columns is returned as
    legacy/incomplete with its stored v1 output, never reinterpreted."""
    company_db.connect()
    company_db._conn.execute(
        """INSERT INTO valuation_run
           (valuation_run_id, company_id, model_name, model_version, run_at,
            assumption_set_id, fact_snapshot_json, output_json, warnings_json)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        ["run_legacy_v1", "0000320193", "FCFF_DCF", "fcff_dcf.v1",
         "2026-01-01T00:00:00", "aset_legacy",
         '{"inputs": {}, "meta": {}}',
         '{"fair_value_per_share": 100.0}', "[]"],
    )
    detail = client.get("/api/v1/companies/AAPL/valuation/runs/run_legacy_v1")
    assert detail.status_code == 200
    d = detail.json()
    assert d["status"] == "legacy/incomplete"
    assert d["output"]["fair_value_per_share"] == 100.0
    assert d["scenarios"] is None or d["scenarios"]["base"] is None


def test_all_new_valuation_paths_report_v2_terminal_contract(client):
    """P02: default, custom, scenarios and reverse DCF share the v2 method."""
    default = client.get("/api/v1/companies/AAPL/valuation/default").json()
    custom = client.post(
        "/api/v1/companies/AAPL/valuation/run",
        json={"persist": False, "assumptions": default["assumptions"]["inputs"]},
    ).json()
    reverse = client.post(
        "/api/v1/companies/AAPL/valuation/reverse-dcf",
        json={"target_price": 300.0, "assumptions": default["assumptions"]["inputs"]},
    ).json()

    for response in (default, custom):
        assert response["model_version"] == "fcff_dcf.v2"
        assert response["result"]["model_version"] == "fcff_dcf.v2"
        assert response["result"]["terminal_forecast"]["definition"]
        assert response["assumptions"]["inputs"]["terminal_roic"] > 0
        for scenario in response["scenarios"].values():
            if scenario["result"] is not None:
                assert scenario["result"]["model_version"] == "fcff_dcf.v2"
                assert scenario["result"]["terminal_forecast"]["definition"]

    assert reverse["model_version"] == "fcff_dcf.v2"
    assert reverse["fixed_assumptions"]["terminal_roic"] == pytest.approx(
        default["assumptions"]["inputs"]["terminal_roic"]
    )


def test_derived_metric_has_resolvable_result_identity(client):
    """D09: a derived metric carries a stable result id that resolves through
    /provenance to a root with its value/frequency/formula and ALL inputs."""
    r = client.get("/api/v1/companies/AAPL/metrics",
                   params={"metrics": "FCF_MARGIN", "frequency": "ttm", "limit": 1})
    assert r.status_code == 200
    m = r.json()["metrics"][0]
    assert m["result_id"], "derived metric must carry a stable result identity"

    p = client.get(f"/api/v1/provenance/{m['result_id']}")
    assert p.status_code == 200
    node = p.json()["tree"]
    assert node["kind"] == "metric_value"
    fields = node["fields"]
    assert fields["metric"] == "FCF_MARGIN"
    assert fields["frequency"] == "ttm"
    assert fields["value"] == m["value"]
    assert fields["formula_id"] == m["formula_id"]
    assert fields["input_fact_ids"] == m["input_fact_ids"]
    assert len(node["parents"]) == len(m["input_fact_ids"])
    assert node["parents"][0]["kind"] == "canonical_fact"


def test_derived_result_identity_binds_value_formula_and_inputs(client):
    """D09: an identity must change if any part of the derived result changes.

    Period-only identities collide across restatements and can later resolve to a
    different card. The identity payload therefore binds value, formula and the
    complete ordered input list.
    """
    from equitylens.metrics.engine import MetricPoint, derived_result_id

    base = MetricPoint(
        metric="FCF_MARGIN", value=0.25, unit="ratio", status="CALCULATED",
        formula_id="fcf_margin.v2", formula_version="fcf_margin.v2",
        input_fact_ids=["ocf-a", "capex-a", "revenue-a"],
        period_label="FY2026Q2", frequency="ttm", period_start="2025-07-01",
        period_end="2026-06-30", fiscal_year=2026, fiscal_quarter=2,
    )
    restated = MetricPoint(**{**base.__dict__, "value": 0.24,
                              "input_fact_ids": ["ocf-b", "capex-a", "revenue-a"]})

    first = derived_result_id("0000320193", base)
    second = derived_result_id("0000320193", restated)
    assert first != second

    # The self-contained identity resolves the original root without asking the
    # metric engine to recompute today's latest-restated result.
    p = client.get(f"/api/v1/provenance/{first}")
    assert p.status_code == 200
    fields = p.json()["tree"]["fields"]
    assert fields["value"] == pytest.approx(0.25)
    assert fields["input_fact_ids"] == ["ocf-a", "capex-a", "revenue-a"]


def _save_v2_run(client, assumptions=None):
    response = client.post(
        "/api/v1/companies/AAPL/valuation/run",
        json={"persist": True, "assumptions": assumptions or {}},
    )
    assert response.status_code == 200
    return response.json()


def test_plan_requires_traceable_run_and_derives_reference(client):
    """P06: the server derives a plan value from one saved run/scenario."""
    arbitrary = client.post(
        "/api/v1/companies/AAPL/valuation/plans",
        json={"reference_value": 100.0, "reference_source": "base_dcf",
              "margin_of_safety": 0.2},
    )
    assert arbitrary.status_code == 400

    run = _save_v2_run(client)
    response = client.post(
        "/api/v1/companies/AAPL/valuation/plans",
        json={
            "valuation_run_id": run["valuation_run_id"], "scenario_key": "base",
            "name": "保守", "margin_of_safety": 0.2,
            "notes": "等待服务收入验证", "conditions_to_verify": ["下一季服务收入继续增长"],
        },
    )
    assert response.status_code == 200
    plan = response.json()
    expected = run["scenarios"]["base"]["result"]["fair_value_per_share"]
    assert plan["reference_value"] == pytest.approx(expected)
    assert plan["reference_price"] == pytest.approx(expected * 0.8)
    assert plan["valuation_run_id"] == run["valuation_run_id"]
    assert plan["scenario_key"] == "base"
    assert plan["conditions_to_verify"] == ["下一季服务收入继续增长"]
    assert plan["review_status"] == "current"
    assert plan["source_filing_as_of"]
    assert plan["source_quote_observed_at"]

    detail = client.get(f"/api/v1/companies/AAPL/valuation/plans/{plan['plan_id']}")
    assert detail.status_code == 200
    assert detail.json()["notes"] == "等待服务收入验证"
    assert detail.json()["conditions_to_verify"] == ["下一季服务收入继续增长"]


def test_plan_margin_validation_and_nonpositive_value(client):
    run = _save_v2_run(client)
    common = {"valuation_run_id": run["valuation_run_id"], "scenario_key": "base"}
    assert client.post("/api/v1/companies/AAPL/valuation/plans",
                       json={**common, "margin_of_safety": -0.1}).status_code == 400
    assert client.post("/api/v1/companies/AAPL/valuation/plans",
                       json={**common, "margin_of_safety": 1.0}).status_code == 400

    negative = _save_v2_run(client, {
        "op_margin_start": -0.5, "op_margin_end": -0.5,
        "da_pct": 0.0, "capex_pct": 0.1, "net_cash": 0.0,
    })
    response = client.post(
        "/api/v1/companies/AAPL/valuation/plans",
        json={"valuation_run_id": negative["valuation_run_id"],
              "scenario_key": "base", "margin_of_safety": 0.2},
    )
    assert response.status_code == 200
    assert response.json()["reference_price"] is None
    assert "不生成可买入参考价" in response.json()["reference_price_reason"]
    detail = client.get(
        f"/api/v1/companies/AAPL/valuation/plans/{response.json()['plan_id']}"
    ).json()
    assert detail["reference_price_reason"] == response.json()["reference_price_reason"]


def test_plan_copy_compare_and_company_isolation(client):
    run = _save_v2_run(client)
    first = client.post(
        "/api/v1/companies/AAPL/valuation/plans",
        json={"valuation_run_id": run["valuation_run_id"], "scenario_key": "base",
              "margin_of_safety": 0.2, "name": "原方案"},
    ).json()
    copied_response = client.post(
        f"/api/v1/companies/AAPL/valuation/plans/{first['plan_id']}/copy",
        json={"name": "复制方案", "margin_of_safety": 0.3},
    )
    assert copied_response.status_code == 200
    copied = copied_response.json()
    assert copied["parent_plan_id"] == first["plan_id"]
    assert copied["version"] == first["version"] + 1
    assert copied["reference_price"] == pytest.approx(copied["reference_value"] * 0.7)

    compared = client.get(
        "/api/v1/companies/AAPL/valuation/plans/compare",
        params={"ids": f"{first['plan_id']},{copied['plan_id']}"},
    )
    assert compared.status_code == 200
    assert "margin_of_safety" in compared.json()["changed_fields"]

    assert client.get(
        f"/api/v1/companies/MSFT/valuation/plans/{first['plan_id']}"
    ).status_code == 404


def test_plan_fields_survive_store_restart(tmp_path):
    """P06: plan source, notes, conditions and review state are persisted data."""
    import json as _json

    from equitylens.valuation.service import create_plan, get_plan

    path = tmp_path / "plans.duckdb"
    store = DuckDBStore(path)
    store.connect()
    store.init_schema()
    store._conn.execute(
        """INSERT INTO valuation_run
           (valuation_run_id, company_id, model_name, model_version, run_at,
            assumption_set_id, fact_snapshot_json, output_json, warnings_json,
            input_fingerprint, scenarios_json, sensitivity_json, model_quality_json)
           VALUES (?, ?, 'FCFF_DCF', 'fcff_dcf.v2', CURRENT_TIMESTAMP,
                   'aset-restart', ?, '{}', '[]', ?, ?, '{}', '{}')""",
        ["run-restart", "TEST", _json.dumps({"source_fact_ids": {}}), "fp-restart",
         _json.dumps({"base": {"status": "OK", "inputs": {"wacc": 0.1},
                                "result": {"fair_value_per_share": 100.0}}})],
    )
    created = create_plan(store, "TEST", "TEST", {
        "valuation_run_id": "run-restart", "scenario_key": "base",
        "margin_of_safety": 0.25, "notes": "restart note",
        "conditions_to_verify": ["condition A"],
    })
    store.close()

    reopened = DuckDBStore(path)
    reopened.connect()
    reopened.init_schema()
    loaded = get_plan(reopened, "TEST", created["plan_id"])
    reopened.close()
    assert loaded is not None
    assert loaded["reference_price"] == pytest.approx(75.0)
    assert loaded["notes"] == "restart note"
    assert loaded["conditions_to_verify"] == ["condition A"]
    assert loaded["source_input_fingerprint"] == "fp-restart"
    assert loaded["review_status"] == "current"


def test_copying_review_required_plan_preserves_review_state(client, company_db):
    run = _save_v2_run(client)
    original = client.post(
        "/api/v1/companies/AAPL/valuation/plans",
        json={"valuation_run_id": run["valuation_run_id"], "scenario_key": "base",
              "margin_of_safety": 0.2, "name": "待复核方案"},
    ).json()
    company_db._conn.execute(
        """UPDATE valuation_plan SET review_status = 'needs_review', review_reason = '财务披露已更新'
           WHERE plan_id = ?""",
        [original["plan_id"]],
    )

    copied = client.post(
        f"/api/v1/companies/AAPL/valuation/plans/{original['plan_id']}/copy",
        json={"name": "待复核副本"},
    )

    assert copied.status_code == 200
    assert copied.json()["review_status"] == "needs_review"
    assert copied.json()["review_reason"] == "财务披露已更新"


def test_refresh_reports_all_modules_and_partial_failure(client, monkeypatch):
    """P08: all four modules report independently; one failure stays retryable."""
    import equitylens.ingestion.sec.sync as sec_sync
    import equitylens.ingestion.sec.management as management_sync
    import equitylens.market.service as mkt_svc
    from equitylens.ingestion.sec.management import ManagementSyncReport
    from equitylens.ingestion.sec.sync import SyncReport
    from equitylens.market.service import SyncReport as QuoteSyncReport

    monkeypatch.setattr(sec_sync, "sync_company",
                        lambda ticker, **kw: SyncReport(company=ticker, facts_accepted=5,
                                                        canonical_count=5, warnings=[]))
    monkeypatch.setattr(sec_sync, "sync_segments", lambda ticker, **kw: (_ for _ in ()).throw(RuntimeError("segment unavailable")))
    monkeypatch.setattr(management_sync, "sync_management",
                        lambda ticker, **kw: ManagementSyncReport(company=ticker, executives=3))
    monkeypatch.setattr(mkt_svc, "sync_quotes",
                        lambda tickers, **kw: [QuoteSyncReport(company=tickers[0], quotes=[{
                            "provider": "test", "price": 100, "observed_at": "2026-09-06"
                        }])])

    r = client.post("/api/v1/companies/AAPL/refresh")
    assert r.status_code == 200
    d = r.json()
    assert d["modules"]["financials"]["status"] == "ok"
    assert d["modules"]["financials"]["facts_accepted"] == 5
    assert d["modules"]["segments"]["status"] == "error"
    assert d["modules"]["segments"]["retryable"] is True
    assert d["modules"]["management"]["status"] == "ok"
    assert d["modules"]["quotes"]["status"] == "ok"
    assert d["status"] == "partial"


def test_refresh_retries_only_selected_failed_module(client, monkeypatch):
    import equitylens.ingestion.sec.sync as sec_sync
    import equitylens.ingestion.sec.management as management_sync
    import equitylens.market.service as mkt_svc
    from equitylens.ingestion.sec.sync import SyncReport

    calls: list[str] = []
    monkeypatch.setattr(sec_sync, "sync_company", lambda *a, **k: calls.append("financials"))
    monkeypatch.setattr(sec_sync, "sync_segments",
                        lambda ticker, **kw: calls.append("segments") or SyncReport(company=ticker, facts_accepted=2))
    monkeypatch.setattr(management_sync, "sync_management", lambda *a, **k: calls.append("management"))
    monkeypatch.setattr(mkt_svc, "sync_quotes", lambda *a, **k: calls.append("quotes"))

    response = client.post("/api/v1/companies/AAPL/refresh", json={"modules": ["segments"]})
    assert response.status_code == 200
    assert calls == ["segments"]
    assert response.json()["modules"]["segments"]["status"] == "ok"
    assert response.json()["modules"]["financials"]["status"] == "skipped"


def test_refresh_rolls_back_failed_module_writes(client, company_db, monkeypatch):
    import equitylens.ingestion.sec.sync as sec_sync

    def write_then_fail(ticker, **kwargs):
        store = kwargs["store"]
        store._conn.execute(
            "INSERT INTO company (company_id, ticker) VALUES ('refresh-sentinel', 'BAD')"
        )
        raise RuntimeError("after write")

    monkeypatch.setattr(sec_sync, "sync_company", write_then_fail)
    response = client.post(
        "/api/v1/companies/AAPL/refresh", json={"modules": ["financials"]}
    )
    assert response.status_code == 200
    assert response.json()["modules"]["financials"]["status"] == "error"
    assert company_db.query_one(
        "SELECT company_id FROM company WHERE company_id = 'refresh-sentinel'"
    ) is None


def test_refresh_marks_existing_plan_for_review_without_recalculation(client, company_db, monkeypatch):
    import equitylens.market.service as market_service
    from equitylens.market.service import SyncReport as QuoteSyncReport

    run = _save_v2_run(client)
    plan = client.post(
        "/api/v1/companies/AAPL/valuation/plans",
        json={"valuation_run_id": run["valuation_run_id"], "scenario_key": "base",
              "margin_of_safety": 0.2},
    ).json()
    old_price = plan["reference_price"]

    def sync_new_quote(tickers, **kwargs):
        kwargs["store"].insert_market_quote({
            "quote_id": "quote-after-refresh", "company_id": "0000320193", "ticker": "AAPL",
            "provider": "test", "observed_at": "2026-09-07T10:00:00+00:00",
            "price": 333.0, "currency": "USD", "source_label": "test",
            "source_url": "https://example.test/quote", "fetched_at": "2099-01-01T00:00:00+00:00",
        })
        return [QuoteSyncReport(company="AAPL", quotes=[{
            "provider": "test", "price": 333.0, "observed_at": "2026-09-07T10:00:00+00:00"
        }])]

    monkeypatch.setattr(market_service, "sync_quotes", sync_new_quote)
    try:
        refreshed = client.post(
            "/api/v1/companies/AAPL/refresh", json={"modules": ["quotes"]}
        ).json()
        assert refreshed["review_required"] is True
        assert refreshed["modules"]["quotes"]["changed"] is True

        loaded = client.get(
            f"/api/v1/companies/AAPL/valuation/plans/{plan['plan_id']}"
        ).json()
        assert loaded["review_status"] == "needs_review"
        assert "行情" in loaded["review_reason"]
        assert loaded["reference_price"] == pytest.approx(old_price)
    finally:
        # company_db is session-scoped because building the golden fixture is
        # expensive. Restore the quote table so this mutation cannot affect
        # reverse-DCF/freshness tests that run later in the same process.
        company_db._conn.execute(
            "DELETE FROM market_quote WHERE quote_id = 'quote-after-refresh'"
        )


def test_refresh_marks_financial_restatement_for_review(client, company_db, monkeypatch):
    import equitylens.ingestion.sec.sync as sec_sync
    from equitylens.domain.filings import SourceDocument
    from equitylens.ingestion.sec.sync import SyncReport

    def sync_restatement(ticker, **kwargs):
        doc = SourceDocument(
            provider="SEC",
            document_type="COMPANYFACTS_SNAPSHOT",
            company_id="0000320193",
            source_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
            content_sha256="f" * 64,
            local_path="/tmp/restated-companyfacts.json",
            fetched_at="2099-01-01T00:00:00+00:00",
            parser_version="test",
        )
        kwargs["store"].upsert_source_documents([doc.to_row()])
        return SyncReport(company=ticker, canonical_count=1)

    monkeypatch.setattr(sec_sync, "sync_company", sync_restatement)
    refreshed = client.post(
        "/api/v1/companies/AAPL/refresh", json={"modules": ["financials"]}
    )

    assert refreshed.status_code == 200
    body = refreshed.json()
    assert body["modules"]["financials"]["changed"] is True
    assert body["review_required"] is True


def test_reverse_dcf_endpoint_returns_implied_growth(client):
    r = client.post("/api/v1/companies/AAPL/valuation/reverse-dcf",
                    json={"target_price": 300.0})
    assert r.status_code == 200
    d = r.json()
    assert "implied_revenue_cagr" in d
    assert d["market"]["status"] == "OK"
    assert d["historical_revenue_cagr"] is not None


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({}, "target_price"),
        ({"target_price": 0}, "target_price"),
        ({"target_price": "NaN"}, "target_price"),
        ({"target_price": 300, "assumptions": {"wacc": -0.5, "terminal_growth": -0.51}}, "wacc"),
        ({"target_price": 300, "assumptions": "bad"}, "assumptions"),
        ({"target_price": 300, "assumptions": []}, "assumptions"),
        ({"target_price": 300, "assumptions": None}, "assumptions"),
    ],
)
def test_reverse_dcf_rejects_invalid_input_with_structured_400(client, payload, field):
    response = client.post("/api/v1/companies/AAPL/valuation/reverse-dcf", json=payload)

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["field"] == field
    assert error["code"] in {"INVALID_INPUT", "INVALID_ASSUMPTION"}
    assert error["message"]


def test_moat_endpoint_real_evidence(client):
    r = client.get("/api/v1/companies/MSFT/moat")
    assert r.status_code == 200
    d = r.json()
    assert d["demo"] is False
    assert d["signals"], "moat signals missing"
    assert any(s["evidence_ids"] for s in d["signals"])
    assert d["qualitative_gaps"], "evidence gaps must be explicit"


def test_risk_endpoint_exposes_actual_check_coverage(client):
    response = client.get("/api/v1/companies/AAPL/risks")
    assert response.status_code == 200
    body = response.json()
    assert body["coverage"]["total"] == len(body["checks"])
    assert body["coverage"]["completed"] == sum(
        check["status"] == "OK" for check in body["checks"]
    )
    assert body["coverage"]["complete"] == (body["coverage"]["completed"] == body["coverage"]["total"])


def test_research_unsupported_question_returns_capability_boundary(client):
    response = client.post("/api/v1/research/ask", json={
        "ticker": "AAPL", "question": "公司2027年收入的内部预测是多少？",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "unsupported"
    assert body["claims"] == []
    assert "增长" in body["supported_topics"]


def test_promises_endpoint_deterministic_verification(client, company_db):
    import json as _json
    from pathlib import Path

    from equitylens.domain.companies import get_company
    from equitylens.domain.promises import ingest_cards

    fx = Path(__file__).parent.parent / "fixtures" / "promises" / "AAPL"
    cards = [_json.loads(f.read_text()) for f in sorted(fx.glob("*.json"))]
    ingest_cards(company_db, get_company("AAPL").cik, "AAPL", cards)
    r = client.get("/api/v1/companies/AAPL/promises")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "READY"
    by_id = {i["promise_id"]: i for i in d["items"]}
    assert by_id["aapl-fy2025-buyback-gte"]["computed_status"] == "VERIFIED"
    assert by_id["aapl-fy2025-buyback-unrealistic"]["computed_status"] == "BROKEN"
    assert by_id["aapl-fy2026-forward"]["computed_status"] == "OPEN"


def test_freshness_endpoint_modules(client):
    r = client.get("/api/v1/companies/AAPL/freshness")
    assert r.status_code == 200
    d = r.json()
    keys = [m["key"] for m in d["modules"]]
    assert "market_quote" in keys and "sec_financials" in keys
    mkt = next(m for m in d["modules"] if m["key"] == "market_quote")
    assert mkt["status"] in ("ok", "stale")
    assert mkt["detail"] and "Nasdaq" in mkt["detail"]
