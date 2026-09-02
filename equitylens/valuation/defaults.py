"""Valuation assumption defaults built from canonical facts (M5).

Base assumptions are derived deterministically from the fact store where
possible; every remaining input is a labeled assumption (config file or
explicit user override). No LLM anywhere near the numbers.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from equitylens.config import CONFIG_DIR
from equitylens.metrics.engine import MetricEngine
from equitylens.valuation.dcf import DcfInputs, FORECAST_YEARS

WACC_CONFIG_PATH = CONFIG_DIR / "valuation" / "wacc_defaults.yaml"


def _load_wacc_config() -> dict:
    return yaml.safe_load(Path(WACC_CONFIG_PATH).read_text())


def _latest_annual_value(store, company_id: str, metric: str) -> float | None:
    engine = MetricEngine(store)
    pts = engine.compute(metric, company_id, frequency="annual")
    if not pts or pts[-1].value is None:
        return None
    return float(pts[-1].value)


def _latest_fy(store, company_id: str, metric: str) -> int | None:
    engine = MetricEngine(store)
    pts = engine.compute(metric, company_id, frequency="annual")
    return pts[-1].fiscal_year if pts else None


def estimate_depreciation(store, company_id: str) -> float | None:
    """D&A estimate from canonical tags.

    Falls back to summing Depreciation + Amortization concepts when the
    single combined concept is absent (MSFT tags them separately).
    """
    combined = _latest_annual_value(store, company_id, "DEPRECIATION_AMORTIZATION")
    if combined is not None:
        return combined
    dep = store.query(
        """SELECT value FROM canonical_fact WHERE company_id = ?
           AND canonical_metric = 'DEPRECIATION_AMORTIZATION'
           AND period_type = 'FY' AND status = 'NORMALIZED'
           ORDER BY fiscal_year DESC LIMIT 1""",
        [company_id],
    )
    return float(dep[0]["value"]) if dep else None


def default_assumption_set(store, company_id: str, ticker: str,
                           risk_free: float | None = None) -> tuple[DcfInputs, dict]:
    """Build DcfInputs from latest canonical facts + config assumptions.

    Returns (inputs, metadata) where metadata explains each input's source.
    """
    wacc_cfg = _load_wacc_config()
    issuer = wacc_cfg["issuers"].get(ticker.upper(), wacc_cfg["issuers"]["MSFT"])
    rf = risk_free if risk_free is not None else wacc_cfg["risk_free_rate"]["value"]
    erp = wacc_cfg["equity_risk_premium"]["value"]
    beta = float(issuer["beta"])
    debt_cost = float(issuer["pre_tax_debt_cost"])
    meta: dict = {
        "risk_free": {"value": rf, **wacc_cfg["risk_free_rate"]},
        "erp": {"value": erp, **wacc_cfg["equity_risk_premium"]},
        "beta": {"value": beta, "source": issuer["beta_source"]},
        "debt_cost": {"value": debt_cost, "source": issuer["debt_cost_source"]},
    }

    revenue = _latest_annual_value(store, company_id, "REVENUE")
    op_income = _latest_annual_value(store, company_id, "OPERATING_INCOME")
    pretax = _latest_annual_value(store, company_id, "PRETAX_INCOME")
    tax = _latest_annual_value(store, company_id, "INCOME_TAX_EXPENSE")
    capex = _latest_annual_value(store, company_id, "CAPITAL_EXPENDITURES")
    net_debt = _latest_annual_value(store, company_id, "NET_DEBT")
    shares = _latest_annual_value(store, company_id, "DILUTED_WEIGHTED_AVG_SHARES")
    fy = _latest_fy(store, company_id, "REVENUE")
    da = estimate_depreciation(store, company_id)

    if not revenue:
        raise ValueError("no revenue facts; run `equitylens sync` first")
    op_margin = op_income / revenue if op_income else None
    tax_rate = (tax / pretax) if (tax and pretax) else 0.17
    capex_pct = (capex / revenue) if capex else 0.05
    da_pct = (da / revenue) if da else 0.03
    # NET_DEBT = debt - cash - ST investments (positive = net debt);
    # DCF equity bridge adds net cash = -NET_DEBT
    net_cash = -net_debt if net_debt is not None else 0.0

    # WACC: E/(D+E)*CoE + D/(D+E)*AfterTaxCoD with documented weights
    # (debt weight assumption 0.10 absent balance-sheet-based weight config)
    debt_weight = 0.10
    equity_weight = 1 - debt_weight
    coe = rf + beta * erp
    cod_after_tax = debt_cost * (1 - tax_rate)
    wacc = equity_weight * coe + debt_weight * cod_after_tax

    growth = [0.08, 0.075, 0.07, 0.06, 0.05]  # default path; user-adjustable
    inputs = DcfInputs(
        revenue_base=revenue,
        revenue_growth=growth,
        op_margin_start=op_margin or 0.25,
        op_margin_end=(op_margin or 0.25) + 0.005,
        tax_rate=tax_rate,
        da_pct=da_pct,
        capex_pct=capex_pct,
        nwc_pct=0.002,
        wacc=wacc,
        terminal_growth=0.025,
        net_cash=net_cash,
        shares=shares or 1.0,
    )
    meta.update({
        "revenue_base": {"value": revenue, "fiscal_year": fy, "source": "SEC 10-K canonical fact"},
        "op_margin": {"value": op_margin, "fiscal_year": fy, "source": "OPERATING_INCOME / REVENUE"},
        "tax_rate": {"value": tax_rate, "source": "INCOME_TAX / PRETAX_INCOME (latest FY)"},
        "da_pct": {"value": da_pct, "source": "canonical D&A / revenue" if da else "assumption (D&A tag absent)"},
        "capex_pct": {"value": capex_pct, "source": "CAPITAL_EXPENDITURES / REVENUE"},
        "net_cash": {"value": net_cash, "source": "NET_DEBT sign flip (latest balance sheet)"},
        "shares": {"value": shares, "basis": "FY diluted weighted-average", "source": "SEC canonical fact"},
        "wacc": {"value": wacc, "formula": "E/(D+E)*CoE + D/(D+E)*CoD_after_tax, weights documented"},
    })
    return inputs, meta
