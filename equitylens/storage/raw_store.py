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
from pathlib import Path

MANIFEST_NAME = "_manifest.json"


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
    """Atomically replace the manifest (temp file + os.replace on same fs)."""
    path = _manifest_path(directory)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    os.replace(tmp, path)


def _versioned_name(doc_name: str, sha: str) -> str:
    p = Path(doc_name)
    return f"{p.stem}.{sha[:8]}{p.suffix}"


def save_snapshot(directory: Path, doc_name: str, content: bytes) -> tuple[Path, str]:
    """Save raw bytes to `directory/doc_name`.

    Returns (path, sha256). Idempotent when content is unchanged; otherwise a
    new versioned file (stem.hash.ext) is created and prior versions are kept.
    The latest pointer is updated only after a successful write.
    """
    directory.mkdir(parents=True, exist_ok=True)
    sha = sha256_bytes(content)
    base = directory / doc_name

    if base.exists() and sha256_bytes(base.read_bytes()) == sha:
        path = base
    elif base.exists():
        # content differs from the canonical fixed name: write a versioned copy
        path = directory / _versioned_name(doc_name, sha)
        if not path.exists():
            path.write_bytes(content)
    else:
        path = base
        path.write_bytes(content)

    # commit the latest pointer only now (atomic-enough: file fully written)
    manifest = _read_manifest(directory)
    manifest[doc_name] = {"sha256": sha, "path": path.name}
    _write_manifest(directory, manifest)
    return path, sha


def load_snapshot(directory: Path, doc_name: str, sha: str | None = None) -> tuple[bytes, str] | None:
    """Load a snapshot for `doc_name`.

    Defaults to the latest successful snapshot recorded in the manifest; pass a
    full or 8-char prefix of a `sha` to read a specific prior version. The
    returned content is always hash-verified against the requested digest.
    """
    if sha is not None:
        return _load_by_sha(directory, doc_name, sha)
    return _load_latest(directory, doc_name)


def _load_by_sha(directory: Path, doc_name: str, sha: str) -> tuple[bytes, str] | None:
    """Strict lookup by full or 8-char-prefix SHA (D08).

    Returns bytes whose computed SHA matches the requested digest, or None when
    no stored snapshot matches (an unknown hash never falls back to the fixed
    legacy name). A versioned file whose name implies the digest but whose bytes
    hash differently is corruption and raises.
    """
    requested = sha.lower()
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
