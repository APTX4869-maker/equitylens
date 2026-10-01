from __future__ import annotations

import hashlib
from pathlib import Path


def _insert_document(db, document_id: str, local_path: Path, content: bytes) -> None:
    db.upsert_source_documents([{
        "source_document_id": document_id,
        "company_id": "0000000001",
        "provider": "SEC",
        "document_type": "FILING_DOCUMENT",
        "source_url": f"https://example.test/{document_id}",
        "fetched_at": "2026-10-01T00:00:00+00:00",
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "local_path": str(local_path),
    }])


def test_source_path_audit_classifies_without_mutating_rows(db, tmp_path):
    from equitylens.storage.source_paths import audit_source_paths

    raw_root = tmp_path / "raw"
    valid = raw_root / "sec" / "1" / "valid.html"
    valid.parent.mkdir(parents=True)
    valid.write_bytes(b"valid")
    _insert_document(db, "valid", valid, b"valid")

    old_root = tmp_path / "deleted-stage" / "raw"
    recoverable_old = old_root / "sec" / "1" / "recoverable.html"
    recoverable_new = raw_root / "sec" / "1" / "recoverable.html"
    recoverable_new.write_bytes(b"recoverable")
    _insert_document(db, "recoverable", recoverable_old, b"recoverable")

    mismatch_old = old_root / "sec" / "1" / "mismatch.html"
    mismatch_new = raw_root / "sec" / "1" / "mismatch.html"
    mismatch_new.write_bytes(b"changed")
    _insert_document(db, "mismatch", mismatch_old, b"original")

    missing = old_root / "sec" / "1" / "missing.html"
    _insert_document(db, "missing", missing, b"missing")

    before = {
        row["source_document_id"]: row["local_path"]
        for row in db.query("SELECT source_document_id, local_path FROM source_document")
    }
    result = audit_source_paths(db, raw_root)
    after = {
        row["source_document_id"]: row["local_path"]
        for row in db.query("SELECT source_document_id, local_path FROM source_document")
    }

    assert result.counts == {
        "valid": 1,
        "recoverable": 1,
        "hash_mismatch": 1,
        "missing": 1,
    }
    assert {item.source_document_id: item.status for item in result.items} == {
        "valid": "valid",
        "recoverable": "recoverable",
        "mismatch": "hash_mismatch",
        "missing": "missing",
    }
    assert after == before
