import { test, expect, type Page } from "@playwright/test";

const inputs = {
  revenue_base: 1000,
  revenue_growth: [0.30, 0.24, 0.18, 0.14, 0.10],
  op_margin_start: 0.60,
  op_margin_end: 0.605,
  tax_rate: 0.17,
  da_pct: 0.03,
  capex_pct: 0.05,
  nwc_pct: 0.002,
  wacc: 0.10,
  terminal_growth: 0.025,
  terminal_roic: 0.20,
  net_cash: 100,
  shares: 10,
  share_basis_label: "FY diluted weighted-average shares",
};

function scenarios(fair = 200) {
  const scenarioInputs = {
    revenue_growth: inputs.revenue_growth,
    op_margin_end: inputs.op_margin_end,
    wacc: inputs.wacc,
    terminal_growth: inputs.terminal_growth,
    terminal_roic: inputs.terminal_roic,
  };
  return {
    bear: { label: "悲观", status: "OK", reason: null, result: { fair_value_per_share: fair * 0.7 }, inputs: scenarioInputs },
    base: { label: "中性", status: "OK", reason: null, result: { fair_value_per_share: fair }, inputs: scenarioInputs },
    bull: { label: "乐观", status: "OK", reason: null, result: { fair_value_per_share: fair * 1.3 }, inputs: scenarioInputs },
  };
}

function readyValuation() {
  return {
    ticker: "NVDA",
    input_fingerprint: "fp-nvda-ready",
    model_version: "fcff_dcf.v2",
    run_at: "2026-09-25T00:00:00Z",
    valuation_run_id: null,
    assumptions: { inputs, meta: {} },
    result: {
      fair_value_per_share: 200,
      enterprise_value: 2100,
      equity_value: 2000,
      terminal_value: 1200,
      pv_terminal: 800,
      sum_pv_fcff: 1300,
      net_cash: inputs.net_cash,
      terminal_value_share: 0.4,
      model_version: "fcff_dcf.v2",
      terminal_forecast: {
        year: 6, revenue: 1600, op_margin: 0.605, ebit: 968, nopat: 803,
        terminal_roic: 0.2, reinvestment_rate: 0.125, reinvestment: 100,
        fcff: 703, definition: "test terminal FCFF",
      },
      forecast: [{ year: 1, revenue: 1300, op_margin: 0.6, fcff: 400, pv_fcff: 360 }],
      warnings: [],
    },
    scenarios: scenarios(),
    sensitivity: { wacc_grid: [0.1], terminal_grid: [0.025], rows: [] },
    market: { status: "UNAVAILABLE", reason: "test" },
  };
}

