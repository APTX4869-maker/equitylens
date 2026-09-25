"""Golden tests: market quote chain (M8) — real captured provider payloads.

The market_quote rows in company_db are parsed from verbatim provider
responses stored in tests/fixtures/market/. Derived values are deterministic
formulas over stored facts; missing data is an explicit state.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from equitylens.domain.companies import get_company
from equitylens.market.service import quote_block, valuation_market_block
from equitylens.metrics.engine import MetricEngine
from equitylens.storage.duckdb_store import DuckDBStore
from equitylens.valuation.service import default_valuation

AAPL_CIK = get_company("AAPL").cik
MSFT_CIK = get_company("MSFT").cik
_FX = Path(__file__).parent.parent / "fixtures" / "market"


class _FixtureClock(datetime):
    @classmethod
    def now(cls, tz=None):
        captured_at = cls(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
        return captured_at if tz is None else captured_at.astimezone(tz)


@pytest.fixture(autouse=True)
def _fix_quote_age_clock(monkeypatch):
    """Captured quotes stay fresh for golden parsing/derivation assertions."""
    import equitylens.market.age as market_age

    monkeypatch.setattr(market_age, "datetime", _FixtureClock)


def _seed_quote(db, company_id: str, quote_id: str) -> None:
    from datetime import datetime, timezone

    db.insert_market_quote({
        "quote_id": quote_id,
        "company_id": company_id,
        "ticker": "TEST",
        "provider": "nasdaq",
        "observed_at": "Sep 3, 2026 9:58 AM ET",
        "price": 10.0,
        "currency": "USD",
        "market_cap": 1000.0,
        "name": "Test Inc.",
        "source_label": "Nasdaq",
        "source_url": "https://example.test/quote",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    })


def _seed_quarter(db, company_id: str, metric: str, fy: int, q: int,
                  value: float, *, unit: str = "USD") -> None:
    db.connect()
    db._conn.execute(
        """INSERT INTO canonical_fact
           (canonical_fact_id, company_id, canonical_metric, period_type, fiscal_year,
            fiscal_quarter, period_start, period_end, instant_date, value, unit, status,
            mapping_rule_id, mapping_version, source_raw_fact_ids, as_known_at, created_at, warnings_json)
           VALUES (?,?,?,'Q_STANDALONE',?,?,NULL,NULL,NULL,?,?,'NORMALIZED',
                   ?,'canonical-mappings.v2','[]','2026-01-01','2026-01-01 00:00:00','[]')""",
        [f"{company_id}-{metric}-{fy}-{q}", company_id, metric, fy, q, value, unit,
         f"{metric.lower()}.usgaap.v2"],
    )


def _nasdaq_expected() -> dict:
    """Values in the captured fixture payloads (verbatim, may drift on recapture)."""
    info = json.loads((_FX / "nasdaq" / "aapl_info.json").read_text())
    summary = json.loads((_FX / "nasdaq" / "aapl_summary.json").read_text())
    p = info["data"]["primaryData"]
    s = summary["data"]["summaryData"]
    return {
        "price": float(p["lastSalePrice"].replace("$", "")),
        "observed_at": p["lastTradeTimestamp"],
        "market_cap": float(s["MarketCap"]["value"].replace(",", "")),
        "prev_close": float(s["PreviousClose"]["value"].replace("$", "")),
    }


def test_market_quote_block_real_captured_values(company_db):
    exp = _nasdaq_expected()
    block = quote_block(company_db, AAPL_CIK, "AAPL")
    assert block["status"] == "OK"
    q = block["quote"]
    assert q["price"] == pytest.approx(exp["price"])
    assert q["observed_at"] == exp["observed_at"]
    assert q["provider"] == "nasdaq"
    assert q["source_url"].startswith("https://api.nasdaq.com")
    assert block["derived"]["market_cap"] == pytest.approx(exp["market_cap"])


def test_pe_ttm_is_deterministic_marketcap_over_ni(company_db):
    block = quote_block(company_db, AAPL_CIK, "AAPL")
    mcap = block["derived"]["market_cap"]
    ni_pts = [p for p in MetricEngine(company_db).compute("NET_INCOME", AAPL_CIK, frequency="ttm") if p.value]
    assert ni_pts, "TTM net income facts missing in golden db"
    expected_pe = round(mcap / float(ni_pts[-1].value), 2)
    assert block["derived"]["pe_ttm"] == expected_pe
    assert block["derived"]["pe_ttm_formula"] == "pe_ttm.v1"
    assert block["derived"]["pe_ttm_evidence"]["market_cap_source"].startswith("market_quote:")
    assert block["derived"]["pe_ttm_evidence"]["ni_ttm_evidence_ids"], "NI TTM evidence ids must be recorded"


def test_msft_tencent_quote_synced(company_db):
    block = quote_block(company_db, MSFT_CIK, "MSFT")
    assert block["status"] == "OK"
    assert block["quote"]["provider"] == "tencent"
    assert block["quote"]["price"] > 0
    assert block["quote"]["observed_at"]  # provider-reported time is never blank


def test_valuation_default_embeds_price_vs_fair(company_db):
    d = default_valuation(company_db, AAPL_CIK, "AAPL")
    market = d["market"]
    assert market["status"] == "OK"
    fair = d["result"]["fair_value_per_share"]
    exp = round((market["quote"]["price"] / fair - 1.0) * 100.0, 2)
    assert market["derived"]["price_vs_fair_pct"] == exp
    assert market["derived"]["price_vs_fair_formula"] == "price_vs_fair.v1"


def test_cross_check_multiples_pe_pfcf_fcf_yield(db):
    """P07: market cap 1000, NI TTM 100, FCF TTM 50 -> P/E 10x, P/FCF 20x,
    FCF yield 5%."""
    from datetime import datetime, timezone

    from equitylens.market.service import quote_block

    now = datetime.now(timezone.utc).isoformat()
    db.insert_market_quote({
        "quote_id": "mq_x1", "company_id": AAPL_CIK, "ticker": "AAPL",
        "provider": "nasdaq", "observed_at": "Sep 3, 2026 9:58 AM ET",
        "price": 10.0, "currency": "USD", "market_cap": 1000.0,
        "name": "Apple Inc.", "source_label": "Nasdaq", "source_url": "https://x",
        "fetched_at": now,
    })

    def seed(metric: str, q: int, value: float):
        db.connect()
        db._conn.execute(
            """INSERT INTO canonical_fact
               (canonical_fact_id, company_id, canonical_metric, period_type, fiscal_year,
                fiscal_quarter, period_start, period_end, instant_date, value, unit, status,
                mapping_rule_id, mapping_version, source_raw_fact_ids, as_known_at, created_at, warnings_json)
               VALUES (?,?,?,'Q_STANDALONE',2025,?,NULL,NULL,NULL,?,'USD','NORMALIZED',
                       ?,'canonical-mappings.v2','[]','2026-01-01','2026-01-01 00:00:00','[]')""",
            [f"{metric}-{q}", AAPL_CIK, metric, q, value, f"{metric.lower()}.usgaap.v2"],
        )

    for q in range(1, 5):
        seed("NET_INCOME", q, 25.0)          # TTM 100
        seed("OPERATING_CASH_FLOW", q, 25.0)  # TTM 100
        seed("CAPITAL_EXPENDITURES", q, 12.5)  # TTM 50 -> FCF TTM 50

    block = quote_block(db, AAPL_CIK, "AAPL")
    d = block["derived"]
    assert d["pe_ttm"] == pytest.approx(10.0)
    assert d["pfcf_ttm"] == pytest.approx(20.0)
    assert d["fcf_yield_ttm"] == pytest.approx(0.05)


def test_cross_check_negative_earnings_are_na(db):
    """P07: negative TTM earnings -> P/E is N/A, not a 'cheap' negative."""
    from datetime import datetime, timezone

    from equitylens.market.service import quote_block

    now = datetime.now(timezone.utc).isoformat()
    db.insert_market_quote({
        "quote_id": "mq_x2", "company_id": AAPL_CIK, "ticker": "AAPL",
        "provider": "nasdaq", "observed_at": "Sep 3, 2026 9:58 AM ET",
        "price": 10.0, "currency": "USD", "market_cap": 1000.0,
        "source_label": "Nasdaq", "source_url": "https://x", "fetched_at": now,
    })
    db.connect()
    for q in range(1, 5):
        db._conn.execute(
            """INSERT INTO canonical_fact
               (canonical_fact_id, company_id, canonical_metric, period_type, fiscal_year,
                fiscal_quarter, period_start, period_end, instant_date, value, unit, status,
                mapping_rule_id, mapping_version, source_raw_fact_ids, as_known_at, created_at, warnings_json)
               VALUES (?,?,?,'Q_STANDALONE',2025,?,NULL,NULL,NULL,?,'USD','NORMALIZED',
                       ?,'canonical-mappings.v2','[]','2026-01-01','2026-01-01 00:00:00','[]')""",
            [f"NI-neg-{q}", AAPL_CIK, "NET_INCOME", q, -10.0, "net_income.usgaap.v2"],
        )
    block = quote_block(db, AAPL_CIK, "AAPL")
    assert block["derived"].get("pe_ttm") is None
    assert "不适用" in block["derived"].get("pe_ttm_reason", "")


def test_market_multiples_do_not_fall_back_when_current_ttm_is_zero(db):
    """D06/P07: latest zero TTM must not expose an older normal multiple."""
    cid = "MARKET_ZERO"
    _seed_quote(db, cid, "mq-zero")
    periods = [(2025, 1), (2025, 2), (2025, 3), (2025, 4), (2026, 1)]
    for index, (fy, q) in enumerate(periods):
        _seed_quarter(db, cid, "NET_INCOME", fy, q, -75.0 if index == 4 else 25.0)
        _seed_quarter(db, cid, "OPERATING_CASH_FLOW", fy, q, -40.0 if index == 4 else 20.0)
        _seed_quarter(db, cid, "CAPITAL_EXPENDITURES", fy, q, 5.0)

    derived = quote_block(db, cid, "TEST")["derived"]

    assert derived["pe_ttm"] is None
    assert derived["pe_ttm_status"] == "UNSUPPORTED"
    assert derived["pfcf_ttm"] is None
    assert derived["fcf_yield_ttm"] is None
    assert derived["pfcf_ttm_status"] == "UNSUPPORTED"


def test_market_multiples_do_not_use_old_window_when_latest_is_incomplete(db):
    """D06/P07: a complete old window cannot stand in for a current gap."""
    cid = "MARKET_GAP"
    _seed_quote(db, cid, "mq-gap")
    for q in range(1, 5):
        _seed_quarter(db, cid, "NET_INCOME", 2025, q, 25.0)
        _seed_quarter(db, cid, "OPERATING_CASH_FLOW", 2025, q, 20.0)
        _seed_quarter(db, cid, "CAPITAL_EXPENDITURES", 2025, q, 5.0)
    _seed_quarter(db, cid, "NET_INCOME", 2026, 2, 30.0)
    _seed_quarter(db, cid, "OPERATING_CASH_FLOW", 2026, 2, 22.0)
    _seed_quarter(db, cid, "CAPITAL_EXPENDITURES", 2026, 2, 6.0)

    derived = quote_block(db, cid, "TEST")["derived"]

    assert derived["pe_ttm"] is None
    assert derived["pe_ttm_status"] == "INCOMPLETE_PERIOD"
    assert "FY2026Q1" in derived["pe_ttm_reason"]
    assert derived["pfcf_ttm"] is None
    assert derived["pfcf_ttm_status"] == "INCOMPLETE_PERIOD"


def test_no_quote_is_explicit_unavailable_not_a_price(db: DuckDBStore):
    block = quote_block(db, AAPL_CIK, "AAPL")
    assert block["status"] == "UNAVAILABLE"
    assert block["synced"] is False
    assert "sync-quotes" in block["reason"]
    vblock = valuation_market_block(db, AAPL_CIK, "AAPL", fair_value_per_share=100.0)
    assert vblock["status"] == "UNAVAILABLE"
    assert "derived" not in vblock or "price_vs_fair_pct" not in vblock.get("derived", {})
