"""Seal validated candidate output as an immutable dataset."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Iterable
from typing import Any

from equitylens.publication.models import (
    canonical_json,
    sha256_json,
    validate_dataset_payload,
)
from equitylens.storage.duckdb_store import DuckDBStore
from equitylens.storage.writer import writer_for


DatasetRows = Iterable[tuple[str, str, dict[str, Any]]]


class DatasetBuilder:
    def __init__(
        self,
        store: DuckDBStore,
        candidate_provider: Callable[[str, str], tuple[dict, DatasetRows]] | None = None,
        *,
        parser_version: str = "onboarding.v1",
        rule_version: str = "quality.v1",
    ) -> None:
        self.store = store
        self.candidate_provider = candidate_provider
        self.parser_version = parser_version
        self.rule_version = rule_version

    def build(self, task_id: str, profile_id: str) -> str:
        if self.candidate_provider is None:
            raise RuntimeError("candidate_provider is required for build()")
        manifest, rows = self.candidate_provider(task_id, profile_id)
        profile = self.store.query_one(
            "SELECT company_id FROM issuer_profile_version WHERE profile_id = ?",
            [profile_id],
        )
        if profile is None:
            raise ValueError("unknown issuer profile")
        return self.seal_rows(
            company_id=profile["company_id"],
            profile_id=profile_id,
            source_manifest=manifest,
            rows=rows,
        )

    def seal_rows(
        self,
        *,
        company_id: str,
        profile_id: str,
        source_manifest: dict[str, Any],
        rows: DatasetRows,
    ) -> str:
        profile = self.store.query_one(
            "SELECT company_id FROM issuer_profile_version WHERE profile_id = ?",
            [profile_id],
        )
        if profile is None or profile["company_id"] != company_id:
            raise ValueError("profile does not belong to dataset company")
        prepared: list[tuple[str, str, str, str]] = []
        seen: set[tuple[str, str]] = set()
        referenced_raw_facts: set[str] = set()
        for entity_type, row_id, payload in rows:
            key = (entity_type, row_id)
            if key in seen:
                raise ValueError(f"duplicate dataset row {entity_type}:{row_id}")
            seen.add(key)
            validated = validate_dataset_payload(entity_type, payload)
            payload_company = validated.get("company_id")
            if payload_company is not None and payload_company != company_id:
                raise ValueError("dataset row belongs to a different company")
            payload_json = canonical_json(validated)
            if entity_type == "canonical_fact":
                referenced_raw_facts.update(validated["source_raw_fact_ids"])
            prepared.append(
                (entity_type, row_id, payload_json, sha256_json(validated))
            )
        prepared.sort(key=lambda item: (item[0], item[1]))
        included_raw_facts = {
            row_id for entity_type, row_id, _, _ in prepared if entity_type == "raw_fact"
        }
        unresolved = referenced_raw_facts - included_raw_facts
        if unresolved:
            placeholders = ", ".join("?" for _ in unresolved)
            existing = {
                row["raw_fact_id"]
                for row in self.store.query(
                    f"SELECT raw_fact_id FROM raw_fact WHERE raw_fact_id IN ({placeholders})",
                    sorted(unresolved),
                )
            }
            unresolved -= existing
        if unresolved:
            raise ValueError(
                "unresolved raw fact references: " + ", ".join(sorted(unresolved))
            )
        dataset_hash = hashlib.sha256(
            "\n".join(f"{a}:{b}:{d}" for a, b, _, d in prepared).encode()
        ).hexdigest()
        dataset_id = str(uuid.uuid4())
        with writer_for(self.store).transaction(self.store):
            self.store._conn.execute(
                """
                INSERT INTO dataset_version (
                  dataset_id, company_id, profile_id, source_manifest_json,
                  parser_version, rule_version, dataset_hash, state, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'SEALED', now())
                """,
                [
                    dataset_id,
                    company_id,
                    profile_id,
                    canonical_json(source_manifest),
                    self.parser_version,
                    self.rule_version,
                    dataset_hash,
                ],
            )
            for entity_type, row_id, payload_json, payload_sha in prepared:
                self.store._conn.execute(
                    "INSERT INTO dataset_row VALUES (?, ?, ?, ?, ?)",
                    [dataset_id, entity_type, row_id, payload_json, payload_sha],
                )
        return dataset_id
