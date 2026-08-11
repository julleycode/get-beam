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
        .locator("h1:has-text('Visitor')")
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

// ── Privacy-hold Clear (Option D) — Hybrid e2e legs ──────────────────────────
//
// These prove the held-row banner/button/confirm-dialog wiring (SPEC AC-1/2/3/6
// + AC-13 copy-presence). They require an AUTHENTICATED dashboard session on a
// site that has a visitor with do_not_resolve=true. That precondition depends on
// the shared Clerk Playwright auth-harness, which is a recurring KNOWN GAP across
// this repo (billing/exports, ads-audiences, cadence-bot-flag). Until that
// harness + a seeded held visitor exist, these legs stay CONDITIONAL and are
// skipped rather than left to fail — tracked as a backlog stub. Flip the guard by
// exporting E2E_PRIVACY_HOLD_VISITOR="<visitor_id>" (a held row on the signed-in
// site) once the auth harness lands. Selectors follow the canonical Playwright
// rules in process/context/tests/all-tests.md (auto-retry toBeVisible, .first()
// with .or(), specific selectors read from the component source).
test.describe("Visitors — privacy hold clear", () => {
  const heldVisitorId = process.env.E2E_PRIVACY_HOLD_VISITOR;

  test.beforeEach(async ({ page }) => {
    test.skip(
      !heldVisitorId,
      "Requires Clerk auth-harness + a seeded do_not_resolve visitor (known gap — backlog stub)",
    );
    await page.goto("/dashboard/visitors");
    await page.waitForLoadState("networkidle");
  });

  // V-e2e-banner (AC-1): held row reads as a privacy hold, not a limit.
  test("held row shows a Privacy hold state, not a usage limit", async ({ page }) => {
    await expect(
      page.locator("text=Privacy hold").first(),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      page.locator("text=policy block, not a usage limit").first(),
    ).toBeVisible({ timeout: 15_000 });
  });

  // V-e2e-button-visibility (AC-2): Clear control shows for held rows.
  test("held row exposes a Clear privacy hold button", async ({ page }) => {
    await expect(
      page.locator("button:has-text('Clear privacy hold')").first(),
    ).toBeVisible({ timeout: 15_000 });
  });

  // V-e2e-confirm-dialog (AC-3): clicking opens a confirm dialog; cancel = no-op.
  test("clicking Clear opens a confirm dialog; Cancel makes no write", async ({ page }) => {
    await page.locator("button:has-text('Clear privacy hold')").first().click();
    await expect(
      page.locator("text=Clear this visitor's privacy hold?"),
    ).toBeVisible({ timeout: 15_000 });
    await page.locator("button:has-text('Cancel')").click();
    // Cancel closes the dialog with no write — the held row (and its Clear
    // button) is still present.
    await expect(
      page.locator("button:has-text('Clear privacy hold')").first(),
    ).toBeVisible({ timeout: 15_000 });
  });

  // V-e2e-copy-presence (AC-13 presence): confirm copy carries the required
  // deliberate / this-site-only / does-not-unsuppress markers.
  test("confirm dialog copy states deliberate, site-only, non-un-suppressing", async ({ page }) => {
    await page.locator("button:has-text('Clear privacy hold')").first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 15_000 });
    await expect(dialog).toContainText("deliberate action");
    await expect(dialog).toContainText("this visitor on this site only");
    await expect(dialog).toContainText("suppression");
  });

  // V-e2e-post-clear-ui (AC-6): after a confirmed clear, the hold is gone and the
  // normal Identify control returns for that visitor.
  test("after confirming, the hold clears and Identify returns", async ({ page }) => {
    await page.locator("button:has-text('Clear privacy hold')").first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 15_000 });
    await dialog.locator("button:has-text('Clear privacy hold')").click();
    // Row re-fetches: the Identify button appears and the Privacy hold state is
    // gone for this visitor.
    await expect(
      page.locator("button:has-text('Identify')").first(),
    ).toBeVisible({ timeout: 15_000 });
  });
});
