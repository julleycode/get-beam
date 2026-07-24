import { test, expect } from "@playwright/test";
import { interceptIngest, fixture, settle } from "./harness";

// Phase 2 — AC7. An email typed inside a CROSS-origin iframe must produce ZERO
// capture events — the pixel's contentDocument access throws SecurityError and
// is no-op'd (the same-origin boundary enforcement). Parent is served from
// 127.0.0.1:8788; the iframe child from localhost:8788 (different origin).

test("produces zero capture events from a cross-origin iframe", async ({ page }) => {
  const ingest = await interceptIngest(page);

  await page.goto(fixture("cross-origin-iframe.html"));
  await settle(page);
  const child = page.frameLocator("#child");
  await child.locator("#child-email").fill("secret@crossorigin.com");
  await child.locator("#child-email").blur();
  await settle(page);

  const leaked = ingest.emails().find((e) => e.email === "secret@crossorigin.com");
  expect(leaked, "cross-origin iframe email must NOT be captured").toBeFalsy();
});
