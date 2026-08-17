/**
 * All onboarding chat copy, as DATA.
 *
 * Lines are PLAIN STRINGS, never HTML. The legacy static funnel built bubbles
 * with `innerHTML` and interpolated provider-supplied `full_name` /
 * `company_name` straight into the markup
 * (public/beam/onboarding-steps.js:394-407) — an XSS shape. React renders
 * these as text nodes, so the same class of bug cannot come back.
 *
 * Interpolation uses `{token}` placeholders resolved by `interpolate()`.
 */

import type { StepId } from "@/lib/onboarding-flow";

export interface Line {
  text: string;
  /** Larger/heavier first line of a step. */
  lead?: boolean;
  /** De-emphasised aside. */
  muted?: boolean;
  /** Explicit typing delay in ms; otherwise derived from length. */
  delay?: number;
}

export const SCRIPT: Record<StepId, Line[]> = {
  // Folded in from the deleted onboarding-welcome-chat.tsx (its three LINES),
  // which was the third copy of this conversation.
  welcome: [
    { text: "hey, i'm beam 👋", lead: true, delay: 500 },
    {
      text: "the stupidly easy way to know who's on your site, and engage them tastefully.",
    },
    { text: "let's get your first site connected. takes about a minute, ready?" },
  ],

  // ── the canary: the whole point of the flow ─────────────────────────────
  canary_go: [
    {
      text: "before you install anything, let me show you what beam does. i'm going to catch you.",
      lead: true,
    },
    {
      text: "open getbeam.fyi in a new tab, read a page or two, then come back here.",
    },
    {
      text: "beam's own pixel runs on that site, so this is a real catch — not a demo.",
      muted: true,
    },
  ],
  canary_listen: [{ text: "listening…", lead: true }],
  canary_reveal: [{ text: "got you.", lead: true }],
  confirm: [{ text: "is this you?", lead: true }],

  // ── the flow that ships today ───────────────────────────────────────────
  site: [
    { text: "what site should i watch?", lead: true },
    {
      text: "the url, a name to recognise it by, and — optional — a line about what you sell.",
      muted: true,
    },
  ],
  install: [
    { text: "nice. now the pixel.", lead: true },
    { text: "drop this snippet on {site} and i'll verify it from here." },
  ],
  done: [
    { text: "we're live.", lead: true },
    { text: "i'll start watching. head to the dashboard whenever you're ready." },
  ],
};

/**
 * The reveal's opening lines depend on whether the visit actually landed.
 *
 * NEVER FAKE A DETECTION. The legacy static funnel's non-sample branch called
 * `setTimeout(advance, 3600)` and then claimed a catch it never made
 * (public/beam/onboarding-steps.js:351). When nothing landed we say so, and
 * fall back to what the IP alone can honestly support.
 */
export const REVEAL_LANDED: Line[] = [{ text: "got you.", lead: true }];

export const REVEAL_GEO_ONLY: Line[] = [
  {
    text: "didn't catch your visit — adblocker, DNT/GPC (we honor both), or the tab never loaded.",
    lead: true,
  },
  // Byte-identical to onboarding-steps.js:446 — see the COPY SYNC FENCE.
  { text: "but here's what your connection alone says:" },
];

export function revealLines(landed: boolean): Line[] {
  return landed ? REVEAL_LANDED : REVEAL_GEO_ONLY;
}

/** Replace `{token}` placeholders. Unknown tokens are left untouched. */
export function interpolate(
  text: string,
  vars: Record<string, string | null | undefined> = {},
): string {
  return text.replace(/\{(\w+)\}/g, (whole, key: string) => {
    const value = vars[key];
    return value == null || value === "" ? whole : value;
  });
}

export function linesFor(
  step: StepId,
  vars: Record<string, string | null | undefined> = {},
): Line[] {
  return (SCRIPT[step] ?? []).map((line) => ({
    ...line,
    text: interpolate(line.text, vars),
  }));
}
