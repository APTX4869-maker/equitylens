"""One server-owned five-stage view of durable onboarding progress."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from equitylens.onboarding.models import (
    OnboardingProgress,
    ProgressStage,
    TaskState,
)


STAGES = (
    ("IDENTITY", "识别公司"),
    ("FETCH", "固定申报数据"),
    ("ADAPTATION", "适配公司配置"),
    ("BUILD_VALIDATE", "构建并校验"),
    ("REVIEW_PUBLISH", "审核并发布"),
)


def _get(value: Any, name: str, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _mapping(task) -> tuple[int, str, str, str]:
    state = task.state
    if state == TaskState.PUBLISHED:
        return 5, "REVIEW_PUBLISH", "COMPLETED", "NONE"
    if state == TaskState.QUEUED:
        return 1, "FETCH", "QUEUED", "SYSTEM"
    if state == TaskState.FETCHING:
        return 1, "FETCH", "RUNNING", "SYSTEM"
    if state == TaskState.NEEDS_ADAPTATION:
        return 2, "ADAPTATION", "WAITING_FOR_MAINTAINER", "MAINTAINER"
    if state == TaskState.BUILDING:
        return (
            (3, "BUILD_VALIDATE", "RUNNING", "SYSTEM")
            if task.profile_id
            else (2, "ADAPTATION", "RUNNING", "SYSTEM")
        )
    if state == TaskState.VALIDATING:
        return 3, "BUILD_VALIDATE", "RUNNING", "SYSTEM"
    if state == TaskState.NEEDS_REVIEW:
        return 4, "REVIEW_PUBLISH", "WAITING_FOR_MAINTAINER", "MAINTAINER"
    if state == TaskState.PUBLISHING:
        return 4, "REVIEW_PUBLISH", "RUNNING", "SYSTEM"
    if state == TaskState.FAILED:
        step = task.current_step.value if task.current_step else None
        if step == "FETCH":
            return 1, "FETCH", "FAILED", "SYSTEM"
        if step == "BUILD" and not task.profile_id:
            return 2, "ADAPTATION", "FAILED", "SYSTEM"
        if step in {"BUILD", "VALIDATE"}:
            return 3, "BUILD_VALIDATE", "FAILED", "SYSTEM"
        return 4, "REVIEW_PUBLISH", "FAILED", "SYSTEM"
    return 0, "IDENTITY", "CANCELLED", "NONE"


def _cancel_snapshot(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if _get(event, "event_type") != "TASK_CANCELLED":
            continue
        payload = _get(event, "payload", {}) or {}
        return payload.get("progress_snapshot") or payload.get("progress_snapshot_json")
    return None


def derive_progress(
    task,
    attempts: list[Any],
    events: list[Any],
    now: datetime,
    stalled_after: timedelta = timedelta(seconds=45),
) -> OnboardingProgress:
    now = _aware(now)
    attempts = list(attempts)
    events = list(events)
    snapshot = _cancel_snapshot(events) if task.state == TaskState.CANCELLED else None
    if snapshot and snapshot.get("stages"):
        restored = dict(snapshot)
        restored["activity"] = "CANCELLED"
        restored["stalled"] = False
        restored["updated_at"] = task.updated_at
        restored["stages"] = [dict(stage) for stage in restored["stages"]]
        for stage in restored["stages"]:
            if stage["id"] == restored["current_stage"]:
                stage["status"] = "CURRENT"
                stage["activity"] = "CANCELLED"
        return OnboardingProgress.model_validate(restored)
    if snapshot:
        completed = int(snapshot["completed"])
        current_stage = snapshot["current_stage"]
        activity, actor = "CANCELLED", snapshot.get("actor", "NONE")
    else:
        completed, current_stage, activity, actor = _mapping(task)

    latest_heartbeat = max(
        (_aware(_get(item, "heartbeat_at")) for item in attempts if _get(item, "heartbeat_at")),
        default=None,
    )
    latest_event_at = max(
        (_aware(_get(item, "created_at")) for item in events if _get(item, "created_at")),
        default=None,
    )
    updated_at = max(
        value for value in (_aware(task.updated_at), latest_heartbeat, latest_event_at) if value
    )
    running_attempts = [item for item in attempts if _get(item, "state") == "RUNNING"]
    running_watermark = max(
        (_aware(_get(item, "heartbeat_at") or _get(item, "started_at")) for item in running_attempts),
        default=None,
    )
    stalled = bool(
        activity == "RUNNING"
        and running_watermark is not None
        and now - running_watermark > stalled_after
    )
    event_watermark = None
    if events:
        last = max(events, key=lambda item: (_aware(_get(item, "created_at")), _get(item, "event_id", "")))
        event_watermark = [_get(last, "event_id"), str(_get(last, "created_at"))]
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "revision": task.revision,
                "heartbeat": latest_heartbeat.isoformat() if latest_heartbeat else None,
                "event": event_watermark,
                "state": task.state.value,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()

    current_index = next(index for index, (stage_id, _) in enumerate(STAGES) if stage_id == current_stage)
    attempts_by_step: dict[str, list[Any]] = {}
    for attempt in attempts:
        step = _get(attempt, "step")
        step = step.value if hasattr(step, "value") else step
        attempts_by_step.setdefault(step, []).append(attempt)

    def attempt_started(*steps: str):
        return min(
            (_aware(_get(item, "started_at")) for step in steps for item in attempts_by_step.get(step, [])),
            default=None,
        )

    def attempt_completed(*steps: str):
        return max(
            (_aware(_get(item, "finished_at")) for step in steps for item in attempts_by_step.get(step, [])
             if _get(item, "state") == "COMPLETED" and _get(item, "finished_at")),
            default=None,
        )

    event_times: dict[str, list[datetime]] = {}
    for event in events:
        if _get(event, "created_at"):
            event_times.setdefault(_get(event, "event_type"), []).append(_aware(_get(event, "created_at")))
    adaptation_done = max(event_times.get("PROFILE_IMPORTED", []), default=None)
    stage_times = {
        "IDENTITY": (task.created_at, task.created_at),
        "FETCH": (attempt_started("FETCH") or task.created_at, attempt_completed("FETCH")),
        "ADAPTATION": (attempt_completed("FETCH"), adaptation_done),
        "BUILD_VALIDATE": (attempt_started("BUILD", "VALIDATE") or adaptation_done,
                           attempt_completed("VALIDATE")),
        "REVIEW_PUBLISH": (attempt_completed("VALIDATE"),
                           task.updated_at if task.state == TaskState.PUBLISHED else attempt_completed("PUBLISH")),
    }
    stages = []
    for index, (stage_id, label) in enumerate(STAGES):
        if completed == 5 or index < completed:
            status, stage_activity = "COMPLETED", "COMPLETED"
        elif index == current_index:
            status, stage_activity = "CURRENT", activity
        else:
            status, stage_activity = "UPCOMING", None
        started_at, completed_at = stage_times[stage_id]
        if status != "COMPLETED":
            completed_at = None
        stages.append(ProgressStage(
            id=stage_id, label=label, status=status, activity=stage_activity,
            started_at=started_at, completed_at=completed_at,
        ))
    return OnboardingProgress(
        completed=completed,
        percent=completed * 20,
        current_stage=current_stage,
        activity=activity,
        actor=actor,
        updated_at=updated_at,
        stalled=stalled,
        stages=stages,
        fingerprint=fingerprint,
    )
