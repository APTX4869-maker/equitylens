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
      eligibility: { status: "SUPPORTED", template: "us_gaap_operating_v1" },
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
    return route.fulfill({ json: { ...task, state: "PUBLISHING", revision: 5, actions: [] } });
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

test("unpublished directory entries are ignored instead of becoming the active company", async ({ page }) => {
  await installOnboardingApiFixture(page);
  const unpublishedNvidia = {
    ...apple,
    company_id: "0001045810",
    security_id: "sec-nvda",
    ticker: "NVDA",
    name: "NVIDIA Corp.",
    publication_id: null,
    quality_status: "PENDING",
    capabilities: [],
  };
  await page.route("**/api/v1/companies?**", (route) => route.fulfill({
    json: { items: [unpublishedNvidia, apple], next_cursor: null },
  }));

  await page.goto("/");

  await expect(page.getByRole("heading", { name: /Apple Inc/ })).toBeVisible();
  await expect(page.getByTestId("company-list").getByText("NVDA", { exact: true })).toHaveCount(0);
  await expect(page.getByText("公司或财务总览加载失败")).toHaveCount(0);
});

test("an older company directory response cannot hide a newly published company", async ({ page }) => {
  await installOnboardingApiFixture(page);
  let requestCount = 0;
  let published = false;
  let staleResponseFinished = false;
  let releaseFirst!: () => void;
  const firstResponseGate = new Promise<void>((resolve) => { releaseFirst = resolve; });
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/company-onboardings/onboarding-ko/review")) published = true;
  });
  await page.route((url) => url.pathname === "/api/v1/companies", async (route) => {
    requestCount += 1;
    if (requestCount === 1) {
      await firstResponseGate;
      await route.fulfill({ json: { items: [apple], next_cursor: null } });
      staleResponseFinished = true;
      return;
    }
    return route.fulfill({ json: {
      items: published
        ? [apple, { ...apple, company_id: "0000021344", security_id: "sec-ko", ticker: "KO", name: "The Coca-Cola Company", exchange: "NYSE", publication_id: "pub-ko" }]
        : [apple],
      next_cursor: null,
    }});
  });

  await page.goto("/");
  await page.getByRole("button", { name: "添加公司" }).click();
  await page.getByLabel("股票代码").fill("KO");
  await page.getByRole("button", { name: "识别公司" }).click();
  await page.getByRole("button", { name: "确认并建档" }).click();
  await page.getByRole("button", { name: "批准并发布" }).click();
  await expect(page.getByTestId("company-list").getByText("KO", { exact: true })).toBeVisible();

  releaseFirst();
  await expect.poll(() => requestCount).toBe(2);
  await expect.poll(() => staleResponseFinished).toBe(true);
  await page.waitForTimeout(250);
  expect(requestCount).toBe(2);
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

test("supported SEC discovery is presented as eligible for onboarding", async ({ page }) => {
  await installOnboardingApiFixture(page);
  await page.goto("/");
  await page.getByRole("button", { name: "添加公司" }).click();
  await page.getByLabel("股票代码").fill("KO");
  await page.getByRole("button", { name: "识别公司" }).click();

  await expect(page.getByText("符合自动建档范围")).toBeVisible();
  await expect(page.getByText("需要人工适配")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "确认并建档" })).toBeEnabled();
});

test("rejected SEC discovery cannot start onboarding", async ({ page }) => {
  await installOnboardingApiFixture(page);
  await page.route("**/api/v1/companies/discover", (route) => route.fulfill({ json: {
    discovery_id: "discovery-fund", ticker: "FUND", identity_hash: "identity-fund", expires_at: "2026-09-12T02:00:00Z",
    candidates: [{ candidate_id: "candidate-fund", company_id: "0000000002", legal_name: "Example Fund", ticker: "FUND", exchange: "NYSE", currency: "USD", instrument_type: "ETF", evidence: [{ source: "SEC" }] }],
    eligibility: { status: "REJECTED", reason_code: "UNSUPPORTED_INSTRUMENT", reason: "不支持基金或 ETF" },
    coverage: { form_counts: {}, earliest_report_date: null, latest_report_date: null }, evidence: [],
  }}));
  await page.goto("/");
  await page.getByRole("button", { name: "添加公司" }).click();
  await page.getByLabel("股票代码").fill("FUND");
  await page.getByRole("button", { name: "识别公司" }).click();

  await expect(page.getByText("不支持基金或 ETF")).toBeVisible();
  await expect(page.getByRole("button", { name: "确认并建档" })).toBeDisabled();
});

