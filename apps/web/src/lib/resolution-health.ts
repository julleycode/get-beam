/**
 * Identity-provider health presentation rules.
 *
 * Pure, so it is unit-testable under the existing node-env vitest config (the
 * repo has no jsdom/testing-library setup, and this work does not add one).
 *
 * Unlike the rest of the dashboard, "dead" is NOT allowed to stay silent. A
 * provider returning `provider_unavailable` (401/403/402 — auth or quota, not a
 * no-match) writes no `resolution_logs` row at all, so it disappears from every
 * existing chart rather than showing up as a failure. That is precisely how the
 * 2026-08-06 rb2b + pdl outage ran four days with zero identified visitors and
 * zero alerts. Healthy and insufficient-data still render nothing.
 */

// Derived from the measured incident (production, 2026-08-11): rb2b and
// pdl_ip_enrich ran at 100% `provider_unavailable` on 8–34 calls/day from
// 2026-08-06 onward. A 50% ratio is far above anything a healthy provider
// produces (a healthy provider's failures are `no_match`, which is a real
// answer and never counts here), so the ratio alone is unambiguous.
export const UNAVAILABLE_RATIO_DEGRADED = 0.5;
// At 100% unavailable there is no plausible innocent explanation.
export const UNAVAILABLE_RATIO_DEAD = 1;

// Sample floor. The whole point is to trip inside ~one day, so this is set from
// the incident's own volume: the quietest incident day was 8 calls and the
// busiest 34. A floor of 10 means a 1-of-1 or 2-of-3 blip stays quiet, while the
// real outage trips on its FIRST day at the observed 16–44 calls/day site rate
// (the 8-call day would sit below the floor and wait one more day — still
// four days sooner than the silence this replaces).
export const UNAVAILABLE_MIN_CALLS = 10;

export type ProviderHealthStatus = "insufficient_data" | "healthy" | "degraded" | "dead";

export interface ProviderHealth {
  provider: string;
  calls: number;
  attempts: number;
  successes: number;
  unavailable: number;
  unavailable_rate: number; // 0..1
}

export function providerStatus(
  calls: number,
  unavailableRate: number
): ProviderHealthStatus {
  if (calls < UNAVAILABLE_MIN_CALLS) return "insufficient_data";
  if (unavailableRate >= UNAVAILABLE_RATIO_DEAD) return "dead";
  if (unavailableRate >= UNAVAILABLE_RATIO_DEGRADED) return "degraded";
  return "healthy";
}

/** Whether this provider should be surfaced at all. Healthy stays silent. */
export function providerIsUnhealthy(
  calls: number,
  unavailableRate: number
): boolean {
  const s = providerStatus(calls, unavailableRate);
  return s === "degraded" || s === "dead";
}

/** The providers worth showing, worst first. Empty = render nothing. */
export function unhealthyProviders(providers: ProviderHealth[]): ProviderHealth[] {
  return providers
    .filter((p) => providerIsUnhealthy(p.calls, p.unavailable_rate))
    .sort((a, b) => b.unavailable_rate - a.unavailable_rate);
}

export function providerMessage(p: ProviderHealth): string {
  const pct = Math.round(p.unavailable_rate * 100);
  switch (providerStatus(p.calls, p.unavailable_rate)) {
    case "dead":
      return `${p.provider} answered none of its ${p.calls} calls — every one failed on auth or quota, not a no-match. Check the provider's credentials and credit balance; until it is fixed this provider contributes nothing.`;
    case "degraded":
      return `${p.provider} failed ${pct}% of its ${p.calls} calls on auth or quota rather than returning a real answer. Check the provider's credentials and credit balance.`;
    case "insufficient_data":
      return `${p.provider} has only ${p.calls} calls in this window — too few to judge.`;
    default:
      return `${p.provider} is answering normally (${pct}% unavailable across ${p.calls} calls).`;
  }
}

/** One-line site-level summary, or null when everything is fine. */
export function resolutionHealthSummary(
  providers: ProviderHealth[]
): string | null {
  const bad = unhealthyProviders(providers);
  if (bad.length === 0) return null;
  const names = bad.map((p) => p.provider).join(", ");
  return bad.length === 1
    ? `Identity provider down: ${names}`
    : `${bad.length} identity providers down: ${names}`;
}
