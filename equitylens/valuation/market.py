"""Market-data provider abstraction (M5).

V0.1 has NO real provider configured (per the approved plan): every quote
endpoint returns a documented UNAVAILABLE state instead of faking prices.
A provider must declare license/storage constraints; dev-only adapters must
be visibly marked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

UNAVAILABLE_REASON = "market-data provider not configured (V0.1); configure in config/sources.yaml"


@dataclass
class Quote:
    ticker: str
    price: float
    currency: str = "USD"
    provider: str = ""
    observed_at: str = ""
    stale: bool = False
    adjusted: bool = False
    source_label: str = ""

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker, "price": self.price, "currency": self.currency,
            "provider": self.provider, "observed_at": self.observed_at,
            "stale": self.stale, "adjusted": self.adjusted, "source_label": self.source_label,
        }


class MarketDataProvider(Protocol):
    name: str
    license_notes: str
    def quote(self, ticker: str) -> Quote: ...
    def price_history(self, ticker: str, lookback: int = 256) -> list[dict]: ...


class MarketDataRegistry:
    """Providers register here; V0.1 ships with none configured."""

    def __init__(self):
        self._providers: dict[str, MarketDataProvider] = {}

    def register(self, provider: MarketDataProvider) -> None:
        self._providers[provider.name] = provider

    def names(self) -> list[str]:
        return list(self._providers.keys())

    def get(self, name: str | None = None) -> MarketDataProvider | None:
        if not self._providers:
            return None
        if name is None:
            return next(iter(self._providers.values()))
        return self._providers.get(name)


registry = MarketDataRegistry()


def market_status() -> dict:
    """Explicit state for the UI: nothing is silently faked."""
    if registry.names():
        return {"configured": True, "providers": registry.names()}
    return {"configured": False, "providers": [], "reason": UNAVAILABLE_REASON}
