import { test, expect } from "@playwright/test";

// Content Ideas dashboard smoke (ad-insights-seo-aeo, C2 / G8).
// Skip-guarded: needs a signed-in Clerk session (no auth harness yet) and a
// site id. Run with E2E_CONTENT_OPPS_SITE="<site_id>" once the harness lands.
test.describe("content opportunities dashboard", () => {
  const siteId = process.env.E2E_CONTENT_OPPS_SITE;

  test("renders top ads + suggestions, not-enough-data, or flag-off state", async ({ page }) => {
    test.skip(
      !siteId,
      "Requires the Clerk Playwright auth harness + E2E_CONTENT_OPPS_SITE (known-gap)"
    );
    await page.goto(`/dashboard/content-opportunities?site=${siteId}`);
    await expect(page.getByTestId("content-opportunities-page")).toBeVisible();
    await expect(page.getByTestId("suggestions-only-note")).toContainText("nothing is published");
    await expect(
      page
        .getByTestId("top-ads-table")
        .or(page.getByText("Not enough ad data yet"))
        .or(page.getByText("Content ideas are not enabled"))
    ).toBeVisible();
  });

  test("Copy and Dismiss controls are present on each suggestion", async ({ page }) => {
    test.skip(
      !siteId,
      "Requires the Clerk Playwright auth harness + E2E_CONTENT_OPPS_SITE (known-gap)"
    );
    await page.goto(`/dashboard/content-opportunities?site=${siteId}`);
    const cards = page.getByTestId("opportunity-card");
    test.skip((await cards.count()) === 0, "No suggestions for this site yet");
    await expect(cards.first().getByRole("button", { name: "Copy" })).toBeVisible();
    await expect(cards.first().getByRole("button", { name: "Dismiss" })).toBeVisible();
  });
});
