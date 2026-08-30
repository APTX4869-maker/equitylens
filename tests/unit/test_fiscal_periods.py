"""Unit tests for the fiscal-period resolver."""

from __future__ import annotations

from datetime import date

import pytest

from equitylens.normalization.fiscal_periods import FiscalCalendar, derive_standalone_quarters


def make_calendar() -> FiscalCalendar:
    # MSFT-like fiscal calendar: FY ends 06-30
    return FiscalCalendar(
        year_ends={2024: date(2024, 6, 30), 2025: date(2025, 6, 30), 2026: date(2026, 6, 30)},
        quarter_ends={
            2024: [date(2023, 9, 30), date(2023, 12, 31), date(2024, 3, 31)],
            2025: [date(2024, 9, 30), date(2024, 12, 31), date(2025, 3, 31)],
            2026: [date(2025, 9, 30), date(2025, 12, 31), date(2026, 3, 31)],
        },
        fallback_mm_dd="06-30",
    )


def test_duration_period_classification():
    cal = make_calendar()
    # standalone quarter ending exactly on q1 end belongs to Q1 (strict boundary)
    p = cal.resolve_duration("2024-07-01", "2024-09-30")
    assert p.period_type == "Q_STANDALONE" and p.fiscal_quarter == 1 and p.fiscal_year == 2025
    # H1 YTD
    p = cal.resolve_duration("2024-07-01", "2024-12-31")
    assert p.period_type == "YTD_6M" and p.fiscal_quarter == 2 and p.fiscal_year == 2025
    # 9M YTD
    p = cal.resolve_duration("2024-07-01", "2025-03-31")
    assert p.period_type == "YTD_9M" and p.fiscal_quarter == 3 and p.fiscal_year == 2025
    # full year
    p = cal.resolve_duration("2024-07-01", "2025-06-30")
    assert p.period_type == "FY" and p.fiscal_quarter is None and p.fiscal_year == 2025


def test_instant_period():
    cal = make_calendar()
    p = cal.resolve_instant("2024-09-30")
    assert p.period_type == "INSTANT" and p.fiscal_year == 2025 and p.fiscal_quarter == 1
    p = cal.resolve_instant("2025-06-30")
    assert p.fiscal_year == 2025 and p.fiscal_quarter == 4


def test_fp_hint_mismatch_warns_but_keeps_date_derived():
    cal = make_calendar()
    p = cal.resolve_duration("2024-07-01", "2024-09-30", fp_hint="Q2")
    assert p.fiscal_quarter == 1  # date-derived wins
    assert any("fp hint" in w for w in p.warnings)


def test_in_progress_fiscal_year_uses_heuristic():
    # no 10-K for FY2026 yet: year end estimated from fallback MM-DD
    cal = FiscalCalendar(
        year_ends={2024: date(2024, 6, 30), 2025: date(2025, 6, 30)},
        quarter_ends={},
        fallback_mm_dd="06-30",
    )
    p = cal.resolve_duration("2025-07-01", "2025-12-31")
    assert p.fiscal_year == 2026 and p.period_type == "YTD_6M"


def test_derive_standalone_quarters_fills_gaps_only():
    cal = make_calendar()
    q1_end = "2024-09-30"
    q2_end = "2024-12-31"
    q3_end = "2025-03-31"
    facts = [
        {"canonical_fact_id": "a", "canonical_metric": "OCF", "period_type": "Q_STANDALONE",
         "fiscal_quarter": 1, "period_end": q1_end, "value": 100.0, "unit": "USD", "as_known_at": "2024-10-30"},
        {"canonical_fact_id": "b", "canonical_metric": "OCF", "period_type": "YTD_6M",
         "fiscal_quarter": 2, "period_end": q2_end, "value": 250.0, "unit": "USD", "as_known_at": "2025-01-29"},
        {"canonical_fact_id": "c", "canonical_metric": "OCF", "period_type": "YTD_9M",
         "fiscal_quarter": 3, "period_end": q3_end, "value": 400.0, "unit": "USD", "as_known_at": "2025-04-29"},
        {"canonical_fact_id": "d", "canonical_metric": "OCF", "period_type": "FY",
         "fiscal_quarter": None, "period_end": "2025-06-30", "value": 550.0, "unit": "USD", "as_known_at": "2025-07-29"},
    ]
    derived = derive_standalone_quarters(facts, 2025, cal)
    by_q = {d["fiscal_quarter"]: d for d in derived}
    # Q1 already reported -> untouched
    assert 1 not in by_q
    assert by_q[2]["value"] == pytest.approx(150.0)  # 250 - 100
    assert by_q[3]["value"] == pytest.approx(150.0)  # 400 - 250
    assert by_q[4]["value"] == pytest.approx(150.0)  # 550 - 400
    assert all(d["status"] == "CALCULATED" for d in derived)


def test_derive_does_not_guess_missing_buckets():
    cal = make_calendar()
    facts = [
        {"canonical_fact_id": "a", "canonical_metric": "OCF", "period_type": "Q_STANDALONE",
         "fiscal_quarter": 1, "period_end": "2024-09-30", "value": 100.0, "unit": "USD", "as_known_at": "2024-10-30"},
        # no YTD-6M: Q2 cannot be derived and must be absent, never guessed
        {"canonical_fact_id": "c", "canonical_metric": "OCF", "period_type": "YTD_9M",
         "fiscal_quarter": 3, "period_end": "2025-03-31", "value": 400.0, "unit": "USD", "as_known_at": "2025-04-29"},
    ]
    derived = derive_standalone_quarters(facts, 2025, cal)
    assert all(d["fiscal_quarter"] != 2 for d in derived)
