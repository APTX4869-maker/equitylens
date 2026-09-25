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


@pytest.mark.parametrize(
    ("start", "end", "fiscal_year"),
    [("2024-09-29", "2025-09-27", 2025), ("2023-10-01", "2024-10-05", 2024)],
)
def test_52_and_53_week_fiscal_years_are_full_years(start, end, fiscal_year):
    """D03: retail 52/53-week calendars remain FY duration facts."""
    cal = FiscalCalendar(
        year_ends={2023: date(2023, 9, 30), 2024: date(2024, 10, 5), 2025: date(2025, 9, 27)},
        quarter_ends={},
        fallback_mm_dd=None,
    )
    period = cal.resolve_duration(start, end)
    assert period.period_type == "FY"
    assert period.fiscal_year == fiscal_year


def test_fiscal_year_end_change_uses_reported_calendar_boundaries():
    """D03: a transition year follows reported 10-K ends, not a fixed MM-DD."""
    cal = FiscalCalendar(
        year_ends={2023: date(2023, 9, 30), 2024: date(2024, 9, 28), 2025: date(2025, 12, 27)},
        quarter_ends={2025: [date(2024, 12, 28), date(2025, 3, 29), date(2025, 6, 28)]},
        fallback_mm_dd="09-30",
    )
    transition = cal.resolve_duration("2024-09-29", "2025-12-27")
    first_quarter = cal.resolve_duration("2024-09-29", "2024-12-28")
    assert transition.period_type == "FY" and transition.fiscal_year == 2025
    assert first_quarter.period_type == "Q_STANDALONE"
    assert first_quarter.fiscal_year == 2025 and first_quarter.fiscal_quarter == 1


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


def test_derive_does_not_treat_standalone_quarter_as_cumulative():
    """D04: with Q1/Q2/Q3 standalone and FY but no YTD9, Q4 must NOT be derived.

    Treating the standalone Q3 as if it were the YTD-9M bucket would produce
    FY(400) - Q3(100) = 300, which is wrong (real Q4 = 400 - 100 - 100 - 100 = 100,
    but with no YTD-9M the quarter simply cannot be derived).
    """
    cal = make_calendar()
    facts = [
        {"canonical_fact_id": "a", "canonical_metric": "OCF", "period_type": "Q_STANDALONE",
         "fiscal_quarter": 1, "period_end": "2024-09-30", "value": 100.0, "unit": "USD", "as_known_at": "2024-10-30"},
        {"canonical_fact_id": "b", "canonical_metric": "OCF", "period_type": "Q_STANDALONE",
         "fiscal_quarter": 2, "period_end": "2024-12-31", "value": 100.0, "unit": "USD", "as_known_at": "2025-01-29"},
        {"canonical_fact_id": "c", "canonical_metric": "OCF", "period_type": "Q_STANDALONE",
         "fiscal_quarter": 3, "period_end": "2025-03-31", "value": 100.0, "unit": "USD", "as_known_at": "2025-04-29"},
        {"canonical_fact_id": "d", "canonical_metric": "OCF", "period_type": "FY",
         "fiscal_quarter": None, "period_end": "2025-06-30", "value": 400.0, "unit": "USD", "as_known_at": "2025-07-29"},
    ]
    derived = derive_standalone_quarters(facts, 2025, cal)
    assert all(d["fiscal_quarter"] != 4 for d in derived), "must not derive Q4 without YTD-9M"


def test_derive_uses_latest_restated_fy_for_q4():
    """D05: Q4 uses the latest-restated FY fact and propagates as_known_at."""
    cal = make_calendar()
    base = [
        {"canonical_fact_id": "a", "canonical_metric": "OCF", "period_type": "Q_STANDALONE",
         "fiscal_quarter": 1, "period_end": "2024-09-30", "value": 100.0, "unit": "USD", "as_known_at": "2024-10-30"},
        {"canonical_fact_id": "b", "canonical_metric": "OCF", "period_type": "YTD_6M",
         "fiscal_quarter": 2, "period_end": "2024-12-31", "value": 250.0, "unit": "USD", "as_known_at": "2025-01-29"},
        {"canonical_fact_id": "c", "canonical_metric": "OCF", "period_type": "YTD_9M",
         "fiscal_quarter": 3, "period_end": "2025-03-31", "value": 300.0, "unit": "USD", "as_known_at": "2025-04-29"},
        {"canonical_fact_id": "d_old", "canonical_metric": "OCF", "period_type": "FY",
         "fiscal_quarter": None, "period_end": "2025-06-30", "value": 400.0, "unit": "USD", "as_known_at": "2025-07-29"},
        {"canonical_fact_id": "d_new", "canonical_metric": "OCF", "period_type": "FY",
         "fiscal_quarter": None, "period_end": "2025-06-30", "value": 500.0, "unit": "USD", "as_known_at": "2025-08-29"},
    ]
    derived = derive_standalone_quarters(base, 2025, cal)
    q4 = next(d for d in derived if d["fiscal_quarter"] == 4)
    assert q4["value"] == pytest.approx(200.0)  # latest FY 500 - YTD9 300
    assert q4["as_known_at"] == "2025-08-29"

    # insertion order reversed -> identical result
    reversed_facts = list(reversed(base))
    derived_rev = derive_standalone_quarters(reversed_facts, 2025, cal)
    q4_rev = next(d for d in derived_rev if d["fiscal_quarter"] == 4)
    assert q4_rev["value"] == pytest.approx(200.0)


