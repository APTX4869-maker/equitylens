import type { Page } from "@playwright/test";

export const publishedCompanies = [
  { company_id: "0000320193", security_id: "sec-aapl", ticker: "AAPL", name: "Apple Inc.", exchange: "NASDAQ", publication_id: "pub-aapl", quality_status: "VERIFIED", capabilities: [{ module: "valuation", status: "READY", reason: null }] },
  { company_id: "0000789019", security_id: "sec-msft", ticker: "MSFT", name: "Microsoft Corp.", exchange: "NASDAQ", publication_id: "pub-msft", quality_status: "VERIFIED", capabilities: [{ module: "valuation", status: "READY", reason: null }] },
];

export async function stubPublishedCompanyDirectory(page: Page) {
  await page.route("**/api/v1/companies?**", (route) => route.fulfill({ json: { items: publishedCompanies, next_cursor: null } }));
}
