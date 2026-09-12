"""Valuation service: assumptions, scenarios, sensitivity, reverse DCF, runs.

Every run persists (model_version, assumptions, fact snapshot, output) so it
can be reproduced exactly (docs/06 §11).
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from equitylens.storage.duckdb_store import DuckDBStore
from equitylens.publication.models import canonical_json, sha256_json
from equitylens.publication.repository import PublicationConflict, PublicationRepository
from equitylens.valuation import dcf as dcf_mod
from equitylens.valuation.dcf import DcfInputs, ValuationError, implied_growth, run_dcf, validate
from equitylens.valuation.defaults import default_assumption_set, load_valuation_config
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


def valuation_confirmation_fingerprint(
    *, security_id: str, publication_id: str, model_version: str, assumptions: dict
) -> str:
    return sha256_json(
        {
            "security_id": security_id,
            "publication_id": publication_id,
            "model_version": model_version,
            "assumptions": assumptions,
        }
    )


def _valuation_error(code: str, message: str, field: str | None = None):
    raise ValuationError(code, message, field)


def confirm_valuation_profile(
    store,
    *,
    company_id: str,
    security_id: str,
    publication_id: str,
    model_version: str,
    assumptions: dict,
    confirmed: bool,
) -> dict:
    """Validate and optionally persist an identity-bound valuation confirmation."""
    security = store.query_one(
        "SELECT * FROM security WHERE security_id=? AND company_id=? AND status='ACTIVE'",
        [security_id, company_id],
    )
    if security is None:
        _valuation_error("VALUATION_SECURITY_MISMATCH", "security does not belong to company")
    try:
        context = PublicationRepository(store).context(company_id, publication_id)
    except PublicationConflict as exc:
        _valuation_error("VALUATION_PUBLICATION_MISMATCH", str(exc))
    if model_version != dcf_mod.MODEL_VERSION:
        _valuation_error("VALUATION_MODEL_UNSUPPORTED", "valuation model version is unsupported")
    company = store.query_one(
        "SELECT reporting_template FROM company WHERE company_id=?", [company_id]
    )
    if company is None or company["reporting_template"] != "us_gaap_operating_v1":
        _valuation_error(
            "VALUATION_MODEL_UNSUPPORTED",
            "no validated valuation model exists for this reporting template",
        )
    capability = store.query_one(
        "SELECT status, reason FROM company_capability WHERE publication_id=? AND module='financials'",
        [publication_id],
    )
    if capability and capability["status"] != "READY":
        _valuation_error(
            "VALUATION_DATA_BLOCKED",
            capability.get("reason") or "published financial data is unavailable",
        )
    facts = PublicationRepository(store).facts(context)
    currencies = {
        str(fact.get("unit"))
        for fact in facts
        if len(str(fact.get("unit") or "")) == 3
        and str(fact.get("unit")).isalpha()
    }
    if currencies and security["currency"] not in currencies:
        _valuation_error(
            "VALUATION_CURRENCY_MISMATCH",
            "financial statement and security quote currencies are not verified as compatible",
        )
    evidence = security.get("identity_evidence_json") or {}
    if isinstance(evidence, str):
        evidence = json.loads(evidence)
    if security["instrument_type"] == "ADR" and not evidence.get("adr_ratio"):
        _valuation_error(
            "VALUATION_ADR_RATIO_UNKNOWN", "ADR conversion ratio is not verified"
        )
    security_count = store.query_one(
        "SELECT count(*) AS n FROM security WHERE company_id=? AND status='ACTIVE'",
        [company_id],
    )["n"]
    if security_count > 1 and assumptions.get("share_basis_security_id") != security_id:
        _valuation_error(
            "VALUATION_SHARE_BASIS_UNVERIFIED",
            "issuer-level share count cannot be paired with one security price",
        )
    try:
        inputs = _inputs_from_dict(assumptions)
        validate(inputs)
    except TypeError as exc:
        _valuation_error("INVALID_ASSUMPTION", f"complete DCF assumptions are required: {exc}")

    assumptions_hash = sha256_json(assumptions)
    fingerprint = valuation_confirmation_fingerprint(
        security_id=security_id,
        publication_id=publication_id,
        model_version=model_version,
        assumptions=assumptions,
    )
    status_value = "CONFIRMED" if confirmed else "DRAFT"
    existing = store.query_one(
        """
        SELECT * FROM valuation_assumption_set
        WHERE confirmation_fingerprint=? AND status=?
        ORDER BY created_at DESC LIMIT 1
        """,
        [fingerprint, status_value],
    )
    if existing is None:
        assumption_set_id = f"aset_{uuid.uuid4().hex[:12]}"
        from equitylens.storage.writer import writer_for

        with writer_for(store).transaction(store):
            locked = store._conn.execute(
                """
                SELECT assumption_set_id FROM valuation_assumption_set
                WHERE confirmation_fingerprint=? AND status=?
                ORDER BY created_at DESC LIMIT 1
                """,
                [fingerprint, status_value],
            ).fetchone()
            if locked:
                assumption_set_id = locked[0]
            else:
                store._conn.execute(
                    """
                    INSERT INTO valuation_assumption_set (
                      assumption_set_id, company_id, security_id, publication_id,
                      name, model_name, model_version, assumptions_json,
                      assumptions_hash, confirmation_fingerprint, status,
                      confirmed_at, source_metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, 'FCFF_DCF', ?, ?, ?, ?, ?,
                              CASE WHEN ? THEN now() ELSE NULL END, ?, now())
                    """,
                    [
                        assumption_set_id,
                        company_id,
                        security_id,
                        publication_id,
                        "Confirmed valuation profile"
                        if confirmed
                        else "Valuation draft",
                        model_version,
                        canonical_json(assumptions),
                        assumptions_hash,
                        fingerprint,
                        status_value,
                        confirmed,
                        canonical_json({"source": "user_confirmation"}),
                    ],
                )
        existing = store.query_one(
            "SELECT * FROM valuation_assumption_set WHERE assumption_set_id=?",
            [assumption_set_id],
        )
    return {
        "confirmation_id": existing["assumption_set_id"],
        "company_id": company_id,
        "security_id": security_id,
        "publication_id": publication_id,
        "model_version": model_version,
        "assumptions_hash": assumptions_hash,
        "confirmation_fingerprint": fingerprint,
        "status": "READY" if confirmed else "NEEDS_CONFIGURATION",
    }


def require_valuation_confirmation(
    store,
    *,
    company_id: str,
    security_id: str,
    publication_id: str,
    model_version: str,
    assumptions: dict | None = None,
) -> dict | None:
    company = store.query_one(
        "SELECT quality_status FROM company WHERE company_id=?", [company_id]
    )
    if company and company["quality_status"] == "LEGACY_UNREVIEWED":
        return None
    params: list = [company_id, security_id, publication_id, model_version]
    sql = """
        SELECT * FROM valuation_assumption_set
        WHERE company_id=? AND security_id=? AND publication_id=?
          AND model_version=? AND status='CONFIRMED'
    """
    if assumptions is not None:
        sql += " AND assumptions_hash=?"
        params.append(sha256_json(assumptions))
    sql += " ORDER BY confirmed_at DESC LIMIT 1"
    row = store.query_one(sql, params)
    if row is None:
        _valuation_error(
            "VALUATION_NEEDS_CONFIGURATION",
            "confirm model assumptions for this security and publication before valuation",
        )
    row = dict(row)
    row["assumptions"] = json.loads(row["assumptions_json"])
    return row


def confirmed_valuation(
    store,
    *,
    company_id: str,
    ticker: str,
    confirmation: dict,
    persist: bool,
) -> dict:
    inputs = _inputs_from_dict(confirmation["assumptions"])
    output = run_dcf(inputs)
    scenarios = scenario_valuation(inputs, ticker)
    sens = sensitivity(inputs)
    meta = {
        key: {
            "value": value,
            "source_type": "user_confirmation",
            "source": f"valuation_confirmation:{confirmation['assumption_set_id']}",
        }
        for key, value in _inputs_dict(inputs).items()
    }
    quality = model_quality_block(meta, output, scenarios)
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    from equitylens.market.service import latest_quote_row

    market_row = latest_quote_row(
        store, company_id, confirmation["security_id"]
    )
    if persist:
        _persist_run(
            store,
            {
                "valuation_run_id": run_id,
                "company_id": company_id,
                "security_id": confirmation["security_id"],
                "publication_id": confirmation["publication_id"],
                "model_name": "FCFF_DCF",
                "model_version": confirmation["model_version"],
                "run_at": _now(),
                "market_observation_id": market_row["quote_id"] if market_row else None,
                "assumption_set_id": confirmation["assumption_set_id"],
                "fact_snapshot_json": canonical_json(
                    {"inputs": _inputs_dict(inputs), "meta": meta, "source_fact_ids": {}}
                ),
                "output_json": canonical_json(_output_dict(output)),
                "warnings_json": canonical_json(output.warnings),
                "input_fingerprint": valuation_input_fingerprint(inputs),
                "scenarios_json": canonical_json(scenarios),
                "sensitivity_json": canonical_json(sens),
                "model_quality_json": canonical_json(quality),
                "confirmation_fingerprint": confirmation["confirmation_fingerprint"],
            },
        )
    from equitylens.market.service import valuation_market_block

    return {
        "ticker": ticker,
        "company_id": company_id,
        "security_id": confirmation["security_id"],
        "publication_id": confirmation["publication_id"],
        "confirmation_id": confirmation["assumption_set_id"],
        "valuation_run_id": run_id if persist else None,
        "input_fingerprint": valuation_input_fingerprint(inputs),
        "model_version": confirmation["model_version"],
        "assumptions": {"inputs": _inputs_dict(inputs), "meta": meta},
        "result": _output_dict(output),
        "scenarios": scenarios,
        "sensitivity": sens,
        "model_quality": quality,
        "market": valuation_market_block(
            store,
            company_id,
            ticker,
            round(output.fair_value_per_share, 2),
            security_id=confirmation["security_id"],
        ),
        "warnings": output.warnings,
        "reproducible": True,
    }


def _source_fact_ids(meta: dict) -> dict[str, list[str]]:
    """Freeze the exact canonical identities behind every fact-derived input."""
    return {
        key: list(value.get("fact_ids") or [])
        for key, value in meta.items()
        if isinstance(value, dict) and value.get("fact_ids")
    }


def _apply_runtime_risk_free(meta: dict, rate: dict) -> None:
    """Keep the normalized metadata contract when the live/fallback rate wins."""
    item = meta.setdefault("risk_free", {})
    item.update(rate)
    item["source_type"] = (
        "external_observation" if "daily yield curve" in str(rate.get("source", "")).lower()
        else "config_assumption"
    )
    item["rule"] = "Use latest Treasury 10Y when available; otherwise the dated config fallback."
    item["reason"] = "Nominal USD cash flows require a same-currency risk-free component."
    item.setdefault("source_ids", [])
    item.setdefault("fact_ids", [])
    item.setdefault("version", "risk-free-adapter.v1")
    item["fallback_reason"] = (
        None if item["source_type"] == "external_observation"
        else "Treasury feed unavailable; using dated config fallback."
    )


def default_valuation(store, company_id: str, ticker: str) -> dict:
    rf = risk_free_rate()
    inputs, meta = default_assumption_set(store, company_id, ticker, risk_free=rf["value"])
    _apply_runtime_risk_free(meta, rf)
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
    issuer = (load_valuation_config().get("issuers") or {}).get(ticker.upper())
    if issuer is not None and issuer.get("scenarios"):
        scenario_cfg = issuer["scenarios"]
    else:
        # A transparent generic policy remains available for isolated model
        # tests. Product defaults still reject unsupported issuers before this
        # function is reached.
        bear_growth, bull_growth = _bear_bull_growth(base.revenue_growth)
        scenario_cfg = {
            "version": "generic-scenarios.v1",
            "bear": {"label": "悲观", "story": "增长和利润率低于当前基准，资本成本上升。",
                     "revenue_growth": bear_growth, "op_margin_delta": -0.02,
                     "wacc_delta": 0.01, "terminal_growth_delta": -0.005},
            "base": {"label": "中性", "story": "沿用当前完整输入，不作额外改变。"},
            "bull": {"label": "乐观", "story": "增长和利润率高于当前基准，资本成本下降。",
                     "revenue_growth": bull_growth, "op_margin_delta": 0.02,
                     "wacc_delta": -0.005, "terminal_growth_delta": 0.005},
        }

    def make(key: str) -> dict:
        spec = scenario_cfg[key]
        g = list(spec.get("revenue_growth", base.revenue_growth))
        m = base.op_margin_end + float(spec.get("op_margin_delta", 0.0))
        w = base.wacc + float(spec.get("wacc_delta", 0.0))
        t = base.terminal_growth + float(spec.get("terminal_growth_delta", 0.0))
        trial = DcfInputs(
            revenue_base=base.revenue_base,
            revenue_growth=g,
            op_margin_start=base.op_margin_start,
            op_margin_end=m,
            tax_rate=base.tax_rate, da_pct=base.da_pct, capex_pct=base.capex_pct,
            nwc_pct=base.nwc_pct, wacc=w, terminal_growth=t,
            net_cash=base.net_cash, shares=base.shares, terminal_roic=base.terminal_roic,
            share_basis_label=base.share_basis_label,
        )
        changed_fields = [
            field for field in DcfInputs.__dataclass_fields__
            if getattr(trial, field) != getattr(base, field)
        ]
        context = {
            "label": spec["label"], "story": spec["story"],
            "scenario_version": scenario_cfg["version"],
            "changed_fields": changed_fields, "inputs": _inputs_dict(trial),
        }
        try:
            result = _output_dict(run_dcf(trial))
            return {**context, "result": result, "status": "OK", "reason": None}
        except dcf_mod.ValuationError as exc:
            return {**context, "result": None, "status": "UNAVAILABLE", "reason": str(exc)}

    return {
        "bear": make("bear"),
        "base": make("base"),
        "bull": make("bull"),
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
                share_basis_label=base.share_basis_label,
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
    _apply_runtime_risk_free(meta, rf)
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
            share_basis_label=str(a.get(
                "share_basis_label",
                "user-supplied share count" if "shares" in a else base.share_basis_label,
            )),
            terminal_roic=float(a.get("terminal_roic", base.terminal_roic)),
        )
        # meta must reflect the FINAL executed inputs, marking user overrides.
        _override_meta = {
            "wacc": "wacc", "terminal_growth": "terminal_growth",
            "op_margin_start": "op_margin_start", "op_margin_end": "op_margin_end",
            "revenue_growth": "revenue_growth",
            "tax_rate": "tax_rate", "net_cash": "net_cash", "shares": "shares",
            "da_pct": "da_pct", "capex_pct": "capex_pct", "revenue_base": "revenue_base",
            "nwc_pct": "nwc_pct",
            "terminal_roic": "terminal_roic",
            "share_basis_label": "share_basis_label",
        }
        for field, meta_key in _override_meta.items():
            if field in a:
                item = meta.setdefault(meta_key, {})
                item.update({
                    "value": a[field], "source_type": "user_override",
                    "source": "user_override", "source_ids": [], "fact_ids": [],
                    "as_of": _now(), "version": "user-input.v1",
                    "rule": "Use the complete value supplied by the user for this run.",
                    "reason": "User edited this field in the valuation draft.",
                    "fallback_reason": None,
                })
        if "op_margin_start" in a or "op_margin_end" in a:
            meta["op_margin"] = {
                "value": base.op_margin_start,
                "source_type": "user_override", "source": "user_override",
                "source_ids": [], "fact_ids": [], "as_of": _now(),
                "version": "user-input.v1",
                "rule": "Compatibility alias; executable inputs are op_margin_start/op_margin_end.",
                "reason": "User edited the operating-margin path.", "fallback_reason": None,
            }
        if "shares" in a:
            meta["shares"]["basis"] = base.share_basis_label
            meta["share_basis_label"] = dict(meta["shares"])
            meta["share_basis_label"]["value"] = base.share_basis_label
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


def reverse_dcf(
    store,
    company_id: str,
    ticker: str,
    payload: dict,
    *,
    confirmed_assumptions: dict | None = None,
    security_id: str | None = None,
) -> dict:
    if confirmed_assumptions is None:
        rf = risk_free_rate()
        base, _ = default_assumption_set(
            store, company_id, ticker, risk_free=rf["value"]
        )
    else:
        base = _inputs_from_dict(confirmed_assumptions)
    if "assumptions" in payload and not isinstance(payload["assumptions"], dict):
        raise ValuationError(
            "INVALID_INPUT", "assumptions must be an object", "assumptions"
        )
    a = payload.get("assumptions", {})

    def number(name: str, default: float) -> float:
        try:
            value = float(a.get(name, default))
        except (TypeError, ValueError) as exc:
            raise ValuationError("INVALID_INPUT", f"{name} must be a number", name) from exc
        if not math.isfinite(value):
            raise ValuationError("INVALID_INPUT", f"{name} must be finite", name)
        return value

    if a:
        try:
            growth = [float(x) for x in a.get("revenue_growth", base.revenue_growth)]
        except (TypeError, ValueError) as exc:
            raise ValuationError(
                "INVALID_INPUT", "revenue_growth must contain numbers", "revenue_growth"
            ) from exc
        base = DcfInputs(
            revenue_base=number("revenue_base", base.revenue_base),
            revenue_growth=growth,
            op_margin_start=number("op_margin_start", base.op_margin_start),
            op_margin_end=number("op_margin_end", base.op_margin_end),
            tax_rate=number("tax_rate", base.tax_rate),
            da_pct=number("da_pct", base.da_pct),
            capex_pct=number("capex_pct", base.capex_pct),
            nwc_pct=number("nwc_pct", base.nwc_pct),
            wacc=number("wacc", base.wacc),
            terminal_growth=number("terminal_growth", base.terminal_growth),
            net_cash=number("net_cash", base.net_cash),
            shares=number("shares", base.shares),
            share_basis_label=str(a.get(
                "share_basis_label",
                "user-supplied share count" if "shares" in a else base.share_basis_label,
            )),
            terminal_roic=number("terminal_roic", base.terminal_roic),
        )
    try:
        target = float(payload.get("target_price"))
    except (TypeError, ValueError) as exc:
        raise ValuationError(
            "INVALID_INPUT", "target_price must be a number", "target_price"
        ) from exc
    if not math.isfinite(target) or target <= 0:
        raise ValuationError(
            "INVALID_INPUT", "target_price must be finite and positive", "target_price"
        )
    validate(base)
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
        "market": valuation_market_block(
            store, company_id, ticker, fair_value_per_share=None,
            security_id=security_id,
        ),
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
    from equitylens.storage.writer import writer_for

    store.connect()
    cols = list(run.keys())
    placeholders = ", ".join("?" for _ in cols)
    with writer_for(store).transaction(store):
        store._conn.execute(
            f"INSERT INTO valuation_run ({', '.join(cols)}) VALUES ({placeholders})",
            [run[c] for c in cols],
        )


# --- P06: personal reference-price plans -------------------------------------
# 参考价 = 选定每股估值 × (1 − 安全边际). Research reference only; no orders.

def create_plan(
    store,
    company_id: str,
    ticker: str,
    payload: dict,
    *,
    review_status: str = "current",
    review_reason: str | None = None,
) -> dict:
    """Create (and immediately persist) a personal reference-price plan.

    The reference price is the SELECTED per-share value (a model/scenario
    output) times (1 - margin_of_safety). A zero/negative reference value is
    kept for research but produces no buyable reference price.
    """
    run_id = payload.get("valuation_run_id")
    scenario_key = payload.get("scenario_key")
    if not run_id:
        raise ValueError("必须选择一个已保存估值运行（valuation_run_id）")
    if scenario_key not in ("base", "bear", "bull"):
        raise ValueError("scenario_key 必须是 base、bear 或 bull")
    run = store.query_one(
        "SELECT * FROM valuation_run WHERE valuation_run_id = ? AND company_id = ?",
        [run_id, company_id],
    )
    if run is None:
        raise ValueError("估值运行不存在或不属于当前公司")
    if not run.get("input_fingerprint") or not run.get("scenarios_json"):
        raise ValueError("历史估值运行缺少完整输入，不能创建普通参考价方案")
    scenarios = json.loads(run["scenarios_json"])
    scenario = scenarios.get(scenario_key)
    result = scenario.get("result") if isinstance(scenario, dict) else None
    if not result or result.get("fair_value_per_share") is None:
        raise ValueError("所选情景不可用，不能创建参考价方案")
    ref = float(result["fair_value_per_share"])
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

    snapshot = json.loads(run.get("fact_snapshot_json") or "{}")
    source_ids = sorted({
        fact_id
        for ids in (snapshot.get("source_fact_ids") or {}).values()
        for fact_id in ids
    })
    filing_as_of = None
    if source_ids:
        row = store.query_one(
            f"SELECT MAX(COALESCE(as_known_at, period_end)) AS at FROM canonical_fact "
            f"WHERE canonical_fact_id IN ({','.join('?' for _ in source_ids)})",
            source_ids,
        )
        filing_as_of = row.get("at") if row else None
    quote_observed_at = None
    if run.get("market_observation_id"):
        quote = store.query_one(
            "SELECT observed_at FROM market_quote WHERE quote_id = ?",
            [run["market_observation_id"]],
        )
        quote_observed_at = str(quote["observed_at"]) if quote else None

    plan_id = f"plan_{uuid.uuid4().hex[:12]}"
    row = {
        "plan_id": plan_id, "company_id": company_id, "ticker": ticker,
        "security_id": run.get("security_id"),
        "publication_id": run.get("publication_id"),
        "name": payload.get("name") or "未命名方案",
        "reference_value": ref,
        "reference_source": f"valuation_run:{run_id}:{scenario_key}",
        "margin_of_safety": margin,
        "reference_price": price,
        "notes": payload.get("notes"),
        "assumptions_json": json.dumps(scenario.get("inputs") or {}, ensure_ascii=False),
        "valuation_run_id": run_id,
        "scenario_key": scenario_key,
        "source_input_fingerprint": run["input_fingerprint"],
        "reference_price_reason": reason,
        "conditions_json": json.dumps(payload.get("conditions_to_verify") or [], ensure_ascii=False),
        "parent_plan_id": payload.get("_parent_plan_id"),
        "version": int(payload.get("_version") or 1),
        "review_status": review_status,
        "review_reason": review_reason,
        "source_filing_as_of": filing_as_of,
        "source_quote_observed_at": quote_observed_at,
        "created_at": _now(),
    }
    from equitylens.storage.writer import writer_for

    store.connect()
    cols = list(row.keys())
    placeholders = ", ".join("?" for _ in cols)
    with writer_for(store).transaction(store):
        store._conn.execute(
            f"INSERT INTO valuation_plan ({', '.join(cols)}) VALUES ({placeholders})",
            [row[c] for c in cols],
        )
    out = dict(row)
    return _plan_out(row)


def _plan_out(row: dict) -> dict:
    out = dict(row)
    assumptions = out.get("assumptions_json")
    out["assumptions_json"] = json.loads(assumptions or "{}") if isinstance(assumptions, str) else (assumptions or {})
    conditions = out.get("conditions_json")
    out["conditions_to_verify"] = json.loads(conditions or "[]") if isinstance(conditions, str) else (conditions or [])
    out.pop("conditions_json", None)
    if not out.get("valuation_run_id"):
        out["review_status"] = "legacy/incomplete"
        out["review_reason"] = out.get("review_reason") or "历史方案缺少估值运行身份"
    return out


def list_plans(store, company_id: str) -> list[dict]:
    store.connect()
    rows = store.query(
        "SELECT * FROM valuation_plan WHERE company_id = ? ORDER BY created_at DESC",
        [company_id],
    )
    return [_plan_out(row) for row in rows]


def get_plan(store, company_id: str, plan_id: str) -> dict | None:
    store.connect()
    row = store.query_one(
        "SELECT * FROM valuation_plan WHERE plan_id = ? AND company_id = ?",
        [plan_id, company_id],
    )
    if row:
        return _plan_out(row)
    return None


def copy_plan(store, company_id: str, ticker: str, plan_id: str, payload: dict) -> dict:
    original = get_plan(store, company_id, plan_id)
    if original is None:
        raise ValueError("方案不存在或不属于当前公司")
    if not original.get("valuation_run_id"):
        raise ValueError("历史不完整方案不能直接复制为普通参考价方案")
    return create_plan(store, company_id, ticker, {
        "valuation_run_id": original["valuation_run_id"],
        "scenario_key": payload.get("scenario_key", original["scenario_key"]),
        "margin_of_safety": payload.get("margin_of_safety", original["margin_of_safety"]),
        "name": payload.get("name", f"{original['name']} 副本"),
        "notes": payload.get("notes", original.get("notes")),
        "conditions_to_verify": payload.get("conditions_to_verify", original.get("conditions_to_verify") or []),
        "_parent_plan_id": plan_id,
        "_version": int(original.get("version") or 1) + 1,
    }, review_status=original.get("review_status") or "needs_review",
       review_reason=original.get("review_reason"))


def compare_plans(store, company_id: str, plan_ids: list[str]) -> dict:
    if len(plan_ids) < 2 or len(plan_ids) > 5:
        raise ValueError("请选择 2 到 5 个方案比较")
    plans = [get_plan(store, company_id, plan_id) for plan_id in plan_ids]
    if any(plan is None for plan in plans):
        raise ValueError("比较列表包含不存在或跨公司的方案")
    fields = ("scenario_key", "reference_value", "margin_of_safety", "reference_price",
              "notes", "conditions_to_verify", "review_status")
    changed = [field for field in fields if len({json.dumps(plan.get(field), sort_keys=True, ensure_ascii=False)
                                                 for plan in plans}) > 1]
    return {"plans": plans, "changed_fields": changed}
