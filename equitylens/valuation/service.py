"""Valuation service: assumptions, scenarios, sensitivity, reverse DCF, runs.

Every run persists (model_version, assumptions, fact snapshot, output) so it
can be reproduced exactly (docs/06 §11).
"""

from __future__ import annotations

import hashlib
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
    return DcfInputs(**{k: value for k, value in d.items() if k in DcfInputs.__dataclass_fields__})


def valuation_input_fingerprint(inputs: DcfInputs | dict) -> str:
    """Deterministic SHA-256 over the complete executed inputs (V03).

    Accepts a ``DcfInputs`` dataclass or its already-serialized dict form; both
    canonicalize identically (sort_keys + compact separators + no NaN) so a
    response fingerprint can be recomputed from the returned input object.
    """
    data = asdict(inputs) if isinstance(inputs, DcfInputs) else inputs
    canonical = json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _source_fact_ids(meta: dict) -> dict[str, list[str]]:
    """Freeze the exact canonical identities behind every fact-derived input."""
    return {
        key: list(value.get("fact_ids") or [])
        for key, value in meta.items()
        if isinstance(value, dict) and value.get("fact_ids")
    }


def default_valuation(store, company_id: str, ticker: str) -> dict:
    rf = risk_free_rate()
    inputs, meta = default_assumption_set(store, company_id, ticker, risk_free=rf["value"])
    meta["risk_free"] = rf
    output = run_dcf(inputs)
    from equitylens.market.service import valuation_market_block

    scenarios = scenario_valuation(inputs, ticker)
    return {
        "ticker": ticker,
        "input_fingerprint": valuation_input_fingerprint(inputs),
        "model_version": dcf_mod.MODEL_VERSION,
        "market": valuation_market_block(store, company_id, ticker, round(output.fair_value_per_share, 2)),
        "risk_free": rf,
        "assumptions": {"inputs": _inputs_dict(inputs), "meta": meta},
        "result": _output_dict(output),
        "scenarios": scenarios,
        "sensitivity": sensitivity(inputs),
        "model_quality": model_quality_block(meta, output, scenarios),
        "reproducible": True,
    }


def scenario_valuation(base: DcfInputs, ticker: str) -> dict:
    """Bear / Base / Bull assumption sets (docs/06 §6).

    Each scenario validates independently: one scenario that cannot be computed
    (e.g. its WACC/terminal-growth offset hits the guardrail) is reported as
    unavailable with a reason, never a whole-request failure.
    """
    def make(g, m, w, t, label) -> dict:
        trial = DcfInputs(
            revenue_base=base.revenue_base,
            revenue_growth=g,
            op_margin_start=base.op_margin_start,
            op_margin_end=m,
            tax_rate=base.tax_rate, da_pct=base.da_pct, capex_pct=base.capex_pct,
            nwc_pct=base.nwc_pct, wacc=w, terminal_growth=t,
            net_cash=base.net_cash, shares=base.shares, terminal_roic=base.terminal_roic,
        )
        try:
            result = _output_dict(run_dcf(trial))
            return {"label": label, "inputs": _inputs_dict(trial), "result": result,
                    "status": "OK", "reason": None}
        except dcf_mod.ValuationError as exc:
            return {"label": label, "inputs": _inputs_dict(trial), "result": None,
                    "status": "UNAVAILABLE", "reason": str(exc)}

    base_m = base.op_margin_end
    bear_g, bull_g = _bear_bull_growth(base.revenue_growth)
    return {
        "bear": make(bear_g, max(0.0, base_m - 0.02), min(0.15, base.wacc + 0.01), max(0.005, base.terminal_growth - 0.005), "Bear"),
        "base": make(list(base.revenue_growth), base_m, base.wacc, base.terminal_growth, "Base"),
        "bull": make(bull_g, base_m + 0.02, max(0.05, base.wacc - 0.005), base.terminal_growth + 0.005, "Bull"),
    }


def _bear_bull_growth(base_growth: list[float]) -> tuple[list[float], list[float]]:
    """Sign-aware Bear/Bull growth paths.

    Bear is always WORSE (lower growth) and Bull always BETTER (higher growth),
    even when the base growth is negative — a mechanical ×0.5/×1.5 would invert
    the 悲观/乐观 labels for negative base growth (P03).
    """
    bear: list[float] = []
    bull: list[float] = []
    for g in base_growth:
        span = abs(g) * 0.5
        bear.append(g - span)
        bull.append(g + span)
    return bear, bull


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
                net_cash=base.net_cash, shares=base.shares, terminal_roic=base.terminal_roic,
            )
            try:
                fair = run_dcf(trial).fair_value_per_share
            except dcf_mod.ValuationError:
                fair = None
            row["values"].append(fair)
        rows.append(row)
    return {"wacc_grid": waccs, "terminal_grid": gs, "rows": rows}


