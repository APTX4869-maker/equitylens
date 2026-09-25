import { defineConfig, devices } from "@playwright/test";

const browserPath = process.env.PLAYWRIGHT_CHROME_PATH;
const testPort = process.env.PLAYWRIGHT_PORT ?? "3000";

// E2E coverage for valuation draft identity (V03/U02): out-of-order preview
// responses must never associate an older growth path with a newer WACC/ticker,
// and a failed/unapplied draft must not be saveable.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  timeout: 30_000,
  retries: process.env.CI ? 2 : 0,
  use: {
    baseURL: `http://127.0.0.1:${testPort}`,
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
    command: `pnpm dev --port ${testPort}`,
    url: `http://127.0.0.1:${testPort}`,
    reuseExistingServer: !process.env.CI && testPort === "3000",
    timeout: 120_000,
  },
});
