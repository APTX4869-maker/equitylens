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
  await page.route("**/api/v1/companies/KO?**", (route) => route.fulfill({ json: { ...apple, company_id: "0000021344", security_id: "sec-ko", ticker: "KO", name: "The Coca-Cola Company", exchange: "NYSE", publication_id: "pub-ko", cik: "0000021344", source_freshness: { COMPANYFACTS_SNAPSHOT: { fetched_at: "2026-09-12T00:00:00Z", sha256: "fixture" } } } }));
  await page.route("**/api/v1/companies/KO/overview?**", (route) => route.fulfill({ json: { ticker: "KO", latest_period: { fiscal_year: 2026, fiscal_quarter: 2, period_end: "2026-06-30" }, kpis: {}, trend: {}, provenance_available: true } }));
  await page.route("**/api/v1/companies/KO/market/quote?**", (route) => route.fulfill({ json: { status: "UNAVAILABLE", configured: false, synced: false, reason: "test" } }));
  await page.route("**/api/v1/companies/KO/freshness?**", (route) => route.fulfill({ json: { modules: [{ key: "sec_financials", label: "SEC 财务事实", as_of: "2026-08-01", detail: "最近披露 10-Q", status: "ok", days_ago: 42 }], stale_modules: [], hint: null } }));
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
  const publishedCompany = page.getByTestId("company-list").getByText("KO", { exact: true });
  await expect(publishedCompany).toBeVisible();
  await page.getByRole("button", { name: "关闭建档中心" }).click();
  await publishedCompany.click();
  await expect(page.getByRole("heading", { name: /The Coca-Cola Company/ })).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("company-list").getByText("KO", { exact: true })).toBeVisible();
});

