"""Validated request bodies for company onboarding APIs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DiscoverRequest(StrictRequest):
    ticker: str


class CreateOnboardingRequest(StrictRequest):
    discovery_id: str
    identity_hash: str
    candidate_id: str


class RevisionRequest(StrictRequest):
    expected_revision: int = Field(ge=1)


class ProfileImportRequest(RevisionRequest):
    profile: dict[str, Any]


class ProfileYamlImportRequest(RevisionRequest):
    yaml_text: str


class ReviewRequest(RevisionRequest):
    fingerprint: str
    decision: Literal["APPROVE", "REJECT"]
    reviewer: str = Field(min_length=1)
    note: str = ""


class ValuationProfileRequest(StrictRequest):
    security_id: str
    publication_id: str
    model_version: str
    assumptions: dict[str, Any]
    confirmed: bool
