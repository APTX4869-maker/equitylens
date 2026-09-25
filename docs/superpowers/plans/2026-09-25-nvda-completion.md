# NVDA Research Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make NVDA usable end to end by synchronizing real quotes and governance filings, then providing an explicit in-product review and confirmation flow that unlocks valuation.

**Architecture:** Keep quote and SEC ingestion inside the existing provider/snapshot pipelines, fixing configuration and document identity rather than adding new sources. Add a read-only valuation draft boundary around the existing deterministic defaults, then render that draft in a focused setup component which submits the existing identity-bound confirmation command and refreshes the company capability directory.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, DuckDB, pytest, Next.js 16, React 19, TypeScript, Playwright, YAML configuration.

**Spec:** `docs/superpowers/specs/2026-09-25-nvda-completion-design.md`

## Global Constraints

- Preserve explicit user confirmation; never auto-create a `CONFIRMED` valuation assumption set.
- Use only the existing Nasdaq primary and Tencent fallback quote providers.
- Treat provider `observed_at` as quote time and `fetched_at` as retrieval time; never substitute one for the other.
- Download SEC Form 4 from the filing's `primaryDocument`; never construct a fixed `form4.xml` URL.
- Keep raw SEC and quote snapshots immutable and replayable.
- Bind valuation confirmation to `security_id`, `publication_id`, `model_version`, and the complete assumptions payload.
- Only the five research assumptions are editable: revenue growth path, year-five operating margin, WACC, terminal growth, and terminal ROIC.
- A new publication must not silently reuse a confirmation created for an older publication.
- Do not change FCFF DCF mathematics or add a new market-data provider in this plan.
- Preserve unrelated untracked raw data and user files in the working tree.

---

## File Structure

- `config/market/sources.yaml`: declare NVDA symbols for the existing provider chain.
- `equitylens/market/service.py`: distinguish missing quote configuration from provider failure.
- `tests/unit/test_market_providers.py`: prove NVDA resolves to both configured symbols without a network call.
- `equitylens/ingestion/sec/management.py`: resolve, fetch, snapshot, replay, and report each filing's real primary document.
- `tests/unit/test_management_sync.py`: isolate dynamic Form 4 URL, replay, and partial-failure behavior.
- `config/valuation/wacc_defaults.yaml`: hold versioned NVDA research priors and scenario stories.
- `equitylens/valuation/service.py`: build an identity-bound valuation-review draft without persisting a confirmation.
- `equitylens/api/company_routes.py`: expose the read-only draft endpoint next to the existing confirmation endpoint.
- `tests/integration/test_onboarding_valuation.py`: verify draft identity, confirmation, stale publication rejection, and existing identity gates.
- `apps/web/src/components/sections/ValuationSetupCard.tsx`: own draft loading, five-field editing, preview, acknowledgement, confirmation, and setup errors.
- `apps/web/src/components/sections/ValuationSection.tsx`: delegate `NEEDS_CONFIGURATION` rendering to the setup card while retaining `BLOCKED` behavior and the existing ready workspace.
- `apps/web/src/app/page.tsx`: reload the company directory after confirmation so the valuation capability changes to `READY` without a browser refresh.
- `apps/web/e2e/valuation-setup.spec.ts`: exercise the user-visible setup and stale/error states.
- `docs/reviews/2026-09-11-company-onboarding-progress.md`: record task completion and verification evidence.
- `docs/reviews/2026-09-25-nvda-completion-validation.md`: capture formal-database-copy rehearsal results and remaining limitations.

### Task 1: Configure and verify NVDA market quotes

**Files:**
- Modify: `config/market/sources.yaml`
- Modify: `equitylens/market/service.py`
- Modify: `tests/unit/test_market_providers.py`

**Interfaces:**
- Consumes: `equitylens.market.sources.get_config() -> MarketSourceConfig`.
- Produces: `get_config().symbols["NVDA"] == {"nasdaq": "NVDA", "tencent": "usNVDA"}` for the existing `sync_quotes()` provider loop.
- Produces: a `ProviderError` beginning with `QUOTE_CONFIG_MISSING:` when a ticker has no symbol for any selected provider.

- [ ] **Step 1: Write the failing configuration test**

Append a pure configuration test:

