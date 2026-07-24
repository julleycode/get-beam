import { Page, Route, Request } from "@playwright/test";

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
