# Trusted Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every research module on one company page read the same immutable publication, expose the period and official evidence behind each conclusion, and refuse conclusions when evidence or valuation approval is missing.

**Architecture:** Add a `PublishedResearchContext` that owns the selected company/security/publication identity plus verified dataset facts, source documents, segment facts and issuer profile. HTTP routes resolve it once and pass it to deterministic research services; no published endpoint may silently instantiate a live-table `MetricEngine`. The browser carries the same identity through every module request and every provenance lookup.

**Tech Stack:** Python 3.12, FastAPI, DuckDB, Pydantic 2, pytest, Next.js 16 App Router, React 19, TypeScript, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-01-personal-product-reliability-design.md`

**Issues covered:** B01, F02, B02, B03, B04, F06, B07, B08, B12, B13.

## Global Constraints

- Published research never falls back to mutable canonical/segment/source tables except for an explicitly marked legacy publication.
- One response contains one `security_id` and `publication_id`; evidence lookup must use that publication.
- Missing evidence produces a visible gap/status, never a positive/negative judgment.
- The research assistant cannot publish a valuation conclusion without the same confirmed valuation gate used by the valuation page.
- Existing valid API shapes remain additive-compatible; frontend work must follow the installed Next.js 16 documentation.
- Tests use fixture or copied data only; do not modify formal data.

---

### Task 1: One immutable research context

**Files:**
- Create: `equitylens/research/context.py`
- Modify: `equitylens/api/routes.py`
- Modify: `equitylens/research/engine.py`
- Modify: `equitylens/domain/risks.py`
- Modify: `equitylens/domain/moat.py`
- Test: `tests/integration/test_api.py`
- Test: `tests/unit/test_research_context.py`

**Interfaces:**
- Produces: `PublishedResearchContext.load(store, company, publication_id)` with publication identity, dataset/profile identity, verified canonical facts, source documents, segment facts, profile content and a publication-backed metric engine.
- Produces: context helpers for provenance-safe evidence IDs and segment reads.
- Preserves: legacy-publication compatibility only when `dataset_version.parser_version == 'legacy'`.

- [x] **Step 1: Write failing split-brain tests**

Create a publication fixture, then insert conflicting newer rows into mutable tables. Assert overview, metrics, risks, moat and research assistant still return only the selected publication's values/evidence. Assert a non-active explicit publication remains stable if the active pointer changes between requests.

- [x] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/unit/test_research_context.py tests/integration/test_api.py -k 'published_research or split_brain' -q`

Expected: risks/moat/assistant read mutable tables or return evidence outside the requested dataset.

- [x] **Step 3: Implement and inject the context**

Load and hash-verify dataset entities once. Construct `MetricEngine(published_facts=...)`; provide published segment/profile/source helpers. Change risks, moat and assistant builders to consume the context. Keep one narrow legacy adapter and label it in code.

- [x] **Step 4: Run focused endpoints**

Run: `uv run pytest tests/unit/test_research_context.py tests/integration/test_api.py -k 'overview or metrics or risks or moat or research' -q`

Expected: all pass and every response identity equals the requested publication.

- [x] **Step 5: Commit**

Commit message: `feat: unify published research context`

### Task 2: Evidence gaps instead of crashes or guesses

**Files:**
- Modify: `equitylens/domain/moat.py`
- Modify: `equitylens/domain/risks.py`
- Modify: `equitylens/api/segments_service.py`
- Modify: `equitylens/api/routes.py`
- Test: `tests/integration/test_api.py`
- Test: `tests/unit/test_moat.py`
- Test: `tests/unit/test_risks.py`

- [x] **Step 1: Write failing missing-evidence tests**

Cover no segment mapping, empty segment facts, missing comparison periods, zero bases, negative bases, stock-split share changes and unavailable modules. Assert HTTP 200 with explicit `gaps`/incomplete checks and no fabricated verdict; never 500 and never call missing evidence a completed check.

