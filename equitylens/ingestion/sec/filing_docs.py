"""Filing document fetching (10-K / 10-Q primary documents) for segment parsing.

Segment facts are NOT in companyfacts (entity-wide only); they live in the
filing's inline XBRL. We fetch the primary document HTML, snapshot it into the
raw store, and extract segment facts from it.
"""

from __future__ import annotations

import json
from pathlib import Path

from equitylens.config import PARSER_VERSION, RAW_DIR, SEC_ARCHIVES_URL
from equitylens.domain.companies import get_company
from equitylens.domain.filings import SourceDocument
from equitylens.ingestion.sec.client import SECClient
from equitylens.storage.duckdb_store import DuckDBStore
from equitylens.storage.raw_store import load_snapshot, load_snapshot_record, save_snapshot

FORMS_SUPPORTED = ("10-K", "10-Q")


def _recent_filings(submissions: dict) -> list[dict]:
    recent = submissions.get("filings", {}).get("recent") or []
    return submission_rows(recent)


def submission_rows(value: dict | list) -> list[dict]:
    """Normalize SEC's columnar recent/history filing payloads."""
    if isinstance(value, list):
        return [dict(item) for item in value]
    if isinstance(value, dict):
        keys = list(value.keys())
        columns = [value[key] for key in keys]
        if not columns:
            return []
        return [dict(zip(keys, row)) for row in zip(*columns)]
    return []


def list_filing_docs(ticker: str, forms: tuple[str, ...] = FORMS_SUPPORTED,
                     limit_per_form: int = 3, *, raw_dir=RAW_DIR,
                     store: DuckDBStore | None = None) -> list[dict]:
    """Pick recent filing metadata (no download), from the LATEST cached
    submissions snapshot (via the raw-store manifest, never a fixed filename)."""
    company = get_company(ticker, store=store)
    directory = raw_dir / "sec" / company.cik
    cached = load_snapshot(directory, "submissions.json")
    if cached is None:
        raise FileNotFoundError(f"No cached submissions snapshot for {ticker}")
    submissions = json.loads(cached[0])
    picked: list[dict] = []
    counts: dict[str, int] = {}
    for row in _recent_filings(submissions):
        form = row.get("form")
        if form not in forms or not row.get("primaryDocument"):
            continue
        if counts.get(form, 0) >= limit_per_form:
            continue
        counts[form] = counts.get(form, 0) + 1
        picked.append(row)
    return picked


def fetch_filing_documents(
    ticker: str,
    forms: tuple[str, ...] = FORMS_SUPPORTED,
    limit_per_form: int = 3,
    *,
    fetch: bool = True,
    store: DuckDBStore | None = None,
    client: SECClient | None = None,
    raw_dir=RAW_DIR,
) -> list[SourceDocument]:
    store = store or DuckDBStore()
    store.connect()
    store.init_schema()
    company = get_company(ticker, store=store)
    cik = company.cik

    cik_int = str(int(cik))
    docs: list[SourceDocument] = []
    own_client = client or SECClient()
    try:
        for row in list_filing_docs(
            ticker, forms, limit_per_form, raw_dir=raw_dir, store=store
        ):
            accn = row["accessionNumber"]
            accn_nodash = accn.replace("-", "")
            doc_name = "primary.html"
            directory = raw_dir / "sec" / cik / "filing_docs" / accn
            url = f"{SEC_ARCHIVES_URL}{cik_int}/{accn_nodash}/{row['primaryDocument']}"

            if fetch:
                _, content, meta = own_client.get(url)
                path, sha = save_snapshot(
                    directory, doc_name, content,
                    metadata={"fetched_at": meta.get("fetched_at") or ""},
                )
            else:
                record = load_snapshot_record(directory, doc_name)
                if record is None:
                    continue
                content, sha, path = record.content, record.sha256, record.path
                meta = {"fetched_at": record.fetched_at}

            doc = SourceDocument(
                provider="SEC",
                document_type="FILING_DOCUMENT",
                form_type=row["form"],
                accession_number=accn,
                published_at=row.get("reportDate"),
                filed_at=row.get("filingDate"),
                source_url=url,
                content_sha256=sha,
                local_path=str(path),
                fetched_at=meta.get("fetched_at") or "",
                parser_version=PARSER_VERSION,
                metadata_json={"primary_document": row.get("primaryDocument"),
                               "report_date": row.get("reportDate")},
                company_id=cik,
            )
            docs.append(doc)
    finally:
        if client is None:
            own_client.close()
    store.upsert_source_documents([d.to_row() for d in docs])
    return docs
