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

function runResponse(saved = false, next = inputs) {
  const scenario = (key: "bear" | "base" | "bull", value: number) => ({
    label: key, story: `${key} company-specific story`, scenario_version: "test-scenarios.v1",
    changed_fields: key === "base" ? [] : ["revenue_growth", "op_margin_end"],
    status: "OK", reason: null, inputs: next, result: {
      fair_value_per_share: value, enterprise_value: value * 10, equity_value: value * 10,
      terminal_value: 500, pv_terminal: 300, sum_pv_fcff: value * 10 - 300,
      net_cash: 10, terminal_value_share: 0.6, model_version: "fcff_dcf.v2",
      warnings: [], forecast: [], terminal_forecast: {
        year: 6, revenue: 120, op_margin: 0.28, ebit: 33.6, nopat: 28.224,
        terminal_roic: 0.20, reinvestment_rate: 0.10, reinvestment: 2.8224,
        fcff: 25.4016, definition: "year-6 NOPAT × (1 − terminal_growth / terminal_roic)",
      },
    },
  });
  return {
    ticker: "AAPL", input_fingerprint: `fp-${next.wacc}`, model_version: "fcff_dcf.v2",
    run_at: "2026-09-06T00:00:00Z", valuation_run_id: saved ? `run-${next.wacc}` : null,
    assumptions: { inputs: next, meta: {} }, result: scenario("base", 100).result,
    scenarios: { bear: scenario("bear", 80), base: scenario("base", 100), bull: scenario("bull", 120) },
    sensitivity: { wacc_grid: [next.wacc], terminal_grid: [0.02], rows: [] },
    market: { status: "UNAVAILABLE", reason: "test" }, risk_free: { value: 0.04 },
  };
}

function plan(index: number, overrides: Record<string, unknown> = {}) {
  return {
    plan_id: `plan-${index}`, name: `方案 ${String(index).padStart(2, "0")}`,
    valuation_run_id: `stored-run-${index}`, scenario_key: "base",
    reference_value: 100, reference_price: 80, margin_of_safety: 0.20,
    reference_price_reason: null, notes: `第 ${index} 个方案备注`,
    conditions_to_verify: [`条件 ${index}`], parent_plan_id: null,
    version: 1, review_status: "current", review_reason: null,
    assumptions_json: { ...inputs, wacc: index === 19 ? 0.11 : 0.10 },
    archived_at: null as string | null,
    ...overrides,
  };
}

type Plan = ReturnType<typeof plan>;

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
  await page.route("**/api/v1/companies/AAPL/valuation/default?**", (route) =>
    route.fulfill({ json: runResponse(false) }));
}

async function openValuation(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "估值" }).click();
  await expect(page.getByTestId("valuation-plan-library")).toBeVisible();
}

