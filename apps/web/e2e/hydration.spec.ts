import { expect, test } from "@playwright/test";

test("browser extension class injection does not surface a hydration error", async ({
  page,
}) => {
  const hydrationErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" && message.text().includes("A tree hydrated")) {
      hydrationErrors.push(message.text());
    }
  });
  await page.addInitScript(() => {
    const observer = new MutationObserver(() => {
      if (document.documentElement) {
        document.documentElement.classList.add("extension-injected");
        observer.disconnect();
      }
    });
    observer.observe(document, { childList: true, subtree: true });
  });

  await page.goto("/");
  await page.waitForLoadState("domcontentloaded");
  await page.waitForTimeout(500);

  await expect(page.locator("html")).toHaveClass(/extension-injected/);
  expect(hydrationErrors).toEqual([]);
});
