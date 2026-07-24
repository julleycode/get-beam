import { test, expect } from "@playwright/test";
import { interceptIngest, fixture, settle } from "./harness";

// Phase 3 — AC12. A per-site config flag disables ONLY its mechanism. With
// data-capture-mailto="off", the mailto click is silent while url-param and
// value-based matching still capture normally.

test("disables only the configured mechanism, leaving others active", async ({ page }) => {
  const ingest = await interceptIngest(page);

  await page.goto(fixture("config-mailto-off.html", "?email=urlparam@on.com"));
  await settle(page);
  // url-param stays active (default on).
  expect(ingest.emails().find((e) => e.email === "urlparam@on.com"), "url-param active").toBeTruthy();

  // mailto is OFF → clicking the mailto link captures nothing.
  await page.click("#email-us");
  await settle(page);
  expect(ingest.emails().find((e) => e.email === "mailto@off.com"), "mailto disabled").toBeFalsy();

  // value-based matching stays active (non-configurable).
  await page.fill("#username", "value@on.com");
  await page.click("#go");
  await settle(page);
  const vm = ingest.emails().find((e) => e.email === "value@on.com");
  expect(vm, "value-match active").toBeTruthy();
  expect(vm!.source).toBe("login");
});
