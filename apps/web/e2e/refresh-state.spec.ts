import { expect, test, type Page } from "@playwright/test";

const inputs = {
  revenue_base: 100, revenue_growth: [0.08, 0.07, 0.06, 0.05, 0.04],
  op_margin_start: 0.25, op_margin_end: 0.28, tax_rate: 0.16,
  da_pct: 0.03, capex_pct: 0.04, nwc_pct: 0.002,
  wacc: 0.10, terminal_growth: 0.02, terminal_roic: 0.20,
  net_cash: 10, shares: 10,
};

function valuationResponse(growth = inputs.revenue_growth) {
  const current = { ...inputs, revenue_growth: growth };
  const scenario = (label: string, value: number) => ({
    label, status: "OK", reason: null, inputs: current,
    result: { fair_value_per_share: value },
  });
  return {
    ticker: "AAPL", input_fingerprint: `fp-${growth[0]}`,
    model_version: "fcff_dcf.v2", run_at: "2026-09-07T00:00:00Z",
    valuation_run_id: null, assumptions: { inputs: current, meta: {} },
    result: {
      fair_value_per_share: 100, enterprise_value: 1000, equity_value: 1010,
      terminal_value: 500, pv_terminal: 300, sum_pv_fcff: 700, net_cash: 10,
      terminal_value_share: 0.3, model_version: "fcff_dcf.v2", warnings: [], forecast: [],
      terminal_forecast: {
        year: 6, revenue: 120, op_margin: 0.28, ebit: 33.6, nopat: 28.224,
        terminal_roic: 0.20, reinvestment_rate: 0.10, reinvestment: 2.8224,
        fcff: 25.4016, definition: "year-6 NOPAT × (1 − terminal_growth / terminal_roic)",
      },
    },
    scenarios: {
      bear: scenario("Bear", 80), base: scenario("Base", 100), bull: scenario("Bull", 120),
    },
    sensitivity: { wacc_grid: [0.1], terminal_grid: [0.02], rows: [] },
    market: { status: "UNAVAILABLE", reason: "test" }, risk_free: { value: 0.04 },
  };
}

async function stubShell(page: Page) {
  await page.route("**/api/v1/companies/AAPL", (route) => route.fulfill({ json: {
    ticker: "AAPL", cik: "0000320193", name: "Apple Inc.", exchange: "NASDAQ",
    fiscal_year_end: "09-30", source_freshness: {},
  }}));
  await page.route("**/api/v1/companies/AAPL/overview", (route) => route.fulfill({ json: {
    ticker: "AAPL", latest_period: null, kpis: {}, trend: {}, provenance_available: true,
  }}));
  await page.route("**/api/v1/companies/AAPL/market/quote", (route) => route.fulfill({ json: {
    status: "UNAVAILABLE", configured: true, synced: false, reason: "test",
  }}));
  await page.route("**/api/v1/companies/AAPL/freshness", (route) => route.fulfill({ json: {
    modules: [], stale_modules: [], hint: null,
  }}));
}

