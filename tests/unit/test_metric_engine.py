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
    assert pts[-1].formula_id == "ttm.v2"
    # TTM as of FY2026Q3 = Q4'25 + Q1'26 + Q2'26 + Q3'26
    assert pts[-1].value == pytest.approx(
        102_466_000_000 + 143_756_000_000 + 111_184_000_000 + 109_417_000_000,
        rel=1e-9,
    )
    assert pts[-1].period_label == "FY2026Q3"
    assert len(pts[-1].input_fact_ids) == 4


# ---------------------------------------------------------------------------
# Synthetic regression tests (D01 debt bridge, D06 TTM continuity, D07 TTM
# frequency). Values are independent hand-computed expectations, not captured
# from the (previously buggy) output.
# ---------------------------------------------------------------------------

def _insert_fact(db, company_id, metric, period_type, fy, q, value, *, unit="USD",
                 fact_id=None, instant=None, period_end=None, as_known_at="2026-01-01"):
    db.connect()
    fid = fact_id or f"{metric}-{fy}-{q}-{value}-{period_end or instant or ''}"
    db._conn.execute(
        """INSERT INTO canonical_fact
           (canonical_fact_id, company_id, canonical_metric, period_type, fiscal_year,
            fiscal_quarter, period_start, period_end, instant_date, value, unit, status,
            mapping_rule_id, mapping_version, source_raw_fact_ids, as_known_at, created_at, warnings_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?, 'NORMALIZED', ?, 'canonical-mappings.v2', '[]', ?, ?, '[]')""",
        [fid, company_id, metric, period_type, fy, q, None, period_end, instant, value, unit,
         f"{metric.lower()}.usgaap.v2", as_known_at, "2026-01-01 00:00:00"],
    )


def test_net_debt_does_not_double_count_current_portion(db):
    """D01: noncurrent 80 + current 20 + commercial paper 5 = debt 105;
    net debt 105 - 30 - 10 = 65 (never 125 or 85)."""
    cid = "TEST"
    d = "2026-06-30"
    _insert_fact(db, cid, "LONG_TERM_DEBT", "INSTANT", None, None, 80e9, instant=d)
    _insert_fact(db, cid, "LONG_TERM_DEBT_CURRENT", "INSTANT", None, None, 20e9, instant=d)
    _insert_fact(db, cid, "COMMERCIAL_PAPER", "INSTANT", None, None, 5e9, instant=d)
    _insert_fact(db, cid, "CASH_AND_EQUIVALENTS", "INSTANT", None, None, 30e9, instant=d)
    _insert_fact(db, cid, "SHORT_TERM_INVESTMENTS", "INSTANT", None, None, 10e9, instant=d)

    eng = MetricEngine(db)
    pts = eng.compute("NET_DEBT", cid, frequency="quarterly")
    assert len(pts) == 1
    assert pts[0].value == pytest.approx(65e9, rel=1e-9)
    # all add/subtract components are listed in provenance
    assert len(pts[0].input_fact_ids) == 5


def test_net_debt_missing_component_is_gap(db):
    """D01: missing a required bridge component -> no silent value."""
    cid = "TEST"
    d = "2026-06-30"
    _insert_fact(db, cid, "LONG_TERM_DEBT", "INSTANT", None, None, 80e9, instant=d)
    # no LONG_TERM_DEBT_CURRENT, no cash, no investments
    eng = MetricEngine(db)
    assert eng.compute("NET_DEBT", cid, frequency="quarterly") == []


def test_net_debt_date_mismatch_is_gap(db):
    """D01: components on different dates must not be spliced together."""
    cid = "TEST"
    _insert_fact(db, cid, "LONG_TERM_DEBT", "INSTANT", None, None, 80e9, instant="2026-06-30")
    _insert_fact(db, cid, "LONG_TERM_DEBT_CURRENT", "INSTANT", None, None, 20e9, instant="2026-03-31")
    _insert_fact(db, cid, "CASH_AND_EQUIVALENTS", "INSTANT", None, None, 30e9, instant="2026-06-30")
    _insert_fact(db, cid, "SHORT_TERM_INVESTMENTS", "INSTANT", None, None, 10e9, instant="2026-06-30")
    eng = MetricEngine(db)
    assert eng.compute("NET_DEBT", cid, frequency="quarterly") == []


def _q(metric, year, quarter, value):
    return {"canonical_metric": metric, "period_type": "Q_STANDALONE",
            "fiscal_year": year, "fiscal_quarter": quarter,
            "period_end": f"{year}-Q{quarter}", "value": value, "unit": "USD",
            "canonical_fact_id": f"{metric}-{year}-{quarter}", "as_known_at": "2026-01-01"}