```python
def test_nvda_uses_existing_primary_and_fallback_symbols():
    cfg = get_config()
    assert cfg.active_providers == ["nasdaq", "tencent"]
    assert cfg.symbols["NVDA"] == {"nasdaq": "NVDA", "tencent": "usNVDA"}
```

- [ ] **Step 2: Run the test and confirm the missing mapping**

Run: `.venv/bin/pytest tests/unit/test_market_providers.py::test_nvda_uses_existing_primary_and_fallback_symbols -q`

Expected: FAIL with `KeyError: 'NVDA'`.

- [ ] **Step 3: Add the two existing-provider symbols**

Add this entry under `symbols` without changing provider order:

```yaml
  NVDA: { nasdaq: NVDA, tencent: usNVDA }
```

- [ ] **Step 4: Run provider and market regression tests**

Before the regression run, add a test that temporarily supplies a `MarketSourceConfig` with no symbols, calls `fetch_quote("UNKNOWN")`, and asserts `QUOTE_CONFIG_MISSING` appears in the exception. In `fetch_quote()`, check whether any selected provider has a configured symbol before entering the provider loop:

```python
if not any((cfg.symbols.get(ticker.upper()) or {}).get(name) for name in order):
    raise ProviderError(
        f"QUOTE_CONFIG_MISSING: no market symbol configured for {ticker}"
    )
```

Run: `.venv/bin/pytest tests/unit/test_market_providers.py tests/golden/test_golden_market.py -q`

Expected: all tests PASS; AAPL/MSFT fixture parsing remains unchanged.

- [ ] **Step 5: Commit the independently usable quote configuration**

```bash
git add config/market/sources.yaml equitylens/market/service.py tests/unit/test_market_providers.py
git commit -m "feat: configure NVDA market quotes"
```

### Task 2: Resolve real SEC Form 4 primary documents

**Files:**
- Create: `tests/unit/test_management_sync.py`
- Modify: `equitylens/ingestion/sec/management.py`

**Interfaces:**
- Produces: `_primary_document_name(row: dict) -> str`, returning the basename of the SEC `primaryDocument` after stripping an optional `xslF345X06/` display prefix.
- Produces: `_filing_document_url(cik_int: str, accession_number: str, primary_document: str) -> str`.
- Produces: `ManagementSyncReport.form4_documents`, `form4_skipped`, and warnings containing accession/document identity for failures.
- Preserves previously stored rows for an accession whose current fetch or parse fails.
- Preserves: `sync_management(ticker, fetch=True, store=None, client=None, forms4_limit=12, raw_dir=RAW_DIR)`.

- [ ] **Step 1: Write failing path-resolution tests**

Create focused tests for a real NVDA-shaped row:

```python
from equitylens.ingestion.sec.management import (
    _filing_document_url,
    _primary_document_name,
)


def test_form4_uses_dynamic_primary_document_without_xsl_prefix():
    row = {
        "accessionNumber": "0001243821-26-000007",
        "primaryDocument": "xslF345X06/wk-form4_1789766132.xml",
    }
    name = _primary_document_name(row)
    assert name == "wk-form4_1789766132.xml"
    assert _filing_document_url("1045810", row["accessionNumber"], name) == (
        "https://www.sec.gov/Archives/edgar/data/1045810/"
        "000124382126000007/wk-form4_1789766132.xml"
    )
```

- [ ] **Step 2: Run the path test and confirm the helpers do not exist**

Run: `.venv/bin/pytest tests/unit/test_management_sync.py::test_form4_uses_dynamic_primary_document_without_xsl_prefix -q`

Expected: collection FAIL because the helper functions are not defined.

- [ ] **Step 3: Implement primary-document normalization and URL construction**

Add small pure helpers near `_slug`:

```python
def _primary_document_name(row: dict) -> str:
    value = str(row.get("primaryDocument") or "").strip().replace("\\", "/")
    name = value.rsplit("/", 1)[-1]
    if not name or name in {".", ".."}:
        raise ValueError("SEC_PRIMARY_DOCUMENT_MISSING: SEC primaryDocument is missing")
    return name


def _filing_document_url(cik_int: str, accession_number: str, document_name: str) -> str:
    accession = accession_number.replace("-", "")
    return f"{SEC_ARCHIVES_URL}{cik_int}/{accession}/{document_name}"
```

