"""DuckDB persistence layer.

One DuckDB database holds the canonical fact store and application metadata.
Raw snapshots live on disk (see storage/raw_store.py); the DB references them
by hash-verified path.

The schema comes from spec/schema.sql (the handoff's logical schema) plus a
small set of runtime tables (ingestion_run, mapping_log).
"""

from __future__ import annotations

import json
import sqlite3  # noqa: F401  (reminder: not used; DuckDB only)
from contextlib import contextmanager
from pathlib import Path

import duckdb

from equitylens.config import DB_PATH, SPEC_DIR

EXTRA_SCHEMA = """
-- M6: management / governance records
CREATE TABLE IF NOT EXISTS executive (
  executive_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL,
  name VARCHAR NOT NULL,
  title VARCHAR,
  source_document_id VARCHAR,
  source_doc_type VARCHAR,
  as_of_year INTEGER
);
CREATE TABLE IF NOT EXISTS executive_compensation (
  comp_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL,
  executive_id VARCHAR,
  fiscal_year INTEGER NOT NULL,
  salary DOUBLE,
  bonus DOUBLE,
  stock_awards DOUBLE,
  option_awards DOUBLE,
  non_equity_incentive DOUBLE,
  all_other DOUBLE,
  total_compensation DOUBLE,
  source_document_id VARCHAR
);
CREATE TABLE IF NOT EXISTS board_member (
  board_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL,
  name VARCHAR NOT NULL,
  occupation VARCHAR,
  age INTEGER,
  director_since VARCHAR,
  independent VARCHAR,
  committees VARCHAR,
  source_document_id VARCHAR
);
CREATE TABLE IF NOT EXISTS insider_transaction (
  transaction_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL,
  insider_name VARCHAR NOT NULL,
  insider_cik VARCHAR,
  officer_title VARCHAR,
  transaction_date DATE,
  transaction_code VARCHAR,
  security_title VARCHAR,
  shares DOUBLE,
  price_per_share DOUBLE,
  acquired_disposed_code VARCHAR,
  shares_owned_after DOUBLE,
  filed_at DATE,
  accession_number VARCHAR,
  source_url VARCHAR,
  source_document_id VARCHAR
);

-- ownership column so a canonical fact resolves to its source document
-- without a join, and re-normalization is idempotent per document
ALTER TABLE canonical_fact ADD COLUMN IF NOT EXISTS source_document_id VARCHAR;
ALTER TABLE segment_fact ADD COLUMN IF NOT EXISTS segment_kind VARCHAR;
ALTER TABLE segment_fact ADD COLUMN IF NOT EXISTS period_type VARCHAR;
ALTER TABLE raw_fact ADD COLUMN IF NOT EXISTS accession_number VARCHAR;
ALTER TABLE raw_fact ADD COLUMN IF NOT EXISTS form_type VARCHAR;
ALTER TABLE raw_fact ADD COLUMN IF NOT EXISTS filed_at VARCHAR;

CREATE TABLE IF NOT EXISTS ingestion_run (
  run_id VARCHAR PRIMARY KEY,
  company_id VARCHAR,
  provider VARCHAR NOT NULL,
  command VARCHAR,
  started_at TIMESTAMP,
  finished_at TIMESTAMP,
  status VARCHAR,
  fetched_bytes BIGINT,
  facts_seen BIGINT,
  facts_accepted BIGINT,
  facts_rejected BIGINT,
  warnings_json JSON
);

-- M8: market quote observations (external facts, never overwritten; latest wins by fetched_at)
CREATE TABLE IF NOT EXISTS market_quote (
  quote_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL,
  security_id VARCHAR,
  ticker VARCHAR NOT NULL,
  provider VARCHAR NOT NULL,
  observed_at VARCHAR,
  price DOUBLE NOT NULL,
  currency VARCHAR,
  prev_close DOUBLE,
  open_price DOUBLE,
  high DOUBLE,
  low DOUBLE,
  market_cap DOUBLE,
  name VARCHAR,
  source_label VARCHAR,
  source_url VARCHAR,
  snapshot_sha VARCHAR,
  fetched_at TIMESTAMP
);

-- P06: personal reference-price plans. Immutable once saved; the reference price
-- is reference_value * (1 - margin_of_safety). No order/broker/trading actions.
CREATE TABLE IF NOT EXISTS valuation_plan (
  plan_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL,
  ticker VARCHAR NOT NULL,
  name VARCHAR NOT NULL,
  reference_value DOUBLE,
  reference_source VARCHAR,
  margin_of_safety DOUBLE,
  reference_price DOUBLE,
  notes VARCHAR,
  assumptions_json JSON,
  valuation_run_id VARCHAR,
  scenario_key VARCHAR,
  source_input_fingerprint VARCHAR,
  reference_price_reason VARCHAR,
  conditions_json JSON,
  parent_plan_id VARCHAR,
  version INTEGER,
  review_status VARCHAR,
  review_reason VARCHAR,
  source_filing_as_of TIMESTAMP,
  source_quote_observed_at VARCHAR,
  created_at TIMESTAMP NOT NULL
);
"""

