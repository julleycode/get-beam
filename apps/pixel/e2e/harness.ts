import { Page, Route, Request, test } from "@playwright/test";

// Shared harness for pixel capture specs.
//
// The pixel POSTs batched events to `${data-api}/api/v1/events/ingest`. We
// intercept that route (never hitting a real API), fulfil 204, and record every
// captured payload so specs can assert on the events the tracker actually sent.
//
// `form_email_capture` events are what every email-capture mechanism ultimately
// emits (via captureEmail → pushEvent → flush). Specs assert on those.

export interface CapturedBatch {
  site_id: string;
  visitor_id: string;
  events: Array<Record<string, any>>;
}

export interface Ingest {
  batches: CapturedBatch[];
  /** flat list of every event across all batches */
  events: () => Array<Record<string, any>>;
  /** every form_email_capture event's {email, source} */
  emails: () => Array<{ email: string; source: string }>;
  /** total number of ingest network calls the pixel made */
  callCount: () => number;
}

/**
 * Install the ingest route interceptor. Returns an Ingest recorder. Call this
 * BEFORE navigating so the very first flush is captured.
 */
export async function interceptIngest(page: Page): Promise<Ingest> {
  const batches: CapturedBatch[] = [];
  let calls = 0;

  // Transport fix (harness-only — tracker.js is untouched).
  //
  // tracker.js flush() uses a readable XHR only for the FIRST flush of a
  // session, then navigator.sendBeacon for every flush after. page.route
  // intercepts sendBeacon in chromium but NOT in webkit/firefox, so on those
  // two engines every post-first-flush batch was invisible to this recorder —
  // any assertion about a later batch passed without testing anything.
  //
  // Stubbing sendBeacon to return false makes flush() fall through to its own
  // XHR path (same payload), which page.route does see everywhere.
  //
  // Gated on project name deliberately: chromium CAN intercept sendBeacon, and
  // sendBeacon is the transport production actually uses for every flush after
  // the first. Stubbing it unconditionally would leave no engine covering that
  // transport at all — relocating the same "green but testing nothing" problem.
  const project = test.info().project.name;
  if (project === "webkit" || project === "firefox") {
    await page.addInitScript(() => {
      Object.defineProperty(navigator, "sendBeacon", { value: () => false, configurable: true });
    });
  }

  await page.route("**/api/v1/events/ingest", async (route: Route, request: Request) => {
    calls++;
    try {
      const body = request.postData();
      if (body) batches.push(JSON.parse(body) as CapturedBatch);
    } catch {
      /* non-JSON body — ignore, still count the call */
    }
    await route.fulfill({ status: 204, body: "" });
  });

  return {
    batches,
    events: () => batches.flatMap((b) => b.events || []),
    emails: () =>
      batches
        .flatMap((b) => b.events || [])
        .filter((e) => e.type === "form_email_capture" && e.email)
        .map((e) => ({ email: e.email as string, source: (e.source as string) || "form" })),
    callCount: () => calls,
  };
}

/**
 * Build a fixture URL with optional query string (used for URL-param tests).
 */
export function fixture(name: string, query = ""): string {
  const q = query ? (query.startsWith("?") ? query : "?" + query) : "";
  return `http://127.0.0.1:8788/e2e/fixtures/${name}${q}`;
}

/**
 * Give the pixel a beat to run its synchronous capture + first flush. captureEmail
 * calls flush() synchronously, so a short settle is enough; we also poll.
 */
export async function settle(page: Page, ms = 300): Promise<void> {
  await page.waitForTimeout(ms);
}

export interface GreetingStub {
  /** number of times greeting.js was requested */
  scriptLoads: () => number;
  /** every /api/v1/greeting request URL */
  apiCalls: string[];
}

/**
 * On-site greeting harness (onsite-greeting). Serves the UNMINIFIED
 * src/greeting.js for any `**\/pixel/greeting.js` request (the tracker loads it
 * from data-api, which the static server does not host) and stubs
 * `**\/api/v1/greeting` with the given status/body. Call BEFORE navigating.
 */
export async function interceptGreeting(
  page: Page,
  body: Record<string, unknown> = { show: true, template_id: "default", text: "Welcome, Acme team!", cta_url: null },
  status = 200,
): Promise<GreetingStub> {
  const fs = await import("fs");
  const path = await import("path");
  const src = fs.readFileSync(path.join(__dirname, "..", "src", "greeting.js"), "utf8");
  let loads = 0;
  const apiCalls: string[] = [];
  await page.route("**/pixel/greeting.js*", async (route: Route) => {
    loads++;
    await route.fulfill({ status: 200, contentType: "application/javascript", body: src });
  });
  await page.route("**/api/v1/greeting*", async (route: Route, request: Request) => {
    apiCalls.push(request.url());
    await route.fulfill({
      status,
      contentType: "application/json",
      headers: { "access-control-allow-origin": "*", "cache-control": "no-store" },
      body: JSON.stringify(body),
    });
  });
  return { scriptLoads: () => loads, apiCalls };
}
