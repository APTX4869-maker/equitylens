"""Single-step durable onboarding runner and lifespan executor."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from typing import Any

from equitylens.onboarding.models import OnboardingStep
from equitylens.onboarding.repository import OnboardingRepository


class OnboardingPause(RuntimeError):
    """A successful step that intentionally waits for maintainer input."""

    def __init__(self, state, current_step, message: str, *, candidate_artifact=None) -> None:
        super().__init__(message)
        self.state = state
        self.current_step = current_step
        self.candidate_artifact = candidate_artifact


class OnboardingRunner:
    def __init__(
        self, store, repository: OnboardingRepository, handlers=None,
        *, heartbeat_seconds: float = 10.0,
    ) -> None:
        self.store = store
        self.repository = repository
        self.handlers: dict[OnboardingStep, Callable] = handlers or {}
        self.heartbeat_seconds = heartbeat_seconds

    def recover_interrupted(self) -> int:
        return self.repository.recover_interrupted()

    def run_once(self) -> bool:
        task = self.repository.runnable()
        if task is None or task.current_step is None:
            return False
        if task.cancel_requested:
            self.repository.finalize_cancel(task.onboarding_id)
            return True
        if self.repository.completed_attempt(task):
            self.repository.advance_completed(task)
            return True
        handler = self.handlers.get(task.current_step)
        if handler is None:
            return False
        attempt_id = self.repository.begin_attempt(task)
        stop_heartbeat = threading.Event()

        def heartbeat_loop():
            while not stop_heartbeat.wait(self.heartbeat_seconds):
                try:
                    self.repository.heartbeat_attempt(attempt_id)
                except Exception:
                    return

        heartbeat = threading.Thread(target=heartbeat_loop, daemon=True)
        heartbeat.start()

        def stop_heartbeat_loop():
            stop_heartbeat.set()
            heartbeat.join(timeout=max(1.0, self.heartbeat_seconds * 2))

        try:
            output = handler(task)
            stop_heartbeat_loop()
            output_hash = hashlib.sha256(
                json.dumps(output, sort_keys=True, default=str).encode()
            ).hexdigest()
            current = self.repository.get(task.onboarding_id)
            if current.cancel_requested:
                self.repository.finalize_cancel(current.onboarding_id)
                return True
            self.repository.complete_attempt(task, attempt_id, output_hash)
        except OnboardingPause as pause:
            stop_heartbeat_loop()
            self.repository.pause_attempt(
                task,
                attempt_id,
                state=pause.state,
                current_step=pause.current_step,
                message=str(pause),
                candidate_artifact=pause.candidate_artifact,
            )
        except Exception as exc:
            stop_heartbeat_loop()
            retryable = bool(getattr(exc, "retryable", False))
            self.repository.fail_attempt(
                task,
                attempt_id,
                {
                    "code": getattr(exc, "code", "STEP_FAILED"),
                    "message": str(exc),
                    "retryable": retryable,
                },
                retryable=retryable,
            )
        finally:
            stop_heartbeat_loop()
        return True


class OnboardingExecutor:
    def __init__(self, runner: OnboardingRunner, *, poll_seconds: float = 1.0) -> None:
        self.runner = runner
        self.poll_seconds = poll_seconds
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.runner.recover_interrupted()
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.is_set():
            progressed = self.runner.run_once()
            if not progressed:
                self._wake.wait(self.poll_seconds)
                self._wake.clear()
