from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from equitylens.api import company_routes
from equitylens.api.main import app
from equitylens.companies.discovery import CompanyDiscovery, DiscoveryError
from equitylens.companies.models import CompanyIdentity, SecurityIdentity
from equitylens.companies.registry import CompanyRegistry
from equitylens.onboarding.pipeline import OnboardingPipeline
from equitylens.onboarding.repository import OnboardingRepository
from equitylens.onboarding.runner import OnboardingRunner
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


def _strict_profile(company_id: str, version: int):
    return {
        "schema_version": 1,
        "company_id": company_id,
        "version": version,
        "template": "us_gaap_operating_v1",
        "fiscal_calendar": {"year_end": "12-31", "week_based": False},
        "metrics": {
            "REVENUE": {
                "concepts": ["us-gaap:Revenues"],
                "unit": "USD",
                "context": "consolidated",
                "period": "duration",
                "selection": "latest_filed_same_basis",
            }
        },
        "segments": {"axes": [], "reconciliation": "explicit_eliminations"},
        "cash_debt": {
            "cash_components": ["us-gaap:CashAndCashEquivalentsAtCarryingValue"],
            "debt_components": ["us-gaap:LongTermDebtNoncurrent"],
            "restricted_cash_policy": "separate",
        },
        "eps_method": "reported_diluted",
        "securities": [
            {
                "ticker": "EXAMPLE",
                "exchange": "NYSE",
                "currency": "USD",
                "instrument_type": "COMMON_STOCK",
                "evidence": ["security-evidence"],
            }
        ],
        "applicability": {},
        "evidence": [
            {
                "evidence_id": "security-evidence",
                "source_document_id": "doc-1",
                "content_sha256": "a" * 64,
                "locator": "SEC submissions tickers[0]",
            }
        ],
    }


def test_profile_review_and_quality_report_endpoints_complete_the_workflow(db, monkeypatch):
    client, discovery = _client(db, monkeypatch)
    created, _ = _create(client, discovery, key="review-workflow")
    task = created.json()
    imported = client.post(
        f"/api/v1/company-onboardings/{task['onboarding_id']}/profile",
        json={
            "expected_revision": task["revision"],
            "profile": _strict_profile(task["company_id"], 301),
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
