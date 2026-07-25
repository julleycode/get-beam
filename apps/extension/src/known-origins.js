// Shared constants for the Beam LinkedIn Outreach Connect extension.
//
// KEEP IN SYNC with the dashboard-side mirror in
// apps/web/src/app/dashboard/social-accounts/page.tsx (BEAM_ORIGINS /
// KNOWN_EXTENSION_ID). These two apps are separate build/deploy targets with no
// shared-package plumbing, so the values are deliberately duplicated, not
// imported (see plan "Blast Radius note — why known-origins.js is duplicated").

// The Chrome Web Store assigns the real extension id only on first upload
// (even a draft). Until then this placeholder is used; the dashboard's
// chrome.runtime.sendMessage(KNOWN_EXTENSION_ID, ...) call hardcodes the same
// value. Replace both on store-listing creation (plan OI-4 / Step 9).
export const KNOWN_EXTENSION_ID = "PENDING_STORE_LISTING";

// Beam dashboard origins the extension is allowed to talk to. Must match the
// manifest's host_permissions / externally_connectable / content_scripts.
// Prod + local dev only for v1. Add the staging origin here AND in the manifest
// AND in the dashboard mirror if/when a staging hostname is finalized.
export const BEAM_ORIGINS = ["https://getbeam.fyi", "http://localhost:3000"];

// Match-pattern form of BEAM_ORIGINS for chrome.tabs.query({url: ...}).
export const BEAM_ORIGIN_PATTERNS = ["https://getbeam.fyi/*", "http://localhost:3000/*"];

// LinkedIn URL the session cookie is read against.
export const LINKEDIN_COOKIE_URL = "https://www.linkedin.com";
export const LINKEDIN_COOKIE_NAME = "li_at";

// postMessage discriminator for the D7 popup relay channel. Public/known — the
// nonce (not this string) is the actual anti-forgery control (plan D10/OI-3).
export const MESSAGE_SOURCE = "beam-extension";
