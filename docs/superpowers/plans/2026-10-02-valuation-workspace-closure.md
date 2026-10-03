# Valuation Workspace Closure Implementation Plan

> **For Codex:** Execute this plan task-by-task with `superpowers:executing-plans`. Follow red-green-refactor for every behavior change and run the verification listed under each task before committing it.

**Goal:** Make a confirmed valuation profile usable for legal personal assumption edits, preserve the reviewed fact/model provenance, and turn saved valuation plans into a complete, recoverable personal workspace.

**Architecture:** Split the immutable reviewed `ValuationBaseline` from a mutable five-field `PersonalDraft`. The backend remains authoritative: it binds the baseline to publication/model/security, rejects edits to factual fields, preserves provenance, validates all calculations, and stores immutable runs/plans. The frontend renders exact editable values, expands controls around real issuer data, reports failures inline, and exposes a searchable/paginated/archiveable plan library with actual value comparisons.

**Tech Stack:** FastAPI, SQLite, Python dataclasses/services, Next.js/React/TypeScript, Vitest, Playwright, pytest.

**Approved decisions:** Use `docs/superpowers/specs/2026-10-01-personal-product-reliability-design.md` section 10. A confirmation covers the reviewed fact baseline and model applicability; only revenue growth, year-five operating margin, WACC, terminal growth, and terminal ROIC are editable. Runs/plans are immutable; editing begins from a copy. Archives are reversible and comparisons display real values.

---

## Task 1: Bind valuation confirmation to the published baseline

**Files:**
- Modify: `equitylens/valuation/defaults.py`
- Modify: `equitylens/valuation/service.py`
- Modify: `equitylens/api/routes.py`
- Test: `tests/integration/test_onboarding_valuation.py`

### Step 1: Write failing integration tests

Add tests proving that:

- default valuation inputs are read from the active publication context, not unreviewed live facts;
- a confirmation stores the full generated metadata and source fact IDs;
- reopening the confirmed default preserves the original source type/as-of/version instead of replacing every field with `user_confirmation`;
- a confirmation for an old publication is no longer current after publication/model identity changes.

Run:

```bash
pytest tests/integration/test_onboarding_valuation.py -k "published_baseline or confirmation_preserves_provenance" -q
```

Expected: FAIL on the current live-engine and synthetic-metadata behavior.

### Step 2: Add an injectable metric context

Allow `default_assumption_set`, `default_valuation`, and `valuation_profile_draft` to receive the route's publication-bound metric engine. Keep the current default only for internal callers that have no publication context.

### Step 3: Persist the reviewed baseline bundle

When confirming, regenerate the current published baseline, verify all immutable factual inputs, apply only the approved five assumption fields, and store the resulting `inputs`, complete `meta`, and `source_fact_ids` with the confirmation. Do not label unchanged fact inputs as user-authored.

### Step 4: Use the stored bundle on reopen

Reconstruct confirmed valuation output from the persisted bundle and retain each field's lineage. Continue checking security, publication, model version, and fingerprint.

### Step 5: Verify and commit

Run:

```bash
pytest tests/integration/test_onboarding_valuation.py -q
```

Commit:

```bash
git add equitylens/valuation/defaults.py equitylens/valuation/service.py equitylens/api/routes.py tests/integration/test_onboarding_valuation.py
git commit -m "fix: bind valuation confirmation to published baseline"
```

## Task 2: Permit only the five legal personal overrides

**Files:**
- Modify: `equitylens/valuation/service.py`
- Modify: `equitylens/api/routes.py`
- Test: `tests/integration/test_onboarding_valuation.py`
- Test: `tests/integration/test_api.py`

### Step 1: Write failing contract tests

Cover:

