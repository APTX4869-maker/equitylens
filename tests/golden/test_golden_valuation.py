"""Golden tests for the FCFF DCF valuation engine (M5).

Determinism and guardrails are the core acceptance criteria
(docs/09 F): same inputs + model version reproduce the same output;
WACC > terminal growth is enforced; sensitivity recalcs, never scales.
"""

from __future__ import annotations

import pytest

from equitylens.valuation.dcf import DcfInputs, ValuationError, implied_growth, run_dcf


def make_inputs(**over) -> DcfInputs:
    base = dict(
        revenue_base=100.0,
        revenue_growth=[0.08, 0.07, 0.06, 0.05, 0.04],
        op_margin_start=0.25,
        op_margin_end=0.28,
        tax_rate=0.16,
        da_pct=0.03,
        capex_pct=0.04,
        nwc_pct=0.002,
        wacc=0.085,
        terminal_growth=0.025,
        net_cash=10.0,
        shares=10.0,
    )
    base.update(over)
    return DcfInputs(**base)


def test_dcf_is_deterministic():
    a = run_dcf(make_inputs())
    b = run_dcf(make_inputs())
    assert a.fair_value_per_share == pytest.approx(b.fair_value_per_share, rel=1e-15)
    assert a.model_version == "fcff_dcf.v2"


def test_dcf_guardrail_wacc_must_exceed_growth():
    with pytest.raises(ValuationError, match="WACC"):
        run_dcf(make_inputs(wacc=0.02, terminal_growth=0.025))


def test_dcf_forecast_year_count_and_tv():
    out = run_dcf(make_inputs())
    assert len(out.forecast) == 5
    assert out.enterprise_value == pytest.approx(out.sum_pv_fcff + out.pv_terminal, rel=1e-9)
    assert out.equity_value == pytest.approx(out.enterprise_value + out.net_cash, rel=1e-9)
    assert 0.5 < out.terminal_value_share < 0.95


def test_dcf_share_basis_stated():
    inputs = make_inputs(shares=5.0)
    out = run_dcf(inputs)
    assert out.fair_value_per_share == pytest.approx(out.equity_value / 5.0, rel=1e-9)


def test_reverse_dcf_finds_known_root():
    """If market price equals the fair value at g=12%, implied growth ~ 12%."""
    target = run_dcf(make_inputs(revenue_growth=[0.12] * 5)).fair_value_per_share
    implied = implied_growth(make_inputs(revenue_growth=[0.05] * 5), target)
    assert implied is not None
    assert implied == pytest.approx(0.12, abs=1e-4)


def test_reverse_dcf_no_root_reports_none():
    """An absurdly low target has no root in the growth bounds."""
    implied = implied_growth(make_inputs(), target_price=1.0)
    assert implied is None


# --- V01: missing / zero / invalid input handling -----------------------------

def test_zero_tax_capex_margin_stay_zero():
    """Real zeros are valid values, not 'missing'."""
    out = run_dcf(make_inputs(tax_rate=0.0, capex_pct=0.0, op_margin_start=0.0, op_margin_end=0.0))
    assert out.fair_value_per_share == pytest.approx(out.equity_value / 10.0, rel=1e-9)


def test_nan_inf_rejected():
    import math

    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValuationError):
            run_dcf(make_inputs(wacc=bad))
        with pytest.raises(ValuationError):
            run_dcf(make_inputs(revenue_base=bad))
        with pytest.raises(ValuationError):
            run_dcf(make_inputs(terminal_roic=bad))


def test_out_of_range_inputs_rejected():
    with pytest.raises(ValuationError):
        run_dcf(make_inputs(tax_rate=1.5))
    with pytest.raises(ValuationError):
        run_dcf(make_inputs(op_margin_end=2.0))
    with pytest.raises(ValuationError):
        run_dcf(make_inputs(revenue_growth=[-1.2] * 5))
    with pytest.raises(ValuationError):
        run_dcf(make_inputs(revenue_growth=[0.05, 0.05]))  # not 5 items
    with pytest.raises(ValuationError):
        run_dcf(make_inputs(shares=0.0))


