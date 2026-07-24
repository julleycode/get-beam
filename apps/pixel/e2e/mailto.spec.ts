import { test, expect } from "@playwright/test";
import { interceptIngest, fixture, settle } from "./harness";

// Phase 1 — AC3. Clicking a mailto: link captures the address in the href
// (query suffix stripped), via the existing click handler + captureEmail funnel.

test("captures the address from a clicked mailto: link", async ({ page }) => {
  const ingest = await interceptIngest(page);

  await page.goto(fixture("mailto.html"));
  await page.click("#email-us");
  await settle(page);

  const captured = ingest.emails().find((e) => e.email === "hello@co.com");
  expect(captured, "mailto address should be captured").toBeTruthy();
  expect(captured!.source).toBe("mailto_click");
});