test("invalid ticker shows a localized user-facing error without JavaScript noise", async ({ page }) => {
  await installOnboardingApiFixture(page);
  await page.route("**/api/v1/companies/discover", (route) => route.fulfill({
    status: 422,
    json: { detail: { code: "INVALID_TICKER", message: "股票代码只能包含 1—20 位字母、数字、点或连字符" } },
  }));
  await page.goto("/");
  await page.getByRole("button", { name: "添加公司" }).click();
  await page.getByLabel("股票代码").fill("../../etc/passwd");
  await page.getByRole("button", { name: "识别公司" }).click();

  const alert = page.locator(".action-error[role=alert]");
  await expect(alert).toContainText("股票代码只能包含 1—20 位字母、数字、点或连字符");
  await expect(alert).not.toContainText("Error:");
});

test("adaptation-required task pauses polling and explains the required action", async ({ page }) => {
  await installOnboardingApiFixture(page);
  let detailRequests = 0;
  const adaptationTask = {
    onboarding_id: "onboarding-adaptation",
    company_id: "0001045810",
    ticker: "NVDA",
    company_name: "NVIDIA CORP",
    state: "NEEDS_ADAPTATION",
    current_step: "BUILD",
    revision: 3,
    cancel_requested: false,
    input_fingerprint: "input-nvda",
    discovery_id: "discovery-nvda",
    profile_id: null,
    dataset_id: null,
    quality_report_id: null,
    review_id: null,
    publication_id: null,
    error: { code: "PROFILE_REQUIRED", message: "no reviewed issuer profile is installed", retryable: false },
    created_at: "2026-09-18T01:00:00Z",
    updated_at: "2026-09-18T01:03:00Z",
    actions: ["CANCEL", "PROFILE_IMPORT"],
  };
  await page.route("**/api/v1/company-onboardings?**", (route) => route.fulfill({ json: { items: [adaptationTask], next_cursor: null } }));
  await page.route("**/api/v1/company-onboardings/onboarding-adaptation", (route) => {
    detailRequests += 1;
    return route.fulfill({ json: { ...adaptationTask, steps: [], checks: [], blocking_reasons: [] } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "建档中心" }).click();

  await expect(page.locator(".task-state", { hasText: "需要人工适配" })).toBeVisible();
  await expect(page.getByText(/任务已暂停，不会自动继续/)).toBeVisible();
  await expect(page.getByText(/可重试当前步骤/)).toHaveCount(0);
  await page.waitForTimeout(200);
  const settledRequestCount = detailRequests;
  await page.waitForTimeout(2_300);
  expect(detailRequests).toBe(settledRequestCount);
});

test("paused task does not retry-poll when its detail request fails", async ({ page }) => {
  await installOnboardingApiFixture(page);
  let detailRequests = 0;
  const adaptationTask = {
    onboarding_id: "onboarding-paused-error", company_id: "0001045810", ticker: "NVDA", company_name: "NVIDIA CORP",
    state: "NEEDS_ADAPTATION", current_step: "BUILD", revision: 3, cancel_requested: false, input_fingerprint: "input-nvda",
    discovery_id: "discovery-nvda", profile_id: null, dataset_id: null, quality_report_id: null, review_id: null, publication_id: null,
    error: { code: "PROFILE_REQUIRED", message: "profile required", retryable: false }, created_at: "2026-09-18T01:00:00Z",
    updated_at: "2026-09-18T01:03:00Z", actions: ["CANCEL", "PROFILE_IMPORT"],
  };
  await page.route("**/api/v1/company-onboardings?**", (route) => route.fulfill({ json: { items: [adaptationTask], next_cursor: null } }));
  await page.route("**/api/v1/company-onboardings/onboarding-paused-error", (route) => {
    detailRequests += 1;
    return route.fulfill({ status: 503, json: { detail: { message: "temporarily unavailable" } } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "建档中心" }).click();
  await expect(page.locator(".onboarding-detail .action-error")).toContainText("任务加载失败");
  await page.waitForTimeout(200);
  const settledRequestCount = detailRequests;
  await page.waitForTimeout(2_300);
  expect(detailRequests).toBe(settledRequestCount);
});

test("retrying a failed task resumes polling until the new run finishes", async ({ page }) => {
  await installOnboardingApiFixture(page);
  let retried = false;
  let detailRequests = 0;
  const failedTask = {
    onboarding_id: "onboarding-retry", company_id: "0000000003", ticker: "TEST", company_name: "Test Corp.",
    state: "FAILED", current_step: "FETCH", revision: 2, cancel_requested: false, input_fingerprint: "input-test",
    discovery_id: "discovery-test", profile_id: null, dataset_id: null, quality_report_id: null, review_id: null, publication_id: null,
    error: { code: "UPSTREAM", message: "temporary failure", retryable: true }, created_at: "2026-09-18T01:00:00Z",
    updated_at: "2026-09-18T01:03:00Z", actions: ["RETRY", "CANCEL"],
  };
  await page.route("**/api/v1/company-onboardings?**", (route) => route.fulfill({ json: { items: [failedTask], next_cursor: null } }));
  await page.route("**/api/v1/company-onboardings/onboarding-retry/retry", (route) => {
    retried = true;
    return route.fulfill({ json: { ...failedTask, state: "FETCHING", revision: 3, error: null, actions: ["CANCEL"] } });
  });
  await page.route("**/api/v1/company-onboardings/onboarding-retry", (route) => {
    detailRequests += 1;
    return route.fulfill({ json: retried
      ? { ...failedTask, state: "PUBLISHED", revision: 4, error: null, publication_id: "pub-test", actions: [] }
      : { ...failedTask, steps: [], checks: [], blocking_reasons: [] } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "建档中心" }).click();
  await page.getByRole("button", { name: "重试当前步骤" }).click();

  await expect(page.locator(".task-state", { hasText: "已发布" })).toBeVisible();
  expect(detailRequests).toBeGreaterThanOrEqual(2);
});

test("onboarding task list failure can be retried without closing the center", async ({ page }) => {
  await installOnboardingApiFixture(page);
  let attempts = 0;
  await page.route("**/api/v1/company-onboardings?**", (route) => {
    attempts += 1;
    if (attempts === 1) return route.fulfill({ status: 503, json: { detail: { message: "temporarily unavailable" } } });
    return route.fulfill({ json: { items: [], next_cursor: null } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "建档中心" }).click();

  await expect(page.locator(".task-list .action-error[role=alert]")).toContainText("任务列表加载失败");
  await page.getByRole("button", { name: "重试任务列表" }).click();
  await expect(page.getByText("暂无建档任务")).toBeVisible();
  expect(attempts).toBe(2);
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

test("mobile overview does not overflow the viewport", async ({ page }) => {
  await installOnboardingApiFixture(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  await expect(page.getByRole("heading", { name: /Apple Inc/ })).toBeVisible();
  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }));
  expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport);
});

test("valuation explains a company configuration gate", async ({ page }) => {
  await installOnboardingApiFixture(page);
  await page.route("**/api/v1/companies?**", (route) => route.fulfill({ json: { items: [{ ...apple, capabilities: [{ module: "valuation", status: "NEEDS_CONFIGURATION", reason: "需要确认 USD 与稀释股本口径" }] }], next_cursor: null } }));
  await page.goto("/");
  await page.getByRole("button", { name: "估值" }).click();
  await expect(page.getByTestId("valuation-gate")).toContainText("待配置");
  await expect(page.getByTestId("valuation-gate")).toContainText("需要确认 USD 与稀释股本口径");
});
