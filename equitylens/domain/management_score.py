"""Capital allocation time series + management rubric scoring (M6).

Capital allocation is computed deterministically from canonical facts:
gross buybacks, SBC, net buybacks, dividends, capex, FCF, share-count trend.

Rubric scoring follows config/management/management_rubric.yaml:
- numeric scores come ONLY from deterministic formulas over sourced facts
- a dimension score is unavailable when < 70% of its criteria have a
  deterministic basis (minimum_evidence_coverage_for_score)
- LLM explanations may be added later (M7) but never set the numbers
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from equitylens.config import CONFIG_DIR
from equitylens.metrics.engine import MetricEngine

RUBRIC_PATH = CONFIG_DIR / "management" / "management_rubric.yaml"


def capital_allocation(store, company_id: str) -> dict:
    """Annual capital allocation series from canonical facts (latest 5 FY)."""
    engine = MetricEngine(store)
    metrics = [
        "SHARE_REPURCHASES", "DIVIDENDS_PAID", "CAPITAL_EXPENDITURES",
        "SHARE_BASED_COMPENSATION", "OPERATING_CASH_FLOW", "DILUTED_WEIGHTED_AVG_SHARES",
    ]
    series: dict[int, dict] = {}
    for m in metrics:
        points = engine.compute(m, company_id, frequency="annual")
        for p in points:
            year = p.fiscal_year
            if year is None or p.value is None:
                continue
            series.setdefault(year, {})[m] = p.value
    # FCF annual = OCF - CapEx (same series alignment)
    for year, row in series.items():
        if "OPERATING_CASH_FLOW" in row and "CAPITAL_EXPENDITURES" in row:
            row["FCF"] = row["OPERATING_CASH_FLOW"] - row["CAPITAL_EXPENDITURES"]

    years = sorted(series)[-5:]
    out: list[dict] = []
    for y in years:
        r = series[y]
        gross_buyback = r.get("SHARE_REPURCHASES")
        sbc = r.get("SHARE_BASED_COMPENSATION")
        out.append({
            "fiscal_year": y,
            "gross_buybacks": gross_buyback,
            "sbc": sbc,
            "net_buybacks": (gross_buyback - sbc) if (gross_buyback is not None and sbc is not None) else None,
            "dividends": r.get("DIVIDENDS_PAID"),
            "capex": r.get("CAPITAL_EXPENDITURES"),
            "operating_cash_flow": r.get("OPERATING_CASH_FLOW"),
            "fcf": r.get("FCF"),
            "diluted_shares": r.get("DILUTED_WEIGHTED_AVG_SHARES"),
        })
    latest = out[-1] if out else None

    def cagr(first: float | None, last: float | None, years: int) -> float | None:
        if first is None or last is None or first <= 0 or years < 1:
            return None
        return (last / first) ** (1 / years) - 1.0

    summary = {}
    if len(out) >= 2:
        f0, f1 = out[0], out[-1]
        summary["fcf_cagr"] = cagr(f0.get("fcf"), f1.get("fcf"), len(out) - 1)
        summary["capex_cagr"] = cagr(f0.get("capex"), f1.get("capex"), len(out) - 1)
        summary["buyback_cagr"] = cagr(f0.get("gross_buybacks"), f1.get("gross_buybacks"), len(out) - 1)
        summary["dividend_cagr"] = cagr(f0.get("dividends"), f1.get("dividends"), len(out) - 1)
        if f0.get("diluted_shares") and f1.get("diluted_shares"):
            summary["share_count_5y_change"] = f1["diluted_shares"] / f0["diluted_shares"] - 1.0
    # allocation mix (latest year, share of cash returned + capex)
    mix = {}
    if latest:
        fcf = latest.get("fcf") or 0
        if fcf:
            total = sum(v for v in (latest.get("gross_buybacks"), latest.get("dividends"), latest.get("capex")) if v)
            mix = {
                "buyback": (latest.get("gross_buybacks") or 0) / total if total else None,
                "dividend": (latest.get("dividends") or 0) / total if total else None,
                "capex": (latest.get("capex") or 0) / total if total else None,
            }
    return {"series": out, "latest": latest, "summary": summary, "mix": mix}


def _load_rubric() -> dict:
    return yaml.safe_load(Path(RUBRIC_PATH).read_text())


def _clip(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def management_scorecard(store, company_id: str, ticker: str) -> dict:
    """Deterministic rubric scorecard with evidence coverage."""
    rubric = _load_rubric()
    alloc = capital_allocation(store, company_id)
    margin_trend = _margin_signal_from_engine(store, company_id)
    min_cov = rubric.get("minimum_evidence_coverage_for_score", 0.70)
    dims: list[dict] = []
    covered_weight = 0.0
    total_weight = 0.0
    scored_weight = 0.0

    for dim_key, dim_spec in rubric["dimensions"].items():
        weight = dim_spec["weight"]
        total_weight += weight
        criteria = dim_spec["criteria"]
        sub_scores: dict[str, float | None] = {}
        evidence_flags: dict[str, bool] = {}

        for c in criteria:
            cid = c["id"]
            value, ok = _criterion_score(cid, alloc, margin_trend)
            sub_scores[cid] = value
            evidence_flags[cid] = ok
        scored = [v for v in sub_scores.values() if v is not None]
        coverage = sum(1 for v in sub_scores.values() if v is not None) / len(sub_scores) if sub_scores else 0.0
        if scored and coverage >= min_cov:
            weights = {c["id"]: c["weight"] for c in criteria}
            wsum = sum(weights[cid] for cid in sub_scores if sub_scores[cid] is not None)
            dim_score = sum(sub_scores[cid] * weights[cid] for cid in sub_scores if sub_scores[cid] is not None) / wsum
            covered_weight += weight
            scored_weight += weight
        else:
            dim_score = None
        dims.append({
            "key": dim_key,
            "weight": weight,
            "score": round(dim_score, 1) if dim_score is not None else None,
            "coverage": coverage,
            "scorable": dim_score is not None,
            "criteria": [
                {"id": c["id"], "score": sub_scores.get(c["id"]),
                 "evidence": evidence_flags.get(c["id"], False)}
                for c in criteria
            ],
            "reason": None if dim_score is not None else "证据覆盖不足（确定性评分依据不足）",
        })

    overall = None
    if total_weight and covered_weight / total_weight >= min_cov:
        overall = sum(d["score"] * d["weight"] for d in dims if d["score"] is not None) / covered_weight
    return {
        "ticker": ticker,
        "minimum_coverage": min_cov,
        "coverage": covered_weight / total_weight if total_weight else 0.0,
        "overall_score": round(overall, 1) if overall is not None else None,
        "overall_reason": None if overall is not None else "证据覆盖不足，管理评分不可用（覆盖率 %.0f%% < %.0f%%）" % (100 * (covered_weight / total_weight if total_weight else 0), 100 * min_cov),
        "dimensions": dims,
    }


def _margin_signal_from_engine(store, company_id: str) -> float | None:
    """3-year operating-margin trend score from canonical facts."""
    try:
        engine = MetricEngine(store)
        pts = engine.compute("OPERATING_MARGIN", company_id, frequency="annual")
    except ValueError:
        return None
    annual = [p.value for p in pts if p.value is not None][-3:]
    if len(annual) < 2:
        return None
    first, last = annual[0], annual[-1]
    if first is None or last is None or first <= 0:
        return None
    change = last / first - 1.0  # e.g. +0.05 = 5pp relative improvement
    return _clip(50 + change * 100 * 6)


def _margin_signal_from_engine(store, company_id: str) -> float | None:
    """3-year operating-margin trend score from canonical facts."""
    try:
        engine = MetricEngine(store)
        pts = engine.compute("OPERATING_MARGIN", company_id, frequency="annual")
    except ValueError:
        return None
    annual = [p.value for p in pts if p.value is not None][-3:]
    if len(annual) < 2:
        return None
    first, last = annual[0], annual[-1]
    if first is None or last is None or first <= 0:
        return None
    change = last / first - 1.0  # e.g. +0.05 = 5pp relative improvement
    return _clip(50 + change * 100 * 6)


def _criterion_score(cid: str, alloc: dict, margin_trend: float | None = None) -> tuple[float | None, bool]:
    """Deterministic sub-score from capital-allocation facts, or None."""
    latest = alloc.get("latest") or {}
    summary = alloc.get("summary") or {}
    series = alloc.get("series") or []
    marg = None
    if cid == "net_dilution":
        change = summary.get("share_count_5y_change")
        if change is None:
            return None, False
        return _clip(50 - change * 100 * 4), True  # -1% shares -> 54; +1% -> 46
    if cid == "incentive_alignment":
        sbc = latest.get("sbc")
        fcf = latest.get("fcf")
        if sbc is None or not fcf:
            return None, False
        return _clip(100 - (sbc / fcf) * 100 * 6), True  # SBC > ~17% of FCF drags score
    if cid == "capital_return_quality":
        nb = latest.get("net_buybacks")
        d = latest.get("dividends")
        fcf = latest.get("fcf")
        if nb is None or d is None or not fcf:
            return None, False
        returned = nb + d
        return _clip(returned / fcf * 100 * 0.8), True  # returning ~100% of FCF -> 80
    if cid == "reinvestment_returns":
        fc = summary.get("fcf_cagr")
        cc = summary.get("capex_cagr")
        if fc is None or cc is None:
            return None, False
        return _clip(50 + (fc - cc) * 100 * 2), True  # FCF growing faster than capex -> better
    if cid == "buyback_discipline":
        nb = latest.get("net_buybacks")
        gb = latest.get("gross_buybacks")
        if nb is None or not gb:
            return None, False
        return _clip(100 * (nb / gb)), True  # net buyback share of gross
    if cid == "acquisition_record":
        return None, False  # requires M&A data (not in V0.1)
    if cid == "balance_sheet_discipline":
        # net debt positive -> penalize; proxy via FCF/capex coverage
        if not series:
            return None, False
        avg_fcf = sum(y.get("fcf") or 0 for y in series[-3:]) / 3 if series else 0
        avg_capex = sum(y.get("capex") or 0 for y in series[-3:]) / 3 if series else 0
        if avg_capex <= 0:
            return None, False
        return _clip(40 + (avg_fcf / avg_capex) * 30), True
    if cid == "margin_discipline":
        if margin_trend is None:
            return None, False
        return margin_trend, True
    if cid == "cash_conversion":
        latest = alloc.get("latest") or {}
        ocf = latest.get("operating_cash_flow")
        fcf = latest.get("fcf")
        if not ocf or fcf is None:
            return None, False
        return _clip(100 * max(0.0, fcf / ocf)), True
    if cid == "return_on_capital_stability":
        return None, False  # ROIC locked out of V0.1 until definition is tested
    if cid in ("strategic_decision_outcomes", "operating_goal_delivery", "strategic_consistency",
               "delivery_rate", "miss_severity", "transparency_on_misses",
               "board_independence_and_controls", "compensation_governance", "succession_key_person_risk",
               "executive_ownership"):
        return None, False  # evidence-based criteria need M7 research records
    return None, False


def _margin_signal(alloc: dict) -> float | None:
    """3-year operating margin trend from canonical facts (via engine)."""
    return None  # supplied by caller when available
