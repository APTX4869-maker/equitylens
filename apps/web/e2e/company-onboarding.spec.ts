import { expect, test, type Page } from "@playwright/test";

const apple = {
  company_id: "0000320193",
  security_id: "sec-aapl",
  ticker: "AAPL",
  name: "Apple Inc.",
  exchange: "NASDAQ",
  publication_id: "pub-aapl",
  quality_status: "VERIFIED",
  capabilities: [{ module: "valuation", status: "READY", reason: null }],
};

async function installOnboardingApiFixture(page: Page) {
  let published = false;
  let createCalls = 0;
  const task = {
    onboarding_id: "onboarding-ko",
    company_id: "0000021344",
    ticker: "KO",
    company_name: "The Coca-Cola Company",
    state: "NEEDS_REVIEW",
    current_step: "PUBLISH",
    revision: 4,
    cancel_requested: false,
    input_fingerprint: "input-ko",
    discovery_id: "discovery-ko",
    profile_id: "profile-ko",
    dataset_id: "dataset-ko",
    quality_report_id: "report-ko",
    review_id: null,
    publication_id: null,
    error: null,
    created_at: "2026-09-12T01:00:00Z",
    updated_at: "2026-09-12T01:03:00Z",
    actions: ["REVIEW", "CANCEL"],
  };

  await page.route("**/api/v1/companies?**", (route) => route.fulfill({ json: {
    items: published ? [apple, { ...apple, company_id: "0000021344", security_id: "sec-ko", ticker: "KO", name: "The Coca-Cola Company", exchange: "NYSE", publication_id: "pub-ko" }] : [apple],
    next_cursor: null,
  }}));
  await page.route("**/api/v1/companies", (route) => route.fulfill({ json: { items: [apple], next_cursor: null } }));
  await page.route("**/api/v1/companies/AAPL?**", (route) => route.fulfill({ json: { ...apple, cik: apple.company_id, source_freshness: {} } }));
  await page.route("**/api/v1/companies/AAPL/overview?**", (route) => route.fulfill({ json: { ticker: "AAPL", latest_period: null, kpis: {}, trend: {}, provenance_available: true } }));
  await page.route("**/api/v1/companies/AAPL/market/quote?**", (route) => route.fulfill({ json: { status: "UNAVAILABLE", configured: false, synced: false, reason: "test" } }));
  await page.route("**/api/v1/companies/AAPL/freshness?**", (route) => route.fulfill({ json: { modules: [], stale_modules: [], hint: null } }));
  await page.route("**/api/v1/companies/discover", async (route) => {
    await route.fulfill({ json: {
      discovery_id: "discovery-ko", ticker: "KO", identity_hash: "identity-ko", expires_at: "2026-09-12T02:00:00Z",
      candidates: [{ candidate_id: "candidate-ko", company_id: "0000021344", legal_name: "The Coca-Cola Company", ticker: "KO", exchange: "NYSE", currency: "USD", instrument_type: "COMMON_STOCK", evidence: [{ source: "SEC" }] }],
      eligibility: { status: "ELIGIBLE", template: "us_gaap_operating_v1" },
      coverage: { form_counts: { "10-K": 3, "10-Q": 9 }, earliest_report_date: "2023-12-31", latest_report_date: "2026-06-30" }, evidence: [],
    }});
  });
  await page.route("**/api/v1/company-onboardings?**", async (route) => {
    return route.fulfill({ json: { items: [published ? { ...task, state: "PUBLISHED", revision: 5, publication_id: "pub-ko", actions: [] } : task], next_cursor: null } });
  });
  await page.route("**/api/v1/company-onboardings", async (route) => {
    if (route.request().method() === "POST") {
      createCalls += 1;
      await new Promise((resolve) => setTimeout(resolve, 150));
      return route.fulfill({ status: 202, json: { ...task, existing: false } });
    }
    return route.fulfill({ status: 405, json: { detail: "method not allowed" } });
  });
  await page.route("**/api/v1/company-onboardings/onboarding-ko", (route) => route.fulfill({ json: published ? { ...task, state: "PUBLISHED", revision: 5, publication_id: "pub-ko", actions: [], steps: [], checks: [] } : { ...task, steps: [], checks: [{ check_id: "identity", scope_key: "company", status: "PASS", severity: "BLOCKER", reason: null }], blocking_reasons: [] } }));
  await page.route("**/api/v1/company-onboardings/onboarding-ko/review-package", (route) => route.fulfill({ json: { onboarding_id: task.onboarding_id, company_id: task.company_id, revision: 4, fingerprint: "review-ko", dataset_id: "dataset-ko", dataset_hash: "dataset-hash", profile_id: "profile-ko", profile_hash: "profile-hash", profile: {}, source_manifest: {}, quality: { result: "PASS", checks: [{ check_id: "identity", scope_key: "company", status: "PASS", severity: "BLOCKER", reason: null }] } } }));
  await page.route("**/api/v1/company-onboardings/onboarding-ko/review", async (route) => {
    published = true;
    return route.fulfill({ json: { ...task, state: "PUBLISHED", revision: 5, publication_id: "pub-ko", actions: [] } });
  });
  return { createCalls: () => createCalls };
}