# Idempotent additive migrations: add nullable columns to legacy tables so
# existing rows are preserved and reads can distinguish legacy/incomplete rows.
_MIGRATIONS = [
    "ALTER TABLE valuation_run ADD COLUMN IF NOT EXISTS input_fingerprint VARCHAR",
    "ALTER TABLE valuation_run ADD COLUMN IF NOT EXISTS scenarios_json JSON",
    "ALTER TABLE valuation_run ADD COLUMN IF NOT EXISTS sensitivity_json JSON",
    "ALTER TABLE valuation_run ADD COLUMN IF NOT EXISTS model_quality_json JSON",
    "ALTER TABLE valuation_plan ADD COLUMN IF NOT EXISTS valuation_run_id VARCHAR",
    "ALTER TABLE valuation_plan ADD COLUMN IF NOT EXISTS scenario_key VARCHAR",
    "ALTER TABLE valuation_plan ADD COLUMN IF NOT EXISTS source_input_fingerprint VARCHAR",
    "ALTER TABLE valuation_plan ADD COLUMN IF NOT EXISTS reference_price_reason VARCHAR",
    "ALTER TABLE valuation_plan ADD COLUMN IF NOT EXISTS conditions_json JSON",
    "ALTER TABLE valuation_plan ADD COLUMN IF NOT EXISTS parent_plan_id VARCHAR",
    "ALTER TABLE valuation_plan ADD COLUMN IF NOT EXISTS version INTEGER",
    "ALTER TABLE valuation_plan ADD COLUMN IF NOT EXISTS review_status VARCHAR",
    "ALTER TABLE valuation_plan ADD COLUMN IF NOT EXISTS review_reason VARCHAR",
    "ALTER TABLE valuation_plan ADD COLUMN IF NOT EXISTS source_filing_as_of TIMESTAMP",
    "ALTER TABLE valuation_plan ADD COLUMN IF NOT EXISTS source_quote_observed_at VARCHAR",
]


