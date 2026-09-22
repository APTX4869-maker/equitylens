# Company Onboarding Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an arbitrary supported US issuer such as NVDA progress from discovery through fixed SEC evidence, maintainer-reviewed Profile v2, quality review, and publication while remaining visible and recoverable in the UI.

**Architecture:** Extend the existing DuckDB-backed onboarding state machine with immutable fetch bundles, candidate artifacts, and append-only events. Keep all mutations in repository transactions, derive one five-stage progress representation in the backend, and make the existing onboarding center plus a global task indicator consume that representation. Filing documents and Profile v2 evidence remain SHA-bound; no UI action bypasses build, quality, review, or publication gates.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, DuckDB, httpx, lxml, PyYAML, pytest; Next.js 16, React 19, TypeScript, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-19-company-onboarding-closure-design.md`

## Global Constraints

- New onboarding imports require `schema_version: 2`; schema v1 is read-only compatibility only.
- FETCH selects three distinct 10-K report dates and eight distinct 10-Q report dates plus applicable amendments as of the attempt start time.
- Downstream reads use immutable bundle document SHA/locator values, never raw-store latest pointers.
- YAML input is UTF-8, at most 512 KiB, depth 20, 20,000 nodes, and 64 KiB per scalar; tags, aliases, anchors, merge keys, duplicate keys, non-string keys, multiple documents, and non-mapping roots are rejected.
- A running attempt heartbeats at least every 10 seconds and is considered stalled only after 45 seconds without a heartbeat.
- Profile import is one transaction and requires both `expected_revision` and `Idempotency-Key`.
- Candidate generation never approves or publishes a Profile.
- Every completed C-task updates `docs/reviews/2026-09-11-company-onboarding-progress.md` with commit, commands, results, risks, and next step.
- Preserve untracked `.superpowers/` and `data/raw/` files; never add them to a feature commit.
- The market/company-page refresh improvements in spec section 14 remain outside this plan.

---

### C01: Immutable Fetch Bundle Persistence

**Files:**
- Modify: `equitylens/storage/migrations.py`
- Modify: `equitylens/onboarding/models.py`
- Modify: `equitylens/onboarding/repository.py`
- Test: `tests/integration/test_onboarding_migration.py`
- Test: `tests/integration/test_onboarding_runner.py`
- Modify: `docs/reviews/2026-09-11-company-onboarding-progress.md`

**Interfaces:**
- Produces: `FetchBundle`, `FetchDocument`, `OnboardingEvent`, `OnboardingRepository.create_fetch_bundle(...)`, `get_fetch_bundle(...)`, `append_event(...)`.
- Produces task pointers `fetch_bundle_id` and `profile_candidate_id` without mutating historical artifacts.

- [x] **Step 1: Add failing migration and transaction tests**

```python
def test_fetch_bundle_is_immutable_and_bound_atomically(repository):
    task = repository.create_task_for_test("0001045810")
    bundle = repository.create_fetch_bundle(task.onboarding_id, task.revision, documents=DOCUMENTS)
    assert repository.get(task.onboarding_id).fetch_bundle_id == bundle.fetch_bundle_id
    assert repository.get_fetch_bundle(bundle.fetch_bundle_id).content_sha256 == bundle.content_sha256
    with pytest.raises(OnboardingConflict):
        repository.create_fetch_bundle(task.onboarding_id, task.revision, documents=OTHER_DOCUMENTS)
