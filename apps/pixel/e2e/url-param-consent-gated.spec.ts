import { test, expect } from "@playwright/test";
import { interceptIngest, fixture, settle } from "./harness";

// Phase 1 — Hard Guardrail G7 (VALIDATE finding). On a GATED site (data-consent
// ="all"), a URL-param email must be QUEUED but NOT sent until the visitor grants
// consent. Proves the url-param capture is placed after the GATED/consentDecision
// init so flush()'s consentBlocked() hold applies (no EU-consent-hold bypass).

test("holds URL-param capture until consent is granted on a GATED site", async ({ page }) => {
  const ingest = await interceptIngest(page);

  await page.goto(fixture("consent-all.html", "?email=jane@gated.com"));
  await settle(page);

  // Consent undecided → zero network calls, but the event is queued in _rta_q.
  expect(ingest.callCount(), "no ingest call before consent").toBe(0);
  const queuedHasEmail = await page.evaluate(() => {
    try {
      const q = JSON.parse(localStorage.getItem("_rta_q") || "[]");
      return q.some((e: any) => e.type === "form_email_capture" && e.email === "jane@gated.com");
    } catch {
      return false;
    }
  });
  expect(queuedHasEmail, "url-param email should be queued while consent pending").toBe(true);

  // Grant consent → the held batch (incl. the url-param email) flushes.
  await page.evaluate(() => (window as any).beamConsent(true));
  await settle(page);

  expect(ingest.callCount(), "ingest call fires after consent granted").toBeGreaterThanOrEqual(1);
  const captured = ingest.emails().find((e) => e.email === "jane@gated.com");
  expect(captured, "url-param email delivered after consent").toBeTruthy();
});
