from __future__ import annotations

import json

import pytest

from equitylens.onboarding.repository import OnboardingRepository
from equitylens.onboarding.pipeline import OnboardingPipeline
from equitylens.onboarding.runner import OnboardingRunner
from equitylens.publication.builder import DatasetBuilder
from equitylens.publication.repository import PublicationRepository
from equitylens.issuers.review import ReviewConflict, ReviewService
from equitylens.issuers.profile import IssuerProfileService


def _profile(company_id: str, version: int) -> dict:
    return {
        "schema_version": 1,
        "company_id": company_id,
        "version": version,
        "template": "us_gaap_operating_v1",
        "fiscal_calendar": {"year_end": "09-30", "week_based": True},
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
                "ticker": "AAPL",
                "exchange": "NASDAQ",
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


def _fact(company_id: str, value: float, fact_id: str) -> dict:
    return {
        "canonical_fact_id": fact_id,
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
    }


@pytest.fixture()
def review_case(db):
    company_id = "0000320193"
    security_id = db.query_one(
        "SELECT security_id FROM security WHERE company_id=?", [company_id]
    )["security_id"]
    tasks = OnboardingRepository(db)
    task = tasks.create_task(
        company_id=company_id,
        security_id=security_id,
        input_fingerprint="review-input",
    )
    publications = PublicationRepository(db)
    builder = DatasetBuilder(db)

    def install_candidate(version: int, revenue: float, result: str = "PASS"):
        profile = _profile(company_id, version)
        profile_id = publications.create_profile(
            company_id,
            version=version,
            schema_version=1,
            content=profile,
        )
        dataset_id = builder.seal_rows(
            company_id=company_id,
            profile_id=profile_id,
            source_manifest={
                "documents": [
                    {
                        "source_document_id": "doc-1",
                        "local_path": "/private/should-not-be-exported",
                        "content_sha256": "a" * 64,
                    }
                ]
            },
            rows=[("canonical_fact", f"fact-{version}", _fact(company_id, revenue, f"fact-{version}"))],
        )
        report_id = f"report-{version}"
        db._conn.execute(
            "INSERT INTO quality_report VALUES (?, ?, 'fixture-v1', ?, ?, now())",
            [report_id, dataset_id, result, f"quality-{version}"],
        )
        db._conn.execute(
            """
            UPDATE company_onboarding SET profile_id=?, dataset_id=?, quality_report_id=?,
              state='NEEDS_REVIEW', current_step='PUBLISH', revision=revision+1,
              updated_at=now() WHERE onboarding_id=?
            """,
            [profile_id, dataset_id, report_id, task.onboarding_id],
        )
        return tasks.get(task.onboarding_id)

    current = install_candidate(101, 100)
    service = ReviewService(db, tasks, publications, publish_immediately=False)

    class Case:
        def approve_current(self):
            current_task = tasks.get(task.onboarding_id)
            fingerprint = publications.publication_fingerprint(
                company_id=company_id,
                dataset_id=current_task.dataset_id,
                profile_id=current_task.profile_id,
                quality_report_id=current_task.quality_report_id,
            )
            return service.review(
                task.onboarding_id,
                expected_revision=current_task.revision,
                fingerprint=fingerprint,
                decision="APPROVE",
                reviewer="maintainer",
                note="fixture approval",
            )

        def change_profile_and_rebuild(self):
            return install_candidate(102, 999)

        def publish_with(self, approval):
            current_task = tasks.get(task.onboarding_id)
            return service.publish_approved(
                task.onboarding_id,
                expected_revision=current_task.revision,
                review_id=approval.review_id,
            )

    return Case(), service, tasks, publications, task.onboarding_id, install_candidate


def test_old_approval_cannot_publish_new_candidate(review_case):
    case, *_ = review_case
    approval = case.approve_current()
    case.change_profile_and_rebuild()

    with pytest.raises(ReviewConflict) as exc:
        case.publish_with(approval)
    assert exc.value.code == "REVIEW_STALE"


def test_quality_failure_cannot_be_approved(review_case):
    _, service, tasks, publications, task_id, install_candidate = review_case
    task = install_candidate(103, 50, result="FAIL")
    fingerprint = publications.publication_fingerprint(
        company_id=task.company_id,
        dataset_id=task.dataset_id,
        profile_id=task.profile_id,
        quality_report_id=task.quality_report_id,
    )

    with pytest.raises(ReviewConflict) as exc:
        service.review(
            task_id,
            expected_revision=task.revision,
            fingerprint=fingerprint,
            decision="APPROVE",
            reviewer="maintainer",
            note="must fail",
        )
    assert exc.value.code == "QUALITY_BLOCKED"


def test_review_package_is_fixed_and_does_not_export_arbitrary_paths(review_case):
    _, service, _, _, task_id, _ = review_case

    package = service.review_package(task_id)

    assert package["dataset_hash"]
    assert package["profile_hash"]
    assert package["quality"]["result"] == "PASS"
    serialized = json.dumps(package)
    assert "/private/should-not-be-exported" not in serialized


def test_approved_review_publishes_exact_candidate(review_case):
    _, service, tasks, publications, task_id, _ = review_case
    service.publish_immediately = True
    task = tasks.get(task_id)
    fingerprint = publications.publication_fingerprint(
        company_id=task.company_id,
        dataset_id=task.dataset_id,
        profile_id=task.profile_id,
        quality_report_id=task.quality_report_id,
    )

    approval = service.review(
        task_id,
        expected_revision=task.revision,
        fingerprint=fingerprint,
        decision="APPROVE",
        reviewer="maintainer",
        note="publish",
    )

    published = tasks.get(task_id)
    assert published.state.value == "PUBLISHED"
    assert publications.context(task.company_id).dataset_id == task.dataset_id
    assert approval.fingerprint == fingerprint


def test_durable_runner_retries_approved_publication(review_case):
    case, _, tasks, publications, task_id, _ = review_case
    approval = case.approve_current()
    task = tasks.get(task_id)
    assert task.state.value == "PUBLISHING"

    pipeline = OnboardingPipeline(tasks.store, tasks)
    runner = OnboardingRunner(tasks.store, tasks, handlers=pipeline.handlers())

    assert runner.run_once() is True
    published = tasks.get(task_id)
    assert published.state.value == "PUBLISHED"
    assert published.review_id == approval.review_id
    assert publications.context(task.company_id).dataset_id == task.dataset_id


def test_profile_import_is_immutable_and_invalidates_candidate(review_case):
    _, _, tasks, publications, task_id, _ = review_case
    task = tasks.get(task_id)
    imported = IssuerProfileService(publications, tasks).import_profile(
        task_id,
        task.revision,
        _profile(task.company_id, 104),
    )

    assert imported.state.value == "BUILDING"
    assert imported.current_step.value == "BUILD"
    assert imported.profile_id
    assert imported.dataset_id is None
    assert imported.quality_report_id is None
    assert imported.review_id is None


def test_maintainer_review_command_calls_api_without_database_fallback(monkeypatch):
    from equitylens import cli

    calls = []

    def request(method, path, *, json_body=None):
        calls.append((method, path, json_body))
        return {"state": "PUBLISHED"}

    monkeypatch.setattr(cli, "_onboarding_request", request)
    result = cli.main(
        [
            "onboarding",
            "review",
            "task-1",
            "--fingerprint",
            "abc",
            "--revision",
            "7",
            "--reviewer",
            "maintainer",
            "--decision",
            "APPROVE",
            "--note",
            "verified",
        ]
    )

    assert result == 0
    assert calls == [
        (
            "POST",
            "/company-onboardings/task-1/review",
            {
                "expected_revision": 7,
                "fingerprint": "abc",
                "decision": "APPROVE",
                "reviewer": "maintainer",
                "note": "verified",
            },
        )
    ]


def test_maintainer_review_command_requires_explicit_decision(monkeypatch):
    from equitylens import cli

    monkeypatch.setattr(
        cli,
        "_onboarding_request",
        lambda *args, **kwargs: pytest.fail("review request must not be sent"),
    )

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "onboarding",
                "review",
                "task-1",
                "--fingerprint",
                "abc",
                "--revision",
                "7",
                "--reviewer",
                "maintainer",
            ]
        )

    assert exc.value.code == 2