def test_minus_100_percent_growth_releases_working_capital():
    """V01: at -100% first-year growth, released working capital must stay in
    FCFF. dNWC is computed from the PRIOR revenue base, not the new zero."""
    inputs = make_inputs(revenue_base=100.0, revenue_growth=[-1.0, 0, 0, 0, 0],
                         op_margin_start=0, op_margin_end=0, tax_rate=0,
                         da_pct=0, capex_pct=0, nwc_pct=0.10,
                         wacc=0.10, terminal_growth=0, net_cash=0, shares=1)
    out = run_dcf(inputs)
    assert out.forecast[0].nwc_delta == -10.0
    assert out.forecast[0].fcff == 10.0


@pytest.mark.parametrize(("field", "value"), [
    ("capex_pct", -0.2),
    ("wacc", -1.0),
])
def test_dcf_rejects_model_incompatible_inputs(field, value):
    """V01: negative CapEx and WACC <= -1 are model-incompatible; they must be
    rejected with a structured error naming the offending field (never a normal
    price nor a downstream ZeroDivisionError)."""
    with pytest.raises(ValuationError) as exc:
        run_dcf(make_inputs(**{field: value},
                            terminal_growth=-1.1 if field == "wacc" else 0.02))
    assert exc.value.field == field
    assert exc.value.code == "INVALID_ASSUMPTION"


def test_explicit_terminal_values_must_be_finite():
    """V01: explicit-forecast terminal inputs (terminal_ebit etc.) must be
    finite; NaN must not flow through to a NaN fair value."""
    from equitylens.valuation.dcf import run_dcf_explicit

    with pytest.raises(ValuationError) as exc:
        run_dcf_explicit(
            ebit=[20.0] * 5,
            da=[3.0] * 5,
            capex=[5.0] * 5,
            tax_rate=0.25,
            wacc=0.10,
            terminal_growth=0.0,
            net_cash=10.0,
            shares=10.0,
            terminal_ebit=float("nan"),
        )
    assert exc.value.field == "terminal_ebit"


def test_explicit_terminal_year_cash_flow_is_not_grown_twice():
    """P02: terminal inputs describe year 6 already, so TV uses that FCFF once."""
    from equitylens.valuation.dcf import run_dcf_explicit

    out = run_dcf_explicit(
        ebit=[20.0] * 5, da=[3.0] * 5, capex=[5.0] * 5,
        tax_rate=0.20, wacc=0.10, terminal_growth=0.02,
        net_cash=0.0, shares=1.0, nwc_delta=[0.0] * 5,
        terminal_ebit=120.0, terminal_da=10.0,
        terminal_capex=5.0, terminal_nwc_delta=1.0,
    )

    # Terminal-year FCFF = 120*(1-.2)+10-5-1 = 100; TV = 100/(.10-.02).
    assert out.terminal_value == pytest.approx(1250.0)


def test_production_v2_terminal_uses_stable_roic_reinvestment():
    """P02: production constructs year-6 FCFF from stable growth and ROIC."""
    inputs = make_inputs(
        revenue_base=100.0, revenue_growth=[0.0] * 5,
        op_margin_start=0.25, op_margin_end=0.25, tax_rate=0.20,
        da_pct=0.0, capex_pct=0.0, nwc_pct=0.0,
        wacc=0.10, terminal_growth=0.02, net_cash=0.0, shares=1.0,
    )
    inputs.terminal_roic = 0.20

    out = run_dcf(inputs)
    terminal = out.terminal_forecast
    assert out.model_version == "fcff_dcf.v2"
    assert terminal["revenue"] == pytest.approx(102.0)
    assert terminal["nopat"] == pytest.approx(20.4)
    assert terminal["reinvestment_rate"] == pytest.approx(0.10)
    assert terminal["reinvestment"] == pytest.approx(2.04)
    assert terminal["fcff"] == pytest.approx(18.36)
    assert out.terminal_value == pytest.approx(18.36 / 0.08)