Use the helpers for Form 4 downloads. Pass the real document name to `_fetch_doc`, `load_snapshot_record`, `SourceDocument.metadata_json`, and `source_url`.

- [ ] **Step 4: Write a failing fetch/replay identity test**

Use a fake SEC client returning a minimal ownership XML and stub `list_filing_docs()` with `primaryDocument="wk-form4_1789766132.xml"`. Assert the requested URL, snapshot filename, source-document metadata, and one parsed transaction all carry that identity. Run once with `fetch=True`, then again with `fetch=False` against the same temporary raw directory.

Run: `.venv/bin/pytest tests/unit/test_management_sync.py -q`

Expected: the new identity/replay test FAIL until the loop no longer references `form4.xml`.

- [ ] **Step 5: Implement per-document failure isolation**

Wrap each Form 4 fetch/parse in its own `try/except`. On success increment `form4_documents`; on failure increment `form4_skipped`. Preserve `SEC_PRIMARY_DOCUMENT_MISSING` from the helper; otherwise append a warning in this exact shape:

```python
f"SEC_FORM4_PARSE_FAILED: Form 4 {accn} ({doc_name}) skipped: {exc}"
```

Do not call `replace_insider_transactions()` until all filings have been attempted. Before the loop, read existing insider rows keyed by `accession_number`. For each successfully parsed accession, replace that accession's old rows with newly parsed rows; for each failed accession, carry its old rows forward unchanged. Then call `replace_insider_transactions()` once with the combined deterministic list. A failed filing must not discard either successful filings from the current run or the last good rows for that accession.

- [ ] **Step 6: Add and pass the partial-failure test**

Seed an old transaction for the first accession, then stub two Form 4 rows: the first client call raises `RuntimeError("invalid XML")`; the second returns valid ownership XML. Assert the old transaction and the newly parsed transaction are both persisted, `form4_documents == 1`, `form4_skipped == 1`, and the warning contains the failed accession.

Run: `.venv/bin/pytest tests/unit/test_management_sync.py tests/unit/test_replay_paths.py tests/golden/test_golden_management.py -q`

Expected: all tests PASS.

- [ ] **Step 7: Commit the ingestion fix**

```bash
git add equitylens/ingestion/sec/management.py tests/unit/test_management_sync.py
git commit -m "fix: ingest SEC Form 4 primary documents"
```

### Task 3: Add versioned NVDA valuation research priors

**Files:**
- Modify: `config/valuation/wacc_defaults.yaml`
- Modify: `tests/golden/test_golden_valuation.py`

**Interfaces:**
- Consumes: `default_assumption_set(store, company_id, "NVDA", risk_free=...)`.
- Produces: a complete `DcfInputs` and metadata for NVDA using the current FCFF model.

- [ ] **Step 1: Write a failing NVDA configuration-shape test**

Add a test that reads `load_valuation_config()` and verifies the NVDA block is explicit and complete:

```python
def test_nvda_has_versioned_research_defaults():
    from equitylens.valuation.defaults import load_valuation_config

    issuer = load_valuation_config()["issuers"]["NVDA"]
    assert issuer["growth_path_version"] == "nvda-growth.v1"
    assert len(issuer["growth_path"]) == 5
    assert set(issuer["scenarios"]) == {"version", "bear", "base", "bull"}
    assert issuer["beta_source"].startswith("assumption")
    assert issuer["growth_path_source"].startswith("assumption")
```

- [ ] **Step 2: Run the test and confirm NVDA is absent**

Run: `.venv/bin/pytest tests/golden/test_golden_valuation.py::test_nvda_has_versioned_research_defaults -q`

Expected: FAIL with `KeyError: 'NVDA'`.

- [ ] **Step 3: Add reviewed NVDA priors and scenarios**

Increment the configuration version to `6` and add this research-prior block. These values are deliberately labeled assumptions; they are not claims about current market consensus:

