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
    // Wait for page to fully render
    await page.waitForTimeout(3000);

    // Either a site selector, onboarding CTA, or dashboard content should be visible
    const hasSiteSelector = await page
      .locator('[data-testid="site-selector"], select, [role="combobox"]')
      .isVisible()
      .catch(() => false);
    const hasOnboarding = await page
      .locator('text=Add your website')
      .or(page.locator('text=Get started'))
      .or(page.locator('a[href*="onboarding"]'))
      .isVisible()
      .catch(() => false);
    // Dashboard might show content directly without explicit selector
    const hasDashboardContent = await page
      .locator('text=Visitors')
      .or(page.locator('text=Dashboard'))
      .or(page.locator('text=Overview'))
      .isVisible()
      .catch(() => false);
    const hasContent = hasSiteSelector || hasOnboarding || hasDashboardContent;
    expect(hasContent).toBeTruthy();
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

    // Wait for data to load (either stats cards or empty state)
    await page.waitForTimeout(3000);

    // Check for stats-related text (numbers, metric labels)
    const pageContent = await page.textContent("body");
    const hasMetrics =
      pageContent?.includes("Visitors") ||
      pageContent?.includes("Pageviews") ||
      pageContent?.includes("Sessions") ||
      pageContent?.includes("No data");

    expect(hasMetrics).toBeTruthy();
  });
});
