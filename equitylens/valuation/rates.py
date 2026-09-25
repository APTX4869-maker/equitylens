"""Risk-free rate adapter (M5).

Preferred source: US Treasury daily yield curve (Tier C). The Treasury host is
not reliably reachable from this network, so the adapter falls back to the
documented config value (config/valuation/wacc_defaults.yaml). Every returned
rate carries a date + source label.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import yaml

from equitylens.config import CONFIG_DIR, user_agent

TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                "pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value=all")
DEFAULT_TIMEOUT = 4.0  # the Treasury host is often unreachable; fail fast to config

_CACHE: dict = {"t": 0.0, "value": None}
_CACHE_TTL = 600.0  # seconds


def _cached_or(fn):
    import time

    now = time.monotonic()
    if now - _CACHE["t"] < _CACHE_TTL:
        return _CACHE["value"]  # cache the decision (incl. failure) for the TTL
    result = fn()
    _CACHE["t"] = now
    _CACHE["value"] = result
    return result


def fetch_treasury_10y(timeout: float = DEFAULT_TIMEOUT) -> dict | None:
    """Latest 10Y constant maturity from the Treasury daily XML feed."""
    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": user_agent()}) as client:
            r = client.get(TREASURY_URL)
            r.raise_for_status()
    except httpx.HTTPError:
        return None
    text = r.text
    # rows look like: <entry>... <m:properties> <d:NEW_DATE>2026-08-25</...> <d:BC_10YEAR>4.21</...>
    import re
    dates = re.findall(r"NEW_DATE>(\d{4}-\d{2}-\d{2})<", text)
    tens = re.findall(r"BC_10YEAR>([\d.]+)<", text)
    if not dates or not tens:
        return None
    # last row is the most recent
    return {"value": float(tens[-1]) / 100.0, "as_of": dates[-1],
            "source": "US Treasury daily yield curve (BC_10YEAR)",
            "source_url": TREASURY_URL}


def risk_free_rate() -> dict:
    """Best available risk-free rate with full provenance (cached 10 min)."""
    live = _cached_or(lambda: fetch_treasury_10y())
    if live:
        return live
    cfg = yaml.safe_load(Path(CONFIG_DIR / "valuation" / "wacc_defaults.yaml").read_text())
    fallback = cfg["risk_free_rate"]
    return {"value": fallback["value"], "as_of": fallback.get("as_of"),
            "source": fallback.get("source", "documented config fallback"),
            "source_url": fallback.get("source_url")}
