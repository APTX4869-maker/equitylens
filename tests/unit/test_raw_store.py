"""D08: raw snapshot store must discover the LATEST version via a manifest,
not by guessing from directory file names; prior versions stay readable."""

from __future__ import annotations

import json

import pytest

from equitylens.storage.raw_store import (
    load_snapshot,
    load_snapshot_record,
    save_snapshot,
    sha256_bytes,
)


def test_snapshot_record_preserves_fetch_time_and_exact_version_path(tmp_path):
    d = tmp_path / "snap"
    save_snapshot(
        d, "primary.html", b"v1", metadata={"fetched_at": "2025-01-01T00:00:00+00:00"}
    )
    v2_path, v2_sha = save_snapshot(
        d, "primary.html", b"v2", metadata={"fetched_at": "2026-02-03T04:05:06+00:00"}
    )

    record = load_snapshot_record(d, "primary.html")

    assert record is not None
    assert record.content == b"v2"
    assert record.sha256 == v2_sha
    assert record.path == v2_path
    assert record.fetched_at == "2026-02-03T04:05:06+00:00"


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


def test_load_unknown_sha_returns_none_not_legacy(tmp_path):
    """D08: an unknown hash must return None, never the old fixed-name v1."""
    d = tmp_path / "snap"
    save_snapshot(d, "companyfacts.json", b"v1-content")
    save_snapshot(d, "companyfacts.json", b"v2-content")

    assert load_snapshot(d, "companyfacts.json", sha="0" * 64) is None
    assert load_snapshot(d, "companyfacts.json", sha="deadbeef") is None


@pytest.mark.parametrize("bad_sha", ["", "a", "abcdefg", "not-a-sha", "a" * 9, "a" * 63])
def test_load_rejects_malformed_sha_selectors(tmp_path, bad_sha):
    """D08: only an 8-hex prefix or a full SHA-256 is a supported identity.

    Empty and arbitrarily short prefixes must not match unrelated bytes through
    ``computed.startswith(requested)``.
    """
    d = tmp_path / "snap"
    save_snapshot(d, "companyfacts.json", b"v1-content")

    with pytest.raises(ValueError, match="8 hexadecimal|64 hexadecimal"):
        load_snapshot(d, "companyfacts.json", sha=bad_sha)


def test_load_8char_prefix_matches_versioned(tmp_path):
    d = tmp_path / "snap"
    save_snapshot(d, "companyfacts.json", b"v1")
    _, sha2 = save_snapshot(d, "companyfacts.json", b"v2")

    content, computed = load_snapshot(d, "companyfacts.json", sha=sha2[:8])
    assert content == b"v2"
    assert computed == sha2


def test_load_corrupted_versioned_sha_raises(tmp_path):
    """D08: a versioned file whose name implies the digest but whose bytes hash
    differently is corruption, not a valid read."""
    d = tmp_path / "snap"
    save_snapshot(d, "companyfacts.json", b"v1")
    _, sha2 = save_snapshot(d, "companyfacts.json", b"v2")

    versioned = next(
        p for p in d.iterdir()
        if p.name != "companyfacts.json" and p.name != "_manifest.json"
    )
    versioned.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="corrupted"):
        load_snapshot(d, "companyfacts.json", sha=sha2)


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


def test_company_offline_replay_does_not_refresh_source_fetch_time(tmp_path, db):
    from equitylens.ingestion.sec.sync import sync_company

    class StubClient:
        def get(self, url):
            content = (
                b'{"filings": {"recent": []}}'
                if "submissions" in url
                else b'{"facts": {"us-gaap": {}}}'
            )
            return 200, content, {
                "fetched_at": "2020-01-02T03:04:05+00:00",
                "content_length": len(content),
                "status": 200,
            }

        def close(self):
            pass

    raw = tmp_path / "raw-fetch-time"
    sync_company("AAPL", fetch=True, store=db, client=StubClient(), raw_dir=raw)
    sync_company("AAPL", fetch=False, store=db, raw_dir=raw)

    rows = db.query(
        """SELECT fetched_at FROM source_document
           WHERE company_id = '0000320193'
             AND document_type IN ('SUBMISSIONS_SNAPSHOT', 'COMPANYFACTS_SNAPSHOT')"""
    )
    assert len(rows) == 2
    assert {str(row["fetched_at"]) for row in rows} == {"2020-01-02 03:04:05"}


