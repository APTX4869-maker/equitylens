"""Company identity registry.

V0.x supports AAPL and MSFT end-to-end. The ticker->CIK lookup is seeded from
the SEC company_tickers registry; supported companies carry curated metadata
(fiscal year end, exchange) used by the fiscal-period resolver.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from equitylens.config import RAW_DIR, SEC_TICKERS_URL


@dataclass(frozen=True)
class Company:
    ticker: str
    cik: str  # zero-padded 10-digit string as used by SEC URLs
    name: str
    exchange: str | None = None
    fiscal_year_end: str | None = None  # "MM-DD"
    security_id: str | None = None


SUPPORTED: dict[str, Company] = {
    "AAPL": Company(
        "AAPL", "0000320193", "Apple Inc.", exchange="NASDAQ", fiscal_year_end="09-30"
    ),
    "MSFT": Company(
        "MSFT", "0000789019", "Microsoft Corporation", exchange="NASDAQ", fiscal_year_end="06-30"
    ),
}


def get_company(ticker: str, *, store=None, security_id: str | None = None) -> Company:
    ticker = ticker.strip().upper()
    owned = False
    if store is None:
        try:
            from equitylens.storage.duckdb_store import DuckDBStore

            store = DuckDBStore().connect()
            owned = True
        except Exception:
            store = None
    if store is not None:
        try:
            from equitylens.companies.registry import CompanyRegistry, CompanyRegistryError

            security = CompanyRegistry(store).resolve(ticker, security_id)
            row = store.query_one(
                "SELECT legal_name, fiscal_year_end FROM company WHERE company_id=?",
                [security.company_id],
            )
            return Company(
                ticker=security.ticker,
                cik=security.company_id,
                name=row["legal_name"],
                exchange=security.exchange,
                fiscal_year_end=row.get("fiscal_year_end"),
                security_id=security.security_id,
            )
        except CompanyRegistryError:
            if security_id is not None or ticker not in SUPPORTED:
                raise
        except Exception:
            if security_id is not None or ticker not in SUPPORTED:
                raise KeyError(f"Company {ticker!r} is not registered")
        finally:
            if owned:
                store.close()
    if ticker not in SUPPORTED:
        raise KeyError(f"Company {ticker!r} is not registered")
    return SUPPORTED[ticker]


def ticker_lookup_from_registry() -> dict[str, str]:
    """ticker -> CIK from the official SEC company_tickers registry (raw snapshot)."""
    path = RAW_DIR / "sec" / "_registry" / "company_tickers.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return {v["ticker"]: f"{v['cik_str']:010d}" for v in data.values()}
