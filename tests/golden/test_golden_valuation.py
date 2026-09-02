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
    assert a.model_version == "fcff_dcf.v1"


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


def test_sensitivity_recalculates():
    from equitylens.valuation.service import sensitivity

    sens = sensitivity(make_inputs())
    assert len(sens["rows"]) == 5 and len(sens["terminal_grid"]) == 5
    # the grid must contain the exact base inputs cell
    base_fair = run_dcf(make_inputs()).fair_value_per_share
    center = sens["rows"][2]["values"][2]
    assert center == pytest.approx(base_fair, rel=1e-6)


def test_defaults_built_from_real_facts(company_db):
    """Assumption defaults reflect real canonical facts (AAPL)."""
    from equitylens.valuation.defaults import default_assumption_set

    inputs, meta = default_assumption_set(company_db, "0000320193", "AAPL")
    assert inputs.revenue_base == pytest.approx(416_161_000_000, rel=1e-6)
    assert inputs.op_margin_start == pytest.approx(133_050 / 416_161, rel=1e-4)
    assert inputs.capex_pct == pytest.approx(12_715 / 416_161, rel=1e-4)
    assert meta["revenue_base"]["source"].startswith("SEC")
    assert inputs.wacc > inputs.terminal_growth + 0.01


def test_default_run_reproducible_and_persisted(company_db):
    from equitylens.valuation.service import run_custom

    a = run_custom(company_db, "0000320193", "AAPL", {"assumptions": {"wacc": 0.085}})
    b = run_custom(company_db, "0000320193", "AAPL", {"assumptions": {"wacc": 0.085}})
    assert a["result"]["fair_value_per_share"] == pytest.approx(b["result"]["fair_value_per_share"], rel=1e-12)
    runs = company_db.query("SELECT count(*) n FROM valuation_run")
    assert runs[0]["n"] >= 2
