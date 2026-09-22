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
from equitylens.storage.raw_store import save_snapshot


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


def _profile_v2_for_bundle(bundle, version: int) -> dict:
    filing = next(item for item in bundle.documents if item.document_type == "FILING_DOCUMENT")
    evidence = ["filing-evidence"]
    return {
        "schema_version": 2, "company_id": CIK, "version": version,
        "template": "us_gaap_operating_v1", "template_evidence": evidence,
        "fiscal_calendar": {"year_end": "12-31", "week_based": False, "evidence": evidence},
        "metrics": {"REVENUE": {"concepts": ["us-gaap:Revenues"], "unit": "USD", "context": "consolidated", "period": "duration", "selection": "latest_filed_same_basis", "evidence": evidence}},
        "segments": {"parser": "not_applicable", "axes": [], "reconciliation": "not_applicable", "revenue_concept": None, "profit_concept": None, "evidence": evidence},
        "cash_debt": {"cash_components": ["us-gaap:CashAndCashEquivalentsAtCarryingValue"], "debt_components": ["us-gaap:LongTermDebtNoncurrent"], "restricted_cash_policy": "separate", "evidence": evidence},
        "eps_method": "reported_diluted", "eps_method_evidence": evidence,
        "securities": [{"ticker": "ONE", "exchange": "NYSE", "currency": "USD", "instrument_type": "COMMON_STOCK", "evidence": evidence}],
        "applicability": {"EPS": "required", "SEGMENTS": "not_applicable", "VALUATION": "required"},
        "applicability_evidence": {"SEGMENTS": evidence},
        "evidence": [{"evidence_id": "filing-evidence", "source_document_id": filing.document_id, "content_sha256": filing.content_sha256, "locator": "//*[@name='us-gaap:Revenues']"}],
    }


def _ixbrl_revenue() -> bytes:
    return b"""<html xmlns:ix='http://www.xbrl.org/2013/inlineXBRL'
    xmlns:xbrli='http://www.xbrl.org/2003/instance'>
    <xbrli:context id='ctx'><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate>
    <xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
    <ix:nonFraction name='us-gaap:Revenues' contextRef='ctx' unitRef='USD'>100</ix:nonFraction>
    </html>"""


def _payloads():
    submissions = _quality_window_submissions()
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


def _quality_window_submissions() -> dict:
    rows = []
    for year in (2023, 2024, 2025):
        rows.append(
            {
                "form": "10-K",
                "reportDate": f"{year}-01-31",
                "filingDate": f"{year}-03-01",
                "accessionNumber": f"0000000001-{year % 100:02d}-000001",
                "primaryDocument": f"annual-{year}.htm",
            }
        )
    for index in range(8):
        year = 2024 + index // 4
        month = (index % 4 + 1) * 2
        rows.append(
            {
                "form": "10-Q",
                "reportDate": f"{year}-{month:02d}-01",
                "filingDate": f"{year}-{month:02d}-15",
                "accessionNumber": f"0000000001-{year % 100:02d}-{index + 10:06d}",
                "primaryDocument": f"quarter-{year}-{month}.htm",
            }
        )
    recent = {key: [row[key] for row in rows] for key in rows[0]}
    return {
        "cik": CIK,
        "name": "ONE CORP",
        "tickers": ["ONE"],
        "exchanges": ["NYSE"],
        "filings": {"recent": recent, "files": []},
    }


def test_fetch_atomically_binds_fixed_filing_bundle(db, tmp_path):
    submissions = _quality_window_submissions()
    companyfacts = {"cik": int(CIK), "entityName": "ONE CORP", "facts": {}}

    def fetch(url: str):
        if "submissions" in url:
            payload = json.dumps(submissions).encode()
        elif "companyfacts" in url:
            payload = json.dumps(companyfacts).encode()
        else:
            payload = f"<html data-source='{url}'></html>".encode()
        return payload, {"fetched_at": "2026-09-19T00:00:00+00:00"}

    security_id = _register(db)
    repository = OnboardingRepository(db)
    task = repository.create_task(
        company_id=CIK,
        security_id=security_id,
        input_fingerprint="fixed-fetch-bundle",
    )
    pipeline = OnboardingPipeline(db, repository, raw_dir=tmp_path / "raw", fetcher=fetch)

    assert OnboardingRunner(db, repository, handlers=pipeline.handlers()).run_once()
    current = repository.get(task.onboarding_id)
    bundle = repository.get_fetch_bundle(current.fetch_bundle_id)

    assert current.state == TaskState.BUILDING
    assert len(bundle.documents) == 13
    assert {document.document_type for document in bundle.documents} == {
        "SUBMISSIONS",
        "COMPANYFACTS",
        "FILING_DOCUMENT",
    }
    assert all(not document.raw_locator.startswith("/") for document in bundle.documents)

    original_sha = bundle.content_sha256
    save_snapshot(
        tmp_path / "raw" / "sec" / CIK,
        "submissions.json",
        b'{"changed":true}',
        metadata={"fetched_at": "2026-09-20T00:00:00+00:00"},
    )
    assert repository.get_fetch_bundle(current.fetch_bundle_id).content_sha256 == original_sha


