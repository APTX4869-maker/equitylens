# EquityLens Remediation Batch 4 Implementation Plan

**Goal:** Make every valuation assumption and research conclusion understandable, traceable, and usable by a financial beginner without changing the deterministic calculation engine.

**Architecture:** Normalize assumption metadata at the valuation-service boundary so API, saved runs, and UI share one contract. Define scenarios from issuer-specific economic stories and explicit changed fields. Keep advanced diagnostics available behind disclosure controls while the beginner path presents evidence, uncertainty, actions, and review triggers in reading order. Research and risk responses expose actual check coverage and resolvable evidence identities.

**Tech Stack:** Python 3.12, FastAPI, DuckDB, pytest, Next.js 16.3.3, React 19.2.8, TypeScript, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-06-remediation-rework-design.md`

## Global Constraints

- Preserve historical valuation runs and plans; new explanatory fields are additive.
- Source facts, deterministic formulas, configuration assumptions, fallbacks, and user overrides keep distinct source types.
- Negative operating outcomes remain visible; scenarios and reference ranges never clip or rename results to force an ordering.
- Beginner and professional modes use the same draft and model result.
- Tests use temporary stores and stubbed browser APIs; do not sync real data.

---

### Task 1: Complete Default-Assumption Provenance (P01)

**Files:** `config/valuation/wacc_defaults.yaml`, `equitylens/valuation/defaults.py`, `equitylens/valuation/service.py`, `apps/web/src/components/sections/ValuationSection.tsx`, `tests/golden/test_golden_valuation.py`, `tests/integration/test_api.py`

- [x] Add API regressions requiring metadata for every `DcfInputs` field: source type, evidence IDs or config version, period/date, rule, default reason, and fallback reason when used.
- [x] Add versioned issuer reasons for growth, margin, working capital, terminal growth, capital weights, beta, debt cost, ERP, and terminal ROIC. Reject unknown issuers.
- [x] Normalize fact-derived and fallback metadata. Record tax normalization and the exact revenue/margin/share periods; label share basis from metadata rather than value magnitude.
- [x] Show the current company reference, default reason, source/date/version, and calculation rule beside each editable assumption.
- [x] Run focused backend tests, TypeScript, ESLint, update Batch 4 evidence/progress, and commit.

---

### Task 2: Make Scenarios Economic and Stress-Capable (P03)

**Files:** `config/valuation/wacc_defaults.yaml`, `equitylens/valuation/service.py`, `apps/web/src/components/sections/ValuationSection.tsx`, `tests/golden/test_golden_valuation.py`, `tests/integration/test_api.py`, `apps/web/e2e/beginner-valuation.spec.ts`

- [x] Add failing tests for a −5% first-year stress path, a loss-making base whose bear margin becomes more negative, and scenario fields/stories that exactly describe all changes.
- [x] Define issuer-specific Bear/Base/Bull stories and explicit deltas/paths in versioned config. Do not use magnitude-based labels or clamp margins at zero.
- [x] Return `story`, `changed_fields`, full CapEx/D&A/NWC and terminal assumptions, status, and reason for every scenario.
- [x] Render expandable scenario details and preserve the scenario names even when result values are not ordered.
- [x] Run focused backend/browser checks, update Batch 4 evidence/progress, and commit.

---

### Task 3: Enforce Evidence and Conclusion Boundaries (P05/U01/U05 remainder)

**Files:** `equitylens/domain/risks.py`, `equitylens/research/engine.py`, `equitylens/api/routes.py`, `apps/web/src/components/sections/RisksSection.tsx`, `apps/web/src/components/sections/AiSection.tsx`, `apps/web/src/components/SourceDrawer.tsx`, tests under `tests/unit` and `tests/integration`

- [x] Add regressions showing failed risk checks remain unavailable, numeric claims have resolvable evidence IDs, and unsupported research questions return capability guidance without unrelated claims.
- [x] Return risk coverage counts/statuses and keep severity independent from evidence confidence. Replace unconditional “no risk” language with the actual completed-check boundary.
- [x] Make every numeric research claim use canonical or derived identities that the provenance endpoint can resolve; mark structural statements separately.
- [x] Present deterministic rules as reproducible rules, not correctness guarantees; expose evidence and unavailable checks in the risk/research UI.
- [x] Verify ticker changes clear source/research context, run focused checks, update Batch 4 evidence/progress, and commit.

---

### Task 4: Finish the Beginner Reading Path (P04)

**Files:** `apps/web/src/components/sections/ValuationSection.tsx`, `apps/web/src/components/MetricDrawer.tsx`, `apps/web/src/lib/metricKnowledge.ts`, `apps/web/src/app/globals.css`, `apps/web/e2e/beginner-valuation.spec.ts`, documentation under `docs/reviews`

- [x] Write a scripted browser reading test that finds company economics/data recency, the current growth and its source, the least reliable assumption, WACC direction, scenario method, reverse DCF, safety margin, and review trigger.
- [x] Reorder beginner mode into evidence → range/uncertainty → adjust assumptions → reverse DCF → save/review. Keep sensitivity and raw field metadata collapsed until requested.
- [x] Add plain-language parameter explanations with raise/lower effects; do not describe WACC as a promised return. Keep edited inputs when switching modes.
- [x] Confirm ratio titles/units follow the selected metric and all drawers are company-safe. Financials and Overview both expose the selected title/unit; KPI drawers prefer the complete derived result identity and company switching closes open drawers.
- [x] Run full backend, TypeScript, ESLint, and all Playwright tests. Update the Batch 4 evidence and consolidated progress documents after completion.
- [x] Apply verification-before-completion and finish the development branch workflow.
