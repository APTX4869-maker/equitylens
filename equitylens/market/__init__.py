"""Real-time market quote sync + deterministic derived multiples (M8).

Quotes are external facts, not SEC facts. Discipline mirrors the SEC chain:

  provider HTTP → raw snapshot (SHA-256, data/raw/market/) → market_quote row
  (provider / observed_at / source_url) → deterministic derivations
  (market cap, P/E TTM, price-to-fair-value) with formula ids → API → UI.

A missing sync is an explicit UNAVAILABLE state, never a guessed price.
The legacy protocol/registry types in equitylens.valuation.market are kept
for compatibility but the live API path uses this package (quote rows come
from the DuckDB store, which is filled by `equitylens sync-quotes`).
"""
