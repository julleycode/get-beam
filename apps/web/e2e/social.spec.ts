import { test, expect } from "@playwright/test";

test.describe("EasyEngage — Social Accounts", () => {
  test("social accounts page loads", async ({ page }) => {
    await page.goto("/dashboard/social-accounts");

    // Auto-wait for page content. Use .first() to avoid strict mode violation
    // when .or() matches multiple elements (e.g. "Social" in nav + heading).
    await expect(page.locator("body")).not.toBeEmpty();
    await expect(
      page
        .locator("text=Social Accounts")
        .or(page.locator("text=Connect a"))
        .or(page.locator("h1"))
        .first()
    ).toBeVisible({ timeout: 15_000 });
  });
});

test.describe("EasyEngage — Drafts", () => {
  test("drafts page loads", async ({ page }) => {
    await page.goto("/dashboard/drafts");

    // Auto-wait for page content. Use .first() to avoid strict mode violation.
    await expect(page.locator("body")).not.toBeEmpty();
    await expect(
      page
        .locator("text=Drafts")
        .or(page.locator("text=No drafts"))
        .or(page.locator("h1"))
        .first()
    ).toBeVisible({ timeout: 15_000 });
  });
});

test.describe("EasyEngage — Feed", () => {
  test("feed page loads", async ({ page }) => {
    await page.goto("/dashboard/feed");

    // Auto-wait for any meaningful content to render
    await expect(page.locator("body")).not.toBeEmpty();
    await page.waitForLoadState("networkidle");
    const pageContent = await page.textContent("body");
    expect(pageContent).toBeTruthy();
    expect(pageContent!.length).toBeGreaterThan(10);
  });
});
