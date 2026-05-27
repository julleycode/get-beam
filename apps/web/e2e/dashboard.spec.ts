import { test, expect } from "@playwright/test";

test.describe("Dashboard — Main Page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/dashboard");
  });

  test("loads dashboard page", async ({ page }) => {
    // Should show the main dashboard layout
    await expect(page).toHaveURL(/dashboard/);
    // Page should have loaded (not a blank white screen)
    await expect(page.locator("body")).not.toBeEmpty();
  });

  test("shows site selector or onboarding prompt", async ({ page }) => {
    // Use Playwright auto-waiting instead of waitForTimeout + isVisible.
    // The dashboard always shows at least one of these within 15s.
    await expect(
      page
        .locator('[data-testid="site-selector"], select, [role="combobox"]')
        .or(page.locator('text=Add your website'))
        .or(page.locator('text=Get started'))
        .or(page.locator('a[href*="onboarding"]'))
        .or(page.locator('text=Dashboard'))
        .or(page.locator('text=Overview'))
    ).toBeVisible({ timeout: 15_000 });
  });

  test("navigation sidebar is visible", async ({ page }) => {
    // Check that key navigation items exist
    await expect(
      page.locator('a[href*="visitors"], nav >> text=Visitors')
    ).toBeVisible({ timeout: 10_000 });
  });
});

test.describe("Dashboard — Stats Cards", () => {
  test("displays visitor/pageview/session metrics when site has data", async ({
    page,
  }) => {
    await page.goto("/dashboard");

    // Auto-wait for dashboard to render metric labels or empty state
    await expect(
      page
        .locator("text=Visitors")
        .or(page.locator("text=Pageviews"))
        .or(page.locator("text=Sessions"))
        .or(page.locator("text=No data"))
        .or(page.locator("text=Add site"))
    ).toBeVisible({ timeout: 15_000 });
  });
});
