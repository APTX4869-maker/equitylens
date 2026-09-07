# EquityLens Remediation Batch 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> 状态回填（2026-09-07）：本计划各步骤已在 Batch 1 及后续边界补修中完成；最终全量验证为后端 220 passed、Playwright 9 passed，详见 `docs/reviews/2026-09-06-remediation-progress.md`。

**Goal:** Eliminate the reviewed paths that can return an incorrect financial value or associate a valuation result with the wrong ticker or input draft.

**Architecture:** Add explicit period-selection and current-TTM contracts in the existing metric layer, then make market, risk, and research consumers use those contracts. Tighten valuation inputs at the pure engine boundary and carry one complete, fingerprinted draft through the API and React client so stale responses cannot become saveable results.

**Tech Stack:** Python 3.12, FastAPI, DuckDB, pytest, Next.js 16.3.3, React 19.2.8, TypeScript, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-06-remediation-rework-design.md`

## Global Constraints

- Preserve existing raw snapshots, valuation runs, plans, and database backups.
- A numeric zero is valid; only `None`/`null` means missing.
- Invalid or incomplete current data must not fall back to an older valid-looking result.
- Negative operating profit, FCFF, or equity value may remain valid economic outputs.
- Preview requests never persist; only an explicit save persists an immutable run.
- New tests use temporary stores and deterministic fixtures. Do not write to the real user database.
- Keep current AAPL/MSFT support scope and existing Python/FastAPI/DuckDB and Next.js/React architecture.

---

### Task 1: Normalize Quarter Date Inputs

**Files:**
- Modify: `equitylens/normalization/fiscal_periods.py:227`
- Test: `tests/unit/test_fiscal_periods.py`

**Interfaces:**
- Consumes: fact dictionaries whose `period_start` and `period_end` may be `date`, `datetime`, or ISO strings.
- Produces: `_iso_date(value: object) -> str | None`, used by `derive_standalone_quarters` for matching and emitted period fields.

- [x] **Step 1: Write the failing date-equivalence regression**

Add a parametrized test that passes the same FY and YTD facts once with ISO strings and once with `datetime.date` values. Use literal inputs FY=400 and YTD9=300 and assert both derive FY2025Q4 value `100`, the same input IDs, and ISO `period_end`.

```python
@pytest.mark.parametrize("as_date", [False, True])
def test_q4_derivation_accepts_date_and_iso_periods(as_date):
    end = date(2025, 6, 30) if as_date else "2025-06-30"
    q3 = date(2025, 3, 31) if as_date else "2025-03-31"
    facts = [
        {"canonical_fact_id": "fy", "canonical_metric": "OCF", "period_type": "FY",
         "fiscal_quarter": None, "period_end": end, "value": 400.0, "unit": "USD",
         "as_known_at": "2026-01-01"},
        {"canonical_fact_id": "ytd9", "canonical_metric": "OCF", "period_type": "YTD_9M",
         "fiscal_quarter": 3, "period_end": q3, "value": 300.0, "unit": "USD",
         "as_known_at": "2025-10-30"},
    ]
    result = derive_standalone_quarters(facts, 2025, make_calendar())
    q4 = next(row for row in result if row["fiscal_quarter"] == 4)
    assert q4["value"] == 100.0
    assert q4["period_end"] == "2025-06-30"
    assert q4["input_ids"] == ["ytd9", "fy"]
