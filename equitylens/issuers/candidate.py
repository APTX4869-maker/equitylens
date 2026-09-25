"""Generate deterministic, evidence-limited profile candidates for review."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal, TYPE_CHECKING

import yaml
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from equitylens.onboarding.models import FetchBundle


GENERATOR_VERSION = "issuer-profile-candidate.v4"
PROFILE_SCHEMA_VERSION = 2


class _NoAliasSafeDumper(yaml.SafeDumper):
    """Keep generated review YAML compatible with the strict import loader."""

    def ignore_aliases(self, data: Any) -> bool:
        return True


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class UnresolvedField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    reason: str
    action: str


class CandidateArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    onboarding_id: str
    task_revision: int
    company_id: str
    fetch_bundle_id: str
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generator_version: str
    mapping_version: str
    mapping_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_manifest: list[dict[str, Any]]
    profile: dict[str, Any]
    unresolved_fields: list[UnresolvedField]
    yaml_text: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    yaml_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_status: Literal["NEEDS_ADAPTATION"] = "NEEDS_ADAPTATION"


class ProfileCandidate(CandidateArtifact):
    profile_candidate_id: str
    created_at: datetime


def observed_concepts(companyfacts: dict[str, Any]) -> set[str]:
    concepts: set[str] = set()
    for taxonomy, facts in (companyfacts.get("facts") or {}).items():
        for name in facts:
            concepts.add(f"{taxonomy}:{name}")
    return concepts


def build_candidate_profile(
    *, company_id: str, companyfacts: dict[str, Any], common_mapping: dict[str, Any]
) -> dict[str, Any]:
    """Return suggestions only for concepts present in the fixed raw snapshot."""
    available = observed_concepts(companyfacts)
    metrics = {}
    unresolved = []
    for metric, rule in (common_mapping.get("canonical_facts") or {}).items():
        matches = [concept for concept in rule.get("concepts") or [] if concept in available]
        if matches:
            metrics[metric] = {"concepts": matches, "candidate_only": True}
        else:
            unresolved.append(metric)
    return {
        "company_id": company_id,
        "metrics": metrics,
        "unresolved_metrics": unresolved,
        "review_status": "NEEDS_ADAPTATION",
    }


def _mapping_identity(mapping: Any) -> tuple[str, str, list[dict[str, Any]]]:
    rules = []
    for name in sorted(mapping.all_metrics()):
        rule = mapping.metric(name)
        rules.append({
            "name": name,
            "metric_type": rule.metric_type,
            "unit_family": rule.unit_family,
            "concepts": list(rule.concepts),
            "sign": rule.sign,
            "derive_standalone_quarter": rule.derive_standalone_quarter,
        })
    return mapping.mapping_version, _sha(_canonical(rules)), rules


def _unit_for_family(family: str) -> str:
    return {"currency": "USD", "shares": "shares", "currency_per_share": "USD/shares"}.get(
        family, "__REVIEW_REQUIRED__"
    )


def _profile_year_end(value: str | None) -> str | None:
    if value is None or "-" in value:
        return value
    if len(value) == 4 and value.isdigit():
        return f"{value[:2]}-{value[2:]}"
    return value


def build_candidate_artifact(
    *, onboarding_id: str, task_revision: int, company_id: str,
    bundle: FetchBundle, mapping: Any,
    fact_catalogs: dict[str, list[dict[str, Any]]],
    securities: list[dict[str, Any]], fiscal_year_end: str | None,
    version: int = 1,
) -> CandidateArtifact:
    """Build a complete but deliberately invalid-until-reviewed Profile v2 skeleton."""
    mapping_version, mapping_sha256, rules = _mapping_identity(mapping)
    input_sha256 = _sha(_canonical({
        "fetch_bundle_sha256": bundle.content_sha256,
        "generator_version": GENERATOR_VERSION,
        "mapping_version": mapping_version,
        "mapping_sha256": mapping_sha256,
        "schema_version": PROFILE_SCHEMA_VERSION,
    }))
    documents = {document.document_id: document for document in bundle.documents}
    manifest = [document.model_dump(mode="json") for document in sorted(
        bundle.documents, key=lambda item: item.document_id
    )]
    occurrences: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for document_id, catalog in sorted(fact_catalogs.items()):
        for fact in catalog:
            occurrences.setdefault(str(fact["concept"]), []).append((document_id, fact))

    evidence: list[dict[str, Any]] = []
    evidence_by_key: dict[tuple[str, str], str] = {}

    def evidence_for(document_id: str, locator: str) -> str:
        key = (document_id, locator)
        if key in evidence_by_key:
            return evidence_by_key[key]
        evidence_id = f"ev-{_sha(document_id + ':' + locator)[:16]}"
        document = documents[document_id]
        evidence.append({
            "evidence_id": evidence_id,
            "source_document_id": document_id,
            "content_sha256": document.content_sha256,
            "locator": locator,
        })
        evidence_by_key[key] = evidence_id
        return evidence_id

    filing_documents = sorted(
        (item for item in bundle.documents if item.document_type == "FILING_DOCUMENT"),
        key=lambda item: item.document_id,
    )
    root_evidence = evidence_for(filing_documents[0].document_id, "/") if filing_documents else None
    unresolved: list[UnresolvedField] = []
    metrics: dict[str, dict[str, Any]] = {}
    for rule in rules:
        name = rule["name"]
        matches = [concept for concept in rule["concepts"] if concept in occurrences]
        metric_evidence: list[str] = []
        for concept in matches:
            document_id, fact = sorted(
                occurrences[concept], key=lambda item: (item[0], str(item[1].get("locator", "")))
            )[0]
            metric_evidence.append(evidence_for(document_id, str(fact.get("locator") or "/")))
        metrics[name] = {
            "concepts": matches,
            "unit": _unit_for_family(rule["unit_family"]),
            "context": "consolidated",
            "period": rule["metric_type"],
            "selection": "latest_filed_same_basis",
            "evidence": sorted(set(metric_evidence)),
        }
        if not matches:
            unresolved.append(UnresolvedField(
                path=f"metrics.{name}.concepts",
                reason="No configured concept was observed in the fixed filing bundle.",
                action="Review the filing facts and select the correct issuer concept or applicability.",
            ))

    security_rows = []
    for index, security in enumerate(securities):
        row = {key: security.get(key) for key in ("ticker", "exchange", "currency", "instrument_type")}
        row["class_label"] = security.get("class_label")
        row["evidence"] = [root_evidence] if root_evidence else []
        security_rows.append(row)
        if not root_evidence:
            unresolved.append(UnresolvedField(
                path=f"securities.{index}.evidence", reason="No fixed filing evidence is available.",
                action="Add filing evidence for the security identity.",
            ))

    diluted_present = bool(metrics.get("DILUTED_EPS", {}).get("concepts"))
    profile = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "company_id": company_id,
        "version": version,
        "template": "us_gaap_operating_v1",
        "template_evidence": [root_evidence] if root_evidence else [],
        "fiscal_calendar": {"year_end": _profile_year_end(fiscal_year_end), "week_based": False,
                            "evidence": [root_evidence] if root_evidence else []},
        "metrics": metrics,
        "segments": {"parser": None, "axes": [], "reconciliation": None,
                     "revenue_concept": None, "profit_concept": None, "evidence": []},
        "cash_debt": {
            "cash_components": metrics.get("CASH_AND_EQUIVALENTS", {}).get("concepts", []),
            "debt_components": metrics.get("LONG_TERM_DEBT", {}).get("concepts", []),
            "restricted_cash_policy": None, "evidence": [],
        },
        "eps_method": "reported_diluted" if diluted_present else None,
        "eps_method_evidence": metrics.get("DILUTED_EPS", {}).get("evidence", []),
        "securities": security_rows,
        "applicability": {"EPS": None, "SEGMENTS": None, "VALUATION": None},
        "applicability_evidence": {},
        "evidence": sorted(evidence, key=lambda item: item["evidence_id"]),
    }
    for path, reason, action in (
        ("segments.parser", "Segment disclosure applicability requires review.", "Choose an approved parser or not_applicable."),
        ("segments.reconciliation", "Segment reconciliation policy requires review.", "Choose explicit_eliminations or not_applicable."),
        ("cash_debt.restricted_cash_policy", "Restricted cash treatment requires review.", "Choose include, exclude, or separate."),
        ("applicability.EPS", "Module applicability requires review.", "Choose required, not_disclosed, or not_applicable."),
        ("applicability.SEGMENTS", "Module applicability requires review.", "Choose required, not_disclosed, or not_applicable."),
        ("applicability.VALUATION", "Module applicability requires review.", "Choose required, not_disclosed, or not_applicable."),
    ):
        unresolved.append(UnresolvedField(path=path, reason=reason, action=action))
    if fiscal_year_end is None:
        unresolved.append(UnresolvedField(
            path="fiscal_calendar.year_end",
            reason="The fixed submissions document has no fiscal year end.",
            action="Enter the issuer fiscal year end as MM-DD.",
        ))
    if not security_rows:
        unresolved.append(UnresolvedField(
            path="securities", reason="No task security identity is available.",
            action="Add at least one reviewed listed security.",
        ))

    unresolved.sort(key=lambda item: item.path)
    comments = ["# Candidate only. Review every field before import."]
    comments.extend(f"# REVIEW REQUIRED: {item.path} — {item.action}" for item in unresolved)
    yaml_text = "\n".join(comments) + "\n" + yaml.dump(
        profile, Dumper=_NoAliasSafeDumper, allow_unicode=True, sort_keys=False
    )
    content_sha256 = _sha(_canonical({
        "profile": profile,
        "unresolved_fields": [item.model_dump(mode="json") for item in unresolved],
        "snapshot_manifest": manifest,
    }))
    return CandidateArtifact(
        onboarding_id=onboarding_id, task_revision=task_revision, company_id=company_id,
        fetch_bundle_id=bundle.fetch_bundle_id, input_sha256=input_sha256,
        generator_version=GENERATOR_VERSION, mapping_version=mapping_version,
        mapping_sha256=mapping_sha256, snapshot_manifest=manifest, profile=profile,
        unresolved_fields=unresolved, yaml_text=yaml_text, content_sha256=content_sha256,
        yaml_sha256=_sha(yaml_text),
    )
