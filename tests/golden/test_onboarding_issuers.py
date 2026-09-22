"""Release goldens for issuer profiles, official snapshots, and fact lineage.

Expected values are transcribed from the named statement rows in each SEC 10-K;
the parser under test never generates this table.
"""

from __future__ import annotations

import hashlib
import gzip
import json
from pathlib import Path

import pytest

from equitylens.companies.models import CompanyIdentity, SecurityIdentity
from equitylens.companies.registry import CompanyRegistry, seed_security_id
from equitylens.issuers.profile import load_profile_yaml
from equitylens.normalization.fiscal_periods import FiscalCalendar
from equitylens.normalization.ixbrl import IxbrlDocument
from equitylens.normalization.normalize import normalize_companyfacts
from equitylens.normalization.segments import extract_segments, segment_config_from_profile
from equitylens.onboarding.pipeline import ProfileMappingRegistry
from equitylens.publication.builder import DatasetBuilder
from equitylens.publication.repository import PublicationRepository
from equitylens.quality.engine import QualityEngine
from equitylens.storage.raw_store import sha256_bytes


ROOT = Path(__file__).parents[2]
CASES = ["0000021344", "0000909832", "0000320193", "0000789019"]
REQUIRED_METRICS = {
    "REVENUE", "OPERATING_INCOME", "NET_INCOME", "BASIC_EPS", "DILUTED_EPS",
    "BASIC_WEIGHTED_AVG_SHARES", "DILUTED_WEIGHTED_AVG_SHARES", "TOTAL_ASSETS",
    "TOTAL_LIABILITIES", "STOCKHOLDERS_EQUITY", "OPERATING_CASH_FLOW",
    "INVESTING_CASH_FLOW", "FINANCING_CASH_FLOW", "CASH_AND_EQUIVALENTS",
}


def test_nvda_fixed_10k_preserves_filing_context_signs_and_segment_evidence():
    directory = ROOT / "tests" / "fixtures" / "onboarding" / "0001045810"
    manifest = json.loads((directory / "manifest.json").read_text())
    filing = manifest["annual_filing"]
    compressed = directory / filing["fixture_path"]
    assert hashlib.sha256(compressed.read_bytes()).hexdigest() == filing["compressed_sha256"]
    content = gzip.decompress(compressed.read_bytes())
    assert hashlib.sha256(content).hexdigest() == filing["content_sha256"]

    document = IxbrlDocument.parse(content)
    expected = manifest["expected"]

    def annual_value(concept: str) -> float:
        fact = next(
            item for item in document.facts(concept)
            if not item.dims and item.period_end == filing["period_end"]
        )
        assert fact.context_ref
        assert fact.locator.startswith("/")
        return fact.value

    assert annual_value("us-gaap:Revenues") == expected["revenue"]
    assert annual_value("us-gaap:NetCashProvidedByUsedInOperatingActivities") == expected["operating_cash_flow"]
    assert annual_value("us-gaap:NetCashProvidedByUsedInInvestingActivities") == expected["investing_cash_flow"]
    assert annual_value("us-gaap:NetCashProvidedByUsedInFinancingActivities") == expected["financing_cash_flow"]
    assert annual_value("us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect") == expected["net_change_in_cash_including_fx"]

    profile = load_profile_yaml(ROOT / manifest["profile_path"])
    config = segment_config_from_profile(profile)
    segments, warnings = extract_segments(
        "NVDA",
        document,
        config,
        FiscalCalendar({}, {}, fallback_mm_dd="01-31"),
        f"filing:{filing['accession']}:{filing['content_sha256']}",
    )
    assert warnings == []
    latest = {
        row["segment_name_reported"]: row["value"]
        for row in segments
        if row["period_type"] == "FY" and row["period_end"] == filing["period_end"]
    }
    assert latest == expected["segments"]
    assert sum(latest.values()) == expected["revenue"]

    evidence = {item.evidence_id: item for item in profile.evidence}
    segment_evidence = evidence[profile.segments.evidence[0]]
    assert segment_evidence.source_document_id == f"filing:{filing['accession']}:{filing['content_sha256']}"
    assert segment_evidence.content_sha256 == filing["content_sha256"]
    assert segment_evidence.locator in {
        fact.locator
        for fact in document.facts("us-gaap:Revenues")
        if fact.axis_members.get("StatementBusinessSegmentsAxis")
    }


def test_nvda_formal_profile_evidence_resolves_against_fixed_sec_bytes():
    directory = ROOT / "tests" / "fixtures" / "onboarding" / "0001045810"
    manifest = json.loads((directory / "manifest.json").read_text())["formal_profile"]
    profile = load_profile_yaml(ROOT / manifest["profile_path"])
    assert profile.version == 3
    assert len(profile.evidence) == 37

    locators_by_document = {}
    for filing in manifest["documents"]:
        compressed = (directory / filing["fixture_path"]).read_bytes()
        assert hashlib.sha256(compressed).hexdigest() == filing["compressed_sha256"]
        content = gzip.decompress(compressed)
        assert hashlib.sha256(content).hexdigest() == filing["content_sha256"]
        document_id = f"filing:{filing['accession']}:{filing['content_sha256']}"
        locators_by_document[document_id] = {
            item["locator"] for item in IxbrlDocument.parse(content).fact_catalog()
        } | {"/"}

    for evidence in profile.evidence:
        assert evidence.source_document_id in locators_by_document
        assert evidence.content_sha256 == evidence.source_document_id.rsplit(":", 1)[1]
        assert evidence.locator in locators_by_document[evidence.source_document_id]


