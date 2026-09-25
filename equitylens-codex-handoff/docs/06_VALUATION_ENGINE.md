# Valuation Engine Specification

## 1. Philosophy

EquityLens must not present a single precise “target price” as truth.

Primary output:

> **Reference Value Range** + assumptions + sensitivity + reverse DCF + model confidence.

Valuation is a research input, not a trading signal.

## 2. Model selection by company archetype

The engine should support pluggable model families.

Initial archetype:

**Mature / high-quality technology or software company**

Recommended methods:

- FCFF DCF
- historical P/E / P/FCF / FCF yield
- peer multiple comparison
- reverse DCF

Future examples:

- Banks: P/B + ROE + dividend/residual-income approaches
- Insurers: P/B/ROE + embedded-value concepts when available
- REITs: P/FFO + NAV
- unprofitable growth SaaS: EV/Sales + long-horizon scenario model
- cyclical companies: normalized earnings / mid-cycle EBITDA

Do not apply one generic DCF template blindly to every sector.

## 3. FCFF DCF

### Forecast

For year `t`:

```text
Revenue_t = Revenue_(t-1) * (1 + growth_t)
EBIT_t = Revenue_t * operating_margin_t
NOPAT_t = EBIT_t * (1 - normalized_tax_rate_t)
FCFF_t = NOPAT_t + D&A_t - CapEx_t - ΔNWC_t
```

V0.x may model D&A, CapEx and NWC as explicit ratios to revenue based on historical evidence, but each ratio must be visible as an assumption.

### Present value

```text
PV(FCFF_t) = FCFF_t / (1 + WACC)^t
Terminal Value = FCFF_(n+1) / (WACC - g)
Enterprise Value = sum(PV(FCFF)) + PV(Terminal Value)
Equity Value = Enterprise Value + excess cash/investments - debt - other claims
Fair Value Per Share = Equity Value / share_count_basis
```

Guardrail: require `WACC > terminal_growth` with a safe margin.

## 4. WACC

```text
Cost of Equity = Risk-free Rate + Beta * Equity Risk Premium
After-tax Cost of Debt = pre-tax debt cost * (1 - tax rate)
WACC = E/(D+E)*CoE + D/(D+E)*AfterTaxCoD
```

Data/provenance requirements:

- risk-free rate: timestamped U.S. Treasury source or a documented equivalent
- beta: reproducible calculation with price provider, benchmark, frequency and lookback window; or labeled third-party value
- ERP: configured source/value/date/version; never an unexplained hard-coded constant
- debt cost: sourced/derived and documented

## 5. Share count basis

Per-share valuation must state its denominator:

- latest common shares outstanding, or
- a documented diluted-share approximation

Do not silently mix weighted-average diluted shares with current shares outstanding.

## 6. Bear / Base / Bull scenarios

Scenarios are assumption sets, not independent “AI price targets.”

At minimum vary:

- revenue growth path
- margin path
- reinvestment / CapEx path
- WACC if justified
- terminal growth

Store all scenario assumptions and model outputs.

Reference range can be derived from scenario values or a defined subset; the UI must state the method.

## 7. Sensitivity matrix

Default view: WACC × terminal growth, recalculating the complete DCF.

Example grid:

- WACC: base ± 0.5% / ±1.0%
- terminal growth: base ± 0.25% / ±0.5%

Do not fake sensitivity by scaling the base price.

## 8. Reverse DCF

Given current market price and fixed assumptions, solve for one chosen implied variable, initially 5Y revenue CAGR.

Use root finding/bisection with bounded intervals and return failure if no sensible root exists.

Output:

- implied revenue CAGR
- historical CAGR
- explicit fixed assumptions
- interpretation, not a buy/sell instruction

## 9. Relative valuation

### Current multiples

- P/E
- P/FCF
- FCF Yield
- EV/EBIT or EV/EBITDA when cleanly supported

### Historical percentile

Must be point-in-time safe:

```text
historical price at date t / fundamentals actually available at t
```

Do not use current/restated future-known fundamentals to reconstruct historical multiples without labeling the bias.

### Peer comparison

Peer sets should be curated/versioned. Compare multiple, growth and cash-flow quality together.

## 10. Model confidence

Confidence is not “probability the price is correct.” It is an assessment of model appropriateness/predictability.

Possible rubric inputs:

- revenue stability
- margin stability
- FCF stability
- cyclicality
- balance-sheet complexity
- dependence on terminal value
- dispersion between scenarios
- amount of estimated vs disclosed input data

Return `HIGH | MEDIUM | LOW` plus reasons.

## 11. Reproducibility

Persist every valuation run:

- model version
- timestamp
- canonical fact snapshot IDs
- market-data snapshot
- assumption set
- scenario outputs
- sensitivity outputs
- reverse DCF result

The same inputs and model version must reproduce the same output.
