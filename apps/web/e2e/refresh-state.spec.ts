import { expect, test, type Page } from "@playwright/test";
import { stubPublishedCompanyDirectory } from "./company-directory-fixture";

test.beforeEach(async ({ page }) => { await stubPublishedCompanyDirectory(page); });

const inputs = {
  revenue_base: 100, revenue_growth: [0.08, 0.07, 0.06, 0.05, 0.04],
  op_margin_start: 0.25, op_margin_end: 0.28, tax_rate: 0.16,
  da_pct: 0.03, capex_pct: 0.04, nwc_pct: 0.002,
  wacc: 0.10, terminal_growth: 0.02, terminal_roic: 0.20,
  net_cash: 10, shares: 10,
};

function valuationResponse(overrides: Partial<typeof inputs> = {}) {
  const current = {
    ...inputs,
    ...overrides,
    revenue_growth: [...(overrides.revenue_growth ?? inputs.revenue_growth)],
  };
  const scenario = (label: string, value: number) => ({
    label, status: "OK", reason: null, inputs: current,
    result: { fair_value_per_share: value },
  });
  return {
    ticker: "AAPL", input_fingerprint: `fp-${current.revenue_growth[0]}`,
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

async function stubShell(page: Page, freshnessModules: Array<{
  key: string; label: string; as_of: string | null; detail: string;
  status: "ok" | "stale" | "missing"; days_ago: number | null;
}> = []) {
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
    modules: freshnessModules, stale_modules: [], hint: null,
  }}));
}

async function stubMicrosoftShell(page: Page) {
  await page.route("**/api/v1/companies/MSFT?**", (route) => route.fulfill({ json: {
    ticker: "MSFT", cik: "0000789019", name: "Microsoft Corp.", exchange: "NASDAQ",
    fiscal_year_end: "06-30", source_freshness: {},
  }}));
  await page.route("**/api/v1/companies/MSFT/overview?**", (route) => route.fulfill({ json: {
    ticker: "MSFT", latest_period: null, kpis: {}, trend: {}, provenance_available: true,
  }}));
  await page.route("**/api/v1/companies/MSFT/market/quote?**", (route) => route.fulfill({ json: {
    status: "UNAVAILABLE", configured: true, synced: false, reason: "test",
  }}));
  await page.route("**/api/v1/companies/MSFT/freshness?**", (route) => route.fulfill({ json: {
    modules: [], stale_modules: [], hint: null,
  }}));
}

