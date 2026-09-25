"""Transactional issuer/security registry.

Ticker aliases are time bounded.  A ticker is therefore a lookup key, never
the issuer identity, and ambiguous active aliases must be resolved explicitly.
"""

from __future__ import annotations

import json
import uuid
from datetime import date

from equitylens.companies.models import CompanyIdentity, SecurityIdentity
from equitylens.storage.duckdb_store import DuckDBStore
from equitylens.storage.writer import writer_for


class CompanyRegistryError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        candidates: list[SecurityIdentity] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.candidates = candidates or []


def seed_security_id(company_id: str, ticker: str, exchange: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"https://equitylens.local/security/{company_id}/{exchange}/{ticker}",
        )
    )


class CompanyRegistry:
    def __init__(self, store: DuckDBStore):
        self.store = store
        self.store.connect()

    def register_company(
        self, company: CompanyIdentity, *, legacy_ticker: str
    ) -> CompanyIdentity:
        with writer_for(self.store).transaction(self.store):
            self.store._conn.execute(
                """
                INSERT INTO company (
                  company_id, ticker, cik, legal_name, reporting_template,
                  quality_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, now(), now())
                ON CONFLICT (company_id) DO UPDATE SET
                  cik = excluded.cik,
                  legal_name = excluded.legal_name,
                  reporting_template = excluded.reporting_template,
                  quality_status = excluded.quality_status,
                  updated_at = now()
                """,
                [
                    company.company_id,
                    legacy_ticker.strip().upper(),
                    company.cik,
                    company.legal_name,
                    company.reporting_template,
                    company.quality_status,
                ],
            )
        return company

    def register_security(
        self,
        security: SecurityIdentity,
        *,
        valid_from: date | None = None,
        valid_to: date | None = None,
    ) -> SecurityIdentity:
        with writer_for(self.store).transaction(self.store):
            self.store._conn.execute(
                """
                INSERT INTO security (
                  security_id, company_id, class_label, exchange, currency,
                  instrument_type, status, identity_evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    security.security_id,
                    security.company_id,
                    security.class_label,
                    security.exchange,
                    security.currency,
                    security.instrument_type,
                    security.status,
                    json.dumps(security.identity_evidence, sort_keys=True),
                ],
            )
            self._add_ticker_alias(
                security.security_id,
                ticker=security.ticker,
                exchange=security.exchange,
                valid_from=valid_from,
                valid_to=valid_to,
            )
        return security

    def add_ticker_alias(
        self,
        security_id: str,
        *,
        ticker: str,
        exchange: str,
        valid_from: date | None = None,
        valid_to: date | None = None,
    ) -> None:
        with writer_for(self.store).transaction(self.store):
            self._add_ticker_alias(
                security_id,
                ticker=ticker,
                exchange=exchange,
                valid_from=valid_from,
                valid_to=valid_to,
            )

    def _add_ticker_alias(
        self,
        security_id: str,
        *,
        ticker: str,
        exchange: str,
        valid_from: date | None,
        valid_to: date | None,
    ) -> None:
        ticker = ticker.strip().upper()
        start = valid_from or date(1900, 1, 1)
        if valid_to is not None and valid_to < start:
            raise CompanyRegistryError(
                "INVALID_ALIAS_RANGE", "ticker alias valid_to precedes valid_from"
            )
        overlap = self.store._conn.execute(
            """
            SELECT alias_id FROM security_ticker_alias
            WHERE ticker = ? AND exchange = ?
              AND coalesce(valid_to, DATE '9999-12-31') >= ?
              AND coalesce(?, DATE '9999-12-31') >= valid_from
            LIMIT 1
            """,
            [ticker, exchange, start, valid_to],
        ).fetchone()
        if overlap:
            raise CompanyRegistryError(
                "TICKER_ALIAS_OVERLAP",
                f"{exchange}:{ticker} already has an overlapping validity range",
            )
        alias_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"https://equitylens.local/alias/{security_id}/{exchange}/{ticker}/{start}/{valid_to}",
            )
        )
        self.store._conn.execute(
            """
            INSERT INTO security_ticker_alias
              (alias_id, security_id, ticker, exchange, valid_from, valid_to)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [alias_id, security_id, ticker, exchange, start, valid_to],
        )

    def resolve(
        self, ticker: str, security_id: str | None = None
    ) -> SecurityIdentity:
        normalized = ticker.strip().upper()
        params: list[object] = [normalized]
        security_clause = ""
        if security_id is not None:
            security_clause = " AND s.security_id = ?"
            params.append(security_id)
        rows = self.store.query(
            f"""
            SELECT s.*, a.ticker, a.valid_from, a.valid_to,
                   c.legal_name AS company_name
            FROM security_ticker_alias a
            JOIN security s ON s.security_id = a.security_id
            JOIN company c ON c.company_id = s.company_id
            WHERE a.ticker = ?
              AND a.valid_from <= CURRENT_DATE
              AND (a.valid_to IS NULL OR a.valid_to >= CURRENT_DATE)
              AND s.status = 'ACTIVE'
              {security_clause}
            ORDER BY s.security_id
            """,
            params,
        )
        candidates = [self._identity(row) for row in rows]
        if not candidates:
            raise CompanyRegistryError(
                "SECURITY_NOT_FOUND", f"no active security found for {normalized}"
            )
        if len(candidates) > 1:
            raise CompanyRegistryError(
                "AMBIGUOUS_SECURITY",
                f"multiple active securities found for {normalized}",
                candidates=candidates,
            )
        return candidates[0]

    @staticmethod
    def _identity(row: dict) -> SecurityIdentity:
        evidence = row.get("identity_evidence_json") or {}
        if isinstance(evidence, str):
            evidence = json.loads(evidence)
        return SecurityIdentity(
            security_id=row["security_id"],
            company_id=row["company_id"],
            ticker=row["ticker"],
            class_label=row.get("class_label"),
            exchange=row["exchange"],
            currency=row["currency"],
            instrument_type=row["instrument_type"],
            status=row["status"],
            identity_evidence=evidence,
            valid_from=row.get("valid_from"),
            valid_to=row.get("valid_to"),
            company_name=row.get("company_name"),
        )
