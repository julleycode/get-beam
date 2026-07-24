import { test, expect } from "@playwright/test";
import { interceptIngest, fixture, settle } from "./harness";

// Phase 1 — AC4 (capture leg; the no-plaintext-log leg is a backend pytest,
// tests/unit/test_url_param_email_logging.py). A page loaded with ?email=<addr>
// captures the address via the URL-param mechanism. Non-GATED site → flushes.

test("captures a URL email param and never echoes it as plaintext", async ({ page }) => {
  const ingest = await interceptIngest(page);

  await page.goto(fixture("base.html", "?email=jane@magiclink.com"));
  await settle(page);

  const captured = ingest.emails().find((e) => e.email === "jane@magiclink.com");
  expect(captured, "url-param email should be captured").toBeTruthy();
  expect(captured!.source).toBe("url_param");

  // Client-side no-plaintext guard (D1): the pixel must not create any NEW
  // plaintext store for the address. The transient event queue (_rta_q) may hold
  // a pageview whose `url` mirrors the browser URL (which itself carries the
  // ?email= param — unavoidable browser state, not a pixel-created leak, per D1);
  // that plus the pixel's own known keys are the ONLY places the string may live.
  // A leak = the raw email inside any key outside that allow-list.
  const KNOWN = ["_rta_q", "_rta_vid", "_rta_c"];
  const leaked = await page.evaluate((known) => {
    const out: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)!;
      if (!known.includes(k) && (localStorage.getItem(k) || "").includes("jane@magiclink.com")) out.push(k);
    }
    return out;
  }, KNOWN);
  expect(leaked, "pixel must not create a new plaintext store for the email").toEqual([]);
});