test("plan library exposes retry, all pages, search, archive, restore and immutable detail", async ({ page }) => {
  await stubShell(page);
  const plans: Plan[] = Array.from({ length: 20 }, (_, index) => plan(20 - index));
  const bearPlan = plans.find((item) => item.plan_id === "plan-13")!;
  bearPlan.scenario_key = "bear";
  bearPlan.reference_value = 70;
  bearPlan.assumptions_json = { ...bearPlan.assumptions_json, wacc: 0.2 };
  let failList = true;

  await page.route("**/api/v1/companies/AAPL/valuation/runs/**", (route) => {
    const runId = new URL(route.request().url()).pathname.split("/").at(-1);
    return route.fulfill({ json: {
      valuation_run_id: runId, status: "complete", model_name: "FCFF_DCF",
      model_version: "fcff_dcf.v2", run_at: "2026-09-06T00:00:00Z",
      assumptions: { inputs, meta: {} }, output: { fair_value_per_share: 100 },
      scenarios: runResponse().scenarios, sensitivity: null, model_quality: null, warnings: [],
    }});
  });
  await page.route("**/api/v1/companies/AAPL/valuation/plans**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (request.method() === "GET" && path.endsWith("/plans")) {
      if (failList) {
        return route.fulfill({ status: 503, json: { detail: "方案库暂时不可用" } });
      }
      const status = url.searchParams.get("status") ?? "active";
      const q = (url.searchParams.get("q") ?? "").toLowerCase();
      const offset = Number(url.searchParams.get("cursor") ?? 0);
      const filtered = plans.filter((item) => {
        const archived = item.archived_at != null;
        return (status === "archived" ? archived : !archived)
          && (!q || `${item.name} ${item.notes}`.toLowerCase().includes(q));
      });
      const items = filtered.slice(offset, offset + 6);
      const next = offset + items.length < filtered.length ? String(offset + items.length) : null;
      return route.fulfill({ json: { plans: items, next_cursor: next } });
    }
    const id = path.split("/").at(-2);
    if (request.method() === "POST" && path.endsWith("/archive")) {
      const item = plans.find((candidate) => candidate.plan_id === id)!;
      item.archived_at = "2026-10-03T00:00:00Z";
      return route.fulfill({ json: item });
    }
    if (request.method() === "POST" && path.endsWith("/restore")) {
      const item = plans.find((candidate) => candidate.plan_id === id)!;
      item.archived_at = null;
      return route.fulfill({ json: item });
    }
    if (request.method() === "GET") {
      const planId = path.split("/").at(-1);
      return route.fulfill({ json: plans.find((candidate) => candidate.plan_id === planId) });
    }
    return route.fallback();
  });

  await openValuation(page);
  await expect(page.getByText("方案库暂时不可用")).toBeVisible();
  failList = false;
  await page.getByRole("button", { name: "重试加载方案" }).click();
  await expect(page.getByText("方案 20", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "加载更多方案" }).click();
  await page.getByRole("button", { name: "加载更多方案" }).click();
  await page.getByRole("button", { name: "加载更多方案" }).click();
  await expect(page.getByTestId("plan-library-row")).toHaveCount(20);
  await expect(page.getByText("方案 01", { exact: true })).toBeVisible();

  await page.getByRole("searchbox", { name: "搜索方案" }).fill("方案 13");
  await page.getByRole("button", { name: "搜索方案" }).click();
  await expect(page.getByTestId("plan-library-row")).toHaveCount(1);
  await page.getByRole("button", { name: "归档方案 13" }).click();
  await expect(page.getByText("没有匹配的有效方案")).toBeVisible();

  await page.getByRole("button", { name: "已归档" }).click();
  await expect(page.getByText("方案 13", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "恢复方案 13" }).click();
  await expect(page.getByText("没有匹配的归档方案")).toBeVisible();
  await page.getByRole("button", { name: "有效方案" }).click();
  await page.getByRole("button", { name: "打开方案 13" }).click();
  const detail = page.getByTestId("plan-detail");
  await expect(detail).toContainText("第 13 个方案备注");
  await expect(detail).toContainText("条件 13");
  await expect(detail).toContainText("WACC");
  await expect(detail).toContainText("20.00%");
  await expect(detail).toContainText("所选情景每股价值");
  await expect(detail.getByText("$70.00", { exact: true })).toBeVisible();
});

