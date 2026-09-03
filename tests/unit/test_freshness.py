"""Unit tests: data freshness service (M8.6) — per-module honest as-of."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from equitylens.domain.companies import get_company
from equitylens.domain.freshness import freshness

AAPL_CIK = get_company("AAPL").cik


def test_empty_db_reports_missing_with_commands(db):
    d = freshness(db, AAPL_CIK, "AAPL")
    keys = [m["key"] for m in d["modules"]]
    assert {"sec_financials", "segments", "management", "market_quote", "valuation_runs"} <= set(keys)
    assert d["stale_modules"], "empty db must be flagged stale/missing"
    assert d["hint"] and "sync" in d["hint"]


def test_market_quote_freshness_ok_and_stale(db):
    now = datetime.now(timezone.utc)
    # old quote only -> stale
    db.insert_market_quote({
        "quote_id": "mq_old1", "company_id": AAPL_CIK, "ticker": "AAPL",
        "provider": "nasdaq", "observed_at": "2026-01-01 10:00 AM ET", "price": 300.0,
        "currency": "USD", "source_label": "Nasdaq", "source_url": "https://x",
        "fetched_at": (now - timedelta(days=400)).isoformat(),
    })
    d = freshness(db, AAPL_CIK, "AAPL")
    mkt = next(m for m in d["modules"] if m["key"] == "market_quote")
    assert mkt["status"] == "stale"
    assert mkt["days_ago"] >= 365

    # then a recent quote -> ok (latest wins)
    db.insert_market_quote({
        "quote_id": "mq_fresh1", "company_id": AAPL_CIK, "ticker": "AAPL",
        "provider": "nasdaq", "observed_at": "2026-09-03 10:00 AM ET", "price": 326.0,
        "currency": "USD", "market_cap": 1e12, "name": "Apple Inc.",
        "source_label": "Nasdaq", "source_url": "https://x",
        "fetched_at": now.isoformat(),
    })
    d2 = freshness(db, AAPL_CIK, "AAPL")
    mkt2 = next(m for m in d2["modules"] if m["key"] == "market_quote")
    assert mkt2["status"] == "ok"