def test_negative_fcff_not_clipped_to_zero():
    """A legal negative-FCFF path must not crash nor be coerced to zero."""
    out = run_dcf(make_inputs(op_margin_start=-0.05, op_margin_end=-0.05, tax_rate=0.2,
                              da_pct=0.01, capex_pct=0.10, nwc_pct=0.0,
                              revenue_growth=[0.0] * 5, wacc=0.10, terminal_growth=0.03,
                              net_cash=0.0))
    assert out.forecast[0].fcff < 0
    assert out.fair_value_per_share < 0  # not zeroed for "niceness"


def test_sensitivity_recalculates():
    from equitylens.valuation.service import sensitivity

    sens = sensitivity(make_inputs())
    assert len(sens["rows"]) == 5 and len(sens["terminal_grid"]) == 5
    # the grid must contain the exact base inputs cell
    base_fair = run_dcf(make_inputs()).fair_value_per_share
    center = sens["rows"][2]["values"][2]
    assert center == pytest.approx(base_fair, rel=1e-6)


def test_reverse_dcf_uses_supplied_assumptions_not_defaults(company_db):
    """V02: reverse DCF must solve from the confirmed input snapshot (WACC 12%,
    constant growth 10%), never fall back to the default 8.5% WACC."""
    from equitylens.valuation.service import reverse_dcf

    base = DcfInputs(revenue_base=100.0, revenue_growth=[0.10] * 5,
                     op_margin_start=0.25, op_margin_end=0.25, tax_rate=0.16,
                     da_pct=0.03, capex_pct=0.04, nwc_pct=0.002,
                     wacc=0.12, terminal_growth=0.025, net_cash=10.0, shares=10.0)
    target = run_dcf(base).fair_value_per_share
    assumptions = {
        "revenue_base": 100.0, "revenue_growth": [0.10] * 5,
        "op_margin_start": 0.25, "op_margin_end": 0.25, "tax_rate": 0.16,
        "da_pct": 0.03, "capex_pct": 0.04, "nwc_pct": 0.002,
        "wacc": 0.12, "terminal_growth": 0.025, "net_cash": 10.0, "shares": 10.0,
    }
    d = reverse_dcf(company_db, "0000320193", "AAPL",
                    {"target_price": target, "assumptions": assumptions})
    assert d["implied_revenue_cagr"] == pytest.approx(0.10, abs=1e-4)
    assert d["fixed_assumptions"]["wacc"] == pytest.approx(0.12)


def test_scenario_valuation_never_raises_for_guardrail():
    """V04: a legal base (WACC 5%, g 3.5%) must return; a sub-scenario that
    hits the guardrail is reported unavailable, never a whole-request failure."""
    from equitylens.valuation.service import scenario_valuation

    out = scenario_valuation(make_inputs(wacc=0.05, terminal_growth=0.035), "TEST")
    assert out["base"]["status"] == "OK" and out["base"]["result"] is not None
    for k in ("bear", "base", "bull"):
        assert out[k]["status"] in ("OK", "UNAVAILABLE")
        if out[k]["status"] == "UNAVAILABLE":
            assert out[k]["reason"] and out[k]["result"] is None


def test_explicit_forecast_example_a_stable():
    """P02 例A：无增长稳定经营，FCFF=13/年，TV=130，EV=130，每股 14。"""
    from equitylens.valuation.dcf import run_dcf_explicit

    out = run_dcf_explicit(ebit=[20] * 5, da=[3] * 5, capex=[5] * 5, tax_rate=0.25,
                           wacc=0.10, terminal_growth=0.0, net_cash=10.0, shares=10.0)
    assert [f.fcff for f in out.forecast] == pytest.approx([13] * 5, abs=1e-9)
    assert out.terminal_value == pytest.approx(130.0, abs=1e-6)
    assert out.sum_pv_fcff == pytest.approx(49.2802280023, abs=1e-6)
    assert out.pv_terminal == pytest.approx(80.7197719977, abs=1e-6)
    assert out.enterprise_value == pytest.approx(130.0, abs=1e-6)
    assert out.fair_value_per_share == pytest.approx(14.0, abs=1e-6)


