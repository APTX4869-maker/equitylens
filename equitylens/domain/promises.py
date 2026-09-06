"""Promise Tracker: evidence cards + deterministic verification (M8.6).

A promise is only tracked with an EVIDENCE CARD (quote + speaker + date +
source_url + a machine-checkable claim). Status is never hand-written: at read
time the engine verifies the claim against canonical SEC facts with a versioned
rule (promise_verify.v1) and returns VERIFIED / BROKEN / OPEN / UNVERIFIED.

    verification = {metric, frequency, fiscal_year, operator, target}
    metric      : canonical metric computable by the metric engine (annual FY)
    operator    : gte | lte | approx
    target      : the committed value

Earnings-call/prepared-remarks parsing (Phase 7) will later WRITE these cards;
until then cards come from `equitylens ingest-promises` (data/evidence/promises).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from equitylens.metrics.engine import MetricEngine

PROMISE_VERIFY_VERSION = "promise_verify.v1"
CARD_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "evidence" / "promises"

_OPERATORS = ("gte", "lte", "approx")


def _card_dir(ticker: str) -> Path:
    return CARD_DIR / ticker.upper()


def load_cards(ticker: str, cards_dir: Path | None = None) -> list[dict]:
    """Read *.json evidence cards (files starting with '_' are ignored)."""
    directory = cards_dir or _card_dir(ticker)
    if not directory.exists():
        return []
    out = []
    for f in sorted(directory.glob("*.json")):
        if f.name.startswith("_"):
            continue
        out.append(json.loads(f.read_text()))
    return out


def _verify_spec(card: dict) -> dict | None:
    v = card.get("verification") or card.get("verification_metrics") or {}
    metric = v.get("metric")
    fy = v.get("fiscal_year")
    op = v.get("operator")
    target = v.get("target")
    if not metric or not fy or op not in _OPERATORS or target is None:
        return None
    return {"metric": metric, "frequency": v.get("frequency", "annual"),
            "fiscal_year": int(fy), "operator": op, "target": float(target)}


def verify_promise(store, card: dict) -> dict:
    """Deterministic status over canonical facts (never guesses)."""
    spec = _verify_spec(card)
    deadline = card.get("verification_deadline")
    if spec is None:
        return {"status": "UNVERIFIED", "note": "承诺卡缺少可机器核对口径（metric/fiscal_year/operator/target）",
                "evidence_ids": [], "verification": None}
    company_id = card.get("company_id")
    if not company_id:
        return {"status": "UNVERIFIED", "note": "承诺卡缺少 company_id，无法核对",
                "evidence_ids": [], "verification": spec}
    pts = [p for p in MetricEngine(store).compute(spec["metric"], company_id,
                                                  frequency=spec["frequency"])
           if p.value and p.fiscal_year == spec["fiscal_year"]]
    disclosed = float(pts[-1].value) if pts else None
    evidence_ids: list[str] = []
    for p in pts:
        if p.canonical_fact_id:
            evidence_ids.append(p.canonical_fact_id)
        elif getattr(p, "input_fact_ids", None):
            evidence_ids.extend(p.input_fact_ids)
    target = spec["target"]
    if disclosed is None:
        # Fact not filed yet: OPEN while before deadline, else UNVERIFIED.
        if deadline:
            return {"status": "OPEN", "note": f"FY{spec['fiscal_year']} {spec['metric']} 尚未披露（验证截止 {deadline} 前保持跟踪）",
                    "evidence_ids": [], "verification": spec}
        return {"status": "UNVERIFIED", "note": f"FY{spec['fiscal_year']} {spec['metric']} 未找到披露，无法验证",
                "evidence_ids": [], "verification": spec}
    op = spec["operator"]
    if op == "gte":
        ok = disclosed >= target
    elif op == "lte":
        ok = disclosed <= target
    else:  # approx ±5%
        ok = abs(disclosed - target) / target <= 0.05
    note = (f"披露 {disclosed/1e9:.1f}B vs 承诺 {'≥' if op == 'gte' else '≤' if op == 'lte' else '≈'}"
            f"{target/1e9:.1f}B（FY{spec['fiscal_year']} {spec['metric']}，{PROMISE_VERIFY_VERSION}）")
    return {"status": "VERIFIED" if ok else "BROKEN", "note": note,
            "evidence_ids": evidence_ids, "verification": spec}


def list_promises(store, company_id: str, ticker: str) -> dict:
    """Enrich stored promise rows with computed verification status."""
    rows = store.query(
        "SELECT promise_id, source_evidence_id, speaker, statement_date, promise_text, "
        "normalized_claim, verification_metrics, verification_deadline, status, "
        "review_evidence_ids, created_at FROM management_promise "
        "WHERE company_id = ? ORDER BY statement_date DESC",
        [company_id],
    )
    items = []
    for r in rows:
        card = dict(r)
        card["verification_metrics"] = json.loads(r["verification_metrics"] or "{}")
        card["company_id"] = company_id
        verified = verify_promise(store, card)
        items.append({
            "promise_id": r["promise_id"],
            "speaker": r["speaker"],
            "statement_date": str(r["statement_date"] or "")[:10],
            "promise_text": r["promise_text"],
            "normalized_claim": r["normalized_claim"],
            "source_evidence_id": r["source_evidence_id"],
            "source_url": card.get("source_url"),
            "source_label": card.get("source_label"),
            "verification_deadline": str(r["verification_deadline"] or "")[:10],
            "computed_status": verified["status"],
            "status_note": verified["note"],
            "evidence_ids": verified["evidence_ids"],
            "verification": verified["verification"],
        })
    return {
        "ticker": ticker,
        "status": "READY",
        "note": "承诺状态由确定性规则对照 SEC 事实自动判定（promise_verify.v1）；证据卡来自 ingest-promises 或未来的 Earnings-call 解析。",
        "items": items,
        # Phase 7 discipline: no delivery-rate until a meaningful sample exists.
        "delivery_rate": None,
    }


def ingest_cards(store, company_id: str, ticker: str, cards: list[dict], dry_run: bool = False) -> dict:
    """Upsert evidence cards into management_promise."""
    rows = []
    for card in cards:
        text = card.get("promise_text") or ""
        if not text:
            continue
        pid = card.get("promise_id") or (
            "pm_" + hashlib.sha256(f"{company_id}|{card.get('statement_date')}|{text}".encode()).hexdigest()[:10])
        rows.append({
            "promise_id": pid,
            "company_id": company_id,
            "source_evidence_id": card.get("source_evidence_id") or card.get("source_url") or f"card_{pid}",
            "speaker": card.get("speaker"),
            "statement_date": card.get("statement_date"),
            "promise_text": text,
            "normalized_claim": card.get("normalized_claim"),
            "verification_metrics": json.dumps(card.get("verification") or {}, ensure_ascii=False),
            "verification_deadline": card.get("verification_deadline"),
            "status": "OPEN",
            "review_evidence_ids": json.dumps(card.get("review_evidence_ids") or [], ensure_ascii=False),
            "created_at": card.get("created_at") or "2026-01-01T00:00:00",
            "updated_at": card.get("updated_at") or "2026-01-01T00:00:00",
        })
    if dry_run:
        return {"company": ticker, "cards": len(cards), "dry_run": True}
    for row in rows:
        store.upsert_promise(row)
    return {"company": ticker, "cards": len(cards), "inserted": len(rows)}
