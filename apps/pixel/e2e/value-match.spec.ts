import { test, expect } from "@playwright/test";
import { interceptIngest, fixture, settle } from "./harness";

// Phase 1 — AC1. Value-based matching: a field named "username" (no "email"
// hint) holding a valid email is captured on submit. The pre-SPEC name/type
// matcher would miss this entirely.

test("captures an email typed into a non-email-named field via value-based matching", async ({ page }) => {
  const ingest = await interceptIngest(page);

  await page.goto(fixture("value-username.html"));
  await page.fill("#username", "jane@login.com");
  await page.click("button[type=submit]");
  await settle(page);

  const captured = ingest.emails().find((e) => e.email === "jane@login.com");
  expect(captured, "value-based email should be captured").toBeTruthy();
  expect(captured!.source).toBe("login");
});
