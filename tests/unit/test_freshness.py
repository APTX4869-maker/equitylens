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


def test_ingest_today_does_not_refresh_old_filing(db):
    """D10: a 10-K disclosed 2020-01-01 must stay old even when ingested today —
    SEC financial age is the disclosure date, never the ingestion completion."""
    now = datetime.now(timezone.utc)
    db.upsert_source_documents([{
        "source_document_id": "doc_old_10k", "company_id": AAPL_CIK,
        "provider": "SEC", "document_type": "FILING_DOCUMENT",
        "form_type": "10-K", "filed_at": "2020-01-01T00:00:00",
        "source_url": "https://x", "fetched_at": "2020-01-01T00:00:00",
        "content_sha256": "a" * 64,
    }])
    db.insert_ingestion_run({
        "run_id": "run_today", "company_id": AAPL_CIK, "provider": "SEC",
        "command": "sync", "started_at": now.isoformat(),
        "finished_at": now.isoformat(), "status": "ok",
    })
    d = freshness(db, AAPL_CIK, "AAPL")
    sec = next(m for m in d["modules"] if m["key"] == "sec_financials")
    assert sec["status"] == "stale"
    assert sec["days_ago"] is not None and sec["days_ago"] >= 2000  # ~2020 -> now


def test_published_facts_supply_disclosure_date_for_older_dataset_envelopes(db):
    """Early immutable datasets omitted filed_at from source-document payloads."""
    result = freshness(
        db,
        AAPL_CIK,
        "AAPL",
        source_documents=[{
            "source_document_id": "published-10q",
            "document_type": "FILING_DOCUMENT",
            "form_type": "10-Q",
            "fetched_at": "2026-09-19T00:00:00+00:00",
        }],
        canonical_facts=[{
            "canonical_fact_id": "published-revenue",
            "source_document_id": "published-10q",
            "as_known_at": "2026-08-27",
        }],
    )

    financials = next(
        module for module in result["modules"] if module["key"] == "sec_financials"
    )
    assert financials["as_of"] == "2026-08-27"
    assert financials["status"] == "ok"
    segments = next(module for module in result["modules"] if module["key"] == "segments")
    assert segments["as_of"] == "2026-08-27"


def test_quote_block_marks_stale_observation(db):
    """D10: the quote-comparison block reports the same status as freshness — a
    stale quote is STALE (not OK) yet remains viewable with its price/date."""
    from equitylens.market.service import quote_block

    now = datetime.now(timezone.utc)
    old_obs = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    db.insert_market_quote({
        "quote_id": "mq_stale_blk", "company_id": AAPL_CIK, "ticker": "AAPL",
        "provider": "nasdaq", "observed_at": old_obs, "price": 300.0,
        "currency": "USD", "market_cap": 3e12, "name": "Apple Inc.",
        "source_label": "Nasdaq", "source_url": "https://x",
        "fetched_at": now.isoformat(),
    })
    block = quote_block(db, AAPL_CIK, "AAPL")
    assert block["status"] == "STALE"
    assert block["quote"]["price"] == 300.0
    assert block["quote"]["observed_at"]


def test_replay_keeps_original_fetch_time_from_name():
    """D10: replay parses the original fetch time from the snapshot filename."""
    from equitylens.market.service import _fetch_time_from_snapshot_name

    ts = _fetch_time_from_snapshot_name("nasdaq_20260903T140349Z.json")
    assert ts.startswith("2026-09-03T14:03:49")
    assert _fetch_time_from_snapshot_name("no_timestamp.json") is None


def test_provider_timezone_is_converted_to_utc():
    """D10: an ET observation is an eastern-market timestamp, not UTC text."""
    from equitylens.market.age import parse_observed_at

    summer = parse_observed_at("Sep 3, 2026 9:58 AM ET")
    winter = parse_observed_at("Jan 3, 2026 9:58 AM ET")

    assert summer is not None and summer.isoformat() == "2026-09-03T13:58:00+00:00"
    assert winter is not None and winter.isoformat() == "2026-01-03T14:58:00+00:00"


def test_market_quote_freshness_ok_and_stale(db):
    now = datetime.now(timezone.utc)
    # old observation (400 days ago) only -> stale, judged by observed_at
    old_obs = (now - timedelta(days=400)).strftime("%Y-%m-%d %H:%M:%S")
    db.insert_market_quote({
        "quote_id": "mq_old1", "company_id": AAPL_CIK, "ticker": "AAPL",
        "provider": "nasdaq", "observed_at": old_obs, "price": 300.0,
        "currency": "USD", "source_label": "Nasdaq", "source_url": "https://x",
        "fetched_at": (now - timedelta(days=400)).isoformat(),
    })
    d = freshness(db, AAPL_CIK, "AAPL")
    mkt = next(m for m in d["modules"] if m["key"] == "market_quote")
    assert mkt["status"] == "stale"
    assert mkt["days_ago"] >= 365

    # then a recent observation -> ok (latest fetched wins)
    recent_obs = (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    db.insert_market_quote({
        "quote_id": "mq_fresh1", "company_id": AAPL_CIK, "ticker": "AAPL",
        "provider": "nasdaq", "observed_at": recent_obs, "price": 326.0,
        "currency": "USD", "market_cap": 1e12, "name": "Apple Inc.",
        "source_label": "Nasdaq", "source_url": "https://x",
        "fetched_at": now.isoformat(),
    })
    d2 = freshness(db, AAPL_CIK, "AAPL")
    mkt2 = next(m for m in d2["modules"] if m["key"] == "market_quote")
    assert mkt2["status"] == "ok"