- editing any subset of the five approved assumption fields after confirmation returns a valid preview/run;
- unchanged confirmed inputs still work;
- changing revenue base, shares, cash, tax rate, starting margin, D&A, capex, or NWC is rejected with a field-specific 409/422 error;
- reverse DCF follows the same baseline/override contract;
- stored run metadata marks only changed fields `user_override` and retains their baseline provenance;
- invalid/non-finite/out-of-domain inputs return structured errors and never persist a run.

Run:

```bash
pytest tests/integration/test_onboarding_valuation.py tests/integration/test_api.py -k "personal_override or immutable_baseline" -q
```

Expected: FAIL because the current exact-assumption hash blocks legal edits.

### Step 2: Add a baseline merge/validation helper

Create one service-level path that:

1. loads the confirmed baseline;
2. compares immutable fields exactly (with normalized numeric/list serialization);
3. accepts only `revenue_growth`, `op_margin_end`, `wacc`, `terminal_growth`, and `terminal_roic` as personal overrides;
4. preserves original metadata under each changed field while adding override provenance;
5. invokes the DCF validator before persistence.

### Step 3: Route preview, save, and reverse through the helper

Remove exact full-draft fingerprint matching from legal valuation calculations. Keep the confirmation identity gate and immutable baseline check.

### Step 4: Verify and commit

Run:

```bash
pytest tests/integration/test_onboarding_valuation.py tests/integration/test_api.py -q
```

Commit:

```bash
git add equitylens/valuation/service.py equitylens/api/routes.py tests/integration/test_onboarding_valuation.py tests/integration/test_api.py
git commit -m "fix: support confirmed personal valuation overrides"
```

## Task 3: Make all five controls exact, adaptive, and self-validating

**Files:**
- Modify: `apps/web/src/lib/valuationDraft.ts`
- Create: `apps/web/src/components/valuation/ValuationControls.tsx`
- Modify: `apps/web/src/components/sections/ValuationSection.tsx`
- Test: `apps/web/src/lib/valuationDraft.test.ts`
- Test: `apps/web/e2e/valuation-state.spec.ts`

### Step 1: Write failing unit and browser tests

Test that:

- slider bounds expand to contain issuer values such as NVDA growth above 20% and margin above 60%;
- every slider has a synchronized exact numeric input;
- a baseline value is displayed exactly rather than clipped;
- `-100%` growth cannot create a later-year path below the backend's `-100%` floor;
- invalid WACC/terminal-growth/ROIC combinations show a field error and disable calculation/save;
- invalid margin text does not silently preview as zero.

Run:

```bash
cd apps/web
npm test -- --run src/lib/valuationDraft.test.ts
npx playwright test e2e/valuation-state.spec.ts
```

Expected: FAIL on clipped controls and silent coercion.

### Step 2: Implement pure range and validation helpers

Add helpers that expand a sensible default range outward to include the current value, round by the control step, preserve exact numeric entry, and return field-level errors compatible with backend DCF rules.

### Step 3: Extract the controls component

Render the five editable assumptions in a focused component. Keep the existing visual language, keyboard labels, units, and explanatory provenance. The parent owns draft/calculation state; the child emits validated edits.

### Step 4: Prevent invalid preview/save

Do not coerce empty/invalid input to zero. Show the reason next to the field and disable dependent actions until valid.

### Step 5: Verify and commit

Run:

```bash
cd apps/web
npm test -- --run src/lib/valuationDraft.test.ts
npx playwright test e2e/valuation-state.spec.ts e2e/valuation-setup.spec.ts
```

Commit:

```bash
git add apps/web/src/lib/valuationDraft.ts apps/web/src/lib/valuationDraft.test.ts apps/web/src/components/valuation/ValuationControls.tsx apps/web/src/components/sections/ValuationSection.tsx apps/web/e2e/valuation-state.spec.ts
git commit -m "fix: render exact adaptive valuation controls"
```

## Task 4: Complete the immutable plan-library backend

