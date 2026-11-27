import { test, expect } from "@playwright/test";

// Accounts dashboard smoke (account-measurement, AC7-render).
// Skip-guarded: needs a signed-in Clerk session (no auth harness yet) and a
// site id. Run with E2E_ACCOUNTS_SITE="<site_id>" once the harness lands.
test.describe("accounts dashboard", () => {
  const siteId = process.env.E2E_ACCOUNTS_SITE;

  test("renders list, empty or flag-off state", async ({ page }) => {
    test.skip(
      !siteId,
      "Requires the Clerk Playwright auth harness + E2E_ACCOUNTS_SITE (known-gap)"
    );
    await page.goto(`/dashboard/accounts?site=${siteId}`);
    await expect(page.getByTestId("accounts-page")).toBeVisible();
    await expect(
      page
        .getByTestId("accounts-table")
        .or(page.getByText("No accounts yet"))
        .or(page.getByText("Accounts view is not enabled"))
    ).toBeVisible();
  });
});
