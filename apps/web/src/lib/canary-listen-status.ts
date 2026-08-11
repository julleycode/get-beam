/**
 * Timing and copy for the "listening…" beat — pure, because the whole point of
 * this module is that the escalation schedule is testable without waiting 90
 * real seconds.
 *
 * `apps/web/vitest.config.ts` is `environment: "node"` with no jsdom, so these
 * decisions cannot live in the component (see the plan's "Logic lives in
 * src/lib" constraint).
 */

/**
 * 90 seconds, not the legacy static funnel's 15
 * (public/beam/onboarding-steps.js:333). The user has to open a tab, actually
 * read something, and come back — 15s only ever measured page-load time, which
 * is why the legacy flow had to fake the catch.
 */
export const LISTEN_DEADLINE_MS = 90_000;

/**
 * Poll cadence. 2s for the full 90s would be 45 calls against the endpoint's
 * 30/minute limit — a 429 in the middle of the reveal. Backing off to 4s after
 * 20s lands at ~27 calls, inside the budget with headroom.
 */
export const POLL_FAST_MS = 2_000;
export const POLL_SLOW_MS = 4_000;
export const POLL_BACKOFF_AFTER_MS = 20_000;

/** A dormant endpoint (server flag off → 404) resolves in ~3 polls, not 90s. */
export const MAX_CONSECUTIVE_ERRORS = 3;

export function pollIntervalFor(elapsedMs: number): number {
  return elapsedMs < POLL_BACKOFF_AFTER_MS ? POLL_FAST_MS : POLL_SLOW_MS;
}

/**
 * Escalating status copy. An unchanging "listening…" for 60 seconds reads as a
 * hang; naming the likely cause at each stage keeps it a conversation and gives
 * the user something to act on.
 */
export function statusFor(elapsedMs: number): string {
  if (elapsedMs < 8_000) return "listening…";
  if (elapsedMs < 25_000) return "open a page on getbeam.fyi…";
  if (elapsedMs < 60_000) return "still listening — did the tab actually load?";
  return "one more moment…";
}
