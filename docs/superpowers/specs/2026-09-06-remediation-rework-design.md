# EquityLens Remediation Rework Design

Date: 2026-09-06

## Purpose

Repair the items that were reported as complete but do not meet the original acceptance criteria, then finish the remaining remediation work. The result must give a single user trustworthy, explainable US equity analysis without silently substituting stale, incomplete, or differently scoped data.

This design implements the requirements in `docs/reviews/2026-09-05-equitylens-remediation-handoff.md` and resolves the findings in `docs/reviews/2026-09-06-remediation-quality-review.md`. The handoff remains the product specification; this document defines the implementation boundaries and order for the rework.

## Decisions

1. Work proceeds in dependency order through four independently verifiable batches.
2. Each defect starts with a regression test that demonstrates the reviewed failure.
3. `fcff_dcf.v2` becomes the default method for new calculations after its full product path is connected.
4. `fcff_dcf.v1` remains readable for historical runs. Stored v1 outputs are never recalculated through v2.
5. Existing raw snapshots, valuation runs, plans, and database backups are preserved. Schema changes are additive and legacy rows are explicitly marked incomplete when data is absent.
6. A zero value remains a valid observation. Missing, incomplete, stale, invalid, and unsupported states remain distinct throughout the backend and UI.
7. Preview calculations do not persist. Persistence occurs only after an explicit save action and records the complete immutable calculation snapshot.

## Batch 1: Correct Numbers and Input Identity

This batch repairs issues that can currently produce an incorrect number or associate a result with the wrong input.

### Financial period and TTM contract

Create one shared trailing-window result used by metrics, market multiples, risks, research, and UI APIs. A valid TTM window contains four distinct, consecutive fiscal quarters with compatible metric, currency, unit, period semantics, and non-null values. Zero is valid. If the latest expected window is incomplete, consumers receive `INCOMPLETE_PERIOD` with the missing or conflicting quarter identities; they must not search backward for an older valid window and present it as current.

Metric results expose frequency, period start and end, status, missing reason, formula version, value unit, and every input fact ID. P/E, P/FCF, and FCF yield use the current TTM result only. Risks and research consume the same metric service rather than summing the latest four rows themselves.

### Fiscal quarter and depreciation selection

Fiscal-period matching normalizes date, datetime, and ISO string values before comparison. Quarter derivation requires the documented cumulative buckets, keeps Q1 equivalence explicit, and rejects incompatible periods rather than guessing.

Depreciation and amortization inputs are selected for the same fiscal period and unit as the valuation revenue base. A reliable combined value wins only within that target period. Otherwise compatible, non-overlapping depreciation and amortization components are added for that same period. Older combined values cannot override current split values. Missing or conflicting components produce a visible estimate or missing state according to the original V01 policy.

### DCF validation and calculation identity

All DCF entry points share validation for finite numbers, path length, positive revenue and shares, growth at or above -100%, compatible rate relationships, model-compatible tax, margin, reinvestment inputs, and finite terminal assumptions. Invalid input returns one structured client error and performs no write.

At -100% revenue growth, working-capital change uses the prior revenue base before advancing revenue to zero, so released working capital remains in FCFF. Negative operating profit, FCFF, and equity value remain valid economic results when inputs are otherwise valid.

The valuation page owns a complete local draft. Every preview request carries the complete draft and a deterministic input fingerprint. Local state updates immediately when the user edits a field. A response can update displayed output only when ticker, request sequence, and fingerprint all match the latest applied draft. Failed or unapplied drafts cannot be saved as if they produced the visible result.

### Batch 1 acceptance

- Latest zero or incomplete TTM values never fall back to an older normal multiple.
- Risks and research report module coverage and failure reasons instead of swallowing errors.
- Date objects and ISO strings produce identical quarter derivation.
- Current split D&A beats an unrelated older combined value.
- Negative CapEx ratios and invalid WACC combinations are rejected consistently.
- The reviewed -100% growth working-capital example produces the correct release.
- Controlled out-of-order valuation requests cannot associate an old growth path with a new WACC or ticker.

## Batch 2: Reproducibility, Provenance, and Freshness

### Immutable raw snapshot identity

