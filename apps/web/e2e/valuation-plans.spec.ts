import { test, expect, type Page } from "@playwright/test";
import { stubPublishedCompanyDirectory } from "./company-directory-fixture";

test.beforeEach(async ({ page }) => { await stubPublishedCompanyDirectory(page); });

const inputs = {
  revenue_base: 100, revenue_growth: [0.08, 0.07, 0.06, 0.05, 0.04],
  op_margin_start: 0.25, op_margin_end: 0.28, tax_rate: 0.16,
  da_pct: 0.03, capex_pct: 0.04, nwc_pct: 0.002,
  wacc: 0.10, terminal_growth: 0.02, terminal_roic: 0.20,
  net_cash: 10, shares: 10,
};

function runResponse(saved = false) {
  const scenario = (key: "bear" | "base" | "bull", value: number) => ({
    label: key, story: `${key} company-specific story`,
    scenario_version: "test-scenarios.v1",
    changed_fields: key === "base" ? [] : ["revenue_growth", "op_margin_end"],
    status: "OK", reason: null, inputs, result: {
      fair_value_per_share: value, enterprise_value: value * 10,
      equity_value: value * 10, terminal_value: 500, pv_terminal: 300,
      sum_pv_fcff: value * 10 - 300, net_cash: 10, terminal_value_share: 0.6,
      model_version: "fcff_dcf.v2", warnings: [], forecast: [],
      terminal_forecast: {
        year: 6, revenue: 120, op_margin: 0.28, ebit: 33.6, nopat: 28.224,
        terminal_roic: 0.20, reinvestment_rate: 0.10, reinvestment: 2.8224,
        fcff: 25.4016, definition: "year-6 NOPAT × (1 − terminal_growth / terminal_roic)",
      },
    },
  });
  return {
    ticker: "AAPL", input_fingerprint: "fp-v2", model_version: "fcff_dcf.v2",
    run_at: "2026-09-06T00:00:00Z", valuation_run_id: saved ? "run-v2" : null,
    assumptions: { inputs, meta: {} },
    result: scenario("base", 100).result,
    scenarios: { bear: scenario("bear", 80), base: scenario("base", 100), bull: scenario("bull", 120) },
    sensitivity: { wacc_grid: [0.1], terminal_grid: [0.02], rows: [] },
    market: { status: "UNAVAILABLE", reason: "test" },
    risk_free: { value: 0.04 },
  };
}

async function stubShell(page: Page) {
  await page.route("**/api/v1/companies/AAPL?**", (route) => route.fulfill({ json: {
    ticker: "AAPL", cik: "0000320193", name: "Apple Inc.", exchange: "NASDAQ",
    fiscal_year_end: "09-30", source_freshness: {},
  }}));
  await page.route("**/api/v1/companies/AAPL/overview?**", (route) => route.fulfill({ json: {
    ticker: "AAPL", latest_period: null, kpis: {}, trend: {}, provenance_available: true,
  }}));
  await page.route("**/api/v1/companies/AAPL/market/quote?**", (route) => route.fulfill({ json: {
    status: "UNAVAILABLE", configured: true, synced: false, reason: "test",
  }}));
  await page.route("**/api/v1/companies/AAPL/freshness?**", (route) => route.fulfill({ json: {
    modules: [], stale_modules: [], hint: null,
  }}));
  await page.route("**/api/v1/companies/AAPL/valuation/default", (route) =>
    route.fulfill({ json: runResponse(false) }));
}

test("save, open, copy and compare traceable valuation plans", async ({ page }) => {
  await stubShell(page);
  const plans: Record<string, unknown>[] = [];
  let planRequest: Record<string, unknown> | null = null;

  await page.route("**/api/v1/companies/AAPL/valuation/run", (route) =>
    route.fulfill({ json: runResponse(true) }));
  await page.route("**/api/v1/companies/AAPL/valuation/plans", async (route) => {
    if (route.request().method() === "GET") return route.fulfill({ json: { plans } });
    planRequest = route.request().postDataJSON() as Record<string, unknown>;
    const created = {
      plan_id: "plan-1", name: "Bear 方案", valuation_run_id: "run-v2",
      scenario_key: "bear", reference_value: 80, reference_price: 60,
      margin_of_safety: 0.25, notes: "等待验证", conditions_to_verify: ["条件 A"],
      version: 1, review_status: "current",
    };
    plans.splice(0, plans.length, created);
    return route.fulfill({ json: created });
  });
  await page.route("**/api/v1/companies/AAPL/valuation/plans/plan-1", (route) =>
    route.fulfill({ json: plans[0] }));
  await page.route("**/api/v1/companies/AAPL/valuation/plans/plan-1/copy", (route) => {
    const copied = { ...plans[0], plan_id: "plan-2", name: "Bear 方案 副本",
      parent_plan_id: "plan-1", version: 2, margin_of_safety: 0.30, reference_price: 56 };
    plans.unshift(copied);
    return route.fulfill({ json: copied });
  });
  await page.route("**/api/v1/companies/AAPL/valuation/plans/compare?**", (route) =>
    route.fulfill({ json: { plans, changed_fields: ["margin_of_safety", "reference_price"] } }));

  await page.goto("/");
  await page.getByRole("button", { name: "估值" }).click();
  await expect(page.getByText("bear company-specific story")).toBeVisible();
  await page.getByText("查看全部假设与差异").first().click();
  await expect(page.getByText(/相对当前草稿变更：revenue_growth、op_margin_end/).first()).toBeVisible();
  await page.getByRole("button", { name: "保存本次运行" }).click();
  await expect(page.getByText(/已保存 · run run-v2/)).toBeVisible();

  await page.getByLabel("参考情景").selectOption("bear");
  await page.getByLabel("方案备注").fill("等待验证");
  await page.getByLabel("待验证条件").fill("条件 A");
  await page.getByRole("spinbutton", { name: "安全边际 %" }).fill("25");
  await page.getByRole("textbox", { name: "方案名" }).fill("Bear 方案");
  await page.getByRole("button", { name: "保存参考价方案" }).click();
  await expect(page.getByText(/已保存方案：参考价 \$60/)).toBeVisible();
  expect(planRequest).toMatchObject({ valuation_run_id: "run-v2", scenario_key: "bear", margin_of_safety: 0.25 });
  expect(planRequest).not.toHaveProperty("reference_value");

  await page.getByRole("button", { name: "打开" }).click();
  await expect(page.getByTestId("plan-detail")).toContainText("等待验证");
  await page.getByRole("button", { name: "复制" }).click();
  await expect(page.getByText(/已复制为版本 2/)).toBeVisible();

  await page.getByLabel("比较 Bear 方案 副本").check();
  await page.getByLabel("比较 Bear 方案", { exact: true }).check();
  await page.getByRole("button", { name: "比较所选方案" }).click();
  await expect(page.getByTestId("plan-comparison")).toContainText("margin_of_safety");
});
