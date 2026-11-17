---
name: plan:linkedin-extension-onboarding-spec
description: "Product-discovery SPEC for a guided 4-step onboarding wizard that walks a non-technical user through installing and connecting the Beam LinkedIn extension — auto-advancing, tab-switch-aware, dialog-hosted, launched from the existing Connected Accounts card"
date: 26-07-26
feature: campaigns-outreach
---

# LinkedIn Extension Onboarding Wizard — SPEC

## Summary

The Beam LinkedIn outreach extension works, but nobody is shown how to set it up. Today the
Connected Accounts page only shows a "Connect with extension" button if the extension happens to
already be installed — there is no explanation of what the extension is, no path to install it, no
handling for "you're not signed into LinkedIn yet," and no feedback while any of that is in
progress. This SPEC covers a guided, 4-step onboarding wizard — hosted in a dialog, launched from a
button on the LinkedIn outreach card — that walks a non-technical user through browser check →
install → LinkedIn sign-in → connect, automatically detecting and advancing through each step as
the user completes it (including after they switch away to another tab and come back), so a founder
who has never opened DevTools can get LinkedIn outreach working without reading a manual.

## User Stories / Jobs To Be Done

1. **As a non-technical user who has never installed the extension**, I want a step-by-step guide
   that tells me exactly what to click next, so that I can turn on LinkedIn outreach without asking
   for help or hunting through settings myself.
2. **As a user who installs the extension mid-flow**, I want the wizard to notice I've installed it
   and move me to the next step automatically when I come back to the dashboard tab, so that I don't
   have to click a "check again" button or re-read instructions.
3. **As a user who isn't signed into LinkedIn yet**, I want the wizard to send me to sign in and then
   pick up right where I left off when I return, so that signing in feels like part of the flow, not
   a dead end.
4. **As a user on Firefox or Safari**, I want the wizard to tell me clearly that the extension isn't
   available on my browser and point me to the existing manual option, so that I'm not shown an
   install button that can never work for me.
5. **As a user who already has the extension installed and is already signed into LinkedIn**, I want
   the wizard to recognize that and skip straight to the final connect step, so I never have to click
   through steps that are already done.
6. **As a returning user whose LinkedIn session has expired**, I want the same guided wizard to walk
   me through reconnecting, so refreshing access doesn't feel different or scarier than the first
   time.
