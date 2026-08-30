"""Shared pytest fixtures: normalize saved SEC fixtures into a temp DuckDB."""

from __future__ import annotations

from pathlib import Path

import pytest

from equitylens.ingestion.sec.sync import sync_company
from equitylens.storage.duckdb_store import DuckDBStore

FIXTURE_ROOT = Path(__file__).parent / "fixtures"

SUPPORTED_TICKERS = ["AAPL", "MSFT"]


@pytest.fixture()
def db(tmp_path) -> DuckDBStore:
    store = DuckDBStore(tmp_path / "test.duckdb")
    store.connect()
    store.init_schema()
    yield store
    store.close()


@pytest.fixture(scope="session")
def company_db(tmp_path_factory) -> DuckDBStore:
    """AAPL + MSFT normalized ONCE from the saved official SEC fixtures."""
    store = DuckDBStore(tmp_path_factory.mktemp("golden") / "test.duckdb")
    store.connect()
    store.init_schema()
    for ticker in SUPPORTED_TICKERS:
        sync_company(ticker, fetch=False, store=store, raw_dir=FIXTURE_ROOT)
    yield store
    store.close()


def latest_annual(store: DuckDBStore, cik: str, metric: str, fy: int) -> float:
    rows = store.query(
        """SELECT value, as_known_at FROM canonical_fact
           WHERE company_id=? AND canonical_metric=? AND fiscal_year=? AND period_type='FY'""",
        [cik, metric, fy],
    )
    assert rows, f"no FY{fy} {metric} facts"
    best = max(rows, key=lambda r: str(r["as_known_at"] or ""))
    return float(best["value"])


def standalone(store: DuckDBStore, cik: str, metric: str, fy: int) -> dict[int, float]:
    rows = store.query(
        """SELECT fiscal_quarter, value FROM canonical_fact
           WHERE company_id=? AND canonical_metric=? AND fiscal_year=?
             AND period_type='Q_STANDALONE'""",
        [cik, metric, fy],
    )
    return {int(r["fiscal_quarter"]): float(r["value"]) for r in rows}
