import type { ErrorEvent, TransactionEvent } from "@sentry/core";
import * as Sentry from "@sentry/nextjs";

/**
 * Sentry for the Next.js dashboard.
 *
 * Off unless NEXT_PUBLIC_SENTRY_DSN or SENTRY_DSN is set. The browser only
 * sees NEXT_PUBLIC_SENTRY_DSN (Next inlines that prefix). The server can
 * also read SENTRY_DSN.
 *
 * @sentry/nextjs 11 dropped `sendDefaultPii`. `dataCollection` is the
 * replacement: no automatic user profile, no cookies, no bodies, no local
 * variables. `scrubSentryEvent` still strips auth headers and any user
 * field other than id, in case an integration adds them later.
 */

export const TRACES_SAMPLE_RATE = 0.1;

const SENSITIVE_HEADER = /^(authorization|proxy-authorization|cookie|set-cookie|x-api-key)$/i;

type Scrubbable = {
  request?: {
    headers?: Record<string, string>;
    cookies?: unknown;
    data?: unknown;
  };
  user?: {
    id?: string | number;
    email?: string;
    username?: string;
    ip_address?: string | null;
  } | null;
};

export function readSentryDsn(env: NodeJS.ProcessEnv = process.env): string {
  return (env.NEXT_PUBLIC_SENTRY_DSN || env.SENTRY_DSN || "").trim();
}

export function readSentryEnvironment(env: NodeJS.ProcessEnv = process.env): string | undefined {
  const value = (env.VERCEL_ENV || env.APP_ENV || env.NODE_ENV || "").trim();
  return value || undefined;
}

/** Vercel injects VERCEL_GIT_COMMIT_SHA. Railway's SHA is the fallback. */
export function readSentryRelease(env: NodeJS.ProcessEnv = process.env): string | undefined {
  const value = (env.VERCEL_GIT_COMMIT_SHA || env.RAILWAY_GIT_COMMIT_SHA || "").trim();
  return value || undefined;
}

export function scrubSentryEvent<T extends Scrubbable>(event: T): T {
  const headers = event.request?.headers;
  if (headers) {
    for (const key of Object.keys(headers)) {
      if (SENSITIVE_HEADER.test(key)) delete headers[key];
    }
  }
  if (event.request) {
    delete event.request.cookies;
    delete event.request.data;
  }
  if (event.user) {
    const id = event.user.id;
    const hasId = id !== undefined && id !== null && String(id) !== "";
    event.user = hasId ? { id: String(id) } : undefined;
  }
  return event;
}

export function buildSentryOptions(dsn: string, env: NodeJS.ProcessEnv = process.env) {
  return {
    dsn,
    environment: readSentryEnvironment(env),
    release: readSentryRelease(env),
    tracesSampleRate: TRACES_SAMPLE_RATE,
    // Keep transaction events so beforeSendTransaction can scrub them.
    // The SDK default ("stream") ignores beforeSendTransaction.
    traceLifecycle: "static" as const,
    dataCollection: {
      userInfo: false,
      cookies: false,
      httpHeaders: {
        request: {
          deny: ["authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key"],
        },
        response: { deny: ["set-cookie"] },
      },
      httpBodies: [],
      stackFrameVariables: false,
      genAI: { inputs: false, outputs: false },
    },
    beforeSend(event: ErrorEvent) {
      return scrubSentryEvent(event);
    },
    beforeSendTransaction(event: TransactionEvent) {
      return scrubSentryEvent(event);
    },
  };
}

/** Returns true only when a DSN was present and init did not throw. */
export function initSentry(): boolean {
  const dsn = readSentryDsn();
  if (!dsn) return false;
  try {
    Sentry.init(buildSentryOptions(dsn));
    return true;
  } catch {
    return false;
  }
}
