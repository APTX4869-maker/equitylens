import { test, expect, type Page } from "@playwright/test";
import { stubPublishedCompanyDirectory } from "./company-directory-fixture";

test.beforeEach(async ({ page }) => { await stubPublishedCompanyDirectory(page); });

// Controlled-order browser tests for valuation draft identity (V03/U02): the
// newest complete draft must win, an out-of-order response must not overwrite
// it, and a failed/unapplied draft must not be saveable.

type Assumptions = {
  revenue_base: number;
  revenue_growth: number[];
  op_margin_start: number;
  op_margin_end: number;
  tax_rate: number;
  da_pct: number;
  capex_pct: number;
  nwc_pct: number;
  wacc: number;
  terminal_growth: number;
  terminal_roic: number;
  net_cash: number;
  shares: number;
};

function defaults(): Assumptions {
  return {
    revenue_base: 416_161_000_000,
    revenue_growth: [0.08, 0.075, 0.07, 0.065, 0.06],
    op_margin_start: 0.32,
    op_margin_end: 0.33,
    tax_rate: 0.16,
    da_pct: 0.03,
    capex_pct: 0.04,
    nwc_pct: 0.002,
    wacc: 0.085,
    terminal_growth: 0.025,
    terminal_roic: 0.20,
    net_cash: 36_549_000_000,
    shares: 15_000_000_000,
  };
}

function runResponse(fair: number, assumptions: Assumptions) {
  const scen = (mult: number, label: string) => ({
    label,
    status: "OK" as const,
    reason: null,
    result: { fair_value_per_share: fair * mult },
    inputs: {
      revenue_growth: assumptions.revenue_growth,
      op_margin_end: assumptions.op_margin_end,
      wacc: assumptions.wacc,
      terminal_growth: assumptions.terminal_growth,
    },
  });
  return {
    ticker: "AAPL",
    input_fingerprint: `fp-${fair}`,
    model_version: "fcff_dcf.v2",
    run_at: "2026-09-06T00:00:00",
    valuation_run_id: null,
    assumptions: { inputs: assumptions, meta: {} },
    result: {
      fair_value_per_share: fair,
      enterprise_value: fair * 10,
      equity_value: fair * 10 + assumptions.net_cash,
      terminal_value: 0,
      pv_terminal: 0,
      sum_pv_fcff: 0,
      net_cash: assumptions.net_cash,
      terminal_value_share: 0.6,
      model_version: "fcff_dcf.v2",
      terminal_forecast: {
        year: 6, revenue: 120, op_margin: 0.33, ebit: 39.6, nopat: 33.264,
        terminal_roic: assumptions.terminal_roic, reinvestment_rate: 0.125,
        reinvestment: 4.158, fcff: 29.106,
        definition: "year-6 NOPAT × (1 − terminal_growth / terminal_roic)",
      },
      forecast: [
        { year: 1, revenue: 100, op_margin: 0.3, fcff: 10, pv_fcff: 9 },
        { year: 2, revenue: 110, op_margin: 0.3, fcff: 11, pv_fcff: 9 },
      ],
      warnings: [],
    },
    scenarios: {
      bear: scen(0.8, "Bear"),
      base: scen(1.0, "Base"),
      bull: scen(1.2, "Bull"),
    },
    sensitivity: { wacc_grid: [0.085], terminal_grid: [0.025], rows: [] },
    risk_free: { value: 0.042, as_of: "2026-09-06" },
    market: { status: "UNAVAILABLE", reason: "test: no synced quote" },
  };
}