test("company appears only after publication and duplicate submit is prevented", async ({ page }) => {
  const fixture = await installOnboardingApiFixture(page);
  await page.goto("/");

  await page.getByRole("button", { name: "添加公司" }).click();
  await page.getByLabel("股票代码").fill("KO");
  await page.getByRole("button", { name: "识别公司" }).click();
  await expect(page.getByText("The Coca-Cola Company")).toBeVisible();
  const confirm = page.getByRole("button", { name: "确认并建档" });
  await confirm.dblclick();

  await expect(page.locator(".task-state", { hasText: "等待维护者复核" })).toBeVisible();
  await expect(page.getByTestId("company-list").getByText("KO", { exact: true })).toHaveCount(0);
  expect(fixture.createCalls()).toBe(1);

  await page.getByRole("button", { name: "批准并发布" }).click();
  await expect(page.getByTestId("company-list").getByText("KO", { exact: true })).toBeVisible();
});

test("add-company dialog supports Escape and restores focus", async ({ page }) => {
  await installOnboardingApiFixture(page);
  await page.goto("/");
  const trigger = page.getByRole("button", { name: "添加公司" });
  await trigger.click();
  await expect(page.getByRole("dialog", { name: "添加研究公司" })).toBeVisible();
  await expect(page.getByLabel("股票代码")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "添加研究公司" })).toBeHidden();
  await expect(trigger).toBeFocused();
});

test("quality failure disables approval with a next step", async ({ page }) => {
  await installOnboardingApiFixture(page);
  await page.route("**/api/v1/company-onboardings/onboarding-ko/review-package", (route) => route.fulfill({ json: {
    onboarding_id: "onboarding-ko", company_id: "0000021344", revision: 4, fingerprint: "review-ko",
    dataset_id: "dataset-ko", dataset_hash: "hash", profile_id: "profile-ko", profile_hash: "hash", profile: {}, source_manifest: {},
    quality: { result: "FAIL", checks: [{ check_id: "shares", scope_key: "company", status: "FAIL", severity: "BLOCKER", reason: "缺少稀释股本" }] },
  }}));
  await page.goto("/");
  await page.getByRole("button", { name: "建档中心" }).click();
  await page.getByRole("button", { name: /KO.*等待维护者复核/ }).click();
  await expect(page.getByRole("button", { name: "批准并发布" })).toBeDisabled();
  await expect(page.getByText(/补齐阻断项后重新验证/)).toBeVisible();
});

test("late company response cannot overwrite a newer security and publication selection", async ({ page }) => {
  await installOnboardingApiFixture(page);
  const microsoft = { ...apple, company_id: "0000789019", security_id: "sec-msft", ticker: "MSFT", name: "Microsoft Corp.", publication_id: "pub-msft" };
  await page.route("**/api/v1/companies?**", (route) => route.fulfill({ json: { items: [apple, microsoft], next_cursor: null } }));
  await page.route("**/api/v1/companies/AAPL?**", async (route) => { await new Promise((resolve) => setTimeout(resolve, 450)); await route.fulfill({ json: { ...apple, cik: apple.company_id, source_freshness: {} } }); });
  await page.route("**/api/v1/companies/MSFT?**", (route) => route.fulfill({ json: { ...microsoft, cik: microsoft.company_id, source_freshness: {} } }));
  await page.route("**/api/v1/companies/MSFT/overview?**", (route) => route.fulfill({ json: { ticker: "MSFT", latest_period: null, kpis: {}, trend: {}, provenance_available: true } }));
  await page.route("**/api/v1/companies/MSFT/market/quote?**", (route) => route.fulfill({ json: { status: "UNAVAILABLE", configured: false, synced: false, reason: "test" } }));
  await page.route("**/api/v1/companies/MSFT/freshness?**", (route) => route.fulfill({ json: { modules: [], stale_modules: [], hint: null } }));
  await page.goto("/");
  await page.getByRole("button", { name: /MSFT Microsoft/ }).click();
  await expect(page.getByRole("heading", { name: /Microsoft Corp/ })).toBeVisible();
  await page.waitForTimeout(600);
  await expect(page.getByRole("heading", { name: /Microsoft Corp/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Apple Inc/ })).toHaveCount(0);
});

test("mobile onboarding actions stay visible without clipped controls", async ({ page }) => {
  await installOnboardingApiFixture(page);
  await page.route("**/api/v1/companies?**", (route) => route.fulfill({ json: { items: [{ ...apple, capabilities: [{ module: "valuation", status: "NEEDS_CONFIGURATION", reason: "需要确认 USD 与稀释股本口径" }] }], next_cursor: null } }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "添加公司" }).click();
  const dialog = page.getByRole("dialog", { name: "添加研究公司" });
  await expect(dialog).toBeVisible();
  const box = await dialog.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
});

test("valuation explains a company configuration gate", async ({ page }) => {
  await installOnboardingApiFixture(page);
  await page.route("**/api/v1/companies?**", (route) => route.fulfill({ json: { items: [{ ...apple, capabilities: [{ module: "valuation", status: "NEEDS_CONFIGURATION", reason: "需要确认 USD 与稀释股本口径" }] }], next_cursor: null } }));
  await page.goto("/");
  await page.getByRole("button", { name: "估值" }).click();
  await expect(page.getByTestId("valuation-gate")).toContainText("待配置");
  await expect(page.getByTestId("valuation-gate")).toContainText("需要确认 USD 与稀释股本口径");
});
