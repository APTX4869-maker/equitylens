"""Pure deterministic reconciliation rules using disclosure precision."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from equitylens.quality.models import CheckResult, CheckStatus, Severity


@dataclass(frozen=True)
class RoundingInterval:
    low: Decimal
    high: Decimal

    @classmethod
    def from_value(cls, value: float, decimals: int | str = 0) -> "RoundingInterval":
        number = Decimal(str(value))
        if str(decimals).upper() == "INF":
            half = Decimal(0)
        else:
            half = (Decimal(10) ** -int(decimals)) / 2
        return cls(number - half, number + half)

    def __add__(self, other: "RoundingInterval") -> "RoundingInterval":
        return RoundingInterval(self.low + other.low, self.high + other.high)

    def intersects(self, other: "RoundingInterval") -> bool:
        return self.low <= other.high and other.low <= self.high

    def as_dict(self) -> dict[str, str]:
        return {"low": str(self.low), "high": str(self.high)}


def _sum_intervals(values: Iterable[float], decimals: int | str) -> RoundingInterval:
    result = RoundingInterval(Decimal(0), Decimal(0))
    for value in values:
        result = result + RoundingInterval.from_value(value, decimals)
    return result


def balance_equation(
    *,
    assets: float,
    liabilities: float,
    equity: float,
    mezzanine: float = 0,
    decimals: int | str = 0,
) -> CheckResult:
    left = RoundingInterval.from_value(assets, decimals)
    right = _sum_intervals([liabilities, equity, mezzanine], decimals)
    return CheckResult(
        check_id="BALANCE.equation",
        status=CheckStatus.PASS if left.intersects(right) else CheckStatus.FAIL,
        actual={"assets": assets, "liabilities_equity_mezzanine": liabilities + equity + mezzanine},
        expected={"equation": "assets = liabilities + equity + mezzanine"},
        tolerance={"basis": "xbrl_decimals", "left": left.as_dict(), "right": right.as_dict()},
        reason=None if left.intersects(right) else "BALANCE_MISMATCH",
    )


def cash_bridge(
    *,
    opening: float,
    operating: float,
    investing: float,
    financing: float,
    fx: float,
    closing: float,
    other: float = 0,
    decimals: int | str = 0,
) -> CheckResult:
    expected = _sum_intervals(
        [opening, operating, investing, financing, fx, other], decimals
    )
    disclosed = RoundingInterval.from_value(closing, decimals)
    passed = expected.intersects(disclosed)
    return CheckResult(
        check_id="CASH.bridge",
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        actual={
            "opening": opening,
            "operating": operating,
            "investing": investing,
            "financing": financing,
            "fx": fx,
            "other": other,
            "closing": closing,
        },
        expected={"closing_from_bridge": opening + operating + investing + financing + fx + other},
        tolerance={"basis": "xbrl_decimals", "bridge": expected.as_dict(), "closing": disclosed.as_dict()},
        reason=None if passed else "CASH_DEFINITION_MISMATCH",
    )


def cash_bridge_with_disclosed_change(
    *,
    opening: float,
    operating: float,
    investing: float,
    financing: float,
    disclosed_change: float,
    closing: float,
    decimals: int | str = 0,
) -> CheckResult:
    """Reconcile issuers that disclose net cash change including FX as one line."""
    activities = _sum_intervals([operating, investing, financing], decimals)
    change = RoundingInterval.from_value(disclosed_change, decimals)
    full_bridge = activities.intersects(change)
    closing_from_change = _sum_intervals([opening, disclosed_change], decimals)
    disclosed_closing = RoundingInterval.from_value(closing, decimals)
    passed = closing_from_change.intersects(disclosed_closing)
    implied_fx_or_other = disclosed_change - operating - investing - financing
    return CheckResult(
        check_id="CASH.bridge" if full_bridge else "CASH.rollforward",
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        severity=Severity.BLOCKER if full_bridge or not passed else Severity.WARNING,
        actual={
            "opening": opening,
            "operating": operating,
            "investing": investing,
            "financing": financing,
            "disclosed_change_including_fx": disclosed_change,
            "implied_fx_or_other": implied_fx_or_other,
            "closing": closing,
        },
        expected={
            "closing_from_disclosed_change": opening + disclosed_change,
            "activities_equal_disclosed_change": operating + investing + financing
            if full_bridge else None,
        },
        tolerance={"basis": "xbrl_decimals", "decimals": str(decimals)},
        reason=(
            "CASH_DEFINITION_MISMATCH" if not passed
            else "FX_OR_OTHER_NOT_SEPARATELY_DISCLOSED" if not full_bridge
            else None
        ),
    )


def derive_standalone_quarter(
    *,
    current_ytd: float,
    previous_ytd: float,
    fiscal_year: int,
    previous_fiscal_year: int,
    basis: str,
    previous_basis: str,
) -> float:
    if fiscal_year != previous_fiscal_year or basis != previous_basis:
        raise ValueError("cumulative facts must use the same fiscal year and basis")
    return current_ytd - previous_ytd


def eps_reconciliation(
    *,
    reported_eps: float,
    numerator: float,
    weighted_shares: float,
    explicit_method: str | None,
    decimals: int | str = 2,
) -> CheckResult:
    if not explicit_method:
        return CheckResult(
            check_id="EPS.reconciliation",
            status=CheckStatus.FAIL,
            actual={"reported_eps": reported_eps},
            expected={"requires": "explicit two-class/preferred/anti-dilution method"},
            reason="EPS_METHOD_UNPROVEN",
        )
    calculated = numerator / weighted_shares
    passed = RoundingInterval.from_value(reported_eps, decimals).intersects(
        RoundingInterval.from_value(calculated, decimals)
    )
    return CheckResult(
        check_id="EPS.reconciliation",
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        actual={"reported_eps": reported_eps, "calculated_eps": calculated, "method": explicit_method},
        tolerance={"basis": "xbrl_decimals", "decimals": str(decimals)},
        reason=None if passed else "EPS_MISMATCH",
    )


def segment_reconciliation(
    *,
    consolidated: float,
    segments: list[float],
    eliminations: float | None,
    decimals: int | str = 0,
) -> CheckResult:
    segment_total = sum(segments)
    if eliminations is None and not RoundingInterval.from_value(
        consolidated, decimals
    ).intersects(RoundingInterval.from_value(segment_total, decimals)):
        return CheckResult(
            check_id="SEGMENTS.reconciliation",
            status=CheckStatus.FAIL,
            actual={"consolidated": consolidated, "segments": segment_total},
            reason="SEGMENT_ELIMINATION_MISSING",
        )
    reconciled = segment_total + (eliminations or 0)
    passed = RoundingInterval.from_value(consolidated, decimals).intersects(
        RoundingInterval.from_value(reconciled, decimals)
    )
    return CheckResult(
        check_id="SEGMENTS.reconciliation",
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        actual={"consolidated": consolidated, "segments": segment_total, "eliminations": eliminations},
        reason=None if passed else "SEGMENT_MISMATCH",
    )


def required_period_coverage(
    *,
    annual_years: list[int],
    quarters: list[str],
    required_annual: int = 3,
    required_quarters: int = 8,
) -> CheckResult:
    annual_count = len(set(annual_years))
    quarter_count = len(set(quarters))
    passed = annual_count >= required_annual and quarter_count >= required_quarters
    return CheckResult(
        check_id="COVERAGE.periods",
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        actual={"annual_count": annual_count, "quarter_count": quarter_count},
        expected={"annual_count": required_annual, "quarter_count": required_quarters},
        reason=None if passed else "COVERAGE_INCOMPLETE",
    )


def evidence_required(
    *, check_id: str, claimed_status: CheckStatus, evidence: list[dict]
) -> CheckResult:
    if claimed_status in (CheckStatus.NOT_APPLICABLE, CheckStatus.NOT_DISCLOSED) and not evidence:
        return CheckResult(
            check_id=check_id,
            status=CheckStatus.FAIL,
            severity=Severity.BLOCKER,
            evidence=[],
            reason="EVIDENCE_MISSING",
        )
    return CheckResult(
        check_id=check_id,
        status=claimed_status,
        evidence=evidence,
    )
