---
name: plan:linkedin-extension-onboarding
description: "Guided 4-step onboarding wizard (dialog-hosted) that walks a non-technical user through browser check → install extension → sign into LinkedIn → connect, auto-advancing on tab-return, reusing the existing shipped LinkedIn extension's message channel plus one new read-only session-check probe"
date: 26-07-26
feature: campaigns-outreach
phase: "n/a — single COMPLEX plan"
---

# LinkedIn Extension Onboarding Wizard — PLAN

Date: 26-07-26
Status: PLAN drafted — pending VALIDATE.
Complexity: **COMPLEX** (new user-facing flow, new extension message type crossing a security trust
boundary, dialog-hosted wizard with tab-switch-aware auto-advance, shared-hook refactor of existing
detection logic).
Spec: `process/features/campaigns-outreach/active/linkedin-extension-onboarding_26-07-26/linkedin-extension-onboarding_SPEC_26-07-26.md`
Feasibility verdict (read before EXECUTE): `linkedin-extension-onboarding_FEASIBILITY_26-07-26.md`
— NOT-VIABLE for "silent auto-detect on plain enable/reload"; this plan is built around that verdict
(see Locked Decisions D1).

## Overview

The LinkedIn outreach extension (`apps/extension/`, shipped 25-07-26) works, but nobody is shown how
to set it up — the Connected Accounts page only shows a "Connect with extension" button if the
extension already happens to be installed. This plan adds a 4-step guided wizard, hosted in a dialog
and launched from the LinkedIn outreach card, that walks a user through browser check → install →
LinkedIn sign-in → connect, auto-advancing steps whose condition is already true and detecting state
changes when the user returns to the dashboard tab. Backend is untouched — the wizard's final step
calls the same `api.enableLinkedInOutreach()` the manual form already calls. One new extension
message type is added (`beam-session-check`, read-only, boolean-only) to let the wizard know whether
the user is already signed into LinkedIn without doing a full connect.

## TL;DR

New `apps/web/src/components/linkedin-connect-wizard.tsx` (self-contained 4-step dialog component)
+ a new shared hook (`useLinkedInExtensionStatus`) that both the wizard and the existing card consume
for extension-detection + LinkedIn-session state. Extension gains one new read-only message type
(`beam-session-check`) served over the same Chrome-verified `externally_connectable` channel as the
existing connect request — no nonce needed on this leg (reasoning in Security Checklist). Step 2
(install) is reload-based, not silently auto-detecting (per the FEASIBILITY verdict) — the wizard
tells the user to click "I've installed it," which reloads the page and reopens the wizard via a
`?connectLinkedIn=1` query param. Step 3 (LinkedIn sign-in) genuinely auto-advances on tab-return
(no injection problem there). Manual paste form stays, de-emphasized. Zero backend files touched.

---

## Locked Decisions (carried from SPEC Constraints + INNOVATE Decision Summary — do not reopen)

