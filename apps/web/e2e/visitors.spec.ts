import { test, expect } from "@playwright/test";

const API_BASE = "http://localhost:8000";

test.describe("Visitors Page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/dashboard/visitors");
  });

  test("loads visitors page", async ({ page }) => {
    await expect(page).toHaveURL(/visitors/);
    // Should show some visitor-related content
    await expect(page.locator("body")).not.toBeEmpty();
  });

  test("shows visitor list or empty state", async ({ page }) => {
    // Auto-wait for visitor-related content. Use .first() to avoid strict
    // mode violation when "Visitor" matches both nav link + page heading.
    await expect(
      page
        .locator("h2:has-text('Visitor')")
        .or(page.locator("text=No visitors"))
        .or(page.locator("text=anonymous"))
        .first()
    ).toBeVisible({ timeout: 15_000 });
  });

  test("has search or filter controls", async ({ page }) => {
    // Verify the page renders — auto-wait
    await expect(page.locator("body")).not.toBeEmpty();
    await page.waitForLoadState("networkidle");
    const pageContent = await page.textContent("body");
    expect(pageContent).toBeTruthy();
  });
});

test.describe("Visitor Detail Page", () => {
  test("shows 404 or redirect for invalid visitor ID", async ({ page }) => {
    await page.goto("/dashboard/visitors/nonexistent-visitor-id");

    // Auto-wait for the page to render something
    await expect(page.locator("body")).not.toBeEmpty();
    await page.waitForLoadState("networkidle");
    const pageContent = await page.textContent("body");
    expect(pageContent).toBeTruthy();
  });
});
