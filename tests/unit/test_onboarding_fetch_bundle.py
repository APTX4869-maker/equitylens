from __future__ import annotations

from datetime import datetime, timezone

import pytest

from equitylens.onboarding.fetch_bundle import (
    FetchBundleCorrupted,
    FetchBundleIncomplete,
    collect_submission_rows,
    load_bundle_document,
    select_required_filings,
)
from equitylens.onboarding.models import FetchDocument


def _row(form: str, report: str, filed: str, accession: str) -> dict:
    return {
        "form": form,
        "reportDate": report,
        "filingDate": filed,
        "accessionNumber": accession,
        "primaryDocument": f"{accession}.htm",
    }


def test_selects_quality_window_and_applicable_amendments_deterministically():
    rows = [
        *[
            _row("10-K", f"{year}-01-31", f"{year}-03-01", f"k-{year}")
            for year in range(2022, 2026)
        ],
        *[
            _row("10-Q", f"202{year // 4}-{(year % 4 + 1) * 2:02d}-28", f"202{year // 4}-09-01", f"q-{year}")
            for year in range(1, 10)
        ],
        _row("10-Q/A", "2022-04-28", "2022-09-15", "q-9-a"),
        _row("10-K", "2026-01-31", "2026-03-01", "future"),
    ]

    selected = select_required_filings(
        list(reversed(rows)), as_of=datetime(2025, 12, 31, tzinfo=timezone.utc)
    )

    assert len({item.report_date for item in selected if item.base_form == "10-K"}) == 3
    assert len({item.report_date for item in selected if item.base_form == "10-Q"}) == 8
    assert "future" not in {item.accession_number for item in selected}
    assert "q-9-a" in {item.accession_number for item in selected}
    assert selected == sorted(
        selected, key=lambda item: (item.report_date, item.filing_date, item.accession_number)
    )


def test_rejects_missing_primary_document_in_required_window():
    rows = [_row("10-K", f"202{year}-01-31", f"202{year}-03-01", f"k-{year}") for year in range(3, 6)]
    rows += [_row("10-Q", f"2025-{month:02d}-01", f"2025-{month:02d}-15", f"q-{month}") for month in range(1, 9)]
    rows[-1]["primaryDocument"] = ""

    with pytest.raises(FetchBundleIncomplete, match="primaryDocument"):
        select_required_filings(rows, as_of=datetime(2025, 12, 31, tzinfo=timezone.utc))


def test_collects_recent_and_every_declared_history_file():
    submissions = {
        "filings": {
            "recent": {
                "form": ["10-K"],
                "reportDate": ["2025-01-31"],
                "filingDate": ["2025-03-01"],
                "accessionNumber": ["recent"],
                "primaryDocument": ["recent.htm"],
            },
            "files": [{"name": "old.json"}],
        }
    }
    history = {
        "old.json": {
            "form": ["10-Q"],
            "reportDate": ["2024-10-31"],
            "filingDate": ["2024-12-01"],
            "accessionNumber": ["old"],
            "primaryDocument": ["old.htm"],
        }
    }

    assert [row["accessionNumber"] for row in collect_submission_rows(submissions, history)] == [
        "recent",
        "old",
    ]

    with pytest.raises(FetchBundleIncomplete, match="old.json"):
        collect_submission_rows(submissions, {})


def test_bundle_document_loader_rejects_hash_mismatch(tmp_path):
    path = tmp_path / "sec" / "doc.html"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"tampered")
    document = FetchDocument(
        document_id="filing:one",
        document_type="FILING_DOCUMENT",
        accession_number="one",
        form_type="10-K",
        filed_at="2025-03-01",
        report_date="2025-01-31",
        fetched_at="2025-03-01T00:00:00Z",
        source_url="https://www.sec.gov/example",
        content_sha256="a" * 64,
        raw_locator="sec/doc.html",
    )

    with pytest.raises(FetchBundleCorrupted, match="filing:one"):
        load_bundle_document(tmp_path, document)
