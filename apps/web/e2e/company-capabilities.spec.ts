import { expect, test, type Page } from "@playwright/test";
import { publishedCompanies } from "./company-directory-fixture";
import type { CompanyCapability } from "../src/lib/types";

async function directory(page: Page, capabilities: CompanyCapability[]) {
  await page.route("**/api/v1/companies?**", route => route.fulfill({ json: {
    items: [{ ...publishedCompanies[0], capabilities }, { ...publishedCompanies[1], capabilities: [{ module: "valuation", status: "READY", reason: null }] }], next_cursor: null,
  } }));
  for (const company of publishedCompanies) {
    const ticker = company.ticker;
    await page.route(`**/api/v1/companies/${ticker}?**`, route => route.fulfill({ json: { ...company, cik: company.company_id, source_freshness: {} } }));
    await page.route(`**/api/v1/companies/${ticker}/overview?**`, route => route.fulfill({ json: { ticker, latest_period: null, kpis: {}, trend: {} } }));
    await page.route(`**/api/v1/companies/${ticker}/market/quote?**`, route => route.fulfill({ json: { status: "UNAVAILABLE", reason: "not synced" } }));
    await page.route(`**/api/v1/companies/${ticker}/freshness?**`, route => route.fulfill({ json: { modules: [], stale_modules: [] } }));
    await page.route(`**/api/v1/companies/${ticker}/metrics?**`, route => route.fulfill({ json: { ticker, metrics: [] } }));
    await page.route(`**/api/v1/companies/${ticker}/facts?**`, route => route.fulfill({ json: { ticker, facts: [] } }));
  }
}

test("mixed capabilities explain each limit without treating market access as a fresh quote", async ({ page }) => {
  await directory(page, [
    { module: "financials", status: "READY", reason: null },
    { module: "segments", status: "NOT_DISCLOSED", reason: "no published segment facts" },
    { module: "market", status: "READY", reason: null },
    { module: "valuation", status: "NEEDS_CONFIGURATION", reason: "confirm security-specific assumptions" },
  ]);
  await page.goto("/");
  const panel = page.getByTestId("company-capabilities");
  await panel.locator(":scope > summary").click();
  await expect(panel).toContainText("已发布不等于所有模块可用");
  await expect(panel.getByTestId("capability-financials")).toContainText("期间和证据缺口");
  await expect(panel.getByTestId("capability-segments")).toContainText("当前发布无分部事实");
  await expect(panel.getByTestId("capability-market")).toContainText("不代表行情已同步或未过期");
  await expect(panel.getByTestId("capability-valuation")).toContainText("待配置或确认");
  await panel.getByRole("button", { name: "查看估值审核与阻塞" }).click();
  await expect(page.locator("#section-valuation")).toBeVisible();
});

test("data-blocked and unsupported capabilities never offer an assumption confirmation action", async ({ page }) => {
  await directory(page, [
    { module: "financials", status: "DATA_BLOCKED", reason: "published dataset has no canonical facts" },
    { module: "valuation", status: "UNSUPPORTED_MODEL", reason: "no validated valuation model for this reporting template" },
  ]);
  await page.goto("/");
  const panel = page.getByTestId("company-capabilities");
  await panel.locator(":scope > summary").click();
  await expect(panel.getByTestId("capability-financials")).toContainText("数据阻断");
  await expect(panel.getByTestId("capability-valuation")).toContainText("模型不适用");
  await expect(panel.getByTestId("capability-valuation")).toContainText("不能靠确认假设解除");
  await expect(panel.getByRole("button", { name: "查看估值审核与阻塞" })).toHaveCount(0);
});

test("missing and unknown capability states stay unverified and preserve the server reason", async ({ page }) => {
  await directory(page, [{ module: "valuation", status: "FUTURE_STATUS", reason: "special review required" }]);
  await page.goto("/");
  const panel = page.getByTestId("company-capabilities");
  await panel.locator(":scope > summary").click();
  await expect(panel.getByTestId("capability-financials")).toContainText("未记录");
  await expect(panel.getByTestId("capability-valuation")).toContainText("状态待核实");
  await expect(panel.getByTestId("capability-valuation")).toContainText("special review required");
  await expect(panel.getByRole("button", { name: "查看估值审核与阻塞" })).toHaveCount(0);
});

