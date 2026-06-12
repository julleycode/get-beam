import { test, expect } from "@playwright/test";

test.describe("Segments Page", () => {
  test("shows segment cards or the unlock-progress empty state", async ({ page }) => {
    await page.goto("/dashboard/segments");

    await expect(page.locator("h2:has-text('Segments')").first()).toBeVisible({
      timeout: 15_000,
    });

    // Either real segment cards render ("Channels:" label) or the empty
    // state explains the 10-enriched-visitors unlock with a progress bar.
    await expect(
      page
        .locator("text=No segments yet")
        .or(page.locator("text=Channels:"))
        .first()
    ).toBeVisible({ timeout: 15_000 });
  });

  test("empty state shows progress toward 10 enriched visitors", async ({ page }) => {
    await page.goto("/dashboard/segments");

    const emptyState = page.locator("text=No segments yet");
    const hasEmptyState = await emptyState
      .first()
      .waitFor({ state: "visible", timeout: 15_000 })
      .then(() => true)
      .catch(() => false);

    if (hasEmptyState) {
      await expect(page.locator("text=of 10").first()).toBeVisible({ timeout: 15_000 });
    } else {
      // Site already has segments — progress bar intentionally absent.
      await expect(page.locator("text=Channels:").first()).toBeVisible({ timeout: 15_000 });
    }
  });
});
