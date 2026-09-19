from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

import pytest

from equitylens.onboarding.models import OnboardingStep, TaskState
from equitylens.onboarding.repository import OnboardingConflict, OnboardingRepository
from equitylens.onboarding.runner import OnboardingRunner
from equitylens.storage.writer import DatabaseWriter, WriterBusy, writer_for


@pytest.fixture()
def runner_case(db):
    repository = OnboardingRepository(db)
    task = repository.create_task(
        company_id="0000320193",
        security_id=db.query_one(
            "SELECT security_id FROM security WHERE company_id='0000320193'"
        )["security_id"],
        input_fingerprint="fixture-input",
    )
    calls = {OnboardingStep.FETCH: 0}

    def fetch(_task):
        calls[OnboardingStep.FETCH] += 1
        return {"manifest_hash": "fetched-once"}

    class Case:
        def __init__(self):
            self.repository = repository
            self.task = task
            self.runner = OnboardingRunner(db, repository, {OnboardingStep.FETCH: fetch})

        @property
        def fetch_call_count(self):
            return calls[OnboardingStep.FETCH]

        def persist_completed_fetch(self):
            db._conn.execute(
                "UPDATE company_onboarding SET state='FETCHING', current_step='FETCH' "
                "WHERE onboarding_id=?",
                [task.onboarding_id],
            )
            attempt_id = repository.begin_attempt(repository.get(task.onboarding_id))
            db._conn.execute(
                """
                UPDATE onboarding_step_attempt SET output_hash='fetched-once',
                  state='COMPLETED', finished_at=now(), heartbeat_at=now()
                WHERE attempt_id=?
                """,
                [attempt_id],
            )

        def restart(self):
            self.runner = OnboardingRunner(
                db, repository, {OnboardingStep.FETCH: fetch}
            )

    return Case()


def test_restart_does_not_duplicate_completed_step(runner_case):
    runner_case.persist_completed_fetch()
    runner_case.restart()
    runner_case.runner.recover_interrupted()
    runner_case.runner.run_once()

    assert runner_case.fetch_call_count == 0
    task = runner_case.repository.get(runner_case.task.onboarding_id)
    assert task.current_step == OnboardingStep.BUILD
    assert task.state == TaskState.BUILDING


def test_expected_revision_rejects_stale_cancel(db):
    repository = OnboardingRepository(db)
    security_id = db.query_one(
        "SELECT security_id FROM security WHERE company_id='0000320193'"
    )["security_id"]
    task = repository.create_task(
        company_id="0000320193",
        security_id=security_id,
        input_fingerprint="revision-fixture",
    )
    updated = repository.cancel(task.onboarding_id, expected_revision=task.revision)
    assert updated.state == TaskState.CANCELLED

    with pytest.raises(OnboardingConflict) as exc:
        repository.cancel(task.onboarding_id, expected_revision=task.revision)
    assert exc.value.code == "TASK_CONFLICT"


def test_cancel_records_pre_cancel_progress_snapshot(db):
    repository = OnboardingRepository(db)
    security_id = db.query_one(
        "SELECT security_id FROM security WHERE company_id='0000320193'"
    )["security_id"]
    task = repository.create_task(
        company_id="0000320193", security_id=security_id,
        input_fingerprint="cancel-progress",
    )
    cancelled = repository.cancel(task.onboarding_id, expected_revision=task.revision)
    event = repository.list_events(task.onboarding_id)[-1]
    progress = repository.progress(cancelled)

    assert event.event_type == "TASK_CANCELLED"
    assert event.payload["progress_snapshot"]["current_stage"] == "FETCH"
    assert progress.activity == "CANCELLED"
    assert progress.completed == event.payload["progress_snapshot"]["completed"]


