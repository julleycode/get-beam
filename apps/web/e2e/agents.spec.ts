import { test, expect } from "@playwright/test";

test.describe("Agents Page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/dashboard/agents");
  });

  test("loads agents page", async ({ page }) => {
    await expect(page).toHaveURL(/agents/);
    await expect(page.locator("body")).not.toBeEmpty();
  });

  test("renders an Agents heading", async ({ page }) => {
    // Auto-wait. .first() avoids a strict-mode violation when "Agents" matches
    // both the nav link and the page heading.
    await expect(
      page
        .locator("h1:has-text('Agents')")
        .or(page.locator("text=No agent visits"))
        .or(page.locator("text=Select a site"))
        .first()
    ).toBeVisible({ timeout: 15_000 });
  });
});

test.describe("Tab separation (Agents vs Visitors)", () => {
  test("visitors page still renders its own heading, unaffected by Agents tab", async ({
    page,
  }) => {
    await page.goto("/dashboard/visitors");
    await expect(page).toHaveURL(/visitors/);
    await expect(
      page
        .locator("h1:has-text('Visitor')")
        .or(page.locator("text=No visitors"))
        .or(page.locator("text=anonymous"))
        .first()
    ).toBeVisible({ timeout: 15_000 });
  });
});

test.describe("Agent Detail Page", () => {
  test("renders something for an invalid agent ID (no crash)", async ({ page }) => {
    await page.goto("/dashboard/agents/not-a-uuid");
    await expect(page.locator("body")).not.toBeEmpty();
    await page.waitForLoadState("networkidle");
    const pageContent = await page.textContent("body");
    expect(pageContent).toBeTruthy();
  });
});
