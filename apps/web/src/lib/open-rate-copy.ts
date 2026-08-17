/**
 * Open-rate display copy.
 *
 * The ONLY sanctioned bridge between a backend open-rate number and text
 * rendered in the dashboard. Mirrors `OPEN_RATE_CAVEAT` in
 * `apps/api/services/campaign_stats.py`.
 *
 * TWO HONESTY RULES, enforced here rather than at each call site:
 *
 * 1. **No sends is not a measured zero.** A campaign that sent nothing has an
 *    open rate of `null`, and this module renders "no data" for it — never
 *    "0%". "0% open rate" is a claim about a measurement that never happened.
 * 2. **Every open-rate value carries the unreliability caveat.** Apple Mail
 *    Privacy Protection prefetches tracking pixels (overcounting) and blocked
 *    images suppress them (undercounting), so clicks are the reliable signal.
 *    Surfaces must place the caveat next to the value, not bury it.
 *
 * COPY CONTRACT: every string this module emits is a compile-time constant or a
 * formatted number. Nothing tenant-authored is ever interpolated.
 */

/** Verbatim mirror of `OPEN_RATE_CAVEAT` in services/campaign_stats.py. */
export const OPEN_RATE_CAVEAT =
  "Open rates are unreliable: Apple Mail Privacy Protection prefetches " +
  "tracking pixels (overcounting) and blocked images suppress them " +
  "(undercounting). Clicks are the reliable signal.";

/** Shown in place of a percentage when the campaign sent nothing. */
export const NO_DATA_LABEL = "No sends yet";

/**
 * Format an open rate for display. `null`/`undefined` means "never measured"
 * and renders as {@link NO_DATA_LABEL}, NOT as "0.0%".
 */
export function openRateLabel(rate: number | null | undefined): string {
  if (rate === null || rate === undefined || Number.isNaN(rate)) {
    return NO_DATA_LABEL;
  }
  return `${(rate * 100).toFixed(1)}%`;
}

/**
 * The benchmark comparison sentence. Always a pooled category AVERAGE (mean) —
 * the backend schema stores sums plus a tenant count, which cannot yield a
 * median, so the word "median" must never appear here.
 *
 * No period-over-period delta is ever rendered: near the k-anonymity floor,
 * differencing consecutive periods can narrow an individual tenant's numbers.
 */
export function benchmarkComparisonLabel(
  category: string,
  siteOpenRate: number | null | undefined,
  categoryOpenRate: number,
): string {
  const readableCategory = category.replace(/_/g, " ");
  return (
    `Your open rate is ${openRateLabel(siteOpenRate)} against a ` +
    `${openRateLabel(categoryOpenRate)} category average for ` +
    `${readableCategory} sites.`
  );
}

/** Panel heading — says campaign/segment, never "subject" (ranking by subject
 * line is a named deferral and no subject text is read anywhere). */
export const WHATS_WORKING_TITLE = "What's working";
export const WHATS_WORKING_SUBTITLE =
  "Your best-performing campaigns and segments this period, ranked by conversions.";
