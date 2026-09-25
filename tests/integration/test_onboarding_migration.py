from __future__ import annotations

import hashlib
import shutil

import duckdb
import pytest

from equitylens.storage.migrations import MigrationChecksumError, apply_migrations


LEGACY_SCHEMA = """
CREATE TABLE company (
  company_id VARCHAR PRIMARY KEY,
  ticker VARCHAR NOT NULL,
  cik VARCHAR,
  legal_name VARCHAR,
  fiscal_year_end VARCHAR,
  exchange VARCHAR,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);
CREATE TABLE market_quote (
  quote_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL,
  ticker VARCHAR NOT NULL,
  provider VARCHAR NOT NULL,
  observed_at VARCHAR,
  price DOUBLE NOT NULL,
  currency VARCHAR,
  fetched_at TIMESTAMP
);
CREATE TABLE valuation_run (
  valuation_run_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL,
  model_name VARCHAR NOT NULL,
  model_version VARCHAR NOT NULL,
  run_at TIMESTAMP NOT NULL,
  market_observation_id VARCHAR,
  assumption_set_id VARCHAR NOT NULL,
  fact_snapshot_json JSON NOT NULL,
  output_json JSON NOT NULL,
  warnings_json JSON
);
CREATE TABLE valuation_assumption_set (
  assumption_set_id VARCHAR PRIMARY KEY
);
CREATE TABLE valuation_plan (
  plan_id VARCHAR PRIMARY KEY
);
"""


def _legacy_database(path):
    conn = duckdb.connect(str(path))
    conn.execute(LEGACY_SCHEMA)
    conn.execute(
        "INSERT INTO company VALUES (?, ?, ?, ?, ?, ?, now(), now())",
        ["0000320193", "AAPL", "0000320193", "Apple Inc.", "09-30", "NASDAQ"],
    )
    conn.execute(
        "INSERT INTO market_quote VALUES (?, ?, ?, ?, ?, ?, ?, now())",
        ["quote-aapl", "0000320193", "AAPL", "fixture", "2026-09-03", 100.0, "USD"],
    )
    conn.execute(
        "INSERT INTO valuation_run VALUES (?, ?, ?, ?, now(), NULL, ?, ?, ?, ?)",
        ["run-aapl", "0000320193", "FCFF_DCF", "v1", "assumption-aapl", "{}", "{}", "[]"],
    )
    conn.close()


def _table_digest(conn, table):
    rows = conn.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall()
    return hashlib.sha256(repr(rows).encode()).hexdigest(), len(rows)


def test_identity_migration_is_idempotent_and_preserves_legacy_rows(tmp_path):
    source = tmp_path / "legacy.duckdb"
    migrated = tmp_path / "migrated.duckdb"
    _legacy_database(source)
    shutil.copy2(source, migrated)

    conn = duckdb.connect(str(migrated))
    before = {
        table: _table_digest(conn, table)
        for table in ("market_quote", "valuation_run")
    }
    first = apply_migrations(conn, target_version=1)
    after_first = {
        table: _table_digest(conn, table)
        for table in ("market_quote", "valuation_run")
    }
    second = apply_migrations(conn, target_version=1)

    assert first == [1]
    assert second == []
    assert after_first == before
    assert conn.execute("SELECT count(*) FROM schema_migration").fetchone() == (1,)
    assert conn.execute("SELECT count(*) FROM security").fetchone() == (2,)
    aapl = conn.execute(
        "SELECT s.company_id, a.ticker, s.exchange FROM security s "
        "JOIN security_ticker_alias a USING (security_id) WHERE a.ticker = 'AAPL'"
    ).fetchone()
    assert aapl == ("0000320193", "AAPL", "NASDAQ")
    company = conn.execute(
        "SELECT reporting_template, quality_status FROM company WHERE company_id='0000320193'"
    ).fetchone()
    assert company == ("us_gaap_operating_v1", "LEGACY_UNREVIEWED")
    conn.close()


def test_applied_migration_checksum_is_immutable(tmp_path):
    path = tmp_path / "legacy.duckdb"
    _legacy_database(path)
    conn = duckdb.connect(str(path))
    apply_migrations(conn, target_version=1)
    conn.execute("UPDATE schema_migration SET checksum = 'tampered' WHERE version = 1")

    with pytest.raises(MigrationChecksumError):
        apply_migrations(conn, target_version=1)
    conn.close()


def test_onboarding_closure_migration_is_additive_and_idempotent(tmp_path):
    path = tmp_path / "legacy.duckdb"
    _legacy_database(path)
    conn = duckdb.connect(str(path))

    first = apply_migrations(conn)
    second = apply_migrations(conn)
    tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    task_columns = {
        row[1] for row in conn.execute("PRAGMA table_info('company_onboarding')").fetchall()
    }

    assert first == [1, 2, 3, 4, 5, 6, 7]
    assert second == []
    assert {
        "onboarding_fetch_bundle",
        "onboarding_fetch_document",
        "issuer_profile_candidate",
        "onboarding_event",
        "profile_import_idempotency",
    } <= tables
    assert {"fetch_bundle_id", "profile_candidate_id"} <= task_columns
    assert conn.execute("SELECT count(*) FROM company").fetchone() == (2,)
    conn.close()
