"""Golden tests for M7 risk signals + evidence-first research engine."""

from __future__ import annotations

import pytest


def test_risk_msft_capex_intensity(company_db):
    """MSFT FY2026 real capex ~$116B vs OCF -> HIGH capital-intensity risk."""
    from equitylens.domain.risks import risk_signals

    d = risk_signals(company_db, "0000789019", "MSFT")
    capex_risk = next((r for r in d["risks"] if "资本开支" in r["title"]), None)
    assert capex_risk is not None
    assert capex_risk["severity"] == "HIGH"
    assert capex_risk["category"] == "financial"
    assert capex_risk["generated_by"] == "deterministic-rules.v1"
    assert capex_risk["monitoring"]


def test_risk_aapl_concentration(company_db):
    """AAPL iPhone ~50% of revenue -> structural concentration signal."""
    from equitylens.domain.risks import risk_signals

    d = risk_signals(company_db, "0000320193", "AAPL")
    conc = next((r for r in d["risks"] if "集中度" in r["title"]), None)
    assert conc is not None
    assert conc["severity"] == "MEDIUM"
    assert "iPhone" in conc["description"]


def test_ai_growth_answer_has_real_numbers_and_evidence(company_db):
    from equitylens.research.engine import ask

    d = ask(company_db, "0000320193", "AAPL", "收入增长为什么放缓？")
    assert any("16.4" in c["claim"] for c in d["claims"]), "must cite the real YoY figure"
    assert any(c["evidence_ids"] for c in d["claims"]), "claims must carry evidence ids"
    assert not any("不可知" in c["claim"] and c["evidence_ids"] for c in d["claims"])


def test_ai_risk_answer_derived_from_rules(company_db):
    from equitylens.research.engine import ask

    d = ask(company_db, "0000789019", "MSFT", "有什么风险？")
    joined = " ".join(c["claim"] for c in d["claims"])
    assert "CapEx" in joined or "资本开支" in joined


def test_ai_never_fabricates_unknown_metric(company_db):
    """Asking for something outside the fact store must not produce numbers."""
    from equitylens.research.engine import ask

    d = ask(company_db, "0000320193", "AAPL", "公司2027年收入的内部预测是多少？")
    # the engine routes this to overview/fallback; no claim may present a made-up future number
    assert not any("2027" in c["claim"] and "$" in c["claim"] for c in d["claims"])


def test_promises_endpoint_empty_but_ready(company_db):
    rows = company_db.query("SELECT count(*) n FROM management_promise")
    assert rows[0]["n"] == 0  # schema exists, no earnings-call evidence yet
