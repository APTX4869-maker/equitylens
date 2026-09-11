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


def get_company(ticker: str) -> Company:
    ticker = ticker.strip().upper()
    if ticker not in SUPPORTED:
        raise KeyError(f"Company {ticker!r} is not in the supported set (V0.x: AAPL, MSFT)")
    return SUPPORTED[ticker]


def ticker_lookup_from_registry() -> dict[str, str]:
    """ticker -> CIK from the official SEC company_tickers registry (raw snapshot)."""
    path = RAW_DIR / "sec" / "_registry" / "company_tickers.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return {v["ticker"]: f"{v['cik_str']:010d}" for v in data.values()}
