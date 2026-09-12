from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml

from equitylens.companies.models import CompanyIdentity, SecurityIdentity
from equitylens.companies.registry import CompanyRegistry, seed_security_id
from equitylens.onboarding.models import TaskState
from equitylens.onboarding.pipeline import OnboardingPipeline
from equitylens.onboarding.repository import OnboardingRepository
from equitylens.onboarding.runner import OnboardingRunner
from equitylens.issuers.profile import IssuerProfileService
from equitylens.publication.repository import PublicationRepository


CIK = "0000000001"


def _profile() -> dict:
    return {
        "schema_version": 1,
        "company_id": CIK,
        "version": 1,
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
                "ticker": "ONE",
                "exchange": "NYSE",
                "currency": "USD",
                "instrument_type": "COMMON_STOCK",
                "evidence": ["identity"],
            }
        ],
        "applicability": {"SEGMENTS": "required"},
        "evidence": [
            {
                "evidence_id": "identity",
                "source_document_id": "submissions",
                "content_sha256": "a" * 64,
                "locator": "https://www.sec.gov/edgar/browse/?CIK=1",
            }
        ],
    }


def _payloads():
    submissions = {
        "cik": CIK,
        "name": "ONE CORP",
        "tickers": ["ONE"],
        "exchanges": ["NYSE"],
        "filings": {
            "recent": {
                "form": ["10-K"],
                "reportDate": ["2025-12-31"],
                "accessionNumber": ["one-2025"],
            }
        },
    }
    companyfacts = {
        "cik": int(CIK),
        "entityName": "ONE CORP",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2025-01-01",
                                "end": "2025-12-31",
                                "val": 100,
                                "accn": "one-2025",
                                "fy": 2025,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2026-02-01",
                            }
                        ]
                    }
                }
            }
        },
    }
    return submissions, companyfacts


def _register(db, cik=CIK, ticker="ONE"):
    registry = CompanyRegistry(db)
    registry.register_company(
        CompanyIdentity(
            company_id=cik,
            cik=cik,
            legal_name=f"{ticker} CORP",
            reporting_template="us_gaap_operating_v1",
            quality_status="PENDING",
        ),
        legacy_ticker=ticker,
    )
    security_id = seed_security_id(cik, ticker, "NYSE")
    registry.register_security(
        SecurityIdentity(
            security_id=security_id,
            company_id=cik,
            ticker=ticker,
            exchange="NYSE",
            currency="USD",
            instrument_type="COMMON_STOCK",
            identity_evidence={"fixture": True},
        )
    )
    return security_id


def test_configured_pipeline_fetches_builds_and_validates(db, tmp_path):
    submissions, companyfacts = _payloads()
    profile_root = tmp_path / "profiles"
    profile_path = profile_root / CIK / "1.yaml"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(yaml.safe_dump(_profile(), sort_keys=False))

    def fetch(url: str):
        payload = submissions if "submissions" in url else companyfacts
        return json.dumps(payload).encode(), {"fetched_at": "2026-09-12T00:00:00+00:00"}

    security_id = _register(db)
    repository = OnboardingRepository(db)
    task = repository.create_task(
        company_id=CIK,
        security_id=security_id,
        input_fingerprint="pipeline-fixture",
    )
    pipeline = OnboardingPipeline(
        db, repository, raw_dir=tmp_path / "raw", profile_root=profile_root, fetcher=fetch
    )
    runner = OnboardingRunner(db, repository, handlers=pipeline.handlers())

    assert runner.run_once() is True
    assert runner.run_once() is True
    assert runner.run_once() is True

    completed = repository.get(task.onboarding_id)
    assert completed.state == TaskState.NEEDS_ADAPTATION
    assert completed.profile_id and completed.dataset_id and completed.quality_report_id
    assert completed.actions == ["CANCEL", "PROFILE_IMPORT"]


