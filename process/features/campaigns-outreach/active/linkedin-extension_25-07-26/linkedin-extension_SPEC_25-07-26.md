---
name: plan:linkedin-extension-spec
description: "Product-discovery SPEC for a Chrome/Edge browser extension that replaces manual DevTools cookie-copy with one-click LinkedIn outreach connect, feeding the existing dashboard flow — no backend change"
date: 25-07-26
feature: campaigns-outreach
---

# LinkedIn Outreach Connect Extension — SPEC

## Summary

Today, turning on "LinkedIn outreach" in Beam requires a user to open their browser's developer
tools, find a cookie named `li_at` under Application → Cookies, copy its value, and paste it into
a form on the Beam dashboard. This is a DevTools-literate task and a real drop-off point for
non-technical founders — the exact audience Beam is built for. This SPEC covers a Chrome/Edge
browser extension that does the same job with one click: the extension reads the cookie itself
(something only an extension can do, because the cookie is deliberately hidden from web pages),
and hands it to the already-open Beam dashboard tab, which sends it to the backend exactly the way
the manual form does today. Nothing about the backend, the risk profile, or the LinkedIn ToS
warning changes — only how the value gets from the user's browser into Beam.

## User Stories / Jobs To Be Done

1. **As a non-technical Beam user**, I want to click one button to connect my LinkedIn account for
   outreach, so that I don't have to learn DevTools just to turn on a feature.
2. **As a returning user whose LinkedIn session has expired**, I want an obvious way to refresh the
   connection with one click, so that outreach doesn't silently stop working without me knowing why.
3. **As a cautious user**, I want to understand exactly what the extension can see and send before I
   install it, so that I can trust it isn't doing anything beyond what the dashboard form already did.
4. **As a user who hasn't installed the extension**, I want the dashboard to still work with the
   existing manual copy-paste flow, so that the extension is a convenience, not a requirement.
5. **As a user browsing on Firefox or Safari**, I want a clear message that the extension isn't
   available there yet, rather than a broken or confusing button, so I fall back to the manual flow
   without frustration.

## What The User Wants (Behavioral Outcomes)

- A user who has the extension installed sees a "Connect with extension" option on the LinkedIn
  outreach card (Connected Accounts page) instead of only the manual cookie-paste form.
- Clicking that option: the user is signed into linkedin.com in the same browser, and Beam's
  dashboard tab is open — after clicking, the outreach card updates to "connected" within a few
  seconds, with no copy-pasting and no DevTools.
- If the user is not logged into LinkedIn, the extension tells them so and points them to log in
  first — it does not silently fail or send an empty cookie.
