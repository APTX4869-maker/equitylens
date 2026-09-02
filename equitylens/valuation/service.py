"""Valuation service: assumptions, scenarios, sensitivity, reverse DCF, runs.

Every run persists (model_version, assumptions, fact snapshot, output) so it
can be reproduced exactly (docs/06 §11).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from equitylens.storage.duckdb_store import DuckDBStore
from equitylens.valuation import dcf as dcf_mod
from equitylens.valuation.dcf import DcfInputs, run_dcf, implied_growth
from equitylens.valuation.defaults import default_assumption_set
from equitylens.valuation.rates import risk_free_rate


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _inputs_dict(i: DcfInputs) -> dict:
    return asdict(i)


def _inputs_from_dict(d: dict) -> DcfInputs:
    return DcfInputs(**{k: d[k] for k in DcfInputs.__dataclass_fields__})


def default_valuation(store, company_id: str, ticker: str) -> dict:
    rf = risk_free_rate()
    inputs, meta = default_assumption_set(store, company_id, ticker, risk_free=rf["value"])
    meta["risk_free"] = rf
    output = run_dcf(inputs)
    return {
        "ticker": ticker,
        "model_version": dcf_mod.MODEL_VERSION,
        "market": {"status": "UNAVAILABLE", "reason": "market-data provider not configured"},
        "risk_free": rf,
        "assumptions": {"inputs": _inputs_dict(inputs), "meta": meta},
        "result": _output_dict(output),
        "scenarios": scenario_valuation(inputs, ticker),
        "sensitivity": sensitivity(inputs),
        "reproducible": True,
    }


def scenario_valuation(base: DcfInputs, ticker: str) -> dict:
    """Bear / Base / Bull assumption sets (docs/06 §6)."""
    def make(g, m, w, t, label) -> dict:
        trial = DcfInputs(
            revenue_base=base.revenue_base,
            revenue_growth=g,
            op_margin_start=base.op_margin_start,
            op_margin_end=m,
            tax_rate=base.tax_rate, da_pct=base.da_pct, capex_pct=base.capex_pct,
            nwc_pct=base.nwc_pct, wacc=w, terminal_growth=t,
            net_cash=base.net_cash, shares=base.shares,
        )
        return {"label": label, "inputs": _inputs_dict(trial), "result": _output_dict(run_dcf(trial))}

    base_m = base.op_margin_end
    bear_g = [g * 0.5 for g in base.revenue_growth]
    bull_g = [g * 1.5 for g in base.revenue_growth]
    return {
        "bear": make(bear_g, max(0.0, base_m - 0.02), min(0.15, base.wacc + 0.01), max(0.005, base.terminal_growth - 0.005), "Bear"),
        "base": make(list(base.revenue_growth), base_m, base.wacc, base.terminal_growth, "Base"),
        "bull": make(bull_g, base_m + 0.02, max(0.05, base.wacc - 0.005), base.terminal_growth + 0.005, "Bull"),
    }


def sensitivity(base: DcfInputs) -> dict:
    """Full recalculation over WACC x terminal growth grid (docs/06 §7)."""
    waccs = [base.wacc - 0.01, base.wacc - 0.005, base.wacc, base.wacc + 0.005, base.wacc + 0.01]
    gs = [base.terminal_growth - 0.005, base.terminal_growth - 0.0025,
          base.terminal_growth, base.terminal_growth + 0.0025, base.terminal_growth + 0.005]
    rows = []
    for w in waccs:
        row = {"wacc": w, "values": []}
        for g in gs:
            trial = DcfInputs(
                revenue_base=base.revenue_base, revenue_growth=base.revenue_growth,
                op_margin_start=base.op_margin_start, op_margin_end=base.op_margin_end,
                tax_rate=base.tax_rate, da_pct=base.da_pct, capex_pct=base.capex_pct,
                nwc_pct=base.nwc_pct, wacc=w, terminal_growth=g,
                net_cash=base.net_cash, shares=base.shares,
            )
            try:
                fair = run_dcf(trial).fair_value_per_share
            except dcf_mod.ValuationError:
                fair = None
            row["values"].append(fair)
        rows.append(row)
    return {"wacc_grid": waccs, "terminal_grid": gs, "rows": rows}


def run_custom(store, company_id: str, ticker: str, payload: dict) -> dict:
    """POST /valuation/run: full deterministic recomputation."""
    base, meta = default_assumption_set(store, company_id, ticker)
    if "assumptions" in payload and payload["assumptions"]:
        a = payload["assumptions"]
        base = DcfInputs(
            revenue_base=float(a.get("revenue_base", base.revenue_base)),
            revenue_growth=[float(x) for x in a.get("revenue_growth", base.revenue_growth)],
            op_margin_start=float(a.get("op_margin_start", base.op_margin_start)),
            op_margin_end=float(a.get("op_margin_end", base.op_margin_end)),
            tax_rate=float(a.get("tax_rate", base.tax_rate)),
            da_pct=float(a.get("da_pct", base.da_pct)),
            capex_pct=float(a.get("capex_pct", base.capex_pct)),
            nwc_pct=float(a.get("nwc_pct", base.nwc_pct)),
            wacc=float(a.get("wacc", base.wacc)),
            terminal_growth=float(a.get("terminal_growth", base.terminal_growth)),
            net_cash=float(a.get("net_cash", base.net_cash)),
            shares=float(a.get("shares", base.shares)),
        )
    output = run_dcf(base)
    run = {
        "valuation_run_id": f"run_{uuid.uuid4().hex[:12]}",
        "company_id": company_id,
        "model_name": "FCFF_DCF",
        "model_version": dcf_mod.MODEL_VERSION,
        "run_at": _now(),
        "market_observation_id": None,
        "assumption_set_id": payload.get("assumption_set_id") or f"aset_{uuid.uuid4().hex[:8]}",
        "fact_snapshot_json": json.dumps({"inputs": _inputs_dict(base), "meta": meta}, ensure_ascii=False),
        "output_json": json.dumps(_output_dict(output), ensure_ascii=False),
        "warnings_json": json.dumps(output.warnings, ensure_ascii=False),
    }
    _persist_run(store, run)
    return {
        "valuation_run_id": run["valuation_run_id"],
        "model_version": dcf_mod.MODEL_VERSION,
        "run_at": run["run_at"],
        "assumptions": {"inputs": _inputs_dict(base), "meta": meta},
        "result": _output_dict(output),
        "scenarios": scenario_valuation(base, ticker),
        "sensitivity": sensitivity(base),
        "warnings": output.warnings,
        "reproducible": True,
    }


def reverse_dcf(store, company_id: str, ticker: str, payload: dict) -> dict:
    base, meta = default_assumption_set(store, company_id, ticker)
    a = payload.get("assumptions") or {}
    if a:
        base = DcfInputs(
            revenue_base=float(a.get("revenue_base", base.revenue_base)),
            revenue_growth=[float(x) for x in a.get("revenue_growth", base.revenue_growth)],
            op_margin_start=float(a.get("op_margin_start", base.op_margin_start)),
            op_margin_end=float(a.get("op_margin_end", base.op_margin_end)),
            tax_rate=float(a.get("tax_rate", base.tax_rate)),
            da_pct=float(a.get("da_pct", base.da_pct)),
            capex_pct=float(a.get("capex_pct", base.capex_pct)),
            nwc_pct=float(a.get("nwc_pct", base.nwc_pct)),
            wacc=float(a.get("wacc", base.wacc)),
            terminal_growth=float(a.get("terminal_growth", base.terminal_growth)),
            net_cash=float(a.get("net_cash", base.net_cash)),
            shares=float(a.get("shares", base.shares)),
        )
    target = float(payload.get("target_price"))
    implied = implied_growth(base, target)
    from equitylens.metrics.engine import MetricEngine

    hist = MetricEngine(store)
    rev_pts = hist.compute("REVENUE", company_id, frequency="annual")
    annual = [p.value for p in rev_pts if p.value][-6:]
    hist_cagr = None
    if len(annual) >= 2 and annual[0]:
        hist_cagr = (annual[-1] / annual[0]) ** (1 / (len(annual) - 1)) - 1.0
    return {
        "implied_revenue_cagr": implied,
        "target_price": target,
        "historical_revenue_cagr": hist_cagr,
        "fixed_assumptions": {"wacc": base.wacc, "terminal_growth": base.terminal_growth,
                              "margin_end": base.op_margin_end, "tax_rate": base.tax_rate},
        "interpretation": None if implied is None else (
            f"市场隐含 5Y 收入 CAGR {implied*100:.1f}% "
            f"{'高于' if hist_cagr is not None and implied > hist_cagr else '低于或接近'}历史 {hist_cagr*100:.1f}%"
            if hist_cagr is not None else ""
        ),
        "no_root_reason": None if implied is not None else "目标价超出当前假设下可实现区间（无根）",
    }


def _output_dict(output) -> dict:
    return {
        "fair_value_per_share": round(output.fair_value_per_share, 2),
        "enterprise_value": output.enterprise_value,
        "equity_value": output.equity_value,
        "terminal_value": output.terminal_value,
        "pv_terminal": output.pv_terminal,
        "sum_pv_fcff": output.sum_pv_fcff,
        "net_cash": output.net_cash,
        "terminal_value_share": output.terminal_value_share,
        "forecast": [
            {"year": f.year, "revenue": f.revenue, "op_margin": f.op_margin,
             "fcff": f.fcff, "pv_fcff": f.pv_fcff}
            for f in output.forecast
        ],
        "warnings": output.warnings,
        "model_version": output.model_version,
    }


def _persist_run(store, run: dict) -> None:
    store.connect()
    cols = list(run.keys())
    placeholders = ", ".join("?" for _ in cols)
    store._conn.execute(
        f"INSERT INTO valuation_run ({', '.join(cols)}) VALUES ({placeholders})",
        [run[c] for c in cols],
    )
