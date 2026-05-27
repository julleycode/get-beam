import { test, expect } from "@playwright/test";

test.describe("EasyEngage — Social Accounts", () => {
  test("social accounts page loads", async ({ page }) => {
    await page.goto("/dashboard/social-accounts");

    // Auto-wait for page content — no waitForTimeout
    await expect(page.locator("body")).not.toBeEmpty();
    await expect(
      page
        .locator("text=Connect")
        .or(page.locator("text=Social"))
        .or(page.locator("text=Account"))
    ).toBeVisible({ timeout: 15_000 });
  });
});

test.describe("EasyEngage — Drafts", () => {
  test("drafts page loads", async ({ page }) => {
    await page.goto("/dashboard/drafts");

    // Auto-wait for page content
    await expect(page.locator("body")).not.toBeEmpty();
    await expect(
      page
        .locator("text=Draft")
        .or(page.locator("text=Generate"))
        .or(page.locator("text=Create"))
        .or(page.locator("text=No drafts"))
    ).toBeVisible({ timeout: 15_000 });
  });
});

test.describe("EasyEngage — Feed", () => {
  test("feed page loads", async ({ page }) => {
    await page.goto("/dashboard/feed");

    // Auto-wait for any meaningful content to render
    await expect(page.locator("body")).not.toBeEmpty();
    // Verify page has rendered something beyond just the shell
    await page.waitForLoadState("networkidle");
    const pageContent = await page.textContent("body");
    expect(pageContent).toBeTruthy();
    expect(pageContent!.length).toBeGreaterThan(10);
  });
});
