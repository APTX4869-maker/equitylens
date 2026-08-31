"""Playwright smoke test for the EquityLens web app (real-data pages).

Assumes:
- FastAPI on 127.0.0.1:8000 (data/equitylens.duckdb already synced)
- Next.js dev/prod server on 127.0.0.1:3000

Run:  cd apps/web && pnpm dev &  (backend already running)
      uv run python tests/e2e/smoke.py
"""

from __future__ import annotations

import sys

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:3000"


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

        # 4) Company switch -> MSFT real data
        page.get_by_role("button", name="MSFT Microsoft").click()
        page.wait_for_timeout(1500)
        expect(page.get_by_role("heading", name="Microsoft")).to_be_visible()

        # 5) Demo tab shows the demo banner
        page.get_by_role("button", name="护城河").click()
        page.wait_for_timeout(500)
        demo_body = page.locator("body").inner_text()
        if "模拟" not in demo_body:
            failures.append("moat: demo banner missing")

        page.screenshot(path="/tmp/el_demo_moat.png", full_page=True)
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
