import { test, expect, Page } from "@playwright/test";
import { interceptIngest, fixture, settle, Ingest } from "./harness";

// fp3 = the fp2 base signals plus the installed-font probe and the offline audio
// render. Both new signals run in a real browser only, so these assertions are
// the only place they are actually exercised — the Python tests can just grep
// the source.
//
// The load-bearing property is that fp2 keeps flowing unchanged: it is the key
// every fingerprint already on disk was stored under.

/**
 * fp3 resolves asynchronously (DOM-ready font probe + offline audio render), so
 * poll rather than sleeping a fixed amount. The pixel exposes no flush hook and
 * its timer only fires every 5s, so each poll drives a flush via beamIdentify
 * (captureEmail → flush, synchronously). Emails are unique per attempt so a
 * repeat never dedupes into a no-op.
 */
async function captureWithFp3(page: Page, ingest: Ingest, tag: string): Promise<string> {
  let attempt = 0;
  await expect
    .poll(
      async () => {
        await page.evaluate(
          (e) => (window as any).beamIdentify(e),
          `${tag}-${attempt++}@probe.test`,
        );
        await settle(page, 200);
        return ingest.events().some((e) => e.email?.startsWith(tag) && e._fp3);
      },
      { timeout: 10_000, intervals: [200] },
    )
    .toBe(true);

  const ev = ingest.events().find((e) => e.email?.startsWith(tag) && e._fp3);
  return ev!._fp3 as string;
}

test.describe("fingerprint v3", () => {
  test("emits fp2 immediately and fp3 once fonts + audio resolve", async ({ page }) => {
    const ingest = await interceptIngest(page);
    await page.goto(fixture("form-email.html"));

    const fp3 = await captureWithFp3(page, ingest, "load");
    const events = ingest.events();

    for (const e of events) {
      expect(e._fp, "every event carries fp2").toMatch(/^fp2_/);
    }

    expect(fp3).toMatch(/^fp3_/);
    expect(fp3.length).toBeLessThanOrEqual(64);
    expect(fp3).not.toBe(events[0]._fp);

    // One device, one session => one stable value for each hash.
    expect(new Set(events.map((e) => e._fp)).size).toBe(1);
    expect(new Set(events.filter((e) => e._fp3).map((e) => e._fp3)).size).toBe(1);
  });

  test("fp3 is stable across reloads on the same device", async ({ page }) => {
    const ingest = await interceptIngest(page);

    await page.goto(fixture("form-email.html"));
    const first = await captureWithFp3(page, ingest, "first");

    await page.goto(fixture("form-email.html"));
    const second = await captureWithFp3(page, ingest, "second");

    // An unstable fp3 is worse than no fp3: it splits one person into many
    // visitors and defeats the whole point of the extra signals.
    expect(second).toBe(first);
  });

  test("font probe does not leave its measuring span in the DOM", async ({ page }) => {
    const ingest = await interceptIngest(page);
    await page.goto(fixture("form-email.html"));
    await captureWithFp3(page, ingest, "cleanup");

    const strays = await page.evaluate(
      () =>
        Array.from(document.querySelectorAll("span")).filter(
          (s) => s.textContent === "mmmmmmmmmmlli",
        ).length,
    );
    expect(strays).toBe(0);
  });
});
