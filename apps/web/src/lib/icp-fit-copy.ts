/**
 * ICP-fit display copy.
 *
 * The ONLY sanctioned bridge between the backend's `icp_fit` number and text
 * rendered in the dashboard. Mirrors `apps/api/services/icp_fit.py`'s band
 * thresholds and vocabulary.
 *
 * COPY CONTRACT: every string this module can emit is a compile-time constant.
 * Nothing derived from `site_profile` — persona roles, industries, size bands,
 * category — is ever interpolated. `site_profile` is LLM output generated from
 * fetched third-party page content, so it is untrusted DISPLAY text, not merely
 * untrusted prompt text. Keeping the builder pure and constant-only is what
 * makes that guarantee testable (see `icp-fit-copy.test.ts`).
 */

/** Fixed band vocabulary — mirrors VERDICT_BANDS in services/icp_fit.py. */
export const ICP_FIT_BANDS = [
  "strong ICP fit",
  "partial ICP fit",
  "weak ICP fit",
] as const;

export type IcpFitBand = (typeof ICP_FIT_BANDS)[number];

const STRONG_FIT_AT = 70;
const PARTIAL_FIT_AT = 40;

/** Band label for a score, or null when the visitor is unscored. */
export function icpFitBand(score: number | null | undefined): IcpFitBand | null {
  if (score === null || score === undefined || Number.isNaN(score)) return null;
  if (score >= STRONG_FIT_AT) return ICP_FIT_BANDS[0];
  if (score >= PARTIAL_FIT_AT) return ICP_FIT_BANDS[1];
  return ICP_FIT_BANDS[2];
}

/** Chip label, e.g. "strong ICP fit · 82". Null when unscored. */
export function icpFitLabel(score: number | null | undefined): string | null {
  const band = icpFitBand(score);
  if (band === null) return null;
  return `${band} · ${Math.round(score as number)}`;
}

/**
 * Tooltip text. Constant prose plus the score number — deliberately says
 * nothing about WHICH persona or industry matched, because that text is
 * LLM-authored and must never reach the browser.
 */
export function icpFitTooltip(score: number | null | undefined): string | null {
  const band = icpFitBand(score);
  if (band === null) return null;
  return (
    `Reads as a ${band} (${Math.round(score as number)} of 100). ` +
    "Computed from your reviewed ideal-customer profile — the visitor's role, " +
    "company details and country, scored against the profile you approved in " +
    "site settings. Dimensions with no data are skipped, not counted against them."
  );
}
