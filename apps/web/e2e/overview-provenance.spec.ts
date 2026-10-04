import { expect, test, type Page } from "@playwright/test";
import { stubPublishedCompanyDirectory } from "./company-directory-fixture";

test.beforeEach(async ({ page }) => { await stubPublishedCompanyDirectory(page); });

const derivedId = "derived.v2.overview-revenue";

test("missing report metadata never promotes a KPI quarter into a disclosed report", async ({ page }) => {
  await stubOverview(page);
  await page.goto("/");
  await expect(page.getByTestId("report-period-toolbar")).toContainText("报告元数据未覆盖");
  await expect(page.getByTestId("reporting-summary")).toContainText("不能把原始季度或抓取时间当作最近披露报告");
  await expect(page.getByTestId("reporting-summary").getByRole("button", { name: "查看报告来源" })).toHaveCount(0);
});

test("cash flow snapshot keeps different TTM periods visible instead of implying one subtraction", async ({ page }) => {
  await stubOverview(page);
  await page.route("**/api/v1/companies/AAPL/overview?**", route => route.fulfill({ json: {
    ticker: "AAPL", latest_period: null, trend: {}, provenance_available: true,
    kpis: {
      TTM_OPERATING_CASH_FLOW: { value: 80, period: "FY2026Q1" },
      TTM_CAPITAL_EXPENDITURES: { value: 20, period: "FY2026Q2" },
      TTM_FCF: { value: null, period: "FY2026Q3", missing_reason: "OPERATING_CASH_FLOW missing FY2026Q3" },
    },
  }}));
  await page.goto("/");
  const snapshot = page.locator(".card").filter({ has: page.getByText("现金流转化快照（真实）", { exact: true }) });
  await expect(snapshot.locator(".cash-step").nth(0)).toContainText("FY2026Q1");
  await expect(snapshot.locator(".cash-step").nth(1)).toContainText("FY2026Q2");
  await expect(snapshot.locator(".cash-step").nth(2)).toContainText("经营现金流缺少 FY2026Q3");
  await expect(snapshot.locator(".cash-step").nth(2).locator(".cash-fill")).toHaveCSS("width", "0px");
  await expect(snapshot).toContainText("只有期间一致且输入完整才能相减");
});

for (const annual of [true, false]) {
  test(`report period and ${annual ? "derived Q4" : "coverage gaps"} remain distinct`, async ({ page }) => {
    await stubOverview(page);
    await page.route("**/api/v1/companies/AAPL/overview?**", route => route.fulfill({ json: {
      ticker: "AAPL", latest_period: { fiscal_year: 2026, fiscal_quarter: annual ? 4 : 3, period_end: annual ? "2026-06-30" : "2026-05-10" },
      reporting: {
        latest_report: { fiscal_year: 2026, fiscal_quarter: annual ? 4 : 3, report_date: annual ? "2026-06-30" : "2026-05-10", filed_at: "2026-07-29", form_type: annual ? "10-K" : "10-Q", source_document_id: "current-report" },
        derived_q4_metrics: annual ? ["REVENUE"] : [],
        gaps: annual ? [] : [{ key: "REVENUE_LATEST", available_period: "FY2026Q2", target_period: "FY2026Q3", reason: "当前发布缺少该报告期的完整可计算输入" }],
      },
      period_alignment: { status: "aligned", reference_period: annual ? "FY2026Q4" : "FY2026Q2", reference_period_end: annual ? "2026-06-30" : "2026-02-15", periods: {}, mismatches: [] },
      kpis: { REVENUE_LATEST: { metric: "REVENUE", value: 40, period: annual ? "FY2026Q4" : "FY2026Q2", period_end: annual ? "2026-06-30" : "2026-02-15", status: "CALCULATED" } },
      trend: {}, provenance_available: true,
    }}));
    await page.route("**/api/v1/provenance/current-report?**", route => {
      expect(new URL(route.request().url()).searchParams.get("publication_id")).toBe("pub-aapl");
      return route.fulfill({ json: { entity_id: "current-report", kind: "source_document", tree: { entity_id: "current-report", kind: "source_document", label: "SEC report", fields: { report_date: annual ? "2026-06-30" : "2026-05-10", source_url: "https://www.sec.gov/Archives/current-report" }, parents: [] } } });
    });
    await page.goto("/");
    const summary = page.getByTestId("reporting-summary");
    await expect(summary).toContainText(annual ? "FY2026 年度" : "FY2026 Q3");
    await expect(summary).toContainText(annual ? "年度累计值减前三季度累计值" : "最近季度收入");
    if (!annual) {
      await expect(summary).toContainText("FY2026Q2");
      await expect(summary).toContainText("FY2026Q3");
      await expect(summary).toContainText("当前发布");
    }
    await expect(page.getByTestId("report-period-toolbar")).toContainText(annual ? "FY2026 年度" : "FY2026 Q3");
    await summary.getByRole("button", { name: "查看报告来源" }).click();
    await expect(page.getByRole("dialog").getByRole("link")).toHaveAttribute("href", "https://www.sec.gov/Archives/current-report");
  });
}

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