**Files:**
- Modify: `spec/schema.sql`
- Modify: `equitylens/store/sqlite.py`
- Modify: `equitylens/api/schemas.py`
- Modify: `equitylens/valuation/service.py`
- Modify: `equitylens/api/routes.py`
- Test: `tests/integration/test_onboarding_valuation.py`
- Test: `tests/integration/test_api.py`

### Step 1: Write failing API tests

Cover:

- stable pagination makes 1, 6, and 20+ plans reachable;
- text search finds title/notes;
- archive removes a plan from the active list and restore returns it;
- archived plans remain readable and comparable;
- copying for edit records `parent_plan_id` and increments version only when the recalculated run is saved as a new plan;
- comparison returns field labels and actual values for every selected plan, plus an explicit no-difference result;
- repeated save/copy/archive requests do not create accidental duplicates or lose state.

Run:

```bash
pytest tests/integration/test_onboarding_valuation.py tests/integration/test_api.py -k "plan_library or archive or compare_values" -q
```

Expected: FAIL on the current unpaged, non-archivable library and name-only comparison.

### Step 2: Add the recoverable archive migration

Add a nullable `archived_at` column through the existing idempotent SQLite migration path and schema definition. Never delete a plan for an archive action.

### Step 3: Add list/search/archive/restore contracts

List active plans by default and support `status`, `q`, `limit`, and an opaque/stable cursor. Return `next_cursor`. Add archive and restore endpoints with company ownership checks.

### Step 4: Return structured comparison data

Return each compared editable assumption with per-plan actual values and a `changed` flag; retain the existing summary fields only where compatibility requires them.

### Step 5: Support copy-and-edit lineage

Accept optional `parent_plan_id` on creation, validate ownership, and assign the next version. A copy operation must open an editable draft; it must not pretend an unchanged duplicate is a newly calculated plan.

### Step 6: Verify and commit

Run:

```bash
pytest tests/integration/test_onboarding_valuation.py tests/integration/test_api.py -q
```

Commit:

```bash
git add spec/schema.sql equitylens/store/sqlite.py equitylens/api/schemas.py equitylens/valuation/service.py equitylens/api/routes.py tests/integration/test_onboarding_valuation.py tests/integration/test_api.py
git commit -m "feat: complete recoverable valuation plan library"
```

## Task 5: Deliver the usable plan-library interface

**Files:**
- Create: `apps/web/src/components/valuation/ValuationPlanLibrary.tsx`
- Modify: `apps/web/src/components/sections/ValuationSection.tsx`
- Modify: `apps/web/src/lib/api.ts`
- Test: `apps/web/e2e/valuation-plans.spec.ts`
- Test: `apps/web/e2e/beginner-valuation.spec.ts`

### Step 1: Write failing browser tests

Exercise the actual user journey:

1. save 1, 6, and 20 plans and reach every item;
2. see a visible retryable error when loading fails;
3. search, page, archive, switch to archived, and restore;
4. open an immutable snapshot and see full assumptions/results/notes/conditions;
5. choose “copy and edit”, change an assumption, calculate, save, and see parent/version lineage;
6. compare two plans and read the actual values, including the no-difference case;
7. submit invalid reverse-price text and receive a visible validation message.

Run:

```bash
cd apps/web
npx playwright test e2e/valuation-plans.spec.ts e2e/beginner-valuation.spec.ts
```

Expected: FAIL on swallowed errors, five-item truncation, and incomplete detail/compare behavior.

### Step 2: Add typed API operations

Add typed list cursor/search/status, archive, restore, detailed compare, and plan lineage requests in `api.ts`.

### Step 3: Extract and implement the library component

The library owns query/pagination/archive view/loading/error state. It exposes retry, does not drop prior successful data during a transient failure, and shows clear active/archived states.

### Step 4: Implement open, copy-and-edit, and compare

Open shows the immutable run snapshot. Copy-and-edit loads its five editable values into the personal draft and carries the parent ID until a recalculated plan is saved. Compare renders labels and actual values side by side.

### Step 5: Fix remaining silent validation paths

