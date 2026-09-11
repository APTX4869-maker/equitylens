"""Ordered, checksummed DuckDB schema migrations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import duckdb


class MigrationChecksumError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    signature: str
    apply: Callable[[duckdb.DuckDBPyConnection], None]

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.signature.encode()).hexdigest()


SEED_COMPANIES = (
    {
        "company_id": "0000320193",
        "ticker": "AAPL",
        "legal_name": "Apple Inc.",
        "exchange": "NASDAQ",
        "fiscal_year_end": "09-30",
    },
    {
        "company_id": "0000789019",
        "ticker": "MSFT",
        "legal_name": "Microsoft Corporation",
        "exchange": "NASDAQ",
        "fiscal_year_end": "06-30",
    },
)


def _seed_security_id(company_id: str, ticker: str, exchange: str) -> str:
    from equitylens.companies.registry import seed_security_id

    return seed_security_id(company_id, ticker, exchange)


def _identity_registry(conn: duckdb.DuckDBPyConnection) -> None:
    for statement in (
        "ALTER TABLE company ADD COLUMN IF NOT EXISTS reporting_template VARCHAR",
        "ALTER TABLE company ADD COLUMN IF NOT EXISTS active_publication_id VARCHAR",
        "ALTER TABLE company ADD COLUMN IF NOT EXISTS quality_status VARCHAR",
        "CREATE UNIQUE INDEX IF NOT EXISTS company_cik_unique ON company(cik)",
        """
        CREATE TABLE IF NOT EXISTS security (
          security_id VARCHAR PRIMARY KEY,
          company_id VARCHAR NOT NULL REFERENCES company(company_id),
          class_label VARCHAR,
          exchange VARCHAR NOT NULL,
          currency VARCHAR NOT NULL,
          instrument_type VARCHAR NOT NULL,
          status VARCHAR NOT NULL,
          identity_evidence_json JSON NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS security_ticker_alias (
          alias_id VARCHAR PRIMARY KEY,
          security_id VARCHAR NOT NULL REFERENCES security(security_id),
          ticker VARCHAR NOT NULL,
          exchange VARCHAR NOT NULL,
          valid_from DATE NOT NULL,
          valid_to DATE
        )
        """,
        "CREATE INDEX IF NOT EXISTS security_company_idx ON security(company_id)",
        "CREATE INDEX IF NOT EXISTS security_alias_lookup_idx ON security_ticker_alias(ticker, exchange)",
    ):
        conn.execute(statement)

    for company in SEED_COMPANIES:
        conn.execute(
            """
            INSERT INTO company (
              company_id, ticker, cik, legal_name, fiscal_year_end, exchange,
              reporting_template, quality_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'us_gaap_operating_v1',
                      'LEGACY_UNREVIEWED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (company_id) DO UPDATE SET
              cik = coalesce(company.cik, excluded.cik),
              legal_name = coalesce(company.legal_name, excluded.legal_name),
              fiscal_year_end = coalesce(company.fiscal_year_end, excluded.fiscal_year_end),
              exchange = coalesce(company.exchange, excluded.exchange),
              reporting_template = coalesce(company.reporting_template, excluded.reporting_template),
              quality_status = coalesce(company.quality_status, excluded.quality_status)
            """,
            [
                company["company_id"],
                company["ticker"],
                company["company_id"],
                company["legal_name"],
                company["fiscal_year_end"],
                company["exchange"],
            ],
        )
        security_id = _seed_security_id(
            company["company_id"], company["ticker"], company["exchange"]
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO security VALUES
              (?, ?, 'Common Stock', ?, 'USD', 'COMMON_STOCK', 'ACTIVE', ?)
            """,
            [
                security_id,
                company["company_id"],
                company["exchange"],
                json.dumps(
                    {
                        "source": "curated_legacy_seed",
                        "ticker": company["ticker"],
                        "review_status": "LEGACY_UNREVIEWED",
                    },
                    sort_keys=True,
                ),
            ],
        )
        alias_id = hashlib.sha256(
            f"{security_id}:{company['exchange']}:{company['ticker']}:1900-01-01".encode()
        ).hexdigest()
        conn.execute(
            """
            INSERT OR IGNORE INTO security_ticker_alias
              (alias_id, security_id, ticker, exchange, valid_from, valid_to)
            VALUES (?, ?, ?, ?, DATE '1900-01-01', NULL)
            """,
            [alias_id, security_id, company["ticker"], company["exchange"]],
        )


MIGRATIONS = (
    Migration(
        version=1,
        name="issuer_and_security_registry",
        signature="""
        company:+reporting_template,+active_publication_id,+quality_status,cik_unique;
        security:v1;security_ticker_alias:v1;seed:AAPL,MSFT:LEGACY_UNREVIEWED
        """.strip(),
        apply=_identity_registry,
    ),
)


def apply_migrations(conn: duckdb.DuckDBPyConnection) -> list[int]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migration (
          version INTEGER PRIMARY KEY,
          applied_at TIMESTAMP NOT NULL,
          checksum VARCHAR NOT NULL
        )
        """
    )
    applied = {
        int(version): checksum
        for version, checksum in conn.execute(
            "SELECT version, checksum FROM schema_migration"
        ).fetchall()
    }
    for migration in MIGRATIONS:
        stored = applied.get(migration.version)
        if stored is not None and stored != migration.checksum:
            raise MigrationChecksumError(
                f"migration {migration.version} checksum changed: {stored} != {migration.checksum}"
            )

    completed: list[int] = []
    for migration in MIGRATIONS:
        if migration.version in applied:
            continue
        conn.execute("BEGIN TRANSACTION")
        try:
            migration.apply(conn)
            conn.execute(
                "INSERT INTO schema_migration VALUES (?, ?, ?)",
                [
                    migration.version,
                    datetime.now(timezone.utc).replace(tzinfo=None),
                    migration.checksum,
                ],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        completed.append(migration.version)
    return completed
