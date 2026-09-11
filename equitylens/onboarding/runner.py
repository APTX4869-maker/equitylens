"""Single-step durable onboarding runner and lifespan executor."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from typing import Any

from equitylens.onboarding.models import OnboardingStep
from equitylens.onboarding.repository import OnboardingRepository


class OnboardingRunner:
    def __init__(self, store, repository: OnboardingRepository, handlers=None) -> None:
        self.store = store
        self.repository = repository
        self.handlers: dict[OnboardingStep, Callable] = handlers or {}

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
        try:
            output = handler(task)
            output_hash = hashlib.sha256(
                json.dumps(output, sort_keys=True, default=str).encode()
            ).hexdigest()
            current = self.repository.get(task.onboarding_id)
            if current.cancel_requested:
                self.repository.finalize_cancel(current.onboarding_id)
                return True
            self.repository.complete_attempt(task, attempt_id, output_hash)
        except Exception as exc:
            self.repository.fail_attempt(
                task,
                attempt_id,
                {"code": "STEP_FAILED", "message": str(exc), "retryable": True},
                retryable=True,
            )
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
