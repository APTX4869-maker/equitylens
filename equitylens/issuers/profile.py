"""Strict, data-only issuer profile schema v1."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Literal
import hashlib
import re
import uuid

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from equitylens.publication.models import sha256_json

if False:  # pragma: no cover - imports only for type checkers
    from equitylens.onboarding.models import FetchBundle
    from equitylens.onboarding.repository import OnboardingRepository
    from equitylens.publication.repository import PublicationRepository


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FiscalCalendarConfig(StrictModel):
    year_end: str = Field(pattern=r"^\d{2}-\d{2}$")
    week_based: bool


class MetricConfig(StrictModel):
    concepts: list[str] = Field(min_length=1)
    unit: str
    context: Literal["consolidated"]
    period: Literal["duration", "instant"]
    selection: Literal["latest_filed_same_basis"]


class SegmentConfig(StrictModel):
    axes: list[str]
    reconciliation: Literal["explicit_eliminations", "not_applicable"]


class CashDebtConfig(StrictModel):
    cash_components: list[str] = Field(min_length=1)
    debt_components: list[str] = Field(min_length=1)
    restricted_cash_policy: Literal["include", "exclude", "separate"]


class SecurityConfig(StrictModel):
    ticker: str
    exchange: str
    currency: str
    instrument_type: str
    class_label: str | None = None
    evidence: list[str] = Field(min_length=1)


class EvidenceConfig(StrictModel):
    evidence_id: str
    source_document_id: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: str


class IssuerProfile(StrictModel):
    schema_version: Literal[1]
    company_id: str = Field(pattern=r"^\d{10}$")
    version: int = Field(ge=1)
    template: Literal["us_gaap_operating_v1"]
    fiscal_calendar: FiscalCalendarConfig
    metrics: dict[str, MetricConfig] = Field(min_length=1)
    segments: SegmentConfig
    cash_debt: CashDebtConfig
    eps_method: Literal["reported_diluted", "two_class", "preferred_adjusted"] | None = None
    securities: list[SecurityConfig] = Field(min_length=1)
    applicability: dict[str, Literal["required", "not_disclosed", "not_applicable"]]
    applicability_evidence: dict[str, list[str]] = Field(default_factory=dict)
    evidence: list[EvidenceConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def evidence_references_exist(self):
        evidence_ids = {item.evidence_id for item in self.evidence}
        referenced = {item for security in self.securities for item in security.evidence}
        missing = referenced - evidence_ids
        applicability_referenced = {
            item for items in self.applicability_evidence.values() for item in items
        }
        missing |= applicability_referenced - evidence_ids
        if missing:
            raise ValueError(f"security evidence references are missing: {sorted(missing)}")
        return self

    @computed_field
    @property
    def content_sha256(self) -> str:
        return sha256_json(
            self.model_dump(mode="json", exclude={"content_sha256"})
        )


class FiscalCalendarConfigV2(FiscalCalendarConfig):
    evidence: list[str] = Field(min_length=1)


class MetricConfigV2(MetricConfig):
    evidence: list[str] = Field(min_length=1)


class SegmentMemberV2(StrictModel):
    label: str = Field(min_length=1)
    aggregate: bool = False
    kind: Literal["segment", "product", "geo", "elimination", "unallocated"] | None = None


class SegmentAxisV2(StrictModel):
    name: str = Field(min_length=1)
    kind: Literal["segment", "product", "geo"]
    label: str = Field(min_length=1)
    members: dict[str, SegmentMemberV2] = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)


class SegmentConfigV2(StrictModel):
    parser: Literal["ixbrl_segments_v1", "not_applicable"]
    axes: list[SegmentAxisV2]
    reconciliation: Literal["explicit_eliminations", "not_applicable"]
    revenue_concept: str | None
    profit_concept: str | None
    evidence: list[str] = Field(min_length=1)


class CashDebtConfigV2(CashDebtConfig):
    evidence: list[str] = Field(min_length=1)


class IssuerProfileV2(StrictModel):
    schema_version: Literal[2]
    company_id: str = Field(pattern=r"^\d{10}$")
    version: int = Field(ge=1)
    template: Literal["us_gaap_operating_v1"]
    template_evidence: list[str] = Field(min_length=1)
    fiscal_calendar: FiscalCalendarConfigV2
    metrics: dict[str, MetricConfigV2] = Field(min_length=1)
    segments: SegmentConfigV2
    cash_debt: CashDebtConfigV2
    eps_method: Literal["reported_diluted", "two_class", "preferred_adjusted"] | None
    eps_method_evidence: list[str]
    securities: list[SecurityConfig] = Field(min_length=1)
    applicability: dict[str, Literal["required", "not_disclosed", "not_applicable"]]
    applicability_evidence: dict[str, list[str]] = Field(default_factory=dict)
    evidence: list[EvidenceConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_conditions_and_evidence(self):
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence_id values must be unique")
        required_modules = {"EPS", "SEGMENTS", "VALUATION"}
        if set(self.applicability) != required_modules:
            raise ValueError(f"applicability must declare {sorted(required_modules)}")
        if self.segments.parser == "ixbrl_segments_v1":
            if not self.segments.axes:
                raise ValueError("segments.axes must contain at least one axis")
            if not self.segments.revenue_concept:
                raise ValueError("segments.revenue_concept is required")
            if self.segments.reconciliation != "explicit_eliminations":
                raise ValueError("iXBRL segments require explicit_eliminations")
            if self.applicability["SEGMENTS"] == "not_applicable":
                raise ValueError("iXBRL segments cannot be not_applicable")
        else:
            if self.segments.axes:
                raise ValueError("segments.axes must be empty when parser is not_applicable")
            if self.segments.revenue_concept is not None or self.segments.profit_concept is not None:
                raise ValueError("segment concepts must be null when parser is not_applicable")
            if self.segments.reconciliation != "not_applicable":
                raise ValueError("segment reconciliation must be not_applicable")
            if self.applicability["SEGMENTS"] != "not_applicable":
                raise ValueError("SEGMENTS applicability must be not_applicable")
        if (self.applicability["EPS"] == "required" or self.eps_method is not None) and not self.eps_method_evidence:
            raise ValueError("eps_method_evidence is required")

        referenced = set(self.template_evidence)
        referenced.update(self.fiscal_calendar.evidence)
        referenced.update(item for metric in self.metrics.values() for item in metric.evidence)
        referenced.update(self.segments.evidence)
        referenced.update(item for axis in self.segments.axes for item in axis.evidence)
        referenced.update(self.cash_debt.evidence)
        referenced.update(self.eps_method_evidence)
        referenced.update(item for security in self.securities for item in security.evidence)
        for module, status in self.applicability.items():
            module_evidence = self.applicability_evidence.get(module, [])
            if status in {"not_disclosed", "not_applicable"} and not module_evidence:
                raise ValueError(f"applicability_evidence.{module} is required")
            referenced.update(module_evidence)
        missing = referenced - set(evidence_ids)
        if missing:
            raise ValueError(f"evidence references are missing: {sorted(missing)}")
        return self

    @computed_field
    @property
    def content_sha256(self) -> str:
        return sha256_json(self.model_dump(mode="json", exclude={"content_sha256"}))


class ProfileEvidenceError(ValueError):
    pass


def validate_profile_v2_against_bundle(
    profile: IssuerProfileV2, bundle: "FetchBundle"
) -> None:
    fixed = {(item.document_id, item.content_sha256) for item in bundle.documents}
    missing = [
        f"{item.source_document_id}@{item.content_sha256}"
        for item in profile.evidence
        if (item.source_document_id, item.content_sha256) not in fixed
    ]
    if missing:
        raise ProfileEvidenceError(
            f"profile evidence is not in the current fetch bundle: {', '.join(missing)}"
        )


def _normalized_evidence_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def validate_profile_v2_evidence_documents(
    profile: IssuerProfileV2,
    bundle: "FetchBundle",
    raw_dir: Path,
) -> None:
    """Resolve every reviewed locator and substantiate each security identity.

    Hash binding alone proves which bytes were reviewed, but not that a locator
    still addresses those bytes or that a broad document root supports a
    security claim.  BUILD calls this against the immutable fetch bundle before
    any candidate rows are sealed.
    """
    from lxml import etree

    from equitylens.normalization.ixbrl import IxbrlDocument, NS
    from equitylens.onboarding.fetch_bundle import load_bundle_document

    documents = {
        (item.document_id, item.content_sha256): item for item in bundle.documents
    }
    parsed: dict[tuple[str, str], IxbrlDocument] = {}
    resolved: dict[str, tuple[EvidenceConfig, list[object]]] = {}
    for evidence in profile.evidence:
        key = (evidence.source_document_id, evidence.content_sha256)
        document = documents.get(key)
        if document is None:
            raise ProfileEvidenceError(
                f"profile evidence is not in the current fetch bundle: {evidence.evidence_id}"
            )
        if document.document_type != "FILING_DOCUMENT":
            raise ProfileEvidenceError(
                f"profile evidence must resolve to a filing document: {evidence.evidence_id}"
            )
        ixbrl = parsed.get(key)
        if ixbrl is None:
            ixbrl = IxbrlDocument.parse(load_bundle_document(raw_dir, document))
            parsed[key] = ixbrl
        try:
            nodes = (
                [ixbrl.root]
                if evidence.locator.strip() == "/"
                else ixbrl.root.xpath(evidence.locator, namespaces=NS)
            )
        except Exception as exc:
            raise ProfileEvidenceError(
                f"profile evidence locator is invalid: {evidence.evidence_id}"
            ) from exc
        if (
            not isinstance(nodes, list)
            or not nodes
            or any(not isinstance(node, etree._Element) for node in nodes)
        ):
            raise ProfileEvidenceError(
                f"profile evidence locator must resolve to non-empty element nodes: {evidence.evidence_id}"
            )
        resolved[evidence.evidence_id] = (evidence, nodes)

    for metric_name, metric in profile.metrics.items():
        nodes = [
            node
            for evidence_id in metric.evidence
            for node in resolved[evidence_id][1]
        ]
        allowed = set(metric.concepts)
        if not nodes or any(node.get("name") not in allowed for node in nodes):
            raise ProfileEvidenceError(
                f"metric evidence does not substantiate configured concepts: {metric_name}"
            )

    if profile.segments.parser == "ixbrl_segments_v1":
        allowed_concepts = {
            item for item in (
                profile.segments.revenue_concept,
                profile.segments.profit_concept,
            ) if item
        }
        for axis in profile.segments.axes:
            matched = False
            for evidence_id in axis.evidence:
                evidence, nodes = resolved[evidence_id]
                ixbrl = parsed[(evidence.source_document_id, evidence.content_sha256)]
                for node in nodes:
                    if node.get("name") not in allowed_concepts:
                        continue
                    member = ixbrl.context_axis_members(
                        node.get("contextRef")
                    ).get(axis.name)
                    if member in axis.members:
                        matched = True
            if not matched:
                raise ProfileEvidenceError(
                    "segment evidence does not substantiate configured axis members: "
                    f"{axis.name}"
                )

        configured = {
            (axis.name, member)
            for axis in profile.segments.axes
            for member in axis.members
        }
        for evidence_id in profile.segments.evidence:
            evidence, nodes = resolved[evidence_id]
            ixbrl = parsed[(evidence.source_document_id, evidence.content_sha256)]
            if not any(
                node.get("name") in allowed_concepts
                and any(
                    (axis_name, member) in configured
                    for axis_name, member in ixbrl.context_axis_members(
                        node.get("contextRef")
                    ).items()
                )
                for node in nodes
            ):
                raise ProfileEvidenceError(
                    "segment evidence does not substantiate configured concepts and dimensions: "
                    f"{evidence_id}"
                )

    exchange_terms = {
        "nasdaq": ("nasdaq",),
        "nyse": ("nyse", "new york stock exchange"),
    }
    for security in profile.securities:
        referenced = [resolved[item] for item in security.evidence if item in resolved]
        if not referenced or any(evidence.locator.strip() == "/" for evidence, _ in referenced):
            raise ProfileEvidenceError(
                f"security evidence must use a precise filing locator: {security.ticker}"
            )
        text = _normalized_evidence_text(
            " ".join(
                " ".join(str(part) for part in node.itertext())
                for _, nodes in referenced
                for node in nodes
                if hasattr(node, "itertext")
            )
        )
        ticker = _normalized_evidence_text(security.ticker)
        class_label = _normalized_evidence_text(security.class_label or "")
        exchange = _normalized_evidence_text(security.exchange)
        aliases = exchange_terms.get(exchange, (exchange,))
        ticker_ok = bool(re.search(rf"(?:^| )({re.escape(ticker)})(?: |$)", text))
        class_ok = not class_label or class_label in text
        exchange_ok = any(alias and alias in text for alias in aliases)
        if not (ticker_ok and class_ok and exchange_ok):
            raise ProfileEvidenceError(
                f"security evidence does not substantiate ticker, exchange, and class: {security.ticker}"
            )


def parse_profile(data: dict) -> IssuerProfile | IssuerProfileV2:
    if data.get("schema_version") == 2:
        return IssuerProfileV2.model_validate(data)
    return IssuerProfile.model_validate(data)


def load_profile_yaml(path: Path | str) -> IssuerProfile | IssuerProfileV2:
    try:
        data = yaml.safe_load(Path(path).read_text())
    except yaml.YAMLError as exc:
        raise ValueError(f"profile must use safe YAML data only: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("profile must use safe YAML and contain one object")
    return parse_profile(data)


class IssuerProfileService:
    def __init__(
        self,
        publications: "PublicationRepository | None" = None,
        tasks: "OnboardingRepository | None" = None,
        *,
        wake: Callable[[], None] | None = None,
    ) -> None:
        self.publications = publications
        self.tasks = tasks
        self.wake = wake

    def validate(self, profile: dict) -> IssuerProfile | IssuerProfileV2:
        return parse_profile(profile)

    def validate_for_import(self, profile: dict) -> IssuerProfileV2:
        if profile.get("schema_version") != 2:
            raise ValueError("new profile imports require schema_version 2")
        return IssuerProfileV2.model_validate(profile)

    def import_profile(
        self, task_id: str, expected_revision: int, profile: dict,
        *, idempotency_key: str | None = None,
    ):
        """Validate a new Profile v2 and install it in one task transaction."""
        if self.tasks is None:
            raise RuntimeError("profile import requires a task repository")
        parsed = self.validate_for_import(profile)
        request_sha256 = sha256_json({
            "task_id": task_id,
            "expected_revision": expected_revision,
            "profile": parsed.model_dump(mode="json", exclude={"content_sha256"}),
        })
        task = self.tasks.import_profile_atomic(
            task_id,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key or f"json-{uuid.uuid4()}",
            request_sha256=request_sha256,
            profile=parsed,
        )
        if self.wake is not None:
            self.wake()
        return task

    def import_profile_yaml(
        self,
        task_id: str,
        expected_revision: int,
        idempotency_key: str,
        yaml_text: str,
    ):
        if self.tasks is None:
            raise RuntimeError("profile import requires a task repository")
        from equitylens.issuers.yaml_loader import load_strict_profile_yaml

        parsed = load_strict_profile_yaml(yaml_text)
        request_sha256 = sha256_json({
            "task_id": task_id,
            "expected_revision": expected_revision,
            "yaml_sha256": hashlib.sha256(yaml_text.encode("utf-8")).hexdigest(),
        })
        task = self.tasks.import_profile_atomic(
            task_id,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            request_sha256=request_sha256,
            profile=parsed,
        )
        if self.wake is not None:
            self.wake()
        return task
