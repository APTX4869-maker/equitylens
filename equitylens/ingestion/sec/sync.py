"""SEC ingestion orchestrator: fetch -> snapshot -> persist -> normalize."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from equitylens.domain.companies import get_company
from datetime import datetime, timezone

from equitylens.config import (
    PARSER_VERSION,
    RAW_DIR,
    SEC_COMPANYFACTS_URL,
    SEC_SUBMISSIONS_URL,
)
from equitylens.domain.filings import SourceDocument
from equitylens.ingestion.sec.client import SECClient
from equitylens.normalization.fiscal_periods import FiscalCalendar
from equitylens.normalization.normalize import normalize_companyfacts
from equitylens.normalization.taxonomy.mappings import MappingRegistry
from equitylens.storage.duckdb_store import DuckDBStore
from equitylens.storage.raw_store import load_snapshot, load_snapshot_record, save_snapshots

DOC_SUBMISSIONS = "submissions.json"
DOC_COMPANYFACTS = "companyfacts.json"


@dataclass
class SyncReport:
    company: str
    fetched: bool = False
    source_documents: int = 0
    facts_seen: int = 0
    facts_accepted: int = 0
    facts_rejected: int = 0
    canonical_count: int = 0
    derived_count: int = 0
    rejected_reasons: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def line(self) -> str:
        return (
            f"{self.company}: docs={self.source_documents} facts_seen={self.facts_seen} "
            f"accepted={self.facts_accepted} rejected={self.facts_rejected} "
            f"canonical={self.canonical_count} derived={self.derived_count}"
        )


def _snapshot_document(*, url: str, meta: dict, path: Path, sha: str) -> SourceDocument:
    return SourceDocument(
        provider="SEC",
        document_type="COMPANYFACTS_SNAPSHOT" if "companyfacts" in url else "SUBMISSIONS_SNAPSHOT",
        source_url=url,
        content_sha256=sha,
        local_path=str(path),
        fetched_at=meta["fetched_at"],
        parser_version=PARSER_VERSION,
        metadata_json={"http_status": meta.get("status", 200), "content_length": meta["content_length"]},
    )


def sync_company(
    ticker: str,
    *,
    fetch: bool = True,
    force: bool = False,
    store: DuckDBStore | None = None,
    client: SECClient | None = None,
    raw_dir=RAW_DIR,
) -> SyncReport:
    store = store or DuckDBStore()
    store.connect()
    store.init_schema()
    company = get_company(ticker, store=store)
    cik = company.cik
    directory = raw_dir / "sec" / cik

    started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    report = SyncReport(company=ticker)
    fetched_bytes = 0
    try:
        docs: list[SourceDocument] = []
        submissions_data: dict | None = None

        if fetch:
            own_client = client or SECClient()
            try:
                subs_url = SEC_SUBMISSIONS_URL + f"CIK{cik}.json"
                cf_url = SEC_COMPANYFACTS_URL + f"CIK{cik}.json"
                subs_status, subs_content, subs_meta = own_client.get(subs_url)
                cf_status, cf_content, cf_meta = own_client.get(cf_url)
                subs_meta = {**subs_meta, "status": subs_status}
                cf_meta = {**cf_meta, "status": cf_status}
                fetched_bytes += len(subs_content) + len(cf_content)
                submissions_data = json.loads(subs_content)
                published = save_snapshots(
                    directory,
                    {
                        DOC_SUBMISSIONS: subs_content,
                        DOC_COMPANYFACTS: cf_content,
                    },
                    metadata={
                        DOC_SUBMISSIONS: {"fetched_at": subs_meta["fetched_at"]},
                        DOC_COMPANYFACTS: {"fetched_at": cf_meta["fetched_at"]},
                    },
                )
                subs_path, subs_sha = published[DOC_SUBMISSIONS]
                cf_path, cf_sha = published[DOC_COMPANYFACTS]
                subs_doc = _snapshot_document(
                    url=subs_url, meta=subs_meta, path=subs_path, sha=subs_sha,
                )
                subs_doc.company_id = cik
                cf_doc = _snapshot_document(
                    url=cf_url, meta=cf_meta, path=cf_path, sha=cf_sha,
                )
                cf_doc.company_id = cik
                docs.extend([subs_doc, cf_doc])
            finally:
                if client is None:
                    own_client.close()
            report.fetched = True
        else:
            # load from cache (idempotent second sync without downloads)
            subs = load_snapshot_record(directory, DOC_SUBMISSIONS)
            cf = load_snapshot_record(directory, DOC_COMPANYFACTS)
            if subs is None or cf is None:
                raise FileNotFoundError(
                    f"No cached snapshots for {ticker}; run with --fetch first"
                )
            submissions_data = json.loads(subs.content)
            cf_content = cf.content
            docs = [
                SourceDocument(provider="SEC", document_type="SUBMISSIONS_SNAPSHOT",
                              source_url=SEC_SUBMISSIONS_URL + f"CIK{cik}.json",
                              content_sha256=subs.sha256, local_path=str(subs.path),
                              fetched_at=subs.fetched_at, company_id=cik,
                              parser_version=PARSER_VERSION),
                SourceDocument(provider="SEC", document_type="COMPANYFACTS_SNAPSHOT",
                              source_url=SEC_COMPANYFACTS_URL + f"CIK{cik}.json",
                              content_sha256=cf.sha256, local_path=str(cf.path),
                              fetched_at=cf.fetched_at, company_id=cik,
                              parser_version=PARSER_VERSION),
            ]

        # persist source documents (idempotent by hash)
        doc_rows = [d.to_row() for d in docs]
        store.upsert_source_documents(doc_rows)
        report.source_documents = len(doc_rows)

        # normalize companyfacts
        cf_doc = next(d for d in docs if d.document_type == "COMPANYFACTS_SNAPSHOT")
        cf_data = json.loads(cf_content)
        mappings = MappingRegistry()
        calendar = FiscalCalendar.from_submissions(submissions_data, fallback_mm_dd=company.fiscal_year_end)
        raw_rows, canonical_rows, result = normalize_companyfacts(
            cf_data, mappings, calendar, cf_doc.source_document_id, cik
        )
        store.replace_raw_facts(cf_doc.source_document_id, raw_rows)
        store.replace_canonical_facts(cf_doc.source_document_id, canonical_rows)

        report.facts_seen = result.facts_seen
        report.facts_accepted = result.facts_accepted
        report.facts_rejected = result.facts_rejected
        report.canonical_count = result.canonical_count
        report.derived_count = result.derived_count
        report.rejected_reasons = result.rejected_reasons
        report.warnings = [f"{m}: {n}" for m, n in result.rejected_reasons.items()]

        store.insert_ingestion_run({
            "run_id": f"run_{uuid.uuid4().hex[:12]}",
            "company_id": cik,
            "provider": "SEC",
            "command": "sync" + ("" if fetch else " --no-fetch"),
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "status": "OK",
            "fetched_bytes": fetched_bytes,
            "facts_seen": result.facts_seen,
            "facts_accepted": result.facts_accepted,
            "facts_rejected": result.facts_rejected,
            "warnings_json": json.dumps(report.warnings, ensure_ascii=False),
        })
        return report
    except Exception:
        store.insert_ingestion_run({
            "run_id": f"run_{uuid.uuid4().hex[:12]}",
            "company_id": cik,
            "provider": "SEC",
            "command": "sync",
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "status": "ERROR",
            "fetched_bytes": fetched_bytes,
            "facts_seen": 0, "facts_accepted": 0, "facts_rejected": 0,
            "warnings_json": json.dumps(["exception"], ensure_ascii=False),
        })
        raise


def sync_segments(
    ticker: str,
    *,
    fetch: bool = True,
    store: DuckDBStore | None = None,
    client: SECClient | None = None,
    forms: tuple[str, ...] = ("10-K", "10-Q"),
    limit_per_form: int = 5,
    raw_dir=RAW_DIR,
) -> SyncReport:
    """Fetch 10-K/10-Q filing documents and extract segment facts (M4)."""
    from equitylens.ingestion.sec.filing_docs import fetch_filing_documents
    from equitylens.normalization.fiscal_periods import FiscalCalendar
    from equitylens.normalization.ixbrl import IxbrlDocument
    from equitylens.normalization.segments import SegmentConfigRegistry, extract_segments

    store = store or DuckDBStore()
    store.connect()
    store.init_schema()
    company = get_company(ticker, store=store)
    cik = company.cik

    docs = fetch_filing_documents(ticker, forms=forms, limit_per_form=limit_per_form,
                                  fetch=fetch, store=store, client=client, raw_dir=raw_dir)
    subs_cached = load_snapshot(raw_dir / "sec" / cik, DOC_SUBMISSIONS)
    if subs_cached is None:
        raise FileNotFoundError(f"No cached submissions snapshot for {ticker}")
    subs = json.loads(subs_cached[0])
    calendar = FiscalCalendar.from_submissions(subs, fallback_mm_dd=company.fiscal_year_end)
    config = SegmentConfigRegistry().get(ticker)
    if config is None:
        raise ValueError(f"No segment mapping configured for {ticker}")

    total = 0
    warnings: list[str] = []
    for doc in docs:
        content = Path(doc.local_path).read_bytes()
        ixbrl = IxbrlDocument.parse(content)
        rows, ws = extract_segments(ticker, ixbrl, config, calendar, doc.source_document_id)
        for r in rows:
            r["company_id"] = cik
        store.replace_segment_facts(doc.source_document_id, rows)
        total += len(rows)
        warnings.extend(ws)

    report = SyncReport(company=ticker)
    report.facts_accepted = total
    report.warnings = warnings
    return report
