"""Management / governance ingestion (M6).

- DEF 14A proxy: named executives, Summary Compensation Table, board of directors
- Form 4 ownership reports: insider transactions (raw form4.xml)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from equitylens.config import PARSER_VERSION, RAW_DIR, SEC_ARCHIVES_URL
from equitylens.domain.companies import get_company
from equitylens.domain.filings import SourceDocument
from equitylens.ingestion.sec.client import SECClient
from equitylens.ingestion.sec.filing_docs import list_filing_docs
from equitylens.normalization.insider import parse_form4
from equitylens.normalization.proxy import parse_proxy
from equitylens.storage.duckdb_store import DuckDBStore
from equitylens.storage.raw_store import load_snapshot_record, save_snapshot


@dataclass
class ManagementSyncReport:
    company: str
    executives: int = 0
    compensation_rows: int = 0
    board_members: int = 0
    insider_transactions: int = 0
    warnings: list[str] = field(default_factory=list)


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    return s[:40] or "x"


def _fetch_doc(client: SECClient, url: str, directory: Path, doc_name: str,
               company_id: str, form_type: str, accn: str, filed_at: str | None) -> tuple[bytes, SourceDocument]:
    _, content, meta = client.get(url)
    path, sha = save_snapshot(
        directory, doc_name, content,
        metadata={"fetched_at": meta.get("fetched_at") or ""},
    )
    doc = SourceDocument(
        provider="SEC", document_type="FILING_DOCUMENT", form_type=form_type,
        accession_number=accn, filed_at=filed_at,
        source_url=url, content_sha256=sha, local_path=str(path),
        fetched_at=meta.get("fetched_at") or "", parser_version=PARSER_VERSION,
        company_id=company_id, metadata_json={"primary_document": doc_name},
    )
    return content, doc


def sync_management(
    ticker: str,
    *,
    fetch: bool = True,
    store: DuckDBStore | None = None,
    client: SECClient | None = None,
    forms4_limit: int = 12,
    raw_dir=RAW_DIR,
) -> ManagementSyncReport:
    store = store or DuckDBStore()
    store.connect()
    store.init_schema()
    company = get_company(ticker, store=store)
    cik = company.cik
    cik_int = str(int(cik))
    report = ManagementSyncReport(company=ticker)
    own_client = client or SECClient()
    docs_to_persist: list[SourceDocument] = []

    try:
        # ---------- 1) DEF 14A proxy ----------
        proxy_filings = list_filing_docs(
            ticker, forms=("DEF 14A",), limit_per_form=1, raw_dir=raw_dir
        )
        if proxy_filings:
            row = proxy_filings[0]
            accn = row["accessionNumber"]
            directory = raw_dir / "sec" / cik / "filing_docs" / accn
            url = f"{SEC_ARCHIVES_URL}{cik_int}/{accn.replace('-', '')}/{row['primaryDocument']}"
            if fetch:
                content, doc = _fetch_doc(own_client, url, directory, "proxy.html",
                                          cik, "DEF 14A", accn, row.get("filingDate"))
            else:
                record = load_snapshot_record(directory, "proxy.html")
                if record is None:
                    report.warnings.append("no cached proxy; run with --fetch")
                    content, doc = None, None
                else:
                    content = record.content
                    doc = SourceDocument(provider="SEC", document_type="FILING_DOCUMENT",
                                         form_type="DEF 14A", accession_number=accn,
                                         filed_at=row.get("filingDate"), source_url=url,
                                         content_sha256=record.sha256, local_path=str(record.path),
                                         fetched_at=record.fetched_at,
                                         parser_version=PARSER_VERSION, company_id=cik)
            if content is not None and doc is not None:
                docs_to_persist.append(doc)
                parsed = parse_proxy(content)
                exec_rows, comp_rows, board_rows = _proxy_rows(cik, parsed, doc.source_document_id)
                store.replace_proxy(cik, doc.source_document_id, exec_rows, comp_rows, board_rows)
                report.executives = len(exec_rows)
                report.compensation_rows = len(comp_rows)
                report.board_members = len(board_rows)
                report.warnings.extend(parsed.warnings)
        else:
            report.warnings.append("no DEF 14A found in recent filings")

        # ---------- 2) Form 4 ----------
        ins_rows: list[dict] = []
        for row in list_filing_docs(
            ticker, forms=("4",), limit_per_form=forms4_limit, raw_dir=raw_dir
        ):
            accn = row["accessionNumber"]
            accn_nodash = accn.replace("-", "")
            directory = raw_dir / "sec" / cik / "filing_docs" / accn
            url = f"{SEC_ARCHIVES_URL}{cik_int}/{accn_nodash}/form4.xml"
            if fetch:
                content, doc = _fetch_doc(own_client, url, directory, "form4.xml",
                                          cik, "4", accn, row.get("filingDate"))
            else:
                record = load_snapshot_record(directory, "form4.xml")
                if record is None:
                    continue
                content = record.content
                doc = SourceDocument(provider="SEC", document_type="FILING_DOCUMENT",
                                     form_type="4", accession_number=accn,
                                     filed_at=row.get("filingDate"), source_url=url,
                                     content_sha256=record.sha256, local_path=str(record.path),
                                     fetched_at=record.fetched_at,
                                     parser_version=PARSER_VERSION, company_id=cik)
            docs_to_persist.append(doc)
            parsed = parse_form4(content)
            for i, t in enumerate(parsed.transactions):
                ins_rows.append({
                    "transaction_id": f"f4_{cik}_{accn_nodash}_{i}",
                    "company_id": cik,
                    "insider_name": t.insider_name,
                    "insider_cik": t.insider_cik,
                    "officer_title": t.officer_title,
                    "transaction_date": t.transaction_date,
                    "transaction_code": t.transaction_code,
                    "security_title": t.security_title,
                    "shares": t.shares,
                    "price_per_share": t.price_per_share,
                    "acquired_disposed_code": t.acquired_disposed_code,
                    "shares_owned_after": t.shares_owned_after,
                    "filed_at": row.get("filingDate"),
                    "accession_number": accn,
                    "source_url": url,
                    "source_document_id": doc.source_document_id,
                })
        store.replace_insider_transactions(cik, ins_rows)
        report.insider_transactions = len(ins_rows)
        store.upsert_source_documents([d.to_row() for d in docs_to_persist])
    finally:
        if client is None:
            own_client.close()
    return report


def _proxy_rows(cik: str, parsed, source_document_id: str):
    exec_rows: list[dict] = []
    comp_rows: list[dict] = []
    board_rows: list[dict] = []
    for e in parsed.executives:
        eid = f"ex_{cik}_{_slug(e.name)}"
        latest_year = max((c.get("year") for c in e.compensation), default=None)
        exec_rows.append({
            "executive_id": eid, "company_id": cik, "name": e.name, "title": e.title,
            "source_document_id": source_document_id, "source_doc_type": "DEF 14A",
            "as_of_year": latest_year,
        })
        for c in e.compensation:
            comp_rows.append({
                "comp_id": f"{eid}_{c['year']}", "company_id": cik, "executive_id": eid,
                "fiscal_year": c["year"], "salary": c.get("salary"),
                "bonus": c.get("bonus"), "stock_awards": c.get("stock_awards"),
                "option_awards": c.get("option_awards"),
                "non_equity_incentive": c.get("non_equity_incentive"),
                "all_other": c.get("all_other"), "total_compensation": c.get("total"),
                "source_document_id": source_document_id,
            })
    for d in parsed.directors:
        board_rows.append({
            "board_id": f"bd_{cik}_{_slug(d.name)}", "company_id": cik, "name": d.name,
            "occupation": d.occupation, "age": d.age, "director_since": d.director_since,
            "independent": d.independent, "committees": None,
            "source_document_id": source_document_id,
        })
    return exec_rows, comp_rows, board_rows
