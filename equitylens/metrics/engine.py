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

import base64
import hashlib
import json
from dataclasses import dataclass, replace

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
    frequency: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None
    warnings: list[str] | None = None
    missing_reason: str | None = None
    result_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "canonical_fact_id": self.canonical_fact_id,
            "result_id": self.result_id,
            "value": self.value,
            "unit": self.unit,
            "status": self.status,
            "formula_id": self.formula_id,
            "formula_version": self.formula_version,
            "input_fact_ids": self.input_fact_ids or [],
            "period_label": self.period_label,
            "frequency": self.frequency,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "fiscal_year": self.fiscal_year,
            "fiscal_quarter": self.fiscal_quarter,
            "warnings": self.warnings or [],
            "missing_reason": self.missing_reason,
        }


def derived_result_id(company_id: str, point: MetricPoint) -> str:
    """Content-address a complete derived result without writing during a GET.

    The signed payload freezes the card's value, formula, period and ordered
    canonical inputs. A later restatement therefore gets a different identity,
    while the old identity can still resolve its original root.
    """
    payload = {
        "company_id": company_id,
        "metric": point.metric,
        "frequency": point.frequency,
        "period_label": point.period_label,
        "period_start": point.period_start,
        "period_end": point.period_end,
        "value": point.value,
        "unit": point.unit,
        "status": point.status,
        "formula_id": point.formula_id,
        "formula_version": point.formula_version,
        "input_fact_ids": list(point.input_fact_ids or []),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    digest = hashlib.sha256(raw).hexdigest()
    return f"derived.v2.{encoded}.{digest}"


def decode_derived_result_id(entity_id: str) -> dict | None:
    """Verify and decode a v2 derived-result identity."""
    parts = entity_id.split(".")
    if len(parts) != 4 or parts[:2] != ["derived", "v2"]:
        return None
    encoded, expected = parts[2], parts[3]
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except (ValueError, TypeError):
        return None
    if hashlib.sha256(raw).hexdigest() != expected:
        return None
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


class MetricEngine:
    def __init__(self, store, *, published_facts: list[dict] | None = None):
        self.store = store
        self.version = METRIC_ENGINE_VERSION
        self.published_facts = published_facts

    # ---------------- fact loading ----------------

    def load_facts(self, company_id: str, metrics: list[str]) -> dict[str, list[dict]]:
        """latest-restated canonical facts per metric."""
        out: dict[str, list[dict]] = {m: [] for m in metrics}
        if not metrics:
            return out
        if self.published_facts is not None:
            for fact in self.published_facts:
                metric = fact.get("canonical_metric")
                if metric in out:
                    out[metric].append(dict(fact))
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
    def restatement_key(fact: dict) -> tuple[str, str, str]:
        """Stable preference for facts disclosed at the same timestamp."""
        return (
            str(fact.get("as_known_at") or ""),
            str(fact.get("source_document_id") or ""),
            str(fact.get("canonical_fact_id") or ""),
        )

    @staticmethod
    def pick_latest(facts: list[dict]) -> dict | None:
        """Latest restated with deterministic identity tie-breaking."""
        return max(facts, key=MetricEngine.restatement_key) if facts else None

    @staticmethod
    def _latest_instant(facts: list[dict]) -> dict | None:
        """Latest balance-sheet observation: newest date, then latest restated."""
        if not facts:
            return None
        return max(
            facts,
            key=lambda f: (
                f.get("instant_date") or f.get("period_end") or "",
                *MetricEngine.restatement_key(f),
            ),
        )

    def _period_key(self, f: dict) -> tuple:
        return (f.get("fiscal_year"), f.get("fiscal_quarter"), f.get("period_type"))

    @staticmethod
    def _prior_quarter(key: tuple) -> tuple:
        y, q = key[0], key[1]
        q -= 1
        if q == 0:
            return (y - 1, 4)
        return (y, q)

    def _trailing_window(self, keys: set, end: tuple, n: int = 4) -> list[tuple] | None:
        """Return n *consecutive* fiscal quarters ending at `end` (oldest first).

        Returns None if the contiguous window is incomplete — a gap quarter is
        never papered over by pulling an older quarter to reach `n` items.
        """
        window: list[tuple] = []
        k = end
        for _ in range(n):
            if k not in keys:
                return None
            window.append(k)
            k = self._prior_quarter(k)
        return list(reversed(window))

    def _ttm_window(self, series: dict, end: tuple, n: int = 4) -> dict | None:
        """TTM of a duration metric = sum of n consecutive standalone quarters."""
        window = self._trailing_window(set(series), end, n)
        if window is None:
            return None
        vals = [series[k]["value"] for k in window]
        if any(v is None for v in vals):
            return None
        units = {str(series[k].get("unit") or "").upper() for k in window}
        if len(units) != 1:
            return None
        input_ids: list[str] = []
        for key in window:
            fact = series[key]
            candidates = (
                [fact["canonical_fact_id"]]
                if fact.get("canonical_fact_id")
                else fact.get("input_ids") or []
            )
            for fact_id in candidates:
                if fact_id and fact_id not in input_ids:
                    input_ids.append(fact_id)
        return {
            "value": sum(vals),
            "window": window,
            "input_ids": input_ids,
        }

    @staticmethod
    def _ttm_dependencies(metric: str) -> tuple[str, ...] | None:
        direct = {
            "REVENUE", "NET_INCOME", "OPERATING_CASH_FLOW",
            "CAPITAL_EXPENDITURES", "GROSS_PROFIT", "OPERATING_INCOME",
        }
        if metric in direct:
            return (metric,)
        return {
            "FCF": ("OPERATING_CASH_FLOW", "CAPITAL_EXPENDITURES"),
            "FCF_MARGIN": ("OPERATING_CASH_FLOW", "CAPITAL_EXPENDITURES", "REVENUE"),
            "GROSS_MARGIN": ("GROSS_PROFIT", "REVENUE"),
            "OPERATING_MARGIN": ("OPERATING_INCOME", "REVENUE"),
            "NET_MARGIN": ("NET_INCOME", "REVENUE"),
        }.get(metric)

    def _missing_point(self, metric: str, frequency: str, status: str,
                       reason: str, end: tuple | None = None) -> MetricPoint:
        year, quarter = end or (None, None)
        label = f"FY{year}Q{quarter}" if year is not None and quarter is not None else None
        return MetricPoint(
            metric=metric,
            value=None,
            unit="ratio" if metric.endswith("MARGIN") else "USD",
            status=status,
            frequency=frequency,
            period_label=label,
            fiscal_year=year,
            fiscal_quarter=quarter,
            missing_reason=reason,
        )

    def current(self, metric: str, company_id: str,
                frequency: str = "quarterly") -> MetricPoint:
        """Return the current result without silently selecting an older window."""
        if frequency != "ttm":
            points = self.compute(metric, company_id, frequency=frequency)
            if points:
                return points[-1]
            return self._missing_point(metric, frequency, "MISSING_INPUT", "no observations")

        dependencies = self._ttm_dependencies(metric)
        if dependencies is None:
            return self._missing_point(
                metric, "ttm", "UNSUPPORTED", f"{metric} has no additive TTM definition"
            )

        loaded = self.load_facts(company_id, list(dependencies))
        series = {name: self.standalone_series(loaded[name]) for name in dependencies}
        all_keys = {key for values in series.values() for key in values if key[1] in (1, 2, 3, 4)}
        if not all_keys:
            return self._missing_point(metric, "ttm", "MISSING_INPUT", "no quarterly observations")

        end = max(all_keys)
        required: list[tuple] = []
        key = end
        for _ in range(4):
            required.append(key)
            key = self._prior_quarter(key)
        required.reverse()

        gaps: list[str] = []
        window_units: set[str] = set()
        period_ends: dict[tuple, set[str]] = {key: set() for key in required}
        for name, values in series.items():
            for key in required:
                fact = values.get(key)
                label = f"FY{key[0]}Q{key[1]}"
                if fact is None:
                    gaps.append(f"{name} missing {label}")
                    continue
                if fact.get("value") is None:
                    gaps.append(f"{name} null {label}")
                unit = fact.get("unit")
                if unit:
                    window_units.add(str(unit).upper())
                period_end = fact.get("period_end")
                if period_end:
                    period_ends[key].add(str(period_end)[:10])
        if len(window_units) > 1:
            gaps.append("unit mismatch: " + ", ".join(sorted(window_units)))
        for key, ends in period_ends.items():
            if len(ends) > 1:
                gaps.append(f"period mismatch FY{key[0]}Q{key[1]}")
        if gaps:
            return self._missing_point(metric, "ttm", "INCOMPLETE_PERIOD", "; ".join(gaps), end)

        point = next(
            (candidate for candidate in reversed(self.compute(metric, company_id, frequency="ttm"))
             if (candidate.fiscal_year, candidate.fiscal_quarter) == end),
            None,
        )
        if point is None:
            return self._missing_point(
                metric, "ttm", "INCOMPLETE_PERIOD", "current TTM formula inputs are incomplete", end
            )

        first_fact = series[dependencies[0]][required[0]]
        period_start = first_fact.get("period_start") or first_fact.get("period_end")
        current = replace(
            point,
            status="OK",
            frequency="ttm",
            period_start=str(period_start)[:10] if period_start else None,
            missing_reason=None,
            result_id=None,
        )
        return replace(current, result_id=derived_result_id(company_id, current))

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
        """TTM of a duration metric = sum of 4 *consecutive* standalone quarters.

        A missing quarter in the window yields None (never a partial sum).
        """
        series = self.standalone_series(facts)
        quarters = sorted((k for k in series if k[1] in (1, 2, 3, 4)), reverse=True)
        if not quarters:
            return None
        end = as_of_quarter or quarters[0]
        t = self._ttm_window(series, end)
        if t is None:
            return None
        return {
            "value": t["value"],
            "fiscal_year": end[0],
            "fiscal_quarter": end[1],
            "input_ids": t["input_ids"],
        }

    # ---------------- formula implementations ----------------

    @staticmethod
    def _annual_series(facts: list[dict]) -> dict[tuple, dict]:
        """Map (fiscal_year, None) -> latest-restated FY fact."""
        out: dict[tuple, dict] = {}
        for f in facts:
            if f.get("period_type") == "FY" and f.get("fiscal_year") is not None:
                key = (f["fiscal_year"], None)
                if key not in out or MetricEngine.restatement_key(f) > MetricEngine.restatement_key(out[key]):
                    out[key] = f
        return out

    def _two_series(self, num_facts: list[dict], den_facts: list[dict], freq: str):
        """Pair numerator/denominator by period key for quarterly/annual series.

        For `ttm` the caller must use the explicit TTM path (sum-of-quartet over
        sum-of-quartet); this method only serves `quarterly` and `annual`.
        """
        if freq == "quarterly":
            nums = self.standalone_series(num_facts)
            dens = self.standalone_series(den_facts)
        else:  # annual
            nums = self._annual_series(num_facts)
            dens = self._annual_series(den_facts)
        out = []
        for key, n in sorted(nums.items(), key=lambda kv: (kv[0][0] or 0, kv[0][1] or 0)):
            d = dens.get(key)
            if d is None or n.get("value") is None or d.get("value") is None:
                continue
            out.append((key, n, d))
        return out

    def compute(self, metric: str, company_id: str, frequency: str = "quarterly",
                limit: int | None = None, view: str = "latest_restated") -> list[MetricPoint]:
        freq = frequency if frequency in ("quarterly", "annual", "ttm") else "quarterly"
        points: list[MetricPoint] = []

        if metric == "REVENUE_GROWTH_YOY":
            rev = self.load_facts(company_id, ["REVENUE"])["REVENUE"]
            if freq == "quarterly":
                series = self.standalone_series(rev)
                keys = sorted(series, key=lambda k: (k[0] or 0, k[1] or 0))
                for i, k in enumerate(keys):
                    if i < 4:
                        continue
                    cur = series[k]
                    prev = series.get((k[0] - 1, k[1]))
                    if prev is None:
                        continue
                    value = (float(cur["value"]) / float(prev["value"]) - 1.0) if prev["value"] else None
                    points.append(self._point(metric, value, cur, "revenue_growth_yoy.v1",
                                              [cur.get("canonical_fact_id"), prev.get("canonical_fact_id")],
                                              freq, unit="ratio"))
            elif freq == "annual":
                series = self._annual_series(rev)
                for k in sorted(series, key=lambda k: (k[0] or 0, k[1] or 0)):
                    cur = series[k]
                    prev = series.get((k[0] - 1, None))
                    if prev is None:
                        continue
                    value = (float(cur["value"]) / float(prev["value"]) - 1.0) if prev["value"] else None
                    points.append(self._point(metric, value, cur, "revenue_growth_yoy.v1",
                                              [cur.get("canonical_fact_id"), prev.get("canonical_fact_id")],
                                              freq, unit="ratio"))
            else:  # ttm: two complete TTM windows 4 quarters apart (8 consecutive quarters)
                series = self.standalone_series(rev)
                keys = sorted((k for k in series if k[1] in (1, 2, 3, 4)))
                for k in keys:
                    window8 = self._trailing_window(set(series), k, 8)
                    if window8 is None:
                        continue
                    cur4, prev4 = window8[-4:], window8[:4]
                    cur_val = sum(float(series[x]["value"]) for x in cur4)
                    prev_val = sum(float(series[x]["value"]) for x in prev4)
                    if not prev_val:
                        continue
                    value = cur_val / prev_val - 1.0
                    input_ids = [series[x]["canonical_fact_id"] for x in window8]
                    points.append(self._point(metric, value, series[k], "revenue_growth_yoy.ttm.v1",
                                              input_ids, "ttm", unit="ratio"))
        elif metric in ("GROSS_MARGIN", "OPERATING_MARGIN", "NET_MARGIN"):
            num_metric = {"GROSS_MARGIN": "GROSS_PROFIT", "OPERATING_MARGIN": "OPERATING_INCOME",
                          "NET_MARGIN": "NET_INCOME"}[metric]
            facts = self.load_facts(company_id, [num_metric, "REVENUE"])
            if freq == "ttm":
                num_series = self.standalone_series(facts[num_metric])
                den_series = self.standalone_series(facts["REVENUE"])
                keys = sorted({k for k in num_series if k[1] in (1, 2, 3, 4)}
                              & {k for k in den_series if k[1] in (1, 2, 3, 4)})
                for key in keys:
                    nt = self._ttm_window(num_series, key)
                    dt = self._ttm_window(den_series, key)
                    if nt is None or dt is None or not dt["value"]:
                        continue
                    value = nt["value"] / dt["value"]
                    points.append(self._point(metric, value, num_series[key], f"{metric.lower()}.ttm.v1",
                                              nt["input_ids"] + dt["input_ids"], "ttm", unit="ratio"))
            else:
                for key, n, d in self._two_series(facts[num_metric], facts["REVENUE"], freq):
                    inputs = [n.get("canonical_fact_id"), d.get("canonical_fact_id")]
                    if float(d["value"]) == 0:
                        point = self._point(metric, None, n, f"{metric.lower()}.v1", inputs, freq,
                                            unit="ratio")
                        point.status = "UNAVAILABLE"
                        point.missing_reason = "REVENUE denominator is zero"
                        points.append(point)
                    else:
                        points.append(self._point(metric, float(n["value"]) / float(d["value"]), n,
                                                  f"{metric.lower()}.v1", inputs, freq, unit="ratio"))
        elif metric in ("FCF", "FCF_MARGIN"):
            facts = self.load_facts(company_id, ["OPERATING_CASH_FLOW", "CAPITAL_EXPENDITURES", "REVENUE"])
            ocf_facts = facts["OPERATING_CASH_FLOW"]
            capex_facts = facts["CAPITAL_EXPENDITURES"]
            rev_facts = facts["REVENUE"]
            if freq == "ttm":
                ocf_series = self.standalone_series(ocf_facts)
                capex_series = self.standalone_series(capex_facts)
                rev_series = self.standalone_series(rev_facts)
                keys = sorted({k for k in ocf_series if k[1] in (1, 2, 3, 4)}
                              & {k for k in capex_series if k[1] in (1, 2, 3, 4)})
                for key in keys:
                    ot = self._ttm_window(ocf_series, key)
                    ct = self._ttm_window(capex_series, key)
                    if ot is None or ct is None:
                        continue
                    fcf = ot["value"] - ct["value"]
                    if metric == "FCF":
                        points.append(self._point("FCF", fcf, ocf_series[key], "fcf.ttm.v1",
                                                  ot["input_ids"] + ct["input_ids"], "ttm", unit="USD"))
                    else:
                        rt = self._ttm_window(rev_series, key)
                        if rt is None or not rt["value"]:
                            continue
                        points.append(self._point("FCF_MARGIN", fcf / rt["value"], ocf_series[key],
                                                  "fcf_margin.ttm.v1",
                                                  ot["input_ids"] + ct["input_ids"] + rt["input_ids"], "ttm",
                                                  unit="ratio"))
            else:
                ocf = self.standalone_series(ocf_facts) if freq == "quarterly" else self._annual_series(ocf_facts)
                capex = self.standalone_series(capex_facts) if freq == "quarterly" else self._annual_series(capex_facts)
                rev_series = self.standalone_series(rev_facts) if freq == "quarterly" else self._annual_series(rev_facts)
                for key in sorted(set(ocf) & set(capex), key=lambda k: (k[0] or 0, k[1] or 0)):
                    o, c = ocf[key], capex[key]
                    fcf = float(o["value"]) - float(c["value"])
                    if metric == "FCF":
                        points.append(self._point("FCF", fcf, o, "fcf.v1",
                                                  [o.get("canonical_fact_id"), c.get("canonical_fact_id")], freq,
                                                  unit="USD"))
                    else:
                        r = rev_series.get(key)
                        if r and r["value"]:
                            points.append(self._point("FCF_MARGIN", fcf / float(r["value"]), o, "fcf_margin.v1",
                                                      [o.get("canonical_fact_id"), c.get("canonical_fact_id"),
                                                       r.get("canonical_fact_id")], freq, unit="ratio"))
        elif metric == "NET_DEBT":
            # Net-debt bridge = (LT noncurrent + LT current + ST borrowings +
            # commercial paper) - cash - ST investments, all on ONE balance-sheet
            # date. us-gaap:LongTermDebt (total) is excluded because it overlaps
            # the noncurrent + current split (double count).
            debt_core = ("LONG_TERM_DEBT", "LONG_TERM_DEBT_CURRENT")
            debt_optional = ("SHORT_TERM_BORROWINGS", "COMMERCIAL_PAPER")
            facts = self.load_facts(company_id, list(debt_core) + list(debt_optional)
                                    + ["CASH_AND_EQUIVALENTS", "SHORT_TERM_INVESTMENTS"])
            # Latest-restated value per balance-sheet date so the bridge is
            # computed on ONE coherent date (never splicing across dates).
            by_date: dict[str, dict[str, dict]] = {}
            for name in debt_core + debt_optional + ("CASH_AND_EQUIVALENTS", "SHORT_TERM_INVESTMENTS"):
                for f in facts[name]:
                    d = f.get("instant_date") or f.get("period_end")
                    if not d:
                        continue
                    slot = by_date.setdefault(d, {})
                    cur = slot.get(name)
                    if cur is None or self.restatement_key(f) > self.restatement_key(cur):
                        slot[name] = f
            required = ("LONG_TERM_DEBT", "LONG_TERM_DEBT_CURRENT",
                        "CASH_AND_EQUIVALENTS", "SHORT_TERM_INVESTMENTS")
            chosen = None
            for d in sorted(by_date, reverse=True):
                if all(name in by_date[d] for name in required):
                    chosen = d
                    break
            if chosen is None:
                return points  # incomplete net-debt bridge: gap, never a silent value
            c = by_date[chosen]
            lt = c["LONG_TERM_DEBT"]
            ltc = c["LONG_TERM_DEBT_CURRENT"]
            cash = c["CASH_AND_EQUIVALENTS"]
            inv = c["SHORT_TERM_INVESTMENTS"]
            stb = c.get("SHORT_TERM_BORROWINGS")
            cp = c.get("COMMERCIAL_PAPER")
            total_debt = float(lt["value"]) + float(ltc["value"])
            if stb is not None:
                total_debt += float(stb["value"])
            if cp is not None:
                total_debt += float(cp["value"])
            value = total_debt - float(cash["value"]) - float(inv["value"])
            input_ids = [f["canonical_fact_id"] for f in (lt, ltc, stb, cp, cash, inv) if f is not None]
            points.append(self._point("NET_DEBT", value, cash, "net_debt.v2", input_ids, freq, unit="USD"))
        elif metric in ("REVENUE", "GROSS_PROFIT", "OPERATING_INCOME", "NET_INCOME",
                        "OPERATING_CASH_FLOW", "CAPITAL_EXPENDITURES", "DILUTED_EPS",
                        "BASIC_EPS", "DILUTED_WEIGHTED_AVG_SHARES", "BASIC_WEIGHTED_AVG_SHARES",
                        "SHARE_REPURCHASES", "DIVIDENDS_PAID", "SHARE_BASED_COMPENSATION",
                        "DEPRECIATION_AMORTIZATION", "DEPRECIATION",
                        "AMORTIZATION_OF_INTANGIBLE_ASSETS", "PRETAX_INCOME",
                        "INCOME_TAX_EXPENSE", "COST_OF_REVENUE"):
            # passthrough canonical metrics (with standalone-quarter derivation for cash flow)
            facts = self.load_facts(company_id, [metric])[metric]
            if freq == "ttm":
                series = self.standalone_series(facts)
                keys = sorted((k for k in series if k[1] in (1, 2, 3, 4)))
                for key in keys:
                    f = series[key]
                    # TTM summing is only meaningful for additive currency
                    # metrics; per-share ratios (EPS) and share counts are NOT
                    # summed quarter-over-quarter (D06).
                    if str(f.get("unit") or "").upper() != "USD":
                        continue
                    t = self._ttm_window(series, key)
                    if t is None:
                        continue
                    points.append(self._point(metric, t["value"], f, "ttm.v2",
                                              t["input_ids"], "ttm", unit="USD"))
                return points
            series = self.standalone_series(facts) if freq == "quarterly" else self._annual_series(facts)
            for key in sorted(series, key=lambda k: (k[0] or 0, k[1] or 0)):
                f = series[key]
                formula_id = f.get("formula_id") or (
                    f.get("mapping_rule_id") if f.get("status") == "CALCULATED" else None
                )
                raw_inputs = f.get("input_ids")
                if not raw_inputs and f.get("source_raw_fact_ids"):
                    source_ids = f["source_raw_fact_ids"]
                    raw_inputs = json.loads(source_ids) if isinstance(source_ids, str) else list(source_ids)
                input_ids = raw_inputs or [f.get("canonical_fact_id")]
                points.append(self._point(metric, float(f["value"]), f, formula_id, input_ids, freq,
                                          fact_id=f.get("canonical_fact_id")))
        else:
            raise ValueError(f"Metric {metric!r} not implemented in metric engine")

        points.sort(key=lambda p: (p.fiscal_year or 0, p.fiscal_quarter or 0))
        for p in points:
            if p.canonical_fact_id is None and p.input_fact_ids:
                p.result_id = derived_result_id(company_id, p)
        if limit:
            points = points[-limit:]
        return points

    def _point(self, metric, value, fact, formula_id, input_ids, freq,
               fact_id=None, unit=None) -> MetricPoint:
        label = f"FY{fact.get('fiscal_year')}" if freq == "annual" or fact.get("period_type") == "FY" \
            else f"FY{fact.get('fiscal_year')}Q{fact.get('fiscal_quarter')}"
        period_start = fact.get("period_start")
        period_end = fact.get("period_end") or fact.get("instant_date")
        return MetricPoint(
            metric=metric,
            value=value,
            canonical_fact_id=fact_id,
            unit=unit if unit is not None else fact.get("unit"),
            status="CALCULATED" if formula_id else fact.get("status"),
            formula_id=formula_id,
            formula_version=formula_id,
            input_fact_ids=input_ids,
            period_label=label,
            frequency=freq,
            period_start=str(period_start)[:10] if period_start else None,
            period_end=str(period_end)[:10] if period_end else None,
            fiscal_year=fact.get("fiscal_year"),
            fiscal_quarter=fact.get("fiscal_quarter"),
        )