```

- [x] **Step 2: Run the focused tests and confirm RED**

Run: `uv run pytest tests/integration/test_onboarding_migration.py tests/integration/test_onboarding_runner.py -q`

Expected: failures for missing bundle/event tables, models, and task fields.

- [x] **Step 3: Add migration 7 and typed repository operations**

Create additive tables `onboarding_fetch_bundle`, `onboarding_fetch_document`, `issuer_profile_candidate`, `onboarding_event`, and `profile_import_idempotency`; add nullable task pointers. Store canonical JSON and enforce uniqueness for `(onboarding_id, content_sha256)` and `(onboarding_id, input_sha256)`. Implement each compound write through the existing writer transaction.

- [x] **Step 4: Re-run focused tests and migration idempotence**

Run: `uv run pytest tests/integration/test_onboarding_migration.py tests/integration/test_onboarding_runner.py -q`

Expected: PASS, including a second migration run applying no versions and preserving prior task/profile rows.

- [x] **Step 5: Update progress and commit**

```bash
git add equitylens/storage/migrations.py equitylens/onboarding/models.py equitylens/onboarding/repository.py tests/integration/test_onboarding_migration.py tests/integration/test_onboarding_runner.py docs/reviews/2026-09-11-company-onboarding-progress.md
git commit -m "feat: persist immutable onboarding inputs"
```

### C02: Deterministic SEC Filing Bundle

**Files:**
- Modify: `equitylens/ingestion/sec/filing_docs.py`
- Create: `equitylens/onboarding/fetch_bundle.py`
- Modify: `equitylens/onboarding/pipeline.py`
- Test: `tests/unit/test_onboarding_fetch_bundle.py`
- Test: `tests/integration/test_onboarding_pipeline.py`
- Create fixtures under: `tests/fixtures/onboarding/0001045810/`
- Modify: `docs/reviews/2026-09-11-company-onboarding-progress.md`

**Interfaces:**
- Consumes: C01 `create_fetch_bundle` and `FetchDocument`.
- Produces: `select_required_filings(submissions, history, as_of) -> list[SelectedFiling]` and `materialize_fetch_bundle(...) -> FetchBundle`.

- [x] **Step 1: Add failing selection tests** covering recent/history merge, `filingDate <= as_of`, three annual dates, eight quarterly dates, amendments, stable ordering, missing history, missing primary document, and hash mismatch.
- [x] **Step 2: Run RED**

Run: `uv run pytest tests/unit/test_onboarding_fetch_bundle.py tests/integration/test_onboarding_pipeline.py -q`

- [x] **Step 3: Implement deterministic selection and materialization**

```python
def select_required_filings(rows: Iterable[SubmissionRow], *, as_of: datetime) -> list[SelectedFiling]:
    eligible = [row for row in rows if row.filing_date <= as_of.date()]
    annual = _latest_distinct_reports(eligible, base_form="10-K", count=3)
    quarterly = _latest_distinct_reports(eligible, base_form="10-Q", count=8)
    return _with_applicable_amendments(eligible, annual + quarterly)
```

Download by accession/primaryDocument, persist raw relative locators and SHA-256 values, then activate the bundle only after all required documents validate. Make FETCH read its `as_of` from attempt `started_at`.

- [x] **Step 4: Run GREEN and prove latest-pointer independence**

Run: `uv run pytest tests/unit/test_onboarding_fetch_bundle.py tests/integration/test_onboarding_pipeline.py -q`

Expected: changing a mutable raw `submissions.json` after activation does not change bundle reads.

- [x] **Step 5: Update progress and commit** with message `feat: fix onboarding SEC filing inputs`.

### C03: Profile v2 and Filing Evidence

**Files:**
- Modify: `equitylens/issuers/profile.py`
- Modify: `equitylens/normalization/ixbrl.py`
- Modify: `equitylens/normalization/segments.py`
- Modify: `equitylens/onboarding/pipeline.py`
- Create: `config/issuers/schema-v2.json`
- Test: `tests/unit/test_issuer_profile.py`
- Test: `tests/integration/test_onboarding_pipeline.py`
- Test: `tests/golden/test_golden_segments.py`
- Modify: `docs/reviews/2026-09-11-company-onboarding-progress.md`

**Interfaces:**
- Consumes: C02 bundle documents and SHA locators.
- Produces: discriminated `IssuerProfileV1 | IssuerProfileV2`; `validate_profile_v2_against_bundle(profile, bundle)`; iXBRL facts retaining source document, context ID, and locator.

- [x] **Step 1: Add failing model and lineage tests** for all v2 evidence fields, segment parser conditions, EPS conditions, unique evidence IDs, unknown fields, v1 import rejection, and Company Facts not satisfying filing lineage.
- [x] **Step 2: Run RED**

Run: `uv run pytest tests/unit/test_issuer_profile.py tests/integration/test_onboarding_pipeline.py tests/golden/test_golden_segments.py -q`

- [x] **Step 3: Implement v2 strict models and evidence resolution**

```python
IssuerProfile = Annotated[IssuerProfileV1 | IssuerProfileV2, Field(discriminator="schema_version")]

def validate_profile_v2_against_bundle(profile: IssuerProfileV2, bundle: FetchBundle) -> None:
    by_document = {(doc.document_id, doc.content_sha256) for doc in bundle.documents}
    missing = [(e.source_document_id, e.content_sha256) for e in profile.evidence
               if (e.source_document_id, e.content_sha256) not in by_document]
    if missing:
        raise ProfileEvidenceError(missing)
