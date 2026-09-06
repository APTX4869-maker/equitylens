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


def test_market_quote_replay_uses_observation_time(db):
    """D10: a 30-day-old quote replayed today is still stale — staleness is
    judged from observed_at (observation), not fetched_at (fetch/replay)."""
    now = datetime.now(timezone.utc)
    old_obs = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    db.insert_market_quote({
        "quote_id": "mq_replay1", "company_id": AAPL_CIK, "ticker": "AAPL",
        "provider": "nasdaq", "observed_at": old_obs, "price": 300.0,
        "currency": "USD", "source_label": "Nasdaq", "source_url": "https://x",
        "fetched_at": now.isoformat(),  # replayed "today"
    })
    d = freshness(db, AAPL_CIK, "AAPL")
    mkt = next(m for m in d["modules"] if m["key"] == "market_quote")
    assert mkt["status"] == "stale"
    assert mkt["days_ago"] >= 29


def test_new_form4_does_not_refresh_old_proxy(db):
    """D10: a recent Form 4 must not make an old annual proxy look fresh."""
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=400)).isoformat()

    def seed_doc(doc_id, form_type, filed_at):
        db.upsert_source_documents([{
            "source_document_id": doc_id, "company_id": AAPL_CIK,
            "provider": "SEC", "document_type": "FILING_DOCUMENT",
            "form_type": form_type, "filed_at": filed_at,
            "source_url": "https://x", "fetched_at": "2020-01-01T00:00:00",
            "content_sha256": doc_id.ljust(64, "0")[:64],
        }])

    seed_doc("doc_proxy_old", "DEF 14A", old)
    seed_doc("doc_f4_new", "4", now.isoformat())
    d = freshness(db, AAPL_CIK, "AAPL")
    mgmt = next(m for m in d["modules"] if m["key"] == "management")
    assert mgmt["status"] == "stale"
    assert "Form 4" in mgmt["detail"]


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
