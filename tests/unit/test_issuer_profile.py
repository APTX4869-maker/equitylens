from __future__ import annotations

import pytest
from pydantic import ValidationError

from equitylens.issuers.profile import IssuerProfile, load_profile_yaml
from equitylens.issuers.candidate import build_candidate_profile


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
