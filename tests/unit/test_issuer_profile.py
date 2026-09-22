from __future__ import annotations

import pytest
import yaml
from yaml.tokens import AliasToken, AnchorToken
from pydantic import ValidationError

from equitylens.issuers.profile import (
    IssuerProfile,
    IssuerProfileV2,
    IssuerProfileService,
    ProfileEvidenceError,
    load_profile_yaml,
    validate_profile_v2_against_bundle,
)
from equitylens.issuers.yaml_loader import load_strict_profile_yaml
from equitylens.issuers.candidate import build_candidate_artifact, build_candidate_profile
from equitylens.onboarding.models import FetchBundle, FetchDocument
from equitylens.normalization.ixbrl import IxbrlDocument, normalize_profiled_ixbrl
from equitylens.normalization.fiscal_periods import FiscalCalendar
from equitylens.normalization.taxonomy.mappings import MappingRegistry
from equitylens.onboarding.pipeline import ProfileMappingRegistry
from equitylens.normalization.segments import segment_config_from_profile


def valid_profile() -> dict:
    return {
        "schema_version": 1,
        "company_id": "0000000001",
        "version": 1,
        "template": "us_gaap_operating_v1",
        "fiscal_calendar": {"year_end": "12-31", "week_based": False},
        "metrics": {
            "REVENUE": {
                "concepts": ["us-gaap:Revenues"],
                "unit": "USD",
                "context": "consolidated",
                "period": "duration",
                "selection": "latest_filed_same_basis",
            }
        },
        "segments": {"axes": [], "reconciliation": "explicit_eliminations"},
        "cash_debt": {
            "cash_components": ["us-gaap:CashAndCashEquivalentsAtCarryingValue"],
            "debt_components": ["us-gaap:LongTermDebtNoncurrent"],
            "restricted_cash_policy": "separate",
        },
        "securities": [
            {
                "ticker": "EXAMPLE",
                "exchange": "NYSE",
                "currency": "USD",
                "instrument_type": "COMMON_STOCK",
                "evidence": ["evidence-1"],
            }
        ],
        "applicability": {"EPS": "required"},
        "evidence": [
            {
                "evidence_id": "evidence-1",
                "source_document_id": "doc-1",
                "content_sha256": "a" * 64,
                "locator": "statement:income",
            }
        ],
    }


def valid_profile_v2() -> dict:
    return {
        "schema_version": 2,
        "company_id": "0000000001",
        "version": 2,
        "template": "us_gaap_operating_v1",
        "template_evidence": ["filing-evidence"],
        "fiscal_calendar": {
            "year_end": "12-31",
            "week_based": False,
            "evidence": ["filing-evidence"],
        },
        "metrics": {
            "REVENUE": {
                "concepts": ["us-gaap:Revenues"],
                "unit": "USD",
                "context": "consolidated",
                "period": "duration",
                "selection": "latest_filed_same_basis",
                "evidence": ["filing-evidence"],
            }
        },
        "segments": {
            "parser": "not_applicable",
            "axes": [],
            "reconciliation": "not_applicable",
            "revenue_concept": None,
            "profit_concept": None,
            "evidence": ["filing-evidence"],
        },
        "cash_debt": {
            "cash_components": ["us-gaap:CashAndCashEquivalentsAtCarryingValue"],
            "debt_components": ["us-gaap:LongTermDebtNoncurrent"],
            "restricted_cash_policy": "separate",
            "evidence": ["filing-evidence"],
        },
        "eps_method": "reported_diluted",
        "eps_method_evidence": ["filing-evidence"],
        "securities": [
            {
                "ticker": "EXAMPLE",
                "exchange": "NYSE",
                "currency": "USD",
                "instrument_type": "COMMON_STOCK",
                "evidence": ["filing-evidence"],
            }
        ],
        "applicability": {
            "EPS": "required",
            "SEGMENTS": "not_applicable",
            "VALUATION": "required",
        },
        "applicability_evidence": {"SEGMENTS": ["filing-evidence"]},
        "evidence": [
            {
                "evidence_id": "filing-evidence",
                "source_document_id": "filing:one",
                "content_sha256": "a" * 64,
                "locator": "//*[@id='revenue']",
            }
        ],
    }


