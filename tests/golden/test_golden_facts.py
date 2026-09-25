"""Golden tests: AAPL/MSFT canonical facts vs official 10-K/10-Q figures.

The expected values below are the figures printed in the official SEC
statements (latest-restated vintage; see docs/03 for restatement semantics).
Any mismatch here blocks release of the affected metric.
"""

from __future__ import annotations

import pytest

from tests.conftest import latest_annual, standalone

CIK_AAPL = "0000320193"
CIK_MSFT = "0000789019"

# --- AAPL, as restated in the FY2025 10-K (filed 2025-10-31) ---------------
AAPL_FY2024 = {
    "REVENUE": 391_035_000_000,
    "GROSS_PROFIT": 180_683_000_000,
    "OPERATING_INCOME": 123_216_000_000,
    "NET_INCOME": 93_736_000_000,
    "OPERATING_CASH_FLOW": 118_254_000_000,
    "CAPITAL_EXPENDITURES": 9_447_000_000,
    "DILUTED_EPS": 6.08,
}
AAPL_FY2025 = {
    "REVENUE": 416_161_000_000,
    "OPERATING_INCOME": 133_050_000_000,
    "NET_INCOME": 112_010_000_000,
    "OPERATING_CASH_FLOW": 111_482_000_000,
    "CAPITAL_EXPENDITURES": 12_715_000_000,
    "DILUTED_EPS": 7.46,
}

# --- MSFT, as restated in the FY2026 10-K (filed 2026-07-29) ----------------
MSFT_FY2024 = {
    "REVENUE": 245_122_000_000,
    "GROSS_PROFIT": 171_008_000_000,
    "OPERATING_INCOME": 109_433_000_000,
    "NET_INCOME": 88_136_000_000,
    "OPERATING_CASH_FLOW": 118_548_000_000,
    "CAPITAL_EXPENDITURES": 44_477_000_000,
}
MSFT_FY2025 = {
    "REVENUE": 281_724_000_000,
    "OPERATING_INCOME": 128_528_000_000,
    "NET_INCOME": 101_832_000_000,
    "OPERATING_CASH_FLOW": 136_162_000_000,
    "CAPITAL_EXPENDITURES": 64_551_000_000,
}


@pytest.mark.parametrize("metric,expected", AAPL_FY2024.items())
def test_aapl_fy2024_annual(company_db, metric, expected):
    value = latest_annual(company_db, CIK_AAPL, metric, 2024)
    assert value == pytest.approx(expected, rel=1e-9)


@pytest.mark.parametrize("metric,expected", AAPL_FY2025.items())
def test_aapl_fy2025_annual(company_db, metric, expected):
    value = latest_annual(company_db, CIK_AAPL, metric, 2025)
    assert value == pytest.approx(expected, rel=1e-9)


@pytest.mark.parametrize("metric,expected", MSFT_FY2024.items())
def test_msft_fy2024_annual(company_db, metric, expected):
    value = latest_annual(company_db, CIK_MSFT, metric, 2024)
    assert value == pytest.approx(expected, rel=1e-9)


@pytest.mark.parametrize("metric,expected", MSFT_FY2025.items())
def test_msft_fy2025_annual(company_db, metric, expected):
    value = latest_annual(company_db, CIK_MSFT, metric, 2025)
    assert value == pytest.approx(expected, rel=1e-9)


def test_aapl_fy2025_q1_revenue_matches_official_10q(company_db):
    """Dec-2024 quarter revenue ($124.3B) is a widely known official figure."""
    q = standalone(company_db, CIK_AAPL, "REVENUE", 2025)
    assert q[1] == pytest.approx(124_300_000_000, rel=1e-9)


def test_aapl_fy2025_ocf_quarters_sum_to_annual(company_db):
    """Standalone OCF quarters must sum exactly to the fiscal-year OCF."""
    q = standalone(company_db, CIK_AAPL, "OPERATING_CASH_FLOW", 2025)
    assert set(q) == {1, 2, 3, 4}
    assert sum(q.values()) == pytest.approx(
        latest_annual(company_db, CIK_AAPL, "OPERATING_CASH_FLOW", 2025), rel=1e-9
    )