for (const sample of [
  { label: "null", value: null, note: "证据不足", display: "—", tone: "", missing: true },
  { label: "zero", value: 0, note: "现金与债务持平", display: "$0", tone: "", missing: false },
  { label: "positive", value: 2_000_000_000, note: "净负债状态", display: "$2B", tone: "warn", missing: false },
  { label: "negative", value: -2_000_000_000, note: "净现金状态", display: "$-2B", tone: "good", missing: false },
] as const) {
  test(`net debt ${sample.label} has consistent value, meaning and evidence`, async ({ page }) => {
    await stubOverview(page);
    await page.route("**/api/v1/companies/AAPL/overview?**", (route) => route.fulfill({ json: {
      ticker: "AAPL", latest_period: null, trend: {}, provenance_available: true,
      kpis: { NET_DEBT: {
        metric: "NET_DEBT", value: sample.value, unit: "USD", period: "FY2025Q4",
        status: sample.missing ? "MISSING" : "CALCULATED", result_id: sample.missing ? null : "derived-net-debt",
        canonical_fact_id: null, input_fact_ids: sample.missing ? [] : ["debt", "cash"],
        missing_reason: sample.missing ? "缺少现金或债务事实" : null,
      } },
    } }));
    await page.route("**/api/v1/provenance/derived-net-debt*", (route) => {
      expect(new URL(route.request().url()).searchParams.get("publication_id")).toBe("pub-aapl");
      return route.fulfill({ json: { entity_id: "derived-net-debt", kind: "derived_metric", tree: {
        entity_id: "derived-net-debt", kind: "derived_metric", label: "NET_DEBT · FY2025Q4",
        fields: { metric: "NET_DEBT", value: sample.value, unit: "USD", status: "CALCULATED" }, parents: [],
      } } });
    });
    await page.goto("/");
    const card = page.getByRole("button", { name: /净现金 \/ 净债务/ });
    await expect(card.locator(".brief-value")).toHaveText(sample.display);
    await expect(card.locator(".brief-note")).toContainText(sample.note);
    await expect(card.locator(".brief-note")).toHaveClass(`brief-note ${sample.tone}`);
    if (!sample.missing) await expect(card.locator(".brief-note")).toContainText("FY2025Q4");
    if (sample.missing) {
      await expect(card).toContainText("缺少现金或债务事实");
      await expect(card).not.toContainText("净负债状态");
    }
    await card.click();
    const drawer = page.getByRole("dialog");
    await expect(drawer).toContainText("正数表示净负债，负数表示净现金");
    await expect(drawer.locator(".formula")).toHaveText("Net Debt = Interest-bearing Debt − Cash & Equivalents − Short-term Investments");
    if (sample.missing) {
      await expect(drawer).toContainText("当前公司值未覆盖");
      await expect(drawer.getByRole("button", { name: "查看来源 →" })).toHaveCount(0);
    } else {
      await expect(drawer).toContainText(`当前公司值：${sample.value!.toLocaleString("en-US")} USD`);
      await drawer.getByRole("button", { name: "查看来源 →" }).click();
      await expect(page.getByRole("heading", { name: "数据来源与溯源" })).toBeVisible();
      await expect(page.getByRole("dialog")).toContainText("NET_DEBT");
    }
  });
}
