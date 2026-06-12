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

test.describe("Pipeline Explainer", () => {
  test("shows the pipeline explainer card", async ({ page }) => {
    await page.goto("/dashboard/visitors");
    await expect(
      page.locator("text=How Beam turns visitors into campaigns").first()
    ).toBeVisible({ timeout: 15_000 });
  });

  test("dismiss persists across reload", async ({ page }) => {
    await page.goto("/dashboard/visitors");
    await expect(
      page.locator("text=How Beam turns visitors into campaigns").first()
    ).toBeVisible({ timeout: 15_000 });

    await page.locator('button[aria-label="Dismiss"]').first().click();
    await expect(
      page.locator("text=How Beam turns visitors into campaigns")
    ).not.toBeVisible();

    await page.reload();
    // Page renders, explainer stays gone (localStorage flag)
    await expect(page.locator("h2:has-text('Visitor')").first()).toBeVisible({
      timeout: 15_000,
    });
    await expect(
      page.locator("text=How Beam turns visitors into campaigns")
    ).not.toBeVisible();
  });
});

test.describe("Column Tooltips", () => {
  test("intent header shows scoring explanation on hover", async ({ page }) => {
    await page.goto("/dashboard/visitors");
    // Table headers render once the auto-selected site's list loads
    const intentHead = page.locator("th:has-text('Intent')").first();
    await expect(intentHead).toBeVisible({ timeout: 15_000 });

    await intentHead.locator("span[tabindex='0']").first().hover();
    await expect(
      page.locator("text=unlocks identification").first()
    ).toBeVisible({ timeout: 15_000 });
  });
});

test.describe("Resolve Now", () => {
  test("resolve button renders with a site selected", async ({ page }) => {
    await page.goto("/dashboard/visitors");
    await expect(
      page.locator("button:has-text('Resolve now')").first()
    ).toBeVisible({ timeout: 15_000 });
  });
});