def test_same_day_restatement_tie_is_insertion_order_independent():
    """D05: equal filing dates use a stable identity tie-breaker."""
    cal = make_calendar()
    common = [
        {"canonical_fact_id": "ytd9", "canonical_metric": "OCF", "period_type": "YTD_9M",
         "fiscal_quarter": 3, "period_end": "2025-03-31", "value": 300.0, "unit": "USD",
         "as_known_at": "2025-07-29"},
    ]
    tied = [
        {"canonical_fact_id": "fy-a", "canonical_metric": "OCF", "period_type": "FY",
         "fiscal_quarter": None, "period_end": "2025-06-30", "value": 400.0, "unit": "USD",
         "as_known_at": "2025-07-29"},
        {"canonical_fact_id": "fy-b", "canonical_metric": "OCF", "period_type": "FY",
         "fiscal_quarter": None, "period_end": "2025-06-30", "value": 500.0, "unit": "USD",
         "as_known_at": "2025-07-29"},
    ]
    first = derive_standalone_quarters(common + tied, 2025, cal)
    second = derive_standalone_quarters(common + list(reversed(tied)), 2025, cal)
    q4_first = next(row for row in first if row["fiscal_quarter"] == 4)
    q4_second = next(row for row in second if row["fiscal_quarter"] == 4)
    assert q4_first["value"] == q4_second["value"] == 200.0
    assert q4_first["input_ids"] == q4_second["input_ids"] == ["ytd9", "fy-b"]


@pytest.mark.parametrize("as_date", [False, True])
def test_q4_derivation_accepts_date_and_iso_periods(as_date):
    """D04: DuckDB date objects and ISO strings must select the same buckets."""
    fy_end = date(2025, 6, 30) if as_date else "2025-06-30"
    q3_end = date(2025, 3, 31) if as_date else "2025-03-31"
    facts = [
        {"canonical_fact_id": "fy", "canonical_metric": "OCF", "period_type": "FY",
         "fiscal_quarter": None, "period_end": fy_end, "value": 400.0, "unit": "USD",
         "as_known_at": "2025-07-30"},
        {"canonical_fact_id": "ytd9", "canonical_metric": "OCF", "period_type": "YTD_9M",
         "fiscal_quarter": 3, "period_end": q3_end, "value": 300.0, "unit": "USD",
         "as_known_at": "2025-04-30"},
    ]

    result = derive_standalone_quarters(facts, 2025, make_calendar())

    q4 = next(row for row in result if row["fiscal_quarter"] == 4)
    assert q4["value"] == 100.0
    assert q4["period_end"] == "2025-06-30"
    assert q4["input_ids"] == ["ytd9", "fy"]


def test_early_date_not_clamped_to_earliest_year():
    """D03: dates before the earliest known year end use the fallback rule."""
    cal = make_calendar()  # known FY2024..FY2026, fallback 06-30
    p = cal.resolve_duration("2007-07-01", "2008-06-30")
    assert p.period_type == "FY"
    assert p.fiscal_year == 2008  # not clamped into FY2024


def test_early_date_unresolved_without_reliable_fallback():
    cal = FiscalCalendar(
        year_ends={2024: date(2024, 6, 30), 2025: date(2025, 6, 30)},
        quarter_ends={},
        fallback_mm_dd=None,
    )
    p = cal.resolve_duration("2007-07-01", "2008-06-30")
    assert p.fiscal_year is None  # explicitly unresolved, not clamped
