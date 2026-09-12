"""Onboarding task state and public task view."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TaskState(StrEnum):
    QUEUED = "QUEUED"
    FETCHING = "FETCHING"
    BUILDING = "BUILDING"
    NEEDS_ADAPTATION = "NEEDS_ADAPTATION"
    VALIDATING = "VALIDATING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class OnboardingStep(StrEnum):
    FETCH = "FETCH"
    BUILD = "BUILD"
    VALIDATE = "VALIDATE"
    PUBLISH = "PUBLISH"


TERMINAL_STATES = {TaskState.PUBLISHED, TaskState.CANCELLED}
ACTIVE_STATES = {
    TaskState.QUEUED,
    TaskState.FETCHING,
    TaskState.BUILDING,
    TaskState.NEEDS_ADAPTATION,
    TaskState.VALIDATING,
    TaskState.NEEDS_REVIEW,
    TaskState.PUBLISHING,
    TaskState.FAILED,
}


class StepAttempt(BaseModel):
    model_config = ConfigDict(extra="ignore")

    attempt_id: str
    onboarding_id: str
    step: OnboardingStep
    attempt_no: int
    input_hash: str
    output_hash: str | None = None
    state: str
    started_at: datetime
    finished_at: datetime | None = None
    heartbeat_at: datetime | None = None
    error: dict[str, Any] | None = None


class TaskView(BaseModel):
    onboarding_id: str
    company_id: str
    state: TaskState
    current_step: OnboardingStep | None
    revision: int
    cancel_requested: bool
    input_fingerprint: str
    discovery_id: str | None = None
    profile_id: str | None = None
    dataset_id: str | None = None
    quality_report_id: str | None = None
    review_id: str | None = None
    publication_id: str | None = None
    error: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
    actions: list[str] = Field(default_factory=list)
