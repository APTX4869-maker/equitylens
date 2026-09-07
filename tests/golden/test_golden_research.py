"""Golden tests for M7 risk signals + evidence-first research engine."""

from __future__ import annotations

import pytest


def _seed_qfact(db, company_id, metric, fy, q, value, *, unit="USD"):
    """Seed one Q_STANDALONE canonical fact (mirrors test_metric_engine)."""
    db.connect()
    db._conn.execute(
        """INSERT INTO canonical_fact
           (canonical_fact_id, company_id, canonical_metric, period_type, fiscal_year,
            fiscal_quarter, period_start, period_end, instant_date, value, unit, status,
            mapping_rule_id, mapping_version, source_raw_fact_ids, as_known_at, created_at, warnings_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?, 'NORMALIZED', ?, 'canonical-mappings.v2', '[]', ?, ?, '[]')""",
        [f"{metric}-{fy}-{q}", company_id, metric, "Q_STANDALONE", fy, q, None,
         f"{fy}-06-30", None, value, unit, f"{metric.lower()}.usgaap.v2",
         "2026-01-01", "2026-01-01 00:00:00"],
    )


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


def test_risks_report_incomplete_ttm_and_module_failure(db, monkeypatch):
    """D06/U03/P05: a quarter gap makes cash-flow checks INCOMPLETE_PERIOD (never
    a partial four-row sum), a management-scorecard exception is reported as
    ERROR, and no cash-flow risk is emitted from the partial window."""
    from equitylens.domain import risks as risks_mod

    cid = "TEST"
    # FY2025 Q1..Q4 complete; FY2026Q2 present but FY2026Q1 absent -> latest
    # TTM endpoint is FY2026Q2 with a gap at FY2026Q1.
    for q in (1, 2, 3, 4):
        _seed_qfact(db, cid, "OPERATING_CASH_FLOW", 2025, q, 20.0)
        _seed_qfact(db, cid, "CAPITAL_EXPENDITURES", 2025, q, 5.0)
    _seed_qfact(db, cid, "OPERATING_CASH_FLOW", 2026, 2, 20.0)
    _seed_qfact(db, cid, "CAPITAL_EXPENDITURES", 2026, 2, 5.0)

    def _boom(*_a, **_k):
        raise RuntimeError("management unavailable")

    monkeypatch.setattr("equitylens.domain.management_score.management_scorecard", _boom)

    result = risks_mod.risk_signals(db, cid, "TEST")
    checks = {item["key"]: item for item in result["checks"]}
    assert checks["cash_flow"]["status"] == "INCOMPLETE_PERIOD"
    assert checks["cash_flow"]["reason"], "gap reason must identify the missing quarter"
    assert checks["management"]["status"] == "ERROR"
    assert checks["management"]["reason"] == "management unavailable"
    # a partial TTM window must not produce a capital-intensity or net-debt risk
    assert not any("资本开支" in r["title"] for r in result["risks"])
    assert not any("净债务" in r["title"] for r in result["risks"])
    assert result["coverage"]["complete"] is False
    assert result["coverage"]["completed"] < result["coverage"]["total"]
    assert {item["key"] for item in result["coverage"]["unavailable"]} >= {"cash_flow", "management"}


def test_risks_coverage_text_names_failed_modules(company_db):
    """U03/P05: the research risk answer must not claim a failed module was
    checked; it names unavailable checks explicitly."""
    from equitylens.research.engine import ask

    d = ask(company_db, "0000789019", "MSFT", "有什么风险？")
    # for real MSFT the modules complete, so the answer must NOT carry the
    # unconditional "检查了增长、利润率、现金流…" stock phrase pattern that
    # pretends everything was checked regardless of outcome.
    assert "未能完成检查" not in d["answer"] or "已完成" in d["answer"]


def test_ai_compare_revenue_is_ttm_not_single_quarter(company_db):
    """U03: the compare answer's "TTM 收入" must be the true trailing-4-quarter
    sum (~$467B), never the latest single quarter (~$109B)."""
    from equitylens.research.engine import ask

    d = ask(company_db, "0000320193", "AAPL", "和 MSFT 比，谁更好？")
    rev_claim = next((c for c in d["claims"] if "TTM 收入" in c["claim"]), None)
    assert rev_claim is not None
    assert "467" in rev_claim["claim"]  # 466.8B TTM -> "$467B"
    assert "109" not in rev_claim["claim"]  # never the single Q3 quarter


def test_ai_never_fabricates_unknown_metric(company_db):
    """Asking for something outside the fact store must not produce numbers."""
    from equitylens.research.engine import ask

    d = ask(company_db, "0000320193", "AAPL", "公司2027年收入的内部预测是多少？")
    # the engine routes this to overview/fallback; no claim may present a made-up future number
    assert not any("2027" in c["claim"] and "$" in c["claim"] for c in d["claims"])
    assert d["intent"] == "unsupported"
    assert d["claims"] == []
    assert "当前支持" in d["answer"]


@pytest.mark.parametrize("ticker,company_id", [
    ("AAPL", "0000320193"), ("MSFT", "0000789019"),
])
def test_every_numeric_risk_claim_has_resolvable_evidence(company_db, ticker, company_id):
    from equitylens.api.routes import _build_provenance
    from equitylens.domain.risks import risk_signals

    result = risk_signals(company_db, company_id, ticker)
    for risk in result["risks"]:
        if any(ch.isdigit() for ch in risk["description"]):
            assert risk["evidence_ids"], risk["title"]
        for evidence_id in risk["evidence_ids"]:
            assert _build_provenance(company_db, evidence_id, 4, set()) is not None, evidence_id


@pytest.mark.parametrize("question", [
    "收入增长为什么放缓？", "利润率现在怎么样？", "现金流和回购情况？",
    "公司最近的风险有哪些？", "估值怎么看？", "业务构成如何？",
])
def test_every_numeric_research_claim_has_resolvable_evidence(company_db, question):
    from equitylens.api.routes import _build_provenance
    from equitylens.research.engine import ask

    response = ask(company_db, "0000320193", "AAPL", question)
    for claim in response["claims"]:
        if any(ch.isdigit() for ch in claim["claim"]):
            assert claim["evidence_ids"], claim["claim"]
        for evidence_id in claim["evidence_ids"]:
            assert _build_provenance(company_db, evidence_id, 4, set()) is not None, evidence_id
