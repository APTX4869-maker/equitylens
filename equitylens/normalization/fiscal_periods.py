"""Fiscal-period resolver.

SEC's `fy`/`fp` fields on companyfacts entries describe the filing's own
period classification and are unreliable across restatements (a FY2019 10-K
may carry FY2017 facts tagged FY). We therefore never trust `fp` alone:

- The fiscal calendar (year-end and quarter-end dates) is built from the
  submissions index: a 10-K's reportDate IS the fiscal year end; 10-Q
  reportDates inside that window are the quarter ends.
- Every fact's period is derived from its own start/end/instant dates.

Period semantics follow docs/04: Q_STANDALONE | YTD_6M | YTD_9M | FY | INSTANT.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

# span-day windows used to classify duration facts (13-week quarters, etc.)
QUARTER_MIN, QUARTER_MAX = 70, 110
HALF_MIN, HALF_MAX = 160, 200
NINE_MIN, NINE_MAX = 250, 300
YEAR_MIN = 350


def _iso_date(value: object) -> str | None:
    """Normalize supported database/date values before period comparison."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (TypeError, ValueError):
        return None


@dataclass
class Period:
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None  # 1..4; None for FY / unknown
    period_type: str = "UNKNOWN"  # Q_STANDALONE | YTD_6M | YTD_9M | FY | INSTANT
    period_start: str | None = None
    period_end: str | None = None
    instant_date: str | None = None
    warnings: list[str] = field(default_factory=list)

    def key(self) -> tuple:
        return (self.fiscal_year, self.fiscal_quarter, self.period_type)


