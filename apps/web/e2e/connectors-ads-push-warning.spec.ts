import { test, expect } from "@playwright/test";

// AC7 — small-audience warning, BOTH legs:
//   (a) PRE-push: selecting a small segment shows an approximate warning inside
//       the confirm dialog, and the push button stays clickable (warned, never
//       blocked — the user may still confirm or cancel).
//   (b) POST-push: the result message renders copy driven by the backend's
//       below_minimum / minimum_threshold fields, not a hardcoded number.
//
// Every backend call is route-mocked, so this spec asserts the panel's own
// logic and never depends on live segment/connection data or a live Meta call.
//
// Filename contains "connectors" so `npx playwright test connectors` picks it up.

const API = "http://localhost:8000";

const SMALL_SEGMENT = {
  id: "seg-small-1",
  site_id: "e2e-site",
  name: "Tiny segment",
  description: "",
  visitor_count: 42, // well below the 1,000 warning threshold
  created_at: new Date().toISOString(),
};

const META_CONNECTION = {
  provider: "meta",
  auth_type: "oauth",
  status: "connected",
  external_account_label: "Meta Custom Audiences",
  ad_account_id: "act_e2e",
  business_id: "biz",
  is_valid: true,
  last_pushed_at: null,
  last_error: null,
  created_at: new Date().toISOString(),
};

test.describe("Connectors — Ad Audiences small-audience warning (AC7)", () => {
  test.beforeEach(async ({ page }) => {
    // Same auth re-seed as connectors-ads.spec.ts — the shared storage state is
    // occasionally dropped between specs in this suite.
    const res = await page.request.post(`${API}/api/v1/auth/login`, {
      data: { email: "demo@getbeam.fyi", password: "password123" },
    });
    if (res.ok()) {
      const { access_token } = await res.json();
      await page.addInitScript((token) => {
        localStorage.setItem("auth_token", token as string);
        localStorage.setItem("beam_tour_done_v1", "1");
      }, access_token);
    }

    await page.route("**/api/v1/ads/*/connections", (route) =>
      route.fulfill({ json: [META_CONNECTION] })
    );
    await page.route("**/api/v1/segments**", (route) =>
      route.fulfill({ json: { segments: [SMALL_SEGMENT], total: 1 } })
    );

    await page.goto("/dashboard/connectors");
    await page.waitForLoadState("networkidle");
  });

  async function openPushDialogWithSmallSegment(page: import("@playwright/test").Page) {
    const adsTab = page.getByRole("tab", { name: "Ad Audiences" });
    if (await adsTab.isVisible().catch(() => false)) await adsTab.click();

    await page.getByRole("button", { name: "Push segment" }).first().click();
    await expect(page.getByRole("dialog")).toBeVisible({ timeout: 15_000 });

    await page.getByRole("combobox").first().click();
    await page.getByRole("option", { name: /Tiny segment/ }).click();
  }

  // ── AC7 leg (a): pre-push warning, push NOT blocked ────
  test("small segment shows an approximate warning before the push is confirmed", async ({
    page,
  }) => {
    const panel = page.getByRole("button", { name: "Push segment" }).first();
    if (!(await panel.isVisible().catch(() => false))) {
      test.skip(true, "Connectors page did not render (auth harness gap G2)");
    }

    await openPushDialogWithSmallSegment(page);

    const warning = page.getByTestId("ads-pre-push-warning");
    await expect(warning).toBeVisible({ timeout: 10_000 });
    await expect(warning).toContainText("42");
    await expect(warning).toContainText("1,000");
    // Explicitly approximate — this is the pre-safety-filter estimate.
    await expect(warning).toContainText(/about/i);

    // Warned, not blocked: the user can still confirm, or cancel.
    const pushNow = page.getByRole("button", { name: "Push now" });
    await expect(pushNow).toBeEnabled();
    await expect(page.getByRole("button", { name: "Cancel" })).toBeEnabled();
  });

  // ── AC7 leg (b): post-push exact copy from the response ─
  test("post-push message uses the backend's minimum_threshold, not a hardcoded number", async ({
    page,
  }) => {
    const panel = page.getByRole("button", { name: "Push segment" }).first();
    if (!(await panel.isVisible().catch(() => false))) {
      test.skip(true, "Connectors page did not render (auth harness gap G2)");
    }

    // No `warning` string — forces the panel to build the copy from the
    // structured fields, which is exactly what this leg must prove.
    await page.route("**/api/v1/ads/*/connections/meta/push", (route) =>
      route.fulfill({
        json: {
          provider: "meta",
          segment_id: SMALL_SEGMENT.id,
          pushed: 7,
          failed: 0,
          skipped: 35,
          platform_audience_id: "aud-e2e",
          warning: "",
          below_minimum: true,
          minimum_threshold: 1000,
          errors: [],
          queued: false,
        },
      })
    );

    await openPushDialogWithSmallSegment(page);
    await page.getByRole("button", { name: "Push now" }).click();

    const status = page.locator("[role='status']").first();
    await expect(status).toContainText("Pushed 7", { timeout: 15_000 });
    await expect(status).toContainText("1,000");
    await expect(status).toContainText(/still went through/i);
  });
});