- If the user does not have the Beam dashboard tab open, the flow tells the user to open the
  dashboard (the extension cannot act without it, by design — see Locked Decision #1).
  extension can react (e.g. via the extension's own popup) but the transfer of the cookie into
  Beam still requires the dashboard tab.
- A user without the extension installed sees no change: the existing manual cookie-paste form
  keeps working exactly as it does today.
- The existing LinkedIn ToS warning banner is shown (or repeated) at extension-connect time too —
  the user is not shown a "lighter" risk disclosure just because the click is easier.
- Reconnecting (refreshing an expired session) uses the same one-click flow — the user does not
  need to go find the cookie again after the extension is installed.
- The extension, once installed, never sends the cookie anywhere except the Beam dashboard tab/origin
  it detects is open — this is invisible to the user by design, but is a hard behavioral guarantee,
  not an implementation detail (see Security/ToS Constraints).

## Flow / State Diagram

Happy path — extension installed, one-click connect:

```
 [User on Beam dashboard: Connected Accounts page]
              |
              v
   Extension detected? --no--> [Show existing manual cookie-paste form only]
              |
             yes
              v
   [Show "Connect with extension" button next to manual form]
              |
        user clicks
              v
   [Extension reads li_at cookie + User-Agent
    from *.linkedin.com via chrome.cookies API]
              |
    +---------+----------+
    |                     |
 cookie found        cookie NOT found
    |                     |
    v                     v
[Hand cookie + UA    [Show inline message:
 to the open Beam     "You're not signed into
 dashboard tab via    LinkedIn — sign in at
 content script /     linkedin.com, then try
 postMessage]         again"]
    |
    v
[Dashboard tab verifies message came from the
 known extension id, then calls the SAME existing
 POST /api/v1/social/accounts/linkedin/outreach-connect
 the manual form already calls]
    |
    v
[Backend responds — dashboard shows the SAME
 success/failure UI the manual flow already has]
    |
    v
[Outreach card shows "connected" / verified name]
```

Re-connect / refresh path (session expired):

```
[Outreach card shows "connected" but server marks it stale/expired]
       |
       v
[Same "Connect with extension" button, now labeled "Refresh connection"]
       |
       v
(same happy path as above — one click, no cookie hunting)
```

Extension-not-usable branches:

```
Dashboard tab not open in this browser
       |
       v
[Extension has nothing to hand the cookie to — user is told
 "Open your Beam dashboard tab in this browser, then click again"]

Non-Chromium browser (Firefox/Safari)
       |
       v
[No extension available — page shows only the existing manual
 cookie-paste form; no broken "install" prompt for unsupported browsers]

Handshake fails (message not recognized as coming from the extension)
       |
       v
[Dashboard silently ignores it — treated as if the button was
 never clicked, no partial/fake "connected" state]
```

## Acceptance Criteria (Testable Outcomes)

1. **A user with the extension installed and logged into LinkedIn can connect LinkedIn outreach in
   one click from the dashboard, with the same end state (outreach card shows connected, verified
   name if available) as the existing manual cookie-paste flow.**
   proven by: dashboard e2e flow test that loads the unpacked extension into a Playwright
   Chromium context, seeds a fake `li_at` cookie on a mocked linkedin.com origin, opens the
   dashboard, clicks connect, and asserts the outreach card reaches "connected."
   strategy: Hybrid (Playwright supports loading unpacked MV3 extensions into a persistent
   context; the LinkedIn cookie origin and backend call are mocked/stubbed, so this is largely
   automated with one external-realism gap — see Open Questions).

2. **The backend endpoint contract is unchanged: the extension-driven flow calls the exact same
   `POST /api/v1/social/accounts/linkedin/outreach-connect` request/response shape the manual form
   uses today, with no new endpoint, auth mechanism, or CORS rule.**
   proven by: existing backend integration test suite for `social_accounts.py` (outreach-connect,
   outreach-status) continues to pass unmodified; a diff-based check confirms no router/schema
   changes were required for this feature.
   strategy: Fully-Automated (pytest integration lane, already-existing coverage — this criterion
   is proven by absence of required backend changes, verified via git diff + regression run).

3. **A user who is not signed into LinkedIn sees a clear, specific message telling them to sign in
   first — the extension never silently sends an empty or missing cookie to the dashboard.**
   proven by: extension unit/integration test that stubs `chrome.cookies.get` to return `null` for
   `li_at` and asserts the extension surfaces a "not signed in" state instead of invoking the
   dashboard handoff.
   strategy: Fully-Automated (extension-side unit test against the mocked `chrome.cookies` API,
   mirroring the mock-mode pattern used elsewhere in the codebase).

4. **A user without the Beam dashboard tab open in the same browser is told to open it — the
   extension does not fail silently or claim success without a receiving tab.**
   proven by: extension test that simulates zero matching `getbeam.fyi` tabs and asserts a
   "open your dashboard" message is shown, with no success state reached.
   strategy: Fully-Automated (extension-side test using the mocked `chrome.tabs` query API).

5. **The cookie value is never transmitted to any origin other than the legitimate Beam dashboard
   origin (getbeam.fyi and configured dev/staging origins) — this is enforced structurally, not
   just by convention.**
   proven by: a security-focused test that installs the extension with a spoofed/malicious page
   claiming to be the dashboard origin and asserts the extension's `host_permissions` /
   `externally_connectable` (or equivalent messaging target) configuration rejects it; plus a
   manifest review checklist confirming `host_permissions` is scoped to `*.linkedin.com` (cookie
   read) and the message target is scoped to the Beam origin only.
   strategy: Hybrid (automated manifest/config assertion + a scripted attempt to message from a
   disallowed origin in a Playwright test; full adversarial red-team coverage is out of scope for
   v1 and flagged as a residual manual/agent-probe check before Chrome Web Store submission).

6. **The dashboard only accepts an extension-originated connect message if it can verify the
   message came from the known, expected extension id — a copy-cat extension or a malicious page
   cannot trigger the same flow.**
   proven by: dashboard-side test that sends a postMessage/content-script event with a wrong or
   missing origin/sender id and asserts the dashboard takes no action (no API call fired).
   strategy: Fully-Automated (unit/integration test on the dashboard's message-listener logic).

7. **The LinkedIn ToS risk warning is shown to the user at the moment they use the extension-based
   connect flow — it is not skipped just because the click is easier than the manual form.**
   proven by: e2e/component test asserting the warning banner text is present and visible on the
   outreach card regardless of which connect method (manual or extension) is used.
   strategy: Fully-Automated (component/e2e assertion on existing banner markup, extended to cover
   the new button).

8. **The cookie value and User-Agent are never written to any log, error message, or client-side
   storage (e.g. `localStorage`, `chrome.storage`) by the extension or the dashboard — matching the
   existing "Beam never keeps a copy" guarantee in the manual flow.**
   proven by: static/manifest review plus a runtime test asserting no `chrome.storage` write calls
   occur during the connect flow, and a grep-based check that no new logger call in the touched
   dashboard/router code includes the cookie or UA value.
   strategy: Hybrid (automated grep/static check + one scripted runtime assertion in the Playwright
   extension test).

9. **A user on Firefox or Safari sees the existing manual cookie-paste form with no broken
   "extension not detected" UI artifact or dead install button — v1 has no Firefox/Safari
   extension.**
   proven by: e2e test that simulates the extension-detection check returning "not present" and
   asserts only the pre-existing manual form renders, with no extension-specific UI shown.
   strategy: Fully-Automated (Playwright test without the extension loaded — the normal/default
   case for the existing test suite).

10. **Reconnecting an expired LinkedIn session (refresh) uses the identical one-click extension flow
    as the first-time connect — no separate "refresh" code path with different security or
    permission behavior.**
    proven by: e2e test that seeds an existing "connected but stale" outreach account, clicks the
    refresh-labeled button, and asserts it exercises the exact same extension message flow and
    backend call as criterion 1.
    strategy: Hybrid (same Playwright extension harness as criterion 1, reused for the refresh
    state).

## Out Of Scope

- **Firefox and Safari support.** V1 targets Chrome and Edge (Chromium MV3) only; Firefox uses a
  different extension manifest model and is not part of this SPEC.
- **A standalone extension-only flow that doesn't need the dashboard tab open.** The extension is a
  "dumb pipe" to the dashboard by locked architectural decision — it does not independently call
  the Beam backend or hold its own auth.
- **Automatic/background refresh of an expiring LinkedIn cookie without user action.** The
  extension only acts on an explicit user click; there is no silent background re-scrape of the
  cookie.
- **Any other social platform's cookie/session capture** (Twitter, Facebook, Instagram, TikTok
  already use OAuth and are unaffected).
- **Any new backend endpoint, schema change, or CORS allowlist change.** The backend contract is
  reused unchanged (Locked Decision #2).
- **Publishing to the Chrome Web Store as a v1 deliverable** — see Open Questions; v1 may ship as a
  loadable "unpacked" developer build with store submission deferred to a follow-up.
- **Removing or replacing the existing manual DevTools cookie-paste form.** It remains as the
  fallback for users without the extension or on unsupported browsers.

## Constraints

- **Architecture is locked**: extension reads `li_at` (via `chrome.cookies`) + `navigator.userAgent`,
  hands both to the already-open Beam dashboard tab (content script / `postMessage`); the extension
  itself never holds a Clerk JWT and never calls the Beam API directly.
- **Backend contract is locked and unchanged**: `POST /api/v1/social/accounts/linkedin/outreach-connect`
  (`{session_cookie, user_agent, label?}` + `Authorization: Bearer <clerk-jwt>`) and
  `GET /api/v1/social/accounts/linkedin/outreach-status`, both exactly as implemented today
  (`apps/api/routers/social_accounts.py`).
- **Browser scope is locked**: Chrome + Edge (Chromium MV3) only for v1.
- **No new public backend endpoint, pairing table, or CORS allowlist change** is permitted for this
  feature — the whole point of the "dumb pipe" architecture is to avoid all three.
- `li_at` is an HttpOnly cookie — this is precisely why an extension (not page JavaScript) is
  required; the constraint is a technical fact, not a design choice up for revisiting.
- The extension must request the minimum permission set needed: `cookies` +
  `host_permissions` scoped to `*.linkedin.com` (to read the cookie), plus whatever mechanism is
  chosen to detect/message the Beam dashboard tab, scoped to the Beam origin only. No broad
  `<all_urls>` permission.
- The existing LinkedIn ToS risk-acceptance warning currently shown on the manual form must be
  preserved and shown for the extension flow too — this is a business guardrail, not negotiable.
  Beam's "never auto-send" outreach guardrail is unaffected — this feature only changes how a
  cookie gets from the browser to the dashboard, not any send-approval logic.
- Cookie and User-Agent values must never be logged, stored client-side, or persisted anywhere
  outside the existing backend flow's storage.

## Open Questions

1. **Extension popup button vs. in-page "Connect with extension" button on the social-accounts
   page — which is the primary trigger?** Owner: INNOVATE. (The flow diagram above assumes an
   in-page button that appears once the extension is detected, but the extension's own popup could
   also carry a "Connect now" action; INNOVATE should compare these against the detection mechanism
   chosen.)
2. **How does the dashboard page detect the extension is installed** (to decide whether to show the
   "Connect with extension" button at all)? Owner: INNOVATE/PLAN. Candidate mechanisms: a
   content-script-injected marker, `externally_connectable` + a probe message, or a well-known DOM
   attribute — all are implementation choices, not requirements decisions.
3. **Is Chrome Web Store submission in scope for v1, or does v1 ship only as a loadable "unpacked"
   developer build** (distributed via internal instructions, not the public store)? Owner: user
   confirmation before PLAN — this materially affects timeline (store review can take days) and
   whether the extension needs to satisfy Chrome Web Store's permission-justification review
   requirements immediately vs. later.
4. **Where does the extension source live** — a new `apps/extension/` directory mirroring
   `apps/pixel/`'s structure, or elsewhere? Owner: PLAN (this is a repo-layout decision, not a
   product requirement, but flagged here since RESEARCH raised it).
5. **What exact realism gap exists in the Playwright extension test harness for criterion 1** (can a
   real `li_at` cookie be reliably simulated against a mocked linkedin.com origin inside a loaded
   MV3 extension context, or does the automated coverage stop short of the real `linkedin.com` cookie
   read and require one documented manual/agent-probe verification step before ship)? Owner:
   VALIDATE — flagged as a feasibility question for the validate phase rather than answered here,
   since it depends on Playwright's actual MV3 extension support behavior, not on product intent.

None of these open questions block understanding *what* the user wants (the requirements in this
SPEC are unambiguous); they are implementation-shape and scope-boundary decisions appropriately
deferred to INNOVATE/PLAN/VALIDATE.

## Background / Research Findings

- **Manual flow today** (`apps/web/src/app/dashboard/social-accounts/page.tsx`): a "LinkedIn
  outreach (Advanced)" card with a textarea for the `li_at` cookie, an auto-filled but editable
  User-Agent field, an inline "how to find your login key" DevTools walkthrough, a ToS warning
  banner, and a submit button that calls `api.enableLinkedInOutreach(cookie, userAgent)`. This is
  the drop-off point the extension exists to remove — the DevTools walkthrough itself is evidence
  the manual flow assumes a technical user.
- **Backend contract** (`apps/api/routers/social_accounts.py:118` `connect_linkedin_outreach`,
  `:199` `linkedin_outreach_status`): accepts `{session_cookie, user_agent, label?}`, forwards the
  cookie to the `PhantommmClient` sidecar (which stores it encrypted — Beam itself never persists
  the raw cookie, only an opaque `outreach_connection_id`), optionally verifies the connection to
  get a display name, and upserts a `SocialAccount` row. Status endpoint reports `outreach_connected`
  and whether the server has outreach `configured` at all (via `PHANTOMMM_*` env). None of this
  needs to change — the extension is purely a new way to fill in the same two form fields.
  Explicit `logger.info(...connection_id_present=True...)` calls show existing discipline never to
  log the cookie — the extension must uphold the same discipline on the client side.
  Also explicitly noted in the backend docstring: "Beam NEVER stores the raw LinkedIn cookie."
- **`li_at` is HttpOnly**, meaning ordinary page JavaScript on getbeam.fyi cannot read it under any
  circumstance — only a browser extension with the `cookies` permission and `host_permissions` for
  `*.linkedin.com` can read it. This is the extension's entire reason to exist; it is not a
  convenience wrapper around something the page could already do.
  the `document.cookie` read
- **Locked architecture** ("dumb pipe to dashboard tab"): decided by the user + orchestrator after
  RESEARCH specifically to avoid a new backend endpoint, a pairing table, or a CORS allowlist
  change — the extension never authenticates to the Beam API on its own; it only ever hands data to
  a tab that already holds a valid Clerk session.
- **No prior extension code exists in the repo.** `apps/pixel/` (vanilla JS tracker + esbuild build
  + Playwright e2e) is the closest structural precedent for build/test tooling, but is not itself a
  browser extension — it is a website tracking script.
- **Security posture from RESEARCH**: the extension's trust boundary is two-directional — (a) the
  extension must only ever send the cookie to the legitimate Beam dashboard origin, never an
  impersonating page, and (b) the dashboard must verify inbound messages actually come from the
  real Beam extension (by extension id / origin), not an arbitrary web page trying to spoof the same
  message shape. Both directions are captured as acceptance criteria 5 and 6 above.
- **LinkedIn ToS risk is already accepted** by the existing manual flow (visible warning banner);
  the extension is a UX change, not a new risk class, and must not present a "lighter" version of
  that warning.
- **User + orchestrator locked decisions** (verbatim, not reopened by this SPEC): dumb-pipe
  architecture; fixed/reused backend contract; Chrome + Edge only; no new backend surface.
