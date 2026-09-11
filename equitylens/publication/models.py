"""Typed records stored inside immutable dataset envelopes."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: item.isoformat()
        if isinstance(item, (date, datetime))
        else str(item),
        allow_nan=False,
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


class _DatasetRecord(BaseModel):
    model_config = ConfigDict(extra="allow")


class CanonicalFactRecord(_DatasetRecord):
    canonical_fact_id: str
    company_id: str
    canonical_metric: str
    period_type: str
    status: str
    mapping_rule_id: str
    mapping_version: str
    source_raw_fact_ids: list[str]

    @field_validator("source_raw_fact_ids", mode="before")
    @classmethod
    def parse_sources(cls, value: Any) -> Any:
        if isinstance(value, str):
            return json.loads(value)
        return value


class MetricValueRecord(_DatasetRecord):
    metric_value_id: str
    company_id: str
    metric_name: str
    status: str
    formula_id: str
    formula_version: str
    input_fact_ids: list[str]

    @field_validator("input_fact_ids", mode="before")
    @classmethod
    def parse_inputs(cls, value: Any) -> Any:
        if isinstance(value, str):
            return json.loads(value)
        return value


class SegmentFactRecord(_DatasetRecord):
    segment_fact_id: str
    company_id: str
    segment_name_reported: str
    metric_name: str
    status: str


class SourceDocumentRecord(_DatasetRecord):
    source_document_id: str
    company_id: str
    provider: str
    document_type: str
    source_url: str
    fetched_at: str | datetime
    content_sha256: str


class RawFactRecord(_DatasetRecord):
    raw_fact_id: str
    source_document_id: str
    concept: str


ENTITY_MODELS: dict[str, type[_DatasetRecord]] = {
    "canonical_fact": CanonicalFactRecord,
    "metric_value": MetricValueRecord,
    "segment_fact": SegmentFactRecord,
    "source_document": SourceDocumentRecord,
    "raw_fact": RawFactRecord,
}


def validate_dataset_payload(entity_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        model = ENTITY_MODELS[entity_type]
    except KeyError as exc:
        raise ValueError(f"unsupported dataset entity_type: {entity_type}") from exc
    return model.model_validate(payload).model_dump(mode="json")


class Dataset(BaseModel):
    dataset_id: str
    company_id: str
    profile_id: str
    dataset_hash: str
    state: str


class Publication(BaseModel):
    publication_id: str
    company_id: str
    dataset_id: str
    profile_id: str
    quality_report_id: str | None = None
    review_id: str | None = None
    fingerprint: str
    published_at: datetime


class PublicationContext(BaseModel):
    company_id: str
    publication_id: str
    dataset_id: str
    profile_id: str
