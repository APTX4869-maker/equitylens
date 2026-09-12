"""Strict, data-only issuer profile schema v1."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from equitylens.publication.models import sha256_json

if False:  # pragma: no cover - imports only for type checkers
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


def load_profile_yaml(path: Path | str) -> IssuerProfile:
    try:
        data = yaml.safe_load(Path(path).read_text())
    except yaml.YAMLError as exc:
        raise ValueError(f"profile must use safe YAML data only: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("profile must use safe YAML and contain one object")
    return IssuerProfile.model_validate(data)


class IssuerProfileService:
    def __init__(
        self,
        publications: "PublicationRepository | None" = None,
        tasks: "OnboardingRepository | None" = None,
    ) -> None:
        self.publications = publications
        self.tasks = tasks

    def validate(self, profile: dict) -> IssuerProfile:
        return IssuerProfile.model_validate(profile)

    def import_profile(
        self, task_id: str, expected_revision: int, profile: dict
    ):
        """Persist a validated immutable profile and invalidate old candidates."""
        if self.publications is None or self.tasks is None:
            raise RuntimeError("profile import requires publication and task repositories")
        parsed = self.validate(profile)
        task = self.tasks.get(task_id)
        if task.revision != expected_revision or task.cancel_requested:
            from equitylens.onboarding.repository import OnboardingConflict

            raise OnboardingConflict("TASK_CONFLICT", "task revision changed or was cancelled")
        if parsed.company_id != task.company_id:
            raise ValueError("profile company_id does not match onboarding company")
        profile_id = self.publications.create_profile(
            task.company_id,
            version=parsed.version,
            schema_version=parsed.schema_version,
            content=parsed.model_dump(mode="json", exclude={"content_sha256"}),
        )
        from equitylens.onboarding.models import OnboardingStep, TaskState

        return self.tasks.set_candidate(
            task_id,
            expected_revision=expected_revision,
            profile_id=profile_id,
            state=TaskState.BUILDING,
            current_step=OnboardingStep.BUILD,
        )