def test_profile_v2_build_uses_filing_context_instead_of_companyfacts(db, tmp_path):
    submissions = _quality_window_submissions()
    companyfacts = {
        "cik": int(CIK),
        "facts": {"us-gaap": {"Revenues": {"units": {"USD": [{"val": 999}]}}}},
    }
    ixbrl = b"""<html xmlns:ix='http://www.xbrl.org/2013/inlineXBRL'
    xmlns:xbrli='http://www.xbrl.org/2003/instance'>
    <xbrli:context id='ctx'><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate>
    <xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
    <ix:nonFraction name='us-gaap:Revenues' contextRef='ctx' unitRef='USD'>100</ix:nonFraction>
    </html>"""

    def fetch(url: str):
        if "submissions" in url:
            content = json.dumps(submissions).encode()
        elif "companyfacts" in url:
            content = json.dumps(companyfacts).encode()
        else:
            content = ixbrl
        return content, {"fetched_at": "2026-09-19T00:00:00+00:00"}

    security_id = _register(db)
    repository = OnboardingRepository(db)
    task = repository.create_task(
        company_id=CIK, security_id=security_id, input_fingerprint="v2-filing-lineage"
    )
    pipeline = OnboardingPipeline(db, repository, raw_dir=tmp_path / "raw", fetcher=fetch)
    runner = OnboardingRunner(db, repository, handlers=pipeline.handlers())
    assert runner.run_once()
    current = repository.get(task.onboarding_id)
    bundle = repository.get_fetch_bundle(current.fetch_bundle_id)
    filing = next(item for item in bundle.documents if item.document_type == "FILING_DOCUMENT")
    evidence = {
        "evidence_id": "filing-evidence",
        "source_document_id": filing.document_id,
        "content_sha256": filing.content_sha256,
        "locator": "//*[@name='us-gaap:Revenues']",
    }
    profile = {
        "schema_version": 2, "company_id": CIK, "version": 2,
        "template": "us_gaap_operating_v1", "template_evidence": ["filing-evidence"],
        "fiscal_calendar": {"year_end": "12-31", "week_based": False, "evidence": ["filing-evidence"]},
        "metrics": {"REVENUE": {"concepts": ["us-gaap:Revenues"], "unit": "USD", "context": "consolidated", "period": "duration", "selection": "latest_filed_same_basis", "evidence": ["filing-evidence"]}},
        "segments": {"parser": "not_applicable", "axes": [], "reconciliation": "not_applicable", "revenue_concept": None, "profit_concept": None, "evidence": ["filing-evidence"]},
        "cash_debt": {"cash_components": ["us-gaap:CashAndCashEquivalentsAtCarryingValue"], "debt_components": ["us-gaap:LongTermDebtNoncurrent"], "restricted_cash_policy": "separate", "evidence": ["filing-evidence"]},
        "eps_method": "reported_diluted", "eps_method_evidence": ["filing-evidence"],
        "securities": [{"ticker": "ONE", "exchange": "NYSE", "currency": "USD", "instrument_type": "COMMON_STOCK", "evidence": ["filing-evidence"]}],
        "applicability": {"EPS": "required", "SEGMENTS": "not_applicable", "VALUATION": "required"},
        "applicability_evidence": {"SEGMENTS": ["filing-evidence"]}, "evidence": [evidence],
    }
    profile_id = PublicationRepository(db).create_profile(
        CIK, version=2, schema_version=2, content=profile
    )
    bound = repository.set_candidate(
        current.onboarding_id,
        expected_revision=current.revision,
        profile_id=profile_id,
        state=TaskState.BUILDING,
        current_step=current.current_step,
    )

    assert runner.run_once()
    built = repository.get(bound.onboarding_id)
    raw_rows = db.query(
        "SELECT payload_json FROM dataset_row WHERE dataset_id=? AND entity_type='raw_fact'",
        [built.dataset_id],
    )
    parsed = [json.loads(row["payload_json"]) for row in raw_rows]
    assert parsed
    assert {row["raw_value"] for row in parsed} == {100.0}
    assert all(row["context_id"] == "ctx" and row["locator"].startswith("/") for row in parsed)
    assert all(row["source_document_id"].startswith("filing:") for row in parsed)
    source_rows = db.query(
        "SELECT payload_json FROM dataset_row WHERE dataset_id=? AND entity_type='source_document'",
        [built.dataset_id],
    )
    sources = [json.loads(row["payload_json"]) for row in source_rows]
    published_filing = next(
        row for row in sources if row["source_document_id"] == filing.document_id
    )
    assert published_filing["filed_at"] == filing.filed_at.isoformat()
    assert published_filing["report_date"] == filing.report_date.isoformat()