```yaml
  NVDA:
    beta: 2.10
    beta_source: "assumption v1 (high-volatility semiconductor equity research prior; not a live market observation)"
    pre_tax_debt_cost: 0.040
    debt_cost_source: "assumption v1 (USD investment-grade issuer research prior; not a live bond quote)"
    growth_path: [0.30, 0.24, 0.18, 0.14, 0.10]
    growth_path_source: "assumption v1 (AI accelerator expansion with explicit five-year fade; not historical CAGR extrapolation)"
    growth_path_version: "nvda-growth.v1"
    growth_path_reason: "AI 加速计算仍处于扩张阶段，但五年增长路径逐年回落；这是待用户审核的研究先验。"
    scenarios:
      version: "nvda-scenarios.v1"
      bear:
        label: "悲观"
        story: "AI 基础设施消化库存、竞争与出口限制压低增长和利润率，同时资本成本上升。"
        revenue_growth: [0.12, 0.10, 0.08, 0.07, 0.06]
        op_margin_delta: -0.06
        wacc_delta: 0.015
        terminal_growth_delta: -0.005
      base:
        label: "中性"
        story: "沿用 NVDA 已版本化的 AI 加速计算增长衰减路径，不额外改变经营或资本假设。"
      bull:
        label: "乐观"
        story: "AI 基础设施投资和平台扩张持续强于基准，利润率韧性更高且风险溢价略降。"
        revenue_growth: [0.40, 0.32, 0.24, 0.18, 0.12]
        op_margin_delta: 0.02
        wacc_delta: -0.005
        terminal_growth_delta: 0.005
```

- [ ] **Step 4: Verify the config and existing issuer regressions**

Run: `.venv/bin/pytest tests/golden/test_golden_valuation.py -q`

Expected: all tests PASS; AAPL and MSFT defaults remain byte-for-byte equivalent at the `DcfInputs` level.

- [ ] **Step 5: Commit the research configuration**

```bash
git add config/valuation/wacc_defaults.yaml tests/golden/test_golden_valuation.py
git commit -m "feat: add NVDA valuation research defaults"
```

### Task 4: Expose an identity-bound valuation draft API

**Files:**
- Modify: `equitylens/valuation/service.py`
- Modify: `equitylens/api/company_routes.py`
- Modify: `tests/integration/test_onboarding_valuation.py`

**Interfaces:**
- Produces: `valuation_profile_draft(store, *, company_id: str, ticker: str, security_id: str, publication_id: str) -> dict`.
- Produces: `GET /api/v1/companies/{ticker}/valuation-profile/draft?security_id=...&publication_id=...`.
- Response fields: `company_id`, `ticker`, `security_id`, `publication_id`, `model_version`, `status`, `assumptions`, `preview`, and `acknowledgement_required`.
- Consumes: existing `PUT /api/v1/companies/{ticker}/valuation-profile` without weakening its validation.

- [ ] **Step 1: Write the failing draft API test**

Extend the integration fixture with FY2025 `REVENUE`, `OPERATING_INCOME`, `PRETAX_INCOME`, `INCOME_TAX_EXPENSE`, `CAPITAL_EXPENDITURES`, `DEPRECIATION_AMORTIZATION`, and `DILUTED_WEIGHTED_AVG_SHARES`, plus an instant `NET_DEBT` fact. Give the fixture ticker an issuer block by using `AAPL` for this draft-specific test while retaining the synthetic security and publication identities. Call the new endpoint and assert:

```python
assert response.status_code == 200
body = response.json()
assert body["security_id"] == "security-newco"
assert body["publication_id"] == publication.publication_id
assert body["model_version"] == MODEL_VERSION
assert body["status"] == "NEEDS_CONFIGURATION"
assert body["acknowledgement_required"] is True
assert body["assumptions"]["inputs"]["shares"] > 0
assert body["preview"]["scenarios"]["base"]["status"] == "OK"
```

- [ ] **Step 2: Run the endpoint test and confirm the route is missing**

Run: `.venv/bin/pytest tests/integration/test_onboarding_valuation.py::test_unconfirmed_company_can_load_identity_bound_draft -q`

Expected: FAIL with HTTP 404.

- [ ] **Step 3: Implement the read-only draft service**

Build the draft from `default_valuation()`, add the supplied identity fields, and check for an exact existing confirmation without requiring one. Do not write `valuation_assumption_set` or `valuation_run`. Return the executable inputs plus metadata and preview output already produced by the deterministic engine. Name the response's preview keys explicitly as `result`, `scenarios`, `sensitivity`, `model_quality`, and `market`.

