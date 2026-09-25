from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

import yaml
from fastapi.testclient import TestClient

from equitylens.api import company_routes
from equitylens.api.main import app
from equitylens.companies.discovery import CompanyDiscovery, DiscoveryError
from equitylens.companies.models import CompanyIdentity, SecurityIdentity
from equitylens.companies.registry import CompanyRegistry
from equitylens.onboarding.pipeline import OnboardingPipeline
from equitylens.onboarding.repository import OnboardingRepository
from equitylens.onboarding.runner import OnboardingRunner
from equitylens.issuers.candidate import build_candidate_artifact
from equitylens.issuers.profile import IssuerProfileV2
from equitylens.normalization.taxonomy.mappings import MappingRegistry
from equitylens.publication.builder import DatasetBuilder
from equitylens.publication.repository import PublicationRepository


class StableDiscoverySource:
    def __init__(self):
        self.registry_rows = [
            {"cik_str": 1, "ticker": "EXAMPLE", "title": "Example Inc."}
        ]
        self.submissions = {
            "entityType": "operating",
            "sic": "3571",
            "name": "Example Inc.",
            "tickers": ["EXAMPLE"],
            "exchanges": ["NYSE"],
            "filings": {
                "recent": {
                    "accessionNumber": ["a", "b"],
                    "form": ["10-K", "10-Q"],
                    "filingDate": ["2026-02-01", "2026-05-01"],
                    "reportDate": ["2025-12-31", "2026-03-31"],
                    "primaryDocument": ["annual.htm", "quarter.htm"],
                },
                "files": [],
            },
        }

    def registry(self):
        return deepcopy(self.registry_rows), {
            "source": "SEC registry",
            "fetched_at": "2026-09-11T00:00:00+00:00",
            "content_sha256": "a" * 64,
        }

    def issuer_submissions(self, cik):
        return deepcopy(self.submissions), {
            "source": f"SEC submissions {cik}",
            "fetched_at": "2026-09-11T00:00:00+00:00",
            "content_sha256": "b" * 64,
        }

    def historical_submissions(self, name):
        raise AssertionError("no history expected")