def test_configured_pipeline_fetches_builds_and_validates(db, tmp_path):
    submissions, companyfacts = _payloads()
    profile_root = tmp_path / "profiles"
    profile_path = profile_root / CIK / "1.yaml"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(yaml.safe_dump(_profile(), sort_keys=False))

    def fetch(url: str):
        if "submissions" in url:
            content = json.dumps(submissions).encode()
        elif "companyfacts" in url:
            content = json.dumps(companyfacts).encode()
        else:
            content = _ixbrl_revenue()
        return content, {"fetched_at": "2026-09-12T00:00:00+00:00"}

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
    assert paused.profile_candidate_id
    candidate = repository.get_profile_candidate(paused.profile_candidate_id)
    assert candidate.fetch_bundle_id == paused.fetch_bundle_id
    assert candidate.profile["schema_version"] == 2
    assert candidate.review_status == "NEEDS_ADAPTATION"
    assert candidate.unresolved_fields
    assert repository.list_events(task.onboarding_id)[-1].event_type == "PROFILE_CANDIDATE_CREATED"
    assert db.query_one(
        "SELECT count(*) AS n FROM issuer_profile_candidate WHERE onboarding_id=?",
        [task.onboarding_id],
    )["n"] == 1


def test_installed_profile_with_stale_evidence_pauses_for_new_candidate(db, tmp_path):
    submissions, companyfacts = _payloads()

    def fetch(url: str):
        if "submissions" in url:
            content = json.dumps(submissions).encode()
        elif "companyfacts" in url:
            content = json.dumps(companyfacts).encode()
        else:
            content = _ixbrl_revenue()
        return content, {"fetched_at": "2026-09-12T00:00:00+00:00"}

    repository = OnboardingRepository(db)
    task = repository.create_task(
        company_id=CIK, security_id=_register(db), input_fingerprint="stale-profile"
    )
    profile_root = tmp_path / "profiles"
    pipeline = OnboardingPipeline(
        db, repository, raw_dir=tmp_path / "raw", profile_root=profile_root, fetcher=fetch
    )
    runner = OnboardingRunner(db, repository, handlers=pipeline.handlers())
    assert runner.run_once() is True
    bundle = repository.get_fetch_bundle(repository.get(task.onboarding_id).fetch_bundle_id)
    stale = _profile_v2_for_bundle(bundle, 1)
    stale["evidence"][0]["content_sha256"] = "f" * 64
    path = profile_root / CIK / "1.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(stale, sort_keys=False))

    assert runner.run_once() is True
    paused = repository.get(task.onboarding_id)
    assert paused.state == TaskState.NEEDS_ADAPTATION
    assert paused.profile_candidate_id
    assert paused.profile_id is None
    assert paused.actions == ["CANCEL", "PROFILE_IMPORT"]


def test_profile_import_after_pause_rebuilds_instead_of_skipping_build(db, tmp_path):
    submissions, companyfacts = _payloads()

    def fetch(url: str):
        if "submissions" in url:
            content = json.dumps(submissions).encode()
        elif "companyfacts" in url:
            content = json.dumps(companyfacts).encode()
        else:
            content = _ixbrl_revenue()
        return content, {"fetched_at": "2026-09-12T00:00:00+00:00"}

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

    bundle = repository.get_fetch_bundle(paused.fetch_bundle_id)
    imported = IssuerProfileService(PublicationRepository(db), repository).import_profile(
        task.onboarding_id, paused.revision, _profile_v2_for_bundle(bundle, 1)
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
        if "submissions" in url:
            content = json.dumps(submissions).encode()
        elif "companyfacts" in url:
            content = json.dumps(companyfacts).encode()
        else:
            content = _ixbrl_revenue()
        return content, {"fetched_at": "2026-09-12T00:00:00+00:00"}

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
    revised = _profile_v2_for_bundle(repository.get_fetch_bundle(paused.fetch_bundle_id), 2)
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
