import { expect, test, type Page } from "@playwright/test";
import { stubPublishedCompanyDirectory } from "./company-directory-fixture";

test.beforeEach(async ({ page }) => { await stubPublishedCompanyDirectory(page); });

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
}

test("risk page exposes incomplete coverage instead of claiming no risk", async ({ page }) => {
  await stubShell(page);
  await page.route("**/api/v1/companies/AAPL/risks", (route) => route.fulfill({ json: {
    risks: [], checks: [
      { key: "growth", status: "OK", reason: null, evidence_ids: ["fact-1"] },
      { key: "cash_flow", status: "INCOMPLETE_PERIOD", reason: "缺 FY2026Q1", evidence_ids: [] },
    ],
    coverage: {
      total: 2, completed: 1, complete: false,
      unavailable: [{ key: "cash_flow", status: "INCOMPLETE_PERIOD", reason: "缺 FY2026Q1", evidence_ids: [] }],
    },
  } }));

  await page.goto("/");
  await page.getByRole("button", { name: "△ 风险", exact: true }).click();
  await expect(page.getByTestId("risk-coverage-warning")).toContainText("缺 FY2026Q1");
  await expect(page.getByText("仅完成 1/2 项检查；未命中不代表未完成模块没有风险。")).toBeVisible();
});

test("risk evidence control uses a user-facing label while retaining provenance", async ({ page }) => {
  await stubShell(page);
  await page.route("**/api/v1/companies/AAPL/risks", (route) => route.fulfill({ json: {
    risks: [{
      category: "financial", severity: "HIGH", title: "现金流承压", description: "自由现金流下降",
      evidence_ids: ["src_sec_000012345678"], monitoring: "自由现金流", confidence: "HIGH", generated_by: "deterministic-rules.v1",
    }],
    checks: [{ key: "cash_flow", status: "OK", reason: null, evidence_ids: ["src_sec_000012345678"] }],
    coverage: { total: 1, completed: 1, complete: true, unavailable: [] },
  } }));
  await page.route("**/api/v1/provenance/src_sec_000012345678*", (route) => route.fulfill({ json: {
    entity_id: "src_sec_000012345678", kind: "source", tree: {
      entity_id: "src_sec_000012345678", kind: "source", label: "SEC 10-Q", fields: {}, parents: [],
    },
  } }));

  await page.goto("/");
  await page.getByRole("button", { name: "△ 风险", exact: true }).click();
  const evidence = page.getByRole("button", { name: "查看证据", exact: true });
  await expect(evidence).toBeVisible();
  await expect(page.getByText(/src_sec_0000/)).toHaveCount(0);
  await evidence.click();
  await expect(page.getByRole("dialog")).toContainText("SEC 10-Q");
});