def _case(cik: str):
    directory = ROOT / "tests" / "fixtures" / "onboarding" / cik
    manifest = json.loads((directory / "manifest.json").read_text())
    profile = load_profile_yaml(ROOT / manifest["profile_path"])
    return directory, manifest, profile


@pytest.mark.parametrize("cik", CASES)
def test_official_snapshot_identity_and_hashes(cik):
    directory, manifest, profile = _case(cik)
    assert profile.company_id == cik
    for snapshot in manifest["snapshots"]:
        path = (directory / snapshot["path"]).resolve()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == snapshot["sha256"]

    submissions_path = (directory / manifest["submissions_path"]).resolve()
    submissions = json.loads(submissions_path.read_text())
    assert submissions["cik"] == cik
    assert manifest["ticker"] in submissions["tickers"]
    assert manifest["exchange"] in submissions["exchanges"]
    recent = submissions["filings"]["recent"]
    filing = next(
        i
        for i, accession in enumerate(recent["accessionNumber"])
        if accession == manifest["annual_filing"]["accession"]
    )
    assert recent["form"][filing] == "10-K"
    assert recent["reportDate"][filing] == manifest["annual_filing"]["period_end"]


@pytest.mark.parametrize("cik", CASES)
def test_profile_core_metrics_match_independent_10k_goldens(cik):
    directory, manifest, profile = _case(cik)
    companyfacts_path = (directory / manifest["companyfacts_path"]).resolve()
    companyfacts = json.loads(companyfacts_path.read_text())
    submissions = json.loads((directory / manifest["submissions_path"]).resolve().read_text())
    calendar = FiscalCalendar.from_submissions(
        submissions, fallback_mm_dd=profile.fiscal_calendar.year_end
    )
    raw, canonical, _ = normalize_companyfacts(
        companyfacts,
        ProfileMappingRegistry(profile),
        calendar,
        source_document_id=f"SEC-companyfacts-CIK{cik}",
        company_id=cik,
    )
    raw_by_id = {row["raw_fact_id"]: row for row in raw}

    for metric, expected in manifest["expected_facts"].items():
        matches = [
            row
            for row in canonical
            if row["canonical_metric"] == metric
            and row["period_type"] == expected["period_type"]
            and row.get("fiscal_year") == expected["fiscal_year"]
            and str(row.get("period_end") or row.get("instant_date"))
            == expected["period_end"]
            and row["as_known_at"] == manifest["annual_filing"]["filed"]
        ]
        assert matches, f"{cik} missing {metric} at the reviewed period/accession"
        row = matches[-1]
        assert row["value"] == pytest.approx(expected["value"], rel=1e-12)
        assert row["unit"] == expected["unit"]
        source_ids = json.loads(row["source_raw_fact_ids"])
        assert source_ids
        allowed_concepts = (
            {concept for spec in profile.metrics.values() for concept in spec.concepts}
            if row["status"] == "CALCULATED"
            else set(profile.metrics[metric].concepts)
        )
        for source_id in source_ids:
            source = raw_by_id[source_id]
            assert f"{source['taxonomy']}:{source['concept']}" in allowed_concepts
            assert source["accession_number"] == expected["accession"]


@pytest.mark.parametrize("cik", CASES)
def test_issuer_goldens_cover_every_required_metric_or_explicit_gap(cik):
    directory, manifest, profile = _case(cik)
    expected = set(manifest["expected_facts"])
    missing = set(manifest.get("expected_missing") or {})
    assert expected | missing == REQUIRED_METRICS | {"CAPITAL_EXPENDITURES"}

    companyfacts = json.loads((directory / manifest["companyfacts_path"]).resolve().read_text())
    submissions = json.loads((directory / manifest["submissions_path"]).resolve().read_text())
    _, canonical, _ = normalize_companyfacts(
        companyfacts,
        ProfileMappingRegistry(profile),
        FiscalCalendar.from_submissions(submissions, fallback_mm_dd=profile.fiscal_calendar.year_end),
        source_document_id=f"SEC-companyfacts-CIK{cik}",
        company_id=cik,
    )
    for metric, gap in (manifest.get("expected_missing") or {}).items():
        assert not any(
            row["canonical_metric"] == metric
            and str(row.get("period_end") or row.get("instant_date")) == gap["period_end"]
            and row.get("as_known_at") == manifest["annual_filing"]["filed"]
            for row in canonical
        )


