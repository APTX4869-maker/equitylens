import { expect, test, type Page } from "@playwright/test";
import { stubPublishedCompanyDirectory } from "./company-directory-fixture";

test.beforeEach(async ({ page }) => { await stubPublishedCompanyDirectory(page); });

const inputs = {
  revenue_base: 100_000_000_000,
  revenue_growth: [0.06, 0.05, 0.045, 0.04, 0.035],
  op_margin_start: 0.30, op_margin_end: 0.305, tax_rate: 0.16,
  da_pct: 0.03, capex_pct: 0.04, nwc_pct: 0.002,
  wacc: 0.09, terminal_growth: 0.025, terminal_roic: 0.20,
  net_cash: 10_000_000_000, shares: 1_000_000_000,
  share_basis_label: "FY diluted weighted-average shares",
};

const meta = {
  revenue_base: { value: inputs.revenue_base, source_type: "canonical_fact", source: "SEC 10-K", source_ids: ["fact-revenue"], as_of: "FY2025", rule: "latest FY", reason: "最新完整财年收入", fallback_reason: null },
  shares: { value: inputs.shares, source_type: "canonical_fact", source: "SEC shares", source_ids: ["fact-shares"], as_of: "FY2025", rule: "latest FY diluted", reason: "披露的稀释口径", fallback_reason: null, basis: inputs.share_basis_label },
  net_cash: { value: inputs.net_cash, source_type: "deterministic_formula", source: "NET_DEBT", source_ids: ["fact-debt"], as_of: "FY2025", version: "net-cash.v1", rule: "sign flip", reason: "EV 到股权价值桥接", fallback_reason: null },
  revenue_growth: { value: inputs.revenue_growth, source_type: "config_assumption", source: "AAPL mature hardware/services prior", source_ids: [], version: "aapl-growth.v2", rule: "five-year path", reason: "成熟硬件与服务组合，不直接外推历史增速。", fallback_reason: null, historical_reference: { label: "历史收入 CAGR（仅作参照）", value: 0.05, period: "FY2020–FY2025", rule: "不直接用作未来预测" } },
  op_margin_end: { value: inputs.op_margin_end, source_type: "config_assumption", source: "margin path", source_ids: [], version: "margin-path.v1", rule: "latest + 0.5pp", reason: "避免机械外推高利润", fallback_reason: null },
  wacc: { value: inputs.wacc, source_type: "deterministic_formula", source: "CAPM + debt cost", source_ids: [], version: "wacc.v1", rule: "weighted capital cost", reason: "折现未来 FCFF", fallback_reason: null },
  terminal_growth: { value: inputs.terminal_growth, source_type: "config_assumption", source: "stable growth", source_ids: [], version: "terminal-growth.v1", rule: "year 6 once", reason: "成熟期名义增长", fallback_reason: null },
  terminal_roic: { value: inputs.terminal_roic, source_type: "config_assumption", source: "stable ROIC", source_ids: [], version: "terminal-roic.v1", rule: "g / ROIC", reason: "增长与再投资联动", fallback_reason: null },
};

function response(next = inputs) {
  const scenario = (key: "bear" | "base" | "bull", value: number) => ({
    label: key, story: `${key} AAPL business story`, scenario_version: "aapl-scenarios.v1",
    changed_fields: key === "base" ? [] : ["revenue_growth"], status: "OK", reason: null,
    inputs: next, result: { fair_value_per_share: value },
  });
  return {
    ticker: "AAPL", input_fingerprint: "fp-beginner", model_version: "fcff_dcf.v2",
    run_at: "2026-09-07T00:00:00Z", valuation_run_id: null,
    assumptions: { inputs: next, meta },
    result: {
      fair_value_per_share: 100, enterprise_value: 100_000_000_000, equity_value: 110_000_000_000,
      terminal_value: 80_000_000_000, pv_terminal: 60_000_000_000,
      sum_pv_fcff: 40_000_000_000, net_cash: next.net_cash, terminal_value_share: 0.60,
      model_version: "fcff_dcf.v2", warnings: [],
      forecast: [{ year: 1, revenue: 106_000_000_000, op_margin: 0.30, fcff: 10_000_000_000, pv_fcff: 9_000_000_000 }],
      terminal_forecast: { year: 6, revenue: 130_000_000_000, op_margin: 0.305, ebit: 39_650_000_000,
        nopat: 33_306_000_000, terminal_roic: 0.20, reinvestment_rate: 0.125,
        reinvestment: 4_163_250_000, fcff: 29_142_750_000,
        definition: "year-6 NOPAT × (1 − terminal_growth / terminal_roic)" },
    },
    scenarios: { bear: scenario("bear", 70), base: scenario("base", 100), bull: scenario("bull", 130) },
    sensitivity: { wacc_grid: [0.09], terminal_grid: [0.025], rows: [{ wacc: 0.09, values: [100] }] },
    model_quality: { data_completeness: "partial", estimated_inputs: ["revenue_growth"], terminal_value_share: 0.6, scenario_dispersion: 0.6, applicability: "适用于成熟科技公司", note: "不是价格正确概率" },
    market: { status: "UNAVAILABLE", reason: "行情未同步" }, risk_free: { value: 0.04 },
  };
}

