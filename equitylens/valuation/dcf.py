"""FCFF DCF valuation engine (M5) — deterministic, versioned, reproducible.

Model: 5-year FCFF forecast -> PV @ WACC -> terminal value -> EV -> equity.

FCFF_t = NOPAT_t + D&A_t - CapEx_t - dNWC_t
  NOPAT_t = EBIT_t * (1 - tax_rate)
  D&A_t   = Revenue_t * da_pct
  CapEx_t = Revenue_t * capex_pct
  dNWC_t  = (Revenue_t - Revenue_{t-1}) * nwc_pct

Guardrails (docs/06):
- WACC must exceed terminal growth by a safe margin (>= 1.0pp by default)
- per-share value states its share-count basis
- same inputs + model version reproduce the same output
"""

from __future__ import annotations

from dataclasses import dataclass, field

MODEL_VERSION = "fcff_dcf.v1"
FORECAST_YEARS = 5
MIN_WACC_G_MARGIN = 0.01  # 1.0 percentage point


class ValuationError(Exception):
    pass


@dataclass
class DcfInputs:
    revenue_base: float
    revenue_growth: list[float]  # len == 5, per-year YoY
    op_margin_start: float       # first-year operating margin (0.32 = 32%)
    op_margin_end: float         # fifth-year margin; linear path in between
    tax_rate: float
    da_pct: float                # D&A as % of revenue
    capex_pct: float             # CapEx as % of revenue
    nwc_pct: float               # dNWC as % of revenue change
    wacc: float
    terminal_growth: float
    net_cash: float              # cash + ST investments - debt (can be negative)
    shares: float                # share-count basis (diluted)
    share_basis_label: str = "latest fiscal-year diluted weighted-average shares"


@dataclass
class YearForecast:
    year: int
    revenue: float
    op_margin: float
    ebit: float
    nopat: float
    da: float
    capex: float
    nwc_delta: float
    fcff: float
    pv_fcff: float


@dataclass
class DcfOutput:
    fair_value_per_share: float
    enterprise_value: float
    equity_value: float
    terminal_value: float
    pv_terminal: float
    sum_pv_fcff: float
    net_cash: float
    terminal_value_share: float  # % of EV from terminal value
    forecast: list[YearForecast]
    model_version: str = MODEL_VERSION
    warnings: list[str] = field(default_factory=list)


def validate(inputs: DcfInputs) -> list[str]:
    warnings: list[str] = []
    if len(inputs.revenue_growth) != FORECAST_YEARS:
        raise ValuationError(f"revenue_growth must have {FORECAST_YEARS} entries")
    if inputs.wacc <= inputs.terminal_growth + MIN_WACC_G_MARGIN:
        raise ValuationError(
            f"WACC ({inputs.wacc:.2%}) must exceed terminal growth "
            f"({inputs.terminal_growth:.2%}) by at least {MIN_WACC_G_MARGIN:.1%}"
        )
    if inputs.shares <= 0:
        raise ValuationError("share count must be positive")
    if inputs.revenue_base <= 0:
        raise ValuationError("revenue base must be positive")
    if not (0 < inputs.terminal_growth < inputs.wacc):
        warnings.append("terminal growth outside safe band; double-check assumption")
    return warnings


def run_dcf(inputs: DcfInputs) -> DcfOutput:
    warnings = validate(inputs)
    revenue = inputs.revenue_base
    forecast: list[YearForecast] = []
    sum_pv_fcff = 0.0
    for t in range(1, FORECAST_YEARS + 1):
        g = inputs.revenue_growth[t - 1]
        revenue = revenue * (1 + g)
        progress = (t - 1) / (FORECAST_YEARS - 1) if FORECAST_YEARS > 1 else 1.0
        margin = inputs.op_margin_start + (inputs.op_margin_end - inputs.op_margin_start) * progress
        ebit = revenue * margin
        nopat = ebit * (1 - inputs.tax_rate)
        da = revenue * inputs.da_pct
        capex = revenue * inputs.capex_pct
        prev_rev = revenue / (1 + g) if (1 + g) else revenue
        nwc_delta = (revenue - prev_rev) * inputs.nwc_pct
        fcff = nopat + da - capex - nwc_delta
        pv = fcff / (1 + inputs.wacc) ** t
        sum_pv_fcff += pv
        forecast.append(
            YearForecast(
                year=t, revenue=revenue, op_margin=margin, ebit=ebit, nopat=nopat,
                da=da, capex=capex, nwc_delta=nwc_delta, fcff=fcff, pv_fcff=pv,
            )
        )
    last_fcff = forecast[-1].fcff
    tv = last_fcff * (1 + inputs.terminal_growth) / (inputs.wacc - inputs.terminal_growth)
    pv_terminal = tv / (1 + inputs.wacc) ** FORECAST_YEARS
    ev = sum_pv_fcff + pv_terminal
    equity = ev + inputs.net_cash
    fair = equity / inputs.shares
    tv_share = pv_terminal / ev if ev else 0.0
    return DcfOutput(
        fair_value_per_share=fair,
        enterprise_value=ev,
        equity_value=equity,
        terminal_value=tv,
        pv_terminal=pv_terminal,
        sum_pv_fcff=sum_pv_fcff,
        net_cash=inputs.net_cash,
        terminal_value_share=tv_share,
        forecast=forecast,
        warnings=warnings,
    )


def implied_growth(inputs: DcfInputs, target_price: float, lo: float = -0.05,
                   hi: float = 0.35, tol: float = 1e-9, max_iter: int = 100) -> float | None:
    """Reverse DCF: solve a single implied 5Y revenue CAGR s.t. fair == target.

    All other assumptions are held fixed; bisection over the growth path
    (same rate applied to every forecast year). Returns None when no root
    exists within [lo, hi].
    """
    def fair_at(g: float) -> float:
        trial = DcfInputs(
            revenue_base=inputs.revenue_base,
            revenue_growth=[g] * FORECAST_YEARS,
            op_margin_start=inputs.op_margin_start,
            op_margin_end=inputs.op_margin_end,
            tax_rate=inputs.tax_rate, da_pct=inputs.da_pct, capex_pct=inputs.capex_pct,
            nwc_pct=inputs.nwc_pct, wacc=inputs.wacc, terminal_growth=inputs.terminal_growth,
            net_cash=inputs.net_cash, shares=inputs.shares,
        )
        return run_dcf(trial).fair_value_per_share

    f_lo = fair_at(lo) - target_price
    f_hi = fair_at(hi) - target_price
    if f_lo == 0:
        return lo
    if f_hi == 0:
        return hi
    if f_lo * f_hi > 0:
        return None  # no root in bounds (e.g., price below/above achievable range)
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        f_mid = fair_at(mid) - target_price
        if abs(f_mid) < tol or (hi - lo) / 2 < tol:
            return mid
        if f_lo * f_mid <= 0:
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid
    return (lo + hi) / 2.0