def test_ttm_requires_consecutive_quarters():
    """D06: four consecutive quarters sum to 100; a missing quarter is a gap
    even when an older quarter could fill the count."""
    eng = MetricEngine(None)
    facts = [_q("REVENUE", 2025, 1, 10.0), _q("REVENUE", 2025, 2, 20.0),
             _q("REVENUE", 2025, 3, 30.0), _q("REVENUE", 2025, 4, 40.0)]
    t = eng.ttm(facts)
    assert t is not None and t["value"] == pytest.approx(100.0)

    # remove one quarter; an older quarter (2025Q3) must NOT fill the window
    incomplete = [_q("REVENUE", 2025, 1, 10.0), _q("REVENUE", 2025, 2, 20.0),
                  _q("REVENUE", 2025, 3, 30.0), _q("REVENUE", 2026, 1, 40.0)]
    assert eng.ttm(incomplete) is None


def test_ttm_flattens_provenance_for_derived_standalone_quarters():
    """A derived quarter has input_ids rather than a canonical_fact_id."""
    eng = MetricEngine(None)
    facts = [
        _q("OPERATING_CASH_FLOW", 2025, 4, 40.0),
        _q("OPERATING_CASH_FLOW", 2026, 1, 10.0),
        {
            **_q("OPERATING_CASH_FLOW", 2026, 2, 20.0),
            "canonical_fact_id": None,
            "input_ids": ["ocf-ytd3", "ocf-ytd6"],
        },
        {
            **_q("OPERATING_CASH_FLOW", 2026, 3, 30.0),
            "canonical_fact_id": None,
            "input_ids": ["ocf-ytd6", "ocf-ytd9"],
        },
    ]

    ttm = eng.ttm(facts)

    assert ttm is not None
    assert ttm["value"] == pytest.approx(100.0)
    assert ttm["input_ids"] == [
        "OPERATING_CASH_FLOW-2025-4",
        "OPERATING_CASH_FLOW-2026-1",
        "ocf-ytd3",
        "ocf-ytd6",
        "ocf-ytd9",
    ]


def test_published_lowercase_currency_unit_still_computes_ttm():
    facts = [
        {**_q("REVENUE", 2026, quarter, float(quarter)), "unit": "usd"}
        for quarter in range(1, 5)
    ]
    engine = MetricEngine(None, published_facts=facts)

    current = engine.current("REVENUE", "published-company", frequency="ttm")

    assert current.value == pytest.approx(10.0)
    assert current.status == "OK"
    assert current.unit == "USD"


def test_same_day_duplicate_period_selection_is_stable():
    """D05/D06: database insertion order cannot change the selected fact."""
    facts = [
        {"canonical_fact_id": "fact-a", "as_known_at": "2026-01-30", "value": 10.0},
        {"canonical_fact_id": "fact-b", "as_known_at": "2026-01-30", "value": 20.0},
    ]
    assert MetricEngine.pick_latest(facts)["canonical_fact_id"] == "fact-b"
    assert MetricEngine.pick_latest(list(reversed(facts)))["canonical_fact_id"] == "fact-b"


def test_duplicate_quarter_is_selected_once_in_ttm(db):
    """D05/D06: tied duplicate observations cannot be counted twice."""
    cid = "DUPLICATE"
    _insert_fact(db, cid, "REVENUE", "Q_STANDALONE", 2025, 1, 10.0, fact_id="fact-a")
    _insert_fact(db, cid, "REVENUE", "Q_STANDALONE", 2025, 1, 20.0, fact_id="fact-b")
    for quarter, value in ((2, 2.0), (3, 3.0), (4, 4.0)):
        _insert_fact(db, cid, "REVENUE", "Q_STANDALONE", 2025, quarter, value)

    points = MetricEngine(db).compute("REVENUE", cid, frequency="ttm")
    assert len(points) == 1
    assert points[0].value == pytest.approx(29.0)
    assert "fact-b" in points[0].input_fact_ids
    assert "fact-a" not in points[0].input_fact_ids


def test_ratio_zero_denominator_is_explicitly_unavailable(db):
    """D07: a disclosed zero denominator is not a valid zero ratio."""
    cid = "ZERO-DENOMINATOR"
    _insert_fact(db, cid, "GROSS_PROFIT", "Q_STANDALONE", 2025, 1, 10.0, fact_id="gross")
    _insert_fact(db, cid, "REVENUE", "Q_STANDALONE", 2025, 1, 0.0, fact_id="revenue-zero")

    point = MetricEngine(db).compute("GROSS_MARGIN", cid, frequency="quarterly")[0]
    assert point.value is None
    assert point.status == "UNAVAILABLE"
    assert point.missing_reason == "REVENUE denominator is zero"
    assert point.input_fact_ids == ["gross", "revenue-zero"]


def test_aapl_eps_ttm_missing_q4_is_gap(engine):
    """D06/D09: EPS is a per-share ratio and is NOT additive quarter-over-quarter;
    the engine must never emit the bogus 8.44 TTM sum for it."""
    pts = engine.compute("DILUTED_EPS", CIK_AAPL, frequency="ttm")
    assert pts == []  # per-share metrics have no summed-TTM representation
    assert all(abs(p.value - 8.44) > 1e-6 for p in pts)