def model_quality_block(meta: dict, output, scenarios: dict) -> dict:
    """P03: structured model-quality signals.

    Reports data completeness, which inputs are estimates (not SEC facts),
    terminal-value dependence and bear/bull dispersion. This is a model-quality
    statement — NOT the probability that the price is correct.
    """
    estimated: list[str] = []
    for k, v in (meta or {}).items():
        src = (v.get("source") or "") if isinstance(v, dict) else ""
        low = src.lower()
        if "assumption" in low or "user_override" in low or "override" in low:
            estimated.append(k)

    bear_res = (scenarios.get("bear") or {}).get("result") or {}
    bull_res = (scenarios.get("bull") or {}).get("result") or {}
    base_res = (scenarios.get("base") or {}).get("result") or {}
    dispersion = None
    b = bear_res.get("fair_value_per_share")
    bl = bull_res.get("fair_value_per_share")
    bb = base_res.get("fair_value_per_share")
    if b is not None and bl is not None and bb:
        dispersion = round((bl - b) / bb, 3)

    return {
        "data_completeness": "partial" if estimated else "complete",
        "estimated_inputs": estimated,
        "terminal_value_share": round(float(output.terminal_value_share), 3),
        "scenario_dispersion": dispersion,
        "applicability": "成熟高质量科技公司适用；银行/REIT/亏损成长等类型不直接套用此 DCF。",
        "note": "模型质量反映数据完整性与假设依赖，不是价格正确的概率。",
    }


def run_custom(store, company_id: str, ticker: str, payload: dict, persist: bool = True) -> dict:
    """POST /valuation/run: full deterministic recomputation.

    With ``persist=False`` the run is computed but NOT written (drag previews);
    only an explicit save persists a run.
    """
    rf = risk_free_rate()
    base, meta = default_assumption_set(store, company_id, ticker, risk_free=rf["value"])
    meta["risk_free"] = rf
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
            terminal_roic=float(a.get("terminal_roic", base.terminal_roic)),
        )
        # meta must reflect the FINAL executed inputs, marking user overrides.
        _override_meta = {
            "wacc": "wacc", "terminal_growth": "terminal_growth",
            "op_margin_start": "op_margin_start", "op_margin_end": "op_margin",
            "revenue_growth": "revenue_growth",
            "tax_rate": "tax_rate", "net_cash": "net_cash", "shares": "shares",
            "da_pct": "da_pct", "capex_pct": "capex_pct", "revenue_base": "revenue_base",
            "nwc_pct": "nwc_pct",
            "terminal_roic": "terminal_roic",
        }
        for field, meta_key in _override_meta.items():
            if field in a:
                meta.setdefault(meta_key, {})["value"] = a[field]
                meta[meta_key]["source"] = "user_override"
                meta[meta_key]["fact_ids"] = []
    output = run_dcf(base)
    # Build the complete response before persisting so an invalid sub-scenario
    # can never leave a half-written run behind (atomic write-after-compute).
    scenarios = scenario_valuation(base, ticker)
    sens = sensitivity(base)
    mq_block = model_quality_block(meta, output, scenarios)
    fingerprint = valuation_input_fingerprint(base)
    from equitylens.market.service import latest_quote_row

    market_row = latest_quote_row(store, company_id)
    market_observation_id = market_row["quote_id"] if market_row else None
    run = {
        "valuation_run_id": f"run_{uuid.uuid4().hex[:12]}",
        "company_id": company_id,
        "model_name": "FCFF_DCF",
        "model_version": dcf_mod.MODEL_VERSION,
        "run_at": _now(),
        "market_observation_id": market_observation_id,
        "assumption_set_id": payload.get("assumption_set_id") or f"aset_{uuid.uuid4().hex[:8]}",
        "fact_snapshot_json": json.dumps({
            "inputs": _inputs_dict(base), "meta": meta,
            "source_fact_ids": _source_fact_ids(meta),
        }, ensure_ascii=False),
        "output_json": json.dumps(_output_dict(output), ensure_ascii=False),
        "warnings_json": json.dumps(output.warnings, ensure_ascii=False),
        "input_fingerprint": fingerprint,
        "scenarios_json": json.dumps(scenarios, ensure_ascii=False),
        "sensitivity_json": json.dumps(sens, ensure_ascii=False),
        "model_quality_json": json.dumps(mq_block, ensure_ascii=False),
    }
    if persist:
        _persist_run(store, run)
    from equitylens.market.service import valuation_market_block

    return {
        "ticker": ticker,
        "valuation_run_id": run["valuation_run_id"] if persist else None,
        "input_fingerprint": fingerprint,
        "model_version": dcf_mod.MODEL_VERSION,
        "run_at": run["run_at"],
        "risk_free": rf,
        "market": valuation_market_block(store, company_id, ticker, round(output.fair_value_per_share, 2)),
        "assumptions": {"inputs": _inputs_dict(base), "meta": meta},
        "result": _output_dict(output),
        "scenarios": scenarios,
        "sensitivity": sens,
        "model_quality": mq_block,
        "warnings": output.warnings,
        "reproducible": True,
    }


