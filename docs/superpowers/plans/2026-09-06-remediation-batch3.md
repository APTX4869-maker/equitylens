# EquityLens Remediation Batch 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the versioned v2 FCFF model, traceable personal valuation plans, and independently retryable four-module refresh into complete backend and browser workflows.

**Architecture:** Keep historical `fcff_dcf.v1` outputs readable while routing every new calculation through one `fcff_dcf.v2` executor. Plans reference immutable saved runs and selected scenarios rather than accepting free-standing prices. A refresh coordinator serializes DuckDB writes, returns one result per module, and gives the frontend a generation key that remounts the active data section and marks existing research artifacts for review.

**Tech Stack:** Python 3.12, FastAPI, DuckDB, pytest, Next.js 16.3.3, React 19.2.8, TypeScript, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-06-remediation-rework-design.md`

## Global Constraints

- Preserve existing raw snapshots, valuation runs, plans, and database backups.
- New calculations default to `fcff_dcf.v2`; stored v1 outputs are never recalculated.
- A terminal-year cash flow supplied or constructed for year 6 is not grown a second time.
- Preview requests do not persist; an explicit save records the complete immutable v2 run.
- A normal positive plan reference must resolve to a saved run and one selected scenario.
- Refresh reports financials, segments, management, and quotes independently and never converts an optional-module failure into success.
- Tests use temporary stores and raw directories. Do not write to `data/equitylens.duckdb` or existing raw snapshots.

---

### Task 1: Implement the Production `fcff_dcf.v2` Executor

**Files:**
- Modify: `equitylens/valuation/dcf.py`
- Test: `tests/golden/test_golden_valuation.py`

**Interfaces:**
- Produces: `MODEL_VERSION = "fcff_dcf.v2"`.
- Produces: `run_dcf(inputs: DcfInputs, model_version: str = MODEL_VERSION) -> DcfOutput` with explicit dispatch.
- Adds: `DcfInputs.terminal_roic: float` and `DcfOutput.terminal_forecast: dict`.
- Retains: `run_dcf_explicit(...)` as the shared explicit-cash-flow core, with terminal inputs defined as year-6 amounts.

- [x] **Step 1: Write positive-growth hand-calculation regressions**

Add a literal case with WACC 10%, terminal growth 2%, terminal EBIT 120, tax 20%, terminal D&A 10, CapEx 5, and change in NWC 1. Assert terminal FCFF is `100`, terminal value is `1250`, and no extra `1.02` multiplier appears. Add a production `run_dcf` case that asserts its terminal block is built from year-6 revenue, stable margin, and `reinvestment_rate = terminal_growth / terminal_roic`.

- [x] **Step 2: Run the new tests and verify the old double-growth behavior fails**

Run: `.venv/bin/python -m pytest tests/golden/test_golden_valuation.py -k 'terminal_year or v2_terminal' -q -p no:cacheprovider`

Expected: the explicit case returns `1020`, and production has no v2 terminal block.

- [x] **Step 3: Add explicit version dispatch and stable-period economics**

Keep the old percentage-path calculation as `_run_dcf_v1` for explicit compatibility tests. Build the five forecast years once for v2. Construct terminal-year revenue as year-5 revenue times `(1 + terminal_growth)`, terminal EBIT from the stable margin, terminal NOPAT, reinvestment rate as `terminal_growth / terminal_roic`, and terminal FCFF as `terminal_nopat * (1 - reinvestment_rate)`. Pass that already-forward terminal cash flow to the explicit discount core and compute `TV = terminal_fcff / (wacc - terminal_growth)`.

Validate finite `terminal_roic`, require it to be positive, and reject `terminal_growth / terminal_roic >= 1` with a structured `ValuationError(field="terminal_roic")`. Include the terminal revenue, EBIT, NOPAT, reinvestment, FCFF, ROIC and formula text in `terminal_forecast`.

- [x] **Step 4: Verify v1 compatibility and v2 arithmetic**

Run: `.venv/bin/python -m pytest tests/golden/test_golden_valuation.py -q -p no:cacheprovider`

Expected: all tests pass; hand calculations detect any terminal double growth.

- [x] **Step 5: Commit the engine boundary**

```bash
git add equitylens/valuation/dcf.py tests/golden/test_golden_valuation.py
git commit -m "feat: implement production fcff dcf v2"
```

---

### Task 2: Route Every New Valuation Consumer Through v2

**Files:**
- Modify: `equitylens/valuation/defaults.py`
- Modify: `equitylens/valuation/service.py`
- Modify: `equitylens/api/routes.py`
- Modify: `apps/web/src/lib/valuationDraft.ts`
- Modify: `apps/web/src/components/sections/ValuationSection.tsx`
- Modify: `apps/web/e2e/valuation-state.spec.ts`
- Test: `tests/integration/test_api.py`

**Interfaces:**
- All default, preview, saved run, scenario, sensitivity, and reverse DCF responses report `fcff_dcf.v2`.
- Complete input drafts and fingerprints include `terminal_roic`.
- Saved v1 run reads remain byte-for-byte stored output reads.

- [x] **Step 1: Add failing API path coverage**

Extend integration tests to call default, preview, persisted run, scenarios, sensitivity, and reverse DCF. Assert every newly calculated result reports v2 and returns `terminal_forecast`; assert the saved run reads the same terminal block. Keep the existing inserted legacy v1 record and assert it remains v1.

- [x] **Step 2: Verify the production service still reports v1**

Run: `.venv/bin/python -m pytest tests/integration/test_api.py -k 'v2 or legacy_run' -q -p no:cacheprovider`

Expected: new calculations fail the v2 assertions.

- [x] **Step 3: Carry `terminal_roic` through defaults, overrides and the client draft**

Add a documented issuer/config default of 20% and metadata with configuration version. Include it in `_inputs_dict`, fingerprints, scenario trials, sensitivity trials, reverse trials, `buildPreviewRequest`, `draftFingerprint`, controlled-order Playwright fixtures, and an editable percentage control in the valuation page.

- [x] **Step 4: Remove the test-only production split**

Make default, custom, scenario, sensitivity and reverse functions call `run_dcf(..., model_version="fcff_dcf.v2")` through the same dispatch. Do not invoke `run_dcf_explicit` directly in API/service code except inside the v2 executor. Return the terminal definition and v2 model version in API and UI.

- [x] **Step 5: Verify backend and frontend contracts**

Run: `.venv/bin/python -m pytest tests/golden/test_golden_valuation.py tests/integration/test_api.py -q -p no:cacheprovider`

Run: `cd apps/web && pnpm exec tsc --noEmit --incremental false && pnpm lint && pnpm exec playwright test --list`

Expected: all commands pass and the two valuation ordering tests still collect.

- [x] **Step 6: Commit the v2 product path**

```bash
git add equitylens/valuation/defaults.py equitylens/valuation/service.py equitylens/api/routes.py apps/web/src/lib/valuationDraft.ts apps/web/src/components/sections/ValuationSection.tsx apps/web/e2e/valuation-state.spec.ts tests/integration/test_api.py
git commit -m "feat: route valuation workflows through v2"
```

---

### Task 3: Enforce Traceable, Versioned Valuation Plans

**Files:**
- Modify: `spec/schema.sql`
- Modify: `equitylens/storage/duckdb_store.py`
- Modify: `equitylens/valuation/service.py`
- Modify: `equitylens/api/routes.py`
- Test: `tests/integration/test_api.py`

**Interfaces:**
- `POST /valuation/plans` consumes `valuation_run_id`, `scenario_key`, `name`, `margin_of_safety`, `notes`, and `conditions_to_verify`.
- `POST /valuation/plans/{plan_id}/copy` creates a new immutable version with `parent_plan_id`.
- `GET /valuation/plans/{plan_id}` preserves `reference_price_reason`, source identity, notes, conditions, version, and review state.
- `GET /valuation/plans/compare?ids=...` returns same-company plan inputs and changed fields.

- [x] **Step 1: Add failing validation and restart-safe read tests**

Assert arbitrary `reference_value`/`reference_source` fields without a valid saved run return 400. Save a v2 run, create plans for base and bear, and assert the backend derives the selected stored scenario value rather than trusting a client price. Close/reopen a temporary store and verify all fields survive. Assert nonpositive selected values preserve a reason and no normal reference price.

- [x] **Step 2: Verify the current endpoint accepts arbitrary prices**

Run: `.venv/bin/python -m pytest tests/integration/test_api.py -k 'plan_' -q -p no:cacheprovider`

Expected: the arbitrary-price request currently succeeds and copy/compare routes are absent.

- [x] **Step 3: Add an additive plan schema**

Add nullable legacy-compatible columns: `valuation_run_id`, `scenario_key`, `reference_price_reason`, `conditions_json`, `parent_plan_id`, `version`, `review_status`, `review_reason`, `source_filing_as_of`, and `source_quote_observed_at`. Add the same idempotent migrations in `duckdb_store.py`. Existing rows read as `legacy/incomplete` and are not assigned invented run identities.

- [x] **Step 4: Resolve all new plan values from saved runs**

Load the same-company run, require `status=complete`, select only `base|bear|bull`, read the stored result, and calculate `reference_price = selected_value * (1 - margin)`. Persist the run ID, scenario, immutable input fingerprint, source dates, notes and conditions. Copy creates a new row and increments version; compare returns field differences without mutating either plan.

- [x] **Step 5: Verify plan API behavior**

Run: `.venv/bin/python -m pytest tests/integration/test_api.py -k 'plan_' -q -p no:cacheprovider`

Expected: traceability, nonpositive-state, open, copy, compare, company isolation and restart tests pass.

- [x] **Step 6: Commit the plan domain**

```bash
git add spec/schema.sql equitylens/storage/duckdb_store.py equitylens/valuation/service.py equitylens/api/routes.py tests/integration/test_api.py
git commit -m "feat: make valuation plans traceable and versioned"
```

---

### Task 4: Complete the Plan Browser Workflow

**Files:**
- Modify: `apps/web/src/components/sections/ValuationSection.tsx`
- Create: `apps/web/e2e/valuation-plans.spec.ts`

**Interfaces:**
- The page selects base/bear/bull from the last successfully saved run.
- The page supports open, copy, two-plan compare, notes, conditions, and visible review status.

- [x] **Step 1: Write the failing browser workflow**

Stub run and plan APIs. In one Playwright test: save a run, select Bear, enter notes and a condition, save the plan, open it, copy it, select two plans, and compare changed fields. Assert the request always carries the saved run ID and scenario and never sends an authoritative `reference_value`.

- [x] **Step 2: Confirm the controls do not exist**

Run: `cd apps/web && pnpm exec playwright test e2e/valuation-plans.spec.ts --list`

Expected: collection succeeds; running it fails on missing scenario/open/copy/compare controls.

- [x] **Step 3: Implement the plan editor and detail view**

Keep the saved run ID returned by the explicit save. Disable plan creation until one exists. Render scenario selection only for usable scenario results, derive the preview from that result, add notes and repeatable verification conditions, and expose open/copy/compare actions. Show `needs_review`, `current`, and `legacy/incomplete` explicitly.

- [x] **Step 4: Verify static and browser contracts**

Run: `cd apps/web && pnpm exec tsc --noEmit --incremental false && pnpm lint && pnpm exec playwright test --list`

If Chromium is available, run: `cd apps/web && pnpm exec playwright test e2e/valuation-plans.spec.ts`

Expected: type/lint/collection pass; browser workflow passes when the installed browser is available.

- [x] **Step 5: Commit the browser workflow**

```bash
git add apps/web/src/components/sections/ValuationSection.tsx apps/web/e2e/valuation-plans.spec.ts
git commit -m "feat: complete personal valuation plan workflow"
```

---

### Task 5: Coordinate Four-Module Refresh and Failed-Module Retry

**Files:**
- Create: `equitylens/refresh/service.py`
- Modify: `equitylens/api/routes.py`
- Modify: `equitylens/storage/duckdb_store.py`
- Test: `tests/integration/test_api.py`

**Interfaces:**
- `refresh_company(store, ticker, modules=None) -> dict` reports `financials`, `segments`, `management`, and `quotes` separately.
- `POST /companies/{ticker}/refresh` accepts optional `{modules: [...]}` for failed-module retry.
- Response includes `refresh_id`, per-module status/timestamps/error/retryable, `changed`, and `review_required`.

- [x] **Step 1: Add failing four-module and retry tests**

Monkeypatch all four synchronizers. Make segments fail while the other three succeed; assert HTTP 200, exact per-module statuses, retry eligibility, and that management ran. Retry only segments and assert no other synchronizer runs. Add a transaction regression where a module writes a sentinel row then raises; assert that module's sentinel is rolled back while successful sibling commits remain.

- [x] **Step 2: Verify current refresh omits management and returns 500 on required failure**

Run: `.venv/bin/python -m pytest tests/integration/test_api.py -k refresh -q -p no:cacheprovider`

Expected: new four-module, selective retry and rollback assertions fail.

- [x] **Step 3: Add serialized per-module transactions and staged raw publication**

Add a process-wide write lock plus the existing per-company lock. For each selected module, copy the needed current raw inputs into a temporary staging directory, run the synchronizer against that directory inside its own DuckDB transaction, and call `sync_management` as the fourth source. After computation succeeds, publish staged immutable files/manifests while retaining the prior manifests, then commit the database transaction. On any publication or commit error, roll back and atomically restore the prior manifests; new immutable files may remain unreferenced. A failed module must leave both visible latest pointers and database rows at the prior complete state.

- [x] **Step 4: Calculate review impact**

Before and after refresh, capture the latest financial filing identity and quote observation identity. Set `changed` per module and `review_required=true` when either valuation input source changed. Update existing plan rows to `needs_review` with a reason; never recalculate stored runs or plan reference prices.

- [x] **Step 5: Verify refresh integration**

Run: `.venv/bin/python -m pytest tests/integration/test_api.py -k refresh -q -p no:cacheprovider`

Expected: partial failure, failed-only retry, transaction rollback, serialization and review-state tests pass.

- [x] **Step 6: Commit the coordinator**

```bash
git add equitylens/refresh/service.py equitylens/api/routes.py equitylens/storage/duckdb_store.py tests/integration/test_api.py
git commit -m "feat: coordinate retryable four module refresh"
```

---

### Task 6: Reload the Active Browser Section After Refresh

**Files:**
- Modify: `apps/web/src/app/page.tsx`
- Modify: `apps/web/src/components/sections/ValuationSection.tsx`
- Create: `apps/web/e2e/refresh-state.spec.ts`
- Modify: `docs/reviews/2026-09-06-remediation-progress.md`
- Create: `docs/reviews/2026-09-06-remediation-batch3-rework.md`

**Interfaces:**
- Active section receives a refresh generation in its React key or load dependency.
- Failed modules render individual retry actions.
- Valuation drafts and stored plans show review-required state after changed inputs.

- [x] **Step 1: Write the failing refresh browser test**

Stub a first financial response, refresh response with one failed module, and a second changed financial response. Assert the visible active Financials section reloads, the failed module gets a retry button that posts only that module, and a valuation draft/plan displays a review warning without being silently recalculated.

- [x] **Step 2: Run collection and the browser test when possible**

Run: `cd apps/web && pnpm exec playwright test e2e/refresh-state.spec.ts --list`

Expected: collection succeeds; execution fails because child sections ignore the parent reload key.

- [x] **Step 3: Thread refresh generation through active sections**

Key every data section by `${ticker}:${reloadKey}` or pass `reloadKey` into its fetch effect. Clear company-specific drawers and refresh messages when ticker changes. Render all four module outcomes and a retry button for each `retryable` failure. Do not clear unsaved valuation inputs; mark them as requiring recalculation.

- [x] **Step 4: Run Batch 3 verification**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider`

Run: `cd apps/web && pnpm exec tsc --noEmit --incremental false && pnpm lint && pnpm exec playwright test --list`

If Chromium is available, run: `cd apps/web && pnpm exec playwright test`

Expected: all available checks pass; browser execution limitation, if any, is recorded exactly.

- [x] **Step 5: Update evidence and commit**

Record P02/P06/P08 behavior, exact test commands/counts, schema compatibility and remaining browser limitations. Update the consolidated progress state only from current evidence.

```bash
git add apps/web/src/app/page.tsx apps/web/src/components/sections/ValuationSection.tsx apps/web/e2e/refresh-state.spec.ts docs/reviews/2026-09-06-remediation-progress.md docs/reviews/2026-09-06-remediation-batch3-rework.md
git commit -m "docs: record remediation Batch 3 evidence"
```