def test_runner_updates_heartbeat_while_handler_is_running(db):
    repository = OnboardingRepository(db)
    security_id = db.query_one(
        "SELECT security_id FROM security WHERE company_id='0000320193'"
    )["security_id"]
    task = repository.create_task(
        company_id="0000320193", security_id=security_id,
        input_fingerprint="heartbeat-fixture",
    )
    entered = threading.Event()
    release = threading.Event()

    def slow_fetch(_task):
        entered.set()
        assert release.wait(2)
        return {"ok": True}

    runner = OnboardingRunner(
        db, repository, {OnboardingStep.FETCH: slow_fetch}, heartbeat_seconds=0.01
    )
    thread = threading.Thread(target=runner.run_once)
    thread.start()
    assert entered.wait(1)
    time.sleep(0.04)
    attempt = db.query_one(
        "SELECT started_at, heartbeat_at FROM onboarding_step_attempt WHERE onboarding_id=?",
        [task.onboarding_id],
    )
    release.set()
    thread.join(2)

    assert attempt["heartbeat_at"] > attempt["started_at"]
    assert not thread.is_alive()


def test_same_issuer_reuses_active_task(db):
    repository = OnboardingRepository(db)
    security_id = db.query_one(
        "SELECT security_id FROM security WHERE company_id='0000320193'"
    )["security_id"]
    first = repository.create_task(
        company_id="0000320193",
        security_id=security_id,
        input_fingerprint="same-issuer",
    )
    second = repository.create_task(
        company_id="0000320193",
        security_id=security_id,
        input_fingerprint="same-issuer",
    )

    assert second.onboarding_id == first.onboarding_id


def test_fetch_bundle_is_immutable_and_bound_atomically(db):
    repository = OnboardingRepository(db)
    security_id = db.query_one(
        "SELECT security_id FROM security WHERE company_id='0000320193'"
    )["security_id"]
    task = repository.create_task(
        company_id="0000320193",
        security_id=security_id,
        input_fingerprint="bundle-fixture",
    )
    documents = [
        {
            "document_id": "submissions-sha",
            "document_type": "SUBMISSIONS",
            "accession_number": None,
            "form_type": None,
            "filed_at": None,
            "report_date": None,
            "fetched_at": datetime(2026, 9, 19, tzinfo=timezone.utc),
            "source_url": "https://data.sec.gov/submissions/CIK0000320193.json",
            "content_sha256": "a" * 64,
            "raw_locator": "sec/0000320193/submissions.aaaaaaaa.json",
        }
    ]

    bundle = repository.create_fetch_bundle(
        task.onboarding_id,
        expected_revision=task.revision,
        fetcher_version="sec-v1",
        parser_version="ixbrl-v1",
        documents=documents,
    )
    current = repository.get(task.onboarding_id)
    loaded = repository.get_fetch_bundle(bundle.fetch_bundle_id)

    assert current.fetch_bundle_id == bundle.fetch_bundle_id
    assert current.revision == task.revision + 1
    assert loaded == bundle
    assert loaded.documents[0].raw_locator == documents[0]["raw_locator"]
    assert repository.list_events(task.onboarding_id)[0].event_type == "FETCH_BUNDLE_ACTIVATED"

    replay = repository.create_fetch_bundle(
        task.onboarding_id,
        expected_revision=current.revision,
        fetcher_version="sec-v1",
        parser_version="ixbrl-v1",
        documents=documents,
    )
    assert replay.fetch_bundle_id == bundle.fetch_bundle_id
    assert repository.get(task.onboarding_id).revision == current.revision

    changed = [{**documents[0], "content_sha256": "b" * 64}]
    with pytest.raises(OnboardingConflict) as exc:
        repository.create_fetch_bundle(
            task.onboarding_id,
            expected_revision=task.revision,
            fetcher_version="sec-v1",
            parser_version="ixbrl-v1",
            documents=changed,
        )
    assert exc.value.code == "TASK_CONFLICT"


def test_cancel_requested_at_running_boundary_becomes_cancelled(db):
    repository = OnboardingRepository(db)
    security_id = db.query_one(
        "SELECT security_id FROM security WHERE company_id='0000320193'"
    )["security_id"]
    task = repository.create_task(
        company_id="0000320193",
        security_id=security_id,
        input_fingerprint="cancel-boundary",
    )
    db._conn.execute(
        "UPDATE company_onboarding SET state='PUBLISHING', current_step='PUBLISH' WHERE onboarding_id=?",
        [task.onboarding_id],
    )
    current = repository.get(task.onboarding_id)
    repository.cancel(task.onboarding_id, expected_revision=current.revision)

    assert OnboardingRunner(db, repository).run_once()
    assert repository.get(task.onboarding_id).state == TaskState.CANCELLED


