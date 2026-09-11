"""Immutable raw source storage.

Snapshots are saved before parsing and verified by SHA-256. An artifact is
never overwritten: if content changes, a new hash-suffixed version is written.

A per-directory manifest (`_manifest.json`) records the LATEST successful
snapshot for each document name, so readers do not have to guess the newest
version from directory file names or mtimes. The manifest pointer is only
updated after a snapshot is fully written — a failed fetch never advances the
"latest" pointer to a half-written artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_NAME = "_manifest.json"


@dataclass(frozen=True)
class SnapshotRecord:
    content: bytes
    sha256: str
    path: Path
    fetched_at: str


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _manifest_path(directory: Path) -> Path:
    return directory / MANIFEST_NAME


def _read_manifest(directory: Path) -> dict:
    p = _manifest_path(directory)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_manifest(directory: Path, manifest: dict) -> None:
    """Durably replace the manifest after writing it on the same filesystem."""
    path = _manifest_path(directory)
    payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=directory)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _fsync_directory(directory)
    finally:
        tmp.unlink(missing_ok=True)


def _fsync_directory(directory: Path) -> None:
    """Make a completed rename durable where directory fsync is supported."""
    try:
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


@contextmanager
def _manifest_lock(directory: Path):
    """Serialize snapshot publication so concurrent writers cannot lose pointers."""
    import fcntl

    lock_path = directory / ".manifest.lock"
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_immutable(path: Path, content: bytes) -> None:
    """Create immutable snapshot bytes and make the directory entry durable."""
    try:
        with path.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(path.parent)
    except FileExistsError:
        if sha256_bytes(path.read_bytes()) != sha256_bytes(content):
            raise ValueError(f"snapshot filename collision for {path.name}")


def _versioned_name(doc_name: str, sha: str) -> str:
    p = Path(doc_name)
    return f"{p.stem}.{sha[:8]}{p.suffix}"


def save_snapshots(
    directory: Path,
    documents: dict[str, bytes],
    metadata: dict[str, dict] | None = None,
) -> dict[str, tuple[Path, str]]:
    """Durably publish a related set of snapshots with one manifest update.

    All immutable files are written before any latest pointer changes. If a
    write fails, the old manifest remains authoritative; successfully written
    orphan bytes are harmless and may be reused by a later retry.
    """
    directory.mkdir(parents=True, exist_ok=True)
    results: dict[str, tuple[Path, str]] = {}
    with _manifest_lock(directory):
        manifest = _read_manifest(directory)
        next_manifest = dict(manifest)
        for doc_name, content in documents.items():
            sha = sha256_bytes(content)
            base = directory / doc_name
            if base.exists() and sha256_bytes(base.read_bytes()) == sha:
                path = base
            elif base.exists():
                path = directory / _versioned_name(doc_name, sha)
                _write_immutable(path, content)
            else:
                path = base
                _write_immutable(path, content)
            results[doc_name] = (path, sha)
            next_manifest[doc_name] = {
                "sha256": sha,
                "path": path.name,
                **dict((metadata or {}).get(doc_name) or {}),
            }
        # Publish the complete set only after every immutable file is durable.
        manifest = next_manifest
        _write_manifest(directory, manifest)
    return results


def save_snapshot(
    directory: Path,
    doc_name: str,
    content: bytes,
    metadata: dict | None = None,
) -> tuple[Path, str]:
    """Save one immutable snapshot and update its latest pointer."""
    return save_snapshots(
        directory,
        {doc_name: content},
        metadata={doc_name: metadata or {}},
    )[doc_name]


def snapshot_path(directory: Path, doc_name: str, sha: str) -> Path:
    """Return the stored path for hash-verified bytes without guessing latest."""
    fixed = directory / doc_name
    if fixed.exists() and sha256_bytes(fixed.read_bytes()) == sha:
        return fixed
    versioned = directory / _versioned_name(doc_name, sha)
    if versioned.exists() and sha256_bytes(versioned.read_bytes()) == sha:
        return versioned
    raise FileNotFoundError(f"no snapshot path for {doc_name}@{sha[:8]}")


def load_snapshot(directory: Path, doc_name: str, sha: str | None = None) -> tuple[bytes, str] | None:
    """Load a snapshot for `doc_name`.

    Defaults to the latest successful snapshot recorded in the manifest; pass a
    full or 8-char prefix of a `sha` to read a specific prior version. The
    returned content is always hash-verified against the requested digest.
    """
    if sha is not None:
        return _load_by_sha(directory, doc_name, sha)
    return _load_latest(directory, doc_name)


def load_snapshot_record(
    directory: Path, doc_name: str, sha: str | None = None
) -> SnapshotRecord | None:
    """Load verified bytes together with their exact path and capture time.

    New manifests persist the provider fetch time. Legacy snapshots fall back
    to the immutable file's mtime, which is stable across offline replays and
    is preserved by migration copies.
    """
    loaded = load_snapshot(directory, doc_name, sha=sha)
    if loaded is None:
        return None
    content, computed = loaded
    path = snapshot_path(directory, doc_name, computed)
    entry = _read_manifest(directory).get(doc_name) or {}
    fetched_at = None
    if entry.get("sha256") == computed and entry.get("path") == path.name:
        fetched_at = entry.get("fetched_at")
    if not fetched_at:
        fetched_at = datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).replace(microsecond=0).isoformat()
    return SnapshotRecord(content, computed, path, str(fetched_at))


def _load_by_sha(directory: Path, doc_name: str, sha: str) -> tuple[bytes, str] | None:
    """Strict lookup by full or 8-char-prefix SHA (D08).

    Returns bytes whose computed SHA matches the requested digest, or None when
    no stored snapshot matches (an unknown hash never falls back to the fixed
    legacy name). A versioned file whose name implies the digest but whose bytes
    hash differently is corruption and raises.
    """
    requested = sha.lower()
    if len(requested) not in (8, 64) or re.fullmatch(r"[0-9a-f]+", requested) is None:
        raise ValueError("snapshot sha must be 8 hexadecimal characters or 64 hexadecimal characters")
    versioned = directory / _versioned_name(doc_name, requested)
    if versioned.exists():
        content = versioned.read_bytes()
        computed = sha256_bytes(content)
        if not computed.startswith(requested):
            raise ValueError(
                f"snapshot {doc_name}@{requested[:8]} is corrupted "
                f"(content hash {computed[:8]} does not match)"
            )
        return content, computed

    # No versioned file: the fixed legacy name may satisfy the request only when
    # its actual digest matches — a mismatched digest returns None, not v1 bytes.
    fixed = directory / doc_name
    if fixed.exists():
        content = fixed.read_bytes()
        computed = sha256_bytes(content)
        if computed.startswith(requested):
            return content, computed
    return None


def _load_latest(directory: Path, doc_name: str) -> tuple[bytes, str] | None:
    manifest = _read_manifest(directory)
    entry = manifest.get(doc_name)
    if entry and entry.get("path"):
        path = directory / entry["path"]
        if path.exists():
            content = path.read_bytes()
            computed = sha256_bytes(content)
            if entry.get("sha256") and computed != entry["sha256"]:
                raise ValueError(
                    f"snapshot {doc_name} is corrupted (hash {computed[:8]} != {entry['sha256'][:8]})"
                )
            return content, computed

    # fallback: fixed name (pre-manifest / fixture layout)
    path = directory / doc_name
    if not path.exists():
        return None
    content = path.read_bytes()
    return content, sha256_bytes(content)