```

Move issuer-specific segment axes/members into v2 and make BUILD parse only bundle iXBRL documents for required formal facts.

- [x] **Step 4: Run GREEN and schema export check**

Run: `uv run pytest tests/unit/test_issuer_profile.py tests/integration/test_onboarding_pipeline.py tests/golden/test_golden_segments.py -q`

- [x] **Step 5: Update progress and commit** with message `feat: require profile v2 filing evidence`.

### C04: Deterministic Candidate Artifact

**Files:**
- Modify: `equitylens/issuers/candidate.py`
- Modify: `equitylens/onboarding/repository.py`
- Modify: `equitylens/onboarding/pipeline.py`
- Test: `tests/unit/test_issuer_profile.py`
- Test: `tests/integration/test_onboarding_pipeline.py`
- Modify: `docs/reviews/2026-09-11-company-onboarding-progress.md`

**Interfaces:**
- Consumes: C01 candidate table, C02 bundle, C03 v2 model shape.
- Produces: `build_candidate_artifact(...) -> CandidateArtifact`; `bind_profile_candidate(...) -> TaskView`.

- [x] **Step 1: Add failing tests** asserting complete v2 skeleton, null/empty unresolved values, sidecar paths/reasons/actions, deterministic YAML/comments/hashes, same-input reuse, and no automatic approval.
- [x] **Step 2: Run RED**

Run: `uv run pytest tests/unit/test_issuer_profile.py tests/integration/test_onboarding_pipeline.py -q`

- [x] **Step 3: Implement candidate generation and atomic pause**

Candidate `input_sha256` hashes bundle SHA, generator version, mapping version/hash, and schema version. Persist immutable candidate first; atomically bind it, enter `NEEDS_ADAPTATION`, increment revision, and append `PROFILE_CANDIDATE_CREATED`. A generation failure leaves the previous current pointer unchanged.

- [x] **Step 4: Run GREEN** using the focused command from Step 2.
- [x] **Step 5: Update progress and commit** with message `feat: generate reviewable profile candidates`.

### C05: Strict YAML Import and Atomic Resume

**Files:**
- Create: `equitylens/issuers/yaml_loader.py`
- Modify: `equitylens/issuers/profile.py`
- Modify: `equitylens/onboarding/repository.py`
- Modify: `equitylens/onboarding/service.py`
- Test: `tests/unit/test_issuer_profile.py`
- Test: `tests/integration/test_issuer_review.py`
- Test: `tests/integration/test_onboarding_runner.py`
- Modify: `docs/reviews/2026-09-11-company-onboarding-progress.md`

**Interfaces:**
- Produces: `load_strict_profile_yaml(text: str) -> IssuerProfileV2`; `import_profile_yaml(task_id, expected_revision, idempotency_key, yaml_text) -> TaskView`.

- [x] **Step 1: Add failing parser tests** for every size/shape restriction and failing repository tests for rollback, evidence mismatch, CIK mismatch, version monotonicity, same-key replay-before-revision, key/hash conflict, and new-key/stale-revision conflict.
- [x] **Step 2: Run RED**

Run: `uv run pytest tests/unit/test_issuer_profile.py tests/integration/test_issuer_review.py tests/integration/test_onboarding_runner.py -q`

- [x] **Step 3: Implement the loader and one import transaction**

Inside the existing writer transaction: replay a prior successful idempotency row first; validate state/revision; validate Profile v2 and current bundle evidence; insert immutable profile; bind it; clear downstream pointers/errors/timer; stale BUILD/VALIDATE/PUBLISH attempts; enter `BUILDING/BUILD`; append `PROFILE_IMPORTED` and `TASK_RESUMED`; store the full success response. Validation failures and rolled-back errors do not consume the key.

- [x] **Step 4: Run GREEN and executor wake test** using the Step 2 command.
- [x] **Step 5: Update progress and commit** with message `feat: resume onboarding from reviewed yaml`.

### C06: Candidate, Import, and Refetch APIs

**Files:**
- Modify: `equitylens/api/company_schemas.py`
- Modify: `equitylens/api/company_routes.py`
- Modify: `equitylens/onboarding/service.py`
- Test: `tests/integration/test_onboarding_api.py`
- Modify: `spec/openapi_stub.yaml`
- Modify: `docs/reviews/2026-09-11-company-onboarding-progress.md`

**Interfaces:**
- Produces the spec section 6 endpoints for candidate create/read/download, current Profile download, YAML import, and refetch.
- Keeps existing JSON `/profile` but routes it through the same v2 validation and atomic import service.

- [x] **Step 1: Add failing API tests** for response fields/headers, relative locators only, GET side-effect freedom, stable error bodies, legal state/actions, refetch pointer rules, and idempotency header behavior.
- [x] **Step 2: Run RED**

Run: `uv run pytest tests/integration/test_onboarding_api.py -q`

- [x] **Step 3: Implement routes and error translation**

Return `{detail: {code, message, remediation, field_errors}}`; never echo YAML, absolute paths, or secrets. Accept refetch only when `actions` contains `REFETCH`, write `REFETCH_REQUESTED`, set `FETCHING/FETCH`, and wake the executor after commit. New bundle activation clears current candidate/profile/downstream pointers and stales old attempts atomically.

- [x] **Step 4: Run GREEN and OpenAPI consistency check**

Run: `uv run pytest tests/integration/test_onboarding_api.py -q`

- [x] **Step 5: Update progress and commit** with message `feat: expose onboarding adaptation APIs`.

### C07: Unified Progress, Heartbeats, and Attention Count

**Files:**
- Create: `equitylens/onboarding/progress.py`
- Modify: `equitylens/onboarding/models.py`
- Modify: `equitylens/onboarding/repository.py`
- Modify: `equitylens/onboarding/runner.py`
- Modify: `equitylens/api/company_schemas.py`
- Modify: `equitylens/api/company_routes.py`
- Test: `tests/unit/test_onboarding_progress.py`
- Test: `tests/integration/test_onboarding_runner.py`
- Test: `tests/integration/test_onboarding_api.py`
- Modify: `docs/reviews/2026-09-11-company-onboarding-progress.md`

**Interfaces:**
- Produces: `derive_progress(task, attempts, events, now, stalled_after=45s) -> OnboardingProgress` and paged `{items, next_cursor, attention_count}`.

- [x] **Step 1: Add table-driven failing tests** for every state, FAILED mapping, cancellation snapshots, actor/activity, timestamps, heartbeat fingerprint changes, exact count beyond page limit, retry/restart, and illegal transitions.
- [x] **Step 2: Run RED**

Run: `uv run pytest tests/unit/test_onboarding_progress.py tests/integration/test_onboarding_runner.py tests/integration/test_onboarding_api.py -q`

- [x] **Step 3: Implement server-derived progress and heartbeat updates**

Use fixed stage IDs `IDENTITY`, `FETCH`, `ADAPTATION`, `BUILD_VALIDATE`, `REVIEW_PUBLISH`. Include task revision, latest heartbeat, and event watermark in the fingerprint. Save full progress JSON in `TASK_CANCELLED`; query attention count with database `COUNT(*)` excluding PUBLISHED/CANCELLED.

- [x] **Step 4: Run GREEN** using the Step 2 command.
- [x] **Step 5: Update progress and commit** with message `feat: report durable onboarding progress`.

### C08: Onboarding Workbench and Five-Stage UI

**Files:**
- Modify: `apps/web/src/lib/types.ts`
- Modify: `apps/web/src/lib/api.ts`
- Create: `apps/web/src/components/companies/OnboardingProgress.tsx`
- Create: `apps/web/src/components/companies/ProfileWorkbench.tsx`
- Modify: `apps/web/src/components/companies/OnboardingDetail.tsx`
- Modify: `apps/web/src/components/companies/OnboardingCenter.tsx`
- Test: `apps/web/e2e/company-onboarding.spec.ts`
- Modify: `docs/reviews/2026-09-11-company-onboarding-progress.md`

**Interfaces:**
- Consumes C06 endpoints and C07 progress verbatim; the frontend does not recreate backend state mapping.
- Produces accessible stage rendering, candidate/evidence inspection, download/upload, field errors, authorized refetch, and automatic polling resumption.

- [x] **Step 1: Add failing Playwright paths** for 40% adaptation pause, colors plus accessible text, candidate evidence expansion, downloads, empty/oversized/invalid upload errors, stale revision, successful upload moving to stage 4 without refresh, and refetch visibility.
- [x] **Step 2: Run RED**

Run: `PLAYWRIGHT_CHROME_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' pnpm --dir apps/web exec playwright test e2e/company-onboarding.spec.ts --project=chromium`

