import { test, expect, Page } from "@playwright/test";
import { interceptIngest, fixture, settle, Ingest } from "./harness";

// WS2 agent-session signals ("fires at all" check, plan Step 2 / SPEC AC-3).
//
// The Python pixel suite is string/regex-only against raw source — it can prove
// the collector is POSITIONED correctly but never that it EXECUTES. This spec is
// the only place the Stage-2 counters actually run in a browser.
//
// It is a structural sanity check, not a detection-accuracy claim: it asserts the
// counters move off their initial state under real clicks, so a future trim that
// silently kills the signal fails here instead of shipping dead weight (the exact
// pathology that left WS2 dormant in the first place).

/** Force a flush: captureEmail → pushEvent → flush() runs synchronously. */
async function flush(page: Page, tag: string): Promise<void> {
  await page.evaluate((e) => (window as any).beamIdentify(e), `${tag}@probe.test`);
  await settle(page, 200);
}

/** Every _asig object the tracker actually sent. */
function sigs(ingest: Ingest): Array<Record<string, any>> {
  return ingest.events().map((e) => e._asig).filter(Boolean);
}

test.describe("WS2 agent_sig", () => {
  // NOTE: the webkit/firefox sendBeacon transport stub that used to live here
  // now lives in interceptIngest() (harness.ts) so every spec gets it. One
  // mechanism, not two — see that comment for the reasoning and the chromium
  // carve-out.

  test("attaches _asig to every outgoing event", async ({ page }) => {
    const ingest = await interceptIngest(page);
    await page.goto(fixture("agent-sig.html"));
    await flush(page, "attach");

    const events = ingest.events();
    expect(events.length).toBeGreaterThan(0);
    for (const e of events) {
      expect(e._asig, "every event carries _asig").toBeTruthy();
      expect(typeof e._asig.w).toBe("boolean");
      expect(typeof e._asig.h).toBe("boolean");
    }
  });

  test("dead-centre clicks move the Stage-2 counters off their defaults", async ({ page }) => {
    const ingest = await interceptIngest(page);
    await page.goto(fixture("agent-sig.html"));

    // Click the exact centre of each button — the shape the classifier treats as
    // agent-like. Playwright's default click position IS the element centre.
    await page.click("#b1");
    await page.click("#b2");
    await page.click("#b1");
    await flush(page, "centre");

    const all = sigs(ingest);
    expect(all.length).toBeGreaterThan(0);

    // click_ct is cumulative; dead-centre count is a per-event delta, so sum it.
    const clicks = Math.max(...all.map((s) => s.c ?? 0));
    const deadCentre = all.reduce((n, s) => n + (s.d ?? 0), 0);

    expect(clicks, "click_ct did not increment — Stage 2 is dead").toBeGreaterThanOrEqual(3);
    expect(deadCentre, "dead_center_ct stayed at 0 despite centred clicks").toBeGreaterThanOrEqual(3);
  });

  test("pointer movement flips the entropy proxy off its agent-like default", async ({ page }) => {
    const ingest = await interceptIngest(page);
    await page.goto(fixture("agent-sig.html"));

    await flush(page, "before");
    const beforeMove = sigs(ingest);
    expect(beforeMove.length).toBeGreaterThan(0);
    expect(
      beforeMove.every((s) => s.p === 0),
      "p should start at 0 (no pointermove seen = agent-like)",
    ).toBe(true);

    await page.mouse.move(10, 10);
    await page.mouse.move(120, 90);
    await flush(page, "after");

    const latest = sigs(ingest).at(-1)!;
    expect(latest.p, "pointermove fired but the entropy proxy never flipped").toBe(1);
  });

  test("_asig is withheld until the consent gate resolves (G7)", async ({ page }) => {
    // consent-all.html is GATED with no stored decision, so the tracker must not
    // ship anything at all — which also proves no signal leaks pre-gate.
    const ingest = await interceptIngest(page);
    await page.goto(fixture("consent-all.html"));
    await settle(page, 300);

    expect(sigs(ingest).length).toBe(0);
  });
});
