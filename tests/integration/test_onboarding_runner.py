from __future__ import annotations

import json
import subprocess
import sys
import threading
import time

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
    from equitylens.issuers.profile import IssuerProfileService, load_profile_yaml
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
    revised = load_profile_yaml("config/issuers/0000320193/2.yaml").model_dump(
        mode="json", exclude={"content_sha256"}
    )
    revised["version"] = 88
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
