import { test, expect, type Page } from "@playwright/test";

/**
 * The canary onboarding beat: catch → listen → reveal → confirm.
 *
 * Everything here is mocked at the network layer. Two reasons, both load-bearing:
 *
 * 1. The real endpoint needs a live pixel hit on getbeam.fyi from the same
 *    fingerprint, which no CI runner can produce.
 * 2. `location_reveal_enabled` ships FALSE, so the real endpoint 404s. That is
 *    itself a covered path (the flow must degrade honestly), but it cannot be
 *    the substrate for the happy-path legs.
 */

/** A 1×1 transparent PNG — stands in for every OSM tile so CI does no third-party I/O. */
const PNG_1PX = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

const LANDED = {
  landed: true,
  pages: [
    { path: "/pricing", title: "Pricing", seconds: 42, at: "2026-08-10T10:00:00" },
    { path: "/blog", title: "Blog", seconds: 12, at: "2026-08-10T10:01:00" },
  ],
  geo: {
    lat: 21.0278,
    lng: 105.8342,
    accuracy_km: 25,
    city: "Hanoi",
    region: "Hanoi",
    country_code: "VN",
  },
  network: { label: "Viettel Group", kind: "isp" },
};

const NOT_LANDED_NO_GEO = {
  landed: false,
  pages: [],
  geo: null,
  network: null,
  reason: "provider_unavailable",
};

const NOT_LANDED_WITH_GEO = {
  ...LANDED,
  landed: false,
  pages: [],
};

/**
 * The dashboard calls the API cross-origin (:3000 → :8000) with an
 * Authorization header, so the browser sends a CORS preflight. WITHOUT
 * answering OPTIONS with CORS headers the mock silently fails and the UI sees a
 * network error instead of the canned body. Same pattern as
 * onboarding.spec.ts:59-76.
 */
async function mockCanary(
  page: Page,
  bodies: Array<Record<string, unknown>>,
  onCall?: (n: number) => void,
) {
  let call = 0;
  await page.route("**/api/v1/onboarding/canary", async (route) => {
    if (route.request().method() === "OPTIONS") {
      await route.fulfill({
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "POST, OPTIONS",
          "access-control-allow-headers": "authorization, content-type",
        },
      });
      return;
    }
    const body = bodies[Math.min(call, bodies.length - 1)];
    call += 1;
    onCall?.(call);
    await route.fulfill({
      json: body,
      headers: { "access-control-allow-origin": "*" },
    });
  });
}

async function mockFeedback(page: Page) {
  await page.route("**/api/v1/onboarding/identity-feedback", async (route) => {
    if (route.request().method() === "OPTIONS") {
      await route.fulfill({
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "POST, OPTIONS",
          "access-control-allow-headers": "authorization, content-type",
        },
      });
      return;
    }
    await route.fulfill({
      status: 204,
      headers: { "access-control-allow-origin": "*" },
    });
  });
}

/** No third-party network I/O in CI, and a tile that always succeeds. */
async function mockTiles(page: Page) {
  await page.route("**/tile.openstreetmap.org/**", (route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: PNG_1PX }),
  );
}

/**
 * Stub window.open BEFORE any script runs and record the URL, so the
 * `canary_go` leg can assert the exact target without spawning a real tab.
 * Also clears the resume key — a persisted step would skip the whole flow.
 */
async function prepare(page: Page) {
  await page.addInitScript(() => {
    (window as unknown as { __opened: string[] }).__opened = [];
    window.open = ((url?: string | URL) => {
      (window as unknown as { __opened: string[] }).__opened.push(String(url));
      return null;
    }) as typeof window.open;
    try {
      localStorage.removeItem("beam_onboarding_v2");
    } catch {
      /* storage blocked — the flow tolerates it */
    }
  });
}

/** The chat's site form. NOT `input#name` — that is the classic (no-?welcome) form. */
const SITE_URL_INPUT = "input#ob-site-url";

/**
 * Open the chat.
 *
 * The reload is not superstition: on the FIRST navigation after Next's dev
 * server compiles this route it can serve a partially-written chunk, which the
 * browser reports as `SyntaxError: Invalid or unexpected token` and leaves the
 * transcript empty. A second navigation always gets the finished chunk. This is
 * a dev-server artifact — `npm run build` compiles the same source cleanly —
 * but `playwright.config.ts` runs the suite against `npm run dev`, so the suite
 * has to tolerate it or it flakes on whichever spec compiles the route first.
 */
async function openChat(page: Page) {
  await page.goto("/dashboard/onboarding?welcome=1");
  const chat = page.locator(".ob-chat");
  try {
    await expect(chat).not.toBeEmpty({ timeout: 8_000 });
  } catch {
    await page.reload();
    await expect(chat).not.toBeEmpty({ timeout: 20_000 });
  }
}