def test_unconfigured_issuer_pauses_for_adaptation(db, tmp_path):
    submissions, companyfacts = _payloads()

    def fetch(url: str):
        payload = submissions if "submissions" in url else companyfacts
        return json.dumps(payload).encode(), {"fetched_at": "2026-09-12T00:00:00+00:00"}

    security_id = _register(db)
    repository = OnboardingRepository(db)
    task = repository.create_task(
        company_id=CIK,
        security_id=security_id,
        input_fingerprint="unconfigured-fixture",
    )
    pipeline = OnboardingPipeline(
        db, repository, raw_dir=tmp_path / "raw", profile_root=tmp_path / "empty", fetcher=fetch
    )
    runner = OnboardingRunner(db, repository, handlers=pipeline.handlers())

    runner.run_once()
    runner.run_once()

    paused = repository.get(task.onboarding_id)
    assert paused.state == TaskState.NEEDS_ADAPTATION
    assert paused.current_step.value == "BUILD"
    assert paused.actions == ["CANCEL", "PROFILE_IMPORT"]


def test_profile_import_after_pause_rebuilds_instead_of_skipping_build(db, tmp_path):
    submissions, companyfacts = _payloads()

    def fetch(url: str):
        payload = submissions if "submissions" in url else companyfacts
        return json.dumps(payload).encode(), {"fetched_at": "2026-09-12T00:00:00+00:00"}

    security_id = _register(db)
    repository = OnboardingRepository(db)
    task = repository.create_task(
        company_id=CIK, security_id=security_id, input_fingerprint="resume-fixture"
    )
    pipeline = OnboardingPipeline(
        db, repository, raw_dir=tmp_path / "raw", profile_root=tmp_path / "empty", fetcher=fetch
    )
    runner = OnboardingRunner(db, repository, handlers=pipeline.handlers())
    runner.run_once()
    runner.run_once()
    paused = repository.get(task.onboarding_id)

    imported = IssuerProfileService(PublicationRepository(db), repository).import_profile(
        task.onboarding_id, paused.revision, _profile()
    )
    assert imported.current_step.value == "BUILD"

    runner.run_once()

    rebuilt = repository.get(task.onboarding_id)
    assert rebuilt.dataset_id is not None
    assert rebuilt.current_step.value == "VALIDATE"


def test_revised_profile_after_validation_pause_invalidates_completed_build(db, tmp_path):
    submissions, companyfacts = _payloads()
    profile_root = tmp_path / "profiles"
    profile_path = profile_root / CIK / "1.yaml"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(yaml.safe_dump(_profile(), sort_keys=False))

    def fetch(url: str):
        payload = submissions if "submissions" in url else companyfacts
        return json.dumps(payload).encode(), {"fetched_at": "2026-09-12T00:00:00+00:00"}

    security_id = _register(db)
    repository = OnboardingRepository(db)
    task = repository.create_task(
        company_id=CIK, security_id=security_id, input_fingerprint="validation-resume"
    )
    pipeline = OnboardingPipeline(
        db, repository, raw_dir=tmp_path / "raw", profile_root=profile_root, fetcher=fetch
    )
    runner = OnboardingRunner(db, repository, handlers=pipeline.handlers())
    runner.run_once()
    runner.run_once()
    runner.run_once()
    paused = repository.get(task.onboarding_id)
    old_dataset_id = paused.dataset_id
    revised = _profile()
    revised["version"] = 2
    imported = IssuerProfileService(PublicationRepository(db), repository).import_profile(
        task.onboarding_id, paused.revision, revised
    )

    runner.run_once()

    rebuilt = repository.get(task.onboarding_id)
    assert rebuilt.current_step.value == "VALIDATE"
    assert rebuilt.dataset_id is not None
    assert rebuilt.dataset_id != old_dataset_id


def test_pipeline_rejects_profile_for_another_company(db, tmp_path):
    wrong = _profile()
    wrong["company_id"] = "0000000002"
    profile_path = tmp_path / "profiles" / CIK / "1.yaml"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(yaml.safe_dump(wrong, sort_keys=False))
    security_id = _register(db)
    repository = OnboardingRepository(db)
    task = repository.create_task(
        company_id=CIK, security_id=security_id, input_fingerprint="wrong-profile"
    )
    pipeline = OnboardingPipeline(db, repository, profile_root=tmp_path / "profiles")

    with pytest.raises(ValueError, match="company_id"):
        pipeline._profile(task)