```

- [x] **Step 2: Verify the regression fails for `date` values**

Run: `.venv/bin/python -m pytest tests/unit/test_fiscal_periods.py -k date_and_iso -q -p no:cacheprovider`

Expected: the string case passes and the `date` case has no Q4 result.

- [x] **Step 3: Add one date normalization boundary**

Implement `_iso_date` with explicit support for `datetime`, `date`, and ISO-compatible strings. Use it in `pick`, `diff`, and emitted derived period fields; do not compare database objects directly to strings.

```python
def _iso_date(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None
```

- [x] **Step 4: Verify all fiscal-period regressions**

Run: `.venv/bin/python -m pytest tests/unit/test_fiscal_periods.py -q -p no:cacheprovider`

Expected: all tests pass, including existing missing-bucket and restatement cases.

- [x] **Step 5: Commit the focused change**

```bash
git add equitylens/normalization/fiscal_periods.py tests/unit/test_fiscal_periods.py
git commit -m "fix: normalize fiscal period date inputs"
```

---

### Task 2: Select D&A for the Valuation Base Period

**Files:**
- Modify: `equitylens/valuation/defaults.py:26`
- Test: `tests/golden/test_golden_valuation.py`

**Interfaces:**
- Consumes: annual canonical D&A, depreciation, amortization, and revenue facts.
- Produces: `estimate_depreciation(store, company_id: str, fiscal_year: int, unit: str = "USD") -> float | None`.
- Produces: metadata identifying combined, split, or estimated D&A and the selected fiscal year.

- [x] **Step 1: Write the failing base-period selection regression**

Build a temporary store with FY2020 combined D&A `3`, FY2026 depreciation `34.3`, FY2026 amortization `4.7`, and FY2026 revenue. Assert the target-period call returns `39`, while a call for FY2020 returns `3`.

```python
def test_depreciation_uses_requested_valuation_fiscal_year(db):
    cid = "TEST"
    _seed_fact(db, cid, "DEPRECIATION_AMORTIZATION", 2020, 3.0)
    _seed_fact(db, cid, "DEPRECIATION", 2026, 34.3)
    _seed_fact(db, cid, "AMORTIZATION_OF_INTANGIBLE_ASSETS", 2026, 4.7)
    assert estimate_depreciation(db, cid, fiscal_year=2026) == pytest.approx(39.0)
    assert estimate_depreciation(db, cid, fiscal_year=2020) == pytest.approx(3.0)
```

Add separate literal cases where split components have different years or units; both must return `None`.

- [x] **Step 2: Verify the old combined value wins incorrectly**

Run: `.venv/bin/python -m pytest tests/golden/test_golden_valuation.py -k requested_valuation_fiscal_year -q -p no:cacheprovider`

Expected: FAIL because the current function returns the latest combined value without constraining it to FY2026.

- [x] **Step 3: Query annual observations by period and unit**

Replace separate latest-value/latest-year calls with a helper returning a selected `MetricPoint` for an exact fiscal year. Within the target year, prefer the reliable combined metric; otherwise require both split metrics in the same year and unit before summing.

```python
def _annual_point(store, company_id: str, metric: str, fiscal_year: int):
    return next(
        (p for p in MetricEngine(store).compute(metric, company_id, "annual")
         if p.fiscal_year == fiscal_year and p.value is not None),
        None,
    )
```

Call `estimate_depreciation(store, company_id, fiscal_year=fy)` from `default_assumption_set`. Populate `da_pct` metadata with the exact selected fiscal year and whether the source was `combined`, `split`, or `assumption`.

- [x] **Step 4: Verify focused and real-fixture valuation tests**

Run: `.venv/bin/python -m pytest tests/golden/test_golden_valuation.py -q -p no:cacheprovider`

Expected: all tests pass; the MSFT fixture still derives 34.3B + 4.7B for the FY2026 base.

- [x] **Step 5: Commit the focused change**

```bash
git add equitylens/valuation/defaults.py tests/golden/test_golden_valuation.py
git commit -m "fix: align depreciation with valuation base period"
```

---

### Task 3: Add a Current-TTM Result Contract

**Files:**
- Modify: `equitylens/metrics/engine.py:23`
- Modify: `equitylens/api/schemas.py:28`
- Test: `tests/unit/test_metric_engine.py`
- Test: `tests/integration/test_api.py`

**Interfaces:**
- Produces: `MetricPoint.frequency`, `period_start`, and `missing_reason`.
- Produces: `MetricEngine.current(metric: str, company_id: str, frequency: str) -> MetricPoint`.
- `current(metric, company_id, "ttm")` returns the latest expected fiscal-quarter endpoint with status `OK` or `INCOMPLETE_PERIOD`; it never returns an older complete window.

- [x] **Step 1: Write failing current-window tests**

Add real-engine tests for these independently hand-derived cases:

```python
def test_current_ttm_preserves_zero_in_latest_window(store):
    # FY2025Q1..FY2026Q1 = 25,25,25,25,-75; latest TTM is exactly zero.
    point = MetricEngine(store).current("NET_INCOME", CID, "ttm")
    assert point.status == "OK"
    assert point.value == 0.0
    assert point.fiscal_year == 2026 and point.fiscal_quarter == 1

def test_current_ttm_reports_latest_gap_instead_of_older_window(store):
    # A complete FY2025Q1-Q4 exists, but FY2026Q2 is latest and FY2026Q1 is absent.
    point = MetricEngine(store).current("NET_INCOME", CID, "ttm")
    assert point.status == "INCOMPLETE_PERIOD"
    assert point.value is None
    assert "FY2026Q1" in point.missing_reason
```

Add unit-mismatch and null-quarter cases. Assert `period_start`, `period_end`, `frequency="ttm"`, formula version, and ordered input IDs for a valid window.

- [x] **Step 2: Verify the current engine either returns an old point or no status**

Run: `.venv/bin/python -m pytest tests/unit/test_metric_engine.py -k current_ttm -q -p no:cacheprovider`

Expected: FAIL because `current` and the incomplete-period result do not exist.

- [x] **Step 3: Implement explicit window status without changing historical series**

Extend `MetricPoint` and `MetricOut` additively. Implement `current` as the boundary that determines the latest expected endpoint from relevant standalone input series, calls existing `compute`, and accepts a computed point only when its `(fiscal_year, fiscal_quarter)` matches that endpoint.

```python
@dataclass
class MetricPoint:
    frequency: str | None = None
    period_start: str | None = None
    missing_reason: str | None = None

def current(self, metric: str, company_id: str, frequency: str) -> MetricPoint:
    if frequency != "ttm":
        points = self.compute(metric, company_id, frequency)
        return points[-1] if points else self._missing(metric, frequency, "no observations")
    expected_end, missing = self._current_ttm_endpoint(metric, company_id)
    points = self.compute(metric, company_id, "ttm")
    match = next((p for p in reversed(points)
                  if (p.fiscal_year, p.fiscal_quarter) == expected_end), None)
    return match or self._incomplete_ttm(metric, expected_end, missing)
```

The dependency map for this batch must cover `REVENUE`, `NET_INCOME`, `OPERATING_CASH_FLOW`, `FCF`, `FCF_MARGIN`, `GROSS_MARGIN`, `OPERATING_MARGIN`, and `NET_MARGIN`. Validate consistent units within each amount series before summing. Correct current TTM points must use `frequency="ttm"`, not `quarterly`.

- [x] **Step 4: Expose missing status through the metric API**

Add an integration request for the latest-value endpoint used by consumers and assert that `value=null`, `status="INCOMPLETE_PERIOD"`, and `missing_reason` survive JSON serialization. Preserve existing historical-series endpoints.

- [x] **Step 5: Verify metric and API suites**

Run: `.venv/bin/python -m pytest tests/unit/test_metric_engine.py tests/integration/test_api.py -q -p no:cacheprovider`

Expected: all tests pass.

- [x] **Step 6: Commit the contract**

```bash
git add equitylens/metrics/engine.py equitylens/api/schemas.py tests/unit/test_metric_engine.py tests/integration/test_api.py
git commit -m "fix: expose current TTM completeness"
```

---

### Task 4: Make Market Multiples Use the Current TTM Contract

**Files:**
- Modify: `equitylens/market/service.py:155`
- Test: `tests/golden/test_golden_market.py`
- Test: `tests/integration/test_api.py`

**Interfaces:**
- Consumes: `MetricEngine.current(metric, company_id, "ttm")`.
- Produces: derived multiple entries with `value`, `status`, `reason`, formula, period, and input fact IDs.

- [x] **Step 1: Write the zero and missing-current regressions**

Use a temporary store and a literal market cap of `1000`:

```python
def test_market_multiples_do_not_fall_back_when_current_ttm_is_zero(store):
    # Current TTM NI = 0 and current TTM FCF = 0.
    block = quote_block(store, CID, "TEST")
    assert block["derived"]["pe_ttm"] is None
    assert block["derived"]["pe_ttm_status"] == "UNSUPPORTED"
    assert block["derived"]["pfcf_ttm"] is None
    assert block["derived"]["fcf_yield_ttm"] is None

def test_market_multiples_do_not_use_old_window_when_latest_is_incomplete(store):
    block = quote_block(store, CID, "TEST")
    assert block["derived"]["pe_ttm"] is None
    assert block["derived"]["pe_ttm_status"] == "INCOMPLETE_PERIOD"
```

Assert the returned period and evidence IDs refer to the current endpoint whenever a multiple is valid.

- [x] **Step 2: Verify the reviewed P/E=10 and P/FCF=16.67 fallback fails the tests**

Run: `.venv/bin/python -m pytest tests/golden/test_golden_market.py -k 'zero or incomplete' -q -p no:cacheprovider`

Expected: FAIL because truthiness filtering selects an older non-zero metric point.

- [x] **Step 3: Replace list filtering with explicit current results**

Remove `if p.value` selection. Use the Task 3 result and branch explicitly:

```python
net_income = engine.current("NET_INCOME", company_id, "ttm")
if net_income.status != "OK":
    derived.update(pe_ttm=None, pe_ttm_status=net_income.status,
                   pe_ttm_reason=net_income.missing_reason)
elif net_income.value <= 0:
    derived.update(pe_ttm=None, pe_ttm_status="UNSUPPORTED",
                   pe_ttm_reason="当前TTM净利润不为正")
else:
    derived.update(pe_ttm=market_cap / net_income.value, pe_ttm_status="OK")
```

Apply the same logic to FCF and FCF yield. Include period and evidence identity in each valid or unavailable derived metric.

- [x] **Step 4: Verify market and API behavior**

Run: `.venv/bin/python -m pytest tests/golden/test_golden_market.py tests/integration/test_api.py -q -p no:cacheprovider`

Expected: all tests pass, including real AAPL/MSFT fixtures.

- [x] **Step 5: Commit the consumer correction**

```bash
git add equitylens/market/service.py tests/golden/test_golden_market.py tests/integration/test_api.py
git commit -m "fix: prevent stale TTM multiple fallback"
```

---

### Task 5: Share TTM and Failure Coverage with Risks and Research

**Files:**
- Modify: `equitylens/domain/risks.py:12`
- Modify: `equitylens/research/engine.py:96`
- Test: `tests/golden/test_golden_research.py`
- Test: `tests/integration/test_api.py`

**Interfaces:**
- Consumes: `MetricEngine.current` for all TTM values.
- Produces: risk response `checks: list[{key, status, reason, evidence_ids}]`.
- Produces: research coverage statements derived from `checks`, never from a hard-coded list.

- [x] **Step 1: Write failing risk coverage tests**

Create a store with a quarter gap and force one management-score dependency to raise. Assert cash-flow risk is not computed from partial rows and the management check is present as an error:

```python
def test_risks_report_incomplete_ttm_and_module_failure(store, monkeypatch):
    result = risk_signals(store, CID, "TEST")
    checks = {item["key"]: item for item in result["checks"]}
    assert checks["cash_flow"]["status"] == "INCOMPLETE_PERIOD"
    assert checks["management"]["status"] == "ERROR"
    assert checks["management"]["reason"]
    assert not any(r["category"] == "cash_flow" for r in result["risks"])
```

Add a research assertion that its coverage text names the unavailable checks and does not say all modules were checked.

- [x] **Step 2: Verify exceptions are swallowed and the response has no coverage**

Run: `.venv/bin/python -m pytest tests/golden/test_golden_research.py tests/integration/test_api.py -k 'coverage or incomplete_ttm' -q -p no:cacheprovider`

Expected: FAIL because `risk_signals` currently catches exceptions with `pass` and manually sums rows.

- [x] **Step 3: Add a checked-module wrapper and use metric results**

Each risk module appends a check on success, unavailable input, or exception. The wrapper records the failure but lets sibling modules continue.

```python
def record_check(key: str, fn: Callable[[], tuple[str, str | None, list[str]]]) -> None:
    try:
        status, reason, evidence_ids = fn()
        checks.append({"key": key, "status": status, "reason": reason,
                       "evidence_ids": evidence_ids})
    except Exception as exc:
        checks.append({"key": key, "status": "ERROR", "reason": str(exc), "evidence_ids": []})
```

For cash-flow risks, call `current("OPERATING_CASH_FLOW", company_id, "ttm")` and `current("FCF", company_id, "ttm")`; do not query and sum the latest four canonical rows. Only emit a numeric claim when both required results are `OK`, and copy their input IDs into evidence.

- [x] **Step 4: Build research coverage from actual check statuses**

Replace unconditional wording with a compact list of successful and unavailable checks. Numeric risk statements keep their resolvable evidence IDs; an `ERROR` check is described as not completed.

- [x] **Step 5: Verify risk, research, and API suites**

Run: `.venv/bin/python -m pytest tests/golden/test_golden_research.py tests/integration/test_api.py -q -p no:cacheprovider`

Expected: all tests pass.

- [x] **Step 6: Commit the coverage behavior**

```bash
git add equitylens/domain/risks.py equitylens/research/engine.py tests/golden/test_golden_research.py tests/integration/test_api.py
git commit -m "fix: report risk calculation coverage"
```

---

### Task 6: Harden DCF Validation and the -100% Boundary

**Files:**
- Modify: `equitylens/valuation/dcf.py:21`
- Test: `tests/golden/test_golden_valuation.py`

**Interfaces:**
- Consumes: `DcfInputs` and explicit forecast inputs.
- Produces: `ValuationError(code: str, field: str | None, message: str)` for every invalid engine input.
- Keeps `run_dcf(inputs) -> DcfOutput` and the existing explicit-forecast function deterministic.

- [x] **Step 1: Write failing engine regressions**

Add literal tests for each reviewed failure:

```python
def test_minus_100_percent_growth_releases_working_capital():
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
    with pytest.raises(ValuationError) as exc:
        run_dcf(make_inputs(**{field: value}, terminal_growth=-1.1 if field == "wacc" else 0.02))
    assert exc.value.field == field

def test_explicit_terminal_values_must_be_finite():
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
```

Also cover `1 + wacc <= 0`, non-finite growth entries, negative D&A ratios, and non-finite optional terminal D&A/CapEx/dNWC.

- [x] **Step 2: Verify the tests reproduce zero dNWC, accepted negative CapEx, division by zero, and NaN output**

Run: `.venv/bin/python -m pytest tests/golden/test_golden_valuation.py -k 'working_capital or incompatible or terminal_values' -q -p no:cacheprovider`

Expected: FAIL for the reviewed reasons, not fixture construction errors.

- [x] **Step 3: Make validation structured and shared**

Give `ValuationError` stable fields and use helpers for finite and bounded values. Enforce `wacc > -1`, `wacc - terminal_growth >= 0.01`, `da_pct >= 0`, `capex_pct >= 0`, and the existing model bounds. Include optional explicit terminal inputs in finite validation.

```python
class ValuationError(ValueError):
    def __init__(self, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.field = field

def _require_finite(field: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValuationError("INVALID_ASSUMPTION", f"{field} must be finite", field)
```

- [x] **Step 4: Preserve prior revenue before growth**

Use direct state rather than reversing the growth operation:

```python
previous_revenue = revenue
revenue = previous_revenue * (1 + g)
nwc_delta = (revenue - previous_revenue) * inputs.nwc_pct
```

- [x] **Step 5: Verify the valuation engine suite**

Run: `.venv/bin/python -m pytest tests/golden/test_golden_valuation.py -q -p no:cacheprovider`

Expected: all tests pass, including valid negative FCFF/equity cases.

- [x] **Step 6: Commit the engine boundary**

```bash
git add equitylens/valuation/dcf.py tests/golden/test_golden_valuation.py
git commit -m "fix: harden DCF input boundaries"
```

---

### Task 7: Return Structured Valuation API Errors and Fingerprints

**Files:**
- Modify: `equitylens/valuation/service.py:96`
- Modify: `equitylens/api/routes.py:520`
- Modify: `equitylens/api/schemas.py`
- Test: `tests/integration/test_api.py`

**Interfaces:**
- Produces: `valuation_input_fingerprint(inputs: DcfInputs) -> str`, SHA-256 over canonical sorted JSON of all executed inputs.
- Produces: valuation responses containing `ticker`, `input_fingerprint`, and complete executed `assumptions.inputs`.
- Produces: HTTP 400 body `{"error": {"code", "field", "message"}}` for `ValuationError`.

- [x] **Step 1: Write failing API contract tests**

Assert two requests differing only in WACC have different fingerprints, repeated identical requests have the same fingerprint, and the returned fingerprint corresponds to the complete returned input object. Assert invalid CapEx returns the stable structured error and creates no row.

```python
def test_valuation_response_fingerprints_complete_executed_inputs(client):
    a = client.post(RUN, json={"persist": False, "assumptions": {"wacc": 0.10}}).json()
    b = client.post(RUN, json={"persist": False, "assumptions": {"wacc": 0.11}}).json()
    assert a["ticker"] == "AAPL"
    assert a["input_fingerprint"] != b["input_fingerprint"]
    assert a["input_fingerprint"] == fingerprint(a["assumptions"]["inputs"])
```

- [x] **Step 2: Verify the response has no complete identity contract**

Run: `.venv/bin/python -m pytest tests/integration/test_api.py -k 'fingerprint or structured_valuation_error' -q -p no:cacheprovider`

Expected: FAIL because the fields and structured error body do not exist.

- [x] **Step 3: Canonicalize all executed inputs and metadata before calculation**

Serialize dataclass inputs with `asdict`, JSON sort keys, compact separators, and `allow_nan=False`, then hash UTF-8 bytes. Generate metadata after overrides for every editable field, including `op_margin_start` and `nwc_pct`. Return the same complete input object used by the engine.

- [x] **Step 4: Map domain errors at the API boundary**

Catch `ValuationError` separately from other `ValueError` paths and return the stable error object. Confirm every invalid main-input branch exits before persistence.

- [x] **Step 5: Verify API and valuation suites**

Run: `.venv/bin/python -m pytest tests/integration/test_api.py tests/golden/test_golden_valuation.py -q -p no:cacheprovider`

Expected: all tests pass.

- [x] **Step 6: Commit the API identity contract**

```bash
git add equitylens/valuation/service.py equitylens/api/routes.py equitylens/api/schemas.py tests/integration/test_api.py
git commit -m "fix: identify valuation inputs and errors"
```

---

### Task 8: Keep One Complete Valuation Draft in the Client

**Files:**
- Create: `apps/web/src/lib/valuationDraft.ts`
- Modify: `apps/web/src/lib/types.ts`
- Modify: `apps/web/src/components/sections/ValuationSection.tsx:70`
- Modify: `apps/web/package.json`
- Modify: `apps/web/pnpm-lock.yaml`
- Create: `apps/web/playwright.config.ts`
- Create: `apps/web/e2e/valuation-state.spec.ts`

**Interfaces:**
- Consumes: complete backend `DcfInputs`, ticker, and input fingerprint.
- Produces: `ValuationDraft` containing every editable DCF field and `buildPreviewRequest(draft)` containing the full input object.
- Produces: UI state where `draftFingerprint`, `appliedFingerprint`, ticker, and request sequence must all match before output is current or saveable.

- [x] **Step 1: Add Playwright following the repository's Next.js 16 guide**

Read `apps/web/node_modules/next/dist/docs/01-app/02-guides/testing/playwright.md`, then add `@playwright/test`, an `e2e` script, and a config with `baseURL` plus a `webServer` command. Install only Chromium for local verification.

```json
"scripts": {
  "e2e": "playwright test",
  "e2e:valuation": "playwright test e2e/valuation-state.spec.ts"
}
```

- [x] **Step 2: Write the failing controlled-order browser test**

Intercept the default and valuation-run API routes. Delay the first preview response, submit a growth edit, then submit a WACC edit before the first response resolves. Give each response a distinct literal fair value and echoed fingerprint.

```ts
test('keeps the newest complete draft when previews return out of order', async ({ page }) => {
  // Default path is [8, 7.5, 7, 6, 5] percent.
  // Growth edit makes [10, 9.5, 9, 8.5, 8] and the immediate WACC edit must carry it.
  await page.getByLabel('首年收入增速').fill('10')
  await page.getByLabel('WACC').fill('12')
  expect(secondRequest.assumptions).toMatchObject({
    revenue_growth: [0.10, 0.095, 0.09, 0.085, 0.08],
    wacc: 0.12,
  })
  await expect(page.getByTestId('fair-value')).toHaveText('$222.00')
  await expect(page.getByRole('button', { name: '保存本次运行' })).toBeEnabled()
})
```

Add cases for: old `finally` not clearing a newer loading state; a failed newest request marking old output stale and disabling save; ticker change clearing reverse result and source context; market target `326.68` remaining `326.68`.

- [x] **Step 3: Verify the browser test fails against current closure state**

Run: `cd apps/web && pnpm e2e:valuation`

Expected: FAIL because the second request can carry the old `growthPath`, failed drafts leave prior output saveable, and target price is rounded.

- [x] **Step 4: Extract pure draft construction**

Use one object initialized from `response.assumptions.inputs`. Editing a field creates the next complete draft synchronously before starting fetch. Growth edits alone rebuild the five-year path and allow negative values down to the backend limit; editing WACC, margin, or terminal growth preserves the current path.

```ts
export function updateDraft(draft: ValuationDraft, edit: DraftEdit): ValuationDraft {
  if (edit.field === 'growth') {
    const g = edit.percent / 100
    return { ...draft, revenue_growth: [g, g - .005, g - .01, g - .015, g - .02] }
  }
  return { ...draft, [edit.field]: edit.percent / 100 }
}
```

- [x] **Step 5: Gate response application and saving by full identity**

Maintain the current ticker, monotonically increasing sequence, and draft fingerprint in refs. Apply a response only when all three match. Store `appliedFingerprint` from the response; enable save only when it equals the current draft fingerprint and there is no current error. Mark reverse DCF stale whenever target or draft changes. Preserve market-price decimals with `String(q.price)`.

- [x] **Step 6: Send complete inputs for preview, reverse DCF, and save**

`buildPreviewRequest` must include revenue base, all five growth values, both margins, tax, D&A, CapEx, NWC, WACC, terminal growth, net cash, shares, and share-basis label. Saving uses the already applied input/fingerprint contract and must not silently combine a new draft with an old result.

- [x] **Step 7: Verify frontend behavior and static checks**

Run: `cd apps/web && pnpm e2e:valuation && pnpm exec tsc --noEmit --incremental false && pnpm lint`

Expected: all checks pass.

- [x] **Step 8: Commit the client identity behavior**

```bash
git add apps/web/src/lib/valuationDraft.ts apps/web/src/lib/types.ts apps/web/src/components/sections/ValuationSection.tsx apps/web/package.json apps/web/pnpm-lock.yaml apps/web/playwright.config.ts apps/web/e2e/valuation-state.spec.ts
git commit -m "fix: bind valuation previews to complete drafts"
```

---

### Task 9: Verify and Record Batch 1

**Files:**
- Create: `docs/reviews/2026-09-06-remediation-batch1-rework.md`
- Modify: `docs/reviews/2026-09-06-remediation-quality-review.md`

**Interfaces:**
- Consumes: focused regression outputs and the final repository state.
- Produces: one evidence-backed status for D02, D04, D06, D07, V01, V03, U01, U02, U03, P05, and P07 as affected by this batch.

- [x] **Step 1: Run the complete backend suite**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider`

Expected: all tests pass. Record the exact count, duration, and warnings.

- [x] **Step 2: Run all frontend checks**

Run: `cd apps/web && pnpm e2e:valuation && pnpm exec tsc --noEmit --incremental false && pnpm lint`

Expected: all checks pass. Record the exact Playwright count and static-check results.

- [x] **Step 3: Re-run the reviewed counterexamples directly**

Run the focused test selectors from Tasks 1–8 and confirm each reviewed failure now returns the specified value or status. Do not use the real database for writes.

- [x] **Step 4: Write the batch evidence record**

For each affected remediation ID, record implemented behavior, test name, API/UI consistency, version impact, persistence impact, and any remaining limitation. Change an audit status only when all original acceptance dimensions covered by this batch are satisfied; otherwise leave it partial and state the next batch dependency.

- [x] **Step 5: Check the final diff for unintended files**

Run: `git status --short && git diff --check && git diff --stat HEAD~8..HEAD`

Expected: no database files, backups, caches, or unrelated user files are staged or committed.

- [x] **Step 6: Commit the batch record**

```bash
git add docs/reviews/2026-09-06-remediation-batch1-rework.md docs/reviews/2026-09-06-remediation-quality-review.md
git commit -m "docs: record remediation batch 1 evidence"
```

## Plan Self-Review

- Every Batch 1 design requirement maps to a task: period normalization (Task 1), D&A base period (Task 2), current TTM (Tasks 3–5), DCF boundaries (Task 6), API identity (Task 7), and client draft identity (Task 8).
- Every production change begins with a named regression and an expected failing behavior.
- `MetricEngine.current`, `MetricPoint` fields, `ValuationError`, and valuation fingerprints use the same signatures in producer and consumer tasks.
- Batch 2 provenance persistence, Batch 3 v2 rollout/plans/refresh, and Batch 4 explanation work remain outside this plan and follow after Batch 1 evidence is accepted.
- No step writes to the real DuckDB database or changes historical valuation results.
