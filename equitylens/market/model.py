"""Market quote data model (provider-normalized, pre-persistence)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProviderQuote:
    """One normalized quote from one provider.

    observed_at is the provider-reported observation time (raw string, e.g.
    "Sep 3, 2026 9:53 AM ET") — we never reinterpret a foreign timestamp.
    raw_payload is the verbatim provider body kept for the SHA-256 snapshot.
    """

    ticker: str
    provider: str
    price: float
    currency: str = "USD"
    observed_at: str = ""
    name: str = ""
    prev_close: float | None = None
    open_price: float | None = None
    high: float | None = None
    low: float | None = None
    market_cap: float | None = None
    source_label: str = ""
    source_url: str = ""
    raw_payload: dict | None = None

    def to_row(
        self,
        company_id: str,
        snapshot_sha: str | None,
        fetched_at: str,
        security_id: str | None = None,
    ) -> dict:
        from equitylens.storage.raw_store import sha256_bytes

        key = (
            f"{company_id}|{security_id or 'legacy'}|{self.provider}|"
            f"{self.observed_at}|{self.price}"
        )
        return {
            "quote_id": f"mq_{sha256_bytes(key.encode())[:12]}",
            "company_id": company_id,
            "security_id": security_id,
            "ticker": self.ticker,
            "provider": self.provider,
            "observed_at": self.observed_at,
            "price": self.price,
            "currency": self.currency,
            "prev_close": self.prev_close,
            "open_price": self.open_price,
            "high": self.high,
            "low": self.low,
            "market_cap": self.market_cap,
            "name": self.name,
            "source_label": self.source_label,
            "source_url": self.source_url,
            "snapshot_sha": snapshot_sha,
            "fetched_at": fetched_at,
        }


class ProviderError(RuntimeError):
    """A provider could not serve a usable quote (network, parse, missing data)."""
