import { test, expect } from "@playwright/test";
import { interceptIngest, fixture, settle } from "./harness";

// Phase 2 — AC5. Browser autofill into an email field is captured via the
// `input`/`change` path (no form submit). Cross-browser matrix: chromium is
// always run; webkit + firefox run when their binaries are installed (a
// documented known-gap otherwise — plan Phase 0 item 7 / Phase 2 item 1).
// Run with: --project=chromium [--project=webkit --project=firefox]

test("captures an autofilled email across the running browser project", async ({ page }) => {
  const ingest = await interceptIngest(page);

  await page.goto(fixture("autofill.html"));
  // page.fill simulates autofill: sets value + dispatches input (and change).
  await page.fill("#email", "auto@fill.com");
  await page.locator("#email").blur();
  await settle(page);

  const captured = ingest.emails().find((e) => e.email === "auto@fill.com");
  expect(captured, "autofilled email should be captured").toBeTruthy();
});