test("full refresh uses bounded sequential module requests", async ({ page }) => {
  await stubShell(page);
  const refreshBodies: Array<{ modules?: string[] }> = [];
  const refreshUrls: string[] = [];
  const moduleNames = ["financials", "segments", "management", "quotes"];

  await page.route("**/api/v1/companies/AAPL/refresh", async (route) => {
    refreshUrls.push(route.request().url());
    const body = route.request().postDataJSON() as { modules?: string[] };
    refreshBodies.push(body);
    const selected = body.modules?.[0];
    return route.fulfill({ json: {
      refresh_id: `refresh-${selected ?? "all"}`,
      status: "ok",
      review_required: selected === "financials",
      modules: Object.fromEntries(moduleNames.map((moduleName) => [
        moduleName,
        {
          status: moduleName === selected ? "ok" : "skipped",
          retryable: false,
          changed: moduleName === selected && selected === "financials",
        },
      ])),
    } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "↻ 刷新数据" }).click();

  await expect.poll(() => refreshBodies.length).toBe(4);
  expect(refreshBodies).toEqual(moduleNames.map((moduleName) => ({ modules: [moduleName] })));
  expect(refreshUrls.every((url) => url.startsWith("http://127.0.0.1:8000/"))).toBe(true);
  await expect(page.getByText(/financials:成功.*segments:成功.*management:成功.*quotes:成功/)).toBeVisible();
});

test("freshness dates identify their data modules", async ({ page }) => {
  await stubShell(page, [
    {
      key: "sec_financials", label: "SEC 财务事实", as_of: "2026-07-29",
      detail: "最近披露 10-K 2026-07-29", status: "ok", days_ago: 49,
    },
    {
      key: "market_quote", label: "行情快照", as_of: "2026-09-16",
      detail: "Nasdaq $492.40", status: "ok", days_ago: 0,
    },
    {
      key: "valuation_runs", label: "估值运行", as_of: "2026-09-03 14:30:23",
      detail: "12 天前更新", status: "ok", days_ago: 12,
    },
  ]);

  await page.goto("/");

  await expect(page.getByTestId("freshness-sec_financials")).toHaveText(/财务 2026-07-29/);
  await expect(page.getByTestId("freshness-market_quote")).toHaveText(/行情 2026-09-16/);
  await expect(page.getByTestId("freshness-valuation_runs")).toHaveText(/估值运行 2026-09-03$/);
});

test("freshness labels wrap inside the mobile toolbar", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await stubShell(page, [
    { key: "sec_financials", label: "SEC 财务事实", as_of: "2026-07-29", detail: "财务", status: "ok", days_ago: 49 },
    { key: "segments", label: "分部数据", as_of: "2026-07-29", detail: "分部", status: "ok", days_ago: 49 },
    { key: "management", label: "管理层/治理", as_of: "2025-10-21", detail: "治理", status: "ok", days_ago: 330 },
    { key: "market_quote", label: "行情快照", as_of: "2026-09-16", detail: "行情", status: "ok", days_ago: 0 },
    { key: "valuation_runs", label: "估值运行", as_of: "2026-09-03 14:30:23", detail: "估值", status: "ok", days_ago: 12 },
  ]);

  await page.goto("/");

  const dimensions = await page.getByTestId("freshness-group").evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
});

test("refresh reloads the active module and retries only a failed module", async ({ page }) => {
  await stubShell(page);
  let metricRequests = 0;
  const refreshBodies: unknown[] = [];
  let segmentAttempts = 0;

  await page.route("**/api/v1/companies/AAPL/metrics?**", (route) => {
    metricRequests += 1;
    return route.fulfill({ json: { ticker: "AAPL", metrics: [] } });
  });
  await page.route("**/api/v1/companies/AAPL/facts?**", (route) =>
    route.fulfill({ json: { ticker: "AAPL", facts: [] } }));
  await page.route("**/api/v1/companies/AAPL/refresh", async (route) => {
    const body = route.request().postDataJSON() as { modules: string[] };
    const selected = body.modules[0];
    refreshBodies.push(body);
    if (selected === "segments") segmentAttempts += 1;
    const failed = selected === "segments" && segmentAttempts === 1;
    const modules = Object.fromEntries(["financials", "segments", "management", "quotes"].map(
      (moduleName) => [moduleName, {
        status: moduleName === selected ? (failed ? "error" : "ok") : "skipped",
        retryable: moduleName === selected && failed,
        reason: moduleName === selected && failed ? "segment failure" : undefined,
        changed: moduleName === selected && selected === "financials",
      }],
    ));
    return route.fulfill({ json: {
      refresh_id: `refresh-${selected}-${segmentAttempts}`,
      status: failed ? "partial" : "ok",
      modules,
      review_required: selected === "financials",
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
  await expect.poll(() => refreshBodies.length).toBe(5);
  expect(refreshBodies).toEqual([
    { modules: ["financials"] },
    { modules: ["segments"] },
    { modules: ["management"] },
    { modules: ["quotes"] },
    { modules: ["segments"] },
  ]);
  await expect(page.getByText(/segments:成功/)).toBeVisible();
});

test("refresh automatically recalculates valuation with the preserved draft", async ({ page }) => {
  await stubShell(page);
  let refreshCompleted = false;
  let blockNextRefreshedDefault = false;
  let refreshedDefaultRequests = 0;
  let releaseRefreshedDefault!: () => void;
  const refreshedDefaultBlocked = new Promise<void>((resolve) => { releaseRefreshedDefault = resolve; });
  await page.route("**/api/v1/companies/AAPL/valuation/default", async (route) => {
    if (refreshCompleted) refreshedDefaultRequests += 1;
    if (refreshCompleted && blockNextRefreshedDefault) {
      blockNextRefreshedDefault = false;
      await refreshedDefaultBlocked;
    }
    return route.fulfill({ json: valuationResponse(refreshCompleted ? {
      revenue_base: 250,
      net_cash: 30,
      shares: 20,
      revenue_growth: [0.15, 0.14, 0.13, 0.12, 0.11],
    } : {}) });
  });
  await page.route("**/api/v1/companies/AAPL/valuation/plans", (route) =>
    route.fulfill({ json: { ticker: "AAPL", plans: [] } }));
  const valuationRunBodies: Array<{ assumptions: typeof inputs }> = [];
  let blockNextAutomaticRun = false;
  let releaseAutomaticRun!: () => void;
  const automaticRunBlocked = new Promise<void>((resolve) => { releaseAutomaticRun = resolve; });
  await page.route("**/api/v1/companies/AAPL/valuation/run", async (route) => {
    valuationRunRequests += 1;
    const body = route.request().postDataJSON() as { assumptions: typeof inputs };
    valuationRunBodies.push(body);
    if (blockNextAutomaticRun) {
      blockNextAutomaticRun = false;
      await automaticRunBlocked;
    }
    return route.fulfill({ json: valuationResponse(body.assumptions) });
  });
  let valuationRunRequests = 0;
  let segmentAttempts = 0;
  await page.route("**/api/v1/companies/AAPL/refresh", (route) => {
    const body = route.request().postDataJSON() as { modules: string[] };
    const selected = body.modules[0];
    if (selected === "quotes") refreshCompleted = true;
    if (selected === "segments") segmentAttempts += 1;
    const failed = selected === "segments" && segmentAttempts === 1;
    const modules = Object.fromEntries(["financials", "segments", "management", "quotes"].map(
      (moduleName) => [moduleName, {
        status: moduleName === selected ? (failed ? "error" : "ok") : "skipped",
        retryable: moduleName === selected && failed,
        reason: moduleName === selected && failed ? "retry me" : undefined,
        changed: moduleName === selected && selected === "financials",
      }],
    ));
    return route.fulfill({ json: {
      refresh_id: `refresh-${selected}-${segmentAttempts}`,
      status: failed ? "partial" : "ok",
      review_required: selected === "financials",
      modules,
    } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "估值" }).click();
  const growth = page.getByRole("slider", { name: /首年收入增速/ });
  await growth.fill("10");
  await expect(growth).toHaveValue("10");
  await expect.poll(() => valuationRunRequests).toBeGreaterThan(0);
  const runsBeforeRefresh = valuationRunRequests;

  blockNextRefreshedDefault = true;
  blockNextAutomaticRun = true;
  await page.getByRole("button", { name: "↻ 刷新数据" }).click();
  await expect.poll(() => refreshedDefaultRequests).toBe(1);
  await expect(page.getByTestId("refresh-review-warning")).toBeVisible();
  await expect(growth).toBeDisabled();
  await expect(page.getByRole("button", { name: "保存本次运行" })).toBeDisabled();
  releaseRefreshedDefault();

  await expect.poll(() => valuationRunRequests).toBeGreaterThan(runsBeforeRefresh);
  const refreshedRun = valuationRunBodies[runsBeforeRefresh]?.assumptions;
  expect(refreshedRun).toMatchObject({
    revenue_base: 250,
    net_cash: 30,
    shares: 20,
  });
  expect(refreshedRun?.revenue_growth[0]).toBeCloseTo(0.10);

  await growth.fill("11");
  await expect.poll(() => valuationRunRequests).toBe(runsBeforeRefresh + 2);
  expect(valuationRunBodies.at(-1)?.assumptions).toMatchObject({
    revenue_base: 250,
    net_cash: 30,
    shares: 20,
  });
  expect(valuationRunBodies.at(-1)?.assumptions.revenue_growth[0]).toBeCloseTo(0.11);
  releaseAutomaticRun();

  await expect(page.getByTestId("refresh-review-warning")).toBeHidden();
  await expect(growth).toHaveValue("11");
  await expect(page.getByRole("button", { name: "保存本次运行" })).toBeEnabled();

  await page.getByRole("button", { name: "重试 segments" }).click();
  await expect(page.getByText(/segments:成功/)).toBeVisible();
  expect(valuationRunRequests).toBe(runsBeforeRefresh + 2);
  await expect(page.getByTestId("refresh-review-warning")).toBeHidden();
  await expect(growth).toHaveValue("11");
  await expect(page.getByRole("button", { name: "保存本次运行" })).toBeEnabled();
});

test("refresh discards a default response started before the refresh", async ({ page }) => {
  await stubShell(page);
  let releaseOldDefault!: () => void;
  const oldDefaultBlocked = new Promise<void>((resolve) => { releaseOldDefault = resolve; });
  let refreshCompleted = false;
  let oldDefaultRequests = 0;
  let freshDefaultRequests = 0;
  const valuationRunBodies: Array<{ assumptions: typeof inputs }> = [];

  await page.route("**/api/v1/companies/AAPL/valuation/default", async (route) => {
    if (!refreshCompleted) {
      oldDefaultRequests += 1;
      await oldDefaultBlocked;
      return route.fulfill({ json: valuationResponse({ revenue_base: 100 }) });
    }
    freshDefaultRequests += 1;
    return route.fulfill({ json: valuationResponse({ revenue_base: 250, net_cash: 30, shares: 20 }) });
  });
  await page.route("**/api/v1/companies/AAPL/valuation/plans", (route) =>
    route.fulfill({ json: { ticker: "AAPL", plans: [] } }));
  await page.route("**/api/v1/companies/AAPL/valuation/run", (route) => {
    const body = route.request().postDataJSON() as { assumptions: typeof inputs };
    valuationRunBodies.push(body);
    return route.fulfill({ json: valuationResponse(body.assumptions) });
  });
  await page.route("**/api/v1/companies/AAPL/refresh", (route) => {
    const body = route.request().postDataJSON() as { modules: string[] };
    const selected = body.modules[0];
    if (selected === "quotes") refreshCompleted = true;
    return route.fulfill({ json: {
      refresh_id: `refresh-${selected}`,
      status: "ok",
      review_required: selected === "financials",
      modules: Object.fromEntries(["financials", "segments", "management", "quotes"].map(
        (moduleName) => [moduleName, {
          status: moduleName === selected ? "ok" : "skipped",
          retryable: false,
          changed: moduleName === selected && selected === "financials",
        }],
      )),
    } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "估值" }).click();
  await expect.poll(() => oldDefaultRequests).toBeGreaterThan(0);
  await page.getByRole("button", { name: "↻ 刷新数据" }).click();

  await expect.poll(() => freshDefaultRequests).toBe(1);
  await expect.poll(() => valuationRunBodies.length).toBe(1);
  expect(valuationRunBodies[0].assumptions).toMatchObject({ revenue_base: 250, net_cash: 30, shares: 20 });

  releaseOldDefault();
  await page.waitForTimeout(100);
  expect(valuationRunBodies).toHaveLength(1);
  await expect(page.getByTestId("refresh-review-warning")).toBeHidden();
});

test("retry after a refreshed default failure rebases before recalculating", async ({ page }) => {
  await stubShell(page);
  let refreshCompleted = false;
  let refreshedDefaultAttempts = 0;
  const valuationRunBodies: Array<{ assumptions: typeof inputs }> = [];

  await page.route("**/api/v1/companies/AAPL/valuation/default", (route) => {
    if (!refreshCompleted) return route.fulfill({ json: valuationResponse() });
    refreshedDefaultAttempts += 1;
    if (refreshedDefaultAttempts === 1) {
      return route.fulfill({ status: 500, json: { error: "temporary default failure" } });
    }
    return route.fulfill({ json: valuationResponse({ revenue_base: 250, net_cash: 30, shares: 20 }) });
  });
  await page.route("**/api/v1/companies/AAPL/valuation/plans", (route) =>
    route.fulfill({ json: { ticker: "AAPL", plans: [] } }));
  await page.route("**/api/v1/companies/AAPL/valuation/run", (route) => {
    const body = route.request().postDataJSON() as { assumptions: typeof inputs };
    valuationRunBodies.push(body);
    return route.fulfill({ json: valuationResponse(body.assumptions) });
  });
  await page.route("**/api/v1/companies/AAPL/refresh", (route) => {
    const body = route.request().postDataJSON() as { modules: string[] };
    const selected = body.modules[0];
    if (selected === "quotes") refreshCompleted = true;
    return route.fulfill({ json: {
      refresh_id: `refresh-${selected}`,
      status: "ok",
      review_required: selected === "financials",
      modules: Object.fromEntries(["financials", "segments", "management", "quotes"].map(
        (moduleName) => [moduleName, {
          status: moduleName === selected ? "ok" : "skipped",
          retryable: false,
          changed: moduleName === selected && selected === "financials",
        }],
      )),
    } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "估值" }).click();
  await expect(page.getByRole("slider", { name: /首年收入增速/ })).toBeVisible();
  await page.getByRole("button", { name: "↻ 刷新数据" }).click();

  await expect(page.getByText(/请求失败（500）/)).toBeVisible();
  await page.getByRole("button", { name: "重试", exact: true }).click();

  await expect.poll(() => refreshedDefaultAttempts).toBe(2);
  await expect.poll(() => valuationRunBodies.length).toBe(1);
  expect(valuationRunBodies[0].assumptions).toMatchObject({ revenue_base: 250, net_cash: 30, shares: 20 });
  await expect(page.getByTestId("refresh-review-warning")).toBeHidden();
});

test("late refresh response cannot pollute a newly selected company", async ({ page }) => {
  await stubShell(page);
  await stubMicrosoftShell(page);
  await page.route("**/api/v1/companies/AAPL/refresh", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 500));
    await route.fulfill({ json: {
      refresh_id: "late-aapl-refresh",
      status: "partial",
      review_required: false,
      modules: {
        financials: { status: "ok", retryable: false, changed: false },
        segments: { status: "error", retryable: true, changed: false, reason: "AAPL only" },
        management: { status: "ok", retryable: false, changed: false },
        quotes: { status: "ok", retryable: false, changed: false },
      },
    }});
  });

  await page.goto("/");
  await page.getByRole("button", { name: "↻ 刷新数据" }).click();
  await page.getByRole("button", { name: /MSFT Microsoft/ }).click();
  await expect(page.getByRole("heading", { name: /Microsoft Corp/ })).toBeVisible();

  await page.waitForTimeout(700);
  await expect(page.getByRole("button", { name: "重试 segments" })).toHaveCount(0);
  await expect(page.getByText(/刷新完成：/)).toHaveCount(0);
});
