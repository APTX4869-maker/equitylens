"""Deterministic metric engine.

Every derived metric is a pure function of canonical facts, identified by a
versioned formula id, and records its input fact ids so the provenance API can
walk the full lineage. LLMs never participate in these calculations.

Period semantics (docs/04):
- duration metrics: standalone quarterly series (deriving cash-flow quarters
  from the YTD chain when necessary); TTM = sum of the trailing 4 quarters.
- instant metrics: latest valid value; never summed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from equitylens.config import METRIC_ENGINE_VERSION

PERIOD_TYPE_RANK = {"Q_STANDALONE": 0, "YTD_6M": 1, "YTD_9M": 2, "FY": 3, "INSTANT": 4}


@dataclass
class MetricPoint:
    metric: str
    value: float | None
    canonical_fact_id: str | None = None
    unit: str | None = None
    status: str | None = None
    formula_id: str | None = None
    formula_version: str | None = None
    input_fact_ids: list[str] | None = None
    period_label: str | None = None
    period_end: str | None = None
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None
    warnings: list[str] | None = None

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "canonical_fact_id": self.canonical_fact_id,
            "value": self.value,
            "unit": self.unit,
            "status": self.status,
            "formula_id": self.formula_id,
            "formula_version": self.formula_version,
            "input_fact_ids": self.input_fact_ids or [],
            "period_label": self.period_label,
            "period_end": self.period_end,
            "fiscal_year": self.fiscal_year,
            "fiscal_quarter": self.fiscal_quarter,
            "warnings": self.warnings or [],
        }


class MetricEngine:
    def __init__(self, store):
        self.store = store
        self.version = METRIC_ENGINE_VERSION

    # ---------------- fact loading ----------------

    def load_facts(self, company_id: str, metrics: list[str]) -> dict[str, list[dict]]:
        """latest-restated canonical facts per metric."""
        out: dict[str, list[dict]] = {m: [] for m in metrics}
        if not metrics:
            return out
        placeholders = ", ".join("?" for _ in metrics)
        rows = self.store.query(
            f"""
            SELECT canonical_metric, canonical_fact_id, company_id, period_type,
                   fiscal_year, fiscal_quarter, period_start, period_end, instant_date,
                   value, unit, status, mapping_rule_id, mapping_version,
                   source_raw_fact_ids, as_known_at, warnings_json, source_document_id
            FROM canonical_fact
            WHERE company_id = ? AND canonical_metric IN ({placeholders})
            """,
            [company_id, *metrics],
        )
        for r in rows:
            out.setdefault(r["canonical_metric"], []).append(r)
        return out

    @staticmethod
    def pick_latest(facts: list[dict]) -> dict | None:
        """Latest restated: prefer highest as_known_at (filing date)."""
        return max(facts, key=lambda f: f.get("as_known_at") or "") if facts else None

    @staticmethod
    def _latest_instant(facts: list[dict]) -> dict | None:
        """Latest balance-sheet observation: newest date, then latest restated."""
        if not facts:
            return None
        return max(
            facts,
            key=lambda f: (
                f.get("instant_date") or f.get("period_end") or "",
                f.get("as_known_at") or "",
            ),
        )

    def _period_key(self, f: dict) -> tuple:
        return (f.get("fiscal_year"), f.get("fiscal_quarter"), f.get("period_type"))

    # ---------------- standalone quarter series ----------------

    def standalone_series(self, facts: list[dict]) -> dict[tuple, dict]:
        """Map (fiscal_year, quarter) -> best standalone duration fact.

        Direct Q_STANDALONE facts win; otherwise derive from the YTD chain.
        """
        out: dict[tuple, dict] = {}
        direct: dict[tuple, list[dict]] = {}
        for f in facts:
            if f.get("period_type") == "Q_STANDALONE" and f.get("fiscal_quarter"):
                direct.setdefault((f["fiscal_year"], f["fiscal_quarter"]), []).append(f)
        for k, fs in direct.items():
            out[k] = self.pick_latest(fs)

        # derive missing quarters from YTD chain per fiscal year
        from equitylens.normalization.fiscal_periods import derive_standalone_quarters

        for year in {f.get("fiscal_year") for f in facts if f.get("fiscal_year")}:
            year_facts = [f for f in facts if f.get("fiscal_year") == year]
            have = {k for k in out if k[0] == year}
            if len(have) >= 4:
                continue
            calendar = self._calendar_for(year, facts)
            if calendar is None:
                continue
            for d in derive_standalone_quarters(year_facts, year, calendar):
                key = (year, d["fiscal_quarter"])
                if key not in out:
                    out[key] = d
        return out

    def _calendar_for(self, year: int, facts: list[dict]):
        """Build a minimal fiscal calendar from the loaded facts (for derivation)."""
        from datetime import date

        from equitylens.normalization.fiscal_periods import FiscalCalendar

        year_ends: dict[int, date] = {}
        for f in facts:
            if f.get("period_type") == "FY" and f.get("period_end"):
                try:
                    year_ends[f["fiscal_year"]] = date.fromisoformat(f["period_end"])
                except (TypeError, ValueError):
                    pass
        if not year_ends:
            return None
        quarter_ends: dict[int, list[date]] = {}
        for f in facts:
            y = f.get("fiscal_year")
            if y in year_ends and f.get("period_end"):
                try:
                    d = date.fromisoformat(f["period_end"])
                except (TypeError, ValueError):
                    continue
                if f.get("period_type") in ("Q_STANDALONE", "YTD_6M", "YTD_9M") and d < year_ends[y]:
                    quarter_ends.setdefault(y, set()).add(d)  # type: ignore[union-attr]
        return FiscalCalendar(year_ends, {y: sorted(ds) for y, ds in quarter_ends.items()})

    # ---------------- TTM ----------------

    def ttm(self, facts: list[dict], as_of_quarter: tuple | None = None) -> dict | None:
        """TTM of a duration metric = sum of the 4 standalone quarters ending at period t."""
        series = self.standalone_series(facts)
        quarters = sorted((k for k in series if k[1] in (1, 2, 3, 4)), reverse=True)
        if not quarters:
            return None
        end = as_of_quarter or quarters[0]
        window = [k for k in quarters if k[0] < end[0] or (k[0] == end[0] and k[1] <= end[1])][:4]
        if len(window) < 4:
            return None
        vals = [series[k]["value"] for k in window]
        if any(v is None for v in vals):
            return None
        return {
            "value": sum(vals),
            "fiscal_year": end[0],
            "fiscal_quarter": end[1],
            "input_ids": [series[k]["canonical_fact_id"] for k in window],
        }

    # ---------------- formula implementations ----------------

    def _two_series(self, num_facts: list[dict], den_facts: list[dict], freq: str):
        """Pair numerator/denominator by period key; ratios for quarter/annual series."""
        nums = self.standalone_series(num_facts) if freq == "quarterly" else {
            (f["fiscal_year"], None, f["period_type"]): f
            for f in num_facts if f.get("period_type") == "FY"
        }
        dens = self.standalone_series(den_facts) if freq == "quarterly" else {
            (f["fiscal_year"], None, f["period_type"]): f
            for f in den_facts if f.get("period_type") == "FY"
        }
        out = []
        for key, n in sorted(nums.items(), key=lambda kv: (kv[0][0] or 0, kv[0][1] or 0)):
            d = dens.get(key)
            if not d or not n.get("value") or not d.get("value"):
                continue
            out.append((key, n, d))
        return out

    def compute(self, metric: str, company_id: str, frequency: str = "quarterly",
                limit: int | None = None, view: str = "latest_restated") -> list[MetricPoint]:
        freq = frequency if frequency in ("quarterly", "annual", "ttm") else "quarterly"
        points: list[MetricPoint] = []

        if metric == "REVENUE_GROWTH_YOY":
            rev = self.load_facts(company_id, ["REVENUE"])["REVENUE"]
            series = self.standalone_series(rev) if freq == "quarterly" else {
                (f["fiscal_year"], None, "FY"): f for f in rev if f.get("period_type") == "FY"
            }
            keys = sorted(series, key=lambda k: (k[0] or 0, k[1] or 0))
            for i, k in enumerate(keys):
                if freq == "quarterly" and i < 4:
                    continue
                if freq == "annual" and i < 1:
                    continue
                cur = series[k]
                if freq == "annual":
                    prev_key = (k[0] - 1, None, "FY")
                else:
                    prev_key = (k[0] - 1, k[1])
                prev = series.get(prev_key)
                if prev is None:
                    continue
                value = (float(cur["value"]) / float(prev["value"]) - 1.0) if prev["value"] else None
                points.append(self._point(metric, value, cur, "revenue_growth_yoy.v1",
                                          [cur.get("canonical_fact_id"), prev.get("canonical_fact_id")],
                                          freq))
        elif metric in ("GROSS_MARGIN", "OPERATING_MARGIN", "NET_MARGIN"):
            num_metric = {"GROSS_MARGIN": "GROSS_PROFIT", "OPERATING_MARGIN": "OPERATING_INCOME",
                          "NET_MARGIN": "NET_INCOME"}[metric]
            facts = self.load_facts(company_id, [num_metric, "REVENUE"])
            for key, n, d in self._two_series(facts[num_metric], facts["REVENUE"], freq):
                value = float(n["value"]) / float(d["value"]) if d["value"] else None
                points.append(self._point(metric, value, n, f"{metric.lower()}.v1",
                                          [n.get("canonical_fact_id"), d.get("canonical_fact_id")], freq))
        elif metric in ("FCF", "FCF_MARGIN"):
            facts = self.load_facts(company_id, ["OPERATING_CASH_FLOW", "CAPITAL_EXPENDITURES", "REVENUE"])
            ocf = self.standalone_series(facts["OPERATING_CASH_FLOW"]) if freq == "quarterly" else {
                (f["fiscal_year"], None, "FY"): f for f in facts["OPERATING_CASH_FLOW"] if f.get("period_type") == "FY"
            }
            capex = self.standalone_series(facts["CAPITAL_EXPENDITURES"]) if freq == "quarterly" else {
                (f["fiscal_year"], None, "FY"): f for f in facts["CAPITAL_EXPENDITURES"] if f.get("period_type") == "FY"
            }
            rev_series = self.standalone_series(facts["REVENUE"]) if freq == "quarterly" else {
                (f["fiscal_year"], None, "FY"): f for f in facts["REVENUE"] if f.get("period_type") == "FY"
            }
            for key in sorted(set(ocf) & set(capex), key=lambda k: (k[0] or 0, k[1] or 0)):
                o, c = ocf[key], capex[key]
                fcf = float(o["value"]) - float(c["value"])
                if metric == "FCF":
                    points.append(self._point("FCF", fcf, o, "fcf.v1",
                                              [o.get("canonical_fact_id"), c.get("canonical_fact_id")], freq))
                else:
                    r = rev_series.get(key)
                    if r and r["value"]:
                        points.append(self._point("FCF_MARGIN", fcf / float(r["value"]), o, "fcf_margin.v1",
                                                  [o.get("canonical_fact_id"), c.get("canonical_fact_id"),
                                                   r.get("canonical_fact_id")], freq))
        elif metric == "NET_DEBT":
            facts = self.load_facts(company_id, ["SHORT_TERM_DEBT", "LONG_TERM_DEBT",
                                                 "CASH_AND_EQUIVALENTS", "SHORT_TERM_INVESTMENTS"])
            cash = self._latest_instant(facts["CASH_AND_EQUIVALENTS"])
            st = self._latest_instant(facts["SHORT_TERM_DEBT"])
            lt = self._latest_instant(facts["LONG_TERM_DEBT"])
            inv = self._latest_instant(facts["SHORT_TERM_INVESTMENTS"])
            if cash is None or st is None or lt is None:
                return points
            value = float(st["value"]) + float(lt["value"]) - float(cash["value"]) - (float(inv["value"]) if inv else 0.0)
            points.append(self._point("NET_DEBT", value, cash, "net_debt.v1",
                                      [f.get("canonical_fact_id") for f in (st, lt, cash, inv) if f], freq))
        elif metric in ("REVENUE", "GROSS_PROFIT", "OPERATING_INCOME", "NET_INCOME",
                        "OPERATING_CASH_FLOW", "CAPITAL_EXPENDITURES", "DILUTED_EPS",
                        "BASIC_EPS", "DILUTED_WEIGHTED_AVG_SHARES", "BASIC_WEIGHTED_AVG_SHARES",
                        "SHARE_REPURCHASES", "DIVIDENDS_PAID", "SHARE_BASED_COMPENSATION",
                        "DEPRECIATION_AMORTIZATION", "PRETAX_INCOME", "INCOME_TAX_EXPENSE",
                        "COST_OF_REVENUE"):
            # passthrough canonical metrics (with standalone-quarter derivation for cash flow)
            facts = self.load_facts(company_id, [metric])[metric]
            series = self.standalone_series(facts) if freq in ("quarterly", "ttm") else {
                (f["fiscal_year"], None, "FY"): f for f in facts if f.get("period_type") == "FY"
            }
            if freq == "ttm":
                # TTM = trailing 4 standalone quarters per period end
                keys = sorted(series, key=lambda k: (k[0] or 0, k[1] or 0))
                for i, key in enumerate(keys):
                    if i < 3:
                        continue
                    window = keys[i - 3 : i + 1]
                    vals = [float(series[k]["value"]) for k in window]
                    total = sum(vals)
                    f = series[key]
                    points.append(self._point(metric, total, f, "ttm.v1",
                                              [series[k]["canonical_fact_id"] for k in window],
                                              "quarterly"))
                points = [p for p in points]
                return points
            for key in sorted(series, key=lambda k: (k[0] or 0, k[1] or 0)):
                f = series[key]
                formula_id = f.get("formula_id") or (
                    f.get("mapping_rule_id") if f.get("status") == "CALCULATED" else None
                )
                raw_inputs = f.get("input_ids")
                if not raw_inputs and f.get("source_raw_fact_ids"):
                    raw_inputs = json.loads(f["source_raw_fact_ids"] or "[]")
                input_ids = raw_inputs or [f.get("canonical_fact_id")]
                points.append(self._point(metric, float(f["value"]), f, formula_id, input_ids, freq,
                                          fact_id=f.get("canonical_fact_id")))
        else:
            raise ValueError(f"Metric {metric!r} not implemented in metric engine")

        points.sort(key=lambda p: (p.fiscal_year or 0, p.fiscal_quarter or 0))
        if limit:
            points = points[-limit:]
        return points

    def _point(self, metric, value, fact, formula_id, input_ids, freq, fact_id=None) -> MetricPoint:
        label = f"FY{fact.get('fiscal_year')}" if freq == "annual" or fact.get("period_type") == "FY" \
            else f"FY{fact.get('fiscal_year')}Q{fact.get('fiscal_quarter')}"
        return MetricPoint(
            metric=metric,
            value=value,
            canonical_fact_id=fact_id or fact.get("canonical_fact_id"),
            unit=fact.get("unit"),
            status="CALCULATED" if formula_id else fact.get("status"),
            formula_id=formula_id,
            formula_version=f"{formula_id.replace('.v1', '')}.v1" if formula_id else None,
            input_fact_ids=input_ids,
            period_label=label,
            period_end=fact.get("period_end") or fact.get("instant_date"),
            fiscal_year=fact.get("fiscal_year"),
            fiscal_quarter=fact.get("fiscal_quarter"),
        )