class FiscalCalendar:
    """Per-company fiscal calendar derived from the submissions index."""

    def __init__(
        self,
        year_ends: dict[int, date],
        quarter_ends: dict[int, list[date]],
        fallback_mm_dd: str | None = None,
    ):
        self.year_ends = year_ends
        self.quarter_ends = quarter_ends
        self.fallback_mm_dd = fallback_mm_dd

    # ---------------- construction ----------------

    @classmethod
    def from_submissions(cls, submissions: dict, fallback_mm_dd: str | None = None) -> "FiscalCalendar":
        year_ends: dict[int, date] = {}
        quarter_dates: dict[int, set[date]] = {}
        recent = submissions.get("filings", {}).get("recent") or []
        if isinstance(recent, dict):
            # SEC now serves `filings.recent` as parallel arrays (columnar)
            keys = list(recent.keys())
            rows: list[dict] = [dict(zip(keys, vals)) for vals in zip(*recent.values())]
        else:
            rows = recent
        for f in rows:
            form = (f.get("form") or "").upper()
            report = f.get("reportDate")
            if not report:
                continue
            try:
                d = date.fromisoformat(report)
            except ValueError:
                continue
            if form.startswith("10-K"):
                year_ends[d.year] = d  # last one wins (latest amendment)

        # assign each 10-Q report date to its FISCAL year (smallest year end >= d),
        # not its calendar year — quarter ends near year-end would otherwise land
        # in the wrong fiscal year's bucket.
        # For the in-progress fiscal year (no 10-K yet), estimate its year end
        # from the fallback MM-DD so its quarter ends resolve correctly.
        if fallback_mm_dd and year_ends:
            mm_dd = fallback_mm_dd.replace("-", "")
            if len(mm_dd) == 4 and mm_dd.isdigit():
                mm, dd = int(mm_dd[:2]), int(mm_dd[2:])
                last_known = max(year_ends)
                for y in range(last_known + 1, date.today().year + 2):
                    try:
                        year_ends[y] = date(y, mm, dd)
                    except ValueError:
                        pass
        for f in rows:
            form = (f.get("form") or "").upper()
            report = f.get("reportDate")
            if not form.startswith("10-Q") or not report:
                continue
            try:
                d = date.fromisoformat(report)
            except ValueError:
                continue
            fy = min((y for y, e in year_ends.items() if e >= d), default=None)
            if fy is not None:
                quarter_dates.setdefault(fy, set()).add(d)

        quarter_ends: dict[int, list[date]] = {y: sorted(ds) for y, ds in quarter_dates.items()}
        return cls(year_ends, quarter_ends, fallback_mm_dd=fallback_mm_dd)

    # ---------------- resolution ----------------

    def fiscal_year_of(self, d: date) -> int | None:
        """Fiscal year containing date d: smallest year_end >= d.

        The submissions index only carries recent 10-Ks, so dates before the
        earliest *known* fiscal year must not be silently clamped into that
        year. Such dates are resolved via the fallback calendar rule when one is
        available and reliable; otherwise they stay unresolved (None).
        """
        if not self.year_ends:
            return None
        best_year: int | None = None
        best_end: date | None = None
        for y, end in self.year_ends.items():
            if end >= d and (best_end is None or end < best_end):
                best_year, best_end = y, end
        if best_year is None:
            # d is after the latest known year end -> in-progress/future year.
            return self._heuristic_fiscal_year(d)
        earliest_year = min(self.year_ends)
        if best_year == earliest_year and (earliest_year - 1) not in self.year_ends:
            # The earliest known year's start is unbounded, so d could predate
            # it. Do not clamp; resolve via the fallback rule or leave unknown.
            return self._heuristic_fiscal_year(d)
        return best_year

    def _heuristic_fiscal_year(self, d: date) -> int | None:
        if not self.fallback_mm_dd:
            return None
        mm_dd = self.fallback_mm_dd.replace("-", "")
        if len(mm_dd) != 4 or not mm_dd.isdigit():
            return None
        mm, dd = int(mm_dd[:2]), int(mm_dd[2:])
        try:
            end_this_year = date(d.year, mm, dd)
        except ValueError:
            return None
        return d.year if d <= end_this_year else d.year + 1

    def quarter_containing(self, year: int, d: date) -> int | None:
        ends = self.quarter_ends.get(year)
        if not ends:
            return None
        # strict: a date ON a quarter end belongs to THAT quarter
        count = sum(1 for e in ends if e < d)
        return min(count + 1, 4) if count >= 0 else None

    def resolve_duration(self, start: str, end: str, fp_hint: str | None = None) -> Period:
        try:
            s, e = date.fromisoformat(start), date.fromisoformat(end)
        except ValueError:
            return Period(period_type="UNKNOWN", period_start=start, period_end=end,
                          warnings=["unparseable dates"])
        span = (e - s).days
        year = self.fiscal_year_of(e)
        p = Period(period_start=start, period_end=end, fiscal_year=year)

        if span >= YEAR_MIN:
            p.period_type = "FY"
            p.fiscal_quarter = None
        elif NINE_MIN <= span <= NINE_MAX:
            p.period_type = "YTD_9M"
            p.fiscal_quarter = 3
        elif HALF_MIN <= span <= HALF_MAX:
            p.period_type = "YTD_6M"
            p.fiscal_quarter = 2
        elif QUARTER_MIN <= span <= QUARTER_MAX:
            p.period_type = "Q_STANDALONE"
            p.fiscal_quarter = self.quarter_containing(year, e) if year else None
            if p.fiscal_quarter is None and fp_hint and fp_hint.startswith("Q"):
                try:
                    p.fiscal_quarter = int(fp_hint[1])
                except ValueError:
                    pass
        else:
            p.period_type = "UNKNOWN"
            p.warnings.append(f"span {span}d does not map to a fiscal period")

        # cross-check against the SEC fp hint; keep the date-derived value but warn
        if p.period_type == "Q_STANDALONE" and fp_hint and fp_hint.startswith("Q"):
            hint_q = fp_hint[1:]
            if hint_q.isdigit() and p.fiscal_quarter and int(hint_q) != p.fiscal_quarter:
                p.warnings.append(f"fp hint Q{hint_q} != date-derived Q{p.fiscal_quarter}")
        return p

    def resolve_instant(self, instant: str) -> Period:
        try:
            d = date.fromisoformat(instant)
        except ValueError:
            return Period(period_type="INSTANT", instant_date=instant,
                          warnings=["unparseable date"])
        year = self.fiscal_year_of(d)
        return Period(
            fiscal_year=year,
            fiscal_quarter=self.quarter_containing(year, d) if year else None,
            period_type="INSTANT",
            instant_date=instant,
        )

    def quarter_end(self, year: int, quarter: int) -> date | None:
        ends = self.quarter_ends.get(year, [])
        if 1 <= quarter <= 3 and len(ends) >= quarter:
            return ends[quarter - 1]
        if quarter == 4:
            return self.year_ends.get(year)
        return None

    def fiscal_start(self, year: int) -> date | None:
        """First day of fiscal year = day after previous year end."""
        if year - 1 in self.year_ends:
            return self.year_ends[year - 1] + timedelta(days=1)
        if year in self.year_ends:
            return self.year_ends[year] - timedelta(days=364)
        return None


