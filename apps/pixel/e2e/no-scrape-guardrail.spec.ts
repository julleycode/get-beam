import { test, expect } from "@playwright/test";
import { interceptIngest, fixture, settle } from "./harness";

// Phase 2 — AC8 / G6. A field pre-populated by site JS before any interaction,
// and a type="hidden" field carrying an email, both produce ZERO capture events
// even though their values pass looksEmail(). Proves the pixel never scrapes a
// value the visitor didn't actively provide this session.

test("produces zero capture events for a prefilled-untouched field and a hidden field", async ({ page }) => {
  const ingest = await interceptIngest(page);

  await page.goto(fixture("no-scrape.html"));
  await settle(page);

  // No interaction at all → nothing may be captured from page load.
  expect(ingest.emails(), "no email captured on page load").toEqual([]);

  // Even submitting the form must not capture the prefilled (untouched) username
  // or the hidden field — the visitor never typed into either this session.
  await page.click("#go");
  await settle(page);

  const leaked = ingest
    .emails()
    .filter((e) => e.email === "prefilled@leak.com" || e.email === "hidden@leak.com");
  expect(leaked, "prefilled/hidden values must never be captured").toEqual([]);
});