| # | Decision | Source |
|---|---|---|
| D1 | Step 2 (install) is **reload-based, not silent auto-detect**. FEASIBILITY empirically proved plain `content_scripts` do NOT inject into an already-open tab after install or after disable→enable. Copy must never promise silent detection for the install leg. | FEASIBILITY VERDICT (26-07-26), NOT-VIABLE |
| D2 | `?connectLinkedIn=1` query param is required, set before `location.reload()`, read on mount to reopen the wizard; the step itself is recomputed live from current signals — the param only says "reopen the dialog." | INNOVATE |
| D3 | Detection mechanism (shared by Step 2 post-reload check and Step 3 LinkedIn-session check): `visibilitychange`/`focus` listener → immediate one-shot re-check, PLUS a backstop poll every 2s capped at 30 attempts (60s). Cleanup on unmount AND on step change. Cap-exhaustion shows an inline "Still not detected — check again" button that re-arms one fresh check. | INNOVATE (resolves SPEC Open Question 1) |
| D4 | Step 3 genuinely auto-advances (no injection problem — the probe runs from the already-loaded extension when the user returns from linkedin.com). | INNOVATE |
| D5 | New extension message type `beam-session-check`: request → response `{signedIn: true}` or `{signedIn: false, reason: "not_signed_in" \| "cookie_read_failed"}`. **No `cookie` field in the shape, structurally** (AC5). Channel: **D6-only (externally_connectable + `chrome.runtime.sendMessage` direct callback)** — no D7 relay leg, therefore **no nonce required**. See Security Checklist for the reasoning. `reason` stays in the wire shape for debugging but collapses to ONE plain-language UI message. | INNOVATE (resolves SPEC Open Question 4) |
| D6 | Extract `checkLinkedInSignedIn(chromeApi)` as a pure function in `connect-logic.js`; both the existing `readLinkedInSession()` (full connect, returns cookie) and the new probe handler call it — no duplicated "not signed in" branch. | INNOVATE |
| D7 | Component shape: **ONE self-contained `LinkedInConnectWizard.tsx`** with an internal `steps` array (`{key, label, render}`) + locally-computed `currentStepIndex`. Mirrors the onboarding page's numbered-circle progress JSX; no shared stepper primitive extracted (out of SPEC scope). | INNOVATE |
| D8 | State logic lives in a **new shared hook `useLinkedInExtensionStatus()`** owning `extensionDetected`, the nonce (existing D6-channel nonce for the connect flow, unchanged), the `beam-session-check` call + `signedIn` state, and the focus/visibility/poll wiring. Returns `{step, extensionDetected, signedIn, connect, retry, error, isPending}`-shaped state. **VALIDATE fix:** only `social-accounts/page.tsx` (the common host of both consumers) calls `useLinkedInExtensionStatus()` as a React hook — exactly ONCE. The wizard receives this state as PROPS, not by calling the hook itself. (Reason: while the wizard dialog is open, both the card block and the wizard are simultaneously mounted — two independent hook invocations would double-register the D6 nonce, and the extension's `nonceByTabId` registry in `connect-logic.js` is last-write-wins, silently breaking the D7 popup-relay path for whichever consumer's nonce was NOT the one last registered. See Security Checklist item 6.) The card's existing inline detection `useEffect` is lifted into the hook with behavior unchanged. | INNOVATE |
| D9 | v1 surface = Connected Accounts page only. No launcher from `OnboardingTour` (structurally can't host it — spotlights only sidebar `data-tour` nav links) or `today-actions.tsx` (resolves SPEC Open Question 3). | INNOVATE |
| D10 | Chrome Web Store URL = single marked placeholder constant, same pattern as `KNOWN_EXTENSION_ID`. | INNOVATE |
| D11 | Backend unchanged — zero files under `apps/api/`. Wizard's final step calls the existing `api.enableLinkedInOutreach(cookie, userAgent)`. | SPEC Constraint #8 |
| D12 | Manual paste form stays, de-emphasized as the advanced/fallback path, and the only path on Firefox/Safari. | SPEC Constraint #5 |
| D13 (rejected, backlog) | `chrome.scripting.executeScript` + `onInstalled` remedy (proven VIABLE by FEASIBILITY for the fresh-install case) is REJECTED for v1 — only fixes fresh-install, not disable→enable; costs a new `scripting` permission on an extension that already reads a third-party auth cookie. Written up as a backlog note, not implemented. | INNOVATE |

---

## Touchpoints

### NEW — `apps/web/src/lib/use-linkedin-extension-status.ts` (shared hook, D8)

Location: `apps/web/src/lib/` — **RESOLVED by VALIDATE** (re-confirmed live:
`find apps/web/src -type d -iname hooks` returns zero results; `apps/web/src/lib/` is the only
convention this repo uses for shared client-side logic, matching `api.ts`/`fetch-beacon.ts`/
`use-auth-safe.ts`/`use-billing.ts` — note `use-auth-safe.ts` and `use-billing.ts` already live in
`src/lib/` despite being hooks, confirming this IS the hooks convention here, not an exception).
Owns:
- `extensionDetected: boolean` — lifted verbatim from the existing `social-accounts/page.tsx`
  `useEffect` (DOM-attribute first-paint check + `beam-extension-detected` CustomEvent listener).
- `nonce` (existing D6-channel connect-flow nonce, unchanged behavior) + `register-nonce` send.
- `signedIn: boolean | null` (`null` = not yet checked) — calls the new `beam-session-check` message
  (D5) once extension is detected, and on every re-check trigger (D3).
- The D3 detection wiring: `visibilitychange` + `focus` listeners → one-shot re-check; a `setInterval`
  backstop poll (2s, capped at 30 attempts / 60s) that self-clears on cap; `clearInterval` +
  `removeEventListener` cleanup on unmount AND exposed via a `resetPoll()` function so callers can
  re-arm cleanup on step change (a Step-2 poller must never fire during Step 4 — see D3).
- `connect(cookie?, userAgent?)` — wraps the existing `extensionMut`/`connectViaExtension` logic
  (D6 primary channel `beam-connect-request`), unchanged behavior, now hook-owned.
- `retry()` — re-arms exactly one fresh check cycle after poll-cap exhaustion (does not restart the
  full 30-attempt cycle indefinitely — one manual click = one fresh check, per D3).
- Returns: `{extensionDetected, signedIn, connect, retry, error, isPending, isConnected}` (exact
  shape confirmed at EXECUTE against both consumers' real needs — this is the INNOVATE-locked
  contract, field names may be refined without changing behavior). **This return value is what
  `page.tsx` passes down as props to `LinkedInConnectWizard` (VALIDATE fix, D8) — the wizard does
  NOT call this hook itself.**
- **Non-regression requirement:** the existing card's inline `useEffect` (lines 178-225 of
  `social-accounts/page.tsx`) must be lifted into this hook with IDENTICAL behavior — same DOM
  attribute check, same CustomEvent listener, same nonce registration timing, same message-listener
  origin/source/nonce verification for the D7 popup-relay leg (which is orthogonal to and unaffected
  by this plan's new D6-only `beam-session-check` addition).

### NEW — `apps/web/src/components/linkedin-connect-wizard.tsx` (D7)

- `LinkedInConnectWizard({ open, onOpenChange, ...hookState }: { open: boolean; onOpenChange: (open: boolean) => void } & ReturnType<typeof useLinkedInExtensionStatus>)`
  — hosted in the existing `dialog.tsx` primitive (`Dialog`/`DialogContent`/`DialogHeader`/
  `DialogTitle`). **VALIDATE fix (D8):** the wizard receives `extensionDetected`/`signedIn`/`connect`/
  `retry`/`error`/`isPending`/`isConnected` as PROPS from `page.tsx`'s single hook call — it does
  NOT call `useLinkedInExtensionStatus()` internally (see Security Checklist item 6 for why two
  live instances would be a real bug, not just a style preference).
- Internal `steps` array: `[{key: "browser", label: "Browser check", render: ...}, {key: "install", ...}, {key: "linkedin-signin", ...}, {key: "connect", ...}]`.
- `currentStepIndex` computed LIVE on every render from the hook-state PROPS (passed down from
  `page.tsx`'s single hook call, VALIDATE fix D8) + a Chrome/Edge UA sniff for Step 1 — never a
  separately-tracked "which step am I on" state variable that could drift from reality (this is what
  makes the already-fully-set-up short-circuit in SPEC work for free — Step 1/2/3 auto-pass because
  the computed index just starts at 3). **VALIDATE addition:** extract this derivation as a pure,
  exported function (e.g. `computeWizardStepIndex(extensionDetected, signedIn, isChromeOrEdge)`) in
  `use-linkedin-extension-status.ts` — see Test Infra Improvement Notes for why (Vitest-testable
  without a DOM or wall-clock).
- Numbered-circle progress bar JSX mirrors `apps/web/src/app/dashboard/onboarding/page.tsx:114-163`
  visually (same Tailwind classes/structure) — copy the pattern, do not import/extract a shared
  component (SPEC Out of Scope).
- Step 1 (browser check): Chrome/Edge UA sniff (reuse whatever detection the existing D9-guard
  pattern already relies on — `typeof window.chrome !== "undefined"` is the existing extension-API
  presence check; browser-family sniffing for the "which browser is this" copy is a NEW small utility
  — confirm exact UA-sniff approach at EXECUTE, keep it minimal). Auto-advances to Step 2 if
  Chrome/Edge; dead-ends with unsupported-browser copy + manual-form link if not (mirrors SPEC AC9).
- Step 2 (install): shows "already installed?" check first (via the hook's `extensionDetected`); if
  false, shows "Get the extension" button (opens Chrome Web Store placeholder URL, D10, in a new
  tab via `window.open(..., "_blank")`) + "I've installed it" button that sets `?connectLinkedIn=1`
  via `router.push`/`window.location.search` mutation BEFORE calling `location.reload()` (D1/D2 —
  no silent auto-detect promised in copy).
- Step 3 (LinkedIn sign-in): shows "already signed in?" check first (via `signedIn`); if false, shows
  "Sign into LinkedIn" button (opens `https://www.linkedin.com` in a new tab). Auto-advances to Step 4
  via the hook's D3 detection wiring when `signedIn` flips true (D4 — genuinely automatic here, no
  reload needed).
- Step 4 (connect): renders the identical ToS warning banner text/component already shown on the
  manual form (reuse the exact JSX block, not a re-typed copy — see Copy Requirements). "Connect"
  button calls the hook's `connect()`. On success: shows "Connected" + verified account name if the
  backend response includes one (`outreachMut`'s existing success data shape — confirm field name
  at EXECUTE) + a Close button. On failure: if the failure reason is specifically "not signed in,"
  loop back to Step 3 automatically (per SPEC flow diagram); otherwise stay on Step 4 with inline
  error + retry button.
- Server-not-configured branch: if `outreachStatus?.configured === false`, Step 4's Connect button is
  disabled with the existing "not enabled on this server yet" message (reuse existing conditional).
- Permission-transparency copy block: rendered as part of Step 1 or Step 2 (before the install CTA
  is the primary action — SPEC AC13). See Copy Requirements section for exact content guidance.

### MODIFY — `apps/web/src/app/dashboard/social-accounts/page.tsx`

- Replace the inline extension-detection `useEffect` (lines 178-225) + the standalone
  `extensionDetected`/`extensionNonce`/`extensionMut`/`handleExtensionResult`/`connectViaExtension`
  local state with a single `const hookState = useLinkedInExtensionStatus();` call **in `page.tsx`
  only** (VALIDATE fix, D8 — this is the ONE and ONLY call site for this hook; `page.tsx` passes
  `hookState` down as props to `LinkedInConnectWizard`, it does not call the hook a second time).
  **Preserve identical rendered behavior for the existing "Connect with extension" /
  "Refresh connection with extension" button block** (lines 352-384) — this block stays, now wired to
  the hook's `connect`/`isPending`/`error` instead of local state. This is a refactor-only change to
  this block, not a behavior change (regression risk — flag explicitly for VALIDATE/EXECUTE test
  coverage).
- Add a new "Connect LinkedIn" button (opens `LinkedInConnectWizard`) positioned above or alongside
  the existing extension-detected block — the wizard is the NEW primary entry point; the existing
  inline block may remain for users who already have the extension detected (confirm at EXECUTE
  whether to keep both or have the wizard fully replace the inline block's visible UI once the wizard
  ships — SPEC does not mandate removing the existing block, only mandates the wizard exists;
  default to keeping both since SPEC Out of Scope does not authorize removing existing UI, and the
  existing block is also the short-circuit path SPEC Story 5 describes).
- Read the `?connectLinkedIn=1` query param on mount (via `useSearchParams`, mirroring the onboarding
  page's `resumeSite`/`resumeStep` pattern) — if present, auto-open the wizard dialog. Strip the param
  from the URL after reading it (`router.replace` without the param) so a manual page refresh doesn't
  re-trigger the auto-open.
- De-emphasize the manual `li_at` paste form: wrap it in a `<details>` collapsible (mirrors the
  existing "How to find your login key" collapsible pattern already in this file) labeled something
  like "Advanced: paste your login key manually" — collapsed by default when the wizard is available
  (Chrome/Edge); always expanded/only option on Firefox/Safari (no `chrome` global — SPEC AC12/D12).
- Preserve the ToS banner exactly as-is (unconditional, before both paths).
- **VALIDATE fix (resolves the "confirm at EXECUTE" ambiguity in Copy Requirements):** extract the
  existing ToS warning block (lines 346-350: the `<div className="rounded-md border border-warning/30...">`
  containing the "automating LinkedIn is against LinkedIn's Terms of Service..." text) into a new
  small shared component `apps/web/src/components/linkedin-tos-warning.tsx` (no props, or an
  optional `className`), imported by both `page.tsx` (replacing the inline block, zero rendered-
  output change) and `linkedin-connect-wizard.tsx`'s Step 4. This is the concrete, locked resolution
  — a re-typed near-duplicate string is NOT acceptable (AC8 wording-match risk, per Copy
  Requirements) and importing JSX out of a page file is not idiomatic, so extraction into a small
  component is the correct minimal-footprint fix.
- This page becomes the host for `LinkedInConnectWizard` (`open`/`onOpenChange` state).

### MODIFY — `apps/extension/src/background.js`

- Add a third message-type branch in the existing `chrome.runtime.onMessageExternal` listener (same
  D6 channel as `beam-connect-request` and `register-nonce` — no new channel):
  ```
  if (message.type === "beam-session-check") {
    checkLinkedInSignedIn(chrome).then((result) => sendResponse(result));
    return true; // async response
  }
  ```
- No changes to the D7 popup-relay path (`chrome.runtime.onMessage` listener) — the new probe is
  D6-only per D5.

### MODIFY — `apps/extension/src/connect-logic.js`

- Extract a new pure function `checkLinkedInSignedIn(chromeApi)`:
  ```
  export async function checkLinkedInSignedIn(chromeApi) {
    // shares the cookie-read + not-signed-in branching with readLinkedInSession,
    // but returns only {signedIn} — never the cookie value.
  }
  ```
- Refactor `readLinkedInSession()` to call the same shared not-signed-in-detection logic internally
  (D6) — no duplicated branch between the two functions. Exact internal shape (e.g. a private
  `_getLinkedInCookie()` helper both call) decided at EXECUTE; the public contract is: TWO exported
  functions, `readLinkedInSession` (unchanged existing shape, still returns cookie) and
  `checkLinkedInSignedIn` (new, never returns cookie), sharing one internal cookie-read path.
- `checkLinkedInSignedIn`'s return shape: `{signedIn: true}` or `{signedIn: false, reason: "not_signed_in" | "cookie_read_failed"}` — structurally has no `cookie` field (AC5 — this is the
  hard security requirement, not an implementation detail).

### MODIFY — `apps/extension/src/known-origins.js` (if needed)

- Add a message-type-name constant if the repo convention is to centralize message-type strings here
  (confirm existing convention — `background.js` currently uses inline string literals
  `"beam-connect-request"`/`"register-nonce"`/`"beam-connect-request-popup"`, so `"beam-session-check"`
  likely follows the same inline-literal convention; only add a constant if EXECUTE finds an existing
  centralization pattern this should match — do not introduce new centralization unprompted, YAGNI).

### NEW — test files (see Verification Evidence for full AC→gate map)

| File | Purpose |
|---|---|
| `apps/extension/test/connect-logic.test.mjs` (MODIFY — extend existing file) | Unit tests for `checkLinkedInSignedIn()`: mocked `chrome.cookies.get` → cookie present (asserts `{signedIn: true}`, asserts NO `cookie` field anywhere in the return shape), mocked → `null` (asserts `{signedIn: false, reason: "not_signed_in"}`), mocked → throws (asserts `{signedIn: false, reason: "cookie_read_failed"}`). |
| `apps/extension/e2e/session-check.spec.ts` (NEW, mirrors existing `connect.spec.ts`/`nonce-forgery.spec.ts` structure) | MV3 harness test: `beam-session-check` message round-trip from a Beam-origin page via `externally_connectable`, asserting response shape has no `cookie` field; a companion case attempting the same message from a non-Beam origin (mirrors `spoofed-origin.spec.ts`) asserting no response delivered. |
| `apps/web/e2e/linkedin-connect-wizard.spec.ts` (NEW) | Full wizard flow: AC1 (Step 1 auto-pass → Step 2), AC2 (Step 2→3 auto-advance on simulated `beam-extension-detected` event), AC3 (Step 3→4 auto-advance on stubbed signed-in probe response), AC4 (visibilitychange/focus re-check + advance), AC7 (Step 4 auto-advances back if failure reason is not-signed-in, otherwise stays with retry), AC8 (ToS warning always present on Step 4), AC9 (unsupported-browser dead end, no install CTA), AC10 (already-fully-set-up short-circuit lands on Step 4), AC12 (manual form fallback link present + functional), AC13 (permission-transparency copy present before install CTA). |
| `apps/web/e2e/linkedin-outreach-extension.spec.ts` (MODIFY — extend existing file) | Regression: existing AC6/AC7/AC9 assertions from the sibling feature must still pass after the hook refactor (D8's non-regression requirement) — re-run unmodified plus one new assertion that the wizard-launch button is present. |
| **NEW backlog note** | `process/features/campaigns-outreach/backlog/linkedin-onboarding-oninstalled-remedy_NOTE_26-07-26.md` — documents the rejected D13 (`scripting` + `onInstalled` executeScript remedy), framed accurately: "reduces clicks for fresh installs only, not a full auto-detect fix; costs a new permission; FEASIBILITY-proven viable if ever revisited." |

---

## Public Contracts

- **No new backend endpoint, schema, or CORS change** (D11, locked). This plan touches ZERO files
  under `apps/api/`.
- **New extension-to-page message contract** (D6 channel only, no new D7 leg):
  - Request: `{type: "beam-session-check"}` — dashboard → extension, via
    `chrome.runtime.sendMessage(KNOWN_EXTENSION_ID, {type: "beam-session-check"}, callback)`.
  - Response: `{signedIn: true}` OR `{signedIn: false, reason: "not_signed_in" | "cookie_read_failed"}` — structurally never contains `cookie` or `userAgent` (AC5).
  - This is additive to the existing message contract (`beam-connect-request`, `register-nonce`,
    `beam-connect-request-popup`/`beam-connect-response`) — none of those shapes change.
- **`existing` contract reused unchanged**: `api.enableLinkedInOutreach(sessionCookie, userAgent, label?)`
  → `POST /api/v1/social/accounts/linkedin/outreach-connect`. No client-side change to this method's
  signature; only new call sites (the wizard's Step 4) using the existing method.
- **New internal hook contract**: `useLinkedInExtensionStatus()` — consumed by both
  `social-accounts/page.tsx` and `linkedin-connect-wizard.tsx`. Any future change to this hook's
  return shape is now a two-consumer breaking-change surface — note this in Test Infra Improvement
  Notes as a regression risk to watch.

---

## Blast Radius

| Surface | Files | Risk class |
|---|---|---|
| `apps/web/src/lib/use-linkedin-extension-status.ts` (or `src/hooks/`) | 1 new file | Medium — consolidates existing auth-adjacent detection logic; must not regress the sibling feature's existing behavior |
| `apps/web/src/components/linkedin-connect-wizard.tsx` | 1 new file | Medium — new user-facing surface, reuses existing security-verified channels, no new trust boundary of its own beyond D5 |
| `apps/web/src/components/linkedin-tos-warning.tsx` (VALIDATE addition) | 1 new file, extracted verbatim from existing `page.tsx` JSX | Low — pure extraction, zero rendered-output change at the extraction site |
| `apps/web/src/app/dashboard/social-accounts/page.tsx` | 1 file, refactor (lift detection logic to hook) + additive (wizard launch, query-param resume, form de-emphasis) | Medium-High — refactors code that is also part of the sibling feature's already-shipped, already-tested surface; regression risk on the existing "Connect with extension" button and the D7 popup-relay message listener, which are UNCHANGED in behavior but now hook-owned |
| `apps/extension/src/background.js` | 1 file, additive (~6 lines, one new `if` branch on existing listener) | Medium — new message type on an existing Chrome-verified channel; no new permission, no new channel |
| `apps/extension/src/connect-logic.js` | 1 file, refactor (extract shared helper) + additive (new exported function) | Medium — auth/identity-adjacent (LinkedIn session read path); must not change `readLinkedInSession()`'s existing public contract/return shape |
| `apps/extension/src/known-origins.js` | 0-1 files, conditional | Low |
| `apps/extension/manifest.json` | 0 files — **explicitly unchanged**, no new permission (D13 rejected) | None |
| Backend (`apps/api/**`) | 0 files | None |
| New test files | ~4 files (2 new, 2 modified) | N/A |
| New backlog note | 1 file | N/A |
| Total distinct source files touched/created | ~7-8 | High-risk class present: **auth/identity-adjacent** (LinkedIn session cookie handling, same class as the sibling feature) — requires Hybrid-minimum test tier throughout, satisfied below. **No new trust-boundary surface** beyond the sibling feature's already-established D6/D7 channels — the new probe reuses D6 exactly, adding no new attack surface class. |

**Zero-`apps/api/` proof scoping note:** the worktree at plan-write time has unrelated dirty
`apps/api/` files from other concurrent work (visible in `git status` — e.g. `apps/api/config.py`,
`apps/api/jobs/scheduler.py`, etc., none touched by this plan). A bare `git diff -- apps/api/` at
EXECUTE time will NOT be empty because of that unrelated concurrent work — it is NOT valid proof for
this plan alone. The correct proof at EXECUTE/VALIDATE time is: `git diff --name-only -- apps/api/`
scoped to **this plan's own commit or staged changeset** (e.g. `git diff --cached --name-only --
apps/api/` after `git add` of only this plan's files, or `git show --name-only <this-plan's-commit>
-- apps/api/`), confirmed empty. Document which exact method was used when this gate runs.

---

## Security Checklist (derived from AC5 / AC6 / AC8 + the new probe)

1. **No cookie in the probe response shape.** `checkLinkedInSignedIn()`'s return type structurally
   has no `cookie` or `userAgent` field on either branch (`{signedIn: true}` /
   `{signedIn: false, reason}`) — this is a type/shape guarantee, verified by a unit test asserting
   the returned object's keys, not just its truthy/falsy values (AC5, D5).
2. **Sender verification via `externally_connectable` (structural, D6-only, no nonce needed).**
   The new probe is served exclusively on `chrome.runtime.onMessageExternal` — the SAME channel as
   the existing `beam-connect-request` and `register-nonce` messages, which Chrome only delivers from
   pages whose origin is listed in `manifest.externally_connectable.matches`, with `sender` verified
   by Chrome itself. There is no D7 relay leg for this message — the popup never triggers a session
   check, and `content.js` never touches it. **Why no nonce is required here (explicit reasoning, not
   an oversight):** the sibling feature's D10 nonce exists SPECIFICALLY to defend the D7
   `window.postMessage` relay leg, where `event.origin` alone is forgeable by a co-resident malicious
   extension running content scripts in the same page context, and the `source` discriminator string
   is public/reverse-engineerable from the shipped bundle. The D6 direct-callback channel has neither
   weakness — Chrome's own sender verification on `externally_connectable` cannot be forged by a
   co-resident extension (a different extension has a different ID and is never targeted by the
   page's `chrome.runtime.sendMessage(KNOWN_EXTENSION_ID, ...)` call), so there is no equivalent gap
   to close. Adding a nonce to a D6-only message would be redundant hardening with no threat it
   defeats that Chrome's own channel verification doesn't already defeat.
3. **`reason` field collapse for UI.** The wire shape keeps `reason: "not_signed_in" | "cookie_read_failed"` for debuggability, but the wizard's Step 3 UI collapses both to ONE plain-language message
   ("Sign in to LinkedIn, then come back") — `host_permissions` are granted at install time, so
   "can't read cookies" (`cookie_read_failed`) isn't a live user-hittable state distinct from "not
   signed in" in practice; surfacing two different UI messages would only confuse, not help, a
   non-technical user.
4. **No cookie/UA logged or stored anywhere in the new code path.** Same grep-checkable rule as the
   sibling feature (AC8-equivalent): zero `console.log`/`logger.*`/`localStorage`/`chrome.storage`
   calls referencing `cookie`, `response`, or `signedIn`-adjacent variables in the new probe path.
5. **Minimal permissions unchanged — assert no manifest diff.** `manifest.json` gains ZERO new
   permissions, host_permissions, or `externally_connectable` matches. VALIDATE/EXECUTE must assert
   `git diff apps/extension/manifest.json` is empty (or contains only the version bump, if any) —
   this is the concrete, checkable form of D13's rejection (no `scripting` permission added).
6. **Single hook instance is a security-adjacent correctness requirement, not just a style
   preference (VALIDATE finding, fixed as D8).** The extension's `nonceByTabId` registry
   (`connect-logic.js`) is keyed by `tabId` and is last-write-wins — it has no concept of "which
   page-side consumer" registered a nonce. If `useLinkedInExtensionStatus()` were called from BOTH
   `page.tsx` (card) and `linkedin-connect-wizard.tsx` while the wizard is open (both simultaneously
   mounted — confirmed via `dialog.tsx`'s Radix `Presence` semantics, which unmount on close but NOT
   while open), each call would independently `register-nonce` its own random value, and the D7
   popup-relay response (signed with whichever nonce was registered LAST) would be silently rejected
   by the OTHER consumer's `nonce !== extensionNonce` check — a real, user-visible "the popup connect
   flow silently did nothing" bug, not merely a style nit. Fixed structurally: `page.tsx` is the only
   call site; the wizard receives hook state as props (Touchpoints, D8).
7. **New `beam-session-check` probe cannot be used as a cross-origin oracle (adversarial check,
   VALIDATE).** The probe is routed exclusively over `chrome.runtime.onMessageExternal` (D6), which
   Chrome gates on `manifest.externally_connectable.matches` (BEAM_ORIGINS only) — a non-Beam-origin
   page cannot reach the handler at all (Chrome does not deliver the message), so it cannot learn
   `signedIn` state. A co-resident malicious EXTENSION also cannot reach it: `externally_connectable`
   has no `ids` field in this manifest, and Chrome's documented default for an unset `ids` field is
   that NO other extension may connect — only web pages matching `matches` can. The one real residual
   is narrower and pre-existing: an XSS-compromised Beam-origin page could call `beam-session-check`
   itself (same as it could already call the full `beam-connect-request`, which is strictly a WORSE
   leak — the actual cookie, not a boolean). This matches the sibling plan's already-accepted threat
   model, which explicitly excludes "the dashboard page itself is compromised (XSS)" as a threat
   class outside the dumb-pipe architecture's scope. The new probe does not introduce a new threat
   class, only a strictly smaller instance of an already-accepted one.

---

## Copy Requirements (SPEC tone rules — illustrative strings only, not final)

- **Never use "cookie," "DevTools," or "session token" anywhere in the primary wizard path.** These
  terms are confined to the de-emphasized manual/advanced form only (which already uses "login key"
  language, per the existing `page.tsx` copy — "LinkedIn login key (the 'li_at' cookie)" stays
  exactly as-is in its own collapsed section; the wizard's 4 steps never use this vocabulary).
- **Illustrative Step 1 copy** (not final): "We use Chrome or Edge to connect LinkedIn — looks like
  you're on [browser name], which isn't supported yet. Use the manual option below instead."
- **Illustrative Step 2 copy** (not final): "Get the Beam extension — it lets us connect LinkedIn
  with one click instead of copying anything by hand. [Get the extension] opens the Chrome Web
  Store in a new tab. Install it, then come back here and click [I've installed it]." — **must NOT**
  say "we'll detect it automatically" (D1 hard constraint from FEASIBILITY).
- **Illustrative Step 3 copy** (not final): "Sign into LinkedIn — [Sign into LinkedIn] opens
  linkedin.com in a new tab. Sign in, then come back to this tab — we'll pick up right where you left
  off." (this one MAY promise auto-detection — D4 confirms it's real).
- **Illustrative permission-transparency copy** (AC13, before Step 2's install CTA): "What this can
  see: your LinkedIn login session, so Beam can send connection requests on your behalf. What it does
  NOT do: it doesn't read any other site you visit, it doesn't post anything automatically, and Beam
  never keeps a copy of your raw login session." Rendered as part of Step 1 or Step 2 — before, not
  after, the primary install action (AC13's literal ordering requirement).
- **Step 4 ToS warning:** reuse the EXACT existing warning component/text verbatim (`page.tsx` lines
  346-350) via the new shared `<LinkedInTosWarning />` component (**RESOLVED by VALIDATE** — see the
  `page.tsx` Touchpoints entry; extraction into `apps/web/src/components/linkedin-tos-warning.tsx`,
  imported by both consumers, is the locked approach — do not re-type a paraphrase, AC8 wording
  match risk).

---

## Implementation Checklist (Ordered Implementation Steps)

Grouped so the functional flow is verifiable before polish, per the requested ordering
(extension probe → shared hook → wizard component → card integration + reopen param → copy/
permission-transparency → tests → backlog note).

### Step 1 — Extension: new `beam-session-check` probe (D5, D6)
- Extract `checkLinkedInSignedIn(chromeApi)` in `connect-logic.js` (D6), refactoring
  `readLinkedInSession()` to share the underlying not-signed-in detection without changing its
  public return shape.
- Add the `beam-session-check` branch to `background.js`'s existing `onMessageExternal` listener.
- Unit tests: cookie present → `{signedIn: true}` (assert no `cookie` key present); cookie null →
  `{signedIn: false, reason: "not_signed_in"}`; `cookies.get` throws → `{signedIn: false, reason: "cookie_read_failed"}`.
- **Gate:** `cd apps/extension && npm test` green; manual grep confirms no `cookie`/`userAgent` key
  appears in any object literal returned by `checkLinkedInSignedIn`.

### Step 2 — Extension e2e: probe trust boundary (Security Checklist items 1, 2, 5)
- New `apps/extension/e2e/session-check.spec.ts`: round-trip from a Beam-origin fixture page via
  `externally_connectable`, assert response shape; spoofed-origin case (mirrors
  `spoofed-origin.spec.ts`) asserting no response delivered to a non-Beam-origin page.
- Manifest diff assertion: `git diff apps/extension/manifest.json` empty (Security Checklist item 5).
- **Gate:** `cd apps/extension && npm run test:e2e` green (new spec + full existing suite unmodified).

### Step 3 — Shared hook: `useLinkedInExtensionStatus()` (D8)
- Create the hook, lifting the existing `social-accounts/page.tsx` detection `useEffect` behavior
  verbatim (D8 non-regression requirement) and adding the D3 focus/visibility/poll wiring plus the
  `beam-session-check` call + `signedIn` state.
- Do NOT wire this into `page.tsx` yet in this step — build and unit-verify the hook in isolation
  first if a component-test lane exists for `apps/web` (confirm at EXECUTE per Test Infra Improvement
  Notes below; if no isolated-hook-test lane exists, proceed directly to Step 4/5 integration and
  cover the hook's behavior via the e2e specs instead).
- **Gate:** hook compiles + typechecks (`cd apps/web && npx tsc --noEmit`); `cd apps/web && npm run
  test` (Vitest, existing node-env lane) passes the new `use-linkedin-extension-status.test.ts`
  covering `computeWizardStepIndex()`'s pure branches (VALIDATE fix — see Test Infra Improvement
  Notes; this replaces the original "if a component-test lane exists" conditional with a concrete,
  confirmed-runnable gate for the extractable-pure-logic half of D3).

### Step 4 — Wizard component: `LinkedInConnectWizard.tsx` (D7)
- Build the 4-step wizard consuming the Step 3 hook, mirroring the onboarding page's numbered-circle
  progress bar visual pattern.
- Implement each step's render per the Touchpoints section above, including the already-fully-set-up
  short-circuit (currentStepIndex computed live, no separate tracked state).
- **Gate:** `cd apps/web && npx tsc --noEmit` clean; `cd apps/web && npm run lint` clean on the new
  file.

### Step 5 — Card integration + reopen param (D2, D8, D12)
- Wire `LinkedInConnectWizard` into `social-accounts/page.tsx`: replace the inline detection logic
  with the Step 3 hook (non-regression requirement — existing "Connect with extension" block behavior
  must be identical), add the wizard-launch button, read+strip the `?connectLinkedIn=1` param, wrap
  the manual form in a de-emphasized `<details>` collapsible.
- **Gate:** `cd apps/web && npx tsc --noEmit` clean; `cd apps/web && npm run lint` clean; manual smoke
  (dev server) confirms the existing extension-detected block and manual form both still render
  correctly with no extension loaded (AC9-equivalent quick check before the full e2e suite runs).

### Step 6 — Copy + permission transparency (AC13, Copy Requirements section)
- Fill in final copy for all 4 steps + the permission-transparency block, following the Copy
  Requirements guidance (illustrative strings above are NOT final — write real copy at this step).
- Confirm the ToS warning reuse approach (import vs shared constant) and implement it.
- **Gate:** visual/manual review; AC13 copy-presence assertion added to the wizard e2e spec (Step 7
  writes the actual test, this step ensures the copy exists to assert against).

### Step 7 — Tests: full AC→gate coverage
- Write `apps/web/e2e/linkedin-connect-wizard.spec.ts` covering AC1-AC4, AC7-AC10, AC12, AC13 (see
  Verification Evidence for the exact scenario-to-AC map and the 3 automation-realism notes from
  INNOVATE OQ5).
- Extend `apps/web/e2e/linkedin-outreach-extension.spec.ts` with the regression assertion (existing
  AC6/AC7/AC9-equivalent sibling coverage still passes after the hook refactor).
- Extend `apps/extension/test/connect-logic.test.mjs` (Step 1) and add
  `apps/extension/e2e/session-check.spec.ts` (Step 2) if not already finalized.
- **Gate:** all new + modified specs green; full existing `apps/extension/e2e` and
  `apps/web/e2e` suites re-run unmodified and green (regression pass).

### Step 8 — Backlog note + final regression sweep
- Write `linkedin-onboarding-oninstalled-remedy_NOTE_26-07-26.md` documenting the rejected D13 remedy.
- Run `cd apps/web && npm run lint`, `cd apps/web && npx tsc --noEmit`, `cd apps/extension && npm test`,
  `cd apps/extension && npm run test:e2e`, `cd apps/web && npm run test:e2e` (full suites) one final
  time.
- Confirm `git diff --name-only -- apps/api/` scoped to this plan's own changeset is empty (see Blast
  Radius scoping note).
- **Gate:** all Verification Evidence rows green; zero backend files in this plan's changeset;
  manifest.json diff is empty.

---

## Acceptance Criteria

This plan implements all 13 SPEC acceptance criteria verbatim (see SPEC file for full text and exact
proving-mechanism description per AC). Summary: AC1 Step 1 auto-pass on Chrome/Edge; AC2 Step 2→3
auto-advance on install signal; AC3 Step 3→4 auto-advance on signed-in signal; AC4 tab-return
re-triggers detection and advances; AC5 probe never returns the cookie value; AC6 probe reachable
only over the Chrome-verified D6 channel; AC7 full guided-install-to-connect flow reaches "Connected"
with no manual paste; AC8 ToS warning always shown on Step 4; AC9 Firefox/Safari dead-end, no broken
install CTA; AC10 already-set-up short-circuit lands on Step 4; AC11 reconnect uses the identical
wizard/flow as first connect; AC12 manual form stays reachable both inside and outside the wizard;
AC13 permission-transparency copy precedes the install CTA.

## Phase Completion Rules

Single COMPLEX plan (no phase program). **CODE DONE** when Steps 1-8 are implemented and every row
in Verification Evidence is green (Fully-Automated/Hybrid tiers actually passing). **VERIFIED**
requires, in addition to CODE DONE: (a) the same human-in-the-loop confirmation the sibling feature
requires — a real signed-in LinkedIn session exercised through the wizard in a real browser (this
plan's wizard reuses the sibling's already-VERIFIED-pending connect mechanism, so this is the same
outstanding human step, not a new one); (b) confirmation that the hook refactor did not regress the
sibling feature's shipped behavior (Step 7's regression pass, run once more manually against a real
extension load if the sibling feature's own VERIFIED sign-off is still pending at the time this plan
reaches EXECUTE — check `linkedin-extension_PLAN_25-07-26.md`'s status line for current state).

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `cd apps/web && npm run test:e2e` — wizard opens with no extension marker, asserts Step 2 renders immediately, no click to leave Step 1 | Fully-Automated | AC1 |
| `cd apps/web && npm run test:e2e` — wizard opens on Step 2, dispatch `beam-extension-detected` CustomEvent after a delay, asserts Step 3 renders without any click | Fully-Automated | AC2 |
| `cd apps/web && npm run test:e2e` — wizard opens on Step 3, stub the extension's `beam-session-check` response as signed-in (route/page.evaluate stub of the D6 channel response), asserts Step 4 renders without a click | Fully-Automated | AC3 |
| `cd apps/web && npm run test:e2e` — wizard opens on Step 2, dispatch `visibilitychange`/`focus` (real browser-level via `page.bringToFront()` after `context.newPage()`, per INNOVATE OQ5(b)), extension-installed signal now true, asserts advance to Step 3 with no page reload | Fully-Automated — **VALIDATE confirmed via `playwright-core` source** (not docs alone, which only say "activates tab"): Chromium's `bringToFront()` delegate issues the real CDP command `Page.bringToFront` — the same browser-level tab-activation primitive Playwright/Chrome itself would send for an actual tab switch, not a synthetic JS-dispatched event. High confidence this drives a genuine `document.visibilityState`/focus transition. One residual, documented rather than probed away: the exact Chromium-internal wiring from `Page.bringToFront` to the renderer's visibility-state update was not independently re-verified beyond confirming the CDP call itself (this is standard, widely-used Playwright practice for this exact test shape, not a novel/undocumented mechanism like the FEASIBILITY probe's MV3 injection-timing question was) | AC4 |
| `cd apps/extension && npm test` — unit: `checkLinkedInSignedIn()` with mocked cookie present, asserts return object has NO `cookie` key (not just a falsy check — an explicit key-presence assertion) | Fully-Automated | AC5 |
| `cd apps/extension && npm run test:e2e` — MV3 harness: `beam-session-check` invoked from a non-Beam-origin fixture page, asserts no response delivered (mirrors `spoofed-origin.spec.ts`); companion Beam-origin case asserts a well-formed response IS delivered | Hybrid — MV3 extension harness (matches sibling SPEC's AC5/AC6 automation posture; full adversarial red-team coverage remains out of scope for v1) | AC6 |
| `cd apps/web && npm run test:e2e` — full wizard flow: no extension, no LinkedIn session, install (synthetic proxy — see automation-realism note below), sign in (seeded `li_at` cookie via `context.addCookies()`, mirrors sibling AC1's OI-1-probed technique), connect → asserts "Connected" with no manual paste | Hybrid — Playwright MV3 extension context; install-step realism note applies (below); LinkedIn cookie origin mocked/stubbed, same external-realism gap as sibling AC7 | AC7 |
| `cd apps/web && npm run test:e2e` — Step 4 renders across both fresh-connect and already-set-up short-circuit (AC10) paths; asserts ToS warning banner text present/visible in both | Fully-Automated | AC8 |
| `cd apps/web && npm run test:e2e` — simulate extension-API-absent condition (mirrors sibling AC9), asserts wizard renders only the dead-end message + manual-form link, zero install CTA anywhere in the DOM | Fully-Automated | AC9 |
| `cd apps/web && npm run test:e2e` — wizard opens with both `extensionDetected` and `signedIn` pre-seeded true, asserts Step 4 is the first rendered step (no click required through 1-3) | Fully-Automated | AC10 |
| `cd apps/web && npm run test:e2e` — seed an existing "connected but stale" outreach account, open wizard, asserts short-circuit to Step 4 labeled for reconnect, exercises identical message flow + backend call as AC7's test | Hybrid — same Playwright extension harness as AC7, reused for stale/reconnect state | AC11 |
| `cd apps/web && npm run test:e2e` — existing manual-form submit flow (already covered by sibling test coverage) passes unmodified; new assertion that a fallback link to the manual form is present + functional from within the wizard dialog | Fully-Automated | AC12 |
| `cd apps/web && npm run test:e2e` — assert permission-transparency copy block is present and visible on the step that precedes/accompanies the install CTA | Fully-Automated | AC13 |
| `cd apps/web && npm run test:e2e` (extended `linkedin-outreach-extension.spec.ts`) — existing sibling-feature AC6/AC7/AC9 assertions re-run unmodified after the hook refactor | Fully-Automated (regression) | D8 non-regression requirement (not a numbered SPEC AC, but required by this plan) |
| `cd apps/web && npm run test` (Vitest, existing node-env lane — VALIDATE addition) — `computeWizardStepIndex()` pure-function branches: no signals → 0, extension-only → 1, extension+signedIn → 3, unsupported browser → dead-end branch | Fully-Automated | Test-infra improvement (not a numbered SPEC AC); resolves the D3 wall-clock testability concern for the derivable-logic half |

**Automation-realism note (INNOVATE OQ5, all 3 sub-questions resolved):**
(a) probe false→true mid-test via `context.addCookies()` — fully automatable, proven technique
(sibling AC1/OI-1).
(b) tab-switch/return — fully automatable via `context.newPage()` + `page.bringToFront()`, a real
browser-level `visibilitychange`/`focus` event, not a synthetic dispatch.
(c) extension-installed-mid-session (the Step 2 install signal itself appearing) is NOT directly
stageable in Playwright the same way — the AC2 test above uses a **synthetic proxy**: dispatching the
`beam-extension-detected` CustomEvent directly (or setting the DOM marker) rather than actually
installing an extension mid-test. This proves the wizard's REACTION to the signal, not Chrome's
actual delivery mechanism for that signal — the delivery mechanism itself (reload-based, per D1) is
proven separately and empirically by the FEASIBILITY probe, not by this plan's e2e suite. State this
plainly wherever AC2/AC7's coverage is discussed — it is a known, accepted automation boundary, not a
gap being silently dropped.

Known-gap vacuous-green note: no SPEC AC in this plan is assigned Known-Gap as a terminal state. All
13 ACs carry a Fully-Automated or Hybrid gate.

---

## Test Infra Improvement Notes

- **RESOLVED by VALIDATE (was: "confirm at EXECUTE whether apps/web has any isolated
  component/hook-test lane"):** `apps/web/vitest.config.ts` DOES exist (`npm run test` → `vitest run`,
  precedent: `apps/web/src/lib/fetch-beacon.test.ts`) — but it is configured `environment: "node"`,
  scoped to `src/**/*.test.ts` pure-logic files only, with NO `jsdom`/`@testing-library/react` in
  `apps/web/package.json` — so it CANNOT render the hook itself (no DOM, no `renderHook`). Do not add
  those dependencies just for this plan (YAGNI). Instead: extract the step-computation logic as a
  PURE exported function (`computeWizardStepIndex(extensionDetected, signedIn, isChromeOrEdge)`, see
  Touchpoints) and cover it with a new `apps/web/src/lib/use-linkedin-extension-status.test.ts` in the
  EXISTING Vitest node lane — fast, deterministic, no timers, no DOM needed for this specific piece.
  This directly resolves the "2s × 30 = 60s wall-clock" testability concern for the derivable-logic
  half of D3; the actual `setInterval`/`visibilitychange`/`focus` DOM wiring remains e2e-only
  (Hybrid tier, unavoidable — it inherently needs a real event loop and browser context), which is
  an accepted, correctly-scoped gap, not an infra hole.
- The new `useLinkedInExtensionStatus()` hook becomes a two-consumer contract surface (the card +
  the wizard) — any future change to its return shape is now a regression risk across two UI
  surfaces at once. Flag as a maintenance note, not a blocker.
- `apps/extension/e2e` remains local-only, not CI-wired (matches the sibling feature's already-
  accepted `apps/pixel`/`apps/extension` precedent — see sibling plan's Test Infra Improvement Notes).
  This plan's new `session-check.spec.ts` inherits the same gap, not a new one.
- The install-signal automation-realism boundary (OQ5(c) above) means AC2's proving test is a
  synthetic-proxy test, not a full "Chrome actually detected the extension" test — this is the
  correct, deliberate boundary per INNOVATE's resolution, not an infra gap to close later.

---

## Resume and Execution Handoff

1. **Selected plan file path:** `process/features/campaigns-outreach/active/linkedin-extension-onboarding_26-07-26/linkedin-extension-onboarding_PLAN_26-07-26.md`
2. **Last completed phase or step:** PLAN drafted (26-07-26) — RESEARCH/SPEC/FEASIBILITY/INNOVATE
   complete (FEASIBILITY probe empirically resolved the auto-detect question NOT-VIABLE, see
   `linkedin-extension-onboarding_FEASIBILITY_26-07-26.md`). VALIDATE not yet run.
3. **Validate-contract status:** pending — placeholder below, VALIDATE writes this section before
   EXECUTE.
4. **Supporting context files loaded:** `process/context/all-context.md`,
   `process/context/tests/all-tests.md`, the locked SPEC file, the FEASIBILITY VERDICT file, the
   sibling `linkedin-extension_SPEC_25-07-26.md` + `linkedin-extension_PLAN_25-07-26.md` (D6/D7/D10
   vocabulary reused, do not contradict), `apps/web/src/app/dashboard/social-accounts/page.tsx`,
   `apps/web/src/app/dashboard/onboarding/page.tsx`, `apps/web/src/components/ui/dialog.tsx`,
   `apps/extension/src/{background.js,content.js,connect-logic.js,known-origins.js}`,
   `apps/extension/manifest.json`, `apps/extension/e2e/*`, `apps/extension/test/*`,
   `apps/web/e2e/linkedin-outreach-extension.spec.ts`, both `package.json` files for exact test
   commands.
5. **Next step for a fresh agent picking up mid-execution:** run VALIDATE next. If resuming
   mid-EXECUTE, follow Ordered Implementation Steps 1-8 in order — Step 1-2 (extension probe) must
   land before Step 3 (hook) since the hook calls the new probe; Steps 4-5 (wizard + card
   integration) must land before Step 6 (copy) and Step 7 (tests) since tests assert against real
   rendered copy/DOM.

## Validate Contract

Status: PASS
Date: 26-07-26
date: 2026-07-26
generated-by: outer-pvl

Parallel strategy: parallel-subagents (Layer 1: 4 dimension agents — infra/setup fit, test
coverage, breaking changes, security surface; Layer 2: 5 section agents — shared hook, wizard
component, page.tsx refactor, extension probe (background.js/connect-logic.js), test-coverage
plan — all independently checkable against the plan text + real source files, no section's
finding depended on another section's in-flight output; the one genuinely cross-cutting item
found (the double-hook-instance nonce bug) was resolved by folding a direct fix into the plan
text rather than requiring live inter-agent coordination)
Rationale: Score 3/7 (S2 auth/identity-adjacent surface present — LinkedIn session cookie
handling via a new probe; S6 high-risk class present — auth/identity-adjacent + trust-boundary/
secrets, inherited from the sibling feature's already-accepted threat model; S7 not met on file
count alone — ~7-8 source files is under the 5+ threshold read strictly, but the risk-class
signal alone already qualifies MEDIUM tier) → parallel subagents over agent-team, matching the
sibling plan's own VALIDATE precedent for the same reasoning.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC1 | Step 1 auto-passes on Chrome/Edge (nothing installed, not signed in) | Fully-Automated | `cd apps/web && npm run test:e2e` — wizard opens, Step 2 renders immediately, zero click to leave Step 1 | B |
| AC2 | Step 2→3 auto-advances on extension-installed signal, no click | Fully-Automated (synthetic-proxy — see automation-realism note in plan; the delivery mechanism itself is proven separately by the FEASIBILITY probe) | `cd apps/web && npm run test:e2e` — dispatch `beam-extension-detected` CustomEvent, asserts Step 3 renders with no click | B |
| AC3 | Step 3→4 auto-advances on signed-in probe response, no click | Fully-Automated | `cd apps/web && npm run test:e2e` — stub `beam-session-check` response as signed-in, asserts Step 4 renders with no click | B |
| AC4 | Tab-return re-triggers detection and advances (no reload) | Fully-Automated — VALIDATE-confirmed via `playwright-core` source that `page.bringToFront()` issues the real CDP `Page.bringToFront` tab-activation command, not a synthetic event | `cd apps/web && npm run test:e2e` — `context.newPage()` + `page.bringToFront()` back to original tab, extension-installed now true, asserts advance to Step 3 with no reload | B |
| AC5 | Probe never returns the cookie value | Fully-Automated | `cd apps/extension && npm test` — unit test asserts `checkLinkedInSignedIn()`'s return object has NO `cookie` key on either branch (explicit key-presence assertion, not just falsy check) | B |
| AC6 | Probe reachable only over the Chrome-verified D6 channel | Hybrid — MV3 harness, confirmed runnable in this sandbox (zero-infra static server, no Postgres/Docker needed) | `cd apps/extension && npm run test:e2e` — new `session-check.spec.ts` mirroring `spoofed-origin.spec.ts`: non-Beam-origin fixture gets no response; Beam-origin fixture gets a well-formed response | B |
| AC7 | Full guided flow reaches "Connected" with no manual paste | Hybrid — Playwright MV3 extension context, `context.addCookies()` seeding (OI-1-probed technique reused from sibling plan) | `cd apps/web && npm run test:e2e` — full wizard flow: no extension → install (synthetic proxy) → sign in (seeded cookie) → connect → "Connected" | B |
| AC8 | ToS warning always shown on Step 4, both fresh-connect and short-circuit paths | Fully-Automated | `cd apps/web && npm run test:e2e` — asserts `<LinkedInTosWarning />` (VALIDATE-added shared component) text visible in both paths | B |
| AC9 | Firefox/Safari: dead-end, no broken install CTA | Fully-Automated | `cd apps/web && npm run test:e2e` — simulate extension-API-absent, asserts zero install CTA in DOM | B |
| AC10 | Already-fully-set-up short-circuit lands on Step 4 | Fully-Automated | `cd apps/web && npm run test:e2e` — seed both signals true, asserts Step 4 is first rendered step | B |
| AC11 | Reconnect (stale session) uses identical wizard/Step 4 flow as first connect | Hybrid — same Playwright extension harness as AC7 | `cd apps/web && npm run test:e2e` — seed "connected but stale" account, asserts short-circuit to Step 4 reconnect, identical message flow | B |
| AC12 | Manual paste form remains reachable inside and outside the wizard | Fully-Automated | `cd apps/web && npm run test:e2e` — existing manual-form submit unmodified + new fallback-link-from-wizard assertion | B |
| AC13 | Permission-transparency copy precedes the install CTA | Fully-Automated | `cd apps/web && npm run test:e2e` — asserts copy block present/visible on the step preceding the install CTA | B |
| D8 non-regression | Hook refactor does not regress the sibling feature's shipped card behavior | Fully-Automated (regression) | `cd apps/web && npm run test:e2e` (extended `linkedin-outreach-extension.spec.ts`) — existing sibling AC6/AC7/AC9 assertions re-run unmodified | B |
| D3 step-derivation (VALIDATE addition) | Pure step-index computation is deterministic and testable without a DOM/wall-clock | Fully-Automated | `cd apps/web && npm run test` (Vitest, existing node-env lane) — `computeWizardStepIndex()` branch coverage | B |
| Manifest unchanged (Security Checklist item 5) | Zero new permissions/host_permissions/externally_connectable matches | Fully-Automated | `git diff apps/extension/manifest.json` (expect empty or version-bump only) | B |
| Zero `apps/api/**` touched (D11) | Backend contract frozen | Fully-Automated | `git diff --name-only --cached -- apps/api/` scoped to this plan's own changeset (expect empty) — per plan's Zero-`apps/api/`-proof scoping note, a bare unscoped `git diff` is NOT valid proof given concurrent unrelated dirty `apps/api/` files in this worktree | B |

gap-resolution legend:
- A — proven now (gate passes in this cycle)
- B — fixed in this plan (gate added by this plan's checklist; pre-EXECUTE, so every row reads as "will be proven at EXECUTE's regression pass" — consistent with the sibling plan's own pre-EXECUTE convention)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

C-4 reconciliation: all rows above use the 3 proving strategies (Fully-Automated / Hybrid). No row
uses Known-Gap as a strategy — see Known Gaps section below for the one genuinely out-of-scope
item (Chrome Web Store distribution nuances, inherited from the sibling plan, not new here).

Failing stubs (Fully-Automated rows only — one representative stub per new test file; full
per-scenario stubs are enumerated in the plan's Implementation Checklist Steps 1/3/7):

```
// apps/extension/test/connect-logic.test.mjs (extends existing file)
test("AC5: checkLinkedInSignedIn never returns a cookie key", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: checkLinkedInSignedIn returns {signedIn:true} with no cookie key")
})
```
```
// apps/web/src/lib/use-linkedin-extension-status.test.ts (new file)
test("computeWizardStepIndex: extension+signedIn -> step 3", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: computeWizardStepIndex(true, true, true) === 3")
})
```
```
// apps/web/e2e/linkedin-connect-wizard.spec.ts (new file)
test("AC1: Step 1 auto-passes on Chrome/Edge, no extension installed", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: wizard opens directly on Step 2 with no click")
})
```

Legacy line form (retained for existing validate-contract consumers):
- apps/extension (probe, unit + e2e): Fully-automated: `cd apps/extension && npm test` | Hybrid: `cd apps/extension && npm run test:e2e` (zero-infra static-server harness, confirmed runnable in this sandbox) | agent-probe: none required | known-gap: none
- apps/web (wizard, hook, page.tsx refactor): Fully-automated: `cd apps/web && npm run test` (Vitest, pure-logic) + `cd apps/web && npx tsc --noEmit` + `cd apps/web && npm run lint` | Hybrid: `cd apps/web && npm run test:e2e` (env-blocked in THIS validate sandbox — no docker, so no Postgres, so the backend leg of the webServer config cannot fully start; valid and expected to run in a real dev/CI environment with docker-compose up) | agent-probe: none required (AC4's bringToFront concern was resolved via source-reading, not deferred to agent-probe) | known-gap: none
- backend regression: N/A — zero `apps/api/**` files in this plan's scope (D11)

Dimension findings:
- Infra fit: CONCERN → resolved via plan fix. (1) Hook location definitively resolved to `apps/web/src/lib/` (re-confirmed live: no `src/hooks/` dir exists; `use-auth-safe.ts`/`use-billing.ts` already live in `src/lib/`, confirming this IS the hooks convention here). (2) `apps/web/vitest.config.ts` DOES exist (plan's stated uncertainty was stale) but is `environment: "node"` with no jsdom/testing-library — cannot render the hook directly; fixed by extracting a pure `computeWizardStepIndex()` function into the existing Vitest lane instead of adding new test-infra dependencies (YAGNI-respecting). (3) `apps/extension/e2e` confirmed runnable in this validate sandbox (zero-infra Python static server, no Docker/Postgres dependency) — genuinely testable, not aspirational. (4) `apps/web && npm run test:e2e` confirmed environment-blocked in THIS sandbox specifically (no `docker` binary present → cannot start Postgres → the webServer's backend uvicorn leg cannot fully serve DB-backed routes) — this is a sandbox limitation, not a design defect; the gate is correctly specified and will run in a real dev/CI environment. Disclosed explicitly rather than silently assumed green.
- Test coverage: CONCERN → resolved via plan fix. All 13 SPEC ACs + the D8 non-regression requirement carry a Fully-Automated or Hybrid gate — no Known-Gap terminal state (Net-Gate vacuous-green ban satisfied). AC2's synthetic-proxy caveat is already honestly documented in the plan (dispatches the CustomEvent directly, proving the wizard's REACTION not Chrome's delivery mechanism — the delivery mechanism is separately proven by the FEASIBILITY probe) — confirmed sound, no change needed. AC4's `bringToFront()` claim was independently verified against `playwright-core`'s bundled source (not assumed from training knowledge, not deferred to a probe): Chromium's implementation delegates to CDP `Page.bringToFront` — the actual browser-level tab-activation primitive — giving high confidence this drives a real `visibilitychange`/focus transition, not a synthetic dispatch; documented with an honest residual (Chromium-internal wiring beyond the CDP call itself was not independently re-verified, though this is standard, widely-used Playwright test practice, unlike the FEASIBILITY probe's genuinely novel MV3-injection-timing question). The D3 "60s wall-clock" concern is resolved for the derivable-logic half by extracting `computeWizardStepIndex()` into a Vitest-testable pure function; the actual `setInterval`/`visibilitychange`/`focus` DOM wiring remains e2e-only (Hybrid), an accepted and correctly-scoped residual, not an infra hole.
- Breaking changes: CONCERN → resolved via plan fix (the most significant finding of this VALIDATE pass). D8's "ONE shared hook consumed by both the card and the wizard" was architecturally underspecified: the Touchpoints section's original wizard signature (`{open, onOpenChange}`) implied the wizard would call `useLinkedInExtensionStatus()` itself — but Radix `Dialog`'s `Presence` semantics (confirmed via `@radix-ui/react-dialog` source: `present = forceMount || context.open`, and this repo's `dialog.tsx` passes no `forceMount`) mean the wizard unmounts on close but is fully mounted ALONGSIDE the always-mounted card while open. Two live hook instances would each independently call `register-nonce`, and the extension's `nonceByTabId` Map (`connect-logic.js`) is last-write-wins per `tabId` — so the D7 popup-relay response (signed with whichever nonce was registered LAST) would be silently rejected by the OTHER consumer's nonce check. This is a real, user-visible regression-class bug against the sibling feature's already-shipped D10 nonce mechanism, not a style nit. FIXED directly in the plan: `page.tsx` becomes the single call site; the wizard receives hook state as props (D8, Touchpoints, new Security Checklist item 6). The existing card's non-regression requirement (identical rendered behavior, sibling test suite re-run) was already well-specified in the plan and confirmed sound by reading the actual `page.tsx` lines 178-225 and the sibling's `linkedin-outreach-extension.spec.ts` (confirmed its AC6 test does exercise the exact nonce-mismatch path this plan's fix protects).
- Security surface: CONCERN → resolved via plan fix + adversarial confirmation, no FAIL. **No-nonce reasoning on the D6-only `beam-session-check` leg: adversarially re-evaluated and found SOUND.** A non-Beam-origin page cannot reach `onMessageExternal` at all (Chrome gates delivery on `externally_connectable.matches`). A co-resident malicious EXTENSION also cannot reach it: this manifest's `externally_connectable` has no `ids` field, and Chrome's documented default for an unset `ids` is that no other extension may connect — confirmed against the manifest read in this session (only `matches` is set). **Oracle question, adversarially checked:** the probe cannot be used as a cross-origin information-leak oracle by an untrusted page or extension for the reasons above; the one real residual is narrower and pre-existing — an XSS-compromised Beam-origin page could call the probe (same as it already could call the full `beam-connect-request`, which leaks the actual cookie, a strictly WORSE outcome) — this matches the sibling plan's already-accepted threat-model exclusion ("the dumb-pipe architecture assumes the Beam page itself is trustworthy... XSS is a different, unaddressed threat class outside this plan's scope") and introduces no NEW threat class, only a strictly smaller instance of an already-accepted one. New Security Checklist items 6 (single-hook-instance requirement) and 7 (oracle analysis) added to the plan text with this reasoning, not silently assumed.
- Section: shared hook (`use-linkedin-extension-status.ts`) — CONCERN → resolved via plan fix (see Breaking Changes above; single-call-site fix + pure-function extraction for testability).
- Section: wizard component (`linkedin-connect-wizard.tsx`) — CONCERN → resolved via plan fix (props-based hook consumption; ToS banner extraction lock-in, see Infra/Breaking Changes).
- Section: page.tsx refactor — PASS, confirmed by reading the actual current file (lines 178-225 detection `useEffect`, lines 352-384 extension-detected block) — the plan's description of what to lift matches the real code exactly; non-regression requirement is well-specified and now backed by the single-hook-instance fix.
- Section: extension probe (`background.js`/`connect-logic.js`) — PASS. The proposed `checkLinkedInSignedIn(chromeApi)` extraction is mechanically straightforward given the existing `readLinkedInSession()` structure (confirmed by reading the actual file — a shared not-signed-in branch is trivially factorable); the new `onMessageExternal` branch is additive and matches the existing `register-nonce`/`beam-connect-request` branch pattern exactly.
- Section: test-coverage plan — CONCERN → resolved via plan fix (Vitest lane correction, bringToFront confirmation, environment-blocked gate disclosure — see Test coverage dimension above).

Known Gaps (not counted as CONCERN/FAIL, pre-classified as accepted residuals):
- Chrome Web Store distribution-specific install behavior — inherited unchanged from the sibling
  plan's FEASIBILITY VERDICT known-gap ("true `onInstalled` reason `install` behavior... not
  directly staged"); this plan's Step 2 copy already avoids promising silent auto-detection (D1),
  so this residual does not affect this plan's correctness, only the rejected D13 remedy (already
  backlogged).
- `apps/extension/e2e` and the extended `apps/web/e2e` suites remain local-only, not CI-wired —
  matches the sibling feature's already-accepted `apps/pixel`/`apps/extension` precedent (see
  sibling plan's own accepted Open Gap), not a new defect introduced by this plan.

Open gaps:
- `cd apps/web && npm run test:e2e` (and the extended `linkedin-outreach-extension.spec.ts`
  regression re-run) cannot be executed to completion in THIS validate session's sandbox — no
  `docker` binary present, so Postgres cannot be started, so the Playwright config's backend
  `webServer` leg (`uvicorn` on :8000) cannot fully serve DB-backed dashboard routes. This is an
  execution-environment fact about the current sandbox, not a defect in the gate's design — the
  gate is correctly specified and is expected to run green in a normal dev machine or CI runner
  with `docker compose -f infra/docker-compose.yml up -d postgres redis` available. EXECUTE must
  run in an environment where this is available before claiming these specific rows CODE DONE.
- The wizard's `LinkedInConnectWizard` prop contract (post-VALIDATE-fix) is now a two-consumer
  contract surface shared only via `page.tsx`'s single call site — any future third consumer of
  `useLinkedInExtensionStatus()` would need the same single-call-site discipline; flagged as a
  maintenance note for future changes, not a blocker now.

What this coverage does NOT prove:
- AC2's synthetic-proxy test proves the wizard's REACTION to the `beam-extension-detected` signal,
  not Chrome's actual delivery mechanism for that signal on a real install — the delivery
  mechanism itself (reload-based, D1) was separately, empirically proven by the FEASIBILITY probe
  (NOT-VIABLE for silent detection without reload), not by this plan's e2e suite. Documented in
  the plan's own Automation-realism note; not a silently-dropped gap.
- AC4's `bringToFront()` gate proves real CDP-level tab activation is invoked, with high confidence
  this drives real visibility/focus transitions — it does not independently re-derive Chromium's
  internal `Page.bringToFront` → renderer visibility-state wiring from source beyond confirming the
  CDP call itself is issued (standard, widely-relied-upon Playwright practice, not re-verified at
  the Chromium C++ layer).
- AC6/AC7/AC11's Hybrid MV3-harness gates prove the mechanism against a fake, locally-seeded
  `li_at` cookie and a zero-infra static fixture dashboard — they do not prove behavior against a
  *real* LinkedIn session or the real getbeam.fyi/localhost:3000 Next.js dashboard rendering
  (Phase Completion Rules already require a human VERIFIED step for this, inherited from the
  sibling plan's own residual).
- The new Security Checklist item 7 oracle analysis proves the probe is unreachable by a
  non-Beam-origin page or a co-resident extension (structural, Chrome-platform-level); it does NOT
  address an XSS-compromised Beam-origin page, which is an explicitly out-of-scope threat class
  inherited from the sibling plan's own dumb-pipe threat model, not newly introduced or newly
  excluded here.
- `git diff --name-only --cached -- apps/api/` proves no staged files under `apps/api/` in THIS
  plan's own changeset — it does not prove no `apps/api/` file was ever touched during EXECUTE and
  later reverted; the plan's own scoping note already requires documenting which exact diff method
  was used when this gate runs.
(Required until C3 is implemented — temporary C3 mitigation)

Gate: PASS (no FAILs found; 4 CONCERNs found across Infra fit/Test coverage/Breaking changes/
Security surface, all 4 resolved via direct plan-text fixes during this VALIDATE pass — the
double-hook-instance nonce bug (Breaking Changes, most significant), the hook-location + Vitest-lane
+ AC4-CDP-confirmation items (Infra fit/Test coverage), and the security checklist additions
(items 6/7, Security surface) — no gap required deferral to CONDITIONAL/user-acceptance; the one
disclosed environment limitation (`apps/web` e2e not runnable in THIS sandbox) is a non-blocking
Open gap, not a CONCERN, since the gate itself is correctly specified and will run in a normal
dev/CI environment)
Accepted by: session (VALIDATE, 26-07-26) — no CONDITIONAL acceptance was required; all 4 CONCERNs
were resolved by direct plan-text fixes rather than left open for user acceptance. The one
disclosed Open gap (sandbox e2e environment limitation) does not require acceptance since it does
not change the gate's PASS status — it is an execution-environment fact, not a plan defect.

## Autonomous Goal Block

SESSION GOAL: Ship the guided 4-step LinkedIn extension onboarding wizard (browser check →
install → LinkedIn sign-in → connect), auto-advancing on tab-return, reusing the sibling
extension's D6 message channel plus one new read-only `beam-session-check` probe — zero backend
changes, zero new extension permissions.
Charter + umbrella plan: N/A — single COMPLEX plan (no phase program / umbrella).
Autonomy: standard /goal autonomous execution rules apply once EXECUTE begins — CONDITIONAL EVL
findings get fixed and retried; BLOCKED items go to backlog with a note and execution continues on
the remaining steps; irreversible/outward-facing actions require explicit human action and are
never auto-performed (this plan has none — the extension is already shipped/unpacked-installable;
no new Chrome Web Store submission action is part of this plan's scope).
Hard stop conditions / safety constraints:
- Never add the "scripting" permission or any other new manifest permission/host_permission/externally_connectable match (D13 rejected, Security Checklist item 5) — any manifest diff beyond a version bump is a hard stop.
- Never let the `beam-session-check` probe's response shape include a `cookie` or `userAgent` field on either branch (AC5, Security Checklist item 1) — any such field found in review is a hard stop until removed.
- Never call `useLinkedInExtensionStatus()` from more than one call site (page.tsx only) — the wizard must receive hook state as props (D8, Security Checklist item 6); any second call site is a hard stop, return to PLAN.
- Never promise silent auto-detection in Step 2's install copy (D1, FEASIBILITY NOT-VIABLE) — any copy implying "we'll detect it automatically" for the install step is a hard stop until reworded.
- Never remove or weaken the ToS warning on Step 4, and never let Step 4 be reachable without it rendering first (AC8) — any such path is a hard stop.
- Never touch apps/api/** (D11, backend contract frozen) — any change there is a hard stop.
Next phase: EXECUTE — process/features/campaigns-outreach/active/linkedin-extension-onboarding_26-07-26/linkedin-extension-onboarding_PLAN_26-07-26.md, Implementation Checklist Steps 1-8 in order (Steps 1-2 extension probe must land before Step 3 hook; Steps 4-5 wizard+card integration before Step 6 copy and Step 7 tests).
Validate contract: inline in this plan file (## Validate Contract section above) — Gate: PASS, 26-07-26.
Execute start: fully-auto commands: `cd apps/extension && npm run build && npm test`, `cd apps/web && npx tsc --noEmit`, `cd apps/web && npm run lint`, `git diff apps/extension/manifest.json` (expect empty/version-bump only) | e2e spec: `cd apps/extension && npm run test:e2e` (confirmed runnable, zero-infra) + `cd apps/web && npm run test:e2e` (requires `docker compose -f infra/docker-compose.yml up -d postgres redis` first — env-blocked in the VALIDATE sandbox, must be available at EXECUTE time) | probe scenario: none required (D1's silent-detection question already empirically resolved NOT-VIABLE by FEASIBILITY; AC4's bringToFront question resolved via playwright-core source in this VALIDATE pass) | high-risk pack: yes — auth/identity-adjacent (LinkedIn session cookie, same class as the sibling feature), manual-first evidence pack recommended before treating the plan as fully proven, matching the sibling plan's own precedent.

## Next Step

Validate-contract written — Gate: PASS. Say **ENTER EXECUTE MODE** to begin implementation of
Implementation Checklist Steps 1-8 in order. Read the VALIDATE-added D8 single-hook-instance fix
(Touchpoints + Security Checklist item 6) and the shared `<LinkedInTosWarning />` extraction
before starting Steps 3-4 and Step 6 — they are required parts of the implementation, not optional
hardening.
