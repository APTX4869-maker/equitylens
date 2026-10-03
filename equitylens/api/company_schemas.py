"""Validated request bodies for company onboarding APIs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictStr


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DiscoverRequest(StrictRequest):
    ticker: str


class CreateOnboardingRequest(StrictRequest):
    discovery_id: str
    identity_hash: str
    candidate_id: str


class RereviewRequest(StrictRequest):
    ticker: str


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


class ValuationProfileAssumptions(StrictRequest):
    revenue_base: StrictFloat
    revenue_growth: list[StrictFloat] = Field(min_length=5, max_length=5)
    op_margin_start: StrictFloat
    op_margin_end: StrictFloat
    tax_rate: StrictFloat
    da_pct: StrictFloat
    capex_pct: StrictFloat
    nwc_pct: StrictFloat
    wacc: StrictFloat
    terminal_growth: StrictFloat
    net_cash: StrictFloat
    shares: StrictFloat
    share_basis_label: StrictStr
    share_basis_security_id: StrictStr | None = None
    terminal_roic: StrictFloat


class ValuationProfileRequest(StrictRequest):
    security_id: StrictStr
    publication_id: StrictStr
    model_version: StrictStr
    assumptions: ValuationProfileAssumptions
    confirmed: StrictBool