def test_explicit_forecast_example_b_negative_fcff():
    """P02 例B：持续负现金流不被截零，每股 −5。"""
    from equitylens.valuation.dcf import run_dcf_explicit

    out = run_dcf_explicit(ebit=[5] * 5, da=[1] * 5, capex=[10] * 5, tax_rate=0.20,
                           wacc=0.10, terminal_growth=0.0, net_cash=0.0, shares=10.0)
    assert [f.fcff for f in out.forecast] == pytest.approx([-5] * 5, abs=1e-9)
    assert out.fair_value_per_share == pytest.approx(-5.0, abs=1e-6)
    assert out.enterprise_value == pytest.approx(-50.0, abs=1e-6)


def test_explicit_forecast_example_c_capex_ramp():
    """P02 例C：投入高峰回落，FCFF 3/6/9/12/13，每股 12.1435694283。"""
    from equitylens.valuation.dcf import run_dcf_explicit

    out = run_dcf_explicit(ebit=[20] * 5, da=[3] * 5, capex=[15, 12, 9, 6, 5], tax_rate=0.25,
                           wacc=0.10, terminal_growth=0.0, net_cash=10.0, shares=10.0,
                           terminal_capex=5.0)
    assert [f.fcff for f in out.forecast] == pytest.approx([3, 6, 9, 12, 13], abs=1e-9)
    assert out.sum_pv_fcff == pytest.approx(30.7159222855, abs=1e-6)
    assert out.pv_terminal == pytest.approx(80.7197719977, abs=1e-6)
    assert out.enterprise_value == pytest.approx(111.4356942832, abs=1e-6)
    assert out.fair_value_per_share == pytest.approx(12.1435694283, abs=1e-6)


def test_bear_bull_growth_sign_aware():
    """P03: Bear is always worse (lower growth) and Bull always better (higher),
    even for negative base growth — the labels must not invert."""
    from equitylens.valuation.service import _bear_bull_growth

    bear, bull = _bear_bull_growth([0.10, -0.05, 0.0])
    assert bear == pytest.approx([0.05, -0.075, 0.0])
    assert bull == pytest.approx([0.15, -0.025, 0.0])


def test_scenario_negative_growth_bear_worse_bull_better():
    """P03: with a negative base growth, 悲观 is more negative and 乐观 less
    negative (not mechanically inverted)."""
    from equitylens.valuation.service import scenario_valuation

    out = scenario_valuation(make_inputs(revenue_growth=[-0.05] * 5, wacc=0.10, terminal_growth=0.02), "TEST")
    bear_g = out["bear"]["inputs"]["revenue_growth"][0]
    bull_g = out["bull"]["inputs"]["revenue_growth"][0]
    assert bear_g < -0.05  # worse
    assert bull_g > -0.05  # better


def test_model_quality_block_structured():
    """P03: model quality reports data completeness, estimated inputs, terminal
    dependence and scenario dispersion — not a correctness probability."""
    from equitylens.valuation.service import model_quality_block

    out = run_dcf(make_inputs())
    scenarios = {
        "bear": {"result": {"fair_value_per_share": 80.0}},
        "base": {"result": {"fair_value_per_share": 100.0}},
        "bull": {"result": {"fair_value_per_share": 120.0}},
    }
    meta = {
        "wacc": {"source": "user_override"},
        "revenue_base": {"source": "SEC 10-K canonical fact"},
    }
    mq = model_quality_block(meta, out, scenarios)
    assert mq["data_completeness"] == "partial"
    assert "wacc" in mq["estimated_inputs"]
    assert 0 < mq["terminal_value_share"] < 1
    assert mq["scenario_dispersion"] == pytest.approx(0.4)
    assert "不是价格正确的概率" in mq["note"]


def test_aapl_bear_scenario_supports_negative_growth_and_explains_changes():
    from equitylens.valuation.service import scenario_valuation

    scenarios = scenario_valuation(make_inputs(revenue_growth=[0.0] * 5), "AAPL")
    bear = scenarios["bear"]
    assert bear["inputs"]["revenue_growth"][0] == pytest.approx(-0.05)
    assert bear["story"]
    assert set(bear["changed_fields"]) == {
        "revenue_growth", "op_margin_end", "wacc", "terminal_growth"
    }
    assert bear["inputs"]["capex_pct"] == pytest.approx(0.04)
    assert bear["inputs"]["da_pct"] == pytest.approx(0.03)
    assert bear["inputs"]["nwc_pct"] == pytest.approx(0.002)


