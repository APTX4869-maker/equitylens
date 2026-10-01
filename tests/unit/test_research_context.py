from __future__ import annotations

from equitylens.companies.models import CompanyIdentity, SecurityIdentity
from equitylens.companies.registry import CompanyRegistry
from equitylens.domain.companies import get_company
from equitylens.publication.builder import DatasetBuilder
from equitylens.publication.repository import PublicationRepository


def _fact(company_id: str, fact_id: str, value: float) -> dict:
    return {
        "canonical_fact_id": fact_id,
        "company_id": company_id,
        "canonical_metric": "REVENUE",
        "period_type": "FY",
        "fiscal_year": 2025,
        "fiscal_quarter": None,
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "instant_date": None,
        "value": value,
        "unit": "USD",
        "status": "REPORTED",
        "mapping_rule_id": "published-fixture",
        "mapping_version": "v1",
        "source_raw_fact_ids": [],
        "as_known_at": "2026-01-01T00:00:00",
        "created_at": "2026-01-01T00:00:00",
        "warnings_json": [],
        "source_document_id": None,
    }


def test_published_research_context_ignores_mutable_split_brain_rows(db):
    from equitylens.research.context import PublishedResearchContext

    company_id = "0000000401"
    security_id = "40140140-1401-4401-8401-401401401401"
    registry = CompanyRegistry(db)
    registry.register_company(
        CompanyIdentity(
            company_id=company_id,
            cik=company_id,
            legal_name="Published Research Fixture",
            reporting_template="us_gaap_operating_v1",
        ),
        legacy_ticker="PRCX",
    )
    registry.register_security(
        SecurityIdentity(
            security_id=security_id,
            company_id=company_id,
            ticker="PRCX",
            exchange="NYSE",
            currency="USD",
            instrument_type="COMMON_STOCK",
            identity_evidence={"source": "fixture"},
        )
    )
    publications = PublicationRepository(db)
    profile_id = publications.create_profile(
        company_id,
        version=1,
        schema_version=1,
        content={"company_id": company_id, "marker": "published-profile"},
    )
    dataset_id = DatasetBuilder(db).seal_rows(
        company_id=company_id,
        profile_id=profile_id,
        source_manifest={"documents": []},
        rows=[("canonical_fact", "published-revenue", _fact(
            company_id, "published-revenue", 100.0
        ))],
    )
    publication = publications.publish_dataset(
        company_id=company_id,
        dataset_id=dataset_id,
        profile_id=profile_id,
        quality_report_id=None,
        review_id=None,
    )
    db._conn.execute(
        """INSERT INTO canonical_fact (
             canonical_fact_id, company_id, canonical_metric, period_type,
             fiscal_year, period_start, period_end, value, unit, status,
             mapping_rule_id, mapping_version, source_raw_fact_ids,
             as_known_at, created_at, warnings_json
           ) VALUES (
             'mutable-revenue', ?, 'REVENUE', 'FY', 2025,
             '2025-01-01', '2025-12-31', 999, 'USD', 'REPORTED',
             'mutable-fixture', 'v1', '[]', now(), now(), '[]'
           )""",
        [company_id],
    )

    context = PublishedResearchContext.load(
        db, get_company("PRCX", store=db), publication.publication_id
    )
    revenue = context.metric_engine.compute("REVENUE", company_id, frequency="annual")

    assert context.publication_id == publication.publication_id
    assert context.dataset_id == dataset_id
    assert context.profile_content["marker"] == "published-profile"
    assert [point.value for point in revenue] == [100.0]
    assert context.evidence_ids == frozenset({"published-revenue"})
    assert "mutable-revenue" not in context.evidence_ids
