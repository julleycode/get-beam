/**
 * Privacy opt-out presentation rules for the browser-capture card.
 *
 * Pure, so it is unit-testable under the existing node-env vitest config (the
 * repo has no jsdom/testing-library setup, and this work does not add one).
 *
 * The card's philosophy is "healthy stays silent": an opt-out figure is always
 * available per browser, but the site-level indicator only appears when the
 * rate is genuinely abnormal against the measured production baseline.
 */

// Measured 2026-08-10 on production: ~5.9% of visitors carry the sticky
// `do_not_resolve` flag, per-site range 2.8%–21.7%. "Elevated" starts above the
// observed per-site range; "high" is well beyond it.
export const OPTOUT_BASELINE = 0.059;
export const OPTOUT_ELEVATED = 0.1;
export const OPTOUT_HIGH = 0.25;

// Below this many visitors the rate is noise — a 1-of-3 opt-out is 33%.
export const OPTOUT_MIN_SAMPLE = 50;

export type OptoutStatus = "insufficient_data" | "ok" | "elevated" | "high";

export function optoutStatus(
  visitors: number,
  rate: number
): OptoutStatus {
  if (visitors < OPTOUT_MIN_SAMPLE) return "insufficient_data";
  if (rate >= OPTOUT_HIGH) return "high";
  if (rate >= OPTOUT_ELEVATED) return "elevated";
  return "ok";
}

/** Whether the site-level warning indicator should render at all. */
export function optoutIsAbnormal(visitors: number, rate: number): boolean {
  const s = optoutStatus(visitors, rate);
  return s === "elevated" || s === "high";
}

export function optoutMessage(visitors: number, rate: number): string {
  const p = Math.round(rate * 100);
  switch (optoutStatus(visitors, rate)) {
    case "insufficient_data":
      return `Need at least ${OPTOUT_MIN_SAMPLE} visitors to read the opt-out rate reliably.`;
    case "high":
      return `${p}% of visitors send a Do-Not-Track / Global Privacy Control signal, so they are never resolved. That is well above the ~6% we see typically — it caps how high your identification rate can go.`;
    case "elevated":
      return `${p}% of visitors send a Do-Not-Track / Global Privacy Control signal, so they are never resolved. Typical is ~6%. Check the per-browser figures — Firefox and Opera send it far more often than Chrome.`;
    default:
      return `${p}% of visitors opt out of resolution — in line with the ~6% we see typically.`;
  }
}