test("research claims open resolvable evidence and unsupported questions stay in scope", async ({ page }) => {
  await stubShell(page);
  await page.route("**/api/v1/provenance/fact-1*", (route) => route.fulfill({ json: {
    entity_id: "fact-1", kind: "canonical_fact", tree: {
      entity_id: "fact-1", kind: "canonical_fact", label: "OPERATING_MARGIN",
      fields: { metric: "OPERATING_MARGIN", value: 0.3, unit: "ratio", status: "NORMALIZED" },
      parents: [],
    },
  } }));
  await page.route("**/api/v1/research/ask", (route) => {
    const question = (route.request().postDataJSON() as { question: string }).question;
    const unsupported = question.includes("内部预测");
    return route.fulfill({ json: unsupported ? {
      intent: "unsupported", supported_topics: ["增长", "利润率", "现金流", "风险", "估值", "业务构成", "指标解释"],
      answer: "这个问题超出当前规则检索能力。当前支持：增长、利润率、现金流、风险、估值、业务构成和指标解释。",
      claims: [], metric_ids: [], limitations: ["当前是确定性规则检索。"],
    } : {
      intent: "margin", supported_topics: ["增长", "利润率"], answer: "AAPL 最新利润率：",
      claims: [{ claim: "营业利润率 30.0%。", confidence: "HIGH", evidence_ids: ["fact-1"] }],
      metric_ids: ["OPERATING_MARGIN"], limitations: [],
    } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: /AI研究助手/ }).click();
  await page.getByRole("button", { name: "利润率现在怎么样？" }).click();
  await page.getByRole("button", { name: /证据 fact-1/ }).click();
  await expect(page.getByRole("dialog")).toContainText("OPERATING_MARGIN");
  await page.getByRole("button", { name: "×" }).click();

  const input = page.getByPlaceholder(/输入你的研究问题/);
  await input.fill("公司2027年收入的内部预测是多少？");
  await page.getByRole("button", { name: "提问" }).click();
  await expect(page.getByText(/超出当前规则检索能力/)).toBeVisible();
  await expect(page.locator(".answer-point")).toHaveCount(0);
});

test("annual statement cells open provenance for the selected publication", async ({ page }) => {
  await stubShell(page);
  let factsUsedSelectedPublication = false;
  let provenanceUsedSelectedPublication = false;
  const statementMetrics = [
    ["REVENUE", "营业收入"],
    ["GROSS_PROFIT", "毛利润"],
    ["OPERATING_INCOME", "营业利润"],
    ["NET_INCOME", "净利润"],
    ["OPERATING_CASH_FLOW", "经营现金流"],
    ["CAPITAL_EXPENDITURES", "资本开支"],
  ] as const;

  await page.route("**/api/v1/companies/AAPL/metrics?**", (route) => route.fulfill({ json: {
    ticker: "AAPL", company_id: "0000320193", security_id: "sec-aapl",
    publication_id: "pub-aapl", frequency: "annual", metrics: [],
  }}));
  await page.route("**/api/v1/companies/AAPL/facts?**", (route) => {
    const url = new URL(route.request().url());
    factsUsedSelectedPublication = url.searchParams.get("publication_id") === "pub-aapl";
    const facts = statementMetrics.flatMap(([metric], metricIndex) =>
      [2023, 2024, 2025].map((year) => ({
        metric, period: `FY${year}`, period_type: "FY", fiscal_year: year,
        fiscal_quarter: null, period_start: `${year}-01-01`, period_end: `${year}-12-31`,
        instant_date: null, value: (metricIndex + 1) * 100_000_000_000 + (year - 2023),
        unit: "USD", status: "REPORTED", canonical_fact_id: `fact-${metric}-${year}`,
        provenance: { source_document_id: `source-${year}` }, input_fact_ids: [],
      }))
    );
    return route.fulfill({ json: {
      ticker: "AAPL", company_id: "0000320193", security_id: "sec-aapl",
      publication_id: "pub-aapl", frequency: "annual", view: "latest_restated", facts,
    } });
  });
  await page.route("**/api/v1/provenance/fact-REVENUE-2023?**", (route) => {
    const url = new URL(route.request().url());
    provenanceUsedSelectedPublication = url.searchParams.get("publication_id") === "pub-aapl";
    return route.fulfill({ json: {
      entity_id: "fact-REVENUE-2023", kind: "canonical_fact", tree: {
        entity_id: "fact-REVENUE-2023", kind: "canonical_fact", label: "REVENUE",
        fields: { metric: "REVENUE", fiscal_year: 2023, value: 100_000_000_000, unit: "USD", status: "REPORTED" },
        parents: [],
      },
    } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "⌁ 财务分析", exact: true }).click();

  const sourceButtons = page.locator('[data-testid="annual-statement-source"]');
  await expect(sourceButtons).toHaveCount(18);
  await page.getByRole("button", { name: /查看 营业收入 FY2023 来源/ }).click();
  await expect(page.getByRole("dialog")).toContainText("REVENUE");
  expect(factsUsedSelectedPublication).toBe(true);
  expect(provenanceUsedSelectedPublication).toBe(true);
});
