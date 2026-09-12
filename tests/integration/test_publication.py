from __future__ import annotations

import pytest

from equitylens.companies.models import CompanyIdentity, SecurityIdentity
from equitylens.companies.registry import CompanyRegistry
from equitylens.publication.builder import DatasetBuilder
from equitylens.publication.repository import (
    PublicationConflict,
    PublicationRepository,
)


def _fact(company_id: str, value: float, fact_id: str) -> dict:
    return {
        "canonical_fact_id": fact_id,
        "company_id": company_id,
        "canonical_metric": "REVENUE",
        "period_type": "FY",
        "fiscal_year": 2025,
        "fiscal_quarter": None,
        "period_start": "2024-01-01",
        "period_end": "2024-12-31",
        "instant_date": None,
        "value": value,
        "unit": "USD",
        "status": "REPORTED",
        "mapping_rule_id": "fixture-revenue",
        "mapping_version": "v1",
        "source_raw_fact_ids": [],
        "as_known_at": "2026-01-01T00:00:00",
        "created_at": "2026-01-01T00:00:00",
        "warnings_json": [],
        "source_document_id": None,
    }


@pytest.fixture()
def publication_case(db):
    company_id = "0000000001"
    registry = CompanyRegistry(db)
    registry.register_company(
        CompanyIdentity(
            company_id=company_id,
            cik=company_id,
            legal_name="Publication Fixture Inc.",
            reporting_template="us_gaap_operating_v1",
        ),
        legacy_ticker="PUB",
    )
    registry.register_security(
        SecurityIdentity(
            security_id="11111111-1111-4111-8111-111111111111",
            company_id=company_id,
            ticker="PUB",
            exchange="NYSE",
            currency="USD",
            instrument_type="COMMON_STOCK",
            identity_evidence={"source": "fixture"},
        )
    )
    repository = PublicationRepository(db)
    builder = DatasetBuilder(db)
    profile_id = repository.create_profile(
        company_id,
        version=1,
        schema_version=1,
        content={"company_id": company_id, "template": "us_gaap_operating_v1"},
    )
    first_dataset = builder.seal_rows(
        company_id=company_id,
        profile_id=profile_id,
        source_manifest={"documents": ["doc-1"]},
        rows=[("canonical_fact", "fact-1", _fact(company_id, 100, "fact-1"))],
    )
    first = repository.publish_dataset(
        company_id=company_id,
        dataset_id=first_dataset,
        profile_id=profile_id,
        quality_report_id=None,
        review_id=None,
    )

    class Case:
        def __init__(self):
            self.candidate_id = None

        def visible_facts(self):
            return repository.facts(repository.context(company_id))

        def build_candidate(self, revenue):
            self.candidate_id = builder.seal_rows(
                company_id=company_id,
                profile_id=profile_id,
                source_manifest={"documents": ["doc-1"]},
                rows=[
                    (
                        "canonical_fact",
                        "fact-candidate",
                        _fact(company_id, revenue, "fact-candidate"),
                    )
                ],
            )

    return Case(), repository, builder, profile_id, first


def test_candidate_does_not_change_visible_facts(publication_case):
    case, *_ = publication_case
    before = case.visible_facts()
    case.build_candidate(revenue=999)

    assert case.visible_facts() == before


def test_publication_context_rejects_other_company(publication_case):
    _, repository, _, _, publication = publication_case

    with pytest.raises(PublicationConflict) as exc:
        repository.context("0000789019", publication.publication_id)
    assert exc.value.code == "PUBLICATION_NOT_FOUND"


def test_failed_publish_keeps_previous_facts_visible(publication_case):
    case, repository, builder, profile_id, first = publication_case
    candidate = builder.seal_rows(
        company_id="0000000001",
        profile_id=profile_id,
        source_manifest={"documents": ["doc-1"]},
        rows=[
            (
                "canonical_fact",
                "fact-2",
                _fact("0000000001", 999, "fact-2"),
            )
        ],
    )

    def fail_before_pointer_switch():
        raise RuntimeError("injected commit-boundary failure")

    with pytest.raises(RuntimeError, match="commit-boundary"):
        repository.publish_dataset(
            company_id="0000000001",
            dataset_id=candidate,
            profile_id=profile_id,
            quality_report_id=None,
            review_id=None,
            before_pointer_switch=fail_before_pointer_switch,
        )

    context = repository.context("0000000001")
    assert context.publication_id == first.publication_id
    assert case.visible_facts()[0]["value"] == 100


def test_dataset_payload_hash_is_verified_on_read(publication_case):
    _, repository, _, _, first = publication_case
    context = repository.context("0000000001", first.publication_id)
    repository.store._conn.execute(
        "UPDATE dataset_row SET payload_json = ? WHERE dataset_id = ?",
        ['{"value": 999}', context.dataset_id],
    )

    with pytest.raises(PublicationConflict) as exc:
        repository.facts(context)
    assert exc.value.code == "DATASET_HASH_MISMATCH"


def test_dataset_rejects_unresolved_raw_fact_reference(publication_case):
    _, _, builder, profile_id, _ = publication_case
    payload = _fact("0000000001", 100, "broken-lineage")
    payload["source_raw_fact_ids"] = ["missing-raw-fact"]

    with pytest.raises(ValueError, match="unresolved raw fact"):
        builder.seal_rows(
            company_id="0000000001",
            profile_id=profile_id,
            source_manifest={"documents": []},
            rows=[("canonical_fact", "broken-lineage", payload)],
        )