Show an inline error for invalid reverse-price input and keep the action disabled or rejected without a silent return.

### Step 6: Verify and commit

Run:

```bash
cd apps/web
npm test -- --run
npx playwright test e2e/valuation-plans.spec.ts e2e/beginner-valuation.spec.ts e2e/valuation-state.spec.ts e2e/valuation-setup.spec.ts
```

Commit:

```bash
git add apps/web/src/components/valuation/ValuationPlanLibrary.tsx apps/web/src/components/sections/ValuationSection.tsx apps/web/src/lib/api.ts apps/web/e2e/valuation-plans.spec.ts apps/web/e2e/beginner-valuation.spec.ts
git commit -m "feat: deliver valuation plan workspace"
```

## Task 6: Real-data acceptance, regression, and documentation

**Files:**
- Modify: `docs/reviews/2026-10-01-personal-product-full-validation.md`
- Modify: `docs/reviews/2026-10-01-personal-product-audit.md`
- Modify: `docs/superpowers/specs/2026-10-01-personal-product-reliability-design.md`
- Test: `apps/web/e2e/valuation-plans.spec.ts`

### Step 1: Run the full automated suite

```bash
pytest -q
cd apps/web && npm test -- --run && npm run build
```

Then run the complete browser suite against a freshly started backend/frontend:

```bash
cd apps/web && npx playwright test
```

Expected: all commands PASS. Record exact counts and any intentionally skipped online tests.

### Step 2: Run copied-data acceptance

Using copied fixture/database state (never the user's live primary database), verify AAPL, MSFT, and NVDA where available:

- confirmation → edit each of five fields → preview → save run → save plan;
- reload → open immutable snapshot → copy and edit → save child version;
- compare parent/child actual values;
- archive → reload → restore;
- issuer values outside the former static slider range remain exact;
- publication/model mismatch returns to review-required rather than silently reusing a stale confirmation.

Capture API/browser evidence in the validation report. Do not claim online-source freshness if the network test was not executed.

### Step 3: Update issue status and remaining scope

Mark F01/B05/B06/F04/F05/F13 individually as fixed only when their evidence passes. Keep unrelated items and the separate market/company refresh optimization backlog open.

### Step 4: Review the diff and commit

Run:

```bash
git diff --check
git status --short
```

Commit:

```bash
git add docs/reviews/2026-10-01-personal-product-full-validation.md docs/reviews/2026-10-01-personal-product-audit.md docs/superpowers/specs/2026-10-01-personal-product-reliability-design.md apps/web/e2e/valuation-plans.spec.ts
git commit -m "docs: verify valuation workspace closure"
```

## Completion gate

Before claiming completion:

- run `superpowers:requesting-code-review` against the full branch diff;
- address all blocking review findings with new regression tests;
- run `superpowers:verification-before-completion` and quote fresh command results;
- merge only after the full suite and real copied-data acceptance both pass;
- push the integrated `main` branch to `origin` and verify local/remote HEAD equality.

## Closure evidence (2026-10-03)

- Full backend regression: `530 passed, 1 warning`.
- Frontend verification: lint passed, 5 Vitest tests passed, production build passed, and 52 Playwright tests passed.
- Fresh copied-primary acceptance passed for AAPL, MSFT, and NVDA through confirmation, exact personal edit, saved run, parent/child plan, actual-value comparison, archive, and restore. Immutable-fact tampering returned 409 with zero run writes. The primary database SHA-256 remained `1c6453b11dc2cea69f64f876ac7c6ee1e45147c354ee5b75033c1869ab98227b`.
- Independent review findings were fixed with regressions covering confirmation trust boundaries, current-model readiness, copy/recalculation invariants, monotonic lineage versions, save idempotency, exact controls, scenario detail values, publication-bound Reverse DCF history, and filter-bound cursors.
- F09/P4 responsive layout and the separate market/company refresh backlog remain explicitly out of scope and open.
