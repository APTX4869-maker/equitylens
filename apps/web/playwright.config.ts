import { defineConfig, devices } from "@playwright/test";

const browserPath = process.env.PLAYWRIGHT_CHROME_PATH;

// E2E coverage for valuation draft identity (V03/U02): out-of-order preview
// responses must never associate an older growth path with a newer WACC/ticker,
// and a failed/unapplied draft must not be saveable.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  timeout: 30_000,
  retries: process.env.CI ? 2 : 0,
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "on-first-retry",
  },
  projects: [{
    name: "chromium",
    use: {
      ...devices["Desktop Chrome"],
      launchOptions: browserPath ? { executablePath: browserPath } : undefined,
    },
  }],
  webServer: {
    command: "pnpm dev",
    url: "http://127.0.0.1:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