Snapshot lookup by SHA is strict. The requested full hash or unambiguous supported prefix must identify bytes with the matching computed SHA; an unknown hash returns no result and corrupted content raises an integrity error. It never falls back to the fixed legacy filename for a mismatched SHA.

Snapshot files and the manifest remain immutable records. Manifest updates use a temporary file, file sync where supported, and atomic replacement after the snapshot is durable. A failed save or fetch leaves the previous latest pointer intact.

### Derived-result provenance

A derived metric has its own stable result identity instead of borrowing a canonical input fact ID. The provenance root contains ticker, metric, frequency, period, result value, result unit, status, formula ID/version, and the complete ordered input list. Every input can be expanded to canonical fact and source document. The overview, financials, risks, research, valuation, and source drawer pass this result identity.

The API may retain legacy fields during migration, but the new result identity is authoritative. UI cards must show the same value, frequency, unit, and period as the opened provenance root.

### Freshness semantics

Freshness separates data period or filing date, provider observation time, fetch time, replay time, calculation time, and last successful check. SEC financial-data age is based on the latest applicable filed/published disclosure, never the ingestion completion time. Market quote age is based on a timezone-aware provider observation time; an unparseable or future time is degraded rather than replaced by fetch time. Governance age remains tied to the latest proxy filing.

Quote comparison and top-level freshness use the same status. Stale quotes remain viewable with their date but cannot appear as a current-price comparison without a warning state.

### Complete valuation runs

Saved runs contain the exact input fingerprint, complete executed inputs and metadata, fact snapshot identities, market observation identity, base result, every scenario status and output, sensitivity cells, model-quality block, warnings, model version, and calculation timestamp. Override metadata covers every editable input and reflects the executed value.

Run reads return stored data verbatim. Legacy rows without new fields are returned with `legacy/incomplete` status and their stored v1 output. The UI says a run is saved only after success and shows its run ID. Editing inputs after a calculation marks the visible result and reverse calculation as stale.

### Batch 2 acceptance

- Unknown or corrupted requested snapshot hashes cannot return unrelated bytes.
- A derived TTM or ratio source tree exactly matches its card.
- Replaying an old quote or ingesting an old filing today does not refresh its observation or disclosure date.
- Restarting the application and reading a saved run returns the same full inputs, scenarios, sensitivity, and outputs.
- Historical v1 runs remain inspectable without v2 reinterpretation.

## Batch 3: Complete the Product Workflows

### `fcff_dcf.v2` reinvestment and terminal model

The v2 engine accepts explicit annual operating paths and a stable-period terminal input set. It computes annual EBIT, taxes, D&A, CapEx, change in working capital, FCFF, discount factors, and terminal value without applying terminal growth twice. Stable growth, margins, return on incremental capital or equivalent reinvestment assumptions, and the terminal-year cash-flow definition are documented in the response.

The same v2 executor is used by default valuation, custom preview, scenarios, sensitivity, reverse DCF, persisted runs, API schemas, and the UI. There is no test-only calculation path. Scenario construction alters assumptions before execution and validates each scenario independently.

Method dispatch is explicit by `model_version`. New calculations default to v2 only after all consumers are migrated. Historical v1 records use stored outputs; if a v1 executor is retained, it is selected only by explicit version.

### Personal valuation plans

A plan references a valid saved valuation run and selected scenario or another explicit, traceable reference source. The backend rejects an ordinary buy-price plan without assumptions, source identity, or a valid positive reference value. Non-positive valuation results remain explanatory and do not generate a normal buy price.

Plans support name, selected reference, safety margin, notes, conditions to verify, immutable creation version, and review status. The UI can open inputs, copy a plan as a new version, compare plans, and mark plans for review when newer financial disclosures or quote observations exist. Read APIs preserve every reason and status written at creation.

### One-click refresh

Refresh reports financials, segments, management, and quotes independently. A failure in one optional module does not erase successful modules. The response retains module timestamps, errors, and retry eligibility. Users can retry only failed modules.

Writes for one company are serialized, and snapshot/database publication does not expose a half-updated latest state. Cross-company writes respect DuckDB's process-level constraints. On completion, the currently visible section reloads from the new snapshot. Existing draft valuations and saved plans are marked for review rather than silently recalculated.

### Batch 3 acceptance

