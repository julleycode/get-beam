import { test, expect } from "@playwright/test";

// Dashboard-side coverage for the LinkedIn extension connect flow.
// AC6: dashboard only acts on a verifiably-extension-sourced message (nonce).
// AC7: ToS warning is always shown on the extension path too.
// AC9: with no extension present, only the manual form renders (no broken UI).

test.describe("LinkedIn outreach — extension integration (dashboard side)", () => {
  test("AC7 + AC9: ToS warning always shown; no extension → manual form only", async ({
    page,
  }) => {
    await page.goto("/dashboard/social-accounts");

    // ToS warning banner is unconditional (AC7).
    await expect(
      page.getByText(/against LinkedIn's Terms of Service/i)
    ).toBeVisible({ timeout: 15_000 });

    // No extension loaded in this default config → the extension block must NOT
    // render, and the manual cookie-paste form must (AC9).
    await expect(page.getByText("Beam extension detected")).toHaveCount(0);
    await expect(page.getByLabel(/LinkedIn login key/i)).toBeVisible();
  });

  test("AC6: forged postMessage with wrong nonce does not trigger outreach-connect", async ({
    page,
  }) => {
    let outreachConnectCalls = 0;
    await page.route("**/social/accounts/linkedin/outreach-connect", (route) => {
      outreachConnectCalls++;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true }),
      });
    });

    await page.goto("/dashboard/social-accounts");
    await expect(
      page.getByText(/against LinkedIn's Terms of Service/i)
    ).toBeVisible({ timeout: 15_000 });

    // Simulate a co-resident copy-cat extension: correct origin + source string,
    // but a guessed/wrong nonce. The dashboard must ignore it (D10/OI-3).
    await page.evaluate(() => {
      window.postMessage(
        {
          source: "beam-extension",
          nonce: "attacker-guessed-nonce",
          ok: true,
          cookie: "attacker-value",
          userAgent: "attacker-ua",
        },
        window.location.origin
      );
    });
    await page.waitForTimeout(500);

    expect(outreachConnectCalls).toBe(0);
  });

  // Onboarding-plan D8 regression: the extension detection / nonce logic moved
  // into the shared useLinkedInExtensionStatus() hook. The two tests above are
  // the unmodified non-regression proof; this one asserts the new guided-setup
  // launcher is present alongside them.
  test("D8: guided wizard launcher is present on the card", async ({ page }) => {
    await page.goto("/dashboard/social-accounts");
    await expect(
      page.getByText(/against LinkedIn's Terms of Service/i)
    ).toBeVisible({ timeout: 15_000 });

    await expect(
      page.getByRole("button", { name: /^(Connect|Reconnect) LinkedIn$/ }).first()
    ).toBeVisible();
  });
});