test("refresh reloads the active module and retries only a failed module", async ({ page }) => {
  await stubShell(page);
  let metricRequests = 0;
  const refreshBodies: unknown[] = [];

  await page.route("**/api/v1/companies/AAPL/metrics?**", (route) => {
    metricRequests += 1;
    return route.fulfill({ json: { ticker: "AAPL", metrics: [] } });
  });
  await page.route("**/api/v1/companies/AAPL/facts?**", (route) =>
    route.fulfill({ json: { ticker: "AAPL", facts: [] } }));
  await page.route("**/api/v1/companies/AAPL/refresh", async (route) => {
    const body = route.request().postDataJSON();
    refreshBodies.push(body);
    const retrying = Array.isArray(body.modules);
    return route.fulfill({ json: {
      refresh_id: retrying ? "refresh-2" : "refresh-1",
      status: retrying ? "ok" : "partial",
      modules: retrying ? {
        financials: { status: "skipped", retryable: false, changed: false },
        segments: { status: "ok", retryable: false, changed: false },
        management: { status: "skipped", retryable: false, changed: false },
        quotes: { status: "skipped", retryable: false, changed: false },
      } : {
        financials: { status: "ok", retryable: false, changed: true },
        segments: { status: "error", retryable: true, reason: "segment failure", changed: false },
        management: { status: "ok", retryable: false, changed: false },
        quotes: { status: "ok", retryable: false, changed: true },
      },
      review_required: !retrying,
    } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "财务" }).click();
  await expect.poll(() => metricRequests).toBeGreaterThanOrEqual(3);
  const beforeRefresh = metricRequests;

  await page.getByRole("button", { name: "↻ 刷新数据" }).click();
  await expect.poll(() => metricRequests).toBeGreaterThan(beforeRefresh);
  await expect(page.getByRole("button", { name: "重试 segments" })).toBeVisible();

  await page.getByRole("button", { name: "重试 segments" }).click();
  await expect.poll(() => refreshBodies.length).toBe(2);
  expect(refreshBodies).toEqual([{}, { modules: ["segments"] }]);
  await expect(page.getByText(/segments:成功/)).toBeVisible();
});

test("module retry cannot clear valuation review before recalculation", async ({ page }) => {
  await stubShell(page);
  await page.route("**/api/v1/companies/AAPL/valuation/default", (route) =>
    route.fulfill({ json: valuationResponse() }));
  await page.route("**/api/v1/companies/AAPL/valuation/plans", (route) =>
    route.fulfill({ json: { ticker: "AAPL", plans: [] } }));
  await page.route("**/api/v1/companies/AAPL/valuation/run", (route) => {
    const body = route.request().postDataJSON() as { assumptions: typeof inputs };
    return route.fulfill({ json: valuationResponse(body.assumptions.revenue_growth) });
  });
  await page.route("**/api/v1/companies/AAPL/refresh", (route) => {
    const body = route.request().postDataJSON() as { modules?: string[] };
    const retry = body.modules?.[0] === "segments";
    return route.fulfill({ json: {
      refresh_id: retry ? "refresh-retry" : "refresh-valuation",
      status: retry ? "ok" : "partial",
      review_required: !retry,
      modules: retry ? {
        financials: { status: "skipped", retryable: false, changed: false },
        segments: { status: "ok", retryable: false, changed: false },
        management: { status: "skipped", retryable: false, changed: false },
        quotes: { status: "skipped", retryable: false, changed: false },
      } : {
        financials: { status: "ok", retryable: false, changed: true },
        segments: { status: "error", retryable: true, changed: false, reason: "retry me" },
        management: { status: "ok", retryable: false, changed: false },
        quotes: { status: "ok", retryable: false, changed: true },
      },
    } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "估值" }).click();
  const growth = page.getByRole("slider", { name: /首年收入增速/ });
  await growth.fill("10");
  await expect(growth).toHaveValue("10");

  await page.getByRole("button", { name: "↻ 刷新数据" }).click();
  await expect(page.getByTestId("refresh-review-warning")).toBeVisible({ timeout: 10_000 });
  await expect(growth).toHaveValue("10");
  await expect(page.getByRole("button", { name: "保存本次运行" })).toBeDisabled();

  await page.getByRole("button", { name: "重试 segments" }).click();
  await expect(page.getByTestId("refresh-review-warning")).toBeVisible();
  await expect(page.getByRole("button", { name: "保存本次运行" })).toBeDisabled();

  await page.getByRole("button", { name: "按当前草稿重新计算" }).click();
  await expect(page.getByTestId("refresh-review-warning")).toBeHidden();
  await expect(growth).toHaveValue("10");
  await expect(page.getByRole("button", { name: "保存本次运行" })).toBeEnabled();
});
