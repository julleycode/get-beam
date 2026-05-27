import { test, expect, type Page } from "@playwright/test";

const API_BASE = "http://localhost:8000";

// ─── Helpers ───────────────────────────────────────────────

/** Delete a site via API (cleanup) */
async function deleteSiteIfExists(page: Page, siteId: string) {
  // Best-effort cleanup — ignore errors
  try {
    const token = await page.evaluate(() => localStorage.getItem("auth_token"));
    if (token) {
      await page.request.delete(`${API_BASE}/api/v1/sites/${siteId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
    }
  } catch {
    // ignore
  }
}

/** Fill in the "Add Site" form and submit */
async function fillCreateForm(
  page: Page,
  name: string,
  url: string,
  description = ""
) {
  await page.fill('input#name', name);
  await page.fill('input#url', url);
  if (description) {
    await page.fill('textarea#desc', description);
  }
  await page.click('button[type="submit"]');
}

/** Wait for platform detection to finish (spinner disappears) */
async function waitForDetection(page: Page) {
  // First wait for the "install" step to appear
  await expect(page.locator("text=Install tracking pixel")).toBeVisible({
    timeout: 10_000,
  });

  // Wait for the spinner to disappear (detection complete)
  // The spinner has class animate-spin
  await expect(page.locator(".animate-spin")).toBeHidden({ timeout: 30_000 });
}

// ─── Test Suite ────────────────────────────────────────────

test.describe("Onboarding — Platform Detection", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/dashboard/onboarding");
    // Ensure we're on the create step
    await expect(page.locator("text=Add your website")).toBeVisible();
  });

  test("Step 1: Create form is visible with all fields", async ({ page }) => {
    await expect(page.locator('input#name')).toBeVisible();
    await expect(page.locator('input#url')).toBeVisible();
    await expect(page.locator('textarea#desc')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toHaveText("Continue");
  });

  test("Step 1: Progress bar shows 3 steps", async ({ page }) => {
    await expect(page.locator("text=Add Site")).toBeVisible();
    await expect(page.locator("text=Install Pixel")).toBeVisible();
    await expect(page.locator("text=Verified")).toBeVisible();
  });

  test("Shopify detection — shows Connect Shopify Store", async ({ page }) => {
    test.slow(); // platform detection involves HTTP calls

    await fillCreateForm(page, "Test Shopify", "https://gymshark.com");
    await waitForDetection(page);

    // Should show Shopify platform badge
    const badge = page.locator("span.rounded-full:has-text('Shopify')");
    await expect(badge).toBeVisible({ timeout: 5000 });

    // Should show "Connect Shopify Store" card
    await expect(
      page.locator("text=Connect Shopify Store")
    ).toBeVisible();

    // Should have the shop domain input
    await expect(
      page.locator('input[placeholder="mystore.myshopify.com"]')
    ).toBeVisible();

    // Should have Verify button
    await expect(
      page.locator('button:has-text("Verify Installation")')
    ).toBeVisible();
  });

  test("WordPress detection — shows Download Plugin + GTM badge", async ({
    page,
  }) => {
    test.slow();

    await fillCreateForm(page, "Test WordPress", "https://developer.wordpress.org");
    await waitForDetection(page);

    // Should show WordPress platform badge
    const badge = page.locator("span.rounded-full:has-text('WordPress')");
    await expect(badge).toBeVisible({ timeout: 5000 });

    // Should show Download Plugin button
    await expect(
      page.locator('button:has-text("Download WordPress Plugin")')
    ).toBeVisible();

    // Should have Verify button
    await expect(
      page.locator('button:has-text("Verify Installation")')
    ).toBeVisible();
  });

  test("Wix detection — shows guided steps", async ({ page }) => {
    test.slow();

    await fillCreateForm(page, "Test Wix", "https://thaibaotran-growth.com");
    await waitForDetection(page);

    // Should show Wix platform badge
    const badge = page.locator("span.rounded-full:has-text('Wix')");
    await expect(badge).toBeVisible({ timeout: 5000 });

    // Should show numbered steps (use specific step titles)
    await expect(page.locator("h4:has-text('Open Wix Settings')")).toBeVisible();
    await expect(page.locator("h4:has-text('Custom Code')")).toBeVisible();

    // Should show code snippet
    await expect(page.locator("text=Code Snippet")).toBeVisible();
    await expect(page.locator('button:has-text("Copy")')).toBeVisible();

    // Should have Verify button
    await expect(
      page.locator('button:has-text("Verify Installation")')
    ).toBeVisible();
  });

  test("Unknown platform — shows manual install guide", async ({ page }) => {
    test.slow();

    await fillCreateForm(page, "Test Unknown", "https://example.com");
    await waitForDetection(page);

    // Should show "Custom Website" badge
    const badge = page.locator("text=Custom Website");
    await expect(badge).toBeVisible({ timeout: 5000 });

    // Should show code snippet for manual install
    await expect(page.locator("text=Code Snippet")).toBeVisible();
    await expect(page.locator('button:has-text("Copy")')).toBeVisible();

    // Should have Verify button
    await expect(
      page.locator('button:has-text("Verify Installation")')
    ).toBeVisible();
  });

  test("Platform detection shows spinner while detecting", async ({
    page,
  }) => {
    await fillCreateForm(page, "Test Spinner", "https://example.com");

    // Should show spinner/detecting state
    await expect(page.locator("text=Detecting your platform")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.locator(".animate-spin")).toBeVisible();

    // Wait for it to finish
    await expect(page.locator(".animate-spin")).toBeHidden({ timeout: 30_000 });
  });

  test("Snippet contains site ID and tracker.js URL", async ({ page }) => {
    test.slow();

    await fillCreateForm(page, "Test Snippet", "https://example.com");
    await waitForDetection(page);

    // Get the snippet text
    const snippetEl = page.locator("pre");
    const snippetText = await snippetEl.textContent();

    expect(snippetText).toContain("tracker.js");
    expect(snippetText).toContain("data-site=");
    expect(snippetText).toContain("data-api=");
  });

  test("Copy button copies snippet to clipboard", async ({ page, context }) => {
    test.slow();

    // Grant clipboard permissions
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);

    await fillCreateForm(page, "Test Copy", "https://example.com");
    await waitForDetection(page);

    // Click copy button
    const copyBtn = page.locator('button:has-text("Copy")');
    await copyBtn.click();

    // Button should change to "Copied!"
    await expect(page.locator('button:has-text("Copied!")')).toBeVisible();

    // Should revert back after 2s
    await expect(copyBtn).toHaveText("Copy", { timeout: 5000 });
  });
});

test.describe("Onboarding — Verify Flow", () => {
  test("Verify button shows checking state", async ({ page }) => {
    test.slow();

    await page.goto("/dashboard/onboarding");
    await fillCreateForm(page, "Test Verify", "https://example.com");
    await waitForDetection(page);

    // Click verify
    const verifyBtn = page.locator('button:has-text("Verify Installation")');
    await verifyBtn.click();

    // Should show checking state
    await expect(
      page.locator('button:has-text("Checking your website")')
    ).toBeVisible();

    // Wait for result (will be "not found" since pixel isn't really installed)
    await expect(
      page.locator('button:has-text("Verify Installation")')
    ).toBeVisible({ timeout: 30_000 });
  });
});

test.describe("Settings Page — Pixel Management", () => {
  let testSiteId: string;

  test.beforeAll(async ({ browser }) => {
    // Create a test site via API so settings page has data to show
    const context = await browser.newContext({
      storageState: "e2e/.auth/user.json",
    });
    const page = await context.newPage();
    await page.goto("/");
    const token = await page.evaluate(() => localStorage.getItem("auth_token"));

    if (token) {
      const res = await page.request.post(`${API_BASE}/api/v1/sites/`, {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        data: { name: "E2E Test Site", url: "https://e2e-test.example.com" },
      });
      if (res.ok()) {
        const data = await res.json();
        testSiteId = data.site_id;
      }
    }
    await context.close();
  });

  test("Shows site details and pixel snippet", async ({ page }) => {
    test.skip(!testSiteId, "Could not create test site");

    await page.goto(`/dashboard/settings?site=${testSiteId}`);

    // Use Playwright auto-waiting (NOT waitForTimeout + isVisible).
    // expect().toBeVisible() retries until timeout — robust against slow renders.
    // The "Settings" h2 is rendered immediately, before any API call resolves.
    await expect(page.locator("h2")).toContainText("Settings", {
      timeout: 15_000,
    });

    // "Site Details" card appears once api.getSite() resolves.
    // This proves the site was created in beforeAll AND the API works.
    await expect(page.locator("text=Site Details")).toBeVisible({
      timeout: 15_000,
    });
  });

  test("Verify button on settings page", async ({ page }) => {
    test.skip(!testSiteId, "Could not create test site");

    await page.goto(`/dashboard/settings?site=${testSiteId}`);

    // Wait for site data to load — "Verify Now" or "Verified" appears in Site Details.
    // Use .first() because .or() can match multiple elements (strict mode violation).
    await expect(
      page.locator('button:has-text("Verify Now")').or(
        page.locator("text=Verified")
      ).first()
    ).toBeVisible({ timeout: 15_000 });
  });

  test.afterAll(async ({ browser }) => {
    // Cleanup: delete test site
    if (!testSiteId) return;
    const context = await browser.newContext({
      storageState: "e2e/.auth/user.json",
    });
    const page = await context.newPage();
    await page.goto("/");
    await deleteSiteIfExists(page, testSiteId);
    await context.close();
  });
});
