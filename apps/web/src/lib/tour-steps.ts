// Data-driven steps for the dashboard onboarding tour. Content lives here,
// separate from the OnboardingTour component logic, so copy can be edited
// without touching the spotlight/positioning code.
//
// `target` is the `data-tour` attribute on the matching desktop sidebar nav
// link (see NavLink in app/dashboard/layout.tsx). `null` = a centered card with
// no spotlight (intro/outro). `adminOnly` steps are filtered out for non-admins,
// mirroring the nav's own adminOnly filtering.

export type TourStep = {
  id: string;
  target: string | null;
  title: string;
  body: string;
  adminOnly?: boolean;
};

export const TOUR_STEPS: TourStep[] = [
  {
    id: "welcome",
    target: null,
    title: "Welcome to Beam",
    body: "A quick 1-minute tour of what each section does. You can replay it anytime from the Help button in the sidebar.",
  },
  {
    id: "overview",
    target: "overview",
    title: "Overview — your home base",
    body: "Site-wide intent, capture health, and recent activity at a glance.",
  },
  {
    id: "visitors",
    target: "visitors",
    title: "Visitors — who's on your site",
    body: "Every captured visitor with an intent score. Identify and enrich high-intent people here.",
  },
  {
    id: "agents",
    target: "agents",
    title: "Agents — AI crawlers on your site",
    body: "Visits from AI agents like GPTBot, ClaudeBot and PerplexityBot — tracked separately from human visitors, never as a contactable lead.",
  },
  {
    id: "segments",
    target: "segments",
    title: "Segments — group your audience",
    body: "Build segments from behavior and identity so you can target the right people.",
  },
  {
    id: "campaigns",
    target: "campaigns",
    title: "Campaigns — reach them",
    body: "Turn segments into email and social touchpoints. Nothing sends without your approval.",
  },
  {
    id: "connectors",
    target: "connectors",
    title: "Connectors — move your data",
    body: "Export segments as CSV for ad platforms, push identified visitors into your CRM, and import known contacts — all in one place.",
  },
  {
    id: "feed",
    target: "feed",
    title: "EasyEngage — social content",
    body: "Feed, Drafts, and Social Accounts: draft, review, and publish social posts in one place.",
  },
];