Catch missing issuer defaults or missing critical financial facts and raise:

```python
ValuationError(
    "VALUATION_DEFAULT_UNAVAILABLE",
    str(exc),
    None,
)
```

- [ ] **Step 4: Add the GET route with versioned identity resolution**

Resolve the company using the same registry/publication context used by `/valuation/default`. Return a 409 error body with `code`, `field`, and `message` for valuation blockers. Keep the route declaration before `/{ticker}/valuation-profile` cannot matter in FastAPI because the suffix differs, but add a route test to protect it.

- [ ] **Step 5: Write stale-publication and no-write tests**

After loading a draft, publish a newer dataset and submit the old draft to the confirmation endpoint. Assert the request is rejected with `VALUATION_DRAFT_STALE` and no confirmed row is inserted. Also assert merely loading the draft leaves `valuation_assumption_set` and `valuation_run` counts unchanged.

- [ ] **Step 6: Reject confirmation against a non-active publication**

In `confirm_valuation_profile()`, read `company.active_publication_id` immediately before validation. When it differs from the submitted `publication_id`, raise:

```python
ValuationError(
    "VALUATION_DRAFT_STALE",
    "the active publication changed; reload and review the valuation draft",
    "publication_id",
)
```

Keep `require_valuation_confirmation()` able to read historical confirmation records for historical views; only creation of a new confirmation is restricted to the active publication.

- [ ] **Step 7: Run all valuation API tests**

Run: `.venv/bin/pytest tests/integration/test_onboarding_valuation.py tests/golden/test_golden_valuation.py -q`

Expected: all tests PASS, including currency, ADR, multi-security, and publication-binding gates.

- [ ] **Step 8: Commit the draft boundary**

```bash
git add equitylens/valuation/service.py equitylens/api/company_routes.py tests/integration/test_onboarding_valuation.py
git commit -m "feat: expose valuation review drafts"
```

### Task 5: Build the valuation setup card

**Files:**
- Create: `apps/web/src/components/sections/ValuationSetupCard.tsx`
- Create: `apps/web/e2e/valuation-setup.spec.ts`
- Modify: `apps/web/src/components/sections/ValuationSection.tsx`

**Interfaces:**
- Produces React props:

```ts
type ValuationSetupCardProps = {
  ticker: string;
  gate: { status: string; reason: string | null };
  onConfirmed: () => Promise<void> | void;
};
```

- Consumes `GET /api/v1/companies/{ticker}/valuation-profile/draft` and existing `PUT /api/v1/companies/{ticker}/valuation-profile`.
- Produces `data-testid` values `valuation-setup`, `valuation-setup-error`, and `valuation-confirm`.

- [ ] **Step 1: Write the failing setup-flow browser test**

Stub the directory with NVDA valuation status `NEEDS_CONFIGURATION`, stub the draft endpoint with complete inputs/meta/preview, and capture the PUT body. The test must assert that the card shows the publication/model identity, the confirm button is disabled before acknowledgement, changing WACC updates the submitted complete assumptions, and clicking confirm calls `onConfirmed` behavior that unlocks the ready valuation workspace.

Run: `cd apps/web && npm run test:e2e -- valuation-setup.spec.ts`

Expected: FAIL because the setup component and draft request do not exist.

- [ ] **Step 2: Create focused setup types and initial loading/error UI**

Define `DcfInputs`, assumption metadata, draft response, and the five editable field transformations inside the new component or import the existing `DcfInputs` helpers after exporting them from `valuationDraft.ts`. Use `api.fetchJson` and show a retry button on `VALUATION_DEFAULT_UNAVAILABLE`; do not render the confirmation checkbox when `gate.status === "BLOCKED"`.

- [ ] **Step 3: Implement the five editable assumptions and preview**

Reuse `updateDraft()` and `buildPreviewRequest()` so setup and ready mode send the same complete input structure. Show five controls, source/reason text, and Bear/Base/Bull fair values. Preview requests use `persist: false`; debounce slider-driven requests or use request sequence guards so older responses cannot overwrite newer edits.

- [ ] **Step 4: Implement acknowledgement and confirmation**

Submit exactly:

```ts
{
  security_id: draft.security_id,
  publication_id: draft.publication_id,
  model_version: draft.model_version,
  assumptions: editedInputs,
  confirmed: true,
}
```

