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


class ValuationError(ValueError):
    """Structured domain validation error (V01).

    ``code`` is a stable machine-readable status, ``field`` names the offending
    input (or ``None``), and the string form carries the human-readable reason.
    """

    def __init__(self, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


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
    import math

    warnings: list[str] = []
    if len(inputs.revenue_growth) != FORECAST_YEARS:
        raise ValuationError(
            "INVALID_ASSUMPTION",
            f"revenue_growth must have {FORECAST_YEARS} entries",
            "revenue_growth",
        )

    # finite-value guard: NaN/Inf must never flow into a price.
    numeric = {
        "revenue_base": inputs.revenue_base,
        "tax_rate": inputs.tax_rate,
        "op_margin_start": inputs.op_margin_start,
        "op_margin_end": inputs.op_margin_end,
        "da_pct": inputs.da_pct,
        "capex_pct": inputs.capex_pct,
        "nwc_pct": inputs.nwc_pct,
        "wacc": inputs.wacc,
        "terminal_growth": inputs.terminal_growth,
        "net_cash": inputs.net_cash,
        "shares": inputs.shares,
    }
    for name, v in numeric.items():
        if not math.isfinite(v):
            raise ValuationError("INVALID_ASSUMPTION", f"{name} must be a finite number", name)
    for i, g in enumerate(inputs.revenue_growth):
        if not math.isfinite(g) or g < -1.0:
            raise ValuationError(
                "INVALID_ASSUMPTION",
                f"revenue_growth[{i}] must be finite and >= -100% (got {g})",
                f"revenue_growth[{i}]",
            )

    # model-compatible bounds. Zero is a VALID value and must not be coerced;
    # only out-of-range values are rejected.
    if not 0.0 <= inputs.tax_rate <= 1.0:
        raise ValuationError(
            "INVALID_ASSUMPTION",
            f"tax_rate must be within [0, 1] (got {inputs.tax_rate})",
            "tax_rate",
        )
    if inputs.op_margin_start > 1.0:
        raise ValuationError("INVALID_ASSUMPTION", "operating margin must not exceed 100%", "op_margin_start")
    if inputs.op_margin_end > 1.0:
        raise ValuationError("INVALID_ASSUMPTION", "operating margin must not exceed 100%", "op_margin_end")
    if inputs.da_pct < 0:
        raise ValuationError("INVALID_ASSUMPTION", f"da_pct must be >= 0 (got {inputs.da_pct})", "da_pct")
    if inputs.capex_pct < 0:
        raise ValuationError("INVALID_ASSUMPTION", f"capex_pct must be >= 0 (got {inputs.capex_pct})", "capex_pct")
    if inputs.wacc <= -1.0:
        raise ValuationError("INVALID_ASSUMPTION", f"wacc must be > -1 (got {inputs.wacc})", "wacc")
    if inputs.wacc - inputs.terminal_growth < MIN_WACC_G_MARGIN - 1e-9:
        raise ValuationError(
            "INVALID_ASSUMPTION",
            f"WACC − terminal growth must be at least {MIN_WACC_G_MARGIN:.1%} "
            f"(got WACC {inputs.wacc:.2%}, terminal growth {inputs.terminal_growth:.2%})",
            "wacc",
        )
    if inputs.shares <= 0:
        raise ValuationError("INVALID_ASSUMPTION", "share count must be positive", "shares")
    if inputs.revenue_base <= 0:
        raise ValuationError("INVALID_ASSUMPTION", "revenue base must be positive", "revenue_base")
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
        previous_revenue = revenue
        revenue = previous_revenue * (1 + g)
        progress = (t - 1) / (FORECAST_YEARS - 1) if FORECAST_YEARS > 1 else 1.0
        margin = inputs.op_margin_start + (inputs.op_margin_end - inputs.op_margin_start) * progress
        ebit = revenue * margin
        nopat = ebit * (1 - inputs.tax_rate)
        da = revenue * inputs.da_pct
        capex = revenue * inputs.capex_pct
        nwc_delta = (revenue - previous_revenue) * inputs.nwc_pct
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


# --- P02: explicit-amount forecast (5-year EBIT / D&A / CapEx / dNWC paths) ---
# This is the verification mode used to hand-check FCFF/PV/TV/EV/per-share:
#   FCFF_t = EBIT_t*(1-tax) + D&A_t - CapEx_t - dNWC_t
# Terminal FCFF comes from explicit terminal-year inputs (default: last forecast
# year). Terminal growth may be zero (a valid stable state, not an error).

def run_dcf_explicit(
    ebit: list[float],
    da: list[float],
    capex: list[float],
    tax_rate: float,
    wacc: float,
    terminal_growth: float,
    net_cash: float,
    shares: float,
    nwc_delta: list[float] | None = None,
    terminal_ebit: float | None = None,
    terminal_da: float | None = None,
    terminal_capex: float | None = None,
    terminal_nwc_delta: float | None = None,
) -> DcfOutput:
    import math

    if len(ebit) != FORECAST_YEARS or len(da) != FORECAST_YEARS or len(capex) != FORECAST_YEARS:
        raise ValuationError(
            "INVALID_ASSUMPTION", f"explicit paths must each have {FORECAST_YEARS} entries", "ebit"
        )
    nwc = nwc_delta if nwc_delta is not None else [0.0] * FORECAST_YEARS
    if len(nwc) != FORECAST_YEARS:
        raise ValuationError("INVALID_ASSUMPTION", f"nwc_delta must have {FORECAST_YEARS} entries", "nwc_delta")

    for v in (*ebit, *da, *capex, *nwc, tax_rate, wacc, terminal_growth, net_cash, shares):
        if not math.isfinite(v):
            raise ValuationError("INVALID_ASSUMPTION", "explicit-forecast inputs must be finite")
    # terminal-year inputs are optional; when provided they must be finite and
    # must not silently produce a NaN fair value.
    for name, v in (
        ("terminal_ebit", terminal_ebit),
        ("terminal_da", terminal_da),
        ("terminal_capex", terminal_capex),
        ("terminal_nwc_delta", terminal_nwc_delta),
    ):
        if v is not None and not math.isfinite(v):
            raise ValuationError("INVALID_ASSUMPTION", f"{name} must be finite", name)
    if not 0.0 <= tax_rate <= 1.0:
        raise ValuationError("INVALID_ASSUMPTION", "tax_rate must be within [0, 1]", "tax_rate")
    if shares <= 0:
        raise ValuationError("INVALID_ASSUMPTION", "share count must be positive", "shares")
    if wacc <= terminal_growth:
        raise ValuationError("INVALID_ASSUMPTION", "WACC must exceed terminal growth", "wacc")

    t_ebit = terminal_ebit if terminal_ebit is not None else ebit[-1]
    t_da = terminal_da if terminal_da is not None else da[-1]
    t_capex = terminal_capex if terminal_capex is not None else capex[-1]
    t_nwc = terminal_nwc_delta if terminal_nwc_delta is not None else nwc[-1]
    terminal_fcff = t_ebit * (1 - tax_rate) + t_da - t_capex - t_nwc

    forecast: list[YearForecast] = []
    sum_pv_fcff = 0.0
    for t in range(1, FORECAST_YEARS + 1):
        i = t - 1
        fcff = ebit[i] * (1 - tax_rate) + da[i] - capex[i] - nwc[i]
        pv = fcff / (1 + wacc) ** t
        sum_pv_fcff += pv
        forecast.append(YearForecast(
            year=t, revenue=0.0, op_margin=0.0, ebit=ebit[i],
            nopat=ebit[i] * (1 - tax_rate), da=da[i], capex=capex[i],
            nwc_delta=nwc[i], fcff=fcff, pv_fcff=pv,
        ))

    tv = terminal_fcff * (1 + terminal_growth) / (wacc - terminal_growth)
    pv_terminal = tv / (1 + wacc) ** FORECAST_YEARS
    ev = sum_pv_fcff + pv_terminal
    equity = ev + net_cash
    fair = equity / shares
    tv_share = pv_terminal / ev if ev else 0.0
    warnings: list[str] = []
    if not (0 < terminal_growth < wacc):
        warnings.append("terminal growth outside safe band; double-check assumption")
    return DcfOutput(
        fair_value_per_share=fair,
        enterprise_value=ev,
        equity_value=equity,
        terminal_value=tv,
        pv_terminal=pv_terminal,
        sum_pv_fcff=sum_pv_fcff,
        net_cash=net_cash,
        terminal_value_share=tv_share,
        forecast=forecast,
        warnings=warnings,
    )