- [x] **Step 3: Implement typed API and workbench components**

Use green only for completed, red for current/incomplete, gray for upcoming, plus icons and screen-reader text. `NEEDS_ADAPTATION` copy is “任务已暂停，等待维护者操作”. Read the selected file in-browser, show name/bytes, reuse one UUID idempotency key for network retries, then immediately replace task state from the success response and restart polling only for true running activities.

- [x] **Step 4: Run GREEN, typecheck, and lint**

Run: `pnpm --dir apps/web exec tsc --noEmit && pnpm --dir apps/web lint`

Run: the Playwright command from Step 2.

- [x] **Step 5: Update progress and commit** with message `feat: add onboarding adaptation workbench`.

### C09: Global Task Indicator and Refresh Recovery

**Files:**
- Create: `apps/web/src/components/companies/OnboardingAttentionButton.tsx`
- Modify: `apps/web/src/app/page.tsx`
- Modify: `apps/web/src/components/companies/OnboardingCenter.tsx`
- Modify: `apps/web/src/lib/api.ts`
- Test: `apps/web/e2e/company-onboarding.spec.ts`
- Test: `apps/web/e2e/research-boundaries.spec.ts`
- Modify: `docs/reviews/2026-09-11-company-onboarding-progress.md`

**Interfaces:**
- Consumes C07 exact `attention_count` and task progress.
- Produces a fixed top-layer red exclamation button, persisted last task selection, focus refresh, and duplicate-add navigation to the existing task.