def test_pipeline_rejects_stored_profile_payload_for_another_company(db, tmp_path):
    security_id = _register(db)
    repository = OnboardingRepository(db)
    task = repository.create_task(
        company_id=CIK, security_id=security_id, input_fingerprint="wrong-stored-profile"
    )
    wrong = _profile()
    wrong["company_id"] = "0000000002"
    profile_id = PublicationRepository(db).create_profile(
        CIK, version=91, schema_version=1, content=wrong
    )
    task = repository.set_candidate(
        task.onboarding_id,
        expected_revision=task.revision,
        profile_id=profile_id,
        state=TaskState.BUILDING,
        current_step=task.current_step,
    )
    pipeline = OnboardingPipeline(db, repository, raw_dir=tmp_path, fetcher=lambda url: None)

    with pytest.raises(ValueError, match="company_id"):
        pipeline._profile(task)


def test_pipeline_normalization_accepts_only_profile_metric_concepts(db, tmp_path):
    submissions, companyfacts = _payloads()
    profile = _profile()
    profile["metrics"]["REVENUE"]["concepts"] = ["us-gaap:SalesRevenueNet"]
    profile_path = tmp_path / "profiles" / CIK / "1.yaml"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False))

    def fetch(url: str):
        payload = submissions if "submissions" in url else companyfacts
        return json.dumps(payload).encode(), {"fetched_at": "2026-09-12T00:00:00+00:00"}

    security_id = _register(db)
    repository = OnboardingRepository(db)
    task = repository.create_task(
        company_id=CIK, security_id=security_id, input_fingerprint="profile-mapping"
    )
    pipeline = OnboardingPipeline(
        db, repository, raw_dir=tmp_path / "raw", profile_root=tmp_path / "profiles", fetcher=fetch
    )
    runner = OnboardingRunner(db, repository, handlers=pipeline.handlers())

    runner.run_once()
    runner.run_once()

    built = repository.get(task.onboarding_id)
    metrics = {
        json.loads(row["payload_json"])["canonical_metric"]
        for row in db.query(
            "SELECT payload_json FROM dataset_row WHERE dataset_id=? AND entity_type='canonical_fact'",
            [built.dataset_id],
        )
    }
    assert "REVENUE" not in metrics


def test_default_pipeline_reuses_one_sec_client_with_single_attempt_budget(
    db, tmp_path, monkeypatch
):
    created = []

    class CountingClient:
        def __init__(self, *, max_retries):
            self.max_retries = max_retries
            self.urls = []
            created.append(self)

        def get(self, url):
            self.urls.append(url)
            return 200, b"{}", {"fetched_at": "2026-09-12T00:00:00+00:00"}

        def close(self):
            pass

    monkeypatch.setattr("equitylens.onboarding.pipeline.SECClient", CountingClient)
    pipeline = OnboardingPipeline(db, OnboardingRepository(db), raw_dir=tmp_path)

    pipeline._fetch_url("https://data.sec.gov/one")
    pipeline._fetch_url("https://data.sec.gov/two")

    assert len(created) == 1
    assert created[0].max_retries == 1
    assert created[0].urls == ["https://data.sec.gov/one", "https://data.sec.gov/two"]


def test_sec_403_is_not_retried_as_a_transient_step(db, tmp_path, monkeypatch):
    request = httpx.Request("GET", "https://data.sec.gov/submissions/CIK0000000001.json")
    response = httpx.Response(403, request=request)

    class DeniedClient:
        def __init__(self, *, max_retries):
            pass

        def get(self, url):
            raise httpx.HTTPStatusError("forbidden", request=request, response=response)

        def close(self):
            pass

    monkeypatch.setattr("equitylens.onboarding.pipeline.SECClient", DeniedClient)
    security_id = _register(db)
    repository = OnboardingRepository(db)
    task = repository.create_task(
        company_id=CIK, security_id=security_id, input_fingerprint="sec-denied"
    )
    pipeline = OnboardingPipeline(db, repository, raw_dir=tmp_path)
    runner = OnboardingRunner(db, repository, handlers=pipeline.handlers())

    runner.run_once()

    failed = repository.get(task.onboarding_id)
    assert failed.state == TaskState.FAILED
    assert failed.error["code"] == "SEC_ACCESS_DENIED"
