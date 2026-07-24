import { test, expect } from "@playwright/test";
import { interceptIngest, fixture, settle } from "./harness";

// Phase 2 — AC6. An email typed into a field inside a same-origin OPEN shadow
// root is captured. `input` is composed:true so it reaches the document listener;
// composedPath()[0] recovers the true inner field (event.target is retargeted).

test("captures an email typed inside a same-origin open shadow-DOM widget", async ({ page }) => {
  const ingest = await interceptIngest(page);

  await page.goto(fixture("shadow-dom.html"));
  // Playwright CSS pierces open shadow roots by default.
  await page.locator("#semail").fill("shadow@widget.com");
  await settle(page);

  const captured = ingest.emails().find((e) => e.email === "shadow@widget.com");
  expect(captured, "shadow-DOM email should be captured").toBeTruthy();
});