def _client(db, monkeypatch):
    monkeypatch.setattr("equitylens.api.routes.DuckDBStore", lambda: db)
    source = StableDiscoverySource()
    discovery = CompanyDiscovery(
        db,
        source=source,
        clock=lambda: datetime(2026, 9, 11, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(company_routes, "CompanyDiscovery", lambda store: discovery)
    return TestClient(app), discovery


def _create(client, discovery, *, key="request-1"):
    found = discovery.discover("EXAMPLE")
    response = client.post(
        "/api/v1/company-onboardings",
        headers={"Idempotency-Key": key},
        json={
            "discovery_id": found.discovery_id,
            "identity_hash": found.identity_hash,
            "candidate_id": found.candidates[0].candidate_id,
        },
    )
    return response, found


def test_repeated_request_returns_same_task(db, monkeypatch):
    client, discovery = _client(db, monkeypatch)
    first, found = _create(client, discovery)
    second = client.post(
        "/api/v1/company-onboardings",
        headers={"Idempotency-Key": "request-1"},
        json={
            "discovery_id": found.discovery_id,
            "identity_hash": found.identity_hash,
            "candidate_id": found.candidates[0].candidate_id,
        },
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["onboarding_id"] == second.json()["onboarding_id"]
    assert second.json()["existing"] is True


def test_attention_count_is_exact_beyond_current_page_and_progress_is_shared(db, monkeypatch):
    client, _ = _client(db, monkeypatch)
    for index in range(3):
        db._conn.execute(
            """
            INSERT INTO company_onboarding (
              onboarding_id, company_id, state, current_step, revision,
              cancel_requested, input_fingerprint, created_at, updated_at
            ) VALUES (?, '0000320193', 'NEEDS_ADAPTATION', 'BUILD', 1, false, ?, now(), now())
            """,
            [f"attention-{index}", f"attention-{index}"],
        )

    page = client.get(
        "/api/v1/company-onboardings?attention_only=true&limit=1"
    )
    detail = client.get(
        f"/api/v1/company-onboardings/{page.json()['items'][0]['onboarding_id']}"
    )

    assert page.status_code == 200
    assert page.json()["attention_count"] == 3
    assert len(page.json()["items"]) == 1
    assert page.json()["next_cursor"]
    assert page.json()["items"][0]["progress"] == detail.json()["progress"]
    assert detail.json()["progress"]["percent"] == 40


def test_legacy_adaptation_without_fetch_bundle_can_refetch(db, monkeypatch):
    client, _ = _client(db, monkeypatch)
    db._conn.execute(
        """
        INSERT INTO company_onboarding (
          onboarding_id, company_id, state, current_step, revision,
          cancel_requested, input_fingerprint, error_json, created_at, updated_at
        ) VALUES ('legacy-no-bundle', '0000320193', 'NEEDS_ADAPTATION', 'BUILD',
          3, false, 'legacy', ?, now(), now())
        """,
        [json.dumps({"code": "ADAPTATION_REQUIRED", "message": "profile missing"})],
    )

    detail = client.get("/api/v1/company-onboardings/legacy-no-bundle")
    assert detail.status_code == 200
    assert "REFETCH" in detail.json()["actions"]
    assert "PROFILE_IMPORT" not in detail.json()["actions"]

    response = client.post(
        "/api/v1/company-onboardings/legacy-no-bundle/refetch",
        json={"expected_revision": 3},
    )
    assert response.status_code == 200
    assert response.json()["state"] == "FETCHING"
    assert response.json()["revision"] == 4


def test_same_idempotency_key_with_other_input_conflicts(db, monkeypatch):
    client, discovery = _client(db, monkeypatch)
    first, _ = _create(client, discovery)
    assert first.status_code == 202

    conflict = client.post(
        "/api/v1/company-onboardings",
        headers={"Idempotency-Key": "request-1"},
        json={"discovery_id": "other", "identity_hash": "x", "candidate_id": "y"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_discovery_upstream_failure_returns_service_unavailable(db, monkeypatch):
    monkeypatch.setattr("equitylens.api.routes.DuckDBStore", lambda: db)

    class UnavailableDiscovery:
        def __init__(self, store):
            pass

        def discover(self, ticker):
            raise DiscoveryError("SEC_UNAVAILABLE", "SEC access denied", retryable=True)

    monkeypatch.setattr(company_routes, "CompanyDiscovery", UnavailableDiscovery)

    response = TestClient(app).post(
        "/api/v1/companies/discover", json={"ticker": "KO"}
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "SEC_UNAVAILABLE",
        "message": "SEC access denied",
        "remediation": "NONE",
        "field_errors": [],
    }


def test_expired_discovery_cannot_create_task(db, monkeypatch):
    client, discovery = _client(db, monkeypatch)
    found = discovery.discover("EXAMPLE")
    db._conn.execute(
        "UPDATE company_discovery SET expires_at=TIMESTAMP '2026-09-10 00:00:00' WHERE discovery_id=?",
        [found.discovery_id],
    )

    response = client.post(
        "/api/v1/company-onboardings",
        headers={"Idempotency-Key": "expired-request"},
        json={
            "discovery_id": found.discovery_id,
            "identity_hash": found.identity_hash,
            "candidate_id": found.candidates[0].candidate_id,
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "DISCOVERY_EXPIRED"


def test_company_and_task_lists_are_paginated_and_cancellation_is_terminal(db, monkeypatch):
    client, discovery = _client(db, monkeypatch)
    created, _ = _create(client, discovery)
    task_id = created.json()["onboarding_id"]

    companies = client.get("/api/v1/companies", params={"limit": 1})
    assert companies.status_code == 200
    assert len(companies.json()["items"]) == 1
    assert companies.json()["next_cursor"]
    assert companies.json()["items"][0]["security_id"]
    assert "publication_id" in companies.json()["items"][0]

    tasks = client.get("/api/v1/company-onboardings", params={"limit": 1})
    assert tasks.status_code == 200
    assert tasks.json()["items"][0]["onboarding_id"] == task_id

    detail = client.get(f"/api/v1/company-onboardings/{task_id}").json()
    cancelled = client.post(
        f"/api/v1/company-onboardings/{task_id}/cancel",
        json={"expected_revision": detail["revision"]},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "CANCELLED"
    again = client.post(
        f"/api/v1/company-onboardings/{task_id}/cancel",
        json={"expected_revision": cancelled.json()["revision"]},
    )
    assert again.status_code == 409


def test_unpublished_onboarding_candidate_is_not_listed_as_research_company(db, monkeypatch):
    client, discovery = _client(db, monkeypatch)
    created, _ = _create(client, discovery)
    assert created.status_code == 202
    assert created.json()["publication_id"] is None

    response = client.get("/api/v1/companies", params={"limit": 200})

    assert response.status_code == 200
    assert all(item["publication_id"] is not None for item in response.json()["items"])
    assert "EXAMPLE" not in {item["ticker"] for item in response.json()["items"]}


def test_published_security_cannot_start_a_second_onboarding(db, monkeypatch):
    client, discovery = _client(db, monkeypatch)
    first, _ = _create(client, discovery, key="first-onboarding")
    task = first.json()
    cancelled = client.post(
        f"/api/v1/company-onboardings/{task['onboarding_id']}/cancel",
        json={"expected_revision": task["revision"]},
    )
    assert cancelled.status_code == 200
    _publish_revenue(db, company_id=task["company_id"], version=101, value=100)

    found = discovery.discover("EXAMPLE")
    duplicate = client.post(
        "/api/v1/company-onboardings",
        headers={"Idempotency-Key": "published-duplicate"},
        json={
            "discovery_id": found.discovery_id,
            "identity_hash": found.identity_hash,
            "candidate_id": found.candidates[0].candidate_id,
        },
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "ALREADY_PUBLISHED"
    task_count = db.query_one(
        "SELECT count(*) AS count FROM company_onboarding WHERE company_id=?",
        [task["company_id"]],
    )
    assert task_count["count"] == 1


def test_company_directory_pagination_does_not_skip_a_second_active_alias(db, monkeypatch):
    client, _ = _client(db, monkeypatch)
    apple_security = db.query_one(
        "SELECT security_id FROM security_ticker_alias WHERE ticker='AAPL'"
    )
    CompanyRegistry(db).add_ticker_alias(
        apple_security["security_id"], ticker="AAPLX", exchange="NASDAQ"
    )

    tickers: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"limit": 1}
        if cursor is not None:
            params["cursor"] = cursor
        response = client.get("/api/v1/companies", params=params)
        assert response.status_code == 200
        tickers.extend(item["ticker"] for item in response.json()["items"])
        cursor = response.json()["next_cursor"]
        if cursor is None:
            break

    assert {"AAPL", "AAPLX"}.issubset(tickers)


def test_ambiguous_ticker_requires_security_id(db, monkeypatch):
    client, _ = _client(db, monkeypatch)
    registry = CompanyRegistry(db)
    registry.register_company(
        CompanyIdentity(
            company_id="0000000002",
            cik="0000000002",
            legal_name="Dual Listed Inc.",
        ),
        legacy_ticker="DUAL",
    )
    for suffix, exchange in (("one", "NYSE"), ("two", "NASDAQ")):
        registry.register_security(
            SecurityIdentity(
                security_id=f"dual-{suffix}",
                company_id="0000000002",
                ticker="DUAL",
                exchange=exchange,
                currency="USD",
                instrument_type="COMMON_STOCK",
            )
        )

    ambiguous = client.get("/api/v1/companies/DUAL")
    assert ambiguous.status_code == 409
    assert ambiguous.json()["detail"]["code"] == "AMBIGUOUS_SECURITY"
    selected = client.get(
        "/api/v1/companies/DUAL", params={"security_id": "dual-one"}
    )
    assert selected.status_code == 200
    assert selected.json()["security_id"] == "dual-one"


def _publish_revenue(db, *, company_id: str, version: int, value: float):
    publications = PublicationRepository(db)
    profile_id = publications.create_profile(
        company_id,
        version=version,
        schema_version=1,
        content={"company_id": company_id, "version": version},
    )
    dataset_id = DatasetBuilder(db).seal_rows(
        company_id=company_id,
        profile_id=profile_id,
        source_manifest={"documents": []},
        rows=[
            (
                "canonical_fact",
                f"revenue-{version}",
                {
                    "canonical_fact_id": f"revenue-{version}",
                    "company_id": company_id,
                    "canonical_metric": "REVENUE",
                    "period_type": "FY",
                    "fiscal_year": 2025,
                    "value": value,
                    "unit": "USD",
                    "status": "REPORTED",
                    "mapping_rule_id": "fixture",
                    "mapping_version": "v1",
                    "source_raw_fact_ids": [],
                },
            )
        ],
    )
    return publications.publish_dataset(
        company_id=company_id,
        dataset_id=dataset_id,
        profile_id=profile_id,
        quality_report_id=None,
        review_id=None,
    )


def _strict_profile(company_id: str, version: int, document_id: str, digest: str):
    evidence = ["filing-evidence"]
    return {
        "schema_version": 2,
        "company_id": company_id,
        "version": version,
        "template": "us_gaap_operating_v1",
        "template_evidence": evidence,
        "fiscal_calendar": {"year_end": "12-31", "week_based": False, "evidence": evidence},
        "metrics": {
            "REVENUE": {
                "concepts": ["us-gaap:Revenues"],
                "unit": "USD",
                "context": "consolidated",
                "period": "duration",
                "selection": "latest_filed_same_basis",
                "evidence": evidence,
            }
        },
        "segments": {"parser": "not_applicable", "axes": [], "reconciliation": "not_applicable", "revenue_concept": None, "profit_concept": None, "evidence": evidence},
        "cash_debt": {
            "cash_components": ["us-gaap:CashAndCashEquivalentsAtCarryingValue"],
            "debt_components": ["us-gaap:LongTermDebtNoncurrent"],
            "restricted_cash_policy": "separate",
            "evidence": evidence,
        },
        "eps_method": "reported_diluted",
        "eps_method_evidence": evidence,
        "securities": [
            {
                "ticker": "EXAMPLE",
                "exchange": "NYSE",
                "currency": "USD",
                "instrument_type": "COMMON_STOCK",
                "evidence": evidence,
            }
        ],
        "applicability": {"EPS": "required", "SEGMENTS": "not_applicable", "VALUATION": "required"},
        "applicability_evidence": {"SEGMENTS": evidence},
        "evidence": [
            {
                "evidence_id": "filing-evidence",
                "source_document_id": document_id,
                "content_sha256": digest,
                "locator": "/html/body",
            }
        ],
    }


def _prepare_bundle(db, task):
    repository = OnboardingRepository(db)
    digest = "c" * 64
    bundle = repository.create_fetch_bundle(
        task["onboarding_id"], expected_revision=task["revision"],
        fetcher_version="fixture", parser_version="fixture",
        documents=[{
            "document_id": "filing:api", "document_type": "FILING_DOCUMENT",
            "accession_number": "api", "form_type": "10-K",
            "filed_at": "2026-01-01", "report_date": "2025-12-31",
            "fetched_at": "2026-01-01T00:00:00Z", "source_url": "https://www.sec.gov/api",
            "content_sha256": digest, "raw_locator": "sec/api/primary.html",
        }],
    )
    db._conn.execute(
        """UPDATE company_onboarding SET state='NEEDS_ADAPTATION', current_step='BUILD',
           error_json=? WHERE onboarding_id=?""",
        [json.dumps({"code": "ADAPTATION_REQUIRED", "remediation": "PROFILE_IMPORT"}), task["onboarding_id"]],
    )
    return repository.get(task["onboarding_id"]), bundle


def test_candidate_and_yaml_endpoints_are_deterministic_and_side_effect_free(
    db, monkeypatch
):
    client, discovery = _client(db, monkeypatch)
    created, _ = _create(client, discovery, key="candidate-api")
    task, bundle = _prepare_bundle(db, created.json())
    artifact = build_candidate_artifact(
        onboarding_id=task.onboarding_id,
        task_revision=task.revision,
        company_id=task.company_id,
        bundle=bundle,
        mapping=MappingRegistry(),
        fact_catalogs={bundle.documents[0].document_id: [{
            "concept": "us-gaap:Revenues", "context_ref": "ctx",
            "unit_ref": "USD", "locator": "/html/body/fact",
        }]},
        securities=[{"ticker": "EXAMPLE", "exchange": "NYSE", "currency": "USD", "instrument_type": "COMMON_STOCK"}],
        fiscal_year_end="12-31",
    )
    monkeypatch.setattr(OnboardingPipeline, "candidate_artifact", lambda self, current: artifact)

    generated = client.post(
        f"/api/v1/company-onboardings/{task.onboarding_id}/profile-candidate",
        json={"expected_revision": task.revision},
    )
    assert generated.status_code == 200
    body = generated.json()
    candidate_id = body["candidate"]["profile_candidate_id"]
    assert body["candidate"]["review_status"] == "NEEDS_ADAPTATION"
    assert all(not item["raw_locator"].startswith("/") for item in body["candidate"]["snapshot_manifest"])

    revision = body["task"]["revision"]
    repeated = client.post(
        f"/api/v1/company-onboardings/{task.onboarding_id}/profile-candidate",
        json={"expected_revision": revision},
    )
    assert repeated.json()["candidate"]["profile_candidate_id"] == candidate_id
    assert repeated.json()["task"]["revision"] == revision

    before = OnboardingRepository(db).get(task.onboarding_id)
    fetched = client.get(f"/api/v1/company-onboardings/{task.onboarding_id}/profile-candidate")
    downloaded = client.get(f"/api/v1/company-onboardings/{task.onboarding_id}/profile-candidate.yaml")
    after = OnboardingRepository(db).get(task.onboarding_id)
    assert fetched.status_code == downloaded.status_code == 200
    assert before.revision == after.revision
    assert yaml.safe_load(downloaded.text) == fetched.json()["profile"]
    assert downloaded.headers["content-disposition"].endswith('profile-candidate.yaml"')
    assert "yaml_text" not in fetched.json()


def test_yaml_import_api_returns_stable_errors_and_current_profile_download(db, monkeypatch):
    client, discovery = _client(db, monkeypatch)
    created, _ = _create(client, discovery, key="yaml-api")
    task, bundle = _prepare_bundle(db, created.json())
    document = bundle.documents[0]

    invalid = client.post(
        f"/api/v1/company-onboardings/{task.onboarding_id}/profile-yaml",
        headers={"Idempotency-Key": "invalid-yaml"},
        json={"expected_revision": task.revision, "yaml_text": "schema_version: 2\nschema_version: 2\n"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == {
        "code": "INVALID_PROFILE_YAML",
        "message": "duplicate YAML key: schema_version",
        "remediation": "PROFILE_IMPORT",
        "field_errors": [],
    }

    profile = _strict_profile(task.company_id, 401, document.document_id, document.content_sha256)
    imported = client.post(
        f"/api/v1/company-onboardings/{task.onboarding_id}/profile-yaml",
        headers={"Idempotency-Key": "valid-yaml"},
        json={"expected_revision": task.revision, "yaml_text": json.dumps(profile)},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["state"] == "BUILDING"
    current = client.get(f"/api/v1/company-onboardings/{task.onboarding_id}/profile-current.yaml")
    assert current.status_code == 200
    assert current.headers["x-profile-version"] == "401"
    assert yaml.safe_load(current.text) == IssuerProfileV2.model_validate(profile).model_dump(
        mode="json", exclude={"content_sha256"}
    )


def test_refetch_preserves_history_until_new_bundle_activation_and_wakes_executor(db, monkeypatch):
    client, discovery = _client(db, monkeypatch)
    created, _ = _create(client, discovery, key="refetch-api")
    task, old_bundle = _prepare_bundle(db, created.json())
    artifact = build_candidate_artifact(
        onboarding_id=task.onboarding_id, task_revision=task.revision,
        company_id=task.company_id, bundle=old_bundle, mapping=MappingRegistry(),
        fact_catalogs={},
        securities=[{"ticker": "EXAMPLE", "exchange": "NYSE", "currency": "USD", "instrument_type": "COMMON_STOCK"}],
        fiscal_year_end="12-31",
    )
    task, candidate = OnboardingRepository(db).activate_profile_candidate(
        task.onboarding_id, expected_revision=task.revision, artifact=artifact
    )
    rejected = client.post(
        f"/api/v1/company-onboardings/{task.onboarding_id}/refetch",
        json={"expected_revision": task.revision},
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "TASK_CONFLICT"
    db._conn.execute(
        """UPDATE company_onboarding SET error_json=? WHERE onboarding_id=?""",
        [json.dumps({"code": "FETCH_BUNDLE_CORRUPTED", "remediation": "REFETCH"}), task.onboarding_id],
    )
    task = OnboardingRepository(db).get(task.onboarding_id)

    class WakeRecorder:
        calls = 0
        def wake(self):
            self.calls += 1

    recorder = WakeRecorder()
    monkeypatch.setattr(app.state, "onboarding_executor", recorder, raising=False)
    response = client.post(
        f"/api/v1/company-onboardings/{task.onboarding_id}/refetch",
        json={"expected_revision": task.revision},
    )
    assert response.status_code == 200
    refetching = response.json()
    assert refetching["state"] == "FETCHING"
    assert refetching["fetch_bundle_id"] == old_bundle.fetch_bundle_id
    assert refetching["profile_candidate_id"] == candidate.profile_candidate_id
    assert recorder.calls == 1

    repository = OnboardingRepository(db)
    repository.create_fetch_bundle(
        task.onboarding_id,
        expected_revision=refetching["revision"],
        fetcher_version="fixture-2", parser_version="fixture",
        documents=[{
            "document_id": "filing:api-new", "document_type": "FILING_DOCUMENT",
            "accession_number": "api-new", "form_type": "10-K",
            "filed_at": "2026-02-01", "report_date": "2025-12-31",
            "fetched_at": "2026-02-01T00:00:00Z", "source_url": "https://www.sec.gov/api-new",
            "content_sha256": "d" * 64, "raw_locator": "sec/api-new/primary.html",
        }],
    )
    activated = repository.get(task.onboarding_id)
    assert activated.fetch_bundle_id != old_bundle.fetch_bundle_id
    assert activated.profile_candidate_id is None
    assert activated.profile_id is None


def test_profile_review_and_quality_report_endpoints_complete_the_workflow(db, monkeypatch):
    client, discovery = _client(db, monkeypatch)
    created, _ = _create(client, discovery, key="review-workflow")
    task = created.json()
    prepared, bundle = _prepare_bundle(db, task)
    document = bundle.documents[0]
    imported = client.post(
        f"/api/v1/company-onboardings/{task['onboarding_id']}/profile",
        headers={"Idempotency-Key": "profile-review-workflow"},
        json={
            "expected_revision": prepared.revision,
            "profile": _strict_profile(task["company_id"], 301, document.document_id, document.content_sha256),
        },
    )
    assert imported.status_code == 200
    imported_task = imported.json()
    dataset_id = DatasetBuilder(db).seal_rows(
        company_id=task["company_id"],
        profile_id=imported_task["profile_id"],
        source_manifest={"documents": []},
        rows=[],
    )
    db._conn.execute(
        "INSERT INTO quality_report VALUES ('api-report', ?, 'fixture-v1', 'PASS', 'api-quality', now())",
        [dataset_id],
    )
    db._conn.execute(
        """
        UPDATE company_onboarding SET dataset_id=?, quality_report_id='api-report',
          state='NEEDS_REVIEW', current_step='PUBLISH', revision=revision+1
        WHERE onboarding_id=?
        """,
        [dataset_id, task["onboarding_id"]],
    )

    package = client.get(
        f"/api/v1/company-onboardings/{task['onboarding_id']}/review-package"
    )
    assert package.status_code == 200
    reviewed = client.post(
        f"/api/v1/company-onboardings/{task['onboarding_id']}/review",
        json={
            "expected_revision": package.json()["revision"],
            "fingerprint": package.json()["fingerprint"],
            "decision": "APPROVE",
            "reviewer": "maintainer",
            "note": "API workflow",
        },
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["state"] == "PUBLISHING"

    pipeline = OnboardingPipeline(db, OnboardingRepository(db), fetcher=lambda url: None)
    assert OnboardingRunner(
        db, OnboardingRepository(db), handlers=pipeline.handlers()
    ).run_once()
    published = client.get(f"/api/v1/company-onboardings/{task['onboarding_id']}")
    assert published.json()["state"] == "PUBLISHED"
    directory = client.get("/api/v1/companies")
    published_company = next(item for item in directory.json()["items"] if item["ticker"] == "EXAMPLE")
    assert published_company["quality_status"] == "VERIFIED"
    # Publications created before the status update retain a PENDING stored value.
    db._conn.execute(
        "UPDATE company SET quality_status='PENDING' WHERE company_id=?",
        [task["company_id"]],
    )
    directory = client.get("/api/v1/companies")
    published_company = next(item for item in directory.json()["items"] if item["ticker"] == "EXAMPLE")
    assert published_company["quality_status"] == "VERIFIED"

    report = client.get("/api/v1/companies/EXAMPLE/quality-report")
    assert report.status_code == 200
    assert report.json()["publication_id"] == published.json()["publication_id"]
    assert report.json()["report"]["result"] == "PASS"
    blocked = client.get(
        "/api/v1/companies/EXAMPLE/facts", params={"metrics": "REVENUE"}
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "CAPABILITY_UNAVAILABLE"


def test_financial_reads_are_pinned_to_publication_and_reject_cross_company(db, monkeypatch):
    client, _ = _client(db, monkeypatch)
    first = _publish_revenue(db, company_id="0000320193", version=201, value=100)
    candidate_profile = PublicationRepository(db).create_profile(
        "0000320193", version=202, schema_version=1, content={"version": 202}
    )
    candidate_dataset = DatasetBuilder(db).seal_rows(
        company_id="0000320193",
        profile_id=candidate_profile,
        source_manifest={"documents": []},
        rows=[
            (
                "canonical_fact",
                "revenue-202",
                {
                    "canonical_fact_id": "revenue-202",
                    "company_id": "0000320193",
                    "canonical_metric": "REVENUE",
                    "period_type": "FY",
                    "fiscal_year": 2025,
                    "value": 999,
                    "unit": "USD",
                    "status": "REPORTED",
                    "mapping_rule_id": "fixture",
                    "mapping_version": "v1",
                    "source_raw_fact_ids": [],
                },
            )
        ],
    )

    original_facts = PublicationRepository.facts
    switched = []

    def publish_during_read(repository, context):
        if not switched and context.publication_id == first.publication_id:
            switched.append(
                PublicationRepository(db).publish_dataset(
                    company_id="0000320193",
                    dataset_id=candidate_dataset,
                    profile_id=candidate_profile,
                    quality_report_id=None,
                    review_id=None,
                )
            )
        return original_facts(repository, context)

    monkeypatch.setattr(PublicationRepository, "facts", publish_during_read)
    visible = client.get(
        "/api/v1/companies/AAPL/facts", params={"metrics": "REVENUE"}
    )
    assert visible.status_code == 200
    assert visible.json()["publication_id"] == first.publication_id
    assert visible.json()["security_id"]
    assert visible.json()["facts"][0]["value"] == 100

    second = switched[0]
    latest = client.get("/api/v1/companies/AAPL/facts", params={"metrics": "REVENUE"})
    pinned = client.get(
        "/api/v1/companies/AAPL/facts",
        params={"metrics": "REVENUE", "publication_id": first.publication_id},
    )
    assert latest.json()["publication_id"] == second.publication_id
    assert latest.json()["facts"][0]["value"] == 999
    assert pinned.json()["publication_id"] == first.publication_id
    assert pinned.json()["facts"][0]["value"] == 100

    msft = _publish_revenue(db, company_id="0000789019", version=201, value=200)
    wrong = client.get(
        "/api/v1/companies/AAPL/facts",
        params={"metrics": "REVENUE", "publication_id": msft.publication_id},
    )
    assert wrong.status_code == 404


def test_metrics_and_overview_compute_from_the_published_dataset(db, monkeypatch):
    client, _ = _client(db, monkeypatch)
    company_id = "0000320193"
    publications = PublicationRepository(db)
    profile_id = publications.create_profile(
        company_id, version=301, schema_version=1, content={"version": 301}
    )
    rows = [(
        "source_document", "published-filing", {
            "source_document_id": "published-filing",
            "company_id": company_id,
            "provider": "SEC",
            "document_type": "FILING_DOCUMENT",
            "form_type": "10-Q",
            "source_url": "https://www.sec.gov/Archives/example",
            "fetched_at": "2026-09-01T00:00:00Z",
            "content_sha256": "a" * 64,
        },
    )]
    for quarter, value in enumerate((10.0, 20.0, 30.0, 40.0), start=1):
        fact_id = f"published-revenue-q{quarter}"
        rows.append((
            "raw_fact",
            f"raw-q{quarter}",
            {
                "raw_fact_id": f"raw-q{quarter}",
                "source_document_id": "published-filing",
                "concept": "Revenues",
            },
        ))
        rows.append((
            "canonical_fact",
            fact_id,
            {
                "canonical_fact_id": fact_id,
                "company_id": company_id,
                "canonical_metric": "REVENUE",
                "period_type": "Q_STANDALONE",
                "fiscal_year": 2026,
                "fiscal_quarter": quarter,
                "period_end": f"2026-{quarter * 3:02d}-30",
                "value": value,
                "unit": "USD",
                "status": "REPORTED",
                "mapping_rule_id": "fixture",
                "mapping_version": "v1",
                "source_raw_fact_ids": [f"raw-q{quarter}"],
            },
        ))
    dataset_id = DatasetBuilder(db).seal_rows(
        company_id=company_id,
        profile_id=profile_id,
        source_manifest={"documents": []},
        rows=rows,
    )
    publication = publications.publish_dataset(
        company_id=company_id,
        dataset_id=dataset_id,
        profile_id=profile_id,
        quality_report_id=None,
        review_id=None,
    )

    metrics = client.get(
        "/api/v1/companies/AAPL/metrics",
        params={"metrics": "REVENUE", "frequency": "quarterly"},
    )
    overview = client.get("/api/v1/companies/AAPL/overview")

    assert metrics.status_code == 200
    assert metrics.json()["publication_id"] == publication.publication_id
    assert [item["value"] for item in metrics.json()["metrics"]] == [10, 20, 30, 40]
    assert overview.status_code == 200
    assert overview.json()["kpis"]["TTM_REVENUE"]["value"] == 100
    assert overview.json()["latest_period"]["fiscal_quarter"] == 4
    fact = client.get("/api/v1/provenance/published-revenue-q4")
    assert fact.status_code == 200
    assert [node["kind"] for node in fact.json()["tree"]["parents"]] == ["raw_fact"]
    assert fact.json()["tree"]["parents"][0]["parents"][0]["kind"] == "source_document"
    facts = client.get("/api/v1/companies/AAPL/facts", params={"metrics": "REVENUE"})
    assert facts.json()["facts"][-1]["provenance"]["source_url"] == "https://www.sec.gov/Archives/example"
    assert client.get("/api/v1/sources/published-filing").status_code == 200
    derived = client.get(
        f"/api/v1/provenance/{overview.json()['kpis']['TTM_REVENUE']['result_id']}"
    )
    assert derived.status_code == 200
    assert len(derived.json()["tree"]["parents"]) == 4
    assert all(node["kind"] == "canonical_fact" for node in derived.json()["tree"]["parents"])

    restated_rows = []
    for entity_type, row_id, payload in rows:
        changed = dict(payload)
        if entity_type == "canonical_fact":
            changed["mapping_version"] = "v2"
        elif entity_type == "raw_fact":
            changed["concept"] = "RevenueFromContract"
        elif entity_type == "source_document":
            changed["source_url"] = "https://www.sec.gov/Archives/restated"
        restated_rows.append((entity_type, row_id, changed))
    restated_dataset = DatasetBuilder(db).seal_rows(
        company_id=company_id,
        profile_id=profile_id,
        source_manifest={"documents": ["restated"]},
        rows=restated_rows,
    )
    restated = publications.publish_dataset(
        company_id=company_id,
        dataset_id=restated_dataset,
        profile_id=profile_id,
        quality_report_id=None,
        review_id=None,
    )
    old_tree = client.get(
        "/api/v1/provenance/published-revenue-q4",
        params={"publication_id": publication.publication_id},
    )
    new_tree = client.get(
        "/api/v1/provenance/published-revenue-q4",
        params={"publication_id": restated.publication_id},
    )
    assert old_tree.json()["tree"]["fields"]["mapping_version"] == "v1"
    assert new_tree.json()["tree"]["fields"]["mapping_version"] == "v2"
    assert old_tree.json()["tree"]["parents"][0]["fields"]["concept"] == "Revenues"
    pinned_facts = client.get(
        "/api/v1/companies/AAPL/facts",
        params={"metrics": "REVENUE", "publication_id": publication.publication_id},
    )
    assert pinned_facts.json()["facts"][-1]["provenance"]["source_url"] == "https://www.sec.gov/Archives/example"


def test_segments_and_freshness_read_the_published_dataset(db, monkeypatch):
    client, _ = _client(db, monkeypatch)
    company_id = "0000320193"
    document_id = "published-filing"
    digest = "d" * 64
    profile = _strict_profile(company_id, 302, document_id, digest)
    profile["securities"][0]["ticker"] = "AAPL"
    profile["securities"][0]["exchange"] = "NASDAQ"
    profile["segments"] = {
        "parser": "ixbrl_segments_v1",
        "axes": [{
            "name": "StatementBusinessSegmentsAxis",
            "kind": "segment",
            "label": "Operating segment",
            "members": {"PublishedSegmentMember": {"label": "Published Segment"}},
            "evidence": ["filing-evidence"],
        }],
        "reconciliation": "explicit_eliminations",
        "revenue_concept": "us-gaap:Revenues",
        "profit_concept": None,
        "evidence": ["filing-evidence"],
    }
    profile["applicability"]["SEGMENTS"] = "required"
    profile["applicability_evidence"].pop("SEGMENTS")

    publications = PublicationRepository(db)
    profile_id = publications.create_profile(
        company_id, version=302, schema_version=2, content=profile
    )
    dataset_id = DatasetBuilder(db).seal_rows(
        company_id=company_id,
        profile_id=profile_id,
        source_manifest={"documents": []},
        rows=[
            (
                "source_document",
                document_id,
                {
                    "source_document_id": document_id,
                    "company_id": company_id,
                    "provider": "SEC",
                    "document_type": "FILING_DOCUMENT",
                    "form_type": "10-K",
                    "fetched_at": "2026-09-19T12:00:00+00:00",
                    "content_sha256": digest,
                    "source_url": "https://www.sec.gov/example",
                },
            ),
            (
                "source_document",
                "published-filing-new",
                {
                    "source_document_id": "published-filing-new",
                    "company_id": company_id,
                    "provider": "SEC",
                    "document_type": "FILING_DOCUMENT",
                    "form_type": "10-K/A",
                    "fetched_at": "2026-09-19T12:00:00+00:00",
                    "content_sha256": "f" * 64,
                    "source_url": "https://www.sec.gov/example-new",
                },
            ),
            (
                "canonical_fact", "old-disclosure-date", {
                    "canonical_fact_id": "old-disclosure-date",
                    "company_id": company_id,
                    "canonical_metric": "REVENUE",
                    "period_type": "FY",
                    "status": "REPORTED",
                    "mapping_rule_id": "fixture",
                    "mapping_version": "v1",
                    "source_raw_fact_ids": [],
                    "source_document_id": document_id,
                    "as_known_at": "2026-08-20",
                },
            ),
            (
                "canonical_fact", "new-disclosure-date", {
                    "canonical_fact_id": "new-disclosure-date",
                    "company_id": company_id,
                    "canonical_metric": "REVENUE",
                    "period_type": "FY",
                    "status": "REPORTED",
                    "mapping_rule_id": "fixture",
                    "mapping_version": "v1",
                    "source_raw_fact_ids": [],
                    "source_document_id": "published-filing-new",
                    "as_known_at": "2026-08-27",
                },
            ),
            (
                "source_document",
                "published-companyfacts",
                {
                    "source_document_id": "published-companyfacts",
                    "company_id": company_id,
                    "provider": "SEC",
                    "document_type": "COMPANYFACTS",
                    "fetched_at": "2026-09-19T12:00:00+00:00",
                    "content_sha256": "e" * 64,
                    "source_url": "https://data.sec.gov/example",
                },
            ),
            *[
                (
                    "source_document", f"recent-filing-{index}", {
                        "source_document_id": f"recent-filing-{index}",
                        "company_id": company_id,
                        "provider": "SEC",
                        "document_type": "FILING_DOCUMENT",
                        "form_type": "10-Q",
                        "fetched_at": "2026-09-20T12:00:00+00:00",
                        "content_sha256": f"{index}" * 64,
                        "source_url": f"https://www.sec.gov/recent-{index}",
                    },
                )
                for index in range(5)
            ],
            (
                "segment_fact",
                "published-segment-fact",
                {
                    "segment_fact_id": "published-segment-fact",
                    "company_id": company_id,
                    "segment_name_reported": "PublishedSegmentMember",
                    "segment_name_canonical": "Published Segment",
                    "segment_kind": "segment",
                    "metric_name": "REVENUE",
                    "fiscal_year": 2026,
                    "fiscal_quarter": None,
                    "period_type": "FY",
                    "period_end": "2026-01-25",
                    "value": 123.0,
                    "unit": "USD",
                    "status": "DISCLOSED",
                    "source_raw_fact_ids": [],
                    "source_document_id": document_id,
                },
            ),
            (
                "segment_fact", "published-segment-new", {
                    "segment_fact_id": "published-segment-new",
                    "company_id": company_id,
                    "segment_name_reported": "PublishedSegmentMember",
                    "segment_name_canonical": "Published Segment",
                    "segment_kind": "segment",
                    "metric_name": "REVENUE",
                    "fiscal_year": 2026,
                    "fiscal_quarter": None,
                    "period_type": "FY",
                    "period_end": "2026-01-25",
                    "value": 456.0,
                    "unit": "USD",
                    "status": "DISCLOSED",
                    "source_raw_fact_ids": [],
                    "source_document_id": "published-filing-new",
                },
            ),
        ],
    )
    publication = publications.publish_dataset(
        company_id=company_id,
        dataset_id=dataset_id,
        profile_id=profile_id,
        quality_report_id=None,
        review_id=None,
    )

    segment_response = client.get("/api/v1/companies/AAPL/segments")
    freshness_response = client.get("/api/v1/companies/AAPL/freshness")
    company_response = client.get("/api/v1/companies/AAPL")

    assert segment_response.status_code == 200
    assert segment_response.json()["publication_id"] == publication.publication_id
    assert [item["name"] for item in segment_response.json()["segments"]] == [
        "Published Segment"
    ]
    assert segment_response.json()["segments"][0]["latest"]["value"] == 456.0
    assert freshness_response.status_code == 200
    modules = {item["key"]: item for item in freshness_response.json()["modules"]}
    assert modules["sec_financials"]["as_of"] == "2026-08-27"
    assert modules["segments"]["as_of"] == "2026-08-27"
    assert company_response.json()["source_freshness"]["COMPANYFACTS_SNAPSHOT"][
        "fetched_at"
    ].startswith("2026-09-19")
