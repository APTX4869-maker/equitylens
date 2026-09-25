"""Publication transaction and fixed-version reads."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from equitylens.publication.models import (
    Publication,
    PublicationContext,
    canonical_json,
    sha256_json,
    validate_dataset_payload,
)
from equitylens.storage.duckdb_store import DuckDBStore
from equitylens.storage.writer import writer_for


class PublicationConflict(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PublicationRepository:
    def __init__(self, store: DuckDBStore) -> None:
        self.store = store
        self.store.connect()

    def create_profile(
        self,
        company_id: str,
        *,
        version: int,
        schema_version: int,
        content: dict[str, Any],
    ) -> str:
        content_json = canonical_json(content)
        digest = sha256_json(content)
        existing = self.store.query_one(
            """
            SELECT profile_id, content_sha256 FROM issuer_profile_version
            WHERE company_id = ? AND version = ?
            """,
            [company_id, version],
        )
        if existing:
            if existing["content_sha256"] != digest:
                raise PublicationConflict(
                    "PROFILE_VERSION_CONFLICT",
                    "issuer profile versions are immutable",
                )
            return existing["profile_id"]
        profile_id = str(uuid.uuid4())
        with writer_for(self.store).transaction(self.store):
            self.store._conn.execute(
                """
                INSERT INTO issuer_profile_version VALUES (?, ?, ?, ?, ?, ?, now())
                """,
                [profile_id, company_id, version, schema_version, content_json, digest],
            )
        return profile_id

    def context(
        self, company_id: str, publication_id: str | None = None
    ) -> PublicationContext:
        if publication_id is None:
            company = self.store.query_one(
                "SELECT active_publication_id FROM company WHERE company_id = ?",
                [company_id],
            )
            publication_id = company and company["active_publication_id"]
        if not publication_id:
            raise PublicationConflict(
                "PUBLICATION_NOT_FOUND", "company has no active publication"
            )
        row = self.store.query_one(
            """
            SELECT company_id, publication_id, dataset_id, profile_id
            FROM publication WHERE publication_id = ? AND company_id = ?
            """,
            [publication_id, company_id],
        )
        if row is None:
            raise PublicationConflict(
                "PUBLICATION_NOT_FOUND",
                "publication does not belong to the requested company",
            )
        return PublicationContext.model_validate(row)

    def entities(
        self, context: PublicationContext, entity_type: str
    ) -> list[dict[str, Any]]:
        """Read and verify one entity type from an immutable dataset."""
        rows = self.store.query(
            """
            SELECT entity_type, row_id, payload_json, payload_sha256
            FROM dataset_row
            WHERE dataset_id = ? AND entity_type = ?
            ORDER BY row_id
            """,
            [context.dataset_id, entity_type],
        )
        entities: list[dict[str, Any]] = []
        for row in rows:
            payload = row["payload_json"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            if sha256_json(payload) != row["payload_sha256"]:
                raise PublicationConflict(
                    "DATASET_HASH_MISMATCH",
                    f"dataset row hash mismatch: {row['row_id']}",
                )
            entities.append(validate_dataset_payload(entity_type, payload))
        return entities

    def facts(self, context: PublicationContext) -> list[dict[str, Any]]:
        return self.entities(context, "canonical_fact")

    def publication_fingerprint(
        self,
        *,
        company_id: str,
        dataset_id: str,
        profile_id: str,
        quality_report_id: str | None,
    ) -> str:
        """Hash every immutable input covered by an adaptation approval."""
        dataset = self.store.query_one(
            """
            SELECT company_id, profile_id, dataset_hash, parser_version, rule_version, state
            FROM dataset_version WHERE dataset_id = ?
            """,
            [dataset_id],
        )
        if (
            dataset is None
            or dataset["company_id"] != company_id
            or dataset["profile_id"] != profile_id
            or dataset["state"] != "SEALED"
        ):
            raise PublicationConflict(
                "DATASET_CONFLICT", "sealed dataset/profile/company do not match"
            )
        profile = self.store.query_one(
            "SELECT content_sha256 FROM issuer_profile_version WHERE profile_id = ? AND company_id = ?",
            [profile_id, company_id],
        )
        if profile is None:
            raise PublicationConflict("PROFILE_NOT_FOUND", "profile does not exist")
        quality_hash = None
        if quality_report_id:
            report = self.store.query_one(
                "SELECT fingerprint FROM quality_report WHERE report_id = ? AND dataset_id = ?",
                [quality_report_id, dataset_id],
            )
            if report is None:
                raise PublicationConflict(
                    "QUALITY_REPORT_NOT_FOUND", "quality report does not match dataset"
                )
            quality_hash = report["fingerprint"]
        security_hashes = [
            sha256_json(
                {
                    "security_id": row["security_id"],
                    "exchange": row["exchange"],
                    "currency": row["currency"],
                    "instrument_type": row["instrument_type"],
                    "identity_evidence": json.loads(row["identity_evidence_json"])
                    if isinstance(row["identity_evidence_json"], str)
                    else row["identity_evidence_json"],
                }
            )
            for row in self.store.query(
                "SELECT * FROM security WHERE company_id = ? ORDER BY security_id",
                [company_id],
            )
        ]
        return sha256_json(
            {
                "dataset_hash": dataset["dataset_hash"],
                "profile_hash": profile["content_sha256"],
                "rule_version": dataset["rule_version"],
                "parser_version": dataset["parser_version"],
                "quality_report_hash": quality_hash,
                "security_identity_hashes": security_hashes,
            }
        )

    def publish_dataset(
        self,
        *,
        company_id: str,
        dataset_id: str,
        profile_id: str,
        quality_report_id: str | None,
        review_id: str | None,
        expected_active_publication_id: str | None = None,
        fingerprint: str | None = None,
        before_pointer_switch: Callable[[], None] | None = None,
        onboarding_id: str | None = None,
        expected_task_revision: int | None = None,
    ) -> Publication:
        computed_fingerprint = self.publication_fingerprint(
            company_id=company_id,
            dataset_id=dataset_id,
            profile_id=profile_id,
            quality_report_id=quality_report_id,
        )
        if fingerprint is not None and fingerprint != computed_fingerprint:
            raise PublicationConflict("REVIEW_STALE", "publication fingerprint changed")

        publication_id = str(uuid.uuid4())
        with writer_for(self.store).transaction(self.store):
            if onboarding_id is not None:
                task = self.store._conn.execute(
                    """
                    SELECT company_id, state, revision, cancel_requested, profile_id,
                           dataset_id, quality_report_id, review_id
                    FROM company_onboarding WHERE onboarding_id=?
                    """,
                    [onboarding_id],
                ).fetchone()
                expected = (
                    company_id,
                    "PUBLISHING",
                    expected_task_revision,
                    False,
                    profile_id,
                    dataset_id,
                    quality_report_id,
                    review_id,
                )
                if task is None or tuple(task) != expected:
                    raise PublicationConflict(
                        "TASK_CONFLICT", "onboarding candidate, revision, or state changed"
                    )
                current_fingerprint = self.publication_fingerprint(
                    company_id=company_id,
                    dataset_id=dataset_id,
                    profile_id=profile_id,
                    quality_report_id=quality_report_id,
                )
                if current_fingerprint != computed_fingerprint:
                    raise PublicationConflict("REVIEW_STALE", "publication fingerprint changed")
            company = self.store._conn.execute(
                "SELECT active_publication_id FROM company WHERE company_id = ?",
                [company_id],
            ).fetchone()
            if company is None:
                raise PublicationConflict("COMPANY_NOT_FOUND", "company does not exist")
            active = company[0]
            if (
                expected_active_publication_id is not None
                and active != expected_active_publication_id
            ):
                raise PublicationConflict(
                    "PUBLICATION_CONFLICT", "active publication changed"
                )
            self.store._conn.execute(
                """
                INSERT INTO publication (
                  publication_id, company_id, dataset_id, profile_id,
                  quality_report_id, review_id, fingerprint, published_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, now())
                """,
                [
                    publication_id,
                    company_id,
                    dataset_id,
                    profile_id,
                    quality_report_id,
                    review_id,
                    computed_fingerprint,
                ],
            )
            entity_counts = {
                entity_type: count
                for entity_type, count in self.store._conn.execute(
                    """
                    SELECT entity_type, count(*) FROM dataset_row
                    WHERE dataset_id=? GROUP BY entity_type
                    """,
                    [dataset_id],
                ).fetchall()
            }
            financial_count = entity_counts.get("canonical_fact", 0)
            company_template = self.store._conn.execute(
                "SELECT reporting_template FROM company WHERE company_id=?",
                [company_id],
            ).fetchone()[0]
            capabilities = [
                (
                    "financials",
                    "READY" if financial_count else "DATA_BLOCKED",
                    None if financial_count else "published dataset has no canonical facts",
                    {"canonical_fact_rows": financial_count},
                ),
                (
                    "segments",
                    "READY" if entity_counts.get("segment_fact", 0) else "NOT_DISCLOSED",
                    None if entity_counts.get("segment_fact", 0) else "no published segment facts",
                    {"segment_fact_rows": entity_counts.get("segment_fact", 0)},
                ),
                ("market", "READY", None, {}),
                (
                    "valuation",
                    "NEEDS_CONFIGURATION"
                    if company_template == "us_gaap_operating_v1"
                    else "UNSUPPORTED_MODEL",
                    "confirm security-specific assumptions"
                    if company_template == "us_gaap_operating_v1"
                    else "no validated valuation model for this reporting template",
                    {},
                ),
            ]
            for module, capability_status, reason, coverage in capabilities:
                self.store._conn.execute(
                    """
                    INSERT INTO company_capability
                      (publication_id, module, status, reason, coverage_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        publication_id,
                        module,
                        capability_status,
                        reason,
                        canonical_json(coverage),
                    ],
                )
            if before_pointer_switch:
                before_pointer_switch()
            self.store._conn.execute(
                """
                UPDATE valuation_plan SET review_status='needs_review',
                  review_reason='财务发布版本已更新'
                WHERE company_id=? AND review_status='current'
                  AND (publication_id IS NULL OR publication_id <> ?)
                """,
                [company_id, publication_id],
            )
            self.store._conn.execute(
                """UPDATE company SET active_publication_id = ?,
                     quality_status = CASE WHEN ? IS NOT NULL AND ? IS NOT NULL
                       THEN 'VERIFIED' ELSE quality_status END,
                     updated_at = now() WHERE company_id = ?""",
                [publication_id, quality_report_id, review_id, company_id],
            )
            if onboarding_id is not None:
                self.store._conn.execute(
                    """
                    UPDATE company_onboarding SET state='PUBLISHED', current_step=NULL,
                      publication_id=?, revision=revision+1, updated_at=now()
                    WHERE onboarding_id=?
                    """,
                    [publication_id, onboarding_id],
                )
        row = self.store.query_one(
            "SELECT * FROM publication WHERE publication_id = ?", [publication_id]
        )
        return Publication.model_validate(row)

    def publish(
        self, task_id: str, expected_revision: int, fingerprint: str
    ) -> Publication:
        """Publish the currently approved task candidate with an atomic task transition."""
        task = self.store.query_one(
            "SELECT * FROM company_onboarding WHERE onboarding_id=?", [task_id]
        )
        if task is None:
            raise PublicationConflict("TASK_NOT_FOUND", "onboarding task does not exist")
        required = ("profile_id", "dataset_id", "quality_report_id", "review_id")
        if any(not task.get(field) for field in required):
            raise PublicationConflict("CANDIDATE_INCOMPLETE", "approved candidate is incomplete")
        quality = self.store.query_one(
            "SELECT result FROM quality_report WHERE report_id=? AND dataset_id=?",
            [task["quality_report_id"], task["dataset_id"]],
        )
        if quality is None or quality["result"] != "PASS":
            raise PublicationConflict("QUALITY_BLOCKED", "quality gate did not pass")
        review = self.store.query_one(
            "SELECT fingerprint, decision, company_id FROM adaptation_review WHERE review_id=?",
            [task["review_id"]],
        )
        if (
            review is None
            or review["decision"] != "APPROVE"
            or review["company_id"] != task["company_id"]
            or review["fingerprint"] != fingerprint
        ):
            raise PublicationConflict("REVIEW_STALE", "approval does not cover candidate")
        return self.publish_dataset(
            company_id=task["company_id"],
            dataset_id=task["dataset_id"],
            profile_id=task["profile_id"],
            quality_report_id=task["quality_report_id"],
            review_id=task["review_id"],
            fingerprint=fingerprint,
            onboarding_id=task_id,
            expected_task_revision=expected_revision,
        )