Disable the button while submitting. On 409 stale identity, keep edits visible and show “财务发布版本已变化，请重新加载审核方案”; on other errors use `userErrorMessage()` and allow retry. Call `onConfirmed()` only after a 200 response.

- [ ] **Step 5: Delegate only `NEEDS_CONFIGURATION` to the setup card**

In `ValuationSection`, keep `BLOCKED` as a non-actionable gate with its repair reason. Replace the one-line `NEEDS_CONFIGURATION` card with `ValuationSetupCard`. Do not alter the ready valuation workbench.

- [ ] **Step 6: Pass component and regression tests**

Run:

```bash
cd apps/web
npm run lint
npx tsc --noEmit
npm run test:e2e -- valuation-setup.spec.ts valuation-state.spec.ts beginner-valuation.spec.ts
```

Expected: lint and typecheck succeed; all selected Playwright tests PASS.

- [ ] **Step 7: Commit the setup UI**

```bash
git add apps/web/src/components/sections/ValuationSetupCard.tsx apps/web/src/components/sections/ValuationSection.tsx apps/web/e2e/valuation-setup.spec.ts
git commit -m "feat: add valuation assumption review"
```

### Task 6: Unlock valuation without a manual browser refresh

**Files:**
- Modify: `apps/web/src/app/page.tsx`
- Modify: `apps/web/e2e/valuation-setup.spec.ts`

**Interfaces:**
- Consumes: `ValuationSetupCardProps.onConfirmed` through `ValuationSection`.
- Produces: `handleValuationConfirmed(): Promise<void>`, which awaits `loadCompanies()` and advances `reloadKey` for current company data.

- [ ] **Step 1: Strengthen the browser test around automatic capability reload**

Make the stubbed company directory return `NEEDS_CONFIGURATION` on its first request and `READY` after the confirmation PUT. Assert the page shows the ready valuation content without `page.reload()` and that the setup card disappears.

- [ ] **Step 2: Run the test and confirm the gate remains stale**

Run: `cd apps/web && npm run test:e2e -- valuation-setup.spec.ts`

Expected: FAIL because `companies` still contains the old capability.

- [ ] **Step 3: Wire the confirmation callback to directory reload**

Add a memoized handler:

```ts
const handleValuationConfirmed = useCallback(async () => {
  await loadCompanies();
  setReloadKey((value) => value + 1);
}, [loadCompanies]);
```

Pass it through `ValuationSection` to `ValuationSetupCard`. Keep the selected ticker stable while the directory response is replaced.

- [ ] **Step 4: Verify automatic unlock and refresh regressions**

Run:

```bash
cd apps/web
npx tsc --noEmit
npm run test:e2e -- valuation-setup.spec.ts refresh-state.spec.ts valuation-state.spec.ts
```

Expected: all tests PASS; no browser reload is used by the test.

- [ ] **Step 5: Commit the capability refresh**

```bash
git add apps/web/src/app/page.tsx apps/web/src/components/sections/ValuationSection.tsx apps/web/src/components/sections/ValuationSetupCard.tsx apps/web/e2e/valuation-setup.spec.ts
git commit -m "fix: unlock valuation after confirmation"
```

### Task 7: Rehearse NVDA on a formal database copy and close documentation

**Files:**
- Modify: `docs/reviews/2026-09-11-company-onboarding-progress.md`
- Create: `docs/reviews/2026-09-25-nvda-completion-validation.md`

**Interfaces:**
- Consumes the completed quote, management, draft, and confirmation flows.
- Produces reproducible validation evidence without modifying the formal database until the rehearsal passes.

- [ ] **Step 1: Run the complete automated backend suite**

Run: `.venv/bin/pytest tests/unit tests/integration tests/golden -q`

Expected: all tests PASS with no new skips attributable to NVDA work.

- [ ] **Step 2: Run the complete frontend quality gates**

Run:

```bash
cd apps/web
npm run lint
npx tsc --noEmit
npm run build
npm run test:e2e
```

Expected: every command exits 0.

- [ ] **Step 3: Create explicit temporary rehearsal paths**

Use `mktemp -d` and copy only these targets:

