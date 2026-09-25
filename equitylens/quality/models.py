"""Explainable quality report types."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CheckStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_DISCLOSED = "NOT_DISCLOSED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNSUPPORTED = "UNSUPPORTED"


class Severity(StrEnum):
    BLOCKER = "BLOCKER"
    WARNING = "WARNING"


class CheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    check_id: str
    scope_key: str = "company"
    status: CheckStatus
    severity: Severity = Severity.BLOCKER
    actual: dict[str, Any] | None = None
    expected: dict[str, Any] | None = None
    tolerance: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    reason: str | None = None


class QualityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    report_id: str
    dataset_id: str
    rule_version: str
    result: str
    fingerprint: str
    created_at: datetime
    checks: list[CheckResult]