async function stubSetupPage(page: Page, valuationReady: () => boolean) {
  await page.route("**/api/v1/companies?**", (route) => {
    const ready = valuationReady();
    return route.fulfill({ json: {
      items: [{
      company_id: "0001045810", security_id: "sec-nvda", ticker: "NVDA",
      name: "NVIDIA CORP", exchange: "NASDAQ", publication_id: ready ? "pub-nvda-v2" : "pub-nvda",
      quality_status: "VERIFIED",
      capabilities: [{ module: "valuation", status: ready ? "READY" : "NEEDS_CONFIGURATION", reason: ready ? null : "确认估值研究假设" }],
      }],
      next_cursor: null,
    } });
  });
  await page.route("**/api/v1/companies/NVDA?**", async (route) => {
    const publicationId = new URL(route.request().url()).searchParams.get("publication_id");
    if (publicationId === "pub-nvda-v2") {
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    return route.fulfill({ json: {
      ticker: "NVDA", cik: "0001045810",
      name: publicationId === "pub-nvda-v2" ? "NVIDIA UPDATED" : "NVIDIA CORP",
      exchange: "NASDAQ", fiscal_year_end: "01-31", source_freshness: {},
    } });
  });
  await page.route("**/api/v1/companies/NVDA/overview?**", (route) => route.fulfill({ json: {
    ticker: "NVDA", latest_period: { fiscal_year: 2026, fiscal_quarter: 4 },
    kpis: {}, trend: {}, provenance_available: true,
  } }));
  await page.route("**/api/v1/companies/NVDA/market/quote?**", (route) => route.fulfill({ json: {
    status: "UNAVAILABLE", configured: true, synced: false, reason: "test",
  } }));
  await page.route("**/api/v1/companies/NVDA/freshness?**", (route) => route.fulfill({ json: {
    modules: [], stale_modules: [], hint: null,
  } }));
  await page.route("**/api/v1/company-onboardings?**", (route) => route.fulfill({ json: {
    items: [], next_cursor: null, attention_count: 0,
  } }));
  await page.route("**/api/v1/companies/NVDA/valuation-profile/draft?**", (route) => route.fulfill({ json: {
    company_id: "0001045810", ticker: "NVDA", security_id: "sec-nvda",
    publication_id: "pub-nvda", model_version: "fcff_dcf.v2",
    status: "NEEDS_CONFIGURATION", acknowledgement_required: true,
    assumptions: {
      inputs,
      meta: {
        revenue_growth: { reason: "AI 增长路径研究先验", source: "nvda-growth.v1", version: "nvda-growth.v1" },
        op_margin_end: { reason: "五年利润率路径", source: "margin-path.v1", version: "margin-path.v1" },
        wacc: { reason: "资本成本估计", source: "wacc-defaults.v6", version: "wacc-defaults.v6" },
        terminal_growth: { reason: "稳定期名义增长", source: "terminal-growth.v1", version: "terminal-growth.v1" },
        terminal_roic: { reason: "稳定期增量资本回报", source: "terminal-roic.v1", version: "terminal-roic.v1" },
      },
    },
    preview: { scenarios: scenarios(), result: { fair_value_per_share: 200 }, sensitivity: {}, model_quality: {}, market: {} },
  } }));
  await page.route("**/api/v1/companies/NVDA/valuation/run*", async (route) => {
    const body = route.request().postDataJSON() as { assumptions: typeof inputs };
    await route.fulfill({ json: {
      assumptions: { inputs: body.assumptions, meta: {} },
      scenarios: scenarios(body.assumptions.wacc === 0.12 ? 180 : 200),
      result: { fair_value_per_share: body.assumptions.wacc === 0.12 ? 180 : 200 },
    } });
  });
  await page.route("**/api/v1/companies/NVDA/valuation/default?**", (route) => route.fulfill({ json: readyValuation() }));
  await page.route("**/api/v1/companies/NVDA/valuation/plans?**", (route) => route.fulfill({ json: { ticker: "NVDA", plans: [] } }));
}

test("reviews complete assumptions before confirming valuation", async ({ page }) => {
  let ready = false;
  await stubSetupPage(page, () => ready);
  let confirmation: Record<string, unknown> | null = null;
  await page.route("**/api/v1/companies/NVDA/valuation-profile", async (route) => {
    confirmation = route.request().postDataJSON() as Record<string, unknown>;
    ready = true;
    await route.fulfill({ json: { status: "READY" } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "估值" }).click();

  const setup = page.getByTestId("valuation-setup");
  await expect(setup).toContainText("pub-nvda");
  await expect(setup).toContainText("fcff_dcf.v2");
  await expect(page.getByTestId("valuation-input-growth")).toHaveValue("30");
  await expect(page.getByTestId("valuation-input-margin")).toHaveValue("60.5");
  await expect(page.getByTestId("valuation-confirm")).toBeDisabled();

  await page.getByRole("slider", { name: /WACC/ }).fill("12");
  await expect(setup).toContainText("$180");
  await page.getByRole("checkbox", { name: /我已审核/ }).check();
  const newPublicationRequest = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname === "/api/v1/companies/NVDA"
      && url.searchParams.get("publication_id") === "pub-nvda-v2";
  });
  await page.getByTestId("valuation-confirm").click();
  await newPublicationRequest;

  // Once the directory selects v2, the v1 shell must disappear immediately;
  // it cannot be relabelled as v2 while the delayed v2 payload is still loading.
  await expect(page.getByRole("heading", { name: "NVIDIA CORP NVDA" })).toHaveCount(0, { timeout: 150 });

  await expect(page.getByTestId("valuation-setup")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "NVIDIA UPDATED NVDA" })).toBeVisible();
  await expect(page.getByTestId("fair-value")).toHaveText("$200");
  expect(confirmation).toMatchObject({
    security_id: "sec-nvda",
    publication_id: "pub-nvda",
    model_version: "fcff_dcf.v2",
    confirmed: true,
    assumptions: { wacc: 0.12, shares: 10, revenue_base: 1000 },
  });
});