test("missing valuation capability blocks the engine even if defaults could be loaded", async ({ page }) => {
  await directory(page, [{ module: "financials", status: "READY", reason: null }]);
  let defaults = 0;
  await page.route("**/valuation/default?**", route => { defaults += 1; return route.fulfill({ json: {} }); });
  await page.goto("/");
  await page.getByRole("button", { name: /估值$/ }).click();
  await expect(page.getByTestId("valuation-gate")).toContainText("未记录估值能力");
  expect(defaults).toBe(0);
});

test("missing modules count as unresolved and raw unknown states remain visible without a reason", async ({ page }) => {
  await directory(page, [{ module: "valuation", status: "FUTURE_STATUS", reason: null }]);
  await page.goto("/");
  const panel = page.getByTestId("company-capabilities");
  await expect(panel.locator(":scope > summary")).toContainText("4 项需处理");
  await panel.locator(":scope > summary").click();
  await expect(panel.getByTestId("capability-valuation")).toContainText("FUTURE_STATUS");
});

test("data-blocked valuation cannot request the engine", async ({ page }) => {
  await directory(page, [{ module: "valuation", status: "DATA_BLOCKED", reason: "critical facts missing" }]);
  let defaults = 0;
  await page.route("**/valuation/default?**", route => { defaults += 1; return route.fulfill({ json: {} }); });
  await page.goto("/");
  await page.getByRole("button", { name: /估值$/ }).click();
  await expect(page.getByTestId("valuation-gate")).toContainText("critical facts missing");
  expect(defaults).toBe(0);
});

test("company switch replaces capability identity and restrictions", async ({ page }) => {
  await directory(page, [{ module: "valuation", status: "UNSUPPORTED_MODEL", reason: "Apple-specific limitation" }]);
  await page.goto("/");
  const panel = page.getByTestId("company-capabilities");
  await panel.locator(":scope > summary").click();
  await expect(panel).toContainText("Apple-specific limitation");
  await page.getByRole("button", { name: "MSFT Microsoft" }).click();
  await expect(panel).toContainText("MSFT");
  await panel.locator(":scope > summary").click();
  await expect(panel).not.toContainText("Apple-specific limitation");
  await expect(panel.getByTestId("capability-valuation")).toContainText("基准已确认");
});

test("missing valuation baseline explains maintainer action and preserves financial research", async ({ page }) => {
  await directory(page, [{ module: "valuation", status: "NEEDS_CONFIGURATION", reason: "confirm security-specific assumptions" }]);
  await page.route("**/api/v1/companies/AAPL/valuation-profile/draft?**", route => route.fulfill({ status: 409, json: { error: { code: "VALUATION_DEFAULT_UNAVAILABLE", message: "no issuer defaults configured for AAPL" } } }));
  await page.goto("/");
  await page.getByRole("button", { name: "估值" }).click();
  const blocked = page.getByTestId("valuation-setup-error");
  await expect(blocked).toContainText("需要维护者处理");
  await expect(blocked).toContainText("等待或重复刷新不会自动解除");
  await expect(blocked.getByRole("button", { name: "适配完成后重新检查" })).toBeVisible();
  await blocked.getByRole("button", { name: "继续查看财务数据" }).click();
  await expect(page.getByRole("heading", { name: "财务分析", exact: true })).toBeVisible();
});

test("a transient draft failure after a configuration block restores ordinary retry instead of claiming adaptation", async ({ page }) => {
  await directory(page, [{ module: "valuation", status: "NEEDS_CONFIGURATION", reason: "confirm security-specific assumptions" }]);
  let attempts = 0;
  await page.route("**/api/v1/companies/AAPL/valuation-profile/draft?**", route => {
    attempts += 1;
    return route.fulfill({ status: attempts === 1 ? 409 : 503, json: { error: {
      code: attempts === 1 ? "VALUATION_DEFAULT_UNAVAILABLE" : "INTERNAL_ERROR",
      message: attempts === 1 ? "no issuer defaults configured for AAPL" : "temporary service unavailable",
    } } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "估值" }).click();
  const blocked = page.getByTestId("valuation-setup-error");
  await blocked.getByRole("button", { name: "适配完成后重新检查" }).click();
  await expect(blocked).toContainText("temporary service unavailable");
  await expect(blocked).not.toContainText("需要维护者处理");
  await expect(blocked.getByRole("button", { name: "重新加载", exact: true })).toBeVisible();
  await expect(blocked.getByRole("button", { name: "适配完成后重新检查" })).toHaveCount(0);
});