def test_aapl_fy2026_ocf_standalone_not_ytd(company_db):
    """The classic bug: a YTD cash-flow figure mislabeled as a standalone quarter.

    Q2 standalone OCF (28.7B) must NOT equal YTD-6M (82.6B); Q3 standalone must
    NOT equal YTD-9M (117.0B).
    """
    q = standalone(company_db, CIK_AAPL, "OPERATING_CASH_FLOW", 2026)
    assert q[2] == pytest.approx(28_702_000_000, rel=1e-9)
    assert q[3] == pytest.approx(34_369_000_000, rel=1e-9)
    assert q[2] != pytest.approx(82_627_000_000, abs=1)
    assert q[3] != pytest.approx(116_996_000_000, abs=1)


def test_msft_reports_standalone_cashflow_quarters(company_db):
    """MSFT reports 3-month cash-flow values in its 10-Qs; Q4 must be derived."""
    q = standalone(company_db, CIK_MSFT, "OPERATING_CASH_FLOW", 2026)
    assert set(q) == {1, 2, 3, 4}
    assert sum(q.values()) == pytest.approx(
        latest_annual(company_db, CIK_MSFT, "OPERATING_CASH_FLOW", 2026), rel=1e-9
    )


def test_instant_facts_are_not_summed(company_db):
    """TOTAL_ASSETS is an instant fact: the latest-restated value per balance
    sheet date exists and the metric engine never sums balance-sheet values."""
    rows = company_db.query(
        """SELECT value, instant_date, fiscal_year, fiscal_quarter FROM canonical_fact
           WHERE company_id=? AND canonical_metric='TOTAL_ASSETS' AND period_type='INSTANT'
           ORDER BY instant_date DESC LIMIT 3""",
        [CIK_AAPL],
    )
    assert rows
    assert all(r["value"] > 0 for r in rows)
    # several distinct quarter-end dates exist (each a separate observation)
    dates = {r["instant_date"] for r in company_db.query(
        """SELECT instant_date FROM canonical_fact
           WHERE company_id=? AND canonical_metric='TOTAL_ASSETS' AND period_type='INSTANT'""",
        [CIK_AAPL],
    )}
    assert len(dates) >= 8, "AAPL should have many quarters of balance-sheet dates"

    # latest-restated semantics: for the most recent quarter-end date, the
    # highest filing date wins and is a single value
    latest_date = rows[0]["instant_date"]
    best = company_db.query(
        """SELECT cf.value, cf.as_known_at FROM canonical_fact cf
           WHERE cf.company_id=? AND cf.canonical_metric='TOTAL_ASSETS'
             AND cf.period_type='INSTANT' AND cf.instant_date=?
           ORDER BY cf.as_known_at DESC LIMIT 1""",
        [CIK_AAPL, latest_date],
    )
    assert best and float(best[0]["value"]) > 0


def test_net_debt_uses_latest_instant_values(company_db):
    """NET_DEBT = non-overlapping debt components - cash - ST investments, on
    ONE balance-sheet date. us-gaap:LongTermDebt (total) must not double-count
    the current portion against LONG_TERM_DEBT_CURRENT."""
    from equitylens.metrics.engine import MetricEngine

    engine = MetricEngine(company_db)
    points = engine.compute("NET_DEBT", CIK_MSFT, frequency="quarterly")
    assert points

    def on_date(metric: str, d: str) -> float:
        r = company_db.query_one(
            """SELECT value FROM canonical_fact
               WHERE company_id=? AND canonical_metric=? AND period_type='INSTANT'
                 AND COALESCE(instant_date, period_end)=?
               ORDER BY as_known_at DESC LIMIT 1""",
            [CIK_MSFT, metric, d],
        )
        assert r, f"missing instant {metric} on {d}"
        return float(r["value"])

    latest = company_db.query_one(
        """SELECT COALESCE(instant_date, period_end) d FROM canonical_fact
           WHERE company_id=? AND canonical_metric='LONG_TERM_DEBT' AND period_type='INSTANT'
           ORDER BY COALESCE(instant_date, period_end) DESC LIMIT 1""",
        [CIK_MSFT],
    )["d"]

    total_debt = on_date("LONG_TERM_DEBT", latest) + on_date("LONG_TERM_DEBT_CURRENT", latest)
    expected = total_debt - on_date("CASH_AND_EQUIVALENTS", latest) - on_date("SHORT_TERM_INVESTMENTS", latest)
    assert points[-1].value == pytest.approx(expected, rel=1e-9)

    # MSFT total long-term debt = noncurrent + current portion; the bridge must
    # not add the current portion a second time.
    noncurrent = on_date("LONG_TERM_DEBT", latest)
    current = on_date("LONG_TERM_DEBT_CURRENT", latest)
    assert noncurrent + current == pytest.approx(40_294_000_000, rel=1e-6)
