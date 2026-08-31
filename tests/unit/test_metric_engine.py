"""Metric engine tests against the normalized golden fixture DB."""

from __future__ import annotations

import pytest

from equitylens.metrics.engine import MetricEngine

CIK_AAPL = "0000320193"
CIK_MSFT = "0000789019"


@pytest.fixture()
def engine(company_db) -> MetricEngine:
    return MetricEngine(company_db)


def test_ttm_revenue_is_sum_of_four_standalone_quarters(engine):
    pts = engine.compute("REVENUE", CIK_AAPL, frequency="quarterly")
    assert len(pts) >= 4
    last4 = pts[-4:]
    # TTM as of the latest quarter = sum of the 4 trailing standalone quarters
    ttm = engine.ttm(engine.load_facts(CIK_AAPL, ["REVENUE"])["REVENUE"])
    assert ttm is not None
    assert ttm["value"] == pytest.approx(sum(p.value for p in last4), rel=1e-9)


def test_revenue_growth_yoy(engine):
    pts = engine.compute("REVENUE_GROWTH_YOY", CIK_MSFT, frequency="quarterly")
    growth = [p for p in pts if p.value is not None]
    assert growth
    # Q1 FY2025 (Sep-2024) vs Q1 FY2024 (Sep-2023): MSFT grew ~15% YoY
    fy25q1 = next(p for p in growth if p.period_label == "FY2025Q1")
    assert 0.10 < fy25q1.value < 0.20


def test_margin_consistency(engine):
    gp = engine.compute("GROSS_MARGIN", CIK_MSFT, frequency="quarterly")
    assert gp
    latest = gp[-1]
    assert 0.60 < latest.value < 0.75  # MSFT gross margin band


def test_fcf_equals_ocf_minus_capex(engine):
    fcf = engine.compute("FCF", CIK_AAPL, frequency="quarterly")
    ocf = engine.compute("OPERATING_CASH_FLOW", CIK_AAPL, frequency="quarterly")
    capex = engine.compute("CAPITAL_EXPENDITURES", CIK_AAPL, frequency="quarterly")
    assert fcf and ocf and capex
    # FCF point uses the standalone quarter series too
    assert fcf[-1].value == pytest.approx(ocf[-1].value - capex[-1].value, rel=1e-6)


def test_derived_facts_carry_input_ids(engine):
    ocf = engine.compute("OPERATING_CASH_FLOW", CIK_AAPL, frequency="quarterly")
    derived = [p for p in ocf if p.status == "CALCULATED"]
    assert derived, "AAPL Q2/Q3/Q4 OCF should be derived from YTD chain"
    for p in derived:
        assert p.formula_id == "standalone_quarter.ytd_diff.v1"
        assert len(p.input_fact_ids) == 2


def test_metric_points_have_provenance_inputs(engine):
    pts = engine.compute("GROSS_MARGIN", CIK_AAPL, frequency="quarterly")
    assert pts[-1].formula_id == "gross_margin.v1"
    assert len(pts[-1].input_fact_ids) == 2


def test_ttm_frequency_sums_four_quarters(engine):
    pts = engine.compute("REVENUE", CIK_AAPL, frequency="ttm")
    assert pts[-1].formula_id == "ttm.v1"
    # TTM as of FY2026Q3 = Q4'25 + Q1'26 + Q2'26 + Q3'26
    assert pts[-1].value == pytest.approx(
        102_466_000_000 + 143_756_000_000 + 111_184_000_000 + 109_417_000_000,
        rel=1e-9,
    )
    assert pts[-1].period_label == "FY2026Q3"
    assert len(pts[-1].input_fact_ids) == 4