- [x] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/unit/test_moat.py tests/unit/test_risks.py tests/integration/test_api.py -k 'missing_evidence or no_segment or negative_base or split' -q`

Expected: current moat path raises or rules emit misleading judgments.

- [x] **Step 3: Make rule outcomes tri-state**

Use `SUPPORTED`, `NOT_SUPPORTED`, and `EVIDENCE_GAP`/`INCOMPLETE_PERIOD` outcomes. Treat missing/zero/negative comparison bases as non-comparable. A share-count jump alone is not dilution when split evidence or per-share restatement is unresolved.

- [x] **Step 4: Verify focused behavior**

Run the same focused suite; assert evidence gaps include a human-readable reason and the next evidence needed.

- [x] **Step 5: Commit**

Commit message: `fix: make research gaps explicit`

### Task 3: Complete three-year statements with cell provenance

**Files:**
- Modify: `equitylens/api/routes.py`
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/components/sections/FinancialsSection.tsx`
- Modify: `apps/web/src/lib/types.ts`
- Test: `tests/integration/test_api.py`
- Test: `apps/web/e2e/research-boundaries.spec.ts`

- [x] **Step 1: Write failing API and browser tests**

Request six annual metrics with `limit=4` and assert up to four rows **per metric**, not four rows total. In the three-year table assert every non-empty cell is a source button and opens provenance under the selected publication.

- [x] **Step 2: Run tests and verify RED**

Run backend: `uv run pytest tests/integration/test_api.py -k 'annual_statement or per_metric_limit' -q`

Run frontend: `PLAYWRIGHT_CHROME_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' pnpm exec playwright test e2e/research-boundaries.spec.ts --reporter=line`

Expected: only four combined facts are returned and table cells cannot open their own evidence.

- [x] **Step 3: Apply per-series limiting and interactive cells**

Limit after grouping by requested metric. Preserve fact/evidence identity in the table model; render non-empty cells as keyboard-accessible buttons using the existing source drawer.

- [x] **Step 4: Commit**

Commit message: `fix: complete annual statements and provenance`

### Task 4: Period-consistent KPIs and honest freshness

**Files:**
- Modify: `equitylens/metrics/engine.py`
- Modify: `equitylens/domain/freshness.py`
- Modify: `equitylens/market/age.py`
- Modify: `equitylens/api/routes.py`
- Modify: `apps/web/src/app/page.tsx`
- Modify: `apps/web/src/components/sections/OverviewSection.tsx`
- Modify: `apps/web/src/components/sections/FinancialsSection.tsx`
- Test: `tests/unit/test_metrics.py`
- Test: `tests/integration/test_api.py`
- Test: `apps/web/e2e/refresh-state.spec.ts`

- [x] **Step 1: Write failing period/freshness tests**

Use staggered facts so revenue, margin and FCF have different latest periods. Assert each KPI reports its own period and the UI warns instead of presenting a shared snapshot. Assert a stale quote says “行情已过期” with observation and fetch times, never “未同步”. Cover negative-base growth as non-comparable.

- [x] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/unit/test_metrics.py tests/integration/test_api.py -k 'period_alignment or stale_quote or negative_base' -q`

- [x] **Step 3: Add period metadata and stale-state contract**

Return per-card periods, an alignment summary and explicit mismatch reasons. Keep `observed_at` separate from `fetched_at`; represent quote state as `ok|stale|missing` end-to-end.

- [x] **Step 4: Verify browser labels**

Run: `PLAYWRIGHT_CHROME_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' pnpm exec playwright test e2e/refresh-state.spec.ts --reporter=line`

- [x] **Step 5: Commit**

Commit message: `fix: expose research periods and quote age`

### Task 5: Enforce the valuation gate in research answers

**Files:**
- Modify: `equitylens/research/context.py`
- Modify: `equitylens/research/engine.py`
- Modify: `equitylens/api/routes.py`
- Test: `tests/integration/test_api.py`
- Test: `tests/integration/test_onboarding_valuation.py`

- [x] **Step 1: Write failing assistant-gate tests**

