"""Typed issuer and listed-security identities."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CompanyIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    company_id: str
    cik: str
    legal_name: str
    reporting_template: str | None = None
    quality_status: str = "UNREVIEWED"

    @field_validator("company_id", "cik")
    @classmethod
    def validate_cik(cls, value: str) -> str:
        if len(value) != 10 or not value.isdigit():
            raise ValueError("company_id and cik must be zero-padded 10 digit CIKs")
        return value


class SecurityIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    security_id: str
    company_id: str
    ticker: str
    class_label: str | None = None
    exchange: str
    currency: str
    instrument_type: str
    status: str = "ACTIVE"
    identity_evidence: dict[str, Any] = Field(default_factory=dict)
    valid_from: date | None = None
    valid_to: date | None = None
    company_name: str | None = None

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: str) -> str:
        if len(value) != 10 or not value.isdigit():
            raise ValueError("company_id must be a zero-padded 10 digit CIK")
        return value

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("ticker is required")
        return normalized
