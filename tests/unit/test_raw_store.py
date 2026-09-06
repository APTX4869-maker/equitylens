"""D08: raw snapshot store must discover the LATEST version via a manifest,
not by guessing from directory file names; prior versions stay readable."""

from __future__ import annotations

import pytest

from equitylens.storage.raw_store import load_snapshot, save_snapshot, sha256_bytes


def test_save_load_defaults_to_latest(tmp_path):
    d = tmp_path / "snap"
    p1, sha1 = save_snapshot(d, "companyfacts.json", b'{"v": 1}')
    p2, sha2 = save_snapshot(d, "companyfacts.json", b'{"v": 2}')

    content, sha = load_snapshot(d, "companyfacts.json")
    assert content == b'{"v": 2}'
    assert sha == sha2
    assert sha1 != sha2
    # both files still exist (immutable; original kept)
    assert (d / "companyfacts.json").exists()
    assert p1 != p2 or sha1 == sha2


def test_load_specific_version_by_sha(tmp_path):
    d = tmp_path / "snap"
    _, sha1 = save_snapshot(d, "companyfacts.json", b"version-one")
    _, sha2 = save_snapshot(d, "companyfacts.json", b"version-two")

    content, _ = load_snapshot(d, "companyfacts.json", sha=sha1)
    assert content == b"version-one"
    content, _ = load_snapshot(d, "companyfacts.json", sha=sha2)
    assert content == b"version-two"


def test_save_idempotent(tmp_path):
    d = tmp_path / "snap"
    p1, sha1 = save_snapshot(d, "companyfacts.json", b"same")
    p2, sha2 = save_snapshot(d, "companyfacts.json", b"same")
    assert sha1 == sha2
    assert p1 == p2


def test_corruption_is_detected(tmp_path):
    d = tmp_path / "snap"
    save_snapshot(d, "companyfacts.json", b"pristine")
    # corrupt the stored content while the manifest still records the good hash
    (d / "companyfacts.json").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="corrupted"):
        load_snapshot(d, "companyfacts.json")


def test_sync_offline_reads_latest_snapshot(tmp_path, db):
    """After two fetches (v1 then v2), an offline read must see v2, never the
    older fixed-name v1."""
    from equitylens.ingestion.sec.sync import sync_company

    class StubClient:
        def __init__(self, cf_content: bytes):
            self.cf = cf_content

        def get(self, url):
            if "submissions" in url:
                content = b'{"filings": {"recent": []}}'
            else:
                content = self.cf
            return 200, content, {
                "fetched_at": "2026-01-01T00:00:00",
                "content_length": len(content),
                "status": 200,
            }

        def close(self):
            pass

    raw = tmp_path / "raw"
    v1 = b'{"facts": {"us-gaap": {}}}'
    v2 = b'{"facts": {"us-gaap": {"Revenues": {"units": {"USD": []}}}}}'
    sync_company("AAPL", fetch=True, store=db, client=StubClient(v1), raw_dir=raw)
    sync_company("AAPL", fetch=True, store=db, client=StubClient(v2), raw_dir=raw)

    content, _ = load_snapshot(raw / "sec" / "0000320193", "companyfacts.json")
    assert b"Revenues" in content  # latest (v2), not the v1 fixed-name file
