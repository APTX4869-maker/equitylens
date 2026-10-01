"""API response schemas (Pydantic)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictStr


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ResearchAskRequest(StrictRequest):
    ticker: StrictStr = "AAPL"
    question: StrictStr
    security_id: StrictStr | None = None
    publication_id: StrictStr | None = None


class ValuationRunRequest(StrictRequest):
    persist: StrictBool = True
    assumptions: dict[str, Any] | None = None


class ReverseDcfRequest(StrictRequest):
    # The valuation service owns field-specific 400 errors for the numeric
    # domain. This model forbids unknown fields without replacing that API.
    target_price: Any = None
    assumptions: Any = None


class ValuationPlanRequest(StrictRequest):
    valuation_run_id: StrictStr
    scenario_key: Literal["base", "bear", "bull"]
    margin_of_safety: StrictFloat = Field(allow_inf_nan=False)
    name: StrictStr | None = None
    notes: StrictStr | None = None
    conditions_to_verify: list[StrictStr] = Field(default_factory=list)


class ValuationPlanCopyRequest(StrictRequest):
    scenario_key: Literal["base", "bear", "bull"] | None = None
    margin_of_safety: StrictFloat | None = Field(default=None, allow_inf_nan=False)
    name: StrictStr | None = None
    notes: StrictStr | None = None
    conditions_to_verify: list[StrictStr] | None = None


class RefreshRequest(StrictRequest):
    modules: list[Literal["financials", "segments", "management", "quotes"]] | None = None
    operation_id: StrictStr | None = None
    operation_finished: StrictBool = True


class SourceRef(BaseModel):
    source_document_id: str | None = None
    provider: str | None = None
    form_type: str | None = None
    accession_number: str | None = None
    filed_at: str | None = None
    fetched_at: str | None = None
    source_url: str | None = None
    concept: str | None = None
    unit: str | None = None
    mapping_version: str | None = None
    formula_id: str | None = None
    status: str | None = None


class FactOut(BaseModel):
    metric: str
    period: str
    period_type: str
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None
    period_start: str | None = None
    period_end: str | None = None
    instant_date: str | None = None
    value: float
    unit: str
    status: str
    canonical_fact_id: str
    provenance: SourceRef
    input_fact_ids: list[str] = Field(default_factory=list)


class MetricOut(BaseModel):
    metric: str
    period: str
    value: float | None
    unit: str | None = None
    status: str | None = None
    formula_id: str | None = None
    formula_version: str | None = None
    input_fact_ids: list[str] = Field(default_factory=list)
    frequency: str | None = None
    period_start: str | None = None
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None
    period_end: str | None = None
    missing_reason: str | None = None


class CompanyOut(BaseModel):
    ticker: str
    cik: str
    name: str
    exchange: str | None = None
    fiscal_year_end: str | None = None
    source_freshness: dict[str, Any] = Field(default_factory=dict)


class ProvenanceNode(BaseModel):
    entity_id: str
    kind: Literal["canonical_fact", "raw_fact", "source_document", "metric_value"]
    label: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    parents: list["ProvenanceNode"] = Field(default_factory=list)


class ProvenanceOut(BaseModel):
    entity_id: str
    kind: str
    tree: ProvenanceNode