def test_retryable_step_stops_after_three_total_attempts(db):
    repository = OnboardingRepository(db)
    security_id = db.query_one(
        "SELECT security_id FROM security WHERE company_id='0000320193'"
    )["security_id"]
    task = repository.create_task(
        company_id="0000320193",
        security_id=security_id,
        input_fingerprint="retry-cap",
    )

    def unavailable(_task):
        error = RuntimeError("source unavailable")
        error.retryable = True
        raise error

    runner = OnboardingRunner(db, repository, {OnboardingStep.FETCH: unavailable})
    for _ in range(3):
        assert runner.run_once()
        db._conn.execute(
            "UPDATE company_onboarding SET next_attempt_at=NULL WHERE onboarding_id=?",
            [task.onboarding_id],
        )

    final = repository.get(task.onboarding_id)
    assert final.state == TaskState.FAILED
    assert db.query_one(
        "SELECT count(*) AS n FROM onboarding_step_attempt WHERE onboarding_id=?",
        [task.onboarding_id],
    )["n"] == 3


def test_untyped_deterministic_failure_is_not_retried(db):
    repository = OnboardingRepository(db)
    security_id = db.query_one(
        "SELECT security_id FROM security WHERE company_id='0000320193'"
    )["security_id"]
    task = repository.create_task(
        company_id="0000320193",
        security_id=security_id,
        input_fingerprint="deterministic-failure",
    )

    def invalid_profile(_task):
        raise ValueError("invalid profile")

    runner = OnboardingRunner(
        db, repository, {OnboardingStep.FETCH: invalid_profile}
    )
    assert runner.run_once()

    failed = repository.get(task.onboarding_id)
    assert failed.state == TaskState.FAILED
    assert failed.error["retryable"] is False


def test_revised_profile_gets_a_fresh_retry_budget(db):
    from equitylens.issuers.profile import IssuerProfileService
    from equitylens.publication.repository import PublicationRepository

    repository = OnboardingRepository(db)
    security_id = db.query_one(
        "SELECT security_id FROM security WHERE company_id='0000320193'"
    )["security_id"]
    task = repository.create_task(
        company_id="0000320193",
        security_id=security_id,
        input_fingerprint="profile-retry-generation",
    )
    digest = "e" * 64
    repository.create_fetch_bundle(
        task.onboarding_id,
        expected_revision=task.revision,
        fetcher_version="fixture",
        parser_version="fixture",
        documents=[{
            "document_id": "filing:retry", "document_type": "FILING_DOCUMENT",
            "accession_number": "retry", "form_type": "10-K",
            "filed_at": "2026-01-01", "report_date": "2025-09-30",
            "fetched_at": "2026-01-01T00:00:00Z",
            "source_url": "https://www.sec.gov/retry", "content_sha256": digest,
            "raw_locator": "sec/retry/primary.html",
        }],
    )
    db._conn.execute(
        "UPDATE company_onboarding SET state='NEEDS_ADAPTATION', current_step='BUILD' WHERE onboarding_id=?",
        [task.onboarding_id],
    )
    for number in range(1, 4):
        db._conn.execute(
            """
            INSERT INTO onboarding_step_attempt
              (attempt_id, onboarding_id, step, attempt_no, input_hash, state, started_at, finished_at)
            VALUES (?, ?, 'BUILD', ?, 'old-profile-input', 'FAILED', now(), now())
            """,
            [f"old-{number}", task.onboarding_id, number],
        )
    current = repository.get(task.onboarding_id)
    evidence = ["filing-evidence"]
    revised = {
        "schema_version": 2, "company_id": "0000320193", "version": 88,
        "template": "us_gaap_operating_v1", "template_evidence": evidence,
        "fiscal_calendar": {"year_end": "09-30", "week_based": True, "evidence": evidence},
        "metrics": {"REVENUE": {"concepts": ["us-gaap:Revenues"], "unit": "USD", "context": "consolidated", "period": "duration", "selection": "latest_filed_same_basis", "evidence": evidence}},
        "segments": {"parser": "not_applicable", "axes": [], "reconciliation": "not_applicable", "revenue_concept": None, "profit_concept": None, "evidence": evidence},
        "cash_debt": {"cash_components": ["us-gaap:CashAndCashEquivalentsAtCarryingValue"], "debt_components": ["us-gaap:LongTermDebtNoncurrent"], "restricted_cash_policy": "separate", "evidence": evidence},
        "eps_method": "reported_diluted", "eps_method_evidence": evidence,
        "securities": [{"ticker": "AAPL", "exchange": "NASDAQ", "currency": "USD", "instrument_type": "COMMON_STOCK", "evidence": evidence}],
        "applicability": {"EPS": "required", "SEGMENTS": "not_applicable", "VALUATION": "required"},
        "applicability_evidence": {"SEGMENTS": evidence},
        "evidence": [{"evidence_id": "filing-evidence", "source_document_id": "filing:retry", "content_sha256": digest, "locator": "/html"}],
    }
    imported = IssuerProfileService(PublicationRepository(db), repository).import_profile(
        task.onboarding_id, current.revision, revised
    )

    def transient(_task):
        error = RuntimeError("temporary")
        error.retryable = True
        raise error

    OnboardingRunner(db, repository, {OnboardingStep.BUILD: transient}).run_once()

    assert repository.get(task.onboarding_id).state == TaskState.BUILDING