def test_bear_scenario_makes_a_loss_margin_worse_instead_of_clipping_to_zero():
    from equitylens.valuation.service import scenario_valuation

    base = make_inputs(op_margin_start=-0.08, op_margin_end=-0.10)
    bear = scenario_valuation(base, "AAPL")["bear"]
    assert bear["inputs"]["op_margin_end"] < base.op_margin_end
    assert bear["inputs"]["op_margin_end"] == pytest.approx(-0.13)


def test_guardrail_boundary_is_consistent():
    """V04: WACC − g of exactly 1pp vs slightly more/less follows one rule."""
    # >= 1pp is allowed (message says "at least 1.0pp")
    run_dcf(make_inputs(wacc=0.05, terminal_growth=0.04))  # exactly 1pp
    run_dcf(make_inputs(wacc=0.05, terminal_growth=0.04 - 1e-9))  # a hair above
    with pytest.raises(ValuationError):
        run_dcf(make_inputs(wacc=0.05, terminal_growth=0.04 + 1e-6))  # a hair below


def test_guardrail_rejects_negative_wacc_even_when_spread_is_valid():
    with pytest.raises(ValuationError, match="wacc"):
        run_dcf(make_inputs(wacc=-0.50, terminal_growth=-0.51))


def test_defaults_built_from_real_facts(company_db):
    """Assumption defaults reflect real canonical facts (AAPL)."""
    from equitylens.valuation.defaults import default_assumption_set

    inputs, meta = default_assumption_set(company_db, "0000320193", "AAPL")
    assert inputs.revenue_base == pytest.approx(416_161_000_000, rel=1e-6)
    assert inputs.op_margin_start == pytest.approx(133_050 / 416_161, rel=1e-4)
    assert inputs.capex_pct == pytest.approx(12_715 / 416_161, rel=1e-4)
    assert meta["revenue_base"]["source"].startswith("SEC")
    history = meta["revenue_growth"]["historical_reference"]
    assert history["period"] == "FY2020–FY2025"
    assert history["value"] == pytest.approx((416_161 / 274_515) ** (1 / 5) - 1)
    assert "不直接用作未来预测" in history["rule"]
    assert inputs.wacc > inputs.terminal_growth + 0.01


def test_defaults_do_not_mix_prior_year_operating_income(company_db):
    """The latest revenue FY defines the flow-input cohort. An older operating
    income must not be divided by the newer revenue when that cohort is missing."""
    from equitylens.valuation.defaults import default_assumption_set

    company_db._conn.execute("BEGIN")
    try:
        company_db._conn.execute(
            """DELETE FROM canonical_fact
               WHERE company_id = '0000320193' AND canonical_metric = 'OPERATING_INCOME'
                 AND fiscal_year = 2025"""
        )
        with pytest.raises(ValueError, match="FY2025 operating income"):
            default_assumption_set(company_db, "0000320193", "AAPL")
    finally:
        company_db._conn.execute("ROLLBACK")


def test_defaults_use_fallback_instead_of_prior_year_capex(company_db):
    from equitylens.valuation.defaults import default_assumption_set

    company_db._conn.execute("BEGIN")
    try:
        company_db._conn.execute(
            """DELETE FROM canonical_fact
               WHERE company_id = '0000320193' AND canonical_metric = 'CAPITAL_EXPENDITURES'
                 AND fiscal_year = 2025"""
        )
        _, meta = default_assumption_set(company_db, "0000320193", "AAPL")
        assert meta["capex_pct"]["source_type"] == "config_assumption"
        assert meta["capex_pct"]["as_of"] is None
        assert meta["capex_pct"]["source_ids"] == []
    finally:
        company_db._conn.execute("ROLLBACK")


