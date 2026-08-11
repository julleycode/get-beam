import { test, expect, Page } from "@playwright/test";
import { interceptIngest, fixture, settle, Ingest } from "./harness";

// WS2 Detector B — the navigator.brave probe.
//
// The Python pixel suite is string/regex-only against raw source: it proves the
// probe is PRESENT and POSITIONED after the consent gate, but never that it
// EXECUTES. This spec is the only place it actually runs in a browser.
//
// navigator.brave does not exist in Chromium/WebKit/Firefox, so the "real Brave"
// side is stubbed with addInitScript. The un-stubbed control test is the more
// important half: it proves the probe cannot false-positive on an ordinary
// browser, which is what would otherwise silently gate real visitors out of
// Check 2/3 once the flag is flipped.

/** Force a flush: captureEmail → pushEvent → flush() runs synchronously. */
async function flush(page: Page, tag: string): Promise<void> {
  await page.evaluate((e) => (window as any).beamIdentify(e), `${tag}@probe.test`);
  await settle(page, 200);
}

/** Poll until an event carrying _fb shows up — the probe is async. */
async function waitForFb(page: Page, ingest: Ingest, tag: string): Promise<boolean> {
  let attempt = 0;
  try {
    await expect
      .poll(
        async () => {
          await flush(page, `${tag}-${attempt++}`);
          return ingest.events().some((e) => e._fb === 1);
        },
        { timeout: 5_000, intervals: [200] },
      )
      .toBe(true);
    return true;
  } catch {
    return false;
  }
}

test.describe("WS2 farbled probe", () => {
  test("a Brave-like browser eventually marks events with _fb", async ({ page }) => {
    await page.addInitScript(() => {
      (navigator as any).brave = { isBrave: () => Promise.resolve(true) };
    });
    const ingest = await interceptIngest(page);
    await page.goto(fixture("base.html"));

    expect(await waitForFb(page, ingest, "brave")).toBe(true);
  });

  test("an ordinary browser never marks events with _fb", async ({ page }) => {
    const ingest = await interceptIngest(page);
    await page.goto(fixture("base.html"));

    await flush(page, "plain-1");
    await settle(page, 500);
    await flush(page, "plain-2");

    const events = ingest.events();
    expect(events.length).toBeGreaterThan(0);
    for (const e of events) {
      expect(e._fb, "_fb must be absent on a non-farbled browser").toBeUndefined();
    }
  });

  test("isBrave() resolving false is treated as not farbled", async ({ page }) => {
    await page.addInitScript(() => {
      (navigator as any).brave = { isBrave: () => Promise.resolve(false) };
    });
    const ingest = await interceptIngest(page);
    await page.goto(fixture("base.html"));

    await flush(page, "notbrave");
    await settle(page, 500);
    await flush(page, "notbrave-2");

    for (const e of ingest.events()) {
      expect(e._fb).toBeUndefined();
    }
  });

  test("a never-settling probe does not delay the first flush", async ({ page }) => {
    // The promise is deliberately never awaited. If someone later makes the
    // tracker wait on it, this hangs — which is the whole point.
    await page.addInitScript(() => {
      (navigator as any).brave = { isBrave: () => new Promise(() => {}) };
    });
    const ingest = await interceptIngest(page);
    await page.goto(fixture("base.html"));

    const started = Date.now();
    await flush(page, "pending");
    const elapsed = Date.now() - started;

    expect(ingest.events().length, "events still flow with the probe pending")
      .toBeGreaterThan(0);
    expect(elapsed, "flush must not block on the probe").toBeLessThan(3_000);
  });

  test("an audio render that never completes emits no _fp3 at all", async ({ page }) => {
    // The 1s watchdog is the only nondeterministic fp3 input: on a loaded
    // machine the render can miss the deadline in one session and make it in
    // the next, giving the SAME browser two different fp3 values. The server
    // reads an fp3 change as farbling evidence, so the pixel must suppress fp3
    // entirely rather than hash the timing artifact. fp2 must keep flowing.
    await page.addInitScript(() => {
      const Stub = function (this: any) {
        this.destination = {};
        this.createOscillator = () => ({
          type: "",
          frequency: { value: 0 },
          connect: () => {},
          start: () => {},
        });
        this.createDynamicsCompressor = () => ({
          threshold: { value: 0 },
          knee: { value: 0 },
          ratio: { value: 0 },
          attack: { value: 0 },
          release: { value: 0 },
          connect: () => {},
        });
        this.startRendering = () => {}; // oncomplete never fires
      };
      (window as any).OfflineAudioContext = Stub;
      (window as any).webkitOfflineAudioContext = Stub;
    });
    const ingest = await interceptIngest(page);
    await page.goto(fixture("base.html"));

    await flush(page, "audio-timeout-1");
    await settle(page, 1_800); // past the 1s watchdog
    await flush(page, "audio-timeout-2");
    await settle(page, 300);
    await flush(page, "audio-timeout-3");

    const events = ingest.events();
    expect(events.length).toBeGreaterThan(0);
    for (const e of events) {
      expect(e._fp, "fp2 must keep flowing").toBeTruthy();
      expect(e._fp3, "_fp3 must never be emitted after an audio timeout")
        .toBeUndefined();
    }
  });

  test("a throwing navigator.brave never breaks the pixel", async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(navigator, "brave", {
        get() {
          throw new Error("blocked");
        },
      });
    });
    const ingest = await interceptIngest(page);
    await page.goto(fixture("base.html"));

    await flush(page, "throws");

    const events = ingest.events();
    expect(events.length, "the try/catch must keep the tracker alive")
      .toBeGreaterThan(0);
    expect(events[0]._fp, "fingerprinting still works").toBeTruthy();
  });
});