/** Walk the scripted welcome lines and press through to the canary step. */
async function reachCanaryGo(page: Page) {
  await openChat(page);
  const go = page.getByRole("button", { name: /let's do it/i });
  await expect(go).toBeVisible({ timeout: 20_000 });
  await go.click();
  await expect(page.getByRole("button", { name: /catch me/i })).toBeVisible({
    timeout: 20_000,
  });
}

test.describe("Onboarding canary", () => {
  test.beforeEach(async ({ page }) => {
    await prepare(page);
    await mockTiles(page);
    await mockFeedback(page);
  });

  test("canary_go opens getbeam.fyi with ?beam=canary in a new tab", async ({
    page,
  }) => {
    await mockCanary(page, [NOT_LANDED_NO_GEO]);
    await reachCanaryGo(page);

    await page.getByRole("button", { name: /catch me/i }).click();

    const opened = await page.evaluate(
      () => (window as unknown as { __opened: string[] }).__opened,
    );
    // ?beam=canary, NOT the legacy funnel's ?beam=demo — onboarding traffic
    // has to stay separable in the events table.
    expect(opened).toEqual(["https://getbeam.fyi/?beam=canary"]);

    await expect(page.getByTestId("canary-listen")).toBeVisible();
  });

  test("landing on the second poll reveals the map, city and network", async ({
    page,
  }) => {
    // First poll misses (the user has not loaded the page yet), second lands.
    await mockCanary(page, [NOT_LANDED_WITH_GEO, LANDED]);
    await reachCanaryGo(page);
    await page.getByRole("button", { name: /catch me/i }).click();

    const reveal = page.getByTestId("canary-reveal");
    await expect(reveal).toBeVisible({ timeout: 30_000 });

    await expect(page.getByTestId("canary-place")).toContainText("Hanoi");
    await expect(page.getByTestId("canary-place")).toContainText("VN");
    await expect(page.getByTestId("canary-network")).toContainText("Viettel Group");
    await expect(page.getByTestId("canary-pages")).toContainText("/pricing");
    await expect(page.getByTestId("canary-map")).toBeVisible();

    // The honesty caption is not decoration: without it a 30km-off pin reads
    // as a broken product.
    await expect(reveal).toContainText("IP-level estimate");
    // OSM attribution is mandatory under the tile usage policy and must not be
    // hidden. Asserting it here so a future CSS tidy-up cannot quietly drop it.
    await expect(reveal.getByRole("link", { name: /OpenStreetMap/i })).toBeVisible();
  });

  test("a visit that never lands still reveals the map, and never claims a catch", async ({
    page,
  }) => {
    // The VPN / adblocker / DNT cohort. Geo comes from the caller's own IP and
    // is NOT gated on the visit, so this whole cohort must still get a reveal.
    test.setTimeout(180_000);
    await mockCanary(page, [NOT_LANDED_WITH_GEO]);
    await reachCanaryGo(page);
    await page.getByRole("button", { name: /catch me/i }).click();

    await expect(page.getByTestId("canary-reveal")).toBeVisible({
      timeout: 150_000,
    });
    await expect(page.getByTestId("canary-map")).toBeVisible();
    // NEVER fake a detection — the legacy funnel's setTimeout(advance, 3600)
    // claimed a catch it never made.
    await expect(page.locator(".ob-chat")).toContainText("didn't catch your visit");
    await expect(page.locator(".ob-chat")).not.toContainText("got you.");
  });

  test("timing out with no geo says so honestly and renders no map", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    await mockCanary(page, [NOT_LANDED_NO_GEO]);
    await reachCanaryGo(page);
    await page.getByRole("button", { name: /catch me/i }).click();

    // Nothing at all to show → one honest line, straight on to site setup.
    await expect(page.locator(".ob-chat")).toContainText("couldn't catch you", {
      timeout: 150_000,
    });
    await expect(page.getByTestId("canary-map")).toHaveCount(0);
    await expect(page.getByTestId("canary-reveal")).toHaveCount(0);
    await expect(page.locator(SITE_URL_INPUT)).toBeVisible({ timeout: 20_000 });
  });

  test('"not quite" POSTs the checked reasons', async ({ page }) => {
    await mockCanary(page, [LANDED]);
    await reachCanaryGo(page);
    await page.getByRole("button", { name: /catch me/i }).click();

    await expect(page.getByTestId("canary-reveal")).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: /ok, what now/i }).click();

    await page.getByRole("button", { name: /not quite/i }).click();
    await expect(page.getByTestId("identity-feedback-form")).toBeVisible();

    await page.locator('input[value="wrong_city"]').check();
    await page.locator('input[value="vpn_or_proxy"]').check();

    const request = page.waitForRequest(
      (r) =>
        r.url().includes("/api/v1/onboarding/identity-feedback") &&
        r.method() === "POST",
    );
    await page.getByRole("button", { name: /send it/i }).click();
    const posted = await request;

    const body = JSON.parse(posted.postData() || "{}");
    expect(body.reasons).toEqual(["wrong_city", "vpn_or_proxy"]);
    // We record exactly what was on screen, so the feedback is analysable.
    expect(body.shown.city).toBe("Hanoi");
    expect(body.shown.org).toBe("Viettel Group");

    // Optimistic: the flow advances without waiting on the write.
    await expect(page.locator(SITE_URL_INPUT)).toBeVisible({ timeout: 20_000 });
  });

  test("skipping the canary lands straight on the site step", async ({ page }) => {
    await mockCanary(page, [LANDED]);
    await reachCanaryGo(page);

    await page.getByRole("button", { name: /skip, i'll just install/i }).click();

    await expect(page.locator(SITE_URL_INPUT)).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("canary-listen")).toHaveCount(0);
  });

  test("reduced motion reveals every line immediately", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockCanary(page, [LANDED]);

    await page.goto("/dashboard/onboarding?welcome=1");
    // No typing cadence: all three welcome lines plus the control are present
    // as soon as the step mounts.
    await expect(page.getByRole("button", { name: /let's do it/i })).toBeVisible({
      timeout: 5_000,
    });
    await expect(page.locator(".ob-chat")).toContainText("the stupidly easy way");

    await page.getByRole("button", { name: /let's do it/i }).click();
    await expect(page.getByRole("button", { name: /catch me/i })).toBeVisible({
      timeout: 5_000,
    });
    await expect(page.locator(".ob-chat")).toContainText("i'm going to catch you");
  });
});
