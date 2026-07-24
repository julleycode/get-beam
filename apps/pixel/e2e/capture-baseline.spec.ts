import { test, expect } from "@playwright/test";
import { interceptIngest, fixture, settle } from "./harness";

// Phase 0 — AC15 baseline. Proves the harness runs AND that an EXISTING (pre-SPEC)
// capture mechanism (form submit on a literal name="email" field) works end to end
// through the intercepted ingest endpoint. This is the regression anchor for AC2.

test("harness runs and captures an email via the existing form-submit mechanism", async ({ page }) => {
  const ingest = await interceptIngest(page);

  await page.goto(fixture("form-email.html"));
  await page.fill("#email", "jane@baseline.com");
  await page.click("button[type=submit]");
  await settle(page);

  const emails = ingest.emails();
  expect(emails.length).toBeGreaterThanOrEqual(1);
  const captured = emails.find((e) => e.email === "jane@baseline.com");
  expect(captured, "form-submit email should be captured").toBeTruthy();
  // Existing classifier: form#signup-form / action=/subscribe → "newsletter"
  // (sign-up matches). The point is the source is the unchanged classifier value,
  // not a new one — proves pre-SPEC behavior is intact.
  expect(captured!.source).toBe("newsletter");
});
