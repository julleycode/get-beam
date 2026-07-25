# Privacy Policy — Beam LinkedIn Outreach Connect

_Last updated: 2026-07-25_

This browser extension helps you connect your LinkedIn session to your Beam
dashboard so Beam can send LinkedIn outreach on your behalf. This policy explains
exactly what the extension reads, where it goes, and what it never does.

## What the extension reads

- **Your LinkedIn `li_at` session cookie**, only when you explicitly click
  "Connect with extension" (on your Beam dashboard) or "Connect now" (in the
  extension popup).
- **Your browser's User-Agent string**, sent alongside the cookie so LinkedIn
  outreach requests look consistent with your own browser.

The extension does not read any other cookies, browsing history, page content,
or data from any other site.

## Where that data goes

- The cookie and User-Agent are handed **only to your own open Beam dashboard
  tab**, over a locally-scoped browser message channel that is restricted to
  Beam's own origins. The extension never sends this data to any third-party
  server itself, and never contacts LinkedIn's servers.
- Your Beam dashboard then registers the session with Beam's outreach service
  using Beam's existing, unchanged backend. What happens to the cookie after
  that point is governed by **Beam's own privacy policy and Terms of Service**
  (https://getbeam.fyi/beam/privacy.html). Beam stores the session encrypted and
  never returns or displays it again.

## What the extension never does

- It **never logs** your cookie or User-Agent.
- It **never stores** them — no `localStorage`, no `chrome.storage`, no disk. The
  values live only in memory for the moment it takes to hand them to your Beam
  tab.
- It **never** transmits them to any origin other than your Beam dashboard.
- It requests **no** access to your browsing history, tabs' content, or any site
  other than LinkedIn (to read the cookie) and Beam (to hand it over).

## Permissions and why they are needed

- `cookies` — to read the LinkedIn `li_at` session cookie you choose to share.
- `host_permissions: *://*.linkedin.com/*` — the `li_at` cookie is HttpOnly and
  can only be read with host access to LinkedIn.
- `host_permissions` for Beam origins — to detect your own open Beam dashboard
  tab (for the popup path), scoped only to Beam's origins (this replaces the much
  broader `tabs` permission).
- `externally_connectable` (Beam origins only) — restricts which pages may open a
  message channel to the extension to Beam's own dashboard.

## Contact

Questions about this extension's data handling: use the support channel listed on
https://getbeam.fyi.
