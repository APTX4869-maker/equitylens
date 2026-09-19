from datetime import datetime, timedelta, timezone

import pytest

from equitylens.onboarding.models import OnboardingStep, TaskState, TaskView
from equitylens.onboarding.progress import derive_progress


NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def _task(state, *, step, profile_id=None, error=None, revision=3):
    return TaskView(
        onboarding_id="task-1", company_id="0000000001", state=state,
        current_step=step, revision=revision, cancel_requested=False,
        input_fingerprint="input", profile_id=profile_id,
        error=error, created_at=NOW - timedelta(minutes=5), updated_at=NOW,
    )


@pytest.mark.parametrize(
    "task,completed,current,activity,actor",
    [
        (_task(TaskState.QUEUED, step=OnboardingStep.FETCH), 1, "FETCH", "QUEUED", "SYSTEM"),
        (_task(TaskState.FETCHING, step=OnboardingStep.FETCH), 1, "FETCH", "RUNNING", "SYSTEM"),
        (_task(TaskState.BUILDING, step=OnboardingStep.BUILD), 2, "ADAPTATION", "RUNNING", "SYSTEM"),
        (_task(TaskState.NEEDS_ADAPTATION, step=OnboardingStep.BUILD), 2, "ADAPTATION", "WAITING_FOR_MAINTAINER", "MAINTAINER"),
        (_task(TaskState.BUILDING, step=OnboardingStep.BUILD, profile_id="profile"), 3, "BUILD_VALIDATE", "RUNNING", "SYSTEM"),
        (_task(TaskState.NEEDS_REVIEW, step=OnboardingStep.PUBLISH, profile_id="profile"), 4, "REVIEW_PUBLISH", "WAITING_FOR_MAINTAINER", "MAINTAINER"),
        (_task(TaskState.PUBLISHED, step=None, profile_id="profile"), 5, "REVIEW_PUBLISH", "COMPLETED", "NONE"),
    ],
)
def test_progress_state_table(task, completed, current, activity, actor):
    progress = derive_progress(task, [], [], now=NOW)
    assert (progress.completed, progress.percent) == (completed, completed * 20)
    assert progress.current_stage == current
    assert progress.activity == activity
    assert progress.actor == actor
    assert [stage.id for stage in progress.stages] == [
        "IDENTITY", "FETCH", "ADAPTATION", "BUILD_VALIDATE", "REVIEW_PUBLISH"
    ]
    assert all(stage.activity is None for stage in progress.stages if stage.status == "UPCOMING")


@pytest.mark.parametrize(
    "step,profile_id,completed,current",
    [
        (OnboardingStep.FETCH, None, 1, "FETCH"),
        (OnboardingStep.BUILD, None, 2, "ADAPTATION"),
        (OnboardingStep.BUILD, "profile", 3, "BUILD_VALIDATE"),
        (OnboardingStep.VALIDATE, "profile", 3, "BUILD_VALIDATE"),
        (OnboardingStep.PUBLISH, "profile", 4, "REVIEW_PUBLISH"),
    ],
)
def test_failed_progress_maps_to_exact_failed_stage(step, profile_id, completed, current):
    progress = derive_progress(
        _task(TaskState.FAILED, step=step, profile_id=profile_id), [], [], now=NOW
    )
    assert progress.completed == completed
    assert progress.current_stage == current
    assert progress.activity == "FAILED"
    assert next(stage for stage in progress.stages if stage.id == current).activity == "FAILED"


def test_heartbeat_changes_fingerprint_and_stalled_after_45_seconds():
    task = _task(TaskState.FETCHING, step=OnboardingStep.FETCH)
    recent = [{"heartbeat_at": NOW - timedelta(seconds=10), "started_at": NOW - timedelta(minutes=1), "step": "FETCH", "state": "RUNNING"}]
    old = [{**recent[0], "heartbeat_at": NOW - timedelta(seconds=46)}]
    first = derive_progress(task, recent, [], now=NOW)
    second = derive_progress(task, old, [], now=NOW)
    assert first.stalled is False
    assert second.stalled is True
    assert first.fingerprint != second.fingerprint


def test_cancelled_progress_uses_saved_pre_cancel_snapshot():
    task = _task(TaskState.CANCELLED, step=None)
    events = [{
        "event_id": "cancel", "event_type": "TASK_CANCELLED", "created_at": NOW,
        "payload": {"progress_snapshot": {
            "completed": 2, "total": 5, "percent": 40,
            "current_stage": "ADAPTATION", "actor": "MAINTAINER",
            "fingerprint": "before-cancel",
        }},
    }]
    progress = derive_progress(task, [], events, now=NOW)
    assert progress.completed == 2
    assert progress.percent == 40
    assert progress.current_stage == "ADAPTATION"
    assert progress.activity == "CANCELLED"
