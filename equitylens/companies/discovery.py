"""Evidence-backed, read-only SEC issuer and security discovery."""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

import httpx

from equitylens.companies.models import (
    DiscoveryCandidate,
    DiscoveryResult,
    Eligibility,
    FilingCoverage,
)
from equitylens.config import RAW_DIR, SEC_SUBMISSIONS_URL, SEC_TICKERS_URL, user_agent
from equitylens.ingestion.sec.client import SECClient
from equitylens.ingestion.sec.filing_docs import submission_rows
from equitylens.publication.models import sha256_json
from equitylens.storage.raw_store import load_snapshot_record, save_snapshot
from equitylens.storage.writer import writer_for


TICKER_RE = re.compile(r"^[A-Z0-9.-]{1,20}$")


class DiscoveryError(ValueError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class DiscoverySource(Protocol):
    def registry(self) -> tuple[list[dict], dict]: ...
    def issuer_submissions(self, cik: str) -> tuple[dict, dict]: ...
    def historical_submissions(self, name: str) -> tuple[dict, dict]: ...


def normalize_ticker(value: str) -> str:
    ticker = value.strip().upper()
    if not TICKER_RE.fullmatch(ticker):
        raise DiscoveryError(
            "INVALID_TICKER",
            "股票代码只能包含 1—20 位字母、数字、点或连字符",
        )
    return ticker


def _instrument_type(submissions: dict) -> str:
    name = str(submissions.get("name") or "").upper()
    sic = str(submissions.get("sic") or "")
    if sic == "6770" or "SPAC" in name or "ACQUISITION CORP" in name or "BLANK CHECK" in name:
        return "SPAC"
    if " ETF" in name or sic == "6726":
        return "ETF"
    if " FUND" in name or sic == "6722":
        return "FUND"
    return "COMMON_STOCK"


class SECDiscoverySource:
    def __init__(self, *, raw_dir: Path = RAW_DIR, client: SECClient | None = None):
        self.raw_dir = raw_dir
        self.client = client

    def _client(self) -> tuple[SECClient, bool]:
        configured = user_agent()
        if "contact@example.com" in configured:
            raise DiscoveryError(
                "CONFIGURATION_REQUIRED",
                "set EQUITYLENS_USER_AGENT to an identifying SEC contact before discovery",
            )
        return (self.client, False) if self.client else (SECClient(), True)

    def _load_or_fetch(self, directory: Path, name: str, url: str) -> tuple[dict, dict]:
        cached = load_snapshot_record(directory, name)
        if cached:
            fetched = datetime.fromisoformat(cached.fetched_at.replace("Z", "+00:00"))
            if fetched.tzinfo is None:
                fetched = fetched.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - fetched <= timedelta(hours=24):
                return json.loads(cached.content), {
                    "source": url,
                    "fetched_at": cached.fetched_at,
                    "content_sha256": cached.sha256,
                    "local_path": str(cached.path),
                }
        client, owned = self._client()
        try:
            try:
                _, content, metadata = client.get(url)
            except (httpx.HTTPError, RuntimeError) as exc:
                raise DiscoveryError(
                    "SEC_UNAVAILABLE",
                    "SEC EDGAR is temporarily unavailable; retry later",
                    retryable=True,
                ) from exc
        finally:
            if owned:
                client.close()
        path, digest = save_snapshot(
            directory,
            name,
            content,
            metadata={"fetched_at": metadata["fetched_at"]},
        )
        return json.loads(content), {
            "source": url,
            "fetched_at": metadata["fetched_at"],
            "content_sha256": digest,
            "local_path": str(path),
        }

    def registry(self) -> tuple[list[dict], dict]:
        data, evidence = self._load_or_fetch(
            self.raw_dir / "sec" / "_registry",
            "company_tickers.json",
            SEC_TICKERS_URL,
        )
        rows = list(data.values()) if isinstance(data, dict) else list(data)
        return rows, evidence

    def issuer_submissions(self, cik: str) -> tuple[dict, dict]:
        return self._load_or_fetch(
            self.raw_dir / "sec" / cik,
            "submissions.json",
            SEC_SUBMISSIONS_URL + f"CIK{cik}.json",
        )

    def historical_submissions(self, name: str) -> tuple[dict, dict]:
        return self._load_or_fetch(
            self.raw_dir / "sec" / "_submissions_history",
            name,
            SEC_SUBMISSIONS_URL + name,
        )


class CompanyDiscovery:
    def __init__(self, store, *, source: DiscoverySource | None = None, clock=None):
        self.store = store
        self.source = source or SECDiscoverySource()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def discover(self, ticker: str, *, persist: bool = True) -> DiscoveryResult:
        ticker = normalize_ticker(ticker)
        registry, registry_evidence = self.source.registry()
        matches = [row for row in registry if str(row.get("ticker", "")).upper() == ticker]
        if not matches:
            raise DiscoveryError("SECURITY_NOT_FOUND", f"SEC registry has no {ticker}")
        ciks = sorted({f"{int(row['cik_str']):010d}" for row in matches})
        candidates: list[DiscoveryCandidate] = []
        all_evidence = [registry_evidence]
        all_filings: list[dict] = []
        issuer_snapshots: list[dict] = []
        for cik in ciks:
            submissions, evidence = self.source.issuer_submissions(cik)
            all_evidence.append(evidence)
            histories = []
            for file_info in submissions.get("filings", {}).get("files") or []:
                name = file_info.get("name")
                if not name:
                    continue
                historical, historical_evidence = self.source.historical_submissions(name)
                histories.extend(submission_rows(historical))
                all_evidence.append(historical_evidence)
            filings = submission_rows(submissions.get("filings", {}).get("recent") or [])
            filings.extend(histories)
            all_filings.extend(filings)
            issuer_snapshots.append(
                {
                    "cik": cik,
                    "name": submissions.get("name"),
                    "entity_type": submissions.get("entityType"),
                    "sic": submissions.get("sic"),
                    "tickers": submissions.get("tickers") or [],
                    "exchanges": submissions.get("exchanges") or [],
                    "forms": sorted({row.get("form") for row in filings if row.get("form")}),
                }
            )
            tickers = submissions.get("tickers") or [ticker]
            exchanges = submissions.get("exchanges") or [matches[0].get("exchange") or "UNKNOWN"]
            for index, listed_ticker in enumerate(tickers):
                exchange = exchanges[index] if index < len(exchanges) else "UNKNOWN"
                candidate_payload = {
                    "company_id": cik,
                    "ticker": str(listed_ticker).upper(),
                    "exchange": exchange,
                }
                candidates.append(
                    DiscoveryCandidate(
                        candidate_id=sha256_json(candidate_payload),
                        company_id=cik,
                        legal_name=submissions.get("name") or matches[0].get("title") or ticker,
                        ticker=str(listed_ticker).upper(),
                        exchange=exchange,
                        class_label=None,
                        instrument_type=_instrument_type(submissions),
                        evidence=[registry_evidence, evidence],
                    )
                )
        eligibility = self._eligibility(issuer_snapshots, all_filings)
        counts = Counter(row.get("form") for row in all_filings if row.get("form"))
        report_dates = sorted(
            str(row["reportDate"])
            for row in all_filings
            if row.get("reportDate")
        )
        identity_payload = {
            "issuers": issuer_snapshots,
            "securities": [
                item.model_dump(mode="json", exclude={"evidence"}) for item in candidates
            ],
            "evidence_hashes": sorted(
                item.get("content_sha256") for item in all_evidence if item.get("content_sha256")
            ),
        }
        now = self.clock()
        result = DiscoveryResult(
            discovery_id=str(uuid.uuid4()),
            ticker=ticker,
            identity_hash=sha256_json(identity_payload),
            expires_at=now + timedelta(minutes=15),
            candidates=candidates,
            eligibility=eligibility,
            coverage=FilingCoverage(
                form_counts=dict(counts),
                earliest_report_date=report_dates[0] if report_dates else None,
                latest_report_date=report_dates[-1] if report_dates else None,
            ),
            evidence=all_evidence,
        )
        if persist:
            with writer_for(self.store).transaction(self.store):
                self.store._conn.execute(
                    """
                    INSERT INTO company_discovery VALUES (?, ?, ?, ?, ?, now())
                    """,
                    [
                        result.discovery_id,
                        ticker,
                        result.identity_hash,
                        result.model_dump_json(),
                        result.expires_at.replace(tzinfo=None),
                    ],
                )
        return result

    def verify(
        self, discovery_id: str, *, identity_hash: str, candidate_id: str
    ) -> DiscoveryCandidate:
        row = self.store.query_one(
            "SELECT * FROM company_discovery WHERE discovery_id=?", [discovery_id]
        )
        if row is None:
            raise DiscoveryError("DISCOVERY_EXPIRED", "discovery does not exist")
        expires = row["expires_at"]
        now = self.clock()
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if now > expires:
            raise DiscoveryError("DISCOVERY_EXPIRED", "discovery has expired")
        stored = DiscoveryResult.model_validate_json(row["payload_json"])
        if stored.identity_hash != identity_hash:
            raise DiscoveryError("IDENTITY_CHANGED", "identity hash does not match discovery")
        current = self.discover(stored.ticker, persist=False)
        if current.identity_hash != identity_hash:
            raise DiscoveryError("IDENTITY_CHANGED", "issuer or security identity changed")
        for candidate in current.candidates:
            if candidate.candidate_id == candidate_id:
                return candidate
        raise DiscoveryError("IDENTITY_CHANGED", "selected security is no longer available")

    @staticmethod
    def _eligibility(issuers: list[dict], filings: list[dict]) -> Eligibility:
        sic_codes = {str(item.get("sic") or "") for item in issuers}
        entity_types = {str(item.get("entity_type") or "").lower() for item in issuers}
        forms = {str(row.get("form") or "").upper() for row in filings}
        instrument_types = {
            _instrument_type({"name": item.get("name"), "sic": item.get("sic")})
            for item in issuers
        }
        if instrument_types & {"ETF", "FUND", "SPAC"} and "operating" not in entity_types:
            return Eligibility(
                status="REJECTED",
                reason_code="UNSUPPORTED_INSTRUMENT",
                reason="当前仅支持经营性公司，暂不支持基金、ETF 或 SPAC",
            )
        if sic_codes & {"6021", "6022", "6035", "6311", "6331", "6798"}:
            return Eligibility(
                status="NEEDS_ADAPTATION",
                reason_code="TEMPLATE_UNSUPPORTED",
                reason="bank, insurance, or REIT template is not validated",
            )
        if "10-K" in forms and "10-Q" in forms and "operating" in entity_types:
            return Eligibility(status="SUPPORTED", template="us_gaap_operating_v1")
        return Eligibility(
            status="NEEDS_ADAPTATION",
            reason_code="TEMPLATE_UNSUPPORTED",
            reason="issuer does not have the validated 10-K/10-Q operating-company regime",
        )