7. **As a cautious user**, I want to see, before I install anything, a plain-language explanation of
   what the extension can see and do (and what it can't), so I can decide to trust it with confidence
   — not just take it on faith.

## What The User Wants (Behavioral Outcomes)

- A clearly visible button on the LinkedIn outreach card opens a step-by-step dialog ("Connect
  LinkedIn" wizard) instead of the user being expected to already understand the extension.
- The wizard shows exactly 4 steps in order: (1) browser check, (2) install extension, (3) sign into
  LinkedIn, (4) connect. The user always knows which step they're on and what's left.
- Any step whose condition is already true is skipped automatically — a user who already has the
  extension installed and is already signed into LinkedIn is dropped straight at step 4, not forced
  to click through steps 1–3.
- Steps 2 and 3 each open a new browser tab (Chrome Web Store, linkedin.com) and tell the user to
  come back when they're done — the user never has to manually confirm completion by clicking a
  "check again" button. The wizard notices the state changed when the user returns to the dashboard
  tab (whether by switching tabs or closing the opened tab and coming back) and advances itself.
- On an unsupported browser (Firefox/Safari), step 1 becomes a dead end with a clear explanation and
  a path to the existing manual `li_at` paste form — there is no broken "Install" button shown.
- The final connect step shows the same LinkedIn ToS risk warning already shown on the manual form —
  never a "lighter" version just because the click is easier.
- On success, the wizard shows a clear "connected" state (including the verified account name when
  the backend returns one) and can be closed; the outreach card behind it reflects the same
  connected state.
- Before the user installs anything, the wizard tells them in plain language what the extension can
  see (their LinkedIn login session) and what it does with it (hands it once to the Beam dashboard
  tab to connect outreach) — and states plainly what it does NOT do (it doesn't read other sites, it
  doesn't post on the user's behalf automatically, Beam never keeps a copy of the raw session).
- The existing manual `li_at` paste form is never removed. It stays reachable — collapsed and
  de-emphasized — as a fallback from inside the wizard (for any step) and outside it (for users who
  never open the wizard, and always for Firefox/Safari users).
- A user reconnecting an expired session goes through the same 4-step wizard, not a separate/lesser
  "refresh" experience — steps that are already satisfied (browser, extension, LinkedIn sign-in) are
  auto-skipped so the returning user typically lands straight on step 4.

## Flow / State Diagram

```
[User clicks "Connect LinkedIn" on the outreach card]
                    |
                    v
        ┌─────────────────────────┐
        │  STEP 1 — Browser check │
        └─────────────────────────┘
                    |
       Chrome/Edge? ─────────── no ──────────────┐
                    |                             v
                   yes                 [Dead end: "Extension isn't
                    |                    available on this browser
             (auto-advance)              yet." + link to manual
                    |                    paste form. Wizard stops
                    v                    here for this browser.]
        ┌─────────────────────────┐
        │ STEP 2 — Install ext.   │
        │ "Already installed?"    │◄────────────────────────┐
        │ check runs first        │                          │
        └─────────────────────────┘                          │
          already installed? ──yes──(auto-advance to Step 3)─┘
                    |
                   no
                    v
     [Button: "Get the extension" → opens Chrome
      Web Store listing in a NEW TAB. Copy: "Install
      it, then come back to this tab."]
                    |
        user returns to dashboard tab
      (tab-switch / focus / poll re-check)
                    |
          installed now? ──no──> [stay on Step 2, same message]
                    |
                   yes
                    v
        ┌─────────────────────────┐
        │ STEP 3 — Sign into      │
        │ LinkedIn                │◄────────────────────────┐
        │ "Already signed in?"    │                          │
        │ check runs first        │                          │
        └─────────────────────────┘                          │
        already signed in? ──yes──(auto-advance to Step 4)────┘
                    |
                   no
                    v
     [Button: "Sign into LinkedIn" → opens
      linkedin.com in a NEW TAB. Copy: "Sign in,
      then come back to this tab."]
                    |
        user returns to dashboard tab
      (tab-switch / focus / poll re-check)
                    |
        signed in now? ──no──> [stay on Step 3, same message]
                    |
                   yes
                    v
        ┌─────────────────────────┐
        │ STEP 4 — Connect        │
        │ (ToS warning shown here)│
        └─────────────────────────┘
                    |
             user clicks Connect
                    |
        [Same extension message flow as the existing
         "Connect with extension" button — reads the
         li_at cookie, hands it to this dashboard tab,
         dashboard calls the existing
         enableLinkedInOutreach() endpoint]
                    |
              +-----+------+
              |            |
          success       failure
              |            |
              v            v
     [Wizard shows      [Wizard shows the error inline
      "Connected" +      (e.g. "not signed in" — loop
      verified name      back to Step 3 automatically
      if available;      if that's the specific failure;
      Close button]       otherwise stay on Step 4 with
                          a retry button)]
```

Already-fully-set-up short-circuit (Story 5 / Story 6 reconnect):

```
[Wizard opens] → Step 1 auto-passes (Chrome/Edge)
              → Step 2 auto-passes (extension already installed)
              → Step 3 auto-passes (already signed into LinkedIn)
              → user lands directly on Step 4 (Connect / Refresh connection)
```

Server not configured branch (existing `outreachStatus.configured === false`):

```
[Any step] → wizard detects outreach not configured on the server
           → Step 4's Connect button is disabled with the existing
             "not enabled on this server yet — ask your admin" message
             (same condition the manual form already handles today)
```

## Acceptance Criteria (Testable Outcomes)

1. **A user on Chrome or Edge who opens the wizard for the first time (nothing installed, not
   signed in) sees Step 1 auto-pass and lands on Step 2 with an "install" call to action.**
   proven by: `apps/web/e2e/` Playwright test that loads the dashboard with the extension marker
   absent, opens the wizard, and asserts Step 2 is the active/rendered step immediately (no click
   needed to leave Step 1).
   strategy: Fully-Automated

2. **Step 2 auto-advances to Step 3 when the extension-installed signal appears without any user
   click on a "check again" / "continue" button.**
   proven by: `apps/web/e2e/` test that opens the wizard on Step 2, then simulates the existing
   `beam-extension-detected` event (the same detection signal the current card already listens
   for) firing after a delay, and asserts the wizard shows Step 3 without any additional
   interaction.
   strategy: Fully-Automated

3. **Step 3 auto-advances to Step 4 when the extension reports a LinkedIn session is present,
   without the user clicking "continue."**
   proven by: `apps/web/e2e/` test that opens the wizard on Step 3, stubs the extension's session
   probe response as "signed in," and asserts Step 4 renders without an intervening click.
   strategy: Fully-Automated

4. **Returning to the dashboard tab after visiting the Chrome Web Store or linkedin.com in a new
   tab re-triggers the wizard's state check and advances it if the underlying condition is now
   true (tab-switch / return awareness).**
   proven by: `apps/web/e2e/` test that opens the wizard on Step 2, dispatches a
   `visibilitychange`/focus event simulating a return-to-tab (per the mechanism selected in
   PLAN — see Open Questions), with the extension-installed signal now true, and asserts the
   wizard advances to Step 3 without a page reload.
   strategy: Fully-Automated

5. **The new LinkedIn-session probe never returns the cookie value itself — only a boolean-ish
   signed-in/not-signed-in status.**
   proven by: `apps/extension/test/` `node:test` unit spec (mirroring the existing
   `connect-logic.test.mjs` pattern) that calls the new probe handler with a mocked
   `chrome.cookies.get` returning a real-looking cookie value, and asserts the handler's return
   shape contains no `cookie` field (or any field carrying the raw value) — only a status/reason.
   strategy: Fully-Automated

6. **The new probe is reachable only over the same trust boundary as the existing connect
   channel — it enforces Chrome-verified sender identity (`externally_connectable`) and, on any
   relay leg, the same per-page-load nonce check already used for the connect response.**
   proven by: `apps/extension/e2e/` Playwright MV3 harness test that attempts to invoke the probe
   from a non-Beam origin page and asserts no response is delivered (mirrors the existing sibling
   SPEC's AC5/AC6 coverage pattern, extended to the new message type); a companion
   `apps/web/e2e/` test asserts the dashboard's message listener rejects a probe-shaped response
   carrying a wrong or missing nonce.
   strategy: Hybrid (automated MV3 extension harness + dashboard-side message-listener test; full
   adversarial red-team coverage remains out of scope for v1, matching the sibling SPEC's AC5
   posture).

7. **A user with no extension and no LinkedIn session who opens the wizard, installs the
   extension, and signs into LinkedIn — all through the wizard's guided links — reaches a
   "Connected" end state with no manual cookie-paste required.**
   proven by: `apps/web/e2e/` end-to-end wizard flow test loading the unpacked extension into a
   Playwright persistent Chromium context (same technique as the sibling SPEC's AC1), seeding a
   fake `li_at` cookie on a mocked linkedin.com origin partway through the run to simulate "user
   signed in," and asserting the wizard reaches Step 4 and then "Connected" after clicking
   Connect.
   strategy: Hybrid (Playwright MV3 extension context; LinkedIn cookie origin and backend call are
   mocked/stubbed — same external-realism gap noted in the sibling SPEC, carried forward here).

8. **The LinkedIn ToS risk warning is shown on the wizard's Step 4 (Connect) — identical in
   substance to the warning already shown on the manual form — every time a user reaches that
   step, with no path that reaches "Connect" without first rendering the warning.**
   proven by: `apps/web/e2e/` component/e2e assertion that the warning banner text is present and
   visible whenever Step 4 renders, across both the "fresh connect" and "already-set-up
   short-circuit" (AC12) paths.
   strategy: Fully-Automated

9. **A user on Firefox or Safari who opens the wizard sees Step 1 resolve to the unsupported-
   browser dead end with a clear explanation and a link to the manual paste form — never an
   "Install" button that can't work.**
   proven by: `apps/web/e2e/` test that simulates the extension-API-absent condition (mirrors the
   sibling SPEC's AC9 default/no-extension-loaded test case) and asserts the wizard renders only
   the dead-end message plus the manual-form link, with no install CTA anywhere in the DOM.
   strategy: Fully-Automated

10. **A user who already has everything set up (extension installed, LinkedIn session present)
    lands directly on Step 4 when opening the wizard — Steps 1–3 render as already-complete/
    skipped, not as steps the user must click through.**
    proven by: `apps/web/e2e/` test that opens the wizard with both signals already true and
    asserts Step 4 is the first rendered step (no intermediate step requires a click).
    strategy: Fully-Automated

11. **Reconnecting an expired session (Story 6) uses the identical wizard and the identical
    Step 4 connect flow as a first-time connect — there is no separate "refresh" code path with
    different security or permission behavior.**
    proven by: `apps/web/e2e/` test that seeds an existing "connected but stale" outreach account,
    opens the wizard, and asserts it short-circuits to Step 4 labeled for reconnect and exercises
    the same extension message flow and backend call as AC7.
    strategy: Hybrid (same Playwright extension harness as AC7, reused for the stale/reconnect
    state).

12. **The manual `li_at` paste form remains fully reachable and functional both from inside the
    wizard (a de-emphasized fallback link/section on any step) and independently of the wizard
    (a user who never opens the wizard can still use it exactly as before).**
    proven by: `apps/web/e2e/` regression test confirming the existing manual-form submit flow
    (already covered by prior sibling-feature test coverage) still passes unmodified, plus a new
    assertion that a fallback link to the manual form is present and functional from within the
    wizard dialog.
    strategy: Fully-Automated

13. **Before installing the extension, the user sees a plain-language explanation of what the
    extension can access (their LinkedIn login session, nothing else) and what happens with it
    (sent once to connect outreach; never stored raw), rendered as part of Step 1 or Step 2 —
    before the install button is the primary action, not after.**
    proven by: `apps/web/e2e/` assertion that the permission-transparency copy is present and
    visible on the step that precedes/accompanies the install call-to-action.
    strategy: Fully-Automated

## Out Of Scope

- **Firefox and Safari extension support.** Inherited from the sibling SPEC — v1 remains Chrome +
  Edge only; the wizard's unsupported-browser branch is a dead end to the manual form, not a
  second extension build.
- **A generalized/shared stepper or wizard component for the rest of the app.** This wizard is
  purpose-built for the LinkedIn extension onboarding flow; extracting a reusable stepper primitive
  is not required unless PLAN finds it trivially justified by the chosen implementation.
- **Automatic/background refresh of an expiring LinkedIn session without user action.** Inherited
  from the sibling SPEC — the wizard only runs when the user opens it; there is no silent
  background re-check that pops the wizard open on its own.
- **Chrome Web Store publication itself.** Out of scope here as it is in the sibling SPEC — Step 2's
  install link points at whatever store listing exists (a placeholder constant until publication).
- **Removing or replacing the existing manual `li_at` paste form.** It remains as the permanent
  fallback (see AC12).
- **Extending the wizard to any other social platform's connect flow** (Twitter/Facebook/
  Instagram/TikTok already use OAuth popups and are unaffected).
- **Reachability of the wizard from the sidebar `OnboardingTour` or `today-actions.tsx`.** Whether
  those surfaces should also link to/launch the wizard is deferred — see Open Questions.
- **Persisting wizard progress across a full page reload** as a hard requirement — see Open
  Questions; the wizard's state is derived live from the same signals the card already uses,
  and a page reload re-deriving that state from scratch may be sufficient.
- **New backend endpoints, schema changes, or CORS changes.** The wizard's final step calls the
  exact same `api.enableLinkedInOutreach()` call the card already makes — no backend work is in
  scope.

## Constraints

**Locked design decisions (do not re-open in INNOVATE/PLAN):**

1. The wizard is hosted in a dialog (the existing `dialog.tsx` primitive), launched from a button
   on the LinkedIn outreach card on the Connected Accounts page — not page-embedded, not built as
   an extension of `OnboardingTour`, not the static chat onboarding.
2. Exactly 4 steps, auto-advancing when each step's condition is already satisfied: (1) browser
   check, (2) install extension, (3) sign into LinkedIn, (4) connect.
3. Steps 2 and 3 each open their target (Chrome Web Store listing, linkedin.com) in a **new tab**,
   not by navigating the dashboard tab away.
4. The wizard must detect state changes on return to the dashboard tab (tab-switch / return
   awareness) — this is a first-class requirement, not a nice-to-have.
5. The manual `li_at` paste form is never removed; it stays reachable as a de-emphasized fallback,
   both from inside the wizard and independently of it, and remains the only path for unsupported
   browsers.
6. A new, read-only extension message type ("is a LinkedIn session present?" probe) is in scope
   and required — distinct from the existing `beam-connect-request` message, which performs a full
   connect and returns the cookie. The new probe must return only a status, never the cookie value.
7. Chrome Web Store URL used by Step 2's install button is a single named placeholder constant,
   matching the existing `KNOWN_EXTENSION_ID` placeholder pattern already in the codebase — must be
   trivially swappable once the extension is published.
8. Backend is unchanged. No new endpoint, no schema change, no CORS change. The wizard's Step 4
   calls the same existing `api.enableLinkedInOutreach(cookie, userAgent)` call the manual form and
   existing extension button already use.
9. Browser scope is Chrome + Edge only (inherited from the sibling SPEC).

**Inherited security constraints (from the sibling SPEC, unchanged, apply equally to the wizard
and the new probe):**

- The cookie value is never transmitted to any origin other than the legitimate Beam dashboard
  origin.
- The dashboard only accepts an extension-originated message (connect OR the new probe response)
  if it can verify Chrome-verified sender identity and, on any page-relay leg, the same
  per-page-load nonce already used for the connect flow.
- The cookie value and User-Agent are never written to any log, error message, or client-side
  storage by the extension or the dashboard.
- The LinkedIn ToS risk warning is shown at the wizard's connect step exactly as it is on the
  manual form — never a "lighter" disclosure.
- The new probe's response must contain no field carrying the raw cookie value — this is a hard
  security constraint on the new message type, not an implementation detail (see AC5).

## Open Questions

1. **Exact auto-advance detection mechanism and its bounds** — `visibilitychange`, window
   `focus`, a bounded poll interval, or some combination, and what the poll bound/backoff should
   be if polling is used at all. Owner: INNOVATE/PLAN. (The behavioral requirement — "the wizard
   notices and advances when the user returns to the tab" — is locked; the mechanism is not.)
2. **Whether wizard progress needs to persist across a full page reload**, or whether it is
   sufficient for the wizard to always re-derive its step from live signals (extension-installed
   marker, LinkedIn-session probe, `getLinkedInOutreachStatus()`) every time it opens — with no
   separate "onboarding done" flag. RESEARCH noted the existing sidebar tour uses a
   `beam_tour_done_v1` localStorage completion flag, while this feature's state today is entirely
   live-derived. Owner: PLAN.
3. **Whether the wizard should also be reachable from the sidebar `OnboardingTour` or from
   `today-actions.tsx`**, in addition to the Connected Accounts card. Owner: PLAN — this is a
   discoverability/entry-point decision, not a requirements question; the wizard's behavior itself
   does not change based on where it's launched from.
4. **Exact shape and naming of the new LinkedIn-session probe message type** (e.g.
   `beam-session-check` request/response field names) and whether it is served over the same
   `externally_connectable` channel as `beam-connect-request` or a separate handler. Owner: PLAN —
   this is an implementation-shape decision; the requirement (read-only, boolean-only, same trust
   boundary) is locked in Constraints above.
5. **What exact realism gap exists in the Playwright extension test harness for AC7/AC11** (the
   same open question the sibling SPEC raised for its AC1 — can a real `li_at` cookie reliably be
   simulated against a mocked linkedin.com origin inside a loaded MV3 extension context, or does
   automated coverage stop short and require one documented manual/agent-probe verification step
   before ship). Owner: VALIDATE.

None of these open questions block understanding *what* the user wants (the requirements in this
SPEC are unambiguous); they are implementation-shape and scope-boundary decisions appropriately
deferred to INNOVATE/PLAN/VALIDATE.

## Background / Research Findings

- **Today's state** (`apps/web/src/app/dashboard/social-accounts/page.tsx:352-384`): the LinkedIn
  outreach card only shows a "Connect with extension" button when `extensionDetected` is already
  true (set via a DOM-attribute first-paint check + a `beam-extension-detected` CustomEvent
  listener, lines 178-225). There is no install path, no "not signed into LinkedIn" handling
  beyond an inline error message after a failed attempt, and no guidance at all for a user who has
  never heard of the extension. This is the exact gap this SPEC closes.
- **Sibling feature already shipped** (`process/features/campaigns-outreach/active/
  linkedin-extension_25-07-26/`): the extension itself (`apps/extension/`), its dumb-pipe
  architecture, the existing `beam-connect-request` message flow, the `KNOWN_EXTENSION_ID`
  placeholder pattern, and the nonce/sender verification trust boundary are all already built and
  in place. This SPEC's wizard consumes that existing surface — it adds a guided UI and one new
  read-only probe message type; it does not change the connect mechanism itself.
- **No existing "is LinkedIn session present" read-only probe.** `apps/extension/src/
  background.js:13-30` exposes exactly two message types today: `register-nonce` and
  `beam-connect-request` (which performs a full cookie read AND returns the cookie value).
  `connect-logic.js:17-40`'s `readLinkedInSession()` already distinguishes "not signed in" from
  "signed in" internally (via the `not_signed_in` reason), but there is no way to ask that
  question without triggering the full connect flow. The new probe this SPEC requires can likely
  reuse most of `readLinkedInSession()`'s internals while stripping the cookie value from the
  response shape.
- **Closest in-repo wizard precedent**: `apps/web/src/app/dashboard/onboarding/page.tsx` — a
  hand-rolled 2-step (`create` → `install`) wizard with a numbered progress bar with checkmarks,
  and a `?site=<id>&step=install` query-param resume pattern for interrupted setups. This is the
  closest structural precedent in the codebase, though it is page-embedded (not dialog-hosted) and
  has no tab-switch-awareness requirement — INNOVATE/PLAN should draw on its progress-indicator
  visual pattern where useful, without assuming its resume-via-query-param mechanism is the answer
  to Open Question 2.
- **`OnboardingTour`** (`apps/web/src/components/onboarding-tour.tsx` +
  `apps/web/src/lib/tour-steps.ts`): a sidebar spotlight tour whose `target` is a `data-tour`
  attribute on desktop sidebar nav links only — it cannot spotlight in-page content like the
  Connected Accounts card, confirming it cannot host this wizard (Locked Decision #1's rationale).
  It uses a `beam_tour_done_v1` localStorage completion flag, relevant to Open Question 2.
- **Available `apps/web/src/components/ui/` primitives** (confirmed via directory listing):
  `badge.tsx`, `button.tsx`, `card.tsx`, `dialog.tsx`, `icon-button.tsx`, `info-tooltip.tsx`,
  `input.tsx`, `label.tsx`, `period-toggle.tsx`, `select.tsx`, `separator.tsx`, `skeleton.tsx`,
  `status-badge.tsx`, `table.tsx`, `tabs.tsx`, `textarea.tsx`. Notably absent: a stepper,
  progress-bar, sheet, or accordion primitive — the onboarding page's numbered-circle progress
  indicator (`page.tsx:104-163`) is hand-rolled, not a shared component; PLAN will need to decide
  whether to reuse that pattern, build a small new one, or use `separator.tsx`/`badge.tsx` styling
  for step indication.
- **`beam-mascot.tsx`**: a pixel-art React component (no props beyond size/palette shown in the
  read) usable for wizard empty/success states if INNOVATE/PLAN chooses a friendlier visual tone —
  not a requirement, just an available asset.
- **Trust boundary for the new probe**: the existing dashboard message listener
  (`page.tsx:200-218`) already enforces `event.origin === window.location.origin`, a
  `source === EXTENSION_MESSAGE_SOURCE` discriminator, and nonce equality before accepting any
  extension-originated message. The new probe's response must be validated through this exact
  same gate — no new/looser channel.
