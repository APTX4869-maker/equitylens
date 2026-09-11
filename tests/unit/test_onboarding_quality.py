from __future__ import annotations

import pytest
from datetime import date

from equitylens.quality.models import CheckStatus
from equitylens.quality.rules import (
    balance_equation,
    cash_bridge,
    derive_standalone_quarter,
    eps_reconciliation,
    evidence_required,
    required_period_coverage,
    segment_reconciliation,
)
from equitylens.publication.builder import DatasetBuilder
from equitylens.publication.repository import PublicationRepository
from equitylens.quality.engine import QualityEngine
from equitylens.normalization.fiscal_periods import FiscalCalendar, derive_standalone_quarters


@pytest.fixture()
def quality_case():
    class Case:
        cash_bridge = staticmethod(cash_bridge)

    return Case()


def test_cash_bridge_uses_same_cash_definition(quality_case):
    report = quality_case.cash_bridge(
        opening=100,
        operating=20,
        investing=-5,
        financing=-10,
        fx=2,
        closing=107,
        decimals=0,
    )
    assert report.status == CheckStatus.PASS
    assert quality_case.cash_bridge(
        opening=100,
        operating=20,
        investing=-5,
        financing=-10,
        fx=2,
        closing=117,
        decimals=0,
    ).status == CheckStatus.FAIL


def test_rounding_intervals_can_reconcile_reported_millions():
    result = balance_equation(
        assets=100_000_000,
        liabilities=60_400_000,
        equity=40_400_000,
        mezzanine=0,
        decimals=-6,
    )

    assert result.status == CheckStatus.PASS
    assert result.tolerance["basis"] == "xbrl_decimals"


def test_cumulative_quarter_requires_same_year_basis_and_revision():
    assert derive_standalone_quarter(
        current_ytd=75,
        previous_ytd=40,
        fiscal_year=2026,
        previous_fiscal_year=2026,
        basis="reported-v2",
        previous_basis="reported-v2",
    ) == 35

    with pytest.raises(ValueError, match="same fiscal year and basis"):
        derive_standalone_quarter(
            current_ytd=75,
            previous_ytd=40,
            fiscal_year=2026,
            previous_fiscal_year=2025,
            basis="reported-v2",
            previous_basis="reported-v1",
        )


def test_normalizer_does_not_difference_across_restatement_sets():
    calendar = FiscalCalendar(
        {2026: date(2026, 12, 31)},
        {2026: [date(2026, 3, 31), date(2026, 6, 30), date(2026, 9, 30)]},
    )
    facts = [
        {
            "canonical_fact_id": "q1",
            "canonical_metric": "REVENUE",
            "period_type": "Q_STANDALONE",
            "fiscal_quarter": 1,
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
            "value": 10,
            "unit": "USD",
            "restatement_set_id": "old",
        },
        {
            "canonical_fact_id": "ytd6",
            "canonical_metric": "REVENUE",
            "period_type": "YTD_6M",
            "period_end": "2026-06-30",
            "value": 25,
            "unit": "USD",
            "restatement_set_id": "new",
        },
    ]

    assert derive_standalone_quarters(facts, 2026, calendar) == []


def test_eps_is_not_treated_as_unconditional_net_income_identity():
    result = eps_reconciliation(
        reported_eps=2.50,
        numerator=100,
        weighted_shares=50,
        explicit_method=None,
    )

    assert result.status == CheckStatus.FAIL
    assert result.reason == "EPS_METHOD_UNPROVEN"


def test_segment_reconciliation_requires_explicit_eliminations():
    passed = segment_reconciliation(
        consolidated=100,
        segments=[60, 50],
        eliminations=-10,
        decimals=0,
    )
    failed = segment_reconciliation(
        consolidated=100,
        segments=[60, 50],
        eliminations=None,
        decimals=0,
    )

    assert passed.status == CheckStatus.PASS
    assert failed.status == CheckStatus.FAIL
    assert failed.reason == "SEGMENT_ELIMINATION_MISSING"


def test_required_period_coverage_reports_missing_quarter():
    result = required_period_coverage(
        annual_years=[2023, 2024, 2025],
        quarters=["2024Q2", "2024Q3", "2024Q4", "2025Q1", "2025Q2", "2025Q3", "2025Q4"],
        required_annual=3,
        required_quarters=8,
    )

    assert result.status == CheckStatus.FAIL
    assert result.actual["quarter_count"] == 7


def test_not_applicable_without_evidence_is_a_blocker():
    result = evidence_required(
        check_id="EPS.applicability",
        claimed_status=CheckStatus.NOT_APPLICABLE,
        evidence=[],
    )

    assert result.status == CheckStatus.FAIL
    assert result.reason == "EVIDENCE_MISSING"


def test_engine_blocks_unsupported_template_and_corrupt_source(db, tmp_path):
    source = tmp_path / "filing.html"
    source.write_text("actual bytes")
    repository = PublicationRepository(db)
    profile_id = repository.create_profile(
        "0000320193",
        version=99,
        schema_version=1,
        content={
            "company_id": "0000320193",
            "template": "bank_v1",
            "securities": [{"ticker": "AAPL"}],
            "applicability": {},
            "evidence": [],
        },
    )
    rows = [
        (
            "source_document",
            "doc-1",
            {
                "source_document_id": "doc-1",
                "company_id": "0000320193",
                "provider": "SEC",
                "document_type": "FILING_DOCUMENT",
                "source_url": "https://www.sec.gov/example",
                "fetched_at": "2026-01-01T00:00:00",
                "content_sha256": "0" * 64,
                "local_path": str(source),
            },
        ),
        (
            "raw_fact",
            "raw-1",
            {
                "raw_fact_id": "raw-1",
                "source_document_id": "doc-1",
                "concept": "us-gaap:Revenues",
            },
        ),
        (
            "canonical_fact",
            "fact-1",
            {
                "canonical_fact_id": "fact-1",
                "company_id": "0000320193",
                "canonical_metric": "REVENUE",
                "period_type": "FY",
                "fiscal_year": 2025,
                "value": 100,
                "unit": "USD",
                "status": "REPORTED",
                "mapping_rule_id": "fixture",
                "mapping_version": "v1",
                "source_raw_fact_ids": ["raw-1"],
            },
        ),
    ]
    dataset_id = DatasetBuilder(db).seal_rows(
        company_id="0000320193",
        profile_id=profile_id,
        source_manifest={"documents": ["doc-1"]},
        rows=rows,
    )

    report = QualityEngine(db).validate(dataset_id)

    assert report.result == "FAIL"
    assert any(
        item.reason == "TEMPLATE_UNSUPPORTED" and item.status == CheckStatus.UNSUPPORTED
        for item in report.checks
    )
    assert any(item.reason == "SOURCE_CORRUPTED" for item in report.checks)
    assert db.query_one(
        "SELECT result FROM quality_report WHERE report_id=?", [report.report_id]
    ) == {"result": "FAIL"}