For a publication without confirmation, ask about valuation and assert no fair value/range is returned. For confirmed identity, assert the answer uses that confirmation, publication, model version and evidence. Cover missing config, stale quote and changed active publication separately.

- [x] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/integration/test_api.py tests/integration/test_onboarding_valuation.py -k 'research_valuation_gate' -q`

Expected: assistant currently calls `default_valuation` and publishes an unconfirmed conclusion.

- [x] **Step 3: Reuse the formal confirmation gate**

Call `require_valuation_confirmation` with the context security/publication/model identity. If unavailable, return a structured `needs_review` answer and a valuation-page action; do not compute a default conclusion.

- [x] **Step 4: Commit**

Commit message: `fix: apply valuation gate to research assistant`

### Task 6: Publication identity and official links in every UI module

**Files:**
- Modify: `apps/web/src/app/page.tsx`
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/lib/types.ts`
- Modify: `apps/web/src/components/sections/BusinessSection.tsx`
- Modify: `apps/web/src/components/sections/FinancialsSection.tsx`
- Modify: `apps/web/src/components/sections/MoatSection.tsx`
- Modify: `apps/web/src/components/sections/RisksSection.tsx`
- Modify: `apps/web/src/components/sections/AiSection.tsx`
- Modify: `apps/web/src/components/SourceDrawer.tsx`
- Modify: `equitylens/api/routes.py`
- Test: `apps/web/e2e/research-boundaries.spec.ts`
- Test: `tests/integration/test_api.py`

- [ ] **Step 1: Read installed Next.js guidance**

Read `apps/web/node_modules/next/dist/docs/03-architecture/accessibility.md` and the relevant App Router client-component/data-fetching pages before editing.

- [ ] **Step 2: Write failing browser tests**

Intercept all module requests and assert `security_id` plus `publication_id` are present. Change the directory's active publication during a loaded page and assert existing modules remain pinned until the shell intentionally reloads. Assert segment evidence and deep canonical evidence reach a clickable official URL; an unavailable URL is labeled as a gap.

- [ ] **Step 3: Run tests and verify RED**

Run: `PLAYWRIGHT_CHROME_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' pnpm exec playwright test e2e/research-boundaries.spec.ts --reporter=line`

- [ ] **Step 4: Thread a single identity object**

Pass `{security_id, publication_id}` from the selected directory item to all sections and API helpers. Include the publication in assistant POST bodies. Extend provenance traversal only as needed to surface the dataset's official source document; do not fall back to live tables.

- [ ] **Step 5: Commit**

Commit message: `feat: pin research ui to publication`

### Task 7: P1 real-flow verification and progress documentation

**Files:**
- Modify: `docs/reviews/2026-10-01-personal-product-full-validation.md`
- Modify: `docs/reviews/2026-09-11-company-onboarding-progress.md`

- [ ] **Step 1: Run full automated verification**

Run: `uv run pytest -q`

Run in `apps/web`: `pnpm exec tsc --noEmit && pnpm lint && pnpm build`

Run: `PLAYWRIGHT_CHROME_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' pnpm exec playwright test --reporter=line`

- [ ] **Step 2: Run copied-data user flows**

Start backend/frontend against the existing isolated data copy. For AAPL and MSFT open overview, financials, business, moat, risks and assistant; capture each returned publication identity and verify at least one official evidence link per available module. Exercise missing-segment and unconfirmed-valuation paths using fixture/copy state, not formal data.

- [ ] **Step 3: Update status precisely**

Mark only B01/F02/B02/B03/B04/F06/B07/B08/B12/B13 cases proven by tests and copied-data flows. Record any unavailable external link separately from code correctness.

- [ ] **Step 4: Commit**

Commit message: `docs: record trusted research verification`

## Review Focus

- No published research service can construct a live-table metric/segment read behind the context.
- Evidence IDs belong to the selected dataset and provenance cannot escape into another publication.
- Missing evidence and negative/zero bases never become directional claims.
- Assistant valuation text cannot bypass confirmation or model-applicability gates.
- Every browser module stays on one identity during concurrent reloads and company switches.
