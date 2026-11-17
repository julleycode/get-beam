import * as Sentry from "@sentry/nextjs";

export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs" || process.env.NEXT_RUNTIME === "edge") {
    const { initSentry } = await import("./lib/sentry");
    initSentry();
  }
}

// Next.js 15 calls this. Next.js 14 ignores the export; it does not throw.
export const onRequestError = Sentry.captureRequestError;