@pytest.mark.parametrize(
    "mutation",
    [
        "DELETE FROM canonical_fact WHERE company_id = '0000320193' AND canonical_metric = 'PRETAX_INCOME' AND fiscal_year = 2025",
        "DELETE FROM canonical_fact WHERE company_id = '0000320193' AND canonical_metric = 'INCOME_TAX_EXPENSE' AND fiscal_year = 2025",
        "UPDATE canonical_fact SET value = 0 WHERE company_id = '0000320193' AND canonical_metric = 'PRETAX_INCOME' AND fiscal_year = 2025",
    ],
)
def test_tax_rate_fallback_provenance_requires_both_valid_inputs(company_db, mutation):
    from equitylens.valuation.defaults import default_assumption_set

    company_db._conn.execute("BEGIN")
    try:
        company_db._conn.execute(mutation)
        inputs, meta = default_assumption_set(company_db, "0000320193", "AAPL")
        tax_meta = meta["tax_rate"]
        assert inputs.tax_rate == pytest.approx(0.17)
        assert tax_meta["source_type"] == "config_assumption"
        assert tax_meta["source"] == "Tax-rate config fallback"
        assert tax_meta["source_ids"] == []
        assert tax_meta["as_of"] is None
        assert tax_meta["fallback_reason"]
    finally:
        company_db._conn.execute("ROLLBACK")


def test_per_issuer_default_growth_paths_differ(company_db):
    """P01: AAPL and MSFT no longer share one unexplained default growth path."""
    from equitylens.valuation.defaults import default_assumption_set

    aapl, meta_a = default_assumption_set(company_db, "0000320193", "AAPL")
    msft, _ = default_assumption_set(company_db, "0000789019", "MSFT")
    assert aapl.revenue_growth != msft.revenue_growth
    assert aapl.revenue_growth[0] < msft.revenue_growth[0]  # mature vs growth
    assert meta_a["revenue_growth"]["source"]  # every default has a source label
    assert len(meta_a["revenue_growth"]["value"]) == 5


def test_every_default_assumption_has_structured_provenance(company_db):
    """P01: each executable DCF input explains source, time/version and rule."""
    from dataclasses import fields

    from equitylens.valuation.defaults import default_assumption_set

    inputs, meta = default_assumption_set(company_db, "0000320193", "AAPL")
    expected = {field.name for field in fields(inputs)}
    assert expected <= set(meta)
    for name in expected:
        item = meta[name]
        assert item["source_type"] in {
            "canonical_fact", "deterministic_formula", "config_assumption", "user_override"
        }, name
        assert item.get("source"), name
        assert item.get("rule"), name
        assert item.get("reason"), name
        assert item.get("as_of") or item.get("version"), name
        assert item.get("source_ids") or item.get("version"), name
        assert "fallback_reason" in item, name

    shares = meta["shares"]
    assert shares["basis"] == "FY diluted weighted-average shares"
    assert shares["as_of"].startswith("FY")
    assert meta["wacc"]["components"]["debt_weight"] == pytest.approx(0.10)
    assert meta["tax_rate"]["normalization_rule"]


def test_msft_depreciation_sums_separate_components(company_db):
    """D02: MSFT reports Depreciation (34.3B) and AmortizationOfIntangibleAssets
    (4.7B) as separate tags; estimate_depreciation must sum them to 39B instead
    of silently falling back to a revenue percentage."""
    from equitylens.valuation.defaults import estimate_depreciation

    da = estimate_depreciation(company_db, "0000789019", fiscal_year=2026)
    assert da == pytest.approx(34_300_000_000 + 4_700_000_000, rel=1e-6)


def _seed_fact(db, company_id, metric, fy, value, *, unit="USD"):
    db.connect()
    db._conn.execute(
        """INSERT INTO canonical_fact
           (canonical_fact_id, company_id, canonical_metric, period_type, fiscal_year,
            fiscal_quarter, period_start, period_end, instant_date, value, unit, status,
            mapping_rule_id, mapping_version, source_raw_fact_ids, as_known_at, created_at, warnings_json)
           VALUES (?,?,?, 'FY', ?, NULL, NULL, ?, NULL, ?, ?, 'NORMALIZED',
                   ?, 'canonical-mappings.v2', '[]', ?, '2026-01-01 00:00:00', '[]')""",
        [f"{metric}-{fy}", company_id, metric, fy, f"{fy}-06-30", value, unit,
         f"{metric.lower()}.usgaap.v2", "2026-01-01"],
    )


