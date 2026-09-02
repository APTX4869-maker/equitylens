"""Golden tests for M6 management data — vs official DEF 14A / Form 4 filings.

Fixtures: reduced proxy statements + raw Form 4 XML under tests/fixtures/sec/.
"""

from __future__ import annotations

import pytest


def _proxy(store, ticker: str) -> dict:
    cik = "0000320193" if ticker == "AAPL" else "0000789019"
    return store


def test_aapl_neo_compensation_matches_proxy(company_db):
    """Summary Compensation Table values (AAPL FY2025 proxy)."""
    rows = company_db.query(
        """SELECT e.name, c.fiscal_year, c.salary, c.total_compensation
           FROM executive_compensation c JOIN executive e ON e.executive_id = c.executive_id
           WHERE c.company_id = '0000320193' AND e.name = 'Tim Cook' AND c.fiscal_year = 2025"""
    )
    assert rows
    r = rows[0]
    assert float(r["salary"]) == pytest.approx(3_000_000, rel=1e-9)
    assert float(r["total_compensation"]) == pytest.approx(74_294_811, rel=1e-9)


def test_msft_neo_compensation_matches_proxy(company_db):
    rows = company_db.query(
        """SELECT e.name, c.fiscal_year, c.salary, c.total_compensation
           FROM executive_compensation c JOIN executive e ON e.executive_id = c.executive_id
           WHERE c.company_id = '0000789019' AND e.name = 'Satya Nadella' AND c.fiscal_year = 2025"""
    )
    assert rows
    r = rows[0]
    assert float(r["salary"]) == pytest.approx(2_500_000, rel=1e-9)
    assert float(r["total_compensation"]) == pytest.approx(96_496_790, rel=1e-9)


def test_aapl_ceo_title(company_db):
    rows = company_db.query(
        "SELECT title FROM executive WHERE company_id = '0000320193' AND name = 'Tim Cook'"
    )
    assert rows and "Chief Executive Officer" in (rows[0]["title"] or "")


def test_board_sizes_and_director_since(company_db):
    n_aapl = company_db.query_one(
        "SELECT count(*) n FROM board_member WHERE company_id = '0000320193'"
    )["n"]
    assert n_aapl == 9
    n_msft = company_db.query_one(
        "SELECT count(*) n FROM board_member WHERE company_id = '0000789019'"
    )["n"]
    assert n_msft == 12
    levinson = company_db.query_one(
        "SELECT director_since, age FROM board_member WHERE company_id = '0000320193' AND name LIKE 'Art Levinson%'"
    )
    assert levinson and (levinson["director_since"] or "").startswith("2000")
    assert levinson["age"] == 75


def test_form4_transactions_parsed(company_db):
    """Form 4 samples: sale with shares/price/ownership-after."""
    rows = company_db.query(
        "SELECT insider_name, transaction_code, shares, price_per_share, shares_owned_after "
        "FROM insider_transaction WHERE company_id = '0000320193'"
    )
    assert rows
    sale = next(r for r in rows if r["transaction_code"] == "S")
    assert float(sale["shares"]) == pytest.approx(1439, rel=1e-9)
    assert float(sale["price_per_share"]) == pytest.approx(310.95, rel=1e-9)
    assert float(sale["shares_owned_after"]) == pytest.approx(37229, rel=1e-9)


def test_msft_form4_parsed(company_db):
    rows = company_db.query(
        "SELECT insider_name, transaction_code, shares FROM insider_transaction "
        "WHERE company_id = '0000789019'"
    )
    assert rows
    assert rows[0]["insider_name"] == "Coleman Amy"
    assert rows[0]["transaction_code"] == "F"


def test_capital_allocation_aapl_buybacks(company_db):
    """AAPL FY2025: gross buybacks minus SBC = net buybacks (from canonical facts)."""
    from equitylens.domain.management_score import capital_allocation

    alloc = capital_allocation(company_db, "0000320193")
    latest = alloc["latest"]
    assert latest is not None
    assert float(latest["gross_buybacks"]) == pytest.approx(90_711_000_000, rel=1e-9)
    assert float(latest["net_buybacks"]) == pytest.approx(
        float(latest["gross_buybacks"]) - float(latest["sbc"]), rel=1e-9
    )
    assert alloc["summary"]["share_count_5y_change"] < 0  # Apple reduced shares ~11%


def test_scorecard_coverage_gating(company_db):
    """Overall management score must be unavailable below 70% evidence coverage."""
    from equitylens.domain.management_score import management_scorecard

    sc = management_scorecard(company_db, "0000320193", "AAPL")
    assert sc["overall_score"] is None
    assert sc["coverage"] < sc["minimum_coverage"]
    # capital allocation dimension IS scorable deterministically
    cap = next(d for d in sc["dimensions"] if d["key"] == "capital_allocation")
    assert cap["score"] is not None and cap["scorable"] is True
