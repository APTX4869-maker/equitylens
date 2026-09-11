"""Durable onboarding tasks with optimistic revision checks."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from equitylens.onboarding.models import (
    ACTIVE_STATES,
    OnboardingStep,
    TaskState,
    TaskView,
)
from equitylens.storage.duckdb_store import DuckDBStore
from equitylens.storage.writer import writer_for


class OnboardingConflict(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _json(value: Any) -> str | None:
    return json.dumps(value, ensure_ascii=False, sort_keys=True) if value is not None else None


class OnboardingRepository:
    def __init__(self, store: DuckDBStore) -> None:
        self.store = store
        self.store.connect()
        self.writer = writer_for(store)

    def create_task(
        self, *, company_id: str, security_id: str, input_fingerprint: str
    ) -> TaskView:
        with self.writer.transaction(self.store):
            placeholders = ",".join("?" for _ in ACTIVE_STATES)
            active = self.store._conn.execute(
                f"""
                SELECT onboarding_id FROM company_onboarding
                WHERE company_id = ? AND state IN ({placeholders})
                ORDER BY created_at DESC LIMIT 1
                """,
                [company_id, *[state.value for state in ACTIVE_STATES]],
            ).fetchone()
            if active:
                self.store._conn.execute(
                    "INSERT OR IGNORE INTO onboarding_security VALUES (?, ?)",
                    [active[0], security_id],
                )
                task_id = active[0]
            else:
                task_id = str(uuid.uuid4())
                self.store._conn.execute(
                    """
                    INSERT INTO company_onboarding (
                      onboarding_id, company_id, state, current_step, revision,
                      cancel_requested, input_fingerprint, error_json,
                      next_attempt_at, created_at, updated_at
                    ) VALUES (?, ?, 'QUEUED', 'FETCH', 1, false, ?, NULL, NULL, now(), now())
                    """,
                    [task_id, company_id, input_fingerprint],
                )
                self.store._conn.execute(
                    "INSERT INTO onboarding_security VALUES (?, ?)",
                    [task_id, security_id],
                )
        return self.get(task_id)

    def get(self, task_id: str) -> TaskView:
        row = self.store.query_one(
            "SELECT * FROM company_onboarding WHERE onboarding_id = ?", [task_id]
        )
        if row is None:
            raise KeyError(task_id)
        error = row.get("error_json")
        if isinstance(error, str):
            error = json.loads(error)
        state = TaskState(row["state"])
        actions = []
        if state == TaskState.FAILED:
            actions.append("retry")
        if state not in (TaskState.PUBLISHED, TaskState.CANCELLED):
            actions.append("cancel")
        if state == TaskState.NEEDS_REVIEW:
            actions.extend(["review", "export_review_package"])
        if state == TaskState.NEEDS_ADAPTATION:
            actions.extend(["profile_import", "export_review_package"])
        return TaskView(
            onboarding_id=row["onboarding_id"],
            company_id=row["company_id"],
            state=state,
            current_step=OnboardingStep(row["current_step"])
            if row.get("current_step")
            else None,
            revision=row["revision"],
            cancel_requested=row["cancel_requested"],
            input_fingerprint=row["input_fingerprint"],
            error=error,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            actions=actions,
        )

    def runnable(self) -> TaskView | None:
        row = self.store.query_one(
            """
            SELECT onboarding_id FROM company_onboarding
            WHERE state IN ('QUEUED','FETCHING','BUILDING','VALIDATING','PUBLISHING')
              AND (next_attempt_at IS NULL OR next_attempt_at <= now())
            ORDER BY created_at LIMIT 1
            """
        )
        return self.get(row["onboarding_id"]) if row else None

    def cancel(self, task_id: str, *, expected_revision: int) -> TaskView:
        with self.writer.transaction(self.store):
            row = self.store._conn.execute(
                "SELECT state, revision FROM company_onboarding WHERE onboarding_id = ?",
                [task_id],
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            if row[1] != expected_revision or row[0] in ("PUBLISHED", "CANCELLED"):
                raise OnboardingConflict("TASK_CONFLICT", "task revision or state changed")
            running = row[0] in ("FETCHING", "BUILDING", "VALIDATING", "PUBLISHING")
            self.store._conn.execute(
                """
                UPDATE company_onboarding
                SET cancel_requested=true, state=?, revision=revision+1, updated_at=now()
                WHERE onboarding_id=?
                """,
                [row[0] if running else "CANCELLED", task_id],
            )
        return self.get(task_id)

    def retry(self, task_id: str, *, expected_revision: int) -> TaskView:
        with self.writer.transaction(self.store):
            row = self.store._conn.execute(
                "SELECT state, revision FROM company_onboarding WHERE onboarding_id=?",
                [task_id],
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            if row[0] != "FAILED" or row[1] != expected_revision:
                raise OnboardingConflict("TASK_CONFLICT", "failed task revision changed")
            self.store._conn.execute(
                """
                UPDATE company_onboarding SET state=?, error_json=NULL,
                  next_attempt_at=NULL, revision=revision+1, updated_at=now()
                WHERE onboarding_id=?
                """,
                [self._state_for_step(self.get(task_id).current_step).value, task_id],
            )
        return self.get(task_id)

    def finalize_cancel(self, task_id: str) -> TaskView:
        with self.writer.transaction(self.store):
            row = self.store._conn.execute(
                "SELECT cancel_requested, state FROM company_onboarding WHERE onboarding_id=?",
                [task_id],
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            if not row[0] or row[1] == "PUBLISHED":
                raise OnboardingConflict("TASK_CONFLICT", "task cannot be cancelled")
            self.store._conn.execute(
                """
                UPDATE company_onboarding SET state='CANCELLED', current_step=NULL,
                  revision=revision+1, updated_at=now() WHERE onboarding_id=?
                """,
                [task_id],
            )
        return self.get(task_id)

    @staticmethod
    def _state_for_step(step: OnboardingStep | None) -> TaskState:
        return {
            OnboardingStep.FETCH: TaskState.FETCHING,
            OnboardingStep.BUILD: TaskState.BUILDING,
            OnboardingStep.VALIDATE: TaskState.VALIDATING,
            OnboardingStep.PUBLISH: TaskState.PUBLISHING,
        }.get(step, TaskState.QUEUED)

    def completed_attempt(self, task: TaskView) -> dict | None:
        if task.current_step is None:
            return None
        return self.store.query_one(
            """
            SELECT * FROM onboarding_step_attempt
            WHERE onboarding_id=? AND step=? AND input_hash=? AND state='COMPLETED'
            ORDER BY attempt_no DESC LIMIT 1
            """,
            [task.onboarding_id, task.current_step.value, task.input_fingerprint],
        )

    def begin_attempt(self, task: TaskView) -> str:
        attempt_id = str(uuid.uuid4())
        with self.writer.transaction(self.store):
            attempt_no = self.store._conn.execute(
                """
                SELECT coalesce(max(attempt_no), 0) + 1 FROM onboarding_step_attempt
                WHERE onboarding_id=? AND step=?
                """,
                [task.onboarding_id, task.current_step.value],
            ).fetchone()[0]
            self.store._conn.execute(
                """
                INSERT INTO onboarding_step_attempt (
                  attempt_id, onboarding_id, step, attempt_no, input_hash, state,
                  started_at, heartbeat_at
                ) VALUES (?, ?, ?, ?, ?, 'RUNNING', now(), now())
                """,
                [
                    attempt_id,
                    task.onboarding_id,
                    task.current_step.value,
                    attempt_no,
                    task.input_fingerprint,
                ],
            )
            self.store._conn.execute(
                "UPDATE company_onboarding SET state=?, updated_at=now() WHERE onboarding_id=?",
                [self._state_for_step(task.current_step).value, task.onboarding_id],
            )
        return attempt_id

    def complete_attempt(self, task: TaskView, attempt_id: str, output_hash: str) -> TaskView:
        with self.writer.transaction(self.store):
            self.store._conn.execute(
                """
                UPDATE onboarding_step_attempt SET state='COMPLETED', output_hash=?,
                  finished_at=now(), heartbeat_at=now() WHERE attempt_id=?
                """,
                [output_hash, attempt_id],
            )
            self._advance_locked(task.onboarding_id, task.current_step)
        return self.get(task.onboarding_id)

    def advance_completed(self, task: TaskView) -> TaskView:
        with self.writer.transaction(self.store):
            self._advance_locked(task.onboarding_id, task.current_step)
        return self.get(task.onboarding_id)

    def _advance_locked(self, task_id: str, step: OnboardingStep | None) -> None:
        next_step, state = {
            OnboardingStep.FETCH: (OnboardingStep.BUILD, TaskState.BUILDING),
            OnboardingStep.BUILD: (OnboardingStep.VALIDATE, TaskState.VALIDATING),
            OnboardingStep.VALIDATE: (OnboardingStep.PUBLISH, TaskState.NEEDS_REVIEW),
            OnboardingStep.PUBLISH: (None, TaskState.PUBLISHED),
        }[step]
        self.store._conn.execute(
            """
            UPDATE company_onboarding SET current_step=?, state=?, revision=revision+1,
              error_json=NULL, next_attempt_at=NULL, updated_at=now()
            WHERE onboarding_id=?
            """,
            [next_step.value if next_step else None, state.value, task_id],
        )

    def fail_attempt(
        self, task: TaskView, attempt_id: str, error: dict[str, Any], *, retryable: bool
    ) -> None:
        with self.writer.transaction(self.store):
            self.store._conn.execute(
                """
                UPDATE onboarding_step_attempt SET state='FAILED', error_json=?,
                  finished_at=now(), heartbeat_at=now() WHERE attempt_id=?
                """,
                [_json(error), attempt_id],
            )
            count = self.store._conn.execute(
                "SELECT count(*) FROM onboarding_step_attempt WHERE onboarding_id=? AND step=?",
                [task.onboarding_id, task.current_step.value],
            ).fetchone()[0]
            can_retry = retryable and count < 3
            wait_seconds = 2 ** count
            self.store._conn.execute(
                """
                UPDATE company_onboarding SET state=?, error_json=?, revision=revision+1,
                  next_attempt_at=CASE WHEN ? THEN now() + (? * INTERVAL 1 SECOND) ELSE NULL END,
                  updated_at=now() WHERE onboarding_id=?
                """,
                [
                    self._state_for_step(task.current_step).value if can_retry else "FAILED",
                    _json(error),
                    can_retry,
                    wait_seconds,
                    task.onboarding_id,
                ],
            )

    def recover_interrupted(self) -> int:
        with self.writer.transaction(self.store):
            rows = self.store._conn.execute(
                "SELECT DISTINCT onboarding_id FROM onboarding_step_attempt WHERE state='RUNNING'"
            ).fetchall()
            self.store._conn.execute(
                """
                UPDATE onboarding_step_attempt SET state='INTERRUPTED', finished_at=now(),
                  error_json='{"code":"INTERRUPTED","retryable":true}'
                WHERE state='RUNNING'
                """
            )
        return len(rows)