def reverse_dcf(store, company_id: str, ticker: str, payload: dict) -> dict:
    rf = risk_free_rate()
    base, meta = default_assumption_set(store, company_id, ticker, risk_free=rf["value"])
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
            terminal_roic=float(a.get("terminal_roic", base.terminal_roic)),
        )
    target = float(payload.get("target_price"))
    implied = implied_growth(base, target)
    from equitylens.market.service import valuation_market_block
    from equitylens.metrics.engine import MetricEngine

    hist = MetricEngine(store)
    rev_pts = hist.compute("REVENUE", company_id, frequency="annual")
    annual = [p.value for p in rev_pts if p.value][-6:]
    hist_cagr = None
    if len(annual) >= 2 and annual[0]:
        hist_cagr = (annual[-1] / annual[0]) ** (1 / (len(annual) - 1)) - 1.0
    return {
        "model_version": dcf_mod.MODEL_VERSION,
        "implied_revenue_cagr": implied,
        "target_price": target,
        "market": valuation_market_block(store, company_id, ticker, fair_value_per_share=None),
        "historical_revenue_cagr": hist_cagr,
        "fixed_assumptions": {"wacc": base.wacc, "terminal_growth": base.terminal_growth,
                              "terminal_roic": base.terminal_roic,
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
        "terminal_forecast": output.terminal_forecast,
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


# --- P06: personal reference-price plans -------------------------------------
# 参考价 = 选定每股估值 × (1 − 安全边际). Research reference only; no orders.

def create_plan(store, company_id: str, ticker: str, payload: dict) -> dict:
    """Create (and immediately persist) a personal reference-price plan.

    The reference price is the SELECTED per-share value (a model/scenario
    output) times (1 - margin_of_safety). A zero/negative reference value is
    kept for research but produces no buyable reference price.
    """
    if payload.get("reference_value") is None:
        raise ValueError("必须选择一个参考值（reference_value）")
    ref = float(payload["reference_value"])
    if payload.get("margin_of_safety") is None:
        raise ValueError("必须显式设置安全边际（margin_of_safety，0 表示无边际）")
    margin = float(payload["margin_of_safety"])
    if margin < 0 or margin >= 1.0:
        raise ValueError("安全边际必须在 [0, 1) 区间（负值或 ≥100% 不接受）")

    price = None
    reason = None
    if ref > 0:
        price = ref * (1 - margin)
    else:
        reason = "参考值为 0 或负数，不生成可买入参考价（仅供研究）"

    plan_id = f"plan_{uuid.uuid4().hex[:12]}"
    row = {
        "plan_id": plan_id, "company_id": company_id, "ticker": ticker,
        "name": payload.get("name") or "未命名方案",
        "reference_value": ref,
        "reference_source": payload.get("reference_source"),
        "margin_of_safety": margin,
        "reference_price": price,
        "notes": payload.get("notes"),
        "assumptions_json": json.dumps(payload.get("assumptions") or {}, ensure_ascii=False),
        "created_at": _now(),
    }
    store.connect()
    cols = list(row.keys())
    placeholders = ", ".join("?" for _ in cols)
    store._conn.execute(
        f"INSERT INTO valuation_plan ({', '.join(cols)}) VALUES ({placeholders})",
        [row[c] for c in cols],
    )
    out = dict(row)
    out["assumptions_json"] = payload.get("assumptions") or {}
    if reason:
        out["reference_price_reason"] = reason
    return out


def list_plans(store, company_id: str) -> list[dict]:
    store.connect()
    rows = store.query(
        "SELECT * FROM valuation_plan WHERE company_id = ? ORDER BY created_at DESC",
        [company_id],
    )
    for r in rows:
        r["assumptions_json"] = json.loads(r.get("assumptions_json") or "{}")
    return rows


def get_plan(store, company_id: str, plan_id: str) -> dict | None:
    store.connect()
    row = store.query_one(
        "SELECT * FROM valuation_plan WHERE plan_id = ? AND company_id = ?",
        [plan_id, company_id],
    )
    if row:
        row["assumptions_json"] = json.loads(row.get("assumptions_json") or "{}")
    return row