def test_second_process_writer_is_rejected(tmp_path):
    database = tmp_path / "writer.duckdb"
    writer = DatabaseWriter(database)
    writer.start()
    code = """
from pathlib import Path
import sys
from equitylens.storage.writer import DatabaseWriter, WriterBusy
try:
    DatabaseWriter(Path(sys.argv[1])).start()
except WriterBusy:
    raise SystemExit(23)
raise SystemExit(0)
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", code, str(database)], check=False
        )
        assert result.returncode == 23
    finally:
        writer.close()


def test_refresh_and_valuation_writes_are_serialized(db, monkeypatch, tmp_path):
    from equitylens.refresh import service as refresh_service
    from equitylens.valuation.service import _persist_run

    entered_refresh = threading.Event()
    release_refresh = threading.Event()
    valuation_finished = threading.Event()
    stable = {module: None for module in refresh_service.MODULES}

    monkeypatch.setattr(refresh_service, "_identity_snapshot", lambda *_: stable)

    def slow_module(*_args, **_kwargs):
        entered_refresh.set()
        assert release_refresh.wait(2)
        return {}

    monkeypatch.setattr(refresh_service, "_run_module", slow_module)
    refresh_thread = threading.Thread(
        target=refresh_service.refresh_company,
        args=(db, "AAPL"),
        kwargs={"modules": ["financials"], "raw_dir": tmp_path / "raw"},
    )
    refresh_thread.start()
    assert entered_refresh.wait(2)

    run = {
        "valuation_run_id": "serialized-run",
        "company_id": "0000320193",
        "model_name": "FCFF_DCF",
        "model_version": "fixture",
        "run_at": "2026-09-11T00:00:00",
        "market_observation_id": None,
        "assumption_set_id": "fixture",
        "fact_snapshot_json": "{}",
        "output_json": "{}",
        "warnings_json": "[]",
        "input_fingerprint": "fixture",
        "scenarios_json": "{}",
        "sensitivity_json": "{}",
        "model_quality_json": "{}",
    }

    def save_valuation():
        _persist_run(db, run)
        valuation_finished.set()

    valuation_thread = threading.Thread(target=save_valuation)
    valuation_thread.start()
    time.sleep(0.05)
    assert not valuation_finished.is_set()
    release_refresh.set()
    refresh_thread.join(2)
    valuation_thread.join(2)

    assert valuation_finished.is_set()
    assert db.query_one(
        "SELECT valuation_run_id FROM valuation_run WHERE valuation_run_id='serialized-run'"
    ) == {"valuation_run_id": "serialized-run"}