def test_profile_rejects_executable_or_unknown_fields():
    profile = valid_profile()
    profile["metrics"]["REVENUE"]["transform"] = "eval('danger')"

    with pytest.raises(ValidationError):
        IssuerProfile.model_validate(profile)


@pytest.mark.parametrize(
    "field,value",
    [
        ("evidence", []),
        ("securities", []),
        ("cash_debt", {"cash_components": [], "debt_components": [], "restricted_cash_policy": "separate"}),
    ],
)
def test_profile_rejects_empty_approval_evidence(field, value):
    profile = valid_profile()
    profile[field] = value

    with pytest.raises(ValidationError):
        IssuerProfile.model_validate(profile)


def test_yaml_loader_rejects_python_object_tags(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("!!python/object/apply:os.system ['echo unsafe']")

    with pytest.raises(ValueError, match="safe YAML"):
        load_profile_yaml(path)


def test_valid_profile_has_deterministic_content_hash():
    first = IssuerProfile.model_validate(valid_profile())
    second = IssuerProfile.model_validate(dict(reversed(list(valid_profile().items()))))

    assert first.content_sha256 == second.content_sha256


def test_candidate_only_recommends_concepts_present_in_snapshot():
    result = build_candidate_profile(
        company_id="0000000001",
        companyfacts={
            "facts": {"us-gaap": {"Revenues": {"units": {}}}}
        },
        common_mapping={
            "canonical_facts": {
                "REVENUE": {"concepts": ["us-gaap:Revenues"]},
                "NET_INCOME": {"concepts": ["us-gaap:NetIncomeLoss"]},
            }
        },
    )

    assert result["metrics"] == {
        "REVENUE": {"concepts": ["us-gaap:Revenues"], "candidate_only": True}
    }
    assert result["unresolved_metrics"] == ["NET_INCOME"]
    assert result["review_status"] == "NEEDS_ADAPTATION"


def test_candidate_artifact_is_complete_review_only_and_deterministic():
    document = FetchDocument(
        document_id="filing:one",
        document_type="FILING_DOCUMENT",
        accession_number="one",
        form_type="10-K",
        filed_at="2025-03-01",
        report_date="2024-12-31",
        fetched_at="2025-03-01T00:00:00Z",
        source_url="https://www.sec.gov/example",
        content_sha256="a" * 64,
        raw_locator="sec/one/primary.html",
    )
    bundle = FetchBundle(
        fetch_bundle_id="bundle-1",
        onboarding_id="task-1",
        fetcher_version="fetch.v2",
        parser_version="parser.v2",
        content_sha256="b" * 64,
        documents=[document],
        created_at="2025-03-01T00:00:00Z",
    )
    kwargs = {
        "onboarding_id": "task-1",
        "task_revision": 3,
        "company_id": "0000000001",
        "bundle": bundle,
        "mapping": MappingRegistry(),
        "fact_catalogs": {
            "filing:one": [{
                "concept": "us-gaap:Revenues", "context_ref": "ctx",
                "unit_ref": "USD", "locator": "/html/body/ix:nonFraction[1]",
            }],
        },
        "securities": [{
            "ticker": "ONE", "exchange": "NYSE", "currency": "USD",
            "instrument_type": "COMMON_STOCK",
        }],
        "fiscal_year_end": "1231",
    }
    first = build_candidate_artifact(**kwargs)
    second = build_candidate_artifact(**kwargs)

    assert set(first.profile) == {
        "schema_version", "company_id", "version", "template", "template_evidence",
        "fiscal_calendar", "metrics", "segments", "cash_debt", "eps_method",
        "eps_method_evidence", "securities", "applicability",
        "applicability_evidence", "evidence",
    }
    assert first.profile["metrics"]["REVENUE"]["concepts"] == ["us-gaap:Revenues"]
    assert first.profile["fiscal_calendar"]["year_end"] == "12-31"
    assert first.profile["metrics"]["NET_INCOME"]["concepts"] == []
    assert first.profile["segments"]["parser"] is None
    assert {item.path for item in first.unresolved_fields} >= {
        "metrics.NET_INCOME.concepts", "segments.parser"
    }
    assert all(item.reason and item.action for item in first.unresolved_fields)
    assert yaml.safe_load(first.yaml_text) == first.profile
    assert not any(
        isinstance(token, (AliasToken, AnchorToken))
        for token in yaml.scan(first.yaml_text)
    )
    assert "# REVIEW REQUIRED:" in first.yaml_text
    assert first.review_status == "NEEDS_ADAPTATION"
    assert first.input_sha256 == second.input_sha256
    assert first.content_sha256 == second.content_sha256
    assert first.yaml_sha256 == second.yaml_sha256
    assert first.yaml_text == second.yaml_text


def test_profile_v2_enforces_segment_conditions_and_all_evidence_references():
    parsed = IssuerProfileV2.model_validate(valid_profile_v2())
    assert parsed.schema_version == 2

    invalid = valid_profile_v2()
    invalid["segments"] = {
        **invalid["segments"],
        "parser": "ixbrl_segments_v1",
        "reconciliation": "explicit_eliminations",
    }
    invalid["applicability"]["SEGMENTS"] = "required"
    with pytest.raises(ValidationError, match="axes"):
        IssuerProfileV2.model_validate(invalid)

    missing = valid_profile_v2()
    missing["metrics"]["REVENUE"]["evidence"] = ["does-not-exist"]
    with pytest.raises(ValidationError, match="does-not-exist"):
        IssuerProfileV2.model_validate(missing)


def test_new_profile_import_validation_rejects_schema_v1():
    service = IssuerProfileService()
    with pytest.raises(ValueError, match="schema_version 2"):
        service.validate_for_import(valid_profile())
    assert service.validate_for_import(valid_profile_v2()).schema_version == 2


@pytest.mark.parametrize(
    "text,match",
    [
        ("schema_version: 2\nschema_version: 2\n", "duplicate"),
        ("&base {schema_version: 2}\n", "anchors"),
        ("schema_version: !!int '2'\n", "tags"),
        ("1: value\n", "keys must be strings"),
        ("schema_version: 2\n---\nschema_version: 2\n", "exactly one"),
    ],
)
def test_strict_profile_yaml_rejects_ambiguous_yaml(text, match):
    with pytest.raises(ValueError, match=match):
        load_strict_profile_yaml(text)


def test_strict_profile_yaml_enforces_bounded_shape_and_placeholders():
    with pytest.raises(ValueError, match="524288"):
        load_strict_profile_yaml("x" * (512 * 1024 + 1))
    with pytest.raises(ValueError, match="depth"):
        load_strict_profile_yaml("value: " + "[" * 21 + "0" + "]" * 21)
    with pytest.raises(ValueError, match="scalar"):
        load_strict_profile_yaml("value: '" + "x" * (64 * 1024 + 1) + "'")
    with pytest.raises(ValueError, match="20000"):
        load_strict_profile_yaml("values: [" + ",".join("0" for _ in range(20_001)) + "]")
    candidate = valid_profile_v2()
    candidate["metrics"]["REVENUE"]["unit"] = "__REVIEW_REQUIRED__"
    with pytest.raises(ValueError, match="review-required"):
        load_strict_profile_yaml(yaml.safe_dump(candidate))


def test_strict_profile_yaml_returns_profile_v2():
    parsed = load_strict_profile_yaml(yaml.safe_dump(valid_profile_v2()))
    assert parsed.schema_version == 2


def test_profile_v2_evidence_must_resolve_to_current_bundle_document():
    profile = IssuerProfileV2.model_validate(valid_profile_v2())
    document = FetchDocument(
        document_id="filing:one",
        document_type="FILING_DOCUMENT",
        accession_number="one",
        form_type="10-K",
        filed_at="2025-03-01",
        report_date="2025-01-31",
        fetched_at="2025-03-01T00:00:00Z",
        source_url="https://www.sec.gov/example",
        content_sha256="a" * 64,
        raw_locator="sec/one/primary.html",
    )
    bundle = FetchBundle(
        fetch_bundle_id="bundle",
        onboarding_id="task",
        fetcher_version="v1",
        parser_version="v1",
        content_sha256="b" * 64,
        documents=[document],
        created_at="2025-03-01T00:00:00Z",
    )
    validate_profile_v2_against_bundle(profile, bundle)

    wrong_bundle = bundle.model_copy(
        update={"documents": [document.model_copy(update={"content_sha256": "c" * 64})]}
    )
    with pytest.raises(ProfileEvidenceError, match="filing:one"):
        validate_profile_v2_against_bundle(profile, wrong_bundle)


def test_ixbrl_numeric_fact_retains_real_context_and_locator():
    document = IxbrlDocument.parse(
        b"""<html xmlns:ix='http://www.xbrl.org/2013/inlineXBRL'
        xmlns:xbrli='http://www.xbrl.org/2003/instance'>
        <xbrli:context id='ctx'><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate>
        <xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
        <ix:nonFraction name='us-gaap:Revenues' contextRef='ctx' unitRef='USD' sign='-'>100</ix:nonFraction>
        </html>"""
    )

    fact = document.facts("us-gaap:Revenues")[0]
    assert fact.context_ref == "ctx"
    assert fact.locator.startswith("/")
    assert fact.value == -100


def test_segment_config_is_derived_from_reviewed_profile_v2():
    raw = valid_profile_v2()
    raw["segments"] = {
        "parser": "ixbrl_segments_v1",
        "axes": [
            {
                "name": "StatementBusinessSegmentsAxis",
                "kind": "segment",
                "label": "Business segments",
                "members": {"ComputeMember": {"label": "Compute", "aggregate": False}},
                "evidence": ["filing-evidence"],
            }
        ],
        "reconciliation": "explicit_eliminations",
        "revenue_concept": "us-gaap:Revenues",
        "profit_concept": None,
        "evidence": ["filing-evidence"],
    }
    raw["applicability"]["SEGMENTS"] = "required"
    raw["applicability_evidence"] = {}
    profile = IssuerProfileV2.model_validate(raw)

    config = segment_config_from_profile(profile)
    assert config.axes[0].members["ComputeMember"]["label"] == "Compute"
    assert config.revenue_concept == "us-gaap:Revenues"


def test_profiled_ixbrl_normalization_preserves_context_and_locator():
    profile = IssuerProfileV2.model_validate(valid_profile_v2())
    document = IxbrlDocument.parse(
        b"""<html xmlns:ix='http://www.xbrl.org/2013/inlineXBRL'
        xmlns:xbrli='http://www.xbrl.org/2003/instance'>
        <xbrli:context id='ctx'><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate>
        <xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
        <ix:nonFraction name='us-gaap:Revenues' contextRef='ctx' unitRef='USD'>100</ix:nonFraction>
        </html>"""
    )
    raw, canonical, _ = normalize_profiled_ixbrl(
        document,
        profile=profile,
        mappings=ProfileMappingRegistry(profile),
        calendar=FiscalCalendar({}, {}, fallback_mm_dd="12-31"),
        source_document_id="filing:one",
        company_id="0000000001",
        accession_number="one",
        form_type="10-K",
        filed_at="2026-02-01",
    )

    assert raw[0]["context_id"] == "ctx"
    assert raw[0]["locator"].startswith("/")
    assert canonical[0]["source_document_id"] == "filing:one"
