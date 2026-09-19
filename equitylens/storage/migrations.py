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


def _canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: item.isoformat() if hasattr(item, "isoformat") else str(item),
        allow_nan=False,
    )


def _json_hash(value) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _insert_dataset_rows(
    conn: duckdb.DuckDBPyConnection,
    rows: list[tuple[str, str, str, str, str]],
    *,
    chunk_size: int = 1000,
) -> None:
    for offset in range(0, len(rows), chunk_size):
        part = rows[offset : offset + chunk_size]
        values = ",".join("(?,?,?,?,?)" for _ in part)
        params = [value for row in part for value in row]
        conn.execute(
            f"INSERT OR IGNORE INTO dataset_row VALUES {values}", params
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


def _immutable_publications(conn: duckdb.DuckDBPyConnection) -> None:
    for statement in (
        """
        CREATE TABLE IF NOT EXISTS issuer_profile_version (
          profile_id VARCHAR PRIMARY KEY,
          company_id VARCHAR NOT NULL REFERENCES company(company_id),
          version INTEGER NOT NULL,
          schema_version INTEGER NOT NULL,
          content_json JSON NOT NULL,
          content_sha256 VARCHAR NOT NULL,
          created_at TIMESTAMP NOT NULL,
          UNIQUE(company_id, version)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS dataset_version (
          dataset_id VARCHAR PRIMARY KEY,
          company_id VARCHAR NOT NULL REFERENCES company(company_id),
          profile_id VARCHAR NOT NULL REFERENCES issuer_profile_version(profile_id),
          source_manifest_json JSON NOT NULL,
          parser_version VARCHAR NOT NULL,
          rule_version VARCHAR NOT NULL,
          dataset_hash VARCHAR NOT NULL,
          state VARCHAR NOT NULL,
          created_at TIMESTAMP NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS dataset_row (
          dataset_id VARCHAR NOT NULL REFERENCES dataset_version(dataset_id),
          entity_type VARCHAR NOT NULL,
          row_id VARCHAR NOT NULL,
          payload_json JSON NOT NULL,
          payload_sha256 VARCHAR NOT NULL,
          PRIMARY KEY(dataset_id, entity_type, row_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS quality_report (
          report_id VARCHAR PRIMARY KEY,
          dataset_id VARCHAR NOT NULL REFERENCES dataset_version(dataset_id),
          rule_version VARCHAR NOT NULL,
          result VARCHAR NOT NULL,
          fingerprint VARCHAR NOT NULL,
          created_at TIMESTAMP NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS company_quality_check (
          report_id VARCHAR NOT NULL REFERENCES quality_report(report_id),
          check_id VARCHAR NOT NULL,
          scope_key VARCHAR NOT NULL,
          status VARCHAR NOT NULL,
          severity VARCHAR NOT NULL,
          actual_json JSON,
          expected_json JSON,
          tolerance_json JSON,
          evidence_json JSON,
          reason VARCHAR,
          PRIMARY KEY(report_id, check_id, scope_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS adaptation_review (
          review_id VARCHAR PRIMARY KEY,
          company_id VARCHAR NOT NULL REFERENCES company(company_id),
          fingerprint VARCHAR NOT NULL,
          reviewer VARCHAR NOT NULL,
          decision VARCHAR NOT NULL,
          note VARCHAR,
          created_at TIMESTAMP NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS publication (
          publication_id VARCHAR PRIMARY KEY,
          company_id VARCHAR NOT NULL REFERENCES company(company_id),
          dataset_id VARCHAR NOT NULL REFERENCES dataset_version(dataset_id),
          profile_id VARCHAR NOT NULL REFERENCES issuer_profile_version(profile_id),
          quality_report_id VARCHAR,
          review_id VARCHAR,
          fingerprint VARCHAR NOT NULL,
          published_at TIMESTAMP NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS company_capability (
          publication_id VARCHAR NOT NULL REFERENCES publication(publication_id),
          module VARCHAR NOT NULL,
          status VARCHAR NOT NULL,
          reason VARCHAR,
          coverage_json JSON,
          PRIMARY KEY(publication_id, module)
        )
        """,
        "CREATE INDEX IF NOT EXISTS dataset_company_idx ON dataset_version(company_id)",
        "CREATE INDEX IF NOT EXISTS publication_company_idx ON publication(company_id, published_at)",
    ):
        conn.execute(statement)

    existing_tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    entity_tables = (
        ("source_document", "source_document_id"),
        ("canonical_fact", "canonical_fact_id"),
        ("metric_value", "metric_value_id"),
        ("segment_fact", "segment_fact_id"),
    )
    for company in SEED_COMPANIES:
        company_id = company["company_id"]
        profile_id = f"legacy-profile-{company_id}-v1"
        profile_content = {
            "schema_version": 1,
            "company_id": company_id,
            "version": 1,
            "template": "us_gaap_operating_v1",
            "legacy_status": "LEGACY_UNREVIEWED",
        }
        conn.execute(
            """
            INSERT OR IGNORE INTO issuer_profile_version
            VALUES (?, ?, 1, 1, ?, ?, CURRENT_TIMESTAMP)
            """,
            [profile_id, company_id, _canonical_json(profile_content), _json_hash(profile_content)],
        )
        dataset_id = f"legacy-dataset-{company_id}-v1"
        manifest_rows = []
        if "source_document" in existing_tables:
            manifest_rows = conn.execute(
                """
                SELECT source_document_id, content_sha256, fetched_at
                FROM source_document WHERE company_id = ? ORDER BY source_document_id
                """,
                [company_id],
            ).fetchall()
        manifest = {
            "legacy": True,
            "documents": [
                {"source_document_id": row[0], "content_sha256": row[1], "fetched_at": row[2]}
                for row in manifest_rows
            ],
        }
        conn.execute(
            """
            INSERT OR IGNORE INTO dataset_version VALUES
              (?, ?, ?, ?, 'legacy', 'legacy_unreviewed', '', 'SEALED', CURRENT_TIMESTAMP)
            """,
            [dataset_id, company_id, profile_id, _canonical_json(manifest)],
        )
        row_hashes = []
        dataset_rows: list[tuple[str, str, str, str, str]] = []
        for entity_type, id_column in entity_tables:
            if entity_type not in existing_tables:
                continue
            cursor = conn.execute(
                f"SELECT * FROM {entity_type} WHERE company_id = ? ORDER BY {id_column}",
                [company_id],
            )
            columns = [item[0] for item in cursor.description]
            for values in cursor.fetchall():
                payload = dict(zip(columns, values))
                row_id = str(payload[id_column])
                payload_json = _canonical_json(payload)
                payload_sha = hashlib.sha256(payload_json.encode()).hexdigest()
                dataset_rows.append(
                    (dataset_id, entity_type, row_id, payload_json, payload_sha)
                )
                row_hashes.append(f"{entity_type}:{row_id}:{payload_sha}")
        if "raw_fact" in existing_tables and "source_document" in existing_tables:
            cursor = conn.execute(
                """
                SELECT r.* FROM raw_fact r
                JOIN source_document d ON d.source_document_id = r.source_document_id
                WHERE d.company_id = ? ORDER BY r.raw_fact_id
                """,
                [company_id],
            )
            columns = [item[0] for item in cursor.description]
            for values in cursor.fetchall():
                payload = dict(zip(columns, values))
                row_id = str(payload["raw_fact_id"])
                payload_json = _canonical_json(payload)
                payload_sha = hashlib.sha256(payload_json.encode()).hexdigest()
                dataset_rows.append(
                    (dataset_id, "raw_fact", row_id, payload_json, payload_sha)
                )
                row_hashes.append(f"raw_fact:{row_id}:{payload_sha}")
        _insert_dataset_rows(conn, dataset_rows)
        dataset_hash = hashlib.sha256("\n".join(sorted(row_hashes)).encode()).hexdigest()
        conn.execute(
            "UPDATE dataset_version SET dataset_hash = ? WHERE dataset_id = ?",
            [dataset_hash, dataset_id],
        )
        security_hashes = []
        for row in conn.execute(
            """
            SELECT security_id, exchange, currency, instrument_type, identity_evidence_json
            FROM security WHERE company_id = ? ORDER BY security_id
            """,
            [company_id],
        ).fetchall():
            evidence = json.loads(row[4]) if isinstance(row[4], str) else row[4]
            security_hashes.append(
                _json_hash(
                    {
                        "security_id": row[0],
                        "exchange": row[1],
                        "currency": row[2],
                        "instrument_type": row[3],
                        "identity_evidence": evidence,
                    }
                )
            )
        fingerprint = _json_hash(
            {
                "dataset_hash": dataset_hash,
                "profile_hash": _json_hash(profile_content),
                "rule_version": "legacy_unreviewed",
                "parser_version": "legacy",
                "quality_report_hash": None,
                "security_identity_hashes": security_hashes,
            }
        )
        publication_id = f"legacy-publication-{company_id}-v1"
        conn.execute(
            """
            INSERT OR IGNORE INTO publication VALUES
              (?, ?, ?, ?, NULL, NULL, ?, CURRENT_TIMESTAMP)
            """,
            [publication_id, company_id, dataset_id, profile_id, fingerprint],
        )
        conn.execute(
            "UPDATE company SET active_publication_id = ? WHERE company_id = ?",
            [publication_id, company_id],
        )


def _persistent_onboarding(conn: duckdb.DuckDBPyConnection) -> None:
    for statement in (
        """
        CREATE TABLE IF NOT EXISTS company_onboarding (
          onboarding_id VARCHAR PRIMARY KEY,
          company_id VARCHAR NOT NULL REFERENCES company(company_id),
          state VARCHAR NOT NULL,
          current_step VARCHAR,
          revision INTEGER NOT NULL,
          cancel_requested BOOLEAN NOT NULL,
          input_fingerprint VARCHAR NOT NULL,
          error_json JSON,
          next_attempt_at TIMESTAMP,
          created_at TIMESTAMP NOT NULL,
          updated_at TIMESTAMP NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS onboarding_security (
          onboarding_id VARCHAR NOT NULL,
          security_id VARCHAR NOT NULL REFERENCES security(security_id),
          PRIMARY KEY(onboarding_id, security_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS onboarding_step_attempt (
          attempt_id VARCHAR PRIMARY KEY,
          onboarding_id VARCHAR NOT NULL,
          step VARCHAR NOT NULL,
          attempt_no INTEGER NOT NULL,
          input_hash VARCHAR NOT NULL,
          output_hash VARCHAR,
          state VARCHAR NOT NULL,
          started_at TIMESTAMP NOT NULL,
          finished_at TIMESTAMP,
          heartbeat_at TIMESTAMP,
          error_json JSON,
          UNIQUE(onboarding_id, step, attempt_no)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS api_idempotency (
          key VARCHAR PRIMARY KEY,
          request_hash VARCHAR NOT NULL,
          response_json JSON NOT NULL,
          created_at TIMESTAMP NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS onboarding_company_idx ON company_onboarding(company_id, state)",
        "CREATE INDEX IF NOT EXISTS onboarding_runnable_idx ON company_onboarding(state, next_attempt_at)",
    ):
        conn.execute(statement)


def _discovery_cache(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS company_discovery (
          discovery_id VARCHAR PRIMARY KEY,
          ticker VARCHAR NOT NULL,
          identity_hash VARCHAR NOT NULL,
          payload_json JSON NOT NULL,
          expires_at TIMESTAMP NOT NULL,
          created_at TIMESTAMP NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS discovery_ticker_idx ON company_discovery(ticker, expires_at)"
    )


def _onboarding_artifacts(conn: duckdb.DuckDBPyConnection) -> None:
    for column in (
        "discovery_id VARCHAR",
        "profile_id VARCHAR",
        "dataset_id VARCHAR",
        "quality_report_id VARCHAR",
        "review_id VARCHAR",
        "publication_id VARCHAR",
    ):
        conn.execute(f"ALTER TABLE company_onboarding ADD COLUMN IF NOT EXISTS {column}")


def _valuation_identity(conn: duckdb.DuckDBPyConnection) -> None:
    additions = {
        "market_quote": ("security_id VARCHAR",),
        "valuation_assumption_set": (
            "security_id VARCHAR",
            "publication_id VARCHAR",
            "model_version VARCHAR",
            "assumptions_hash VARCHAR",
            "confirmation_fingerprint VARCHAR",
            "status VARCHAR",
            "confirmed_at TIMESTAMP",
        ),
        "valuation_run": (
            "security_id VARCHAR",
            "publication_id VARCHAR",
            "confirmation_fingerprint VARCHAR",
        ),
        "valuation_plan": (
            "security_id VARCHAR",
            "publication_id VARCHAR",
        ),
    }
    for table, columns in additions.items():
        for column in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column}")


def _onboarding_closure_artifacts(conn: duckdb.DuckDBPyConnection) -> None:
    for column in ("fetch_bundle_id VARCHAR", "profile_candidate_id VARCHAR"):
        conn.execute(f"ALTER TABLE company_onboarding ADD COLUMN IF NOT EXISTS {column}")
    for statement in (
        """
        CREATE TABLE IF NOT EXISTS onboarding_fetch_bundle (
          fetch_bundle_id VARCHAR PRIMARY KEY,
          onboarding_id VARCHAR NOT NULL,
          fetcher_version VARCHAR NOT NULL,
          parser_version VARCHAR NOT NULL,
          content_sha256 VARCHAR NOT NULL,
          created_at TIMESTAMP NOT NULL,
          UNIQUE(onboarding_id, content_sha256)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS onboarding_fetch_document (
          fetch_bundle_id VARCHAR NOT NULL,
          document_id VARCHAR NOT NULL,
          document_type VARCHAR NOT NULL,
          accession_number VARCHAR,
          form_type VARCHAR,
          filed_at DATE,
          report_date DATE,
          fetched_at TIMESTAMP NOT NULL,
          source_url VARCHAR NOT NULL,
          content_sha256 VARCHAR NOT NULL,
          raw_locator VARCHAR NOT NULL,
          PRIMARY KEY(fetch_bundle_id, document_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS issuer_profile_candidate (
          profile_candidate_id VARCHAR PRIMARY KEY,
          onboarding_id VARCHAR NOT NULL,
          task_revision INTEGER NOT NULL,
          company_id VARCHAR NOT NULL,
          fetch_bundle_id VARCHAR NOT NULL,
          input_sha256 VARCHAR NOT NULL,
          generator_version VARCHAR NOT NULL,
          mapping_version VARCHAR NOT NULL,
          mapping_sha256 VARCHAR NOT NULL,
          snapshot_manifest_json JSON NOT NULL,
          profile_json JSON NOT NULL,
          unresolved_json JSON NOT NULL,
          yaml_text VARCHAR NOT NULL,
          content_sha256 VARCHAR NOT NULL,
          yaml_sha256 VARCHAR NOT NULL,
          created_at TIMESTAMP NOT NULL,
          UNIQUE(onboarding_id, input_sha256)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS onboarding_event (
          event_id VARCHAR PRIMARY KEY,
          onboarding_id VARCHAR NOT NULL,
          event_type VARCHAR NOT NULL,
          actor_type VARCHAR NOT NULL,
          task_revision INTEGER NOT NULL,
          payload_json JSON NOT NULL,
          created_at TIMESTAMP NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS profile_import_idempotency (
          onboarding_id VARCHAR NOT NULL,
          idempotency_key VARCHAR NOT NULL,
          request_sha256 VARCHAR NOT NULL,
          response_json JSON NOT NULL,
          created_at TIMESTAMP NOT NULL,
          PRIMARY KEY(onboarding_id, idempotency_key)
        )
        """,
        "CREATE INDEX IF NOT EXISTS fetch_bundle_task_idx ON onboarding_fetch_bundle(onboarding_id, created_at)",
        "CREATE INDEX IF NOT EXISTS onboarding_event_task_idx ON onboarding_event(onboarding_id, created_at)",
    ):
        conn.execute(statement)


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
    Migration(
        version=2,
        name="immutable_publications",
        signature="""
        issuer_profile_version:v1;dataset_version:v1;dataset_row:v1;
        publication:v1;quality_report:v1;company_quality_check:v1;
        adaptation_review:v1;company_capability:v1;legacy-publications:AAPL,MSFT
        """.strip(),
        apply=lambda conn: _immutable_publications(conn),
    ),
    Migration(
        version=3,
        name="persistent_onboarding_jobs",
        signature="""
        company_onboarding:v1;onboarding_security:v1;
        onboarding_step_attempt:v1;api_idempotency:v1
        """.strip(),
        apply=lambda conn: _persistent_onboarding(conn),
    ),
    Migration(
        version=4,
        name="company_discovery_cache",
        signature="company_discovery:v1:15-minute-identity-cache",
        apply=lambda conn: _discovery_cache(conn),
    ),
    Migration(
        version=5,
        name="onboarding_artifact_pointers",
        signature="company_onboarding:+discovery,+profile,+dataset,+quality_report,+review,+publication",
        apply=lambda conn: _onboarding_artifacts(conn),
    ),
    Migration(
        version=6,
        name="valuation_security_publication_identity",
        signature="market_quote:+security;valuation_confirmation:v1;valuation_run:+identity;valuation_plan:+identity",
        apply=lambda conn: _valuation_identity(conn),
    ),
    Migration(
        version=7,
        name="onboarding_closure_artifacts",
        signature="onboarding:+fetch_bundle,+profile_candidate;fetch_document:v1;profile_candidate:v1;onboarding_event:v1;profile_import_idempotency:v1",
        apply=lambda conn: _onboarding_closure_artifacts(conn),
    ),
)


def apply_migrations(
    conn: duckdb.DuckDBPyConnection, *, target_version: int | None = None
) -> list[int]:
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
    selected = tuple(
        migration
        for migration in MIGRATIONS
        if target_version is None or migration.version <= target_version
    )
    for migration in selected:
        stored = applied.get(migration.version)
        if stored is not None and stored != migration.checksum:
            raise MigrationChecksumError(
                f"migration {migration.version} checksum changed: {stored} != {migration.checksum}"
            )

    completed: list[int] = []
    for migration in selected:
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
