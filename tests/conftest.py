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


def _seed_segments(store: DuckDBStore, ticker: str) -> None:
    """Seed segment facts from the reduced fixture filing documents (M4)."""
    import json as _json

    from equitylens.domain.companies import get_company
    from equitylens.domain.filings import SourceDocument
    from equitylens.normalization.fiscal_periods import FiscalCalendar
    from equitylens.normalization.ixbrl import IxbrlDocument
    from equitylens.normalization.segments import SegmentConfigRegistry, extract_segments

    company = get_company(ticker)
    cik = company.cik
    subs = _json.loads((FIXTURE_ROOT / "sec" / cik / "submissions.json").read_text())
    calendar = FiscalCalendar.from_submissions(subs, fallback_mm_dd=company.fiscal_year_end)
    config = SegmentConfigRegistry().get(ticker)
    docs_dir = FIXTURE_ROOT / "sec" / cik / "filing_docs"
    if not docs_dir.exists():
        return
    known_forms = {
        "AAPL": {"0000320193-25-000079": "10-K", "0000320193-26-000020": "10-Q"},
        "MSFT": {"0001193125-26-323660": "10-K", "0001193125-26-191507": "10-Q"},
    }
    for accn_dir in sorted(docs_dir.iterdir()):
        primary = accn_dir / "primary.html"
        if not primary.exists():
            continue
        accn = accn_dir.name
        from equitylens.storage.raw_store import sha256_bytes

        doc = SourceDocument(
            provider="SEC", document_type="FILING_DOCUMENT",
            form_type=known_forms[ticker].get(accn, "10-K"),
            accession_number=accn, source_url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn}/primary.html",
            content_sha256=sha256_bytes(primary.read_bytes()),
            local_path=str(primary), fetched_at="2026-01-01T00:00:00",
            parser_version="fixture", company_id=cik,
        )
        store.upsert_source_documents([doc.to_row()])
        ixbrl = IxbrlDocument.parse(primary.read_bytes())
        rows, _ = extract_segments(ticker, ixbrl, config, calendar, doc.source_document_id)
        for r in rows:
            r["company_id"] = cik
        store.replace_segment_facts(doc.source_document_id, rows)


@pytest.fixture(scope="session")
def company_db(tmp_path_factory) -> DuckDBStore:
    """AAPL + MSFT normalized ONCE from the saved official SEC fixtures."""
    store = DuckDBStore(tmp_path_factory.mktemp("golden") / "test.duckdb")
    store.connect()
    store.init_schema()
    for ticker in SUPPORTED_TICKERS:
        sync_company(ticker, fetch=False, store=store, raw_dir=FIXTURE_ROOT)
        _seed_segments(store, ticker)
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