def derive_standalone_quarters(facts: list[dict], year: int, calendar: FiscalCalendar) -> list[dict]:
    """Derive MISSING Q_STANDALONE duration facts from the YTD chain.

    Q1 = YTD-3M (direct), Q2 = YTD-6M - YTD-3M, Q3 = YTD-9M - YTD-6M,
    Q4 = FY - YTD-9M. Quarters already reported standalone are left alone.
    Inputs must belong to the same fiscal year and unit; any missing bucket
    yields no derived fact (never a guess).
    """
    derived: list[dict] = []
    existing = {f.get("fiscal_quarter") for f in facts
                if f.get("period_type") == "Q_STANDALONE" and f.get("fiscal_quarter")}

    def pick(period_type: str, end: date | None) -> dict | None:
        if end is None:
            return None
        candidates = [f for f in facts if f.get("period_type") == period_type
                      and _iso_date(f.get("period_end")) == end.isoformat()]
        if not candidates:
            return None
        # if several (e.g. restated filings for the same period), prefer the
        # latest known (highest as_known_at) so derived quarters follow the
        # latest restatement rather than insertion order.
        return max(
            candidates,
            key=lambda f: (
                str(f.get("as_known_at") or ""),
                str(f.get("source_document_id") or ""),
                str(f.get("canonical_fact_id") or ""),
            ),
        )

    def max_known(*items: dict | None) -> str | None:
        known = [f.get("as_known_at") for f in items if f and f.get("as_known_at")]
        return max(known) if known else None

    q1_end = calendar.quarter_end(year, 1)
    q2_end = calendar.quarter_end(year, 2)
    q3_end = calendar.quarter_end(year, 3)

    def diff(later: dict | None, earlier: dict | None, quarter: int, label: str) -> dict | None:
        if not later or not earlier:
            return None
        if later.get("unit") != earlier.get("unit"):
            return None
        # Issuer adapters attach a restatement_set_id once filing contexts have
        # been reconciled. Never subtract across explicitly different sets.
        later_basis = later.get("restatement_set_id")
        earlier_basis = earlier.get("restatement_set_id")
        if (later_basis or earlier_basis) and later_basis != earlier_basis:
            return None
        return {
            "canonical_metric": later["canonical_metric"],
            "fiscal_year": year,
            "fiscal_quarter": quarter,
            "period_type": "Q_STANDALONE",
            "period_start": _iso_date(earlier.get("period_end")),
            "period_end": _iso_date(later.get("period_end")),
            "value": float(later["value"]) - float(earlier["value"]),
            "unit": later.get("unit"),
            "status": "CALCULATED",
            "formula_id": "standalone_quarter.ytd_diff.v1",
            "input_ids": [earlier.get("canonical_fact_id"), later.get("canonical_fact_id")],
            "derivation": label,
            # earliest moment the derived value could be known = latest input
            "as_known_at": max_known(later, earlier),
        }

    q1_direct = pick("YTD_3M", q1_end)
    if q1_direct is None:
        # Q1 of a cash-flow series is a 3-month standalone period; a Q_STANDALONE
        # fact ending exactly at q1_end is equivalent to first-quarter cumulative.
        q1_direct = pick("Q_STANDALONE", q1_end)
    if 1 not in existing and q1_direct:
        derived.append(dict(q1_direct, period_type="Q_STANDALONE", fiscal_quarter=1,
                            period_start=_iso_date(q1_direct.get("period_start")),
                            period_end=_iso_date(q1_direct.get("period_end")),
                            status="CALCULATED", formula_id="standalone_quarter.direct.v1",
                            input_ids=[q1_direct.get("canonical_fact_id")], derivation="ytd-q1"))
    if 2 not in existing:
        q2 = diff(pick("YTD_6M", q2_end), q1_direct, 2, "q2=ytd6-ytd3")
        if q2:
            derived.append(q2)
    if 3 not in existing:
        q3 = diff(pick("YTD_9M", q3_end), pick("YTD_6M", q2_end), 3, "q3=ytd9-ytd6")
        if q3:
            derived.append(q3)
    if 4 not in existing:
        # Q4 = FY - YTD_9M; prefer the latest-restated FY fact.
        fy = pick("FY", calendar.quarter_end(year, 4))
        q4 = diff(fy, pick("YTD_9M", q3_end), 4, "q4=fy-ytd9")
        if q4:
            derived.append(q4)
    return derived
