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
  return {
    bear: { label: "悲观", status: "OK", reason: null, result: { fair_value_per_share: fair * 0.7 } },
    base: { label: "中性", status: "OK", reason: null, result: { fair_value_per_share: fair } },
    bull: { label: "乐观", status: "OK", reason: null, result: { fair_value_per_share: fair * 1.3 } },
  };
}

async function stubSetupPage(page: Page) {
  await page.route("**/api/v1/companies?**", (route) => route.fulfill({ json: {
    items: [{
      company_id: "0001045810", security_id: "sec-nvda", ticker: "NVDA",
      name: "NVIDIA CORP", exchange: "NASDAQ", publication_id: "pub-nvda",
      quality_status: "VERIFIED",
      capabilities: [{ module: "valuation", status: "NEEDS_CONFIGURATION", reason: "确认估值研究假设" }],
    }],
    next_cursor: null,
  } }));
  await page.route("**/api/v1/companies/NVDA?**", (route) => route.fulfill({ json: {
    ticker: "NVDA", cik: "0001045810", name: "NVIDIA CORP", exchange: "NASDAQ",
    fiscal_year_end: "01-31", source_freshness: {},
  } }));
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
  await page.route("**/api/v1/companies/NVDA/valuation-profile/draft", (route) => route.fulfill({ json: {
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
}

test("reviews complete assumptions before confirming valuation", async ({ page }) => {
  await stubSetupPage(page);
  let confirmation: Record<string, unknown> | null = null;
  await page.route("**/api/v1/companies/NVDA/valuation-profile", async (route) => {
    confirmation = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({ json: { status: "READY" } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "估值" }).click();

  const setup = page.getByTestId("valuation-setup");
  await expect(setup).toContainText("pub-nvda");
  await expect(setup).toContainText("fcff_dcf.v2");
  await expect(page.getByTestId("valuation-confirm")).toBeDisabled();

  await page.getByRole("slider", { name: /WACC/ }).fill("12");
  await expect(setup).toContainText("$180");
  await page.getByRole("checkbox", { name: /我已审核/ }).check();
  await page.getByTestId("valuation-confirm").click();

  await expect(setup).toContainText("配置已确认");
  expect(confirmation).toMatchObject({
    security_id: "sec-nvda",
    publication_id: "pub-nvda",
    model_version: "fcff_dcf.v2",
    confirmed: true,
    assumptions: { wacc: 0.12, shares: 10, revenue_base: 1000 },
  });
});