@pytest.mark.parametrize("cik", CASES)
def test_profile_evidence_is_bound_to_reviewed_snapshots(cik):
    directory, manifest, profile = _case(cik)
    snapshots = {snapshot["sha256"]: snapshot for snapshot in manifest["snapshots"]}
    for item in profile.evidence:
        snapshot = snapshots[item.content_sha256]
        kind = Path(snapshot["path"]).stem.lower()
        assert kind in item.source_document_id.lower()
        assert item.locator == snapshot["url"]


@pytest.mark.parametrize("cik", CASES)
def test_derived_quarters_keep_raw_sec_lineage(cik):
    directory, manifest, profile = _case(cik)
    companyfacts = json.loads((directory / manifest["companyfacts_path"]).resolve().read_text())
    submissions = json.loads((directory / manifest["submissions_path"]).resolve().read_text())
    raw, canonical, _ = normalize_companyfacts(
        companyfacts,
        ProfileMappingRegistry(profile),
        FiscalCalendar.from_submissions(submissions, fallback_mm_dd=profile.fiscal_calendar.year_end),
        source_document_id=f"SEC-companyfacts-CIK{cik}",
        company_id=cik,
    )
    raw_ids = {row["raw_fact_id"] for row in raw}
    derived = [row for row in canonical if row["status"] == "CALCULATED"]
    assert derived
    for row in derived:
        assert set(json.loads(row["source_raw_fact_ids"])) <= raw_ids


@pytest.mark.parametrize("cik", CASES[:2])
def test_new_issuers_keep_ixbrl_context_and_segment_blockers(db, cik):
    directory, manifest, profile = _case(cik)
    registry = CompanyRegistry(db)
    registry.register_company(
        CompanyIdentity(
            company_id=cik,
            cik=cik,
            legal_name=manifest["company_name"],
            reporting_template=profile.template,
            quality_status="PENDING",
        ),
        legacy_ticker=manifest["ticker"],
    )
    security_id = seed_security_id(cik, manifest["ticker"], manifest["exchange"])
    registry.register_security(
        SecurityIdentity(
            security_id=security_id,
            company_id=cik,
            ticker=manifest["ticker"],
            exchange=manifest["exchange"],
            currency="USD",
            instrument_type="COMMON_STOCK",
            identity_evidence={"manifest": str(directory / "manifest.json")},
        )
    )
    companyfacts_path = (directory / manifest["companyfacts_path"]).resolve()
    submissions = json.loads((directory / manifest["submissions_path"]).resolve().read_text())
    raw, canonical, _ = normalize_companyfacts(
        json.loads(companyfacts_path.read_text()),
        ProfileMappingRegistry(profile),
        FiscalCalendar.from_submissions(submissions, fallback_mm_dd=profile.fiscal_calendar.year_end),
        source_document_id=f"SEC-companyfacts-CIK{cik}",
        company_id=cik,
    )
    profile_id = PublicationRepository(db).create_profile(
        cik,
        version=profile.version,
        schema_version=profile.schema_version,
        content=profile.model_dump(mode="json", exclude={"content_sha256"}),
    )
    companyfacts_document = {
        "source_document_id": f"SEC-companyfacts-CIK{cik}",
        "company_id": cik,
        "provider": "SEC",
        "document_type": "COMPANYFACTS_SNAPSHOT",
        "source_url": next(item["url"] for item in manifest["snapshots"] if "companyfacts" in item["path"]),
        "fetched_at": manifest["captured_at"],
        "content_sha256": sha256_bytes(companyfacts_path.read_bytes()),
        "local_path": str(companyfacts_path),
    }
    submissions_path = (directory / manifest["submissions_path"]).resolve()
    submissions_snapshot = next(
        item for item in manifest["snapshots"] if "submissions" in item["path"]
    )
    submissions_document = {
        "source_document_id": f"SEC-submissions-CIK{cik}",
        "company_id": cik,
        "provider": "SEC",
        "document_type": "SUBMISSIONS_SNAPSHOT",
        "source_url": submissions_snapshot["url"],
        "fetched_at": manifest["captured_at"],
        "content_sha256": sha256_bytes(submissions_path.read_bytes()),
        "local_path": str(submissions_path),
    }
    documents = [submissions_document, companyfacts_document]
    rows = [
        ("source_document", document["source_document_id"], document)
        for document in documents
    ]
    rows += [("raw_fact", row["raw_fact_id"], row) for row in raw]
    rows += [("canonical_fact", row["canonical_fact_id"], row) for row in canonical]
    dataset_id = DatasetBuilder(db).seal_rows(
        company_id=cik,
        profile_id=profile_id,
        source_manifest={"manifest": str(directory / "manifest.json"), "documents": documents},
        rows=rows,
    )
    report = QualityEngine(db).validate(dataset_id)
    blockers = {
        check.check_id
        for check in report.checks
        if check.severity.value == "BLOCKER" and check.status.value in {"FAIL", "UNSUPPORTED"}
    }
    assert blockers == {"LINEAGE.filing_context", "SEGMENTS.reconciliation"}