- [x] **Step 1: Add failing browser tests** for hidden/visible badge, counts above page size, reload restoration, one/many task selection, localStorage fallback, focus refresh, terminal disappearance, and duplicate add.
- [x] **Step 2: Run RED**

Run: `PLAYWRIGHT_CHROME_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' pnpm --dir apps/web exec playwright test e2e/company-onboarding.spec.ts e2e/research-boundaries.spec.ts --project=chromium`

- [x] **Step 3: Implement global indicator and recovery behavior**

Refresh summaries at initial load, focus, onboarding mutation, and progress fingerprint change. Poll rapidly only for `QUEUED`/`RUNNING`; waiting, failed, cancelled, and completed states refresh on focus/mutation rather than implying active work.

- [x] **Step 4: Run GREEN, typecheck, lint, and production build**

Run: `pnpm --dir apps/web exec tsc --noEmit && pnpm --dir apps/web lint && pnpm --dir apps/web build`

Run: the Playwright command from Step 2.

- [x] **Step 5: Update progress and commit** with message `feat: keep onboarding tasks globally visible`.

### C10: NVDA Real Closure and Full Verification

**Files:**
- Create or modify: `config/issuers/NVDA.yaml`
- Add fixed evidence fixtures under: `tests/fixtures/onboarding/0001045810/`
- Modify: `tests/golden/test_onboarding_issuers.py`
- Modify: `apps/web/e2e/company-onboarding.spec.ts`
- Create: `docs/reviews/2026-09-19-company-onboarding-closure-validation.md`
- Modify: `docs/reviews/2026-09-11-company-onboarding-progress.md`

**Interfaces:**
- Consumes all C01—C09 interfaces.
- Produces a published NVDA task and a reproducible validation record, or records an external SEC 403/429 outage without weakening gates.

- [x] **Step 1: Run the real NVDA flow** with a valid `EQUITYLENS_USER_AGENT`: refetch, inspect bundle/candidate, download, maintain/version `NVDA.yaml`, upload, let executor build/validate, review PASS, approve, publish, open the company, and force browser reload.
- [x] **Step 2: Add regression fixtures and golden assertions** from the exact downloaded SEC bytes; assert filing context/locator and segment evidence rather than Company Facts substitutes.
- [x] **Step 3: Run focused closure tests**

Run: `uv run pytest tests/golden/test_onboarding_issuers.py tests/integration/test_onboarding_pipeline.py tests/integration/test_onboarding_api.py -q`

Run: `PLAYWRIGHT_CHROME_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' pnpm --dir apps/web exec playwright test e2e/company-onboarding.spec.ts --project=chromium`

- [x] **Step 4: Run complete verification**

```bash
uv sync --frozen
uv run pytest -q
uv run python -m compileall -q equitylens
pnpm --dir apps/web install --frozen-lockfile
pnpm --dir apps/web exec tsc --noEmit
pnpm --dir apps/web lint
pnpm --dir apps/web build
PLAYWRIGHT_CHROME_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' pnpm --dir apps/web e2e
git diff --check
```

- [x] **Step 5: Inspect in a no-extension browser** and record task timeline, publication IDs, screenshots, commands, exact results, and any external blocker in `docs/reviews/2026-09-19-company-onboarding-closure-validation.md`.
- [x] **Step 6: Update progress and commit** with message `test: verify NVDA onboarding closure`.

## Self-Review Record

- Spec coverage: sections 4.1.1/4.1.2 map to C02/C03; persistence and atomicity to C01/C04/C05; APIs/refetch to C06; state/progress/heartbeat to C07; workbench/global UX to C08/C09; compatibility, security, and real acceptance to C01—C10.
- Placeholder scan: no deferred implementation placeholders are used; the only deferred feature is the explicitly out-of-scope refresh improvement in spec section 14.
- Type consistency: C01 bundle/candidate/event models feed C02—C07; C03 exports Profile v2 validation used by C04—C06; C07 is the sole progress source consumed by C08/C09.