```bash
rehearsal_dir="$(mktemp -d /tmp/equitylens-nvda-rehearsal.XXXXXX)"
cp /Users/vincent/workspace/equitylens/data/equitylens.duckdb "$rehearsal_dir/equitylens.duckdb"
cp -R /Users/vincent/workspace/equitylens/data/raw "$rehearsal_dir/raw"
```

Never point a destructive or replacing command at the formal database or raw directory.

- [ ] **Step 4: Run NVDA quote and management refresh against the copy**

Set the SEC user agent only in the rehearsal process environment. Invoke the existing Python services with `DuckDBStore(Path(...))` and `raw_dir=Path(...) / "raw"`; do not rely on default paths. Assert:

```python
assert quote_row["ticker"] == "NVDA"
assert quote_row["observed_at"]
assert management_report.executives > 0
assert management_report.board_members > 0
assert management_report.form4_documents > 0
assert management_report.insider_transactions > 0
```

- [ ] **Step 5: Exercise draft and confirmation against the copy**

Use FastAPI's test client with the copied store injected. Verify the draft is `NEEDS_CONFIGURATION`, submit its exact identity and assumptions, then verify `/valuation/default` returns 200 and the company directory reports valuation `READY`. Create a newer publication in the copy and verify the old confirmation no longer unlocks it.

- [ ] **Step 6: Perform browser visual QA at desktop and mobile widths**

Start API and web services against the rehearsal paths. Inspect NVDA setup at 1440×900 and 390×844. Verify no horizontal overflow, all five controls have labels, the acknowledgement/confirm order is clear, errors remain readable, and confirmation transitions to the ready valuation page without manual refresh.

- [ ] **Step 7: Record evidence and update the progress table**

In the validation document record command results, row counts, quote provider/observation time, filing accessions, confirmation identity, screenshots if captured, and any external-source limitation. Mark the NVDA priority complete in the progress document only if all acceptance assertions pass; otherwise record the exact blocker and leave it open.

- [ ] **Step 8: Run documentation checks and commit**

Run:

```bash
rg -n "T[B]D|T[O]DO|PLACEHOLDER" docs/reviews/2026-09-25-nvda-completion-validation.md docs/reviews/2026-09-11-company-onboarding-progress.md
git diff --check
```

Expected: the placeholder search returns no matches and `git diff --check` exits 0.

```bash
git add docs/reviews/2026-09-25-nvda-completion-validation.md docs/reviews/2026-09-11-company-onboarding-progress.md
git commit -m "docs: validate NVDA research completion"
```

### Task 8: Final review and delivery gate

**Files:**
- Review all files changed by Tasks 1–7.

**Interfaces:**
- Produces a branch that can be merged without database files, raw snapshots, secrets, or unrelated user artifacts.

- [ ] **Step 1: Inspect the complete branch diff**

Run:

```bash
git status --short
git diff --check main...HEAD
git diff --stat main...HEAD
git log --oneline main..HEAD
```

Expected: only planned source, test, configuration, and documentation files are tracked.

- [ ] **Step 2: Verify secrets and generated data are absent**

Run:

```bash
git diff --name-only main...HEAD | rg '(^|/)(\.env|.*\.duckdb|data/raw/|node_modules/|\.next/)' && exit 1 || true
git diff main...HEAD | rg '19949203yxw@gmail\.com|EQUITYLENS_USER_AGENT=' && exit 1 || true
```

Expected: both scans complete without finding tracked secrets or generated data.

- [ ] **Step 3: Run the final targeted smoke suite from repository root**

Run:

```bash
.venv/bin/pytest tests/unit/test_market_providers.py tests/unit/test_management_sync.py tests/integration/test_onboarding_valuation.py -q
cd apps/web && npm run test:e2e -- valuation-setup.spec.ts refresh-state.spec.ts
```

Expected: all tests PASS.

- [ ] **Step 4: Request code review and address only verified findings**

Use the requesting-code-review workflow with the spec, plan, branch diff, and validation evidence. Reproduce every reported defect before changing code, rerun the narrow failing test, then rerun the final smoke suite.

- [ ] **Step 5: Prepare integration handoff**

Report the branch name, commit list, validation commands, formal-data rehearsal result, and whether the earlier refresh-experience PR is a prerequisite or has been incorporated. Do not claim the formal database was updated unless that exact write was performed and separately verified.