def test_filing_offline_replay_reads_manifest_version_path(tmp_path, db):
    from equitylens.ingestion.sec.filing_docs import fetch_filing_documents

    cik = "0000320193"
    raw = tmp_path / "raw-filing-version"
    company_dir = raw / "sec" / cik
    filing_dir = company_dir / "filing_docs" / "0000320193-26-000001"
    submissions = {
        "filings": {"recent": [{
            "form": "10-K",
            "accessionNumber": "0000320193-26-000001",
            "primaryDocument": "aapl-2026.htm",
            "reportDate": "2026-09-26",
            "filingDate": "2026-10-30",
        }]}
    }
    save_snapshot(company_dir, "submissions.json", json.dumps(submissions).encode())
    save_snapshot(filing_dir, "primary.html", b"old filing")
    expected_path, expected_sha = save_snapshot(
        filing_dir,
        "primary.html",
        b"restated filing",
        metadata={"fetched_at": "2026-11-01T00:00:00+00:00"},
    )

    docs = fetch_filing_documents(
        "AAPL", forms=("10-K",), limit_per_form=1,
        fetch=False, store=db, raw_dir=raw,
    )

    assert len(docs) == 1
    assert docs[0].content_sha256 == expected_sha
    assert docs[0].local_path == str(expected_path)
    assert expected_path.read_bytes() == b"restated filing"
    assert docs[0].fetched_at == "2026-11-01T00:00:00+00:00"


def test_two_snapshot_restatement_replays_latest_into_fresh_database(tmp_path, db):
    """D05/D08: latest snapshot bytes must drive a fresh offline normalization."""
    from equitylens.ingestion.sec.sync import sync_company
    from equitylens.metrics.engine import MetricEngine
    from equitylens.storage.duckdb_store import DuckDBStore

    submissions = json.dumps({
        "filings": {"recent": [{"form": "10-K", "reportDate": "2025-09-27"}]}
    }).encode()

    def companyfacts(value: int, filed: str, accn: str) -> bytes:
        return json.dumps({"facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [{
                "start": "2024-09-29", "end": "2025-09-27", "val": value,
                "accn": accn, "fy": 2025, "fp": "FY", "form": "10-K", "filed": filed,
            }]}}
        }}}).encode()

    class StubClient:
        def __init__(self, facts: bytes):
            self.facts = facts

        def get(self, url):
            content = submissions if "submissions" in url else self.facts
            return 200, content, {
                "fetched_at": "2026-01-01T00:00:00", "content_length": len(content), "status": 200,
            }

    raw = tmp_path / "raw-restatement"
    sync_company("AAPL", fetch=True, store=db, client=StubClient(companyfacts(100, "2025-10-30", "v1")), raw_dir=raw)
    sync_company("AAPL", fetch=True, store=db, client=StubClient(companyfacts(120, "2026-10-30", "v2")), raw_dir=raw)
    assert MetricEngine(db).compute("REVENUE", "0000320193", frequency="annual")[-1].value == 120

    replay = DuckDBStore(tmp_path / "replay.duckdb")
    replay.connect()
    replay.init_schema()
    try:
        sync_company("AAPL", fetch=False, store=replay, raw_dir=raw)
        first_count = replay.query_one("SELECT COUNT(*) AS n FROM canonical_fact")["n"]
        assert MetricEngine(replay).compute("REVENUE", "0000320193", frequency="annual")[-1].value == 120
        sync_company("AAPL", fetch=False, store=replay, raw_dir=raw)
        assert replay.query_one("SELECT COUNT(*) AS n FROM canonical_fact")["n"] == first_count
    finally:
        replay.close()


def test_failed_multi_document_fetch_keeps_previous_latest_set(tmp_path, db):
    """D08: a partial network failure cannot publish half of a new SEC snapshot set."""
    from equitylens.ingestion.sec.sync import sync_company

    class Client:
        def __init__(self, submissions: bytes, facts: bytes | None):
            self.submissions = submissions
            self.facts = facts

        def get(self, url):
            if "submissions" in url:
                content = self.submissions
            elif self.facts is None:
                raise RuntimeError("companyfacts failed")
            else:
                content = self.facts
            return 200, content, {
                "fetched_at": "2026-01-01T00:00:00", "content_length": len(content), "status": 200,
            }

    raw = tmp_path / "raw-atomic"
    old_submissions = b'{"filings":{"recent":[]},"version":1}'
    old_facts = b'{"facts":{"us-gaap":{}},"version":1}'
    sync_company("AAPL", fetch=True, store=db, client=Client(old_submissions, old_facts), raw_dir=raw)

    with pytest.raises(RuntimeError, match="companyfacts failed"):
        sync_company(
            "AAPL", fetch=True, store=db,
            client=Client(b'{"filings":{"recent":[]},"version":2}', None), raw_dir=raw,
        )

    directory = raw / "sec" / "0000320193"
    assert load_snapshot(directory, "submissions.json")[0] == old_submissions
    assert load_snapshot(directory, "companyfacts.json")[0] == old_facts
