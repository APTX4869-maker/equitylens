from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import httpx
import pytest

from equitylens.companies.discovery import CompanyDiscovery, DiscoveryError, SECDiscoverySource


class FakeDiscoverySource:
    def __init__(self):
        self.registry_rows = [
            {"cik_str": 1, "ticker": "EXAMPLE", "title": "Example Inc."},
        ]
        self.submission_calls = 0
        self.history_calls = 0
        self.submissions = {
            "cik": "0000000001",
            "entityType": "operating",
            "sic": "3571",
            "name": "Example Inc.",
            "tickers": ["EXAMPLE"],
            "exchanges": ["NYSE"],
            "filings": {
                "recent": {
                    "accessionNumber": ["0000000001-26-000001", "0000000001-26-000002"],
                    "form": ["10-K", "10-Q"],
                    "filingDate": ["2026-02-01", "2026-05-01"],
                    "reportDate": ["2025-12-31", "2026-03-31"],
                    "primaryDocument": ["annual.htm", "quarter.htm"],
                },
                "files": [
                    {"name": "CIK0000000001-submissions-001.json", "filingCount": 1}
                ],
            },
        }

    def registry(self):
        return deepcopy(self.registry_rows), {
            "source": "SEC company_tickers",
            "fetched_at": "2026-09-11T00:00:00+00:00",
            "content_sha256": "a" * 64,
        }

    def issuer_submissions(self, cik):
        self.submission_calls += 1
        return deepcopy(self.submissions), {
            "source": f"SEC submissions {cik}",
            "fetched_at": "2026-09-11T00:00:00+00:00",
            "content_sha256": "b" * 64,
        }

    def historical_submissions(self, name):
        self.history_calls += 1
        return {
            "accessionNumber": ["0000000001-22-000001"],
            "form": ["10-K"],
            "filingDate": ["2022-02-01"],
            "reportDate": ["2021-12-31"],
            "primaryDocument": ["annual-2021.htm"],
        }, {
            "source": name,
            "fetched_at": "2026-09-11T00:00:00+00:00",
            "content_sha256": "c" * 64,
        }


@pytest.fixture()
def discovery_case(db):
    source = FakeDiscoverySource()
    discovery = CompanyDiscovery(
        db,
        source=source,
        clock=lambda: datetime(2026, 9, 11, tzinfo=timezone.utc),
    )
    return source, discovery


def test_changed_identity_cannot_create_task(discovery_case):
    source, discovery = discovery_case
    found = discovery.discover(" example ")
    source.submissions["name"] = "Different Issuer Inc."

    with pytest.raises(DiscoveryError) as exc:
        discovery.verify(
            found.discovery_id,
            identity_hash=found.identity_hash,
            candidate_id=found.candidates[0].candidate_id,
        )
    assert exc.value.code == "IDENTITY_CHANGED"


def test_discovery_fetches_historical_submission_pages(discovery_case):
    source, discovery = discovery_case
    result = discovery.discover("EXAMPLE")

    assert source.history_calls == 1
    assert result.coverage.form_counts == {"10-K": 2, "10-Q": 1}
    assert result.eligibility.status == "SUPPORTED"
    assert result.eligibility.template == "us_gaap_operating_v1"


def test_multiple_share_classes_fetch_financial_identity_once(discovery_case):
    source, discovery = discovery_case
    source.registry_rows.append(
        {"cik_str": 1, "ticker": "EXAMPLE.B", "title": "Example Inc."}
    )
    source.submissions["tickers"].append("EXAMPLE.B")
    source.submissions["exchanges"].append("NYSE")

    result = discovery.discover("EXAMPLE")

    assert source.submission_calls == 1
    assert len(result.candidates) == 2
    assert {item.ticker for item in result.candidates} == {"EXAMPLE", "EXAMPLE.B"}


def test_etf_is_rejected_with_submission_evidence(discovery_case):
    source, discovery = discovery_case
    source.submissions.update(
        {"entityType": "other", "name": "Example Index ETF", "sic": "6722"}
    )

    result = discovery.discover("EXAMPLE")

    assert result.eligibility.status == "REJECTED"
    assert result.eligibility.reason_code == "UNSUPPORTED_INSTRUMENT"
    assert result.eligibility.reason == "当前仅支持经营性公司，暂不支持基金、ETF 或 SPAC"
    assert {candidate.instrument_type for candidate in result.candidates} == {"ETF"}


def test_fund_is_rejected_and_classified_consistently(discovery_case):
    source, discovery = discovery_case
    source.submissions.update(
        {"entityType": "other", "name": "Example Investment Fund", "sic": "6722"}
    )

    result = discovery.discover("EXAMPLE")

    assert result.eligibility.reason_code == "UNSUPPORTED_INSTRUMENT"
    assert {candidate.instrument_type for candidate in result.candidates} == {"FUND"}


def test_blank_check_company_is_rejected_and_classified_as_spac(discovery_case):
    source, discovery = discovery_case
    source.submissions.update(
        {"entityType": "other", "name": "Example Acquisition Corp", "sic": "6770"}
    )

    result = discovery.discover("EXAMPLE")

    assert result.eligibility.reason_code == "UNSUPPORTED_INSTRUMENT"
    assert {candidate.instrument_type for candidate in result.candidates} == {"SPAC"}


def test_missing_supported_filing_regime_requires_adaptation(discovery_case):
    source, discovery = discovery_case
    source.submissions["filings"]["recent"]["form"] = ["20-F", "6-K"]
    source.submissions["filings"]["files"] = []

    result = discovery.discover("EXAMPLE")

    assert result.eligibility.status == "NEEDS_ADAPTATION"
    assert result.eligibility.reason_code == "TEMPLATE_UNSUPPORTED"


def test_sec_access_denial_becomes_retryable_discovery_error(tmp_path, monkeypatch):
    monkeypatch.setenv("EQUITYLENS_USER_AGENT", "EquityLens test test@example.org")
    request = httpx.Request("GET", "https://www.sec.gov/files/company_tickers.json")
    response = httpx.Response(403, request=request)

    class DeniedClient:
        def get(self, url):
            raise httpx.HTTPStatusError("forbidden", request=request, response=response)

    source = SECDiscoverySource(raw_dir=tmp_path, client=DeniedClient())

    with pytest.raises(DiscoveryError) as exc:
        source.registry()

    assert exc.value.code == "SEC_UNAVAILABLE"
    assert exc.value.retryable is True
