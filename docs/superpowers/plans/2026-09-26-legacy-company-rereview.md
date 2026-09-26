# Legacy Company Rereview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a recoverable, auditable maintainer flow that upgrades AAPL/MSFT from `LEGACY_UNREVIEWED` to a newly reviewed immutable publication without interrupting the currently visible publication.

**Architecture:** A new maintenance-only API/CLI creates a normal onboarding task for an existing legacy security and pins its active publication as `base_publication_id`. The existing pipeline performs fresh FETCH → BUILD → VALIDATE → REVIEW, and the existing publication transaction receives that base as `expected_active_publication_id` so a concurrent publication change fails atomically. Existing onboarding UI renders the task and labels its legacy baseline; no second workflow is introduced.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, DuckDB, pytest, Next.js 16, React 19, TypeScript, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-26-legacy-company-rereview-design.md`

## Global Constraints

- Only companies whose current `quality_status` is exactly `LEGACY_UNREVIEWED` may start rereview.
- The old active publication remains the default readable version until an atomic successful publish.
- The task must persist and expose the exact `base_publication_id`; no caller may supply or override it.
- Ordinary add-company requests for an already published security must continue returning `ALREADY_PUBLISHED`.
- CLI operations call the local API only and never fall back to direct DuckDB writes.
- Existing quality, exact-fingerprint review, single-writer, retry, cancellation, and recovery gates remain mandatory.
- KO/COST evidence blockers are unchanged.
- No dependency or framework upgrades.

---

### Task 1: Persist the rereview publication baseline

**Files:**
- Modify: `spec/schema.sql`
- Modify: `equitylens/storage/migrations.py`
- Modify: `equitylens/onboarding/models.py`
- Modify: `equitylens/onboarding/repository.py`
- Modify: `tests/integration/test_onboarding_migration.py`
- Modify: `tests/integration/test_onboarding_runner.py`

**Interfaces:**
- Produces: `TaskView.base_publication_id: str | None`
- Produces: `OnboardingRepository.create_task(..., base_publication_id: str | None = None) -> TaskView`
- Produces: migration 8, `legacy_rereview_baseline`, adding nullable `company_onboarding.base_publication_id`
- Consumed by Tasks 2—4 when creating, publishing, serializing, and displaying rereview tasks.

- [ ] **Step 1: Add failing migration and repository tests**

Add assertions equivalent to:

```python
def test_migration_adds_nullable_rereview_baseline(existing_v7_database):
    apply_migrations(existing_v7_database)
    columns = {row[1] for row in existing_v7_database.execute(
        "pragma table_info('company_onboarding')"
    ).fetchall()}
    assert "base_publication_id" in columns

def test_task_persists_base_publication_id(onboarding_repository, registered_security):
    task = onboarding_repository.create_task(
        company_id=registered_security.company_id,
        security_id=registered_security.security_id,
        input_fingerprint="rereview-input",
        base_publication_id="legacy-publication-v1",
    )
    assert task.base_publication_id == "legacy-publication-v1"
```

Also assert a normal task defaults to `None`, and `_step_input_hash` changes when only the baseline changes.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.venv/bin/python -m pytest tests/integration/test_onboarding_migration.py tests/integration/test_onboarding_runner.py -q`

Expected: FAIL because migration 8, the repository argument, and `TaskView.base_publication_id` do not exist.

- [ ] **Step 3: Add migration 8 and model/repository plumbing**

Implement `_legacy_rereview_baseline(conn)` with:

```python
conn.execute(
    "ALTER TABLE company_onboarding ADD COLUMN IF NOT EXISTS base_publication_id VARCHAR"
)
```

