"""Immutable raw source storage.

Snapshots are saved before parsing and verified by SHA-256. An artifact is
never overwritten: if content changes, a new hash-suffixed version is written.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def save_snapshot(directory: Path, doc_name: str, content: bytes) -> tuple[Path, str]:
    """Save raw bytes to `directory/doc_name`.

    Returns (path, sha256). Idempotent when content is unchanged; otherwise a
    new versioned file (stem.hash.ext) is created and the original is kept.
    """
    directory.mkdir(parents=True, exist_ok=True)
    sha = sha256_bytes(content)
    path = directory / doc_name
    if path.exists():
        if sha256_bytes(path.read_bytes()) == sha:
            return path, sha
        path = directory / f"{Path(doc_name).stem}.{sha[:8]}{Path(doc_name).suffix}"
    path.write_bytes(content)
    return path, sha


def load_snapshot(directory: Path, doc_name: str) -> tuple[bytes, str] | None:
    path = directory / doc_name
    if not path.exists():
        return None
    content = path.read_bytes()
    return content, sha256_bytes(content)
