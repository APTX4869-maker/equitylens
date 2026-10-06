"""Read-only desktop smoke against a running app's published directory.

No import, confirmation, save or refresh; calculation previews are not persisted. Expected limitations are reported,
never called a valuation pass. Run with --help for server/browser options.
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from playwright.sync_api import expect, sync_playwright


def is_expected_draft_block(response, expected: bool) -> bool:
    if not expected or response.status != 409 or not urlsplit(str(response.url)).path.endswith("/valuation-profile/draft"):
        return False
    try:
        body = response.json()
        return isinstance(body, dict) and isinstance(body.get("error"), dict) and body["error"].get("code") == "VALUATION_DEFAULT_UNAVAILABLE"
    except ValueError:
        return False


def published_companies(api_url: str) -> list[dict]:
    items: list[dict] = []
    cursor = None
    seen: set[str] = set()
    with httpx.Client(timeout=30) as client:
        while True:
            params = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            response = client.get(f"{api_url}/companies", params=params)
            response.raise_for_status()
            result = response.json()
            items.extend(item for item in result["items"] if item.get("publication_id"))
            cursor = result.get("next_cursor")
            if not cursor:
                break
            if cursor in seen:
                raise ValueError("directory returned a repeated pagination cursor")
            seen.add(cursor)
    if not items:
        raise ValueError("No published companies: finish publication first; nothing tested")
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:3000")
    parser.add_argument("--api-url", help="API prefix; default BASE/api/v1 proxy")
    parser.add_argument("--ticker", action="append", help="Published ticker (repeatable); default all")
    parser.add_argument("--chrome-path", help="Installed Chrome instead of bundled Chromium")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    try:
        companies = published_companies((args.api_url or f"{base}/api/v1").rstrip("/"))
        if args.ticker:
            requested = {ticker.upper() for ticker in args.ticker}
            absent = requested - {item["ticker"] for item in companies}
            if absent:
                raise ValueError(f"Not in published directory: {sorted(absent)}")
            companies = [item for item in companies if item["ticker"] in requested]
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        print(f"SMOKE FAILED (preflight): {exc}")
        return 1

    artifacts = Path(tempfile.mkdtemp(prefix="equitylens-smoke-"))
    failures: list[str] = []
    limitations: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=args.chrome_path)
        try:
            for company in companies:
                ticker = company["ticker"]
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.set_default_timeout(15_000)
                expected_draft_block = False
                draft_blocks: list[str] = []
                def check_response(response):
                    if response.status < 400:
                        return
                    if is_expected_draft_block(response, expected_draft_block):
                        draft_blocks.append(response.text())
                        limitations.append(f"{ticker}: review draft blocked: {response.text()}")
                    else:
                        failures.append(f"{ticker}: HTTP {response.status} {response.url}")
                page.on("response", check_response)
                page.on("pageerror", lambda exc: failures.append(f"{ticker}: runtime error {exc}"))
                page.on("console", lambda msg: failures.append(f"{ticker}: {msg.text}")
                        if msg.type == "error" and not msg.text.startswith("Failed to load resource:") else None)
                try:
                    page.goto(base, wait_until="networkidle")
                    page.get_by_role("button", name=re.compile(rf"^{re.escape(ticker)}(?:\s|$)")).click()
                    expect(page.get_by_role("heading", level=1)).to_contain_text(ticker)
                    page.get_by_role("button", name="专业模式", exact=True).click()
                    for tab, heading in [
                        ("公司总览", "公司概况"), ("财务分析", "财务分析"),
                        ("业务构成", "业务构成"), ("管理层", "管理层与公司治理"),
                        ("风险", "风险清单"), ("护城河", "护城河分析"), ("AI研究助手", "研究助手"),
                    ]:
                        page.get_by_role("button", name=re.compile(rf"{tab}$")).click()
                        expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
                        page.wait_for_load_state("networkidle")
                        expect(page.get_by_role("heading", level=1)).to_contain_text(ticker)
                        assert "加载失败" not in page.locator("main").inner_text(), f"{tab}: load failure"
                        if tab == "财务分析":
                            expect(page.get_by_text("三年简化财务表", exact=False)).to_be_visible()
                            revenue_card = page.locator(".metric-card", has_text="营业收入").first
                            expect(revenue_card.locator(".metric-value")).to_have_text(re.compile(r"^\$-?\d"))
                            revenue_card.click()
                            expect(page.get_by_text("用人话理解：", exact=True)).to_be_visible()
                            page.get_by_role("dialog").locator(".source-row button").first.click()
                            source = page.get_by_role("dialog").filter(has=page.get_by_role("heading", name="数据来源与溯源"))
                            expect(source.get_by_text("加载溯源链…", exact=True)).to_have_count(0)
                            expect(source.locator(".prov-node").first).to_be_visible()
                            assert "加载失败" not in source.inner_text(), "source drawer failed"
                            page.screenshot(path=str(artifacts / f"{ticker}-来源.png"))
                            source.get_by_role("button", name="×", exact=True).click()
                            expect(page.get_by_role("dialog")).to_have_count(0)
                        elif tab == "AI研究助手":
                            page.get_by_role("button", name="公司最近的风险有哪些？", exact=True).click()
                            expect(page.get_by_text("RESEARCH HELPER · 规则检索", exact=True)).to_be_visible()
                            expect(page.locator(".answer-point").first).to_be_visible()
                            expect(page.locator(".answer-point").first).to_contain_text("置信度")
                        page.screenshot(path=str(artifacts / f"{ticker}-{tab}.png"))
                    capability = next((item for item in company.get("capabilities", []) if item["module"] == "valuation"), {})
                    state = capability.get("status", "UNKNOWN")
                    expected_draft_block = state == "NEEDS_CONFIGURATION"
                    if state == "READY":
                        with page.expect_response(lambda res: "/valuation/default" in res.url and res.status == 200) as default_response:
                            page.get_by_role("button", name=re.compile("估值$")).click()
                        baseline = default_response.value.json()["result"]["fair_value_per_share"]
                    else:
                        page.get_by_role("button", name=re.compile("估值$")).click()
                    if state == "READY":
                        expect(page.get_by_test_id("fair-value")).to_have_text(re.compile(r"^\$-?\d"))
                        expect(page.get_by_test_id("dcf-model").get_by_role("slider")).to_have_count(5)
                        expect(page.get_by_test_id("risk-free-snapshot")).to_be_visible()
                        expect(page.get_by_test_id("valuation-plan-library")).to_be_visible()
                        assert "$$" not in page.locator(".delta").inner_text(), "duplicate currency marker"
                        slider = page.get_by_test_id("dcf-model").get_by_role("slider").first
                        growth = float(slider.input_value())
                        step = float(slider.get_attribute("step") or "1")
                        upper = float(slider.get_attribute("max"))
                        changed_growth = growth + step if growth + step <= upper else growth - step
                        with page.expect_response(lambda res: "/valuation/run" in res.url and res.status == 200) as preview_response:
                            slider.fill(str(changed_growth))
                        preview = preview_response.value.json()
                        assert abs(preview["assumptions"]["inputs"]["revenue_growth"][0] - changed_growth / 100) < 1e-9, "preview uses stale growth"
                        exact_fair = preview["result"]["fair_value_per_share"]
                        assert exact_fair != baseline, "growth preview did not recalculate precise fair value"
                        rounded_fair = Decimal(str(exact_fair)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                        expect(page.get_by_test_id("fair-value")).to_have_text(f"${rounded_fair}")
                        page.get_by_label("Reverse DCF 参考价", exact=True).fill("300")
                        page.get_by_role("button", name="计算隐含增长", exact=True).click()
                        expect(page.get_by_test_id("reverse-dcf").locator(".reverse-number")).to_be_visible()
                        expect(page.get_by_test_id("reverse-dcf").locator(".reverse-number strong")).to_have_text(re.compile(r"^-?\d+(?:\.\d+)?%$|^无根$"))
                    elif state == "NEEDS_CONFIGURATION":
                        panel = page.get_by_test_id("valuation-setup").or_(page.get_by_test_id("valuation-setup-error"))
                        expect(panel).to_be_visible(timeout=15_000)
                        page.wait_for_load_state("networkidle")
                        if page.get_by_test_id("valuation-setup-error").count():
                            assert draft_blocks, "unexpected valuation setup error (not missing defaults)"
                        expect(page.get_by_test_id("fair-value")).to_have_count(0)
                        limitations.append(f"{ticker}: valuation needs review/configuration; no confirmation submitted")
                    else:
                        expect(page.get_by_test_id("valuation-gate")).to_be_visible()
                        expect(page.get_by_test_id("fair-value")).to_have_count(0)
                        limitations.append(f"{ticker}: valuation {state}: {capability.get('reason')}")
                    page.wait_for_load_state("networkidle")
                    page.screenshot(path=str(artifacts / f"{ticker}-估值.png"))
                    print(f"{ticker}: 8 module navigation checked; valuation {state}")
                except Exception as exc:
                    failures.append(f"{ticker}: {exc}")
                    page.screenshot(path=str(artifacts / f"{ticker}-failure.png"))
                finally:
                    page.close()
        finally:
            browser.close()
    for note in limitations:
        print(f"LIMITED: {note}")
    for failure in failures:
        print(f"FAIL: {failure}")
    print(f"Artifacts: {artifacts}")
    print("SMOKE FAILED" if failures else "SMOKE OK (navigation, sources, Q&A, available valuation previews/gates; not a financial or onboarding audit)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
