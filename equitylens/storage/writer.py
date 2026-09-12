"""One process owner and one serialized lane for all canonical DB writes."""

from __future__ import annotations

import fcntl
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class WriterBusy(RuntimeError):
    pass


class DatabaseWriter:
    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path).resolve()
        self.lock_path = self.database_path.with_suffix(
            self.database_path.suffix + ".writer.lock"
        )
        self._thread_lock = threading.RLock()
        self._lock_file = None

    def start(self) -> None:
        if self._lock_file is not None:
            return
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self.lock_path.open("a+")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            lock_file.close()
            raise WriterBusy(
                f"another EquityLens writer owns {self.lock_path}"
            ) from exc
        self._lock_file = lock_file

    def close(self) -> None:
        if self._lock_file is None:
            return
        fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
        self._lock_file.close()
        self._lock_file = None

    @contextmanager
    def serialized(self, *, blocking: bool = True) -> Iterator[None]:
        self.start()
        acquired = self._thread_lock.acquire(blocking=blocking)
        if not acquired:
            raise WriterBusy("another write is already in progress")
        try:
            yield
        finally:
            self._thread_lock.release()

    @contextmanager
    def transaction(self, store, *, blocking: bool = True):
        with self.serialized(blocking=blocking):
            with store.transaction():
                yield store


_WRITERS: dict[Path, DatabaseWriter] = {}
_WRITERS_GUARD = threading.Lock()


def writer_for(store_or_path) -> DatabaseWriter:
    path = Path(getattr(store_or_path, "path", store_or_path)).resolve()
    with _WRITERS_GUARD:
        writer = _WRITERS.get(path)
        if writer is None:
            writer = DatabaseWriter(path)
            _WRITERS[path] = writer
        return writer