Register a new immutable migration signature, update `spec/schema.sql`, extend `TaskView`, include the field in `OnboardingRepository.get`, accept it in `create_task`, persist it on new rows, and include it in `_step_input_hash`. Existing active-task reuse must not rewrite an established baseline.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/integration/test_onboarding_migration.py tests/integration/test_onboarding_runner.py -q`

Expected: all selected tests PASS.

- [ ] **Step 5: Commit**

```bash
git add spec/schema.sql equitylens/storage/migrations.py equitylens/onboarding/models.py equitylens/onboarding/repository.py tests/integration/test_onboarding_migration.py tests/integration/test_onboarding_runner.py
git commit -m "feat: persist legacy rereview baseline"
```

### Task 2: Create a maintenance-only rereview API

**Files:**
- Modify: `equitylens/api/company_schemas.py`
- Modify: `equitylens/onboarding/service.py`
- Modify: `equitylens/api/company_routes.py`
- Modify: `tests/integration/test_onboarding_api.py`

**Interfaces:**
- Consumes: `OnboardingRepository.create_task(..., base_publication_id=...)` from Task 1.
- Produces: `RereviewRequest(ticker: str)`.
- Produces: `OnboardingService.rereview(ticker: str, idempotency_key: str) -> TaskView`.
- Produces: `POST /api/v1/company-onboardings/rereview` with required `Idempotency-Key` and `202` response.
- Consumed by Task 4 CLI.

- [ ] **Step 1: Add failing API behavior tests**

Create legacy and verified fixtures through real migrations and registry rows, then add tests equivalent to:

```python
def test_legacy_company_can_start_rereview(client, legacy_company):
    response = client.post(
        "/api/v1/company-onboardings/rereview",
        headers={"Idempotency-Key": "rereview-aapl-v2"},
        json={"ticker": legacy_company.ticker},
    )
    assert response.status_code == 202
    assert response.json()["base_publication_id"] == legacy_company.publication_id
    assert response.json()["state"] == "QUEUED"

