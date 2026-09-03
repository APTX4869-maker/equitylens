"""Golden tests: market quote chain (M8) — real captured provider payloads.

The market_quote rows in company_db are parsed from verbatim provider
responses stored in tests/fixtures/market/. Derived values are deterministic
formulas over stored facts; missing data is an explicit state.
"""

from __future__ import annotations

import json
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


def test_no_quote_is_explicit_unavailable_not_a_price(db: DuckDBStore):
    block = quote_block(db, AAPL_CIK, "AAPL")
    assert block["status"] == "UNAVAILABLE"
    assert block["synced"] is False
    assert "sync-quotes" in block["reason"]
    vblock = valuation_market_block(db, AAPL_CIK, "AAPL", fair_value_per_share=100.0)
    assert vblock["status"] == "UNAVAILABLE"
    assert "derived" not in vblock or "price_vs_fair_pct" not in vblock.get("derived", {})