test("copy-and-edit saves lineage and comparison shows actual values including equal fields", async ({ page }) => {
  await stubShell(page);
  const plans: Plan[] = [plan(20), plan(19), plan(18)];
  let savedRequest: Record<string, unknown> | null = null;
  let createRequests = 0;
  const runBodies: Array<{ assumptions: typeof inputs; persist?: boolean }> = [];

  await page.route("**/api/v1/companies/AAPL/valuation/run?**", (route) => {
    const body = route.request().postDataJSON() as { assumptions: typeof inputs; persist?: boolean };
    runBodies.push(body);
    return route.fulfill({ json: runResponse(Boolean(body.persist), body.assumptions) });
  });
  await page.route("**/api/v1/companies/AAPL/valuation/plans**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (request.method() === "GET" && path.endsWith("/plans")) {
      return route.fulfill({ json: { plans, next_cursor: null } });
    }
    if (request.method() === "POST" && path.endsWith("/copy")) {
      return route.fulfill({ json: {
        parent_plan_id: "plan-20", next_version: 2,
        assumptions: {
          revenue_growth: plans[0].assumptions_json.revenue_growth,
          op_margin_end: plans[0].assumptions_json.op_margin_end,
          wacc: plans[0].assumptions_json.wacc,
          terminal_growth: plans[0].assumptions_json.terminal_growth,
          terminal_roic: plans[0].assumptions_json.terminal_roic,
        }, source_plan: plans[0],
        plan_defaults: { scenario_key: "base", margin_of_safety: 0.2,
          name: "方案 20 副本", notes: "复制后调整", conditions_to_verify: ["条件 20"] },
      }});
    }
    if (request.method() === "GET" && path.endsWith("/compare")) {
      const ids = (url.searchParams.get("ids") ?? "").split(",");
      const chosen = plans.filter((item) => ids.includes(item.plan_id));
      const values = chosen.map((item) => ({ plan_id: item.plan_id, value: item.assumptions_json.wacc }));
      const margins = chosen.map((item) => ({ plan_id: item.plan_id, value: item.assumptions_json.op_margin_end }));
      const hasDifferences = new Set(values.map((item) => item.value)).size > 1;
      return route.fulfill({ json: { plans: chosen, fields: [
        { key: "wacc", label: "WACC", values, changed: hasDifferences },
        { key: "op_margin_end", label: "第 5 年营业利润率", values: margins, changed: false },
      ], changed_fields: hasDifferences ? ["wacc"] : [], has_differences: hasDifferences } });
    }
    if (request.method() === "POST" && path.endsWith("/plans")) {
      createRequests += 1;
      savedRequest = request.postDataJSON() as Record<string, unknown>;
      await new Promise((resolve) => setTimeout(resolve, 200));
      const created = plan(21, { ...savedRequest, plan_id: "plan-21", version: 2 });
      plans.unshift(created);
      return route.fulfill({ json: created });
    }
    return route.fallback();
  });

  await openValuation(page);
  await page.getByRole("button", { name: "复制并编辑方案 20" }).click();
  await expect(page.getByText("正在编辑“方案 20”的新版本 v2")).toBeVisible();
  await page.getByTestId("valuation-input-wacc").fill("11");
  await expect.poll(() => runBodies.length).toBeGreaterThan(0);
  expect(runBodies.at(-1)?.assumptions.revenue_base).toBe(inputs.revenue_base);
  await page.getByRole("button", { name: "保存本次运行" }).click();
  await expect(page.getByText(/已保存 · run run-0.11/)).toBeVisible();
  await page.getByRole("button", { name: "保存参考价方案" }).dblclick();
  await expect.poll(() => savedRequest).not.toBeNull();
  expect(createRequests).toBe(1);
  expect(savedRequest).toMatchObject({ parent_plan_id: "plan-20", valuation_run_id: "run-0.11" });

  await page.getByLabel("比较 方案 20").check();
  await page.getByLabel("比较 方案 19").check();
  await page.getByRole("button", { name: "比较所选方案" }).click();
  const comparison = page.getByTestId("plan-comparison");
  await expect(comparison).toContainText("WACC");
  await expect(comparison).toContainText("10.00%");
  await expect(comparison).toContainText("11.00%");
  await expect(comparison).toContainText("第 5 年营业利润率");
  await expect(comparison).toContainText("相同");

  await page.getByLabel("比较 方案 19").uncheck();
  await page.getByLabel("比较 方案 18").check();
  await page.getByRole("button", { name: "比较所选方案" }).click();
  await expect(comparison).toContainText("方案完全相同");
});