async function stub(page: Page) {
  await page.route("**/api/v1/companies/AAPL?**", (route) => route.fulfill({ json: { ticker: "AAPL", cik: "0000320193", name: "Apple Inc.", exchange: "NASDAQ", fiscal_year_end: "09-30", source_freshness: {} } }));
  await page.route("**/api/v1/companies/AAPL/overview?**", (route) => route.fulfill({ json: { ticker: "AAPL", latest_period: { fiscal_year: 2025, fiscal_quarter: 4 }, kpis: {}, trend: {}, provenance_available: true } }));
  await page.route("**/api/v1/companies/AAPL/market/quote?**", (route) => route.fulfill({ json: { status: "UNAVAILABLE", reason: "test" } }));
  await page.route("**/api/v1/companies/AAPL/freshness?**", (route) => route.fulfill({ json: { modules: [], stale_modules: [], hint: null } }));
  await page.route("**/api/v1/companies/AAPL/valuation/default", (route) => route.fulfill({ json: response() }));
  await page.route("**/api/v1/companies/AAPL/valuation/plans", (route) => route.fulfill({ json: { plans: [] } }));
  await page.route("**/api/v1/companies/AAPL/valuation/run", (route) => {
    const body = route.request().postDataJSON() as { assumptions: typeof inputs };
    return route.fulfill({ json: response(body.assumptions) });
  });
}

async function stubFinancials(page: Page) {
  for (const ticker of ["AAPL", "MSFT"]) {
    const name = ticker === "AAPL" ? "Apple Inc." : "Microsoft Corp.";
    await page.route(`**/api/v1/companies/${ticker}?**`, (route) => route.fulfill({
      json: { ticker, cik: ticker === "AAPL" ? "0000320193" : "0000789019", name, exchange: "NASDAQ", fiscal_year_end: "06-30", source_freshness: {} },
    }));
    await page.route(`**/api/v1/companies/${ticker}/overview?**`, (route) => route.fulfill({
      json: { ticker, latest_period: { fiscal_year: 2025, fiscal_quarter: 4 }, kpis: {}, trend: {}, provenance_available: true },
    }));
    await page.route(`**/api/v1/companies/${ticker}/market/quote?**`, (route) => route.fulfill({ json: { status: "UNAVAILABLE", reason: "test" } }));
    await page.route(`**/api/v1/companies/${ticker}/freshness?**`, (route) => route.fulfill({ json: { modules: [], stale_modules: [], hint: null } }));
    await page.route(`**/api/v1/companies/${ticker}/metrics?**`, (route) => {
      const url = new URL(route.request().url());
      const frequency = url.searchParams.get("frequency") ?? "quarterly";
      const requested = (url.searchParams.get("metrics") ?? "").split(",");
      const metrics = requested.flatMap((metric) => {
        if (metric !== "REVENUE" && metric !== "GROSS_MARGIN") return [];
        return Array.from({ length: frequency === "quarterly" ? 5 : 2 }, (_, index) => ({
          metric,
          period: frequency === "quarterly" ? `FY2025 Q${index + 1}` : `FY${2024 + index}`,
          value: metric === "REVENUE" ? (90 + index) * 1_000_000_000 : 0.45 + index * 0.001,
          unit: metric === "REVENUE" ? "USD" : "ratio",
          status: metric === "REVENUE" ? "OFFICIAL" : "CALCULATED",
          canonical_fact_id: metric === "REVENUE" ? `${ticker}-revenue-fact` : null,
          input_fact_ids: [],
        }));
      });
      return route.fulfill({ json: { ticker, frequency, metrics } });
    });
    await page.route(`**/api/v1/companies/${ticker}/facts?**`, (route) => route.fulfill({ json: { ticker, facts: [] } }));
  }
  await page.route("**/api/v1/provenance/AAPL-revenue-fact", (route) => route.fulfill({
    json: {
      entity_id: "AAPL-revenue-fact",
      kind: "canonical_fact",
      tree: {
        entity_id: "AAPL-revenue-fact",
        kind: "canonical_fact",
        label: "AAPL revenue",
        fields: { metric: "REVENUE", period_type: "TTM", value: 94_000_000_000, unit: "USD", status: "OFFICIAL" },
        parents: [],
      },
    },
  }));
}

