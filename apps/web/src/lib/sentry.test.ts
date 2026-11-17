import { afterEach, describe, expect, it, vi } from "vitest";
import * as Sentry from "@sentry/nextjs";

import {
  TRACES_SAMPLE_RATE,
  buildSentryOptions,
  initSentry,
  readSentryDsn,
  readSentryEnvironment,
  readSentryRelease,
  scrubSentryEvent,
} from "./sentry";

// Public example key. The transport below never opens a socket.
const DUMMY_DSN = "https://public@o0.ingest.sentry.io/0";

type CapturedEvent = {
  exception?: { values?: Array<{ value?: string }> };
  user?: { id?: string; email?: string };
  release?: string;
  environment?: string;
  request?: { headers?: Record<string, string>; cookies?: unknown };
};

function eventFromEnvelopes(envelopes: unknown[]): CapturedEvent {
  for (const envelope of envelopes) {
    if (!Array.isArray(envelope)) continue;
    const items = envelope[1];
    if (!Array.isArray(items)) continue;
    for (const item of items) {
      if (!Array.isArray(item)) continue;
      const header = item[0] as { type?: string } | undefined;
      const payload = item[1];
      if (header?.type === "event" && payload && typeof payload === "object") {
        return payload as CapturedEvent;
      }
    }
  }
  throw new Error("no event item in captured envelopes");
}

afterEach(async () => {
  vi.unstubAllEnvs();
  await Sentry.close(0);
});

describe("dashboard sentry with no DSN", () => {
  it("stays off and does not throw", () => {
    vi.stubEnv("NEXT_PUBLIC_SENTRY_DSN", "");
    vi.stubEnv("SENTRY_DSN", "");

    expect(readSentryDsn()).toBe("");
    expect(initSentry()).toBe(false);
    expect(Sentry.getClient()?.getDsn()).toBeUndefined();
  });
});

describe("dashboard sentry with a dummy DSN", () => {
  it("captures a forced error and drops auth headers, cookies, and email", async () => {
    const envelopes: unknown[] = [];
    const env = {
      ...process.env,
      VERCEL_ENV: "preview",
      VERCEL_GIT_COMMIT_SHA: "abc123def",
    };

    Sentry.init({
      ...buildSentryOptions(DUMMY_DSN, env),
      transport() {
        return {
          send(envelope: unknown) {
            envelopes.push(envelope);
            return Promise.resolve({});
          },
          flush() {
            return Promise.resolve(true);
          },
        };
      },
    });

    Sentry.setUser({ id: "user_clerk_1", email: "secret@example.com" });
    Sentry.withScope((scope) => {
      scope.addEventProcessor((event) => {
        event.request = {
          ...event.request,
          headers: {
            ...(event.request?.headers ?? {}),
            Authorization: "Bearer secret-token",
            Cookie: "sid=secret-cookie",
            "User-Agent": "vitest",
          },
          cookies: { sid: "secret-cookie" },
        };
        return event;
      });
      Sentry.captureException(new Error("forced sentry test"));
    });
    await Sentry.flush(2000);

    expect(envelopes.length).toBeGreaterThan(0);
    const event = eventFromEnvelopes(envelopes);
    expect(event.exception?.values?.[0]?.value).toBe("forced sentry test");
    expect(event.user).toEqual({ id: "user_clerk_1" });
    expect(event.user).not.toHaveProperty("email");
    expect(event.release).toBe("abc123def");
    expect(event.environment).toBe("preview");
    const headers = event.request?.headers ?? {};
    const headerNames = Object.keys(headers).map((key) => key.toLowerCase());
    expect(headerNames).not.toContain("authorization");
    expect(headerNames).not.toContain("cookie");
    expect(event.request?.cookies).toBeUndefined();
    expect(JSON.stringify(event.request ?? {})).not.toContain("secret-token");
    expect(JSON.stringify(event.request ?? {})).not.toContain("secret-cookie");
    expect(JSON.stringify(event.user)).not.toContain("secret@example.com");
  });
});

describe("sentry tags", () => {
  it("prefers the Vercel commit SHA and environment", () => {
    const env = {
      VERCEL_GIT_COMMIT_SHA: "vercel-sha",
      RAILWAY_GIT_COMMIT_SHA: "railway-sha",
      VERCEL_ENV: "production",
      NODE_ENV: "development",
    } as NodeJS.ProcessEnv;

    expect(readSentryRelease(env)).toBe("vercel-sha");
    expect(readSentryEnvironment(env)).toBe("production");
    expect(buildSentryOptions(DUMMY_DSN, env).tracesSampleRate).toBe(TRACES_SAMPLE_RATE);
    expect(TRACES_SAMPLE_RATE).toBe(0.1);
  });

  it("scrubs a synthetic event down to the user id", () => {
    const event = scrubSentryEvent({
      request: {
        headers: {
          Authorization: "Bearer secret-token",
          Cookie: "sid=secret-cookie",
          "User-Agent": "vitest",
        },
        cookies: { sid: "secret-cookie" },
        data: { email: "secret@example.com" },
      },
      user: { id: "user_abc", email: "secret@example.com", ip_address: "203.0.113.5" },
    });

    expect(event.user).toEqual({ id: "user_abc" });
    expect(event.request?.headers).toEqual({ "User-Agent": "vitest" });
    expect(event.request?.cookies).toBeUndefined();
    expect(event.request?.data).toBeUndefined();
    expect(JSON.stringify(event)).not.toContain("secret@example.com");
  });
});