test("global attention entry restores the last task and disappears when work is terminal", async ({ page }) => {
  await installOnboardingApiFixture(page);
  let terminal = false;
  const base = {
    company_id: "0001045810", state: "NEEDS_ADAPTATION", current_step: "BUILD", revision: 3,
    cancel_requested: false, input_fingerprint: "attention", profile_id: null, dataset_id: null,
    quality_report_id: null, review_id: null, publication_id: null, error: null,
    created_at: "2026-09-19T09:00:00Z", updated_at: "2026-09-19T10:00:00Z",
    actions: ["CANCEL", "PROFILE_IMPORT"],
  };
  const first = { ...base, onboarding_id: "attention-a", ticker: "AAA", company_name: "Alpha Corp" };
  const second = { ...base, onboarding_id: "attention-b", ticker: "BBB", company_name: "Beta Corp" };
  await page.route("**/api/v1/company-onboardings?**", (route) => route.fulfill({ json: {
    items: terminal ? [] : [first, second], next_cursor: null, attention_count: terminal ? 0 : 7,
  } }));
  await page.route("**/api/v1/company-onboardings/attention-a", (route) => route.fulfill({ json: { ...first, steps: [], checks: [] } }));
  await page.route("**/api/v1/company-onboardings/attention-b", (route) => route.fulfill({ json: { ...second, steps: [], checks: [] } }));
  await page.addInitScript(() => localStorage.setItem("equitylens:last-onboarding-task", "attention-b"));

  await page.goto("/");
  const indicator = page.getByRole("button", { name: "有 7 个建档任务需要关注" });
  await expect(indicator).toBeVisible();
  await indicator.click();
  await expect(page.getByRole("heading", { name: "Beta Corp" })).toBeVisible();
  await page.getByRole("button", { name: "关闭建档中心" }).click();

  await page.reload();
  await page.getByRole("button", { name: "有 7 个建档任务需要关注" }).click();
  await expect(page.getByRole("heading", { name: "Beta Corp" })).toBeVisible();
  await page.getByRole("button", { name: "关闭建档中心" }).click();
  terminal = true;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(indicator).toBeHidden();
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

test("adaptation workbench shows five-stage progress, evidence, and resumes after YAML upload", async ({ page }) => {
  await installOnboardingApiFixture(page);
  const stages = ["IDENTITY", "FETCH", "ADAPTATION", "BUILD_VALIDATE", "REVIEW_PUBLISH"];
  const progress = (completed: number, current: string, activity: string) => ({
    completed, total: 5, percent: completed * 20, current_stage: current,
    activity, actor: activity === "WAITING_FOR_MAINTAINER" ? "MAINTAINER" : "SYSTEM",
    updated_at: "2026-09-19T10:00:00Z", stalled: false, fingerprint: `${completed}-${activity}`,
    stages: stages.map((id, index) => ({
      id, label: ["识别公司", "固定申报数据", "适配公司配置", "构建并校验", "审核并发布"][index],
      status: index < completed ? "COMPLETED" : id === current ? "CURRENT" : "UPCOMING",
      activity: index < completed ? "COMPLETED" : id === current ? activity : null,
      started_at: null, completed_at: null,
    })),
  });
  let task = {
    onboarding_id: "onboarding-workbench", company_id: "0001045810", ticker: "NVDA", company_name: "NVIDIA CORP",
    state: "NEEDS_ADAPTATION", current_step: "BUILD", revision: 3, cancel_requested: false,
    input_fingerprint: "input-nvda", fetch_bundle_id: "bundle-nvda", profile_candidate_id: "candidate-nvda" as string | null,
    profile_id: null as string | null, dataset_id: null, quality_report_id: null, review_id: null, publication_id: null,
    error: { code: "ADAPTATION_REQUIRED", message: "需要审核发行人配置", remediation: "PROFILE_IMPORT" },
    created_at: "2026-09-19T09:00:00Z", updated_at: "2026-09-19T10:00:00Z",
    actions: ["CANCEL", "PROFILE_IMPORT"], progress: progress(2, "ADAPTATION", "WAITING_FOR_MAINTAINER"),
  };
  let uploadCalls = 0;
  let uploadKey = "";
  await page.route("**/api/v1/company-onboardings?**", (route) => route.fulfill({ json: { items: [task], next_cursor: null, attention_count: 1 } }));
  await page.route("**/api/v1/company-onboardings/onboarding-workbench/profile-candidate", (route) => route.fulfill({ json: {
    profile_candidate_id: "candidate-nvda", onboarding_id: task.onboarding_id, task_revision: 3,
    content_sha256: "a".repeat(64), snapshot_manifest: [{ document_id: "filing:nvda", document_type: "FILING_DOCUMENT", form_type: "10-K", raw_locator: "sec/nvda/primary.html", content_sha256: "b".repeat(64) }],
    profile: { schema_version: 2, company_id: task.company_id, metrics: { REVENUE: { concepts: ["us-gaap:Revenues"], evidence: ["ev-revenue"] } }, evidence: [{ evidence_id: "ev-revenue", source_document_id: "filing:nvda", content_sha256: "b".repeat(64), locator: "/html/body/fact" }] },
    unresolved_fields: [{ path: "segments.parser", reason: "需要确认分部披露", action: "选择解析器或不适用" }],
    review_status: "NEEDS_ADAPTATION", created_at: "2026-09-19T10:00:00Z", current: true,
  }}));
  await page.route("**/api/v1/company-onboardings/onboarding-workbench/profile-yaml", async (route) => {
    uploadCalls += 1;
    const key = route.request().headers()["idempotency-key"];
    expect(key).toBeTruthy();
    if (uploadCalls === 1) {
      uploadKey = key;
      return route.fulfill({ status: 422, json: { detail: {
        code: "INVALID_PROFILE_YAML", message: "审核版配置有 1 个字段需要修正", remediation: "PROFILE_IMPORT",
        field_errors: [{ path: "segments.parser", message: "Field required" }],
      } } });
    }
    expect(key).toBe(uploadKey);
    task = { ...task, state: "BUILDING", revision: 4, profile_candidate_id: null, profile_id: "profile-nvda", actions: ["CANCEL"], progress: progress(3, "BUILD_VALIDATE", "RUNNING") };
    return route.fulfill({ json: task });
  });
  await page.route("**/api/v1/company-onboardings/onboarding-workbench", (route) => route.fulfill({ json: { ...task, steps: [], checks: [], blocking_reasons: [] } }));

  await page.goto("/");
  await page.getByRole("button", { name: "建档中心" }).click();
  await expect(page.getByRole("progressbar", { name: "建档总进度" })).toHaveAttribute("aria-valuenow", "40");
  await expect(page.getByText("任务已暂停，等待维护者操作")).toBeVisible();
  await expect(page.getByLabel("适配公司配置：进行中")).toBeVisible();
  await page.getByRole("button", { name: "查看候选配置" }).click();
  await expect(page.getByText("segments.parser")).toBeVisible();
  await page.getByText("ev-revenue").click();
  await expect(page.getByText("/html/body/fact")).toBeVisible();

  const picker = page.getByLabel("选择审核版 YAML");
  await picker.setInputFiles({ name: "empty.yaml", mimeType: "application/yaml", buffer: Buffer.alloc(0) });
  await expect(page.locator(".profile-workbench .action-error")).toContainText("YAML 文件为空");
  await picker.setInputFiles({ name: "oversized.yaml", mimeType: "application/yaml", buffer: Buffer.alloc(512 * 1024 + 1) });
  await expect(page.locator(".profile-workbench .action-error")).toContainText("超过 512 KiB");
  await picker.setInputFiles({
    name: "nvda-profile-v1.yaml", mimeType: "application/yaml",
    buffer: Buffer.from("schema_version: 2\ncompany_id: '0001045810'\nversion: 1\n"),
  });
  await expect(page.getByText(/nvda-profile-v1.yaml/)).toBeVisible();
  await page.getByRole("button", { name: "导入并继续" }).click();
  await expect(page.getByText("segments.parser").last()).toBeVisible();
  await expect(page.getByText("Field required")).toBeVisible();
  await page.getByRole("button", { name: "导入并继续" }).click();
  await expect(page.getByRole("progressbar", { name: "建档总进度" })).toHaveAttribute("aria-valuenow", "60");
  await expect(page.getByText("构建并校验")).toBeVisible();
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
    if (new URL(route.request().url()).searchParams.get("attention_only") === "true") {
      return route.fulfill({ json: { items: [], next_cursor: null, attention_count: 0 } });
    }
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
