import { test, expect } from "@playwright/test";

test.describe("EasyEngage — Social Accounts", () => {
  test("social accounts page loads", async ({ page }) => {
    await page.goto("/dashboard/social-accounts");
    await page.waitForTimeout(2000);

    const pageContent = await page.textContent("body");
    // Should show social account connection options or empty state
    const hasSocialContent =
      pageContent?.includes("Connect") ||
      pageContent?.includes("Social") ||
      pageContent?.includes("Account") ||
      pageContent?.includes("Twitter") ||
      pageContent?.includes("LinkedIn") ||
      pageContent?.includes("Facebook");

    expect(hasSocialContent).toBeTruthy();
  });
});

test.describe("EasyEngage — Drafts", () => {
  test("drafts page loads", async ({ page }) => {
    await page.goto("/dashboard/drafts");
    await page.waitForTimeout(2000);

    const pageContent = await page.textContent("body");
    // Should show drafts list or empty state
    const hasDraftsContent =
      pageContent?.includes("Draft") ||
      pageContent?.includes("draft") ||
      pageContent?.includes("Generate") ||
      pageContent?.includes("No drafts") ||
      pageContent?.includes("Create");

    expect(hasDraftsContent).toBeTruthy();
  });
});

test.describe("EasyEngage — Feed", () => {
  test("feed page loads", async ({ page }) => {
    await page.goto("/dashboard/feed");
    await page.waitForTimeout(2000);

    const pageContent = await page.textContent("body");
    // Should show feed content or empty state
    expect(pageContent).toBeTruthy();
    expect(pageContent!.length).toBeGreaterThan(10);
  });
});
