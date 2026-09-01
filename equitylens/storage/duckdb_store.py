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
from pathlib import Path

import duckdb

from equitylens.config import DB_PATH, SPEC_DIR

EXTRA_SCHEMA = """
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
"""


class DuckDBStore:
    def __init__(self, path: Path | str = DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection | None = None

    def connect(self) -> "DuckDBStore":
        if self._conn is None:
            self._conn = duckdb.connect(str(self.path))
        return self

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def init_schema(self) -> None:
        self.connect()
        schema = (SPEC_DIR / "schema.sql").read_text()
        for statement in self._split_statements(schema):
            self._conn.execute(statement)
        for statement in self._split_statements(EXTRA_SCHEMA):
            self._conn.execute(statement)

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
        self.connect()
        self._conn.execute("DELETE FROM raw_fact WHERE source_document_id = ?", [source_document_id])
        self._insert_many("raw_fact", rows)

    def replace_canonical_facts(self, source_document_id: str, rows: list[dict]) -> None:
        self.connect()
        self._conn.execute(
            "DELETE FROM canonical_fact WHERE source_document_id = ?", [source_document_id]
        )
        self._insert_many("canonical_fact", rows)

    def replace_segment_facts(self, source_document_id: str, rows: list[dict]) -> None:
        self.connect()
        self._conn.execute(
            "DELETE FROM segment_fact WHERE source_document_id = ?", [source_document_id]
        )
        self._insert_many("segment_fact", rows)

    def insert_ingestion_run(self, row: dict) -> None:
        self.connect()
        cols = list(row.keys())
        placeholders = ", ".join("?" for _ in cols)
        sql = f"INSERT INTO ingestion_run ({', '.join(cols)}) VALUES ({placeholders})"
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
