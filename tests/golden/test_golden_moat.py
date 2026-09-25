"""Golden tests: deterministic moat-evidence engine (SEC numbers only).

Every signal must carry evidence; qualitative dimensions without SEC numbers
must appear as explicit gaps and never as rated strengths.
"""

from __future__ import annotations

from equitylens.domain.companies import get_company
from equitylens.domain.moat import moat_signals

AAPL_CIK = get_company("AAPL").cik
MSFT_CIK = get_company("MSFT").cik


def test_aapl_signals_real_and_evidence_backed(company_db):
    d = moat_signals(company_db, AAPL_CIK, "AAPL")
    assert d["demo"] is False
    assert d["method"] == "deterministic-moat-evidence.v1"
    assert d["signals"], "signals must be present"
    # AAPL is asset-light with strong self-funding: these verdicts must hold
    verdicts = {s["dimension"]: s["verdict"] for s in d["signals"]}
    assert verdicts["再投资需求"] == "strength"          # CapEx ~3% of revenue
    assert verdicts["现金流护城河"] == "strength"          # FCF margin ~24%
    assert verdicts["规模"] == "strength"
    assert any(s["title"].startswith("毛利率高") for s in d["signals"]), "pricing-power evidence missing"
    # product view concentration (iPhone ~50%) is a watch item
    prod = [s for s in d["signals"] if s["dimension"] == "收入依赖" and s["value_label"] == "50%"]
    assert prod and prod[0]["verdict"] == "watch"
    # AAPL 14A does not mark independence -> explicit gap, not a rated signal
    dims = {s["dimension"] for s in d["signals"]}
    assert "治理" not in dims
    assert any(g["dimension"] == "董事会独立性标注" for g in d["qualitative_gaps"])


def test_msft_signals_and_honest_capex_concern(company_db):
    d = moat_signals(company_db, MSFT_CIK, "MSFT")
    assert d["signals"]
    verdicts = {s["dimension"]: s["verdict"] for s in d["signals"]}
    # MSFT FY2026 CapEx ~$116B -> honest concern on capital intensity
    assert verdicts["再投资需求"] == "concern"
    # high stable gross margin + independent board are strengths
    gm = [s for s in d["signals"] if "毛利率" in s["title"]]
    assert gm and gm[0]["verdict"] == "strength"
    gov = [s for s in d["signals"] if s["dimension"] == "治理"]
    assert gov and gov[0]["verdict"] == "strength"


def test_all_signals_carry_evidence_and_gaps_are_qualitative(company_db):
    for ticker, cik in (("AAPL", AAPL_CIK), ("MSFT", MSFT_CIK)):
        d = moat_signals(company_db, cik, ticker)
        for s in d["signals"]:
            assert s["evidence_ids"], f"{ticker} signal {s['title']} lacks evidence"
        assert d["qualitative_gaps"], "qualitative gaps must be listed"
        assert any("品牌" in g["dimension"] for g in d["qualitative_gaps"])
        assert "证据缺口" in d["summary"] or "缺口" in d["summary"]
