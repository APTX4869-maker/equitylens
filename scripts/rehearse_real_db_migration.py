#!/usr/bin/env python3
"""Build and verify an offline migration candidate without touching the live DB."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from equitylens.ingestion.sec.management import sync_management
from equitylens.ingestion.sec.sync import sync_company, sync_segments
from equitylens.market.service import sync_quotes
from equitylens.storage.duckdb_store import DuckDBStore

TICKERS = ("AAPL", "MSFT")
MATERIAL_TABLES = (
    "raw_fact",
    "canonical_fact",
    "segment_fact",
    "executive",
    "executive_compensation",
    "board_member",
    "insider_transaction",
    "market_quote",
    "valuation_run",
    "valuation_plan",
    "management_promise",
)
SEMANTIC_EXCLUSIONS = {
    # A replay replaces the same effective facts and records when that
    # normalization happened. The timestamp is audit metadata, not identity.
    "canonical_fact": {"created_at"},
}
LEGACY_VALUATION_COLUMNS = (
    "valuation_run_id",
    "company_id",
    "model_name",
    "model_version",
    "run_at",
    "market_observation_id",
    "assumption_set_id",
    "fact_snapshot_json",
    "output_json",
    "warnings_json",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_digest(root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(_sha256_file(path).encode())
        digest.update(b"\n")
        count += 1
    return digest.hexdigest(), count


def _rows_digest(rows: list[tuple]) -> str:
    digest = hashlib.sha256()
    for row in sorted((json.dumps(r, default=str, ensure_ascii=False) for r in rows)):
        digest.update(row.encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _table_digest(conn: duckdb.DuckDBPyConnection, table: str) -> dict:
    all_columns = [row[1] for row in conn.execute(f"PRAGMA table_info('{table}')").fetchall()]
    columns = [c for c in all_columns if c not in SEMANTIC_EXCLUSIONS.get(table, set())]
    selected = ", ".join(f'"{column}"' for column in columns)
    rows = conn.execute(f'SELECT {selected} FROM "{table}"').fetchall()
    return {
        "rows": len(rows),
        "sha256": _rows_digest(rows),
        "columns": columns,
        "excluded_audit_columns": sorted(SEMANTIC_EXCLUSIONS.get(table, set())),
    }


def _summary(db_path: Path) -> dict:
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
        material = {
            table: _table_digest(conn, table)
            for table in MATERIAL_TABLES
            if table in tables
        }
        source_identity = conn.execute(
            """SELECT source_document_id, content_sha256, fetched_at, local_path
               FROM source_document ORDER BY source_document_id"""
        ).fetchall()
        return {
            "material_tables": material,
            "source_document_identity": hashlib.sha256(
                json.dumps(source_identity, default=str, ensure_ascii=False).encode()
            ).hexdigest(),
            "source_document_rows": len(source_identity),
            "ingestion_run_rows": conn.execute(
                "SELECT COUNT(*) FROM ingestion_run"
            ).fetchone()[0],
            "mapping_versions": conn.execute(
                """SELECT mapping_version, COUNT(*)
                   FROM canonical_fact GROUP BY 1 ORDER BY 1"""
            ).fetchall(),
            "boundary_counts": dict(conn.execute(
                """SELECT canonical_metric, COUNT(*)
                   FROM canonical_fact
                   WHERE canonical_metric IN (
                     'LONG_TERM_DEBT_CURRENT', 'SHORT_TERM_BORROWINGS',
                     'COMMERCIAL_PAPER', 'DEPRECIATION',
                     'AMORTIZATION_OF_INTANGIBLE_ASSETS',
                     'DEPRECIATION_AMORTIZATION'
                   ) GROUP BY 1 ORDER BY 1"""
            ).fetchall()),
            "pre_2010_wrong_fiscal_bucket": conn.execute(
                """SELECT COUNT(*) FROM canonical_fact
                   WHERE period_end < '2010-01-01' AND fiscal_year IN (2015, 2020)"""
            ).fetchone()[0],
            "calculated_missing_as_known_at": conn.execute(
                """SELECT COUNT(*) FROM canonical_fact
                   WHERE status = 'CALCULATED' AND as_known_at IS NULL"""
            ).fetchone()[0],
            "valuation_versions": conn.execute(
                "SELECT model_version, COUNT(*) FROM valuation_run GROUP BY 1 ORDER BY 1"
            ).fetchall(),
            "legacy_valuation_rows_sha256": _rows_digest(conn.execute(
                "SELECT " + ", ".join(LEGACY_VALUATION_COLUMNS) + " FROM valuation_run"
            ).fetchall()),
            "legacy_valuation_new_fields_populated": conn.execute(
                """SELECT COUNT(*) FROM valuation_run
                   WHERE input_fingerprint IS NOT NULL OR scenarios_json IS NOT NULL
                      OR sensitivity_json IS NOT NULL OR model_quality_json IS NOT NULL"""
            ).fetchone()[0]
            if "input_fingerprint" in {
                row[1] for row in conn.execute("PRAGMA table_info('valuation_run')").fetchall()
            }
            else 0,
        }
    finally:
        conn.close()


def _replay_once(db_path: Path, raw_dir: Path) -> dict:
    store = DuckDBStore(db_path).connect()
    reports: dict[str, dict] = {}
    try:
        store.init_schema()
        for ticker in TICKERS:
            company = sync_company(ticker, fetch=False, store=store, raw_dir=raw_dir)
            segments = sync_segments(ticker, fetch=False, store=store, raw_dir=raw_dir)
            management = sync_management(ticker, fetch=False, store=store, raw_dir=raw_dir)
            reports[ticker] = {
                "company": company.__dict__,
                "segments": segments.__dict__,
                "management": management.__dict__,
            }
        reports["quotes"] = {
            report.company: {"quotes": report.quotes, "warnings": report.warnings}
            for report in sync_quotes(list(TICKERS), fetch=False, store=store, raw_dir=raw_dir)
        }
    finally:
        store.close()
    return reports


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-db", type=Path, default=Path("data/equitylens.duckdb"))
    parser.add_argument("--source-raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = args.output_root or Path.home() / ".local/share/equitylens-migration-rehearsal" / stamp
    if root.exists():
        raise FileExistsError(f"refusing to overwrite rehearsal directory: {root}")
    root.mkdir(parents=True)

    backup_db = root / "source.duckdb"
    working_db = root / "candidate.duckdb"
    copied_raw = root / "raw"
    shutil.copy2(args.source_db, backup_db)
    shutil.copy2(args.source_db, working_db)
    shutil.copytree(args.source_raw, copied_raw, copy_function=shutil.copy2)

    source_db_sha = _sha256_file(args.source_db)
    backup_db_sha = _sha256_file(backup_db)
    source_raw_sha, source_raw_files = _tree_digest(args.source_raw)
    copied_raw_sha, copied_raw_files = _tree_digest(copied_raw)
    if source_db_sha != backup_db_sha or (source_raw_sha, source_raw_files) != (
        copied_raw_sha,
        copied_raw_files,
    ):
        raise RuntimeError("backup verification failed")

    baseline = _summary(backup_db)
    first_reports = _replay_once(working_db, copied_raw)
    first = _summary(working_db)
    second_reports = _replay_once(working_db, copied_raw)
    second = _summary(working_db)
    idempotent = first["material_tables"] == second["material_tables"]
    source_idempotent = (
        first["source_document_identity"] == second["source_document_identity"]
        and first["source_document_rows"] == second["source_document_rows"]
    )

    result = {
        "created_at": stamp,
        "source": {"db": str(args.source_db.resolve()), "raw": str(args.source_raw.resolve())},
        "rehearsal_root": str(root.resolve()),
        "backup": {
            "db": str(backup_db.resolve()),
            "db_sha256": backup_db_sha,
            "raw": str(copied_raw.resolve()),
            "raw_tree_sha256": copied_raw_sha,
            "raw_file_count": copied_raw_files,
            "verified": True,
        },
        "candidate_db": str(working_db.resolve()),
        "baseline": baseline,
        "first_replay": {"reports": first_reports, "summary": first},
        "second_replay": {"reports": second_reports, "summary": second},
        "checks": {
            "material_tables_idempotent": idempotent,
            "source_document_identities_idempotent": source_idempotent,
            "legacy_valuation_runs_preserved": (
                baseline["legacy_valuation_rows_sha256"]
                == first["legacy_valuation_rows_sha256"]
                and first["legacy_valuation_new_fields_populated"] == 0
            ),
            "raw_backup_matches_source": True,
            "db_backup_matches_source": True,
        },
    }
    report_path = root / "report.json"
    report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n")
    print(json.dumps({"report": str(report_path), "checks": result["checks"]}, indent=2))
    return 0 if all(result["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
