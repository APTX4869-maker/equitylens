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


def load_valuation_config() -> dict:
    """Return the versioned valuation/default/scenario configuration."""
    return _load_wacc_config()


def _latest_annual_point(store, company_id: str, metric: str):
    engine = MetricEngine(store)
    pts = engine.compute(metric, company_id, frequency="annual")
    return pts[-1] if pts and pts[-1].value is not None else None


def _latest_annual_value(store, company_id: str, metric: str) -> float | None:
    point = _latest_annual_point(store, company_id, metric)
    return float(point.value) if point is not None else None


def _latest_instant_point(store, company_id: str, metric: str):
    points = MetricEngine(store).compute(metric, company_id, frequency="instant")
    return next((point for point in reversed(points) if point.value is not None), None)


def _latest_fy(store, company_id: str, metric: str) -> int | None:
    engine = MetricEngine(store)
    pts = engine.compute(metric, company_id, frequency="annual")
    return pts[-1].fiscal_year if pts else None


def _annual_point(store, company_id: str, metric: str, fiscal_year: int):
    """Return the latest-restated annual point for one exact fiscal year."""
    points = MetricEngine(store).compute(metric, company_id, frequency="annual")
    return next(
        (point for point in reversed(points)
         if point.fiscal_year == fiscal_year and point.value is not None),
        None,
    )


def _depreciation_selection(store, company_id: str, fiscal_year: int,
                            unit: str = "USD") -> tuple[float | None, str, list[str]]:
    combined = _annual_point(store, company_id, "DEPRECIATION_AMORTIZATION", fiscal_year)
    if combined is not None and combined.unit == unit:
        ids = [combined.canonical_fact_id] if combined.canonical_fact_id else list(combined.input_fact_ids or [])
        return float(combined.value), "combined", ids

    dep = _annual_point(store, company_id, "DEPRECIATION", fiscal_year)
    amort = _annual_point(store, company_id, "AMORTIZATION_OF_INTANGIBLE_ASSETS", fiscal_year)
    if dep is None or amort is None or dep.unit != unit or amort.unit != unit:
        return None, "missing", []
    dep_ids = [dep.canonical_fact_id] if dep.canonical_fact_id else list(dep.input_fact_ids or [])
    amort_ids = [amort.canonical_fact_id] if amort.canonical_fact_id else list(amort.input_fact_ids or [])
    return float(dep.value) + float(amort.value), "split", dep_ids + amort_ids


def estimate_depreciation(store, company_id: str, fiscal_year: int,
                          unit: str = "USD") -> float | None:
    """D&A estimate from canonical tags.

    Prefer a single combined concept; otherwise sum the separate Depreciation
    and AmortizationOfIntangibleAssets components for the SAME fiscal year
    (MSFT reports them separately). Returns None when no reliable,
    non-overlapping estimate exists — never a silent fallback here.
    """
    value, _, _ = _depreciation_selection(store, company_id, fiscal_year, unit)
    return value