def test_depreciation_prefers_combined_over_separate(db):
    """D02: when a combined D&A line exists, it wins; separate items are not
    double-added."""
    from equitylens.valuation.defaults import estimate_depreciation

    cid = "TEST"
    _seed_fact(db, cid, "DEPRECIATION_AMORTIZATION", 2026, 39e9)
    _seed_fact(db, cid, "DEPRECIATION", 2026, 34.3e9)
    _seed_fact(db, cid, "AMORTIZATION_OF_INTANGIBLE_ASSETS", 2026, 4.7e9)
    assert estimate_depreciation(db, cid, fiscal_year=2026) == pytest.approx(39e9, rel=1e-9)


def test_depreciation_missing_one_component_is_none(db):
    """D02: with only one separate component, do not pretend completeness."""
    from equitylens.valuation.defaults import estimate_depreciation

    cid = "TEST"
    _seed_fact(db, cid, "DEPRECIATION", 2026, 34.3e9)
    assert estimate_depreciation(db, cid, fiscal_year=2026) is None


def test_depreciation_period_mismatch_is_none(db):
    """D02: separate components from different fiscal years must not be summed."""
    from equitylens.valuation.defaults import estimate_depreciation

    cid = "TEST"
    _seed_fact(db, cid, "DEPRECIATION", 2026, 34.3e9)
    _seed_fact(db, cid, "AMORTIZATION_OF_INTANGIBLE_ASSETS", 2025, 4.7e9)
    assert estimate_depreciation(db, cid, fiscal_year=2026) is None


def test_depreciation_uses_requested_valuation_fiscal_year(db):
    """D02: an old combined amount cannot override current split disclosure."""
    from equitylens.valuation.defaults import estimate_depreciation

    cid = "D_AND_A_PERIOD"
    _seed_fact(db, cid, "DEPRECIATION_AMORTIZATION", 2020, 3.0)
    _seed_fact(db, cid, "DEPRECIATION", 2026, 34.3)
    _seed_fact(db, cid, "AMORTIZATION_OF_INTANGIBLE_ASSETS", 2026, 4.7)

    assert estimate_depreciation(db, cid, fiscal_year=2026) == pytest.approx(39.0)
    assert estimate_depreciation(db, cid, fiscal_year=2020) == pytest.approx(3.0)


def test_depreciation_rejects_split_unit_mismatch(db):
    """D02: split D&A components must use the same unit."""
    from equitylens.valuation.defaults import estimate_depreciation

    cid = "D_AND_A_UNIT"
    _seed_fact(db, cid, "DEPRECIATION", 2026, 34.3, unit="USD")
    _seed_fact(db, cid, "AMORTIZATION_OF_INTANGIBLE_ASSETS", 2026, 4.7, unit="EUR")

    assert estimate_depreciation(db, cid, fiscal_year=2026) is None


def test_run_custom_meta_reflects_user_override(company_db):
    """V05: overriding WACC to 12% must update the meta (value + user_override),
    not keep the config-derived 8.5% source."""
    from equitylens.valuation.service import run_custom

    d = run_custom(company_db, "0000320193", "AAPL", {"assumptions": {"wacc": 0.12}})
    assert d["assumptions"]["meta"]["wacc"]["value"] == pytest.approx(0.12)
    assert d["assumptions"]["meta"]["wacc"]["source"] == "user_override"


def test_default_run_reproducible_and_persisted(company_db):
    from equitylens.valuation.service import run_custom

    a = run_custom(company_db, "0000320193", "AAPL", {"assumptions": {"wacc": 0.085}})
    b = run_custom(company_db, "0000320193", "AAPL", {"assumptions": {"wacc": 0.085}})
    assert a["result"]["fair_value_per_share"] == pytest.approx(b["result"]["fair_value_per_share"], rel=1e-12)
    runs = company_db.query("SELECT count(*) n FROM valuation_run")
    assert runs[0]["n"] >= 2
