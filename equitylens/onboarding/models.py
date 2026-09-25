"""Onboarding task state and public task view."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

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


class FetchDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    document_type: str
    accession_number: str | None = None
    form_type: str | None = None
    filed_at: date | None = None
    report_date: date | None = None
    fetched_at: datetime
    source_url: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_locator: str


class FetchBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fetch_bundle_id: str
    onboarding_id: str
    fetcher_version: str
    parser_version: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    documents: list[FetchDocument]
    created_at: datetime


class OnboardingEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    onboarding_id: str
    event_type: str
    actor_type: str
    task_revision: int
    payload: dict[str, Any]
    created_at: datetime


class ProgressStage(BaseModel):
    id: Literal["IDENTITY", "FETCH", "ADAPTATION", "BUILD_VALIDATE", "REVIEW_PUBLISH"]
    label: str
    status: Literal["COMPLETED", "CURRENT", "UPCOMING"]
    activity: Literal[
        "QUEUED", "RUNNING", "WAITING_FOR_MAINTAINER", "FAILED",
        "CANCELLED", "COMPLETED"
    ] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class OnboardingProgress(BaseModel):
    completed: int = Field(ge=0, le=5)
    total: Literal[5] = 5
    percent: int = Field(ge=0, le=100)
    current_stage: Literal["IDENTITY", "FETCH", "ADAPTATION", "BUILD_VALIDATE", "REVIEW_PUBLISH"]
    activity: Literal[
        "QUEUED", "RUNNING", "WAITING_FOR_MAINTAINER", "FAILED",
        "CANCELLED", "COMPLETED"
    ]
    actor: Literal["SYSTEM", "MAINTAINER", "NONE"]
    updated_at: datetime
    stalled: bool
    stages: list[ProgressStage]
    fingerprint: str


class TaskView(BaseModel):
    onboarding_id: str
    company_id: str
    state: TaskState
    current_step: OnboardingStep | None
    revision: int
    cancel_requested: bool
    input_fingerprint: str
    discovery_id: str | None = None
    fetch_bundle_id: str | None = None
    profile_candidate_id: str | None = None
    profile_id: str | None = None
    dataset_id: str | None = None
    quality_report_id: str | None = None
    review_id: str | None = None
    publication_id: str | None = None
    error: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
    actions: list[str] = Field(default_factory=list)