- Positive terminal growth is covered by hand calculations that detect double growth.
- API and UI calculations all report `fcff_dcf.v2`; no production path calls the explicit engine only from tests.
- A plan cannot be created from arbitrary price and margin fields without a traceable valuation reference.
- Plan open, copy, compare, notes, conditions, and review state work after restart.
- Refresh includes all four modules, supports failed-module retry, refreshes the active page, and preserves old complete snapshots on partial failure.

## Batch 4: Explanation and Beginner Quality

Default assumptions identify their source type, source IDs or configuration version, relevant date or period, weighting or normalization rule, and fallback reason. Share-count labels come from actual fact identity instead of magnitude heuristics.

Scenario inputs allow negative growth where the model supports it. Bear, base, and bull labels describe the actual economic changes; a loss-making company's bear margin cannot be mechanically improved to zero. Each scenario includes a company-specific assumption story and the exact changed fields.

Beginner mode introduces the company history reference before an editable assumption, explains why the default was selected and how raising or lowering it affects value, and keeps the advanced sensitivity matrix collapsed until requested. The walkthrough covers company economics, data recency, scenario assumptions, reverse DCF, safety margin, and later review.

Deterministic research and risk conclusions state evidence coverage and unavailable checks. They never claim a module was checked after its calculation failed. Numeric claims carry resolvable evidence identities. Template conclusions are conditional on computed evidence rather than unconditional stock phrases. Ratio charts use ratio formatting and metric-specific titles.

### Batch 4 acceptance

- Every displayed default has a reason, date or version, and traceable source type.
- A user can run the required negative-growth stress case, and bear assumptions do not improve a loss by construction.
- Overview and source drawers reset on ticker changes and never retain another company's context.
- Ratio charts, titles, and units follow the selected metric.
- A scripted beginner reading test can answer what the number means, where it came from, which assumption matters most, and when the plan must be reviewed.

## Interfaces and Compatibility

Backend responses use explicit status values such as `OK`, `MISSING_INPUT`, `INCOMPLETE_PERIOD`, `STALE`, `INVALID_ASSUMPTION`, and `UNSUPPORTED`. Existing lowercase values may be mapped at the API boundary during migration, but one response cannot use a success value for a missing or stale result.

API schema changes are additive until the frontend migrates. Database migrations add nullable columns or versioned JSON structures and preserve current rows. Once the frontend consumes the new contract and compatibility tests pass, unused legacy response fields may be removed in a separate cleanup.

The supported company list remains AAPL and MSFT. This repair does not add multi-user accounts, arbitrary ticker ingestion, automated trading, an LLM dependency, or a peer-comparison dataset.

## Error Handling

Domain validation returns structured errors containing a stable code, field or module, and human-readable reason. Unexpected exceptions are logged and reported as module failures; they are not converted into successful empty content. Optional module failures preserve usable sibling results and their identities.

No failure path writes a valuation run or plan. Snapshot and refresh publication commits only complete immutable artifacts. A UI error clears or marks incompatible prior output so it cannot be saved under the new draft.

## Testing Strategy

Each behavior follows red-green-refactor: add the smallest failing regression, verify the failure matches the reviewed defect, implement the minimum correction, then run the focused suite. Batch completion requires backend unit/integration/golden tests, frontend type and lint checks, and targeted browser tests for request ordering, ticker changes, plan workflows, and refresh state.

Golden values are updated only when a corrected financial formula or verified source input explains the change. Tests must not bless the currently observed defective value. Database-writing integration tests use temporary stores; real data is read-only until a separately reviewed migration is required.

At the end of each batch, update the remediation status from evidence: implemented behavior, regression test, API/UI consistency, model/formula version, persistence impact, and remaining limitations. Contradictory completion claims in prior delivery notes are superseded by the final consolidated record.

## Delivery Sequence

1. Batch 1 establishes correct shared financial and valuation inputs.
2. Batch 2 establishes identities required for immutable v2 runs and plans.
3. Batch 3 connects the v2 calculation and complete user workflows.
4. Batch 4 completes explanation quality after the underlying values and identities are stable.

Each batch is reviewable and testable on its own. A later batch may depend on an earlier interface, but it must not silently change an earlier batch's accepted behavior.
