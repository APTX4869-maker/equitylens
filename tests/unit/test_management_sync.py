from __future__ import annotations

import json
from types import SimpleNamespace

from equitylens.ingestion.sec.management import (
    _filing_document_url,
    _primary_document_name,
    sync_management,
)


FORM4_XML = b"""<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId><rptOwnerCik>0001243821</rptOwnerCik><rptOwnerName>GAWEL SCOTT</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>EVP</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-09-16</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>10</value></transactionShares>
        <transactionPricePerShare><value>200</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>90</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""


class FakeStore:
    def __init__(self, existing=None):
        self.existing = list(existing or [])
        self.transactions = []
        self.source_rows = []

    def connect(self):
        return self

    def init_schema(self):
        pass

    def query(self, sql, params=None):
        if "FROM insider_transaction" in sql:
            return list(self.existing)
        return []

    def replace_insider_transactions(self, company_id, rows):
        self.transactions = list(rows)

    def upsert_source_documents(self, rows):
        self.source_rows.extend(rows)

    def replace_proxy(self, company_id, source_document_id, exec_rows, comp_rows, board_rows):
        pass


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return None, response, {"fetched_at": "2026-09-25T00:00:00+00:00"}


def test_form4_uses_dynamic_primary_document_without_xsl_prefix():
    row = {
        "accessionNumber": "0001243821-26-000007",
        "primaryDocument": "xslF345X06/wk-form4_1789766132.xml",
    }

    name = _primary_document_name(row)

    assert name == "wk-form4_1789766132.xml"
    assert _filing_document_url("1045810", row["accessionNumber"], name) == (
        "https://www.sec.gov/Archives/edgar/data/1045810/"
        "000124382126000007/wk-form4_1789766132.xml"
    )


def _filing(accession: str, document: str) -> dict:
    return {
        "accessionNumber": accession,
        "primaryDocument": document,
        "filingDate": "2026-09-18",
    }


def _stub_filings(monkeypatch, rows):
    def list_docs(ticker, *, forms, limit_per_form, raw_dir):
        return [] if forms == ("DEF 14A",) else list(rows)

    monkeypatch.setattr(
        "equitylens.ingestion.sec.management.list_filing_docs", list_docs
    )
    monkeypatch.setattr(
        "equitylens.ingestion.sec.management.get_company",
        lambda ticker, store: SimpleNamespace(cik="0001045810"),
    )


def test_form4_fetch_and_replay_keep_primary_document_identity(monkeypatch, tmp_path):
    accession = "0001243821-26-000007"
    document = "wk-form4_1789766132.xml"
    _stub_filings(monkeypatch, [_filing(accession, document)])
    store = FakeStore()
    client = FakeClient([FORM4_XML])

    report = sync_management(
        "NVDA", store=store, client=client, raw_dir=tmp_path / "raw"
    )

    expected_url = (
        "https://www.sec.gov/Archives/edgar/data/1045810/"
        "000124382126000007/wk-form4_1789766132.xml"
    )
    assert client.urls == [expected_url]
    assert report.insider_transactions == 1
    assert store.transactions[0]["source_url"] == expected_url
    metadata = json.loads(store.source_rows[0]["metadata_json"])
    assert metadata["primary_document"] == document
    assert store.source_rows[0]["local_path"].endswith(document)

    replay_store = FakeStore()
    replay = sync_management(
        "NVDA",
        fetch=False,
        store=replay_store,
        client=FakeClient([]),
        raw_dir=tmp_path / "raw",
    )
    assert replay.insider_transactions == 1
    assert replay_store.transactions[0]["source_url"] == expected_url
    assert replay_store.source_rows[0]["local_path"].endswith(document)


def test_failed_form4_keeps_old_accession_and_continues(monkeypatch, tmp_path):
    failed_accession = "0001243821-26-000007"
    good_accession = "0001243821-26-000008"
    rows = [
        _filing(failed_accession, "failed.xml"),
        _filing(good_accession, "good.xml"),
    ]
    _stub_filings(monkeypatch, rows)
    old = {
        "transaction_id": "old-failed-accession",
        "company_id": "0001045810",
        "insider_name": "Existing Owner",
        "accession_number": failed_accession,
    }
    store = FakeStore(existing=[old])

    report = sync_management(
        "NVDA",
        store=store,
        client=FakeClient([RuntimeError("invalid XML"), FORM4_XML]),
        raw_dir=tmp_path / "raw",
    )

    assert {row["transaction_id"] for row in store.transactions} == {
        "old-failed-accession",
        "f4_0001045810_000124382126000008_0",
    }
    assert report.form4_documents == 1
    assert report.form4_skipped == 1
    assert any(failed_accession in warning for warning in report.warnings)
