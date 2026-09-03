"""Golden tests: Promise Tracker deterministic verification (M8.6).

Status comes from promise_verify.v1 over real canonical facts, never hand-set:
- FY2025 buyback commitment >= $90B  -> VERIFIED (disclosed 90,711M)
- FY2025 buyback commitment >= $500B  -> BROKEN (disclosed far below)
- FY2026 commitment (not filed yet)   -> OPEN (kept until deadline)
"""

from __future__ import annotations

import json
from pathlib import Path

from equitylens.domain.companies import get_company
from equitylens.domain.promises import ingest_cards, list_promises, load_cards, verify_promise

AAPL_CIK = get_company("AAPL").cik
FX = Path(__file__).parent.parent / "fixtures" / "promises" / "AAPL"


def _seed(company_db):
    cards = [json.loads(f.read_text()) for f in sorted(FX.glob("*.json"))]
    ingest_cards(company_db, AAPL_CIK, "AAPL", cards)
    return cards


def test_promise_verified_against_real_fy2025_buybacks(company_db):
    _seed(company_db)
    out = list_promises(company_db, AAPL_CIK, "AAPL")
    assert out["status"] == "READY"
    by_id = {i["promise_id"]: i for i in out["items"]}

    ok = by_id["aapl-fy2025-buyback-gte"]
    assert ok["computed_status"] == "VERIFIED"
    assert "90.7B" in ok["status_note"] or "90.7" in ok["status_note"]
    assert ok["evidence_ids"], "verification must cite the real canonical facts"

    bad = by_id["aapl-fy2025-buyback-unrealistic"]
    assert bad["computed_status"] == "BROKEN"
    assert bad["evidence_ids"]

    fwd = by_id["aapl-fy2026-forward"]
    assert fwd["computed_status"] == "OPEN"
    assert "尚未披露" in fwd["status_note"]


def test_verify_promise_direct_rules(company_db):
    base = {"company_id": AAPL_CIK, "verification_deadline": "2027-01-01"}
    r = verify_promise(company_db, {**base, "verification": {
        "metric": "SHARE_REPURCHASES", "frequency": "annual", "fiscal_year": 2025,
        "operator": "approx", "target": 90_711_000_000}})
    assert r["status"] == "VERIFIED"  # disclosed equals target within ±5%
    r2 = verify_promise(company_db, {**base, "verification": {
        "metric": "REVENUE", "frequency": "annual", "fiscal_year": 2099,
        "operator": "gte", "target": 1.0}})
    assert r2["status"] == "OPEN"  # no such FY -> kept open before deadline
    r3 = verify_promise(company_db, {"company_id": AAPL_CIK})
    assert r3["status"] == "UNVERIFIED"  # no machine-checkable spec


def test_load_cards_ignores_underscore_templates():
    p = FX.parent / "AAPL"
    cards = load_cards("AAPL", cards_dir=p)
    assert len(cards) == 3