def default_assumption_set(store, company_id: str, ticker: str,
                           risk_free: float | None = None) -> tuple[DcfInputs, dict]:
    """Build DcfInputs from latest canonical facts + config assumptions.

    Returns (inputs, metadata) where metadata explains each input's source.
    """
    wacc_cfg = _load_wacc_config()
    config_version = f"valuation-defaults.v{wacc_cfg['version']}"
    defaults = wacc_cfg["defaults"]
    issuer = wacc_cfg["issuers"].get(ticker.upper())
    if issuer is None:
        raise ValueError(f"no issuer defaults configured for {ticker}")
    rf = risk_free if risk_free is not None else wacc_cfg["risk_free_rate"]["value"]
    erp = wacc_cfg["equity_risk_premium"]["value"]
    beta = float(issuer["beta"])
    debt_cost = float(issuer["pre_tax_debt_cost"])
    terminal_roic_cfg = wacc_cfg["terminal_roic"]
    terminal_roic = float(terminal_roic_cfg["value"])
    def metadata(value, *, source_type: str, source: str, rule: str, reason: str,
                 source_ids: list[str] | None = None, as_of: str | None = None,
                 version: str | None = None, fallback_reason: str | None = None,
                 **extra) -> dict:
        ids = list(source_ids or [])
        return {
            "value": value,
            "source_type": source_type,
            "source": source,
            "source_ids": ids,
            "fact_ids": ids,  # compatibility for saved-run lineage extraction
            "as_of": as_of,
            "version": version,
            "rule": rule,
            "reason": reason,
            "fallback_reason": fallback_reason,
            **extra,
        }

    revenue_point = _latest_annual_point(store, company_id, "REVENUE")
    fy = revenue_point.fiscal_year if revenue_point is not None else None
    if fy is None:
        raise ValueError("no annual revenue facts; run `equitylens sync` first")
    revenue_history = [
        point for point in MetricEngine(store).compute("REVENUE", company_id, frequency="annual")
        if point.value is not None and point.value > 0
    ][-6:]
    # Duration inputs form one fiscal-year cohort. Missing members may use an
    # explicit config fallback where documented, but never an older FY value.
    op_income_point = _annual_point(store, company_id, "OPERATING_INCOME", fy)
    pretax_point = _annual_point(store, company_id, "PRETAX_INCOME", fy)
    tax_point = _annual_point(store, company_id, "INCOME_TAX_EXPENSE", fy)
    capex_point = _annual_point(store, company_id, "CAPITAL_EXPENDITURES", fy)
    shares_point = _annual_point(store, company_id, "DILUTED_WEIGHTED_AVG_SHARES", fy)
    # The enterprise-to-equity bridge is a point-in-time input. Use the latest
    # available balance sheet and disclose its actual date independently.
    net_debt_point = _latest_instant_point(store, company_id, "NET_DEBT")
    revenue = float(revenue_point.value) if revenue_point is not None else None
    op_income = float(op_income_point.value) if op_income_point is not None else None
    pretax = float(pretax_point.value) if pretax_point is not None else None
    tax = float(tax_point.value) if tax_point is not None else None
    capex = float(capex_point.value) if capex_point is not None else None
    net_debt = float(net_debt_point.value) if net_debt_point is not None else None
    shares = float(shares_point.value) if shares_point is not None else None
    da, da_source_kind, da_fact_ids = (
        _depreciation_selection(store, company_id, fy) if fy is not None else (None, "missing", [])
    )

    def fact_ids(point) -> list[str]:
        if point is None:
            return []
        if point.canonical_fact_id:
            return [point.canonical_fact_id]
        return list(point.input_fact_ids or [])

    if not revenue:
        raise ValueError("no revenue facts; run `equitylens sync` first")
    if op_income is None:
        raise ValueError(f"no FY{fy} operating income facts; cannot derive operating margin")
    op_margin = op_income / revenue
    # Zero is a valid value: a real zero tax rate / CapEx / D&A must stay zero,
    # not be silently replaced by an assumption. Only genuine absence falls back.
    tax_rate_from_facts = tax is not None and pretax is not None and pretax != 0
    tax_rate = (tax / pretax) if tax_rate_from_facts else float(defaults["tax_rate_fallback"]["value"])
    capex_pct = (capex / revenue) if capex is not None else float(defaults["capex_pct_fallback"]["value"])
    da_pct = (da / revenue) if da is not None else float(defaults["da_pct_fallback"]["value"])
    # NET_DEBT = debt - cash - ST investments (positive = net debt);
    # DCF equity bridge adds net cash = -NET_DEBT. A missing bridge forbids a
    # per-share value.
    if net_debt is None:
        raise ValueError("no net-debt bridge; cannot derive net cash")
    net_cash = -net_debt
    if shares is None:
        raise ValueError(f"no FY{fy} diluted share count; cannot produce a per-share value")

    # WACC: E/(D+E)*CoE + D/(D+E)*AfterTaxCoD with documented weights
    # (debt weight assumption 0.10 absent balance-sheet-based weight config)
    debt_weight = float(defaults["debt_weight"]["value"])
    equity_weight = 1 - debt_weight
    coe = rf + beta * erp
    cod_after_tax = debt_cost * (1 - tax_rate)
    wacc = equity_weight * coe + debt_weight * cod_after_tax

    # per-issuer default 5-year growth path (user-adjustable); AAPL and MSFT no
    # longer share one unexplained path (P01).
    growth = list(issuer.get("growth_path") or [0.08, 0.075, 0.07, 0.06, 0.05])
    margin_delta = float(defaults["op_margin_end_delta"]["value"])
    nwc_pct = float(defaults["nwc_pct"]["value"])
    terminal_growth = float(defaults["terminal_growth"]["value"])
    share_basis = "FY diluted weighted-average shares"
    inputs = DcfInputs(
        revenue_base=revenue,
        revenue_growth=growth,
        op_margin_start=op_margin,
        op_margin_end=op_margin + margin_delta,
        tax_rate=tax_rate,
        da_pct=da_pct,
        capex_pct=capex_pct,
        nwc_pct=nwc_pct,
        wacc=wacc,
        terminal_growth=terminal_growth,
        net_cash=net_cash,
        shares=shares,
        share_basis_label=share_basis,
        terminal_roic=terminal_roic,
    )
    period = f"FY{fy}" if fy is not None else None
    net_debt_as_of = net_debt_point.period_end if net_debt_point is not None else None
    revenue_cagr = None
    revenue_history_period = None
    if len(revenue_history) >= 2:
        first, last = revenue_history[0], revenue_history[-1]
        years = (
            last.fiscal_year - first.fiscal_year
            if first.fiscal_year is not None and last.fiscal_year is not None
            else len(revenue_history) - 1
        )
        if years <= 0:
            years = len(revenue_history) - 1
        revenue_cagr = (float(last.value) / float(first.value)) ** (1 / years) - 1
        revenue_history_period = (
            f"FY{first.fiscal_year}–FY{last.fiscal_year}"
            if first.fiscal_year is not None and last.fiscal_year is not None
            else f"{first.period}–{last.period}"
        )
    op_ids = fact_ids(op_income_point) + fact_ids(revenue_point)
    tax_ids = fact_ids(tax_point) + fact_ids(pretax_point) if tax_rate_from_facts else []
    meta: dict = {
        "risk_free": metadata(rf, source_type="config_assumption", source=wacc_cfg["risk_free_rate"]["source"],
                              rule="Use latest Treasury 10Y when available; otherwise documented fallback.",
                              reason="Nominal USD cash flows require a same-currency risk-free component.",
                              as_of=wacc_cfg["risk_free_rate"].get("as_of"), version=config_version,
                              fallback_reason="Treasury feed unavailable; using dated config fallback."),
        "erp": metadata(erp, source_type="config_assumption", source=wacc_cfg["equity_risk_premium"]["source"],
                        rule="Cost of equity = risk-free rate + beta × ERP.",
                        reason="Explicit market-risk premium component for WACC.",
                        version=wacc_cfg["equity_risk_premium"].get("version") or config_version),
        "beta": metadata(beta, source_type="config_assumption", source=issuer["beta_source"],
                         rule="Issuer-specific beta is used in CAPM.", reason="Market beta feed is not configured.",
                         version=config_version, fallback_reason="No market-data beta provider is configured."),
        "debt_cost": metadata(debt_cost, source_type="config_assumption", source=issuer["debt_cost_source"],
                              rule="Apply issuer pre-tax debt cost after the modeled tax rate.",
                              reason="Issuer-specific debt-cost prior for WACC.", version=config_version),
        "revenue_base": metadata(revenue, source_type="canonical_fact", source="SEC 10-K canonical REVENUE",
                                 rule="Select latest-restated annual revenue.",
                                 reason="Forecast starts from the latest complete fiscal-year revenue.",
                                 source_ids=fact_ids(revenue_point), as_of=period, fiscal_year=fy),
        "revenue_growth": metadata(growth, source_type="config_assumption",
                                   source=issuer.get("growth_path_source") or "versioned issuer assumption",
                                   rule="Apply the five issuer-specific annual rates in order; do not extrapolate historical CAGR.",
                                   reason=issuer.get("growth_path_reason") or "Versioned issuer growth prior.",
                                   version=issuer.get("growth_path_version") or config_version,
                                   historical_reference={
                                       "label": "历史收入 CAGR（仅作参照）",
                                       "value": revenue_cagr,
                                       "period": revenue_history_period,
                                       "rule": "首尾年度收入复合增长率；不直接用作未来预测。",
                                   }),
        "op_margin_start": metadata(op_margin, source_type="deterministic_formula",
                                    source="OPERATING_INCOME / REVENUE",
                                    rule="Latest-restated FY operating income divided by same-FY revenue.",
                                    reason="Start the margin path from the latest complete operating result.",
                                    source_ids=op_ids, as_of=period, version="operating-margin.v1"),
        "op_margin_end": metadata(op_margin + margin_delta, source_type="config_assumption",
                                  source="Versioned margin-path assumption",
                                  rule=f"Year-5 margin = latest FY margin + {margin_delta:.3f}; interpolate linearly.",
                                  reason=defaults["op_margin_end_delta"]["reason"], source_ids=op_ids,
                                  as_of=period, version=defaults["op_margin_end_delta"]["version"]),
        "tax_rate": metadata(tax_rate,
                             source_type="deterministic_formula" if tax_rate_from_facts else "config_assumption",
                             source="INCOME_TAX_EXPENSE / PRETAX_INCOME" if tax_rate_from_facts else "Tax-rate config fallback",
                             rule="Use latest same-FY reported effective tax rate; do not silently adjust one-offs.",
                             reason="Use a reproducible effective tax rate and disclose when normalization data is unavailable.",
                             source_ids=tax_ids, as_of=period if tax_rate_from_facts else None,
                             version="effective-tax-rate.v1" if tax_rate_from_facts else defaults["tax_rate_fallback"]["version"],
                             fallback_reason=None if tax_rate_from_facts else defaults["tax_rate_fallback"]["reason"],
                             normalization_rule="Latest reported FY effective rate; no one-off normalization without identified evidence."),
        "da_pct": metadata(da_pct, source_type="deterministic_formula" if da is not None else "config_assumption",
                           source="Canonical D&A / revenue" if da is not None else "D&A ratio config fallback",
                           rule="Same-FY non-overlapping D&A divided by revenue.",
                           reason="Forecast D&A as a stable share of revenue in the simplified model.",
                           source_ids=da_fact_ids + fact_ids(revenue_point) if da is not None else [],
                           as_of=period if da is not None else None,
                           version="da-ratio.v1" if da is not None else defaults["da_pct_fallback"]["version"],
                           fallback_reason=None if da is not None else defaults["da_pct_fallback"]["reason"],
                           source_kind=da_source_kind),
        "capex_pct": metadata(capex_pct, source_type="deterministic_formula" if capex is not None else "config_assumption",
                              source="CAPITAL_EXPENDITURES / REVENUE" if capex is not None else "CapEx ratio config fallback",
                              rule="Latest same-FY CapEx divided by revenue.",
                              reason="Forecast CapEx as a stable share of revenue in the simplified model.",
                              source_ids=fact_ids(capex_point) + fact_ids(revenue_point) if capex is not None else [],
                              as_of=period if capex is not None else None,
                              version="capex-ratio.v1" if capex is not None else defaults["capex_pct_fallback"]["version"],
                              fallback_reason=None if capex is not None else defaults["capex_pct_fallback"]["reason"]),
        "nwc_pct": metadata(nwc_pct, source_type="config_assumption", source="Working-capital config assumption",
                            rule="dNWC = change in revenue × nwc_pct.", reason=defaults["nwc_pct"]["reason"],
                            version=defaults["nwc_pct"]["version"]),
        "wacc": metadata(wacc, source_type="deterministic_formula", source="CAPM plus after-tax debt cost",
                         rule="E/(D+E) × (Rf + beta × ERP) + D/(D+E) × pre-tax debt cost × (1-tax rate).",
                         reason="Discount FCFF using an explicit weighted cost of capital.",
                         version="wacc.v1", components={"risk_free": rf, "erp": erp, "beta": beta,
                                                       "pre_tax_debt_cost": debt_cost,
                                                       "equity_weight": equity_weight, "debt_weight": debt_weight}),
        "terminal_growth": metadata(terminal_growth, source_type="config_assumption",
                                    source="Stable-period growth config assumption",
                                    rule="Grow year-5 revenue once into year 6, then use in the stable-period formula.",
                                    reason=defaults["terminal_growth"]["reason"],
                                    version=defaults["terminal_growth"]["version"]),
        "net_cash": metadata(net_cash, source_type="deterministic_formula", source="NET_DEBT sign reversal",
                             rule="net_cash = -NET_DEBT from the latest balance-sheet date.",
                             reason="Bridge enterprise value to equity value using the latest available balance sheet.",
                             source_ids=fact_ids(net_debt_point), as_of=net_debt_as_of,
                             version="net-cash-bridge.v1"),
        "shares": metadata(shares, source_type="canonical_fact", source="SEC canonical diluted weighted-average shares",
                           rule="Use latest FY diluted weighted-average shares as a per-share approximation.",
                           reason="Use the disclosed diluted basis; current point-in-time shares are not yet modeled.",
                           source_ids=fact_ids(shares_point), as_of=period, basis=share_basis),
        "share_basis_label": metadata(share_basis, source_type="canonical_fact",
                                     source="Share fact accounting basis",
                                     rule="Copy the basis label from the selected diluted-share fact policy.",
                                     reason="Display the actual selected share basis without inferring from magnitude.",
                                     source_ids=fact_ids(shares_point), as_of=period),
        "terminal_roic": metadata(terminal_roic, source_type="config_assumption",
                                  source=terminal_roic_cfg["source"],
                                  rule="Stable reinvestment rate = terminal growth / terminal ROIC.",
                                  reason="Link stable growth to required reinvestment.",
                                  version=terminal_roic_cfg.get("version") or config_version),
    }
    # Compatibility alias for old saved-run readers; executable inputs use the
    # explicit start/end keys above.
    meta["op_margin"] = dict(meta["op_margin_start"])
    return inputs, meta