async function stubPage(page: Page) {
  await page.route("**/api/v1/companies/AAPL?**", (route) =>
    route.fulfill({
      json: {
        ticker: "AAPL",
        cik: "0000320193",
        name: "Apple Inc.",
        exchange: "NASDAQ",
        fiscal_year_end: "09-30",
        source_freshness: {},
      },
    })
  );
  await page.route("**/api/v1/companies/AAPL/overview?**", (route) =>
    route.fulfill({ json: { ticker: "AAPL", latest_period: null, kpis: {}, trend: {}, provenance_available: true } })
  );
  await page.route("**/api/v1/companies/AAPL/market/quote?**", (route) =>
    route.fulfill({ json: { status: "UNAVAILABLE", configured: true, synced: false, reason: "test" } })
  );
  await page.route("**/api/v1/companies/AAPL/freshness?**", (route) =>
    route.fulfill({ json: { modules: [], stale_modules: [], hint: null } })
  );
  await page.route("**/api/v1/companies/AAPL/valuation/plans", (route) =>
    route.fulfill({ json: { ticker: "AAPL", plans: [] } })
  );
  await page.route("**/api/v1/companies/AAPL/valuation/default", (route) =>
    route.fulfill({ json: runResponse(300, defaults()) })
  );
}

test("keeps the newest complete draft when previews return out of order", async ({ page }) => {
  const runBodies: { persist: boolean; assumptions: Assumptions }[] = [];
  let runCount = 0;

  await stubPage(page);
  await page.route("**/api/v1/companies/AAPL/valuation/run", async (route) => {
    const body = route.request().postDataJSON() as { persist: boolean; assumptions: Assumptions };
    runBodies.push(body);
    runCount += 1;
    const fair = body.assumptions.wacc === 0.12 ? 222 : 300;
    if (runCount === 1) await new Promise((r) => setTimeout(r, 500)); // hold the growth-only preview
    await route.fulfill({ json: runResponse(fair, body.assumptions) });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "估值" }).click();
  await expect(page.getByTestId("fair-value")).toHaveText("$300");

  // Edit growth to 10% (path 10/9.5/9/8.5/8), then WACC to 12% before the first
  // preview returns. The second request must carry BOTH edits.
  await page.getByRole("slider", { name: /首年收入增速/ }).fill("10");
  await page.getByRole("slider", { name: /WACC/ }).fill("12");

  // The latest (WACC) response is the one that stays visible.
  await expect(page.getByTestId("fair-value")).toHaveText("$222");
  await expect(page.getByRole("button", { name: "保存本次运行" })).toBeEnabled();

  expect(runBodies.length).toBe(2);
  const second = runBodies[1].assumptions;
  [0.1, 0.095, 0.09, 0.085, 0.08].forEach((expected, index) =>
    expect(second.revenue_growth[index]).toBeCloseTo(expected, 10));
  expect(second.wacc).toBe(0.12);
  // complete draft, not a 4-field partial override
  expect(second.revenue_base).toBe(416_161_000_000);
  expect(second.shares).toBe(15_000_000_000);
  expect(second.terminal_roic).toBe(0.20);
});

test("a failed newest request marks the result stale and disables save", async ({ page }) => {
  let failNext = false;

  await stubPage(page);
  await page.route("**/api/v1/companies/AAPL/valuation/run", async (route) => {
    if (failNext) return route.abort();
    const body = route.request().postDataJSON() as { persist: boolean; assumptions: Assumptions };
    await route.fulfill({ json: runResponse(250, body.assumptions) });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "估值" }).click();
  await expect(page.getByTestId("fair-value")).toHaveText("$300");

  failNext = true;
  await page.getByRole("slider", { name: /首年收入增速/ }).fill("10");

  // The failed preview must not be saveable as if it produced the visible result.
  await expect(page.getByRole("button", { name: "保存本次运行" })).toBeDisabled();
});


test("ignores reverse DCF response after target price changes", async ({ page }) => {
  await stubPage(page);
  await page.route("**/api/v1/companies/AAPL/valuation/reverse-dcf", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 500));
    await route.fulfill({ json: {
      implied_revenue_cagr: 0.31,
      historical_revenue_cagr: 0.08,
      no_root_reason: null,
    } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "估值" }).click();
  const target = page.getByPlaceholder("输入参考价格 $");
  await target.fill("300");
  await page.getByRole("button", { name: "计算隐含增长" }).click();
  await target.fill("200");

  await page.waitForTimeout(700);
  await expect(page.getByText("31.0%", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "计算隐含增长" })).toBeEnabled();
});