def test_ttm_margin_is_sum_over_sum(db):
    """D07: TTM margin = sum(4q numerator)/sum(4q revenue), not average of ratios."""
    cid = "TEST"
    for q, (rev, gp) in enumerate([(100.0, 10.0), (200.0, 60.0), (100.0, 20.0), (200.0, 80.0)], start=1):
        _insert_fact(db, cid, "REVENUE", "Q_STANDALONE", 2025, q, rev * 1e9)
        _insert_fact(db, cid, "GROSS_PROFIT", "Q_STANDALONE", 2025, q, gp * 1e9)
    eng = MetricEngine(db)
    pts = eng.compute("GROSS_MARGIN", cid, frequency="ttm")
    assert pts
    assert pts[-1].value == pytest.approx(170.0 / 600.0, rel=1e-9)


def test_ttm_fcf_is_sum_ocf_minus_sum_capex(db):
    """D07: TTM FCF = sum(4q OCF) - sum(4q CapEx) = 140 - 50 = 90."""
    cid = "TEST"
    for q, (ocf, capex) in enumerate([(20.0, 5.0), (30.0, 10.0), (40.0, 15.0), (50.0, 20.0)], start=1):
        _insert_fact(db, cid, "OPERATING_CASH_FLOW", "Q_STANDALONE", 2025, q, ocf * 1e9)
        _insert_fact(db, cid, "CAPITAL_EXPENDITURES", "Q_STANDALONE", 2025, q, capex * 1e9)
    eng = MetricEngine(db)
    pts = eng.compute("FCF", cid, frequency="ttm")
    assert pts
    assert pts[-1].value == pytest.approx(90e9, rel=1e-9)


def test_annual_and_ttm_fcf_differ(db):
    """D07: annual FCF (FY OCF - FY CapEx) must differ from TTM FCF."""
    cid = "TEST"
    for q, (ocf, capex) in enumerate([(20.0, 5.0), (30.0, 10.0), (40.0, 15.0), (50.0, 20.0)], start=1):
        _insert_fact(db, cid, "OPERATING_CASH_FLOW", "Q_STANDALONE", 2025, q, ocf * 1e9)
        _insert_fact(db, cid, "CAPITAL_EXPENDITURES", "Q_STANDALONE", 2025, q, capex * 1e9)
    _insert_fact(db, cid, "OPERATING_CASH_FLOW", "FY", 2025, None, 500e9)
    _insert_fact(db, cid, "CAPITAL_EXPENDITURES", "FY", 2025, None, 200e9)
    eng = MetricEngine(db)
    ttm = eng.compute("FCF", cid, frequency="ttm")
    annual = eng.compute("FCF", cid, frequency="annual")
    assert ttm and annual
    assert ttm[-1].value == pytest.approx(90e9, rel=1e-9)
    assert annual[-1].value == pytest.approx(300e9, rel=1e-9)
    assert ttm[-1].value != pytest.approx(annual[-1].value)


def test_current_ttm_preserves_zero_in_latest_window(db):
    """D06/P07: zero is current data, not a reason to select an older TTM."""
    cid = "TTM_ZERO"
    periods = [
        (2025, 1, 25.0, "2024-09-30"),
        (2025, 2, 25.0, "2024-12-31"),
        (2025, 3, 25.0, "2025-03-31"),
        (2025, 4, 25.0, "2025-06-30"),
        (2026, 1, -75.0, "2025-09-30"),
    ]
    for fy, q, value, end in periods:
        _insert_fact(db, cid, "NET_INCOME", "Q_STANDALONE", fy, q, value,
                     period_end=end)

    point = MetricEngine(db).current("NET_INCOME", cid, "ttm")

    assert point.status == "OK"
    assert point.value == 0.0
    assert point.frequency == "ttm"
    assert point.fiscal_year == 2026 and point.fiscal_quarter == 1
    assert point.period_start == "2024-12-31"
    assert point.period_end == "2025-09-30"
    assert len(point.input_fact_ids) == 4


def test_current_ttm_reports_latest_gap_instead_of_older_window(db):
    """D06/P07: a later incomplete period invalidates the current TTM view."""
    cid = "TTM_GAP"
    for q, end in enumerate(("2024-09-30", "2024-12-31", "2025-03-31", "2025-06-30"), 1):
        _insert_fact(db, cid, "NET_INCOME", "Q_STANDALONE", 2025, q, 25.0,
                     period_end=end)
    _insert_fact(db, cid, "NET_INCOME", "Q_STANDALONE", 2026, 2, 30.0,
                 period_end="2025-12-31")

    point = MetricEngine(db).current("NET_INCOME", cid, "ttm")

    assert point.status == "INCOMPLETE_PERIOD"
    assert point.value is None
    assert point.fiscal_year == 2026 and point.fiscal_quarter == 2
    assert "FY2026Q1" in point.missing_reason


def test_current_ttm_rejects_unit_mismatch(db):
    """D06: a four-quarter count is not valid when amount units conflict."""
    cid = "TTM_UNIT"
    for q in range(1, 5):
        _insert_fact(db, cid, "NET_INCOME", "Q_STANDALONE", 2025, q, 25.0,
                     unit="EUR" if q == 4 else "USD")

    point = MetricEngine(db).current("NET_INCOME", cid, "ttm")

    assert point.status == "INCOMPLETE_PERIOD"
    assert point.value is None
    assert "unit" in point.missing_reason.lower()
