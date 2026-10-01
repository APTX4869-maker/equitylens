"""Immutable inputs shared by every published research module."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from equitylens.domain.companies import Company
from equitylens.metrics.engine import MetricEngine
from equitylens.publication.models import PublicationContext
from equitylens.publication.repository import PublicationRepository


@dataclass(frozen=True)
class PublishedResearchContext:
    store: Any
    company: Company
    publication: PublicationContext
    legacy: bool
    canonical_facts: tuple[dict[str, Any], ...]
    source_documents: tuple[dict[str, Any], ...]
    segment_facts: tuple[dict[str, Any], ...]
    profile_schema_version: int | None
    profile_content: dict[str, Any]
    metric_engine: MetricEngine
    evidence_ids: frozenset[str]

    @property
    def company_id(self) -> str:
        return self.company.cik

    @property
    def security_id(self) -> str | None:
        return self.company.security_id

    @property
    def publication_id(self) -> str:
        return self.publication.publication_id

    @property
    def dataset_id(self) -> str:
        return self.publication.dataset_id

    @property
    def profile_id(self) -> str:
        return self.publication.profile_id

    @classmethod
    def load(
        cls,
        store,
        company: Company,
        publication_id: str | None = None,
    ) -> "PublishedResearchContext":
        repository = PublicationRepository(store)
        publication = repository.context(company.cik, publication_id)
        return cls.from_publication(store, company, publication)

    @classmethod
    def from_publication(
        cls,
        store,
        company: Company,
        publication: PublicationContext,
    ) -> "PublishedResearchContext":
        repository = PublicationRepository(store)
        dataset = store.query_one(
            "SELECT parser_version FROM dataset_version WHERE dataset_id=?",
            [publication.dataset_id],
        )
        legacy = bool(dataset and dataset["parser_version"] == "legacy")
        canonical_facts = tuple(repository.facts(publication))
        source_documents = tuple(repository.entities(publication, "source_document"))
        segment_facts = tuple(repository.entities(publication, "segment_fact"))
        profile = store.query_one(
            "SELECT schema_version, content_json FROM issuer_profile_version WHERE profile_id=?",
            [publication.profile_id],
        )
        profile_content = profile["content_json"] if profile else {}
        if isinstance(profile_content, str):
            profile_content = json.loads(profile_content)

        # Legacy migration snapshots intentionally retain their old live-table
        # compatibility. Every reviewed publication is isolated to sealed facts.
        metric_engine = (
            MetricEngine(store)
            if legacy
            else MetricEngine(store, published_facts=list(canonical_facts))
        )
        evidence_ids = frozenset(
            str(value)
            for rows, key in (
                (canonical_facts, "canonical_fact_id"),
                (source_documents, "source_document_id"),
                (segment_facts, "segment_fact_id"),
            )
            for row in rows
            for value in [row.get(key)]
            if value
        )
        return cls(
            store=store,
            company=company,
            publication=publication,
            legacy=legacy,
            canonical_facts=canonical_facts,
            source_documents=source_documents,
            segment_facts=segment_facts,
            profile_schema_version=profile.get("schema_version") if profile else None,
            profile_content=profile_content,
            metric_engine=metric_engine,
            evidence_ids=evidence_ids,
        )

    def segments(self, *, kind: str = "segment", frequency: str = "annual", limit=None):
        from equitylens.api.segments_service import get_segments

        if self.legacy:
            return get_segments(
                self.store,
                self.company.ticker,
                kind=kind,
                frequency=frequency,
                limit=limit,
            )

        documents = {
            str(item["source_document_id"]): item
            for item in self.source_documents
            if item.get("source_document_id")
        }
        disclosure_by_document: dict[str, str] = {}
        for fact in self.canonical_facts:
            document_id = fact.get("source_document_id")
            disclosed_at = fact.get("as_known_at")
            if document_id and disclosed_at:
                key = str(document_id)
                disclosure_by_document[key] = max(
                    str(disclosed_at), disclosure_by_document.get(key, "")
                )
        rows = [dict(row) for row in self.segment_facts]
        for row in rows:
            document = documents.get(str(row.get("source_document_id")), {})
            for key in ("form_type", "filed_at", "accession_number", "source_url"):
                row[key] = document.get(key)
            row["filed_at"] = row.get("filed_at") or disclosure_by_document.get(
                str(row.get("source_document_id"))
            )

        published_config = None
        if self.profile_schema_version == 2:
            from equitylens.issuers.profile import IssuerProfileV2
            from equitylens.normalization.segments import segment_config_from_profile

            published_config = segment_config_from_profile(
                IssuerProfileV2.model_validate(self.profile_content)
            )
        return get_segments(
            self.store,
            self.company.ticker,
            kind=kind,
            frequency=frequency,
            limit=limit,
            published_rows=rows,
            published_config=published_config,
        )
