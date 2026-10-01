# Data Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent invalid API values, temporary evidence paths, and local-time timestamps from corrupting or misleading persistent EquityLens data.

**Architecture:** Validate typed requests at the HTTP boundary and repeat critical finite-number checks in the domain service. Finalize source-document paths inside the same refresh transaction that publishes staged bytes. Configure every DuckDB connection to UTC while leaving ambiguous historical timestamps untouched, and expose a read-only evidence-path audit before any historical repair.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, DuckDB, pytest.

**Spec:** `docs/superpowers/specs/2026-10-01-personal-product-reliability-design.md`

## Global Constraints

- Never modify formal data during tests; use pytest temporary stores or an explicit data copy.
- Unknown fields, wrong types, NaN and Infinity must fail before writes.
- Historical path repair remains read-only in this plan; no automatic mutation.
- Existing publication, review, revision and fingerprint gates remain intact.

---

### Task 1: Strict request and finite-number boundary

**Files:**
- Modify: `equitylens/api/schemas.py`
- Modify: `equitylens/api/routes.py`
- Modify: `equitylens/valuation/service.py`
- Test: `tests/integration/test_api.py`

**Interfaces:**
- Produces: typed `ResearchAskRequest`, `ValuationRunRequest`, `ReverseDcfRequest`, `ValuationPlanRequest`, `ValuationPlanCopyRequest`, and `RefreshRequest` request bodies.
- Preserves: current successful JSON shapes and HTTP behavior for valid callers.

- [ ] **Step 1: Write failing API tests**

Add parametrized tests proving numeric/string/object mistakes return 4xx, unknown fields are rejected, and a NaN plan request leaves the plan count unchanged. Add a research request test for numeric ticker/question and a refresh request test for invalid modules/operation_finished.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/integration/test_api.py -k 'non_finite or strict_request or wrong_type' -q`

Expected: current dict routes return 500 or accept an invalid value; the plan count changes after NaN.

- [ ] **Step 3: Add strict request schemas and service defense**

Use `ConfigDict(extra="forbid", allow_inf_nan=False)` and strict fields. Constrain `margin_of_safety` to `[0, 1)`, scenario to `base|bear|bull`, conditions to `list[str]`, refresh modules to the four supported literals, and question/ticker to non-empty strings. Keep `math.isfinite()` in `create_plan` as defense below HTTP.

- [ ] **Step 4: Run focused and full API tests**

Run: `uv run pytest tests/integration/test_api.py -q`

Expected: all API integration tests pass; invalid inputs write no rows.

- [ ] **Step 5: Commit**

Commit message: `fix: reject invalid persistent API inputs`

### Task 2: Durable source-document locations

**Files:**
- Create: `equitylens/storage/source_paths.py`
- Modify: `equitylens/refresh/service.py`
- Test: `tests/integration/test_api.py`
- Test: `tests/unit/test_source_paths.py`

**Interfaces:**
- Produces: `finalize_staged_source_paths(store, stage_root, raw_root) -> int` and `audit_source_paths(store, raw_root) -> SourcePathAudit`.
- Consumes: source_document `local_path` and `content_sha256` rows written by module synchronizers.

- [ ] **Step 1: Write failing refresh and audit tests**

Create a staged source document during refresh, let the temporary directory close, then assert the stored path exists under the durable raw root and matches its SHA256. Add read-only audit cases for valid, recoverable, hash-mismatched and missing paths.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/unit/test_source_paths.py tests/integration/test_api.py -k 'source_path or staged_document' -q`

Expected: refreshed row still points into the deleted staging directory; audit API is absent.

- [ ] **Step 3: Implement transactional path finalization**

After `_publish_staged` and before transaction commit, find only rows rooted below the current stage, derive the corresponding durable path, require the destination to exist, verify SHA256, then update `local_path`. Raise on any mismatch so the module transaction rolls back and manifests are restored.

- [ ] **Step 4: Implement read-only historical audit**

Classify each row as `valid`, `recoverable`, `hash_mismatch`, or `missing`. A recoverable row must contain `/raw/`, map to the supplied raw root, exist, and match the stored hash. Do not mutate rows.

- [ ] **Step 5: Run focused refresh tests**

Run: `uv run pytest tests/unit/test_source_paths.py tests/integration/test_api.py -k 'refresh or source_path' -q`

Expected: all pass, including refresh rollback behavior.

- [ ] **Step 6: Commit**

Commit message: `fix: preserve refreshed evidence paths`

### Task 3: UTC database clock contract

**Files:**
- Modify: `equitylens/storage/duckdb_store.py`
- Modify: `equitylens/onboarding/progress.py`
- Test: `tests/unit/test_duckdb_store.py`
- Test: `tests/unit/test_onboarding_progress.py`

**Interfaces:**
- Produces: every `DuckDBStore.connect()` session runs with DuckDB timezone `UTC`.
- Preserves: naive database timestamps are interpreted as UTC only for records written under the new connection contract; no historical bulk rewrite.

- [ ] **Step 1: Write failing timezone tests**

Set process timezone to Asia/Shanghai, open a store, assert DuckDB current timezone is UTC, insert `now()` and compare it to the current UTC instant. Add a progress test showing a newly written naive heartbeat becomes stalled after 46 seconds rather than appearing eight hours in the future.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/unit/test_duckdb_store.py tests/unit/test_onboarding_progress.py -q`

Expected: the connection reports the local timezone or the stored clock differs from UTC.

- [ ] **Step 3: Set UTC on connection and document interpretation**

Execute DuckDB `SET TimeZone='UTC'` immediately after connect. Keep `_aware` explicit about the storage contract. Do not transform existing records.

- [ ] **Step 4: Run onboarding and migration tests**

Run: `uv run pytest tests/unit/test_duckdb_store.py tests/unit/test_onboarding_progress.py tests/integration/test_onboarding_migration.py tests/integration/test_onboarding_runner.py -q`

Expected: all pass in local and UTC process timezone contexts.

- [ ] **Step 5: Commit**

Commit message: `fix: standardize database timestamps on utc`

### Task 4: P0 verification and audit documentation

**Files:**
- Modify: `docs/reviews/2026-10-01-personal-product-full-validation.md`
- Modify: `docs/reviews/2026-09-11-company-onboarding-progress.md`

**Interfaces:**
- Produces: exact P0 verification evidence and a read-only formal-data audit command.

- [ ] **Step 1: Run complete verification**

Run: `uv run pytest -q`

Expected: all backend tests pass.

Run: `pnpm exec tsc --noEmit && pnpm lint && pnpm build` in `apps/web`.

Expected: all commands exit 0.

- [ ] **Step 2: Audit a copied data directory only**

Run the read-only audit against the existing test copy and record counts by classification. Do not apply a repair and do not point it at a writable formal service.

- [ ] **Step 3: Update review status**

Mark only F03/F07/F08/F14 aspects actually proven fixed. Preserve historical evidence and unverified migration/backup gates.

- [ ] **Step 4: Commit**

Commit message: `docs: record data safety verification`

## Review Focus

- Confirm Pydantic coercion cannot turn strings or booleans into persistent numeric values.
- Confirm source path updates and file publication are one rollback unit.
- Confirm path auditing cannot mutate formal data and does not classify a file recoverable without a hash match.
- Confirm timezone changes do not silently reinterpret or rewrite old rows.

