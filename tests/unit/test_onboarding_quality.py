from __future__ import annotations

from datetime import date

import pytest

from equitylens.companies.models import CompanyIdentity, SecurityIdentity
from equitylens.companies.registry import CompanyRegistry
from equitylens.quality.models import CheckStatus
from equitylens.quality.rules import (
    balance_equation,
    cash_bridge,
    cash_bridge_with_disclosed_change,
    derive_standalone_quarter,
    eps_reconciliation,
    evidence_required,
    required_period_coverage,
    segment_reconciliation,
)
from equitylens.publication.builder import DatasetBuilder
from equitylens.publication.repository import PublicationRepository
from equitylens.quality.engine import QualityEngine, _segment_revenue_for_anchor
from equitylens.normalization.fiscal_periods import FiscalCalendar, derive_standalone_quarters
from equitylens.normalization.normalize import normalize_companyfacts
from equitylens.normalization.taxonomy.mappings import MappingRegistry
from equitylens.storage.raw_store import sha256_bytes


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


def test_cash_bridge_accepts_a_disclosed_change_including_exchange_effect():
    report = cash_bridge_with_disclosed_change(
        opening=100,
        operating=20,
        investing=-5,
        financing=-10,
        disclosed_change=5,
        closing=105,
        decimals=0,
    )

    assert report.status == CheckStatus.PASS
    assert report.actual["disclosed_change_including_fx"] == 5
    assert report.check_id == "CASH.bridge"


def test_cash_bridge_infers_nonzero_fx_without_mislabeling_it_a_mismatch():
    report = cash_bridge_with_disclosed_change(
        opening=100,
        operating=20,
        investing=-5,
        financing=-10,
        disclosed_change=15,
        closing=115,
        decimals=0,
    )
    assert report.status == CheckStatus.PASS
    assert report.check_id == "CASH.rollforward"
    assert report.severity.value == "WARNING"
    assert report.reason == "FX_OR_OTHER_NOT_SEPARATELY_DISCLOSED"
    assert report.actual["implied_fx_or_other"] == 10
    invalid = cash_bridge_with_disclosed_change(
        opening=100,
        operating=20,
        investing=-5,
        financing=-10,
        disclosed_change=15,
        closing=120,
        decimals=0,
    )
    assert invalid.status == CheckStatus.FAIL
    assert invalid.severity.value == "BLOCKER"


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


def test_segment_reconciliation_uses_only_the_latest_annual_basis():
    segments = [
        {"metric_name": "REVENUE", "fiscal_year": 2025, "period_type": "FY", "period_end": "2025-01-26", "value": 116},
        {"metric_name": "REVENUE", "fiscal_year": 2025, "period_type": "FY", "period_end": "2025-01-26", "value": 14},
        {"metric_name": "REVENUE", "fiscal_year": 2024, "period_type": "FY", "period_end": "2024-01-28", "value": 47},
        {"metric_name": "REVENUE", "fiscal_year": 2025, "period_type": "Q_STANDALONE", "period_end": "2024-04-28", "value": 22},
    ]

    selected = _segment_revenue_for_anchor(
        segments,
        {"fiscal_year": 2025, "period_end": "2025-01-26"},
    )

    assert [item["value"] for item in selected] == [116, 14]


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
            "applicability": {"SEGMENTS": "not_disclosed"},
            "evidence": [
                {
                    "evidence_id": "unrelated-security",
                    "source_document_id": "other-doc",
                    "content_sha256": "1" * 64,
                    "locator": "security identity",
                }
            ],
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
    segment = next(item for item in report.checks if item.check_id == "SEGMENTS.reconciliation")
    assert segment.status == CheckStatus.FAIL
    assert segment.reason == "EVIDENCE_MISSING"
    assert db.query_one(
        "SELECT result FROM quality_report WHERE report_id=?", [report.report_id]
    ) == {"result": "FAIL"}