class DuckDBStore:
    def __init__(self, path: Path | str = DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._transaction_depth = 0

    def connect(self) -> "DuckDBStore":
        if self._conn is None:
            self._conn = duckdb.connect(str(self.path))
        return self

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @contextmanager
    def transaction(self):
        """Commit one publication unit or roll every database write back."""
        self.connect()
        if self._transaction_depth:
            self._transaction_depth += 1
            try:
                yield self
            finally:
                self._transaction_depth -= 1
            return
        self._conn.execute("BEGIN TRANSACTION")
        self._transaction_depth = 1
        try:
            yield self
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")
        finally:
            self._transaction_depth = 0

    def init_schema(self) -> None:
        from equitylens.storage.writer import writer_for

        self.connect()
        with writer_for(self).serialized():
            schema = (SPEC_DIR / "schema.sql").read_text()
            for statement in self._split_statements(schema):
                self._conn.execute(statement)
            for statement in self._split_statements(EXTRA_SCHEMA):
                self._conn.execute(statement)
            for statement in _MIGRATIONS:
                self._conn.execute(statement)
            from equitylens.storage.migrations import apply_migrations

            apply_migrations(self._conn)

    @staticmethod
    def _split_statements(sql: str) -> list[str]:
        # naive but sufficient: split on ';' at line ends, drop comments
        out, buf = [], []
        for line in sql.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                continue
            buf.append(line)
            if stripped.endswith(";"):
                out.append("\n".join(buf).rstrip(";"))
                buf = []
        if buf:
            out.append("\n".join(buf))
        return [s for s in out if s.strip()]

    # ---------------- writes ----------------

    def upsert_source_documents(self, rows: list[dict]) -> None:
        if not rows:
            return
        self.connect()
        from equitylens.storage.writer import writer_for

        with writer_for(self).transaction(self):
            for row in rows:
                cols = list(row.keys())
                placeholders = ", ".join("?" for _ in cols)
                sql = (
                    f"INSERT OR REPLACE INTO source_document ({', '.join(cols)}) "
                    f"VALUES ({placeholders})"
                )
                self._conn.execute(sql, [row[c] for c in cols])

    def _insert_many(self, table: str, rows: list[dict], chunk: int = 2000) -> None:
        """Bulk insert: one multi-VALUES statement per chunk.

        Per-row execute costs ~1.4ms/row statement preparation with the real
        schema (5k+ rows -> tens of seconds); multi-VALUES drops that to a
        few seconds total.
        """
        if not rows:
            return
        cols = list(rows[0].keys())
        colsql = ", ".join(cols)
        for i in range(0, len(rows), chunk):
            part = rows[i : i + chunk]
            values = ", ".join(
                "(" + ", ".join(["?"] * len(cols)) + ")" for _ in part
            )
            params = [r[c] for r in part for c in cols]
            self._conn.execute(
                f"INSERT INTO {table} ({colsql}) VALUES {values}", params
            )

    def replace_raw_facts(self, source_document_id: str, rows: list[dict]) -> None:
        from equitylens.storage.writer import writer_for

        self.connect()
        with writer_for(self).transaction(self):
            self._conn.execute("DELETE FROM raw_fact WHERE source_document_id = ?", [source_document_id])
            self._insert_many("raw_fact", rows)

    def replace_canonical_facts(self, source_document_id: str, rows: list[dict]) -> None:
        from equitylens.storage.writer import writer_for

        self.connect()
        with writer_for(self).transaction(self):
            self._conn.execute(
                "DELETE FROM canonical_fact WHERE source_document_id = ?", [source_document_id]
            )
            self._insert_many("canonical_fact", rows)

    def replace_segment_facts(self, source_document_id: str, rows: list[dict]) -> None:
        from equitylens.storage.writer import writer_for

        self.connect()
        with writer_for(self).transaction(self):
            self._conn.execute(
                "DELETE FROM segment_fact WHERE source_document_id = ?", [source_document_id]
            )
            self._insert_many("segment_fact", rows)

    def replace_proxy(self, company_id: str, source_document_id: str,
                      exec_rows: list[dict], comp_rows: list[dict], board_rows: list[dict]) -> None:
        from equitylens.storage.writer import writer_for

        self.connect()
        with writer_for(self).transaction(self):
            self._conn.execute("DELETE FROM executive WHERE company_id = ?", [company_id])
            self._conn.execute("DELETE FROM executive_compensation WHERE company_id = ?", [company_id])
            self._conn.execute("DELETE FROM board_member WHERE company_id = ?", [company_id])
            self._insert_many("executive", exec_rows)
            self._insert_many("executive_compensation", comp_rows)
            self._insert_many("board_member", board_rows)

    def replace_insider_transactions(self, company_id: str, rows: list[dict]) -> None:
        from equitylens.storage.writer import writer_for

        self.connect()
        with writer_for(self).transaction(self):
            self._conn.execute("DELETE FROM insider_transaction WHERE company_id = ?", [company_id])
            self._insert_many("insider_transaction", rows)

    def insert_market_quote(self, row: dict) -> None:
        """Append one quote observation; identical observations are ignored."""
        self.connect()
        cols = list(row.keys())
        placeholders = ", ".join("?" for _ in cols)
        from equitylens.storage.writer import writer_for

        with writer_for(self).transaction(self):
            self._conn.execute(
                f"INSERT OR IGNORE INTO market_quote ({', '.join(cols)}) VALUES ({placeholders})",
                [row[c] for c in cols],
            )

    def latest_market_quote(
        self, company_id: str, security_id: str | None = None
    ) -> dict | None:
        return self.query_one(
            """SELECT * FROM market_quote WHERE company_id = ?
               AND (? IS NULL OR security_id = ? OR security_id IS NULL)
               ORDER BY (security_id IS NULL), fetched_at DESC, observed_at DESC LIMIT 1""",
            [company_id, security_id, security_id],
        )

    def upsert_promise(self, row: dict) -> None:
        """Replace (or insert) one management_promise by promise_id."""
        self.connect()
        cols = list(row.keys())
        placeholders = ", ".join("?" for _ in cols)
        from equitylens.storage.writer import writer_for

        with writer_for(self).transaction(self):
            self._conn.execute(
                f"INSERT OR REPLACE INTO management_promise ({', '.join(cols)}) VALUES ({placeholders})",
                [row[c] for c in cols],
            )

    def insert_ingestion_run(self, row: dict) -> None:
        from equitylens.storage.writer import writer_for

        self.connect()
        cols = list(row.keys())
        placeholders = ", ".join("?" for _ in cols)
        sql = f"INSERT INTO ingestion_run ({', '.join(cols)}) VALUES ({placeholders})"
        with writer_for(self).transaction(self):
            self._conn.execute(sql, [row[c] for c in cols])

    # ---------------- queries ----------------

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        self.connect()
        result = self._conn.execute(sql, params or []).fetchall()
        cols = [d[0] for d in self._conn.description]
        return [dict(zip(cols, row)) for row in result]

    def query_one(self, sql: str, params: list | None = None) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def json_col(self, value) -> str | None:
        return json.dumps(value, ensure_ascii=False) if value is not None else None
