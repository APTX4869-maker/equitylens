"""Durable onboarding tasks with optimistic revision checks."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from equitylens.issuers.candidate import CandidateArtifact, ProfileCandidate
from equitylens.onboarding.models import (
    ACTIVE_STATES,
    FetchBundle,
    FetchDocument,
    OnboardingEvent,
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
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=lambda item: item.isoformat() if hasattr(item, "isoformat") else str(item),
        )
        if value is not None
        else None
    )


def _step_input_hash(task: TaskView) -> str:
    """Identify the immutable inputs consumed by the task's current step."""
    payload = {
        "request": task.input_fingerprint,
        "step": task.current_step.value if task.current_step else None,
        "fetch_bundle_id": task.fetch_bundle_id,
        "profile_candidate_id": task.profile_candidate_id,
        "profile_id": task.profile_id,
        "dataset_id": task.dataset_id,
        "quality_report_id": task.quality_report_id,
        "review_id": task.review_id,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


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
        remediation = (error or {}).get("remediation")
        if state == TaskState.FAILED:
            if remediation == "PROFILE_IMPORT" and not row.get("fetch_bundle_id"):
                actions.append("REFETCH")
            elif remediation == "PROFILE_IMPORT":
                actions.append("PROFILE_IMPORT")
            elif remediation == "REFETCH":
                actions.append("REFETCH")
            else:
                actions.append("RETRY")
        if state not in (TaskState.PUBLISHED, TaskState.CANCELLED):
            actions.append("CANCEL")
        if state == TaskState.NEEDS_REVIEW:
            actions.extend(["REVIEW", "EXPORT_REVIEW_PACKAGE"])
        if state == TaskState.NEEDS_ADAPTATION:
            if remediation == "REFETCH" or not row.get("fetch_bundle_id"):
                actions.append("REFETCH")
            else:
                actions.append("PROFILE_IMPORT")
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
            discovery_id=row.get("discovery_id"),
            fetch_bundle_id=row.get("fetch_bundle_id"),
            profile_candidate_id=row.get("profile_candidate_id"),
            profile_id=row.get("profile_id"),
            dataset_id=row.get("dataset_id"),
            quality_report_id=row.get("quality_report_id"),
            review_id=row.get("review_id"),
            publication_id=row.get("publication_id"),
            error=error,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            actions=actions,
        )

    def create_fetch_bundle(
        self,
        task_id: str,
        *,
        expected_revision: int,
        fetcher_version: str,
        parser_version: str,
        documents: list[dict[str, Any] | FetchDocument],
    ) -> FetchBundle:
        parsed = [
            item if isinstance(item, FetchDocument) else FetchDocument.model_validate(item)
            for item in documents
        ]
        canonical_documents = [
            item.model_dump(mode="json")
            for item in sorted(parsed, key=lambda document: document.document_id)
        ]
        content_sha256 = hashlib.sha256(
            _json(
                {
                    "fetcher_version": fetcher_version,
                    "parser_version": parser_version,
                    "documents": canonical_documents,
                }
            ).encode()
        ).hexdigest()
        bundle_id: str | None = None
        with self.writer.transaction(self.store):
            task = self.store._conn.execute(
                "SELECT revision, fetch_bundle_id FROM company_onboarding WHERE onboarding_id=?",
                [task_id],
            ).fetchone()
            if task is None:
                raise KeyError(task_id)
            existing = self.store._conn.execute(
                """
                SELECT fetch_bundle_id FROM onboarding_fetch_bundle
                WHERE onboarding_id=? AND content_sha256=?
                """,
                [task_id, content_sha256],
            ).fetchone()
            if existing and task[1] == existing[0]:
                bundle_id = existing[0]
            else:
                if task[0] != expected_revision:
                    raise OnboardingConflict("TASK_CONFLICT", "task revision changed")
                bundle_id = existing[0] if existing else str(uuid.uuid4())
                if not existing:
                    self.store._conn.execute(
                        """
                        INSERT INTO onboarding_fetch_bundle VALUES (?, ?, ?, ?, ?, now())
                        """,
                        [bundle_id, task_id, fetcher_version, parser_version, content_sha256],
                    )
                    for document in parsed:
                        self.store._conn.execute(
                            """
                            INSERT INTO onboarding_fetch_document VALUES
                              (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            [
                                bundle_id,
                                document.document_id,
                                document.document_type,
                                document.accession_number,
                                document.form_type,
                                document.filed_at,
                                document.report_date,
                                document.fetched_at,
                                document.source_url,
                                document.content_sha256,
                                document.raw_locator,
                            ],
                        )
                new_revision = task[0] + 1
                self.store._conn.execute(
                    """
                    UPDATE company_onboarding SET fetch_bundle_id=?, profile_candidate_id=NULL,
                      profile_id=NULL, dataset_id=NULL, quality_report_id=NULL,
                      review_id=NULL, publication_id=NULL, revision=?, updated_at=now()
                    WHERE onboarding_id=?
                    """,
                    [bundle_id, new_revision, task_id],
                )
                self.store._conn.execute(
                    """
                    UPDATE onboarding_step_attempt SET state='STALE'
                    WHERE onboarding_id=? AND step IN ('BUILD','VALIDATE','PUBLISH')
                      AND state <> 'RUNNING'
                    """,
                    [task_id],
                )
                self._append_event_locked(
                    task_id,
                    event_type="FETCH_BUNDLE_ACTIVATED",
                    actor_type="SYSTEM",
                    task_revision=new_revision,
                    payload={"fetch_bundle_id": bundle_id, "content_sha256": content_sha256},
                )
        return self.get_fetch_bundle(bundle_id)

    def get_fetch_bundle(self, bundle_id: str) -> FetchBundle:
        row = self.store.query_one(
            "SELECT * FROM onboarding_fetch_bundle WHERE fetch_bundle_id=?", [bundle_id]
        )
        if row is None:
            raise KeyError(bundle_id)
        documents = self.store.query(
            """
            SELECT * EXCLUDE (fetch_bundle_id) FROM onboarding_fetch_document
            WHERE fetch_bundle_id=? ORDER BY document_id
            """,
            [bundle_id],
        )
        return FetchBundle.model_validate({**row, "documents": documents})

    def append_event(
        self,
        task_id: str,
        *,
        event_type: str,
        actor_type: str,
        task_revision: int,
        payload: dict[str, Any] | None = None,
    ) -> OnboardingEvent:
        with self.writer.transaction(self.store):
            event_id = self._append_event_locked(
                task_id,
                event_type=event_type,
                actor_type=actor_type,
                task_revision=task_revision,
                payload=payload or {},
            )
        return self._get_event(event_id)

    def _append_event_locked(
        self,
        task_id: str,
        *,
        event_type: str,
        actor_type: str,
        task_revision: int,
        payload: dict[str, Any],
    ) -> str:
        event_id = str(uuid.uuid4())
        self.store._conn.execute(
            """
            INSERT INTO onboarding_event VALUES (?, ?, ?, ?, ?, ?, now())
            """,
            [event_id, task_id, event_type, actor_type, task_revision, _json(payload)],
        )
        return event_id

    def _get_event(self, event_id: str) -> OnboardingEvent:
        row = self.store.query_one("SELECT * FROM onboarding_event WHERE event_id=?", [event_id])
        if row is None:
            raise KeyError(event_id)
        payload = row.pop("payload_json")
        return OnboardingEvent.model_validate(
            {**row, "payload": json.loads(payload) if isinstance(payload, str) else payload}
        )

    def list_events(self, task_id: str) -> list[OnboardingEvent]:
        rows = self.store.query(
            "SELECT event_id FROM onboarding_event WHERE onboarding_id=? ORDER BY created_at, event_id",
            [task_id],
        )
        return [self._get_event(row["event_id"]) for row in rows]

    def progress(self, task: TaskView | str, *, now: datetime | None = None):
        from equitylens.onboarding.progress import derive_progress

        task = self.get(task) if isinstance(task, str) else task
        attempts = self.store.query(
            """SELECT step, state, started_at, finished_at, heartbeat_at
               FROM onboarding_step_attempt WHERE onboarding_id=? ORDER BY started_at""",
            [task.onboarding_id],
        )
        return derive_progress(
            task,
            attempts,
            self.list_events(task.onboarding_id),
            now=now or datetime.now(timezone.utc),
        )

    def get_profile_candidate(self, candidate_id: str) -> ProfileCandidate:
        row = self.store.query_one(
            "SELECT * FROM issuer_profile_candidate WHERE profile_candidate_id=?",
            [candidate_id],
        )
        if row is None:
            raise KeyError(candidate_id)
        for source, target in (
            ("snapshot_manifest_json", "snapshot_manifest"),
            ("profile_json", "profile"),
            ("unresolved_json", "unresolved_fields"),
        ):
            value = row.pop(source)
            row[target] = json.loads(value) if isinstance(value, str) else value
        return ProfileCandidate.model_validate({**row, "review_status": "NEEDS_ADAPTATION"})

    def activate_profile_candidate(
        self, task_id: str, *, expected_revision: int, artifact: CandidateArtifact
    ) -> tuple[TaskView, ProfileCandidate]:
        """Create/reuse and bind a candidate without changing the task phase."""
        with self.writer.transaction(self.store):
            row = self.store._conn.execute(
                """SELECT revision, cancel_requested, fetch_bundle_id, profile_candidate_id
                   FROM company_onboarding WHERE onboarding_id=?""",
                [task_id],
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            if row[0] != expected_revision or row[1] or row[2] != artifact.fetch_bundle_id:
                raise OnboardingConflict("TASK_CONFLICT", "task inputs changed or were cancelled")
            existing = self.store._conn.execute(
                """SELECT profile_candidate_id FROM issuer_profile_candidate
                   WHERE onboarding_id=? AND input_sha256=?""",
                [task_id, artifact.input_sha256],
            ).fetchone()
            candidate_id = existing[0] if existing else str(uuid.uuid4())
            if not existing:
                self._insert_profile_candidate_locked(candidate_id, artifact)
            if row[3] != candidate_id:
                new_revision = row[0] + 1
                self.store._conn.execute(
                    """UPDATE company_onboarding SET profile_candidate_id=?, revision=?,
                       updated_at=now() WHERE onboarding_id=?""",
                    [candidate_id, new_revision, task_id],
                )
                self._append_event_locked(
                    task_id, event_type="PROFILE_CANDIDATE_CREATED", actor_type="SYSTEM",
                    task_revision=new_revision,
                    payload={"profile_candidate_id": candidate_id,
                             "input_sha256": artifact.input_sha256,
                             "content_sha256": artifact.content_sha256,
                             "unresolved_count": len(artifact.unresolved_fields),
                             "reused": bool(existing)},
                )
        return self.get(task_id), self.get_profile_candidate(candidate_id)

    def _insert_profile_candidate_locked(
        self, candidate_id: str, artifact: CandidateArtifact
    ) -> None:
        self.store._conn.execute(
            """
            INSERT INTO issuer_profile_candidate (
              profile_candidate_id, onboarding_id, task_revision, company_id,
              fetch_bundle_id, input_sha256, generator_version, mapping_version,
              mapping_sha256, snapshot_manifest_json, profile_json, unresolved_json,
              yaml_text, content_sha256, yaml_sha256, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())
            """,
            [
                candidate_id, artifact.onboarding_id, artifact.task_revision,
                artifact.company_id, artifact.fetch_bundle_id, artifact.input_sha256,
                artifact.generator_version, artifact.mapping_version,
                artifact.mapping_sha256, _json(artifact.snapshot_manifest),
                _json(artifact.profile),
                _json([item.model_dump(mode="json") for item in artifact.unresolved_fields]),
                artifact.yaml_text, artifact.content_sha256, artifact.yaml_sha256,
            ],
        )

    def bind_profile_candidate(
        self,
        task: TaskView,
        attempt_id: str,
        artifact: CandidateArtifact,
        *,
        message: str,
    ) -> TaskView:
        """Persist/reuse a candidate and pause the running BUILD attempt atomically."""
        with self.writer.transaction(self.store):
            row = self.store._conn.execute(
                """
                SELECT revision, cancel_requested, fetch_bundle_id
                FROM company_onboarding WHERE onboarding_id=?
                """,
                [task.onboarding_id],
            ).fetchone()
            if row is None:
                raise KeyError(task.onboarding_id)
            if row[0] != task.revision or row[1] or row[2] != artifact.fetch_bundle_id:
                raise OnboardingConflict("TASK_CONFLICT", "task inputs changed or were cancelled")
            existing = self.store._conn.execute(
                """
                SELECT profile_candidate_id FROM issuer_profile_candidate
                WHERE onboarding_id=? AND input_sha256=?
                """,
                [task.onboarding_id, artifact.input_sha256],
            ).fetchone()
            candidate_id = existing[0] if existing else str(uuid.uuid4())
            if not existing:
                self._insert_profile_candidate_locked(candidate_id, artifact)
            new_revision = task.revision + 1
            self.store._conn.execute(
                """
                UPDATE onboarding_step_attempt SET state='PAUSED', output_hash=?,
                  finished_at=now(), heartbeat_at=now() WHERE attempt_id=?
                """,
                [artifact.content_sha256, attempt_id],
            )
            self.store._conn.execute(
                """
                UPDATE company_onboarding SET profile_candidate_id=?, state='NEEDS_ADAPTATION',
                  current_step='BUILD', revision=?, error_json=?, next_attempt_at=NULL,
                  updated_at=now() WHERE onboarding_id=?
                """,
                [
                    candidate_id,
                    new_revision,
                    _json({"code": "ADAPTATION_REQUIRED", "message": message,
                           "retryable": False, "remediation": "PROFILE_IMPORT"}),
                    task.onboarding_id,
                ],
            )
            self._append_event_locked(
                task.onboarding_id,
                event_type="PROFILE_CANDIDATE_CREATED",
                actor_type="SYSTEM",
                task_revision=new_revision,
                payload={
                    "profile_candidate_id": candidate_id,
                    "input_sha256": artifact.input_sha256,
                    "content_sha256": artifact.content_sha256,
                    "unresolved_count": len(artifact.unresolved_fields),
                    "reused": bool(existing),
                },
            )
        return self.get(task.onboarding_id)

    def import_profile_atomic(
        self,
        task_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
        request_sha256: str,
        profile: Any,
    ) -> TaskView:
        """Install Profile v2 and resume BUILD as one idempotent transaction."""
        with self.writer.transaction(self.store):
            prior = self.store._conn.execute(
                """
                SELECT request_sha256, response_json FROM profile_import_idempotency
                WHERE onboarding_id=? AND idempotency_key=?
                """,
                [task_id, idempotency_key],
            ).fetchone()
            if prior:
                if prior[0] != request_sha256:
                    raise OnboardingConflict(
                        "IDEMPOTENCY_CONFLICT",
                        "idempotency key was used for another profile import",
                    )
                response = json.loads(prior[1]) if isinstance(prior[1], str) else prior[1]
                return TaskView.model_validate(response)

            task = self.store._conn.execute(
                """
                SELECT company_id, state, current_step, revision, cancel_requested,
                  fetch_bundle_id FROM company_onboarding WHERE onboarding_id=?
                """,
                [task_id],
            ).fetchone()
            if task is None:
                raise KeyError(task_id)
            company_id, state, current_step, revision, cancelled, bundle_id = task
            if revision != expected_revision or cancelled:
                raise OnboardingConflict("TASK_CONFLICT", "task revision changed or was cancelled")
            allowed = state == "NEEDS_ADAPTATION" or (
                state == "FAILED" and current_step in {"BUILD", "VALIDATE"}
            )
            if not allowed:
                raise OnboardingConflict("TASK_CONFLICT", "task does not allow profile import")
            if profile.company_id != company_id:
                raise OnboardingConflict(
                    "PROFILE_COMPANY_MISMATCH",
                    "profile company_id does not match onboarding company",
                )
            if not bundle_id:
                raise OnboardingConflict(
                    "FETCH_BUNDLE_INCOMPLETE", "current fixed fetch bundle is missing"
                )
            fixed = set(
                self.store._conn.execute(
                    """
                    SELECT document_id, content_sha256 FROM onboarding_fetch_document
                    WHERE fetch_bundle_id=?
                    """,
                    [bundle_id],
                ).fetchall()
            )
            missing = [
                item.evidence_id
                for item in profile.evidence
                if (item.source_document_id, item.content_sha256) not in fixed
            ]
            if missing:
                raise OnboardingConflict(
                    "PROFILE_EVIDENCE_MISMATCH",
                    f"profile evidence is not in the current fetch bundle: {', '.join(missing)}",
                )
            maximum = self.store._conn.execute(
                "SELECT max(version) FROM issuer_profile_version WHERE company_id=?",
                [company_id],
            ).fetchone()[0]
            if maximum is not None and profile.version <= maximum:
                raise OnboardingConflict(
                    "PROFILE_VERSION_CONFLICT",
                    f"profile version must be greater than {maximum}",
                )
            content = profile.model_dump(mode="json", exclude={"content_sha256"})
            content_json = _json(content)
            content_sha256 = hashlib.sha256(content_json.encode()).hexdigest()
            profile_id = str(uuid.uuid4())
            self.store._conn.execute(
                """
                INSERT INTO issuer_profile_version
                  (profile_id, company_id, version, schema_version, content_json,
                   content_sha256, created_at)
                VALUES (?, ?, ?, 2, ?, ?, now())
                """,
                [profile_id, company_id, profile.version, content_json, content_sha256],
            )
            self.store._conn.execute(
                """
                UPDATE onboarding_step_attempt SET state='STALE'
                WHERE onboarding_id=? AND step IN ('BUILD','VALIDATE','PUBLISH')
                  AND state <> 'RUNNING'
                """,
                [task_id],
            )
            new_revision = revision + 1
            self.store._conn.execute(
                """
                UPDATE company_onboarding SET profile_candidate_id=NULL, profile_id=?,
                  dataset_id=NULL, quality_report_id=NULL, review_id=NULL,
                  publication_id=NULL, state='BUILDING', current_step='BUILD',
                  revision=?, error_json=NULL, next_attempt_at=NULL, updated_at=now()
                WHERE onboarding_id=?
                """,
                [profile_id, new_revision, task_id],
            )
            self._append_event_locked(
                task_id,
                event_type="PROFILE_IMPORTED",
                actor_type="MAINTAINER",
                task_revision=new_revision,
                payload={
                    "profile_id": profile_id,
                    "version": profile.version,
                    "content_sha256": content_sha256,
                    "fetch_bundle_id": bundle_id,
                },
            )
            self._append_event_locked(
                task_id,
                event_type="TASK_RESUMED",
                actor_type="SYSTEM",
                task_revision=new_revision,
                payload={"current_step": "BUILD"},
            )
            response = self.get(task_id)
            response_json = response.model_dump(mode="json")
            self.store._conn.execute(
                """
                INSERT INTO profile_import_idempotency
                  (onboarding_id, idempotency_key, request_sha256, response_json, created_at)
                VALUES (?, ?, ?, ?, now())
                """,
                [task_id, idempotency_key, request_sha256, _json(response_json)],
            )
        return response

    def set_candidate(
        self,
        task_id: str,
        *,
        expected_revision: int,
        profile_id: str | None = None,
        dataset_id: str | None = None,
        quality_report_id: str | None = None,
        state: TaskState,
        current_step: OnboardingStep,
    ) -> TaskView:
        """Replace candidate pointers and invalidate any prior approval."""
        with self.writer.transaction(self.store):
            row = self.store._conn.execute(
                "SELECT revision, cancel_requested FROM company_onboarding WHERE onboarding_id=?",
                [task_id],
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            if row[0] != expected_revision or row[1]:
                raise OnboardingConflict("TASK_CONFLICT", "task revision changed or was cancelled")
            if dataset_id is None and current_step == OnboardingStep.BUILD:
                self.store._conn.execute(
                    """
                    UPDATE onboarding_step_attempt SET state='STALE'
                    WHERE onboarding_id=? AND step IN ('BUILD','VALIDATE','PUBLISH')
                      AND state <> 'RUNNING'
                    """,
                    [task_id],
                )
            self.store._conn.execute(
                """
                UPDATE company_onboarding SET profile_id=?, dataset_id=?, quality_report_id=?,
                  review_id=NULL, publication_id=NULL, state=?, current_step=?,
                  revision=revision+1, updated_at=now()
                WHERE onboarding_id=?
                """,
                [
                    profile_id,
                    dataset_id,
                    quality_report_id,
                    state.value,
                    current_step.value,
                    task_id,
                ],
            )
        return self.get(task_id)

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
            progress_snapshot = self.progress(task_id).model_dump(mode="json")
            new_revision = row[1] + 1
            self.store._conn.execute(
                """
                UPDATE company_onboarding SET cancel_requested=true, state=?, current_step=?,
                  revision=?, updated_at=now()
                WHERE onboarding_id=?
                """,
                [row[0] if running else "CANCELLED", self.get(task_id).current_step.value if running else None,
                 new_revision, task_id],
            )
            self._append_event_locked(
                task_id,
                event_type="TASK_CANCELLED",
                actor_type="MAINTAINER",
                task_revision=new_revision,
                payload={"progress_snapshot": progress_snapshot},
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

    def request_refetch(self, task_id: str, *, expected_revision: int) -> TaskView:
        with self.writer.transaction(self.store):
            task = self.get(task_id)
            if task.revision != expected_revision or "REFETCH" not in task.actions:
                raise OnboardingConflict("TASK_CONFLICT", "task does not allow refetch")
            new_revision = task.revision + 1
            self._append_event_locked(
                task_id,
                event_type="REFETCH_REQUESTED",
                actor_type="MAINTAINER",
                task_revision=new_revision,
                payload={
                    "fetch_bundle_id": task.fetch_bundle_id,
                    "profile_candidate_id": task.profile_candidate_id,
                    "profile_id": task.profile_id,
                    "dataset_id": task.dataset_id,
                    "quality_report_id": task.quality_report_id,
                    "review_id": task.review_id,
                    "publication_id": task.publication_id,
                },
            )
            self.store._conn.execute(
                """
                UPDATE company_onboarding SET state='FETCHING', current_step='FETCH',
                  revision=?, error_json=NULL, next_attempt_at=NULL, updated_at=now()
                WHERE onboarding_id=?
                """,
                [new_revision, task_id],
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
            [task.onboarding_id, task.current_step.value, _step_input_hash(task)],
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
                    _step_input_hash(task),
                ],
            )
            self.store._conn.execute(
                "UPDATE company_onboarding SET state=?, updated_at=now() WHERE onboarding_id=?",
                [self._state_for_step(task.current_step).value, task.onboarding_id],
            )
        return attempt_id

    def heartbeat_attempt(self, attempt_id: str) -> None:
        with self.writer.transaction(self.store):
            self.store._conn.execute(
                """UPDATE onboarding_step_attempt SET heartbeat_at=now()
                   WHERE attempt_id=? AND state='RUNNING'""",
                [attempt_id],
            )

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

    def pause_attempt(
        self,
        task: TaskView,
        attempt_id: str,
        *,
        state: TaskState,
        current_step: OnboardingStep,
        message: str,
        candidate_artifact: CandidateArtifact | None = None,
    ) -> TaskView:
        if candidate_artifact is not None:
            return self.bind_profile_candidate(
                task, attempt_id, candidate_artifact, message=message
            )
        with self.writer.transaction(self.store):
            self.store._conn.execute(
                """
                UPDATE onboarding_step_attempt SET state='PAUSED',
                  output_hash='PAUSED', finished_at=now(), heartbeat_at=now()
                WHERE attempt_id=?
                """,
                [attempt_id],
            )
            self.store._conn.execute(
                """
                UPDATE company_onboarding SET state=?, current_step=?, revision=revision+1,
                  error_json=?, next_attempt_at=NULL, updated_at=now()
                WHERE onboarding_id=?
                """,
                [
                    state.value,
                    current_step.value,
                    _json({"code": "ADAPTATION_REQUIRED", "message": message, "retryable": False}),
                    task.onboarding_id,
                ],
            )
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
            input_hash = self.store._conn.execute(
                "SELECT input_hash FROM onboarding_step_attempt WHERE attempt_id=?",
                [attempt_id],
            ).fetchone()[0]
            count = self.store._conn.execute(
                """
                SELECT count(*) FROM onboarding_step_attempt
                WHERE onboarding_id=? AND step=? AND input_hash=? AND state='FAILED'
                """,
                [task.onboarding_id, task.current_step.value, input_hash],
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