def test_annual_balance_does_not_borrow_a_later_quarter_asset(db):
    company_id = "0000320193"
    profile_id = PublicationRepository(db).create_profile(
        company_id,
        version=199,
        schema_version=1,
        content={
            "company_id": company_id,
            "template": "us_gaap_operating_v1",
            "securities": [{"ticker": "AAPL"}],
            "applicability": {},
            "evidence": [],
        },
    )

    def fact(metric, value, fiscal_year, end, raw_id):
        return {
            "canonical_fact_id": f"fact-{raw_id}",
            "company_id": company_id,
            "canonical_metric": metric,
            "period_type": "FY" if metric == "REVENUE" else "INSTANT",
            "fiscal_year": fiscal_year,
            "period_end": end if metric == "REVENUE" else None,
            "instant_date": None if metric == "REVENUE" else end,
            "value": value,
            "unit": "USD",
            "status": "NORMALIZED",
            "mapping_rule_id": "fixture",
            "mapping_version": "fixture",
            "source_raw_fact_ids": [raw_id],
            "as_known_at": "2026-02-01" if fiscal_year == 2025 else "2026-05-01",
        }

    rows = []
    for metric, value, year, end, raw_id in (
        ("REVENUE", 100, 2025, "2025-12-31", "raw-revenue"),
        ("TOTAL_LIABILITIES", 60, 2025, "2025-12-31", "raw-liabilities"),
        ("TOTAL_EQUITY", 40, 2025, "2025-12-31", "raw-equity"),
        ("TOTAL_ASSETS", 100, 2026, "2026-03-31", "raw-assets-q1"),
    ):
        rows.append(("raw_fact", raw_id, {"raw_fact_id": raw_id, "source_document_id": "doc", "concept": metric}))
        rows.append(("canonical_fact", f"fact-{raw_id}", fact(metric, value, year, end, raw_id)))
    dataset_id = DatasetBuilder(db).seal_rows(
        company_id=company_id,
        profile_id=profile_id,
        source_manifest={"documents": []},
        rows=rows,
    )

    report = QualityEngine(db).validate(dataset_id)
    balance = next(item for item in report.checks if item.check_id == "BALANCE.equation")

    assert balance.status == CheckStatus.FAIL
    assert balance.reason == "BALANCE_INPUT_MISSING"


def test_liabilities_are_not_derived_across_filing_versions():
    companyfacts = {
        "facts": {
            "us-gaap": {
                "LiabilitiesAndStockholdersEquity": {
                    "units": {"USD": [{"end": "2025-12-31", "val": 100, "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2026-02-01", "accn": "filing-a"}]}
                },
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": {
                    "units": {"USD": [{"end": "2025-12-31", "val": 40, "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2026-03-01", "accn": "filing-b"}]}
                },
            }
        }
    }
    _, canonical, _ = normalize_companyfacts(
        companyfacts,
        MappingRegistry(),
        FiscalCalendar({2025: date(2025, 12, 31)}, {2025: []}),
        "companyfacts",
        "0000000001",
    )

    assert not any(
        fact["canonical_metric"] == "TOTAL_LIABILITIES" and fact["status"] == "CALCULATED"
        for fact in canonical
    )


def test_security_identity_blocks_an_unreviewed_active_share_class(db, tmp_path):
    company_id = "0000000001"
    registry = CompanyRegistry(db)
    registry.register_company(
        CompanyIdentity(
            company_id=company_id,
            cik=company_id,
            legal_name="Multiple Share Classes Inc.",
            reporting_template="us_gaap_operating_v1",
        ),
        legacy_ticker="MSC",
    )
    for security_id, ticker, class_label in (
        ("security-class-a", "MSC", "Class A"),
        ("security-class-b", "MSC.B", "Class B"),
    ):
        registry.register_security(
            SecurityIdentity(
                security_id=security_id,
                company_id=company_id,
                ticker=ticker,
                class_label=class_label,
                exchange="NYSE",
                currency="USD",
                instrument_type="COMMON_STOCK",
                identity_evidence={"source": "fixture"},
            )
        )

    source = tmp_path / "submissions.json"
    source.write_text("official identity bytes")
    digest = sha256_bytes(source.read_bytes())
    repository = PublicationRepository(db)
    profile_id = repository.create_profile(
        company_id,
        version=1,
        schema_version=1,
        content={
            "company_id": company_id,
            "template": "us_gaap_operating_v1",
            "securities": [
                {
                    "ticker": "MSC",
                    "class_label": "Class A",
                    "exchange": "NYSE",
                    "currency": "USD",
                    "instrument_type": "COMMON_STOCK",
                    "evidence": ["identity-a"],
                }
            ],
            "evidence": [
                {
                    "evidence_id": "identity-a",
                    "source_document_id": "identity-document",
                    "content_sha256": digest,
                    "locator": "fixture identity",
                }
            ],
        },
    )
    dataset_id = DatasetBuilder(db).seal_rows(
        company_id=company_id,
        profile_id=profile_id,
        source_manifest={"documents": ["identity-document"]},
        rows=[
            (
                "source_document",
                "identity-document",
                {
                    "source_document_id": "identity-document",
                    "company_id": company_id,
                    "provider": "SEC",
                    "document_type": "SUBMISSIONS_SNAPSHOT",
                    "source_url": "https://data.sec.gov/submissions/CIK0000000001.json",
                    "fetched_at": "2026-01-01T00:00:00",
                    "content_sha256": digest,
                    "local_path": str(source),
                },
            )
        ],
    )

    report = QualityEngine(db).validate(dataset_id)
    security = next(item for item in report.checks if item.check_id == "SECURITY.identity")

    assert security.status == CheckStatus.FAIL
    assert security.actual["unreviewed_registry"] == [
        {
            "ticker": "MSC.B",
            "class_label": "Class B",
            "exchange": "NYSE",
            "currency": "USD",
            "instrument_type": "COMMON_STOCK",
        }
    ]
