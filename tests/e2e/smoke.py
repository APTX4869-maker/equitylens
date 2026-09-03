"""Playwright smoke test for the EquityLens web app (real-data pages).

Assumes:
- FastAPI on 127.0.0.1:8000 (data/equitylens.duckdb already synced)
- Next.js dev/prod server on 127.0.0.1:3000

Run:  cd apps/web && pnpm dev &  (backend already running)
      uv run python tests/e2e/smoke.py
"""

from __future__ import annotations

import re
import sys

from playwright.sync_api import expect, sync_playwright

BASE = "http://localhost:3000"


def main() -> int:
    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        console_errors: list[str] = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: console_errors.append(str(exc)))

        # 1) Overview renders with REAL KPI values
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(1500)
        expect(page.get_by_role("heading", name="Apple Inc.")).to_be_visible()
        body = page.locator("body").inner_text()
        if "TTM 营业收入" not in body or "$4" not in body:
            failures.append("overview: real KPI cards not rendered (TTM revenue missing)")
        if "数据新鲜度" not in body:
            failures.append("overview: data freshness strip missing")
        page.screenshot(path="/tmp/el_overview.png", full_page=True)

        # 2) Financial Analysis tab: real quarterly chart + metric cards + drawers
        page.get_by_role("button", name="财务分析").click()
        page.wait_for_timeout(1500)
        page.screenshot(path="/tmp/el_financials.png", full_page=True)
        fin_body = page.locator("body").inner_text()
        if "三年简化财务表" not in fin_body:
            failures.append("financials: annual statement table missing")
        if "营业收入" not in fin_body or "自由现金流" not in fin_body:
            failures.append("financials: metric cards missing")

        # 3) Metric drawer opens with knowledge + view-source
        page.locator(".metric-card", has_text="营业利润率").first.click()
        page.wait_for_timeout(600)
        expect(page.get_by_role("dialog").first).to_be_visible()
        drawer = page.locator(".modal-body").first.inner_text()
        if "用人话理解" not in drawer:
            failures.append("metric drawer: explanation missing")
        page.get_by_role("button", name="查看来源 →").click()
        page.wait_for_timeout(1000)
        src = page.locator(".modal-body").first.inner_text()
        if "SEC" not in src and "Accession" not in src:
            failures.append("source drawer: lineage not shown")
        page.screenshot(path="/tmp/el_sourcedrawer.png")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # 4) Business tab (AAPL): REAL segment data from SEC filings
        page.get_by_role("button", name="业务构成").click()
        page.wait_for_timeout(2500)
        biz = page.locator("body").inner_text()
        if "公司报告分部" not in biz or "美洲" not in biz:
            failures.append("business: real segments not rendered (AAPL)")
        if "NOT_DISCLOSED" not in biz:
            failures.append("business: NOT_DISCLOSED profitability badge missing")
        page.screenshot(path="/tmp/el_business.png", full_page=True)

        # 5) Company switch -> MSFT: segments with disclosed profit
        page.get_by_role("button", name="MSFT Microsoft").click()
        page.wait_for_timeout(1500)
        expect(page.get_by_role("heading", name="Microsoft")).to_be_visible()
        page.get_by_role("button", name="业务构成").click()
        page.wait_for_timeout(2500)
        biz2 = page.locator("body").inner_text()
        if "智能云" not in biz2 or "生产力与业务流程" not in biz2:
            failures.append("business: MSFT segments not rendered")
        if "官方披露 · 营业利润" not in biz2:
            failures.append("business: MSFT disclosed segment profit missing")

        # 6) Management tab (real DEF 14A + Form 4 data)
        page.get_by_role("button", name="管理层").click()
        page.wait_for_timeout(2500)
        mgmt = page.locator("body").inner_text()
        if "管理层质量评分卡" not in mgmt or "Satya Nadella" not in mgmt:
            failures.append("management: scorecard or leaders missing (MSFT)")
        if "总分不可用" not in mgmt and "证据覆盖" not in mgmt:
            failures.append("management: evidence-coverage gating not shown")
        if "资本配置去向" not in mgmt or "内部人交易" not in mgmt:
            failures.append("management: allocation or Form 4 section missing")
        if "承诺追踪" not in mgmt:
            failures.append("management: promise tracker card missing")
        page.screenshot(path="/tmp/el_management.png", full_page=True)

        # 7) Valuation tab: real DCF + slider recompute + market quote state
        page.get_by_role("button", name="估值").click()
        page.wait_for_timeout(2500)
        val = page.locator("body").inner_text()
        if "5-Year FCFF DCF" not in val or "Scenario Valuation" not in val or "Reverse DCF" not in val:
            failures.append("valuation: DCF sections missing")
        snap = page.locator(".valuation-snapshot").first.inner_text()
        if "市场价" not in snap:
            failures.append("valuation: market snapshot card missing")
        if "未同步" not in snap and not re.search(r"\$\d+\.\d{2}", snap):
            failures.append("valuation: synced quote card missing a price")
        page.screenshot(path="/tmp/el_valuation.png", full_page=True)
        # move a slider -> fair value recomputes deterministically
        fair_before = page.locator(".fair").first.inner_text()
        slider = page.locator('input[type="range"]').nth(0)
        slider.fill("12")  # bump growth
        page.wait_for_timeout(1500)
        fair_after = page.locator(".fair").first.inner_text()
        if fair_before == fair_after:
            failures.append("valuation: slider did not recompute fair value")
        # reverse DCF
        page.locator('input[type="number"]').first.fill("300")
        page.get_by_role("button", name="计算隐含增长").click()
        page.wait_for_timeout(1500)
        if "市场隐含" not in page.locator("body").inner_text() and "无根" not in page.locator("body").inner_text():
            failures.append("valuation: reverse DCF output missing")

        # 8) Risks tab: real deterministic risk signals
        page.get_by_role("button", name="风险").click()
        page.wait_for_timeout(2000)
        rk = page.locator("body").inner_text()
        if "确定性规则" not in rk and "风险信号" not in rk:
            failures.append("risks: deterministic banner missing")
        page.screenshot(path="/tmp/el_risks.png", full_page=True)

        # 9) AI tab: evidence-first Q&A
        page.get_by_role("button", name="AI研究助手").click()
        page.wait_for_timeout(1500)
        page.get_by_role("button", name="公司最近的风险有哪些？").click()
        page.wait_for_timeout(2500)
        ai = page.locator("body").inner_text()
        if "证据优先" not in ai and "Evidence-first" not in ai:
            failures.append("ai: evidence-first banner missing")
        if "置信度" not in ai:
            failures.append("ai: structured claims with confidence missing")
        page.screenshot(path="/tmp/el_ai.png", full_page=True)

        # 10) Moat tab: real SEC-evidence signals + explicit qualitative gaps
        page.get_by_role("button", name="护城河").click()
        page.wait_for_timeout(2500)
        moat_body = page.locator("body").inner_text()
        if "护城河证据" not in moat_body or "确定性" not in moat_body:
            failures.append("moat: real evidence banner missing")
        if "证据缺口" not in moat_body:
            failures.append("moat: qualitative evidence gaps not shown")
        if "强信号" not in moat_body:
            failures.append("moat: verdict signals missing")
        if "模拟" in moat_body:
            failures.append("moat: demo banner still present")

        page.screenshot(path="/tmp/el_moat.png", full_page=True)
        browser.close()

    if console_errors:
        failures.append(f"browser console errors: {console_errors[:5]}")
    if failures:
        print("SMOKE FAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
