"""Durable source-document path finalization and read-only auditing."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path

import duckdb


@dataclass(frozen=True)
class SourcePathAuditItem:
    source_document_id: str
    status: str
    stored_path: str | None
    candidate_path: str | None = None


@dataclass(frozen=True)
class SourcePathAudit:
    items: tuple[SourcePathAuditItem, ...]

    @property
    def counts(self) -> dict[str, int]:
        counts = {key: 0 for key in ("valid", "recoverable", "hash_mismatch", "missing")}
        for item in self.items:
            counts[item.status] += 1
        return counts


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _raw_relative(path: Path) -> Path | None:
    indexes = [index for index, part in enumerate(path.parts) if part == "raw"]
    if not indexes or indexes[-1] == len(path.parts) - 1:
        return None
    return Path(*path.parts[indexes[-1] + 1 :])


def finalize_staged_source_paths(store, stage_root: Path, raw_root: Path) -> int:
    """Repoint rows written below one stage to verified durable files.

    The caller owns the database transaction and must publish staged bytes
    before calling this function.
    """
    stage_root = stage_root.resolve()
    raw_root = raw_root.resolve()
    updated = 0
    rows = store.query(
        "SELECT source_document_id, local_path, content_sha256 "
        "FROM source_document WHERE local_path IS NOT NULL"
    )
    for row in rows:
        staged = Path(row["local_path"]).resolve()
        if not staged.is_relative_to(stage_root):
            continue
        durable = raw_root / staged.relative_to(stage_root)
        if not durable.is_file():
            raise FileNotFoundError(f"published source document is missing: {durable}")
        if _sha256(durable) != row["content_sha256"]:
            raise ValueError(
                f"published source document hash mismatch: {row['source_document_id']}"
            )
        store._conn.execute(
            "UPDATE source_document SET local_path=? WHERE source_document_id=?",
            [str(durable), row["source_document_id"]],
        )
        updated += 1
    return updated


def audit_source_paths(store, raw_root: Path) -> SourcePathAudit:
    """Classify source paths without changing database or filesystem state."""
    raw_root = raw_root.resolve()
    items: list[SourcePathAuditItem] = []
    rows = store.query(
        "SELECT source_document_id, local_path, content_sha256 "
        "FROM source_document ORDER BY source_document_id"
    )
    for row in rows:
        stored_text = row.get("local_path")
        stored = Path(stored_text).resolve() if stored_text else None
        expected = row["content_sha256"]
        if stored is not None and stored.is_file():
            status = "valid" if _sha256(stored) == expected else "hash_mismatch"
            items.append(SourcePathAuditItem(
                row["source_document_id"], status, stored_text, str(stored)
            ))
            continue

        relative = _raw_relative(Path(stored_text)) if stored_text else None
        candidate = (raw_root / relative).resolve() if relative is not None else None
        contained = candidate is not None and candidate.is_relative_to(raw_root)
        if contained and candidate.is_file():
            status = "recoverable" if _sha256(candidate) == expected else "hash_mismatch"
            candidate_text = str(candidate)
        else:
            status = "missing"
            candidate_text = str(candidate) if contained else None
        items.append(SourcePathAuditItem(
            row["source_document_id"], status, stored_text, candidate_text
        ))
    return SourcePathAudit(tuple(items))


class _ReadOnlyStore:
    def __init__(self, connection: duckdb.DuckDBPyConnection):
        self._connection = connection

    def query(self, sql: str) -> list[dict]:
        result = self._connection.execute(sql)
        columns = [item[0] for item in result.description]
        return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit source paths without writes")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    args = parser.parse_args()
    connection = duckdb.connect(str(args.db), read_only=True)
    try:
        result = audit_source_paths(_ReadOnlyStore(connection), args.raw_root)
    finally:
        connection.close()
    print(json.dumps(
        {"counts": result.counts, "items": [asdict(item) for item in result.items]},
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
