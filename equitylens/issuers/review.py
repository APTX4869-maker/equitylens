"""Auditable adaptation review and exact-candidate publication."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from equitylens.config import RAW_DIR
from equitylens.onboarding.repository import OnboardingRepository
from equitylens.publication.repository import PublicationConflict, PublicationRepository
from equitylens.storage.duckdb_store import DuckDBStore
from equitylens.storage.writer import writer_for


class ReviewConflict(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ReviewRecord:
    review_id: str
    company_id: str
    fingerprint: str
    reviewer: str
    decision: str
    note: str | None
    created_at: datetime


def _parsed(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _public_manifest(manifest: Any) -> Any:
    """Remove workstation paths from exported evidence metadata."""
    if isinstance(manifest, dict):
        public = {}
        for key, value in manifest.items():
            if key in {"local_path", "cache_path", "absolute_path"}:
                try:
                    path = Path(str(value)).resolve()
                    root = RAW_DIR.resolve()
                    if path.is_relative_to(root):
                        public["raw_locator"] = path.relative_to(root).as_posix()
                except (OSError, ValueError):
                    pass
                continue
            public[key] = _public_manifest(value)
        return public
    if isinstance(manifest, list):
        return [_public_manifest(value) for value in manifest]
    return manifest


class ReviewService:
    def __init__(
        self,
        store: DuckDBStore,
        tasks: OnboardingRepository,
        publications: PublicationRepository,
        *,
        publish_immediately: bool = True,
    ) -> None:
        self.store = store
        self.tasks = tasks
        self.publications = publications
        self.publish_immediately = publish_immediately

    def _candidate_fingerprint(self, task) -> str:
        if not task.profile_id or not task.dataset_id or not task.quality_report_id:
            raise ReviewConflict("CANDIDATE_INCOMPLETE", "review candidate is incomplete")
        try:
            return self.publications.publication_fingerprint(
                company_id=task.company_id,
                dataset_id=task.dataset_id,
                profile_id=task.profile_id,
                quality_report_id=task.quality_report_id,
            )
        except PublicationConflict as exc:
            raise ReviewConflict(exc.code, str(exc)) from exc

    def review_package(self, task_id: str) -> dict[str, Any]:
        task = self.tasks.get(task_id)
        fingerprint = self._candidate_fingerprint(task)
        dataset = self.store.query_one(
            "SELECT * FROM dataset_version WHERE dataset_id=?", [task.dataset_id]
        )
        profile = self.store.query_one(
            "SELECT content_sha256, content_json FROM issuer_profile_version WHERE profile_id=?",
            [task.profile_id],
        )
        report = self.store.query_one(
            "SELECT report_id, rule_version, result, fingerprint, created_at FROM quality_report WHERE report_id=?",
            [task.quality_report_id],
        )
        checks = self.store.query(
            """
            SELECT check_id, scope_key, status, severity, actual_json, expected_json,
                   tolerance_json, evidence_json, reason
            FROM company_quality_check WHERE report_id=? ORDER BY check_id, scope_key
            """,
            [task.quality_report_id],
        )
        for check in checks:
            for key in ("actual_json", "expected_json", "tolerance_json", "evidence_json"):
                check[key.removesuffix("_json")] = _parsed(check.pop(key))
        return {
            "onboarding_id": task.onboarding_id,
            "company_id": task.company_id,
            "revision": task.revision,
            "fingerprint": fingerprint,
            "dataset_id": task.dataset_id,
            "dataset_hash": dataset["dataset_hash"],
            "profile_id": task.profile_id,
            "profile_hash": profile["content_sha256"],
            "profile": _parsed(profile["content_json"]),
            "source_manifest": _public_manifest(_parsed(dataset["source_manifest_json"])),
            "quality": {
                **{
                    key: value.isoformat() if isinstance(value, datetime) else value
                    for key, value in report.items()
                },
                "checks": checks,
            },
        }

    def review(
        self,
        task_id: str,
        *,
        expected_revision: int,
        fingerprint: str,
        decision: str,
        reviewer: str,
        note: str | None = None,
    ) -> ReviewRecord:
        decision = decision.upper()
        if decision not in {"APPROVE", "REJECT"}:
            raise ReviewConflict("INVALID_DECISION", "decision must be APPROVE or REJECT")
        task = self.tasks.get(task_id)
        if task.state.value != "NEEDS_REVIEW" or task.revision != expected_revision:
            raise ReviewConflict("TASK_CONFLICT", "task revision or state changed")
        current_fingerprint = self._candidate_fingerprint(task)
        if fingerprint != current_fingerprint:
            raise ReviewConflict("REVIEW_STALE", "review candidate changed")
        report = self.store.query_one(
            "SELECT result FROM quality_report WHERE report_id=? AND dataset_id=?",
            [task.quality_report_id, task.dataset_id],
        )
        if decision == "APPROVE" and (report is None or report["result"] != "PASS"):
            raise ReviewConflict("QUALITY_BLOCKED", "quality gate did not pass")

        review_id = str(uuid.uuid4())
        with writer_for(self.store).transaction(self.store):
            locked = self.store._conn.execute(
                """
                SELECT state, revision, cancel_requested, profile_id, dataset_id,
                       quality_report_id
                FROM company_onboarding WHERE onboarding_id=?
                """,
                [task_id],
            ).fetchone()
            expected = (
                "NEEDS_REVIEW",
                expected_revision,
                False,
                task.profile_id,
                task.dataset_id,
                task.quality_report_id,
            )
            if locked is None or tuple(locked) != expected:
                raise ReviewConflict("TASK_CONFLICT", "task revision or state changed")
            self.store._conn.execute(
                """
                INSERT INTO adaptation_review
                  (review_id, company_id, fingerprint, reviewer, decision, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, now())
                """,
                [review_id, task.company_id, fingerprint, reviewer, decision, note],
            )
            next_state = "PUBLISHING" if decision == "APPROVE" else "NEEDS_ADAPTATION"
            next_step = "PUBLISH" if decision == "APPROVE" else "BUILD"
            self.store._conn.execute(
                """
                UPDATE company_onboarding SET review_id=?, state=?, current_step=?,
                  revision=revision+1, updated_at=now() WHERE onboarding_id=?
                """,
                [review_id, next_state, next_step, task_id],
            )
        row = self.store.query_one(
            "SELECT * FROM adaptation_review WHERE review_id=?", [review_id]
        )
        record = ReviewRecord(**row)
        if decision == "APPROVE" and self.publish_immediately:
            revised = self.tasks.get(task_id)
            self.publish_approved(
                task_id,
                expected_revision=revised.revision,
                review_id=review_id,
            )
        return record

    def publish_approved(
        self, task_id: str, *, expected_revision: int, review_id: str
    ):
        task = self.tasks.get(task_id)
        review = self.store.query_one(
            "SELECT company_id, fingerprint, decision FROM adaptation_review WHERE review_id=?",
            [review_id],
        )
        if review is None or review["decision"] != "APPROVE" or review["company_id"] != task.company_id:
            raise ReviewConflict("REVIEW_STALE", "approval is invalid")
        current_fingerprint = self._candidate_fingerprint(task)
        if review["fingerprint"] != current_fingerprint:
            raise ReviewConflict("REVIEW_STALE", "approved candidate changed")
        if task.review_id != review_id:
            raise ReviewConflict("REVIEW_STALE", "approval is not current")
        if task.state.value != "PUBLISHING" or task.revision != expected_revision:
            raise ReviewConflict("TASK_CONFLICT", "task revision or state changed")
        try:
            return self.publications.publish(
                task_id, expected_revision, current_fingerprint
            )
        except PublicationConflict as exc:
            raise ReviewConflict(exc.code, str(exc)) from exc