def test_verified_company_cannot_start_legacy_rereview(client, verified_company):
    response = client.post(
        "/api/v1/company-onboardings/rereview",
        headers={"Idempotency-Key": "verified"},
        json={"ticker": verified_company.ticker},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "REREVIEW_NOT_ALLOWED"
```

Cover missing/ambiguous/inactive security, no active publication, same-key replay, same-key different input, different-key convergence on one active task, and preservation of the existing ordinary `ALREADY_PUBLISHED` behavior.

- [ ] **Step 2: Run the API tests and verify RED**

Run: `.venv/bin/python -m pytest tests/integration/test_onboarding_api.py -q`

Expected: FAIL with the rereview route missing (`404`) and service method absent.

- [ ] **Step 3: Implement the service transaction and route**

Normalize/resolve ticker through `CompanyRegistry`. Build the idempotency hash from literal operation `REREVIEW`, canonical ticker, `security_id`, and the database-derived active publication. Inside the shared writer transaction re-read the active security, `quality_status`, and publication; reject changed inputs with `TASK_CONFLICT`. Call `create_task` with the pinned baseline, persist the idempotency response, and wake the executor after success.

Declare `/company-onboardings/rereview` before the parameterized `/{task_id}` route. Map the specified error codes through the existing structured error envelope.

- [ ] **Step 4: Run API tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/integration/test_onboarding_api.py -q`

Expected: all selected tests PASS, including unchanged add-company behavior.

- [ ] **Step 5: Commit**

```bash
git add equitylens/api/company_schemas.py equitylens/onboarding/service.py equitylens/api/company_routes.py tests/integration/test_onboarding_api.py
git commit -m "feat: start legacy company rereviews"
```

### Task 3: Enforce the baseline at review and publication boundaries

**Files:**
- Modify: `equitylens/issuers/review.py`
- Modify: `equitylens/publication/repository.py`
- Modify: `tests/integration/test_issuer_review.py`
- Modify: `tests/integration/test_publication.py`

**Interfaces:**
- Consumes: `TaskView.base_publication_id` from Task 1.
- Produces: review packages with `base_publication_id`.
- Produces: `PublicationRepository.publish()` forwarding the task baseline to `publish_dataset(expected_active_publication_id=...)`.

- [ ] **Step 1: Add failing conflict and traceability tests**

Add assertions equivalent to:

```python
def test_rereview_package_names_the_replaced_publication(review_case):
    task = review_case.ready_legacy_rereview(base_publication_id="legacy-v1")
    assert review_case.package(task)["base_publication_id"] == "legacy-v1"

def test_rereview_publish_rejects_a_changed_active_publication(review_case):
    task = review_case.approved_legacy_rereview(base_publication_id="legacy-v1")
    review_case.switch_active_publication("other-v2")
    with pytest.raises(PublicationConflict) as error:
        review_case.publish(task)
    assert error.value.code == "PUBLICATION_CONFLICT"
    assert review_case.active_publication_id == "other-v2"
    assert review_case.task(task).state == TaskState.PUBLISHING
```

Add a success test proving the old publication remains explicitly readable after the new pointer becomes active and current valuation plans become `needs_review`.

- [ ] **Step 2: Run review/publication tests and verify RED**

Run: `.venv/bin/python -m pytest tests/integration/test_issuer_review.py tests/integration/test_publication.py -q`

Expected: FAIL because the package omits the baseline and publish does not enforce it.

- [ ] **Step 3: Forward and expose the baseline**

Add `base_publication_id` to `ReviewService.review_package`. In `PublicationRepository.publish`, pass `task["base_publication_id"]` to `publish_dataset(expected_active_publication_id=...)`. Preserve the current semantics for first-time tasks whose baseline is `NULL`.

- [ ] **Step 4: Run review/publication tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/integration/test_issuer_review.py tests/integration/test_publication.py -q`

Expected: all selected tests PASS.

- [ ] **Step 5: Commit**

```bash
git add equitylens/issuers/review.py equitylens/publication/repository.py tests/integration/test_issuer_review.py tests/integration/test_publication.py
git commit -m "fix: fence rereview publication switches"
```

### Task 4: Expose the maintenance command and task identity in the UI

**Files:**
- Modify: `equitylens/cli.py`
- Modify: `tests/integration/test_issuer_review.py`
- Modify: `apps/web/src/lib/types.ts`
- Modify: `apps/web/src/components/companies/OnboardingDetail.tsx`
- Modify: `apps/web/e2e/company-onboarding.spec.ts`
- Modify: `docs/company-onboarding-maintainer-guide.md`

**Interfaces:**
- Consumes: Task 2 API and Task 1 task payload.
- Produces: `equitylens onboarding rereview TICKER --idempotency-key KEY`.
- Produces: task detail label `旧版公司新标准复核` and visible baseline publication.

- [ ] **Step 1: Add failing CLI and browser tests**

Extend the existing CLI request seam:

```python
def test_cli_rereview_calls_local_api(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "_onboarding_request", lambda method, path, **kw: calls.append((method, path, kw)) or {"onboarding_id": "task-aapl"})
    assert cli.main(["onboarding", "rereview", "AAPL", "--idempotency-key", "legacy-aapl-v2"]) == 0
    assert calls == [("POST", "/company-onboardings/rereview", {
        "json_body": {"ticker": "AAPL"},
        "headers": {"Idempotency-Key": "legacy-aapl-v2"},
    })]
```

Add a Playwright fixture task with `base_publication_id: "legacy-publication-aapl-v1"` and assert the task detail shows both `旧版公司新标准复核` and the baseline identifier.

- [ ] **Step 2: Run focused CLI/browser tests and verify RED**

Run: `.venv/bin/python -m pytest tests/integration/test_issuer_review.py -q`

Run: `PLAYWRIGHT_CHROME_PATH='/Users/vincent/Library/Caches/ms-playwright/chromium_headless_shell-1217/chrome-headless-shell-mac-arm64/chrome-headless-shell' pnpm --dir apps/web exec playwright test e2e/company-onboarding.spec.ts --grep "legacy rereview"`

Expected: CLI parser rejects `rereview`; browser assertion fails because baseline metadata is not rendered.

- [ ] **Step 3: Implement CLI and UI copy**

Teach `_onboarding_request` to accept explicit headers if it does not already. Add the `rereview` parser before commands requiring `onboarding_id`, post only `{ticker}`, and print the returned JSON. Extend `OnboardingTask` with `base_publication_id?: string | null`. In `OnboardingDetail`, render a rereview badge/description and a ledger cell labelled `基线发布版本`; normal tasks retain their existing layout and copy.

Update the maintainer guide with the exact command, eligibility, retry behavior, and rule that a publication conflict requires canceling and starting from a new baseline.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/integration/test_issuer_review.py -q`

Run: `PLAYWRIGHT_CHROME_PATH='/Users/vincent/Library/Caches/ms-playwright/chromium_headless_shell-1217/chrome-headless-shell-mac-arm64/chrome-headless-shell' pnpm --dir apps/web exec playwright test e2e/company-onboarding.spec.ts --grep "legacy rereview"`

Expected: both commands PASS.

- [ ] **Step 5: Commit**

```bash
git add equitylens/cli.py tests/integration/test_issuer_review.py apps/web/src/lib/types.ts apps/web/src/components/companies/OnboardingDetail.tsx apps/web/e2e/company-onboarding.spec.ts docs/company-onboarding-maintainer-guide.md
git commit -m "feat: expose legacy rereview workflow"
```

### Task 5: Rehearse AAPL/MSFT and complete delivery evidence

**Files:**
- Modify: `docs/reviews/2026-09-11-company-onboarding-progress.md`
- Create: `docs/reviews/2026-09-26-legacy-company-rereview-validation.md`
- Modify: `docs/superpowers/plans/2026-09-11-company-onboarding.md`
- Test: `tests/golden/test_onboarding_issuers.py`

**Interfaces:**
- Consumes: the complete rereview workflow from Tasks 1—4.
- Produces: reproducible validation identifiers, backup hashes/paths, quality/review/publication IDs, and an accurate T10 status.

- [ ] **Step 1: Run focused static and regression verification**

Run:

```bash
.venv/bin/python -m pytest tests/integration/test_onboarding_migration.py tests/integration/test_onboarding_runner.py tests/integration/test_onboarding_api.py tests/integration/test_issuer_review.py tests/integration/test_publication.py tests/golden/test_onboarding_issuers.py -q
pnpm --dir apps/web exec tsc --noEmit
pnpm --dir apps/web lint
```

Expected: all commands PASS.

- [ ] **Step 2: Create and hash an isolated formal-data copy**

Confirm `lsof data/equitylens.duckdb` has no writer. Create an explicit `mktemp -d /tmp/equitylens-legacy-rereview.XXXXXX`, copy `data/equitylens.duckdb` and `data/raw` without changing the source, and record SHA-256 plus row/publication counts before mutation in the validation document.

Expected: source and copied database hashes match before the copy is opened for migration; source raw manifest/file counts match the copy.

- [ ] **Step 3: Run AAPL then MSFT through the real local API on the isolated copy**

Start the API with `EQUITYLENS_DATA_DIR` pointing at the isolated directory and the already configured identifying SEC User-Agent. For each ticker, invoke `onboarding rereview`, allow FETCH to finish, import its checked-in v2 profile, export and manually inspect the fixed review package, approve only a `PASS` report, then wait for `PUBLISHED`.

Expected per issuer: five stages complete; quality `PASS`; new immutable publication active; old legacy publication still explicitly readable; company `quality_status=VERIFIED`; page data and identity match the fixed golden. If SEC access or evidence is unavailable, record the exact structured blocker and do not approve or alter formal data.

- [ ] **Step 4: Verify the isolated result and formal rollout gate**

Run the full backend, frontend, and browser suites from Step 5 below against code. Query the isolated database for task revision, profile/dataset/report/review/publication IDs, non-PASS checks, old/new publication row counts, and valuation-plan review state. Do not proceed to formal data unless both issuers meet every spec completion condition.

If both pass: stop formal services, create a timestamped database/raw backup with hashes, repeat only the supported API/CLI flow against formal data, and verify hashes/IDs after each issuer. If either fails: preserve formal data unchanged and record the remaining blocker.

- [ ] **Step 5: Run complete fresh verification**

Run:

```bash
.venv/bin/python -m pytest
pnpm --dir apps/web exec tsc --noEmit
pnpm --dir apps/web lint
pnpm --dir apps/web build
PLAYWRIGHT_CHROME_PATH='/Users/vincent/Library/Caches/ms-playwright/chromium_headless_shell-1217/chrome-headless-shell-mac-arm64/chrome-headless-shell' pnpm --dir apps/web e2e
git diff --check
```

Expected: 0 failures; the sole known backend warning may remain the Starlette TestClient/httpx deprecation warning.

- [ ] **Step 6: Update records and commit**

Write exact commands, outcomes, identifiers, backup paths/hashes, blockers, and whether formal data changed. Check the original T10 item only if KO/COST and AAPL/MSFT are all complete; otherwise keep the item open and narrow its blocker text accurately.

```bash
git add docs/reviews/2026-09-11-company-onboarding-progress.md docs/reviews/2026-09-26-legacy-company-rereview-validation.md docs/superpowers/plans/2026-09-11-company-onboarding.md
git commit -m "docs: validate legacy company rereviews"
```

## Final Review

Generate the executing-plans review package from the plan workspace and request one fresh whole-branch review focused on publication races, idempotency, task reuse, legacy read preservation, writer ownership, profile evidence, and false quality approval. Re-grade findings against the spec; fix Critical/Important items once with RED → GREEN tests, record any deferred Minor findings, rerun the complete verification, and only then use `superpowers:finishing-a-development-branch`.
