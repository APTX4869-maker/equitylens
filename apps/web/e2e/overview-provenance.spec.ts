import { expect, test, type Page } from "@playwright/test";
import { stubPublishedCompanyDirectory } from "./company-directory-fixture";

test.beforeEach(async ({ page }) => { await stubPublishedCompanyDirectory(page); });

const derivedId = "derived.v2.overview-revenue";

async function stubOverview(page: Page) {
  await page.route("**/api/v1/companies/AAPL?**", (route) => route.fulfill({ json: {
    ticker: "AAPL", cik: "0000320193", name: "Apple Inc.", exchange: "NASDAQ",
    fiscal_year_end: "09-30", source_freshness: {},
  }}));
  await page.route("**/api/v1/companies/AAPL/overview?**", (route) => route.fulfill({ json: {
    ticker: "AAPL",
    latest_period: { fiscal_year: 2025, fiscal_quarter: 4, period_end: "2025-09-27" },
    kpis: {
      TTM_REVENUE: {
        metric: "REVENUE", value: 400_000_000_000, unit: "USD", period: "FY2025Q4",
        status: "CALCULATED", result_id: derivedId, canonical_fact_id: null,
        input_fact_ids: ["revenue-q1", "revenue-q2", "revenue-q3", "revenue-q4"],
      },
    },
    trend: {
      revenue: { label: "REVENUE", unit: "USD", values: [90_000_000_000, 100_000_000_000], periods: ["FY2025Q3", "FY2025Q4"] },
      revenueGrowth: { label: "REVENUE_GROWTH_YOY", unit: "ratio", values: [0.04, 0.05], periods: ["FY2025Q3", "FY2025Q4"] },
      grossMargin: { label: "GROSS_MARGIN", unit: "ratio", values: [0.45, 0.46], periods: ["FY2025Q3", "FY2025Q4"] },
      opMargin: { label: "OPERATING_MARGIN", unit: "ratio", values: [0.30, 0.31], periods: ["FY2025Q3", "FY2025Q4"] },
      fcf: { label: "FCF", unit: "USD", values: [20_000_000_000, 22_000_000_000], periods: ["FY2025Q3", "FY2025Q4"] },
    },
    provenance_available: true,
  }}));
  await page.route("**/api/v1/companies/AAPL/market/quote?**", (route) => route.fulfill({ json: {
    status: "UNAVAILABLE", configured: true, synced: false, reason: "test",
  }}));
  await page.route("**/api/v1/companies/AAPL/freshness?**", (route) => route.fulfill({ json: {
    modules: [], stale_modules: [], hint: null,
  }}));
  await page.route(`**/api/v1/provenance/${derivedId}*`, (route) => {
    expect(new URL(route.request().url()).searchParams.get("publication_id")).toBe("pub-aapl");
    return route.fulfill({ json: {
    entity_id: derivedId, kind: "derived_metric", tree: {
      entity_id: derivedId, kind: "derived_metric", label: "REVENUE · FY2025Q4",
      fields: { metric: "REVENUE", value: 400_000_000_000, unit: "USD", status: "CALCULATED" },
      parents: [],
    },
  }});
  });
}

test("overview chart and KPI source follow the selected metric", async ({ page }) => {
  await stubOverview(page);
  await page.goto("/");

  await page.getByRole("button", { name: "毛利率", exact: true }).click();
  await expect(page.getByTestId("overview-chart-title")).toHaveText("毛利率 · 最近 8 季（真实）");
  await expect(page.getByTestId("overview-chart-unit")).toHaveText("图表单位：%");

  await page.getByRole("button", { name: /TTM 营业收入/ }).click();
  await expect(page.getByRole("dialog")).toContainText("当前公司值");
  await page.getByRole("button", { name: "查看来源 →" }).click();
  await expect(page.getByRole("heading", { name: "数据来源与溯源" })).toBeVisible();
  await expect(page.getByRole("dialog")).toContainText("REVENUE");
});