test("beginner can trace the valuation path without losing edits across modes", async ({ page }) => {
  await stub(page);
  await page.goto("/");
  await page.getByRole("button", { name: "◎ 估值", exact: true }).click();

  const walkthrough = page.getByTestId("beginner-valuation-walkthrough");
  await expect(walkthrough).toContainText("公司经营基准");
  await expect(walkthrough).toContainText("FY2025");
  await expect(walkthrough).toContainText("最需要自己判断的是收入增长路径");
  await expect(page.getByTestId("assumption-revenue_growth")).toContainText("历史收入 CAGR（仅作参照） 5.0%");
  await expect(page.getByTestId("assumption-revenue_growth")).toContainText("不直接外推历史增速");
  await expect(page.getByTestId("assumption-wacc")).toContainText("调高会更大幅度折价未来现金流");
  await expect(page.getByTestId("assumption-wacc")).toContainText("不是个人承诺收益率");

  await expect(page.getByTestId("sensitivity-matrix")).toBeHidden();
  await page.getByText("展开高级敏感性矩阵（WACC × 永续增长）").click();
  await expect(page.getByTestId("sensitivity-matrix")).toBeVisible();
  await expect(page.getByTestId("reverse-dcf")).toContainText("某价格隐含什么增长");
  await expect(page.getByTestId("reference-price")).toContainText("安全边际");
  await expect(page.getByTestId("plan-review-trigger")).toContainText("下季度新财报后再回来复核");

  const growth = page.getByRole("slider", { name: /首年收入增速/ });
  await growth.fill("10");
  await expect(growth).toHaveValue("10");
  await page.getByRole("button", { name: "专业模式" }).click();
  await page.getByRole("button", { name: "初学者模式" }).click();
  await expect(growth).toHaveValue("10");
});

test("financial metric units and drawers stay scoped to the selected company", async ({ page }) => {
  await stubFinancials(page);
  await page.goto("/");
  await page.getByRole("button", { name: "⌁ 财务分析", exact: true }).click();

  await expect(page.getByText("收入 · 最近季度趋势", { exact: true })).toBeVisible();
  await expect(page.getByTestId("financial-chart-unit")).toHaveText("图表单位：$B");
  await page.locator(".quarter-controls").getByRole("button", { name: "毛利率", exact: true }).click();
  await expect(page.getByText("毛利率 · 最近季度趋势", { exact: true })).toBeVisible();
  await expect(page.getByTestId("financial-chart-unit")).toHaveText("图表单位：%");

  await page.getByRole("button", { name: /营业收入/ }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: /MSFT Microsoft/ }).evaluate((button: HTMLButtonElement) => button.click());
  await expect(page.getByRole("dialog")).toBeHidden();

  const aaplButton = page.getByRole("button", { name: /AAPL Apple/ });
  await aaplButton.click();
  await expect(aaplButton).toHaveClass(/active/);
  await page.getByRole("button", { name: /营业收入/ }).click();
  await page.getByRole("button", { name: "查看来源 →" }).click();
  await expect(page.getByRole("heading", { name: "数据来源与溯源" })).toBeVisible();
  await page.getByRole("button", { name: /MSFT Microsoft/ }).evaluate((button: HTMLButtonElement) => button.click());
  await expect(page.getByRole("dialog")).toBeHidden();
});
