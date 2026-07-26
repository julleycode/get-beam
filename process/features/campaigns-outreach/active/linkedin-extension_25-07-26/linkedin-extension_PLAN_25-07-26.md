---
name: plan:linkedin-extension
description: "Chrome/Edge extension (apps/extension/) that replaces manual DevTools li_at cookie-copy with one-click LinkedIn outreach connect via a 'dumb pipe' to the existing dashboard tab — no backend change; v1 targets Chrome Web Store submission readiness"
date: 25-07-26
feature: campaigns-outreach
phase: "n/a — single COMPLEX plan"
---

# LinkedIn Outreach Connect Extension — PLAN

Date: 25-07-26
Status: CODE DONE — in testing (keep active). RESEARCH/SPEC/INNOVATE/PLAN/VALIDATE(Gate: PASS)/
EXECUTE/EVL all complete (25-07-26); shipped in commits `89d924d` (feat) + `646689e` (process).
Remaining before archival: human VERIFIED sign-off against a real LinkedIn session, 3 dev-stack-gated
`apps/web/e2e` cases (AC6 dashboard leg/AC7/AC9), the Postgres-gated backend regression, real
`KNOWN_EXTENSION_ID` + icon, and Chrome Web Store submission (Step 9). See
`linkedin-extension_REPORT_25-07-26.md` (UPDATE PROCESS closeout, 25-07-26) and backlog note
`process/features/campaigns-outreach/backlog/linkedin-extension-dev-stack-gates_NOTE_25-07-26.md`
for full detail. Do NOT archive to `completed/` until those residuals clear.
Complexity: **COMPLEX** (new user-facing runtime surface — a browser extension — security-sensitive cross-origin messaging, multi-file, new test infra, Chrome Web Store submission workstream).
Spec: `process/features/campaigns-outreach/active/linkedin-extension_25-07-26/linkedin-extension_SPEC_25-07-26.md`

## Overview

Today, enabling LinkedIn outreach requires a user to find and copy a `li_at` cookie via browser
DevTools and paste it into a dashboard form — a real drop-off point for non-technical users. This
plan builds a Chrome/Edge (MV3) browser extension that reads the cookie itself and hands it to the
already-open Beam dashboard tab over a locally-scoped message channel, which then calls the
existing, unchanged backend endpoint. The manual form remains as a permanent fallback. See
`process/context/all-context.md` for repo architecture and `process/context/tests/all-tests.md` for
the test runners and commands used throughout the Verification Evidence section below.

## TL;DR

Build `apps/extension/` (vanilla JS MV3, esbuild, mirrors `apps/pixel/`). Extension reads `li_at` +
UA from `*.linkedin.com` via `chrome.cookies`, hands both to the open Beam dashboard tab over
`externally_connectable` (primary) or a content-script `postMessage` relay (popup path). Dashboard
page (`social-accounts/page.tsx`) gets a new "Connect with extension" button that detects the
extension, verifies the sender, and calls the **existing unchanged** `enableLinkedInOutreach()` /
`POST .../outreach-connect`. Backend is untouched. Ship order: functional build → unpacked-build
validation → Chrome Web Store submission prep (separate late workstream, because store review is
slow and can reject).

---

## Locked Decisions (carried from SPEC + INNOVATE — do not reopen in EXECUTE)

| # | Decision | Source |
|---|---|---|
| D1 | Extension is a "dumb pipe" — never holds a Clerk JWT, never calls Beam API directly | SPEC Constraints |
| D2 | Backend contract frozen: reuse `POST /api/v1/social/accounts/linkedin/outreach-connect` + `GET .../outreach-status` unchanged | SPEC AC2 |
| D3 | Chrome + Edge (MV3) only for v1; Firefox/Safari show only the existing manual form | SPEC Out of Scope |
| D4 | Primary trigger = in-page "Connect with extension" button on the social-accounts LinkedIn card; secondary = extension popup "Connect now" (covers AC4 tab-not-open case) | INNOVATE Decision Summary |
| D5 | Detection = content script auto-injects a CustomEvent (+ DOM-attribute fallback for first paint) | INNOVATE Decision Summary |
| D6 | Primary data channel = `chrome.runtime.sendMessage(KNOWN_EXTENSION_ID, ...)` via `externally_connectable`; background service worker replies on the same channel (scoped to the initiating tab by construction) | INNOVATE Decision Summary |
| D7 | Secondary (popup) channel = popup → `chrome.tabs.sendMessage` → content script → one `window.postMessage` hop into page JS, origin+source+**nonce**-checked on the page side (nonce added by VALIDATE — see D10) | INNOVATE Decision Summary + VALIDATE hardening |
| D8 | Repo layout = `apps/extension/`, mirroring `apps/pixel/` (vanilla JS, esbuild, own Playwright config with a persistent context loading the unpacked build) | INNOVATE Decision Summary |
| D9 | v1 ships to the Chrome Web Store (not just unpacked) — store-readiness is a distinct late workstream, sequenced after functional validation | User (25-07-26, locked scope decision) |
| D10 | The D7 popup/postMessage channel carries a per-page-load random nonce, minted by the dashboard page and registered with the extension exclusively over the Chrome-sender-verified D6 channel, so a co-resident copy-cat extension cannot forge a valid D7 response (resolves OI-3 — see Security Checklist item 2 and Public Contracts) | VALIDATE (25-07-26) — plan supplement, required for AC6 |

---

## Touchpoints

### NEW — `apps/extension/` (new package, mirrors `apps/pixel/` layout)

| File | Purpose |
|---|---|
| `apps/extension/manifest.json` | MV3 manifest: `permissions: ["cookies"]`, `host_permissions: ["*://*.linkedin.com/*", ...BEAM_ORIGINS patterns (e.g. "https://getbeam.fyi/*", "http://localhost:3000/*", staging origin)]`, `externally_connectable: {matches: [beam-origins]}`, `content_scripts` matched to Beam origins, `background.service_worker`, `action.default_popup`. **OI-2 RESOLVED by VALIDATE:** no `tabs` permission needed. `chrome.tabs.query({url: ...})` populates the `url`/`title` fields of returned tabs once the extension holds a matching `host_permissions` entry for that origin (Chrome MV3 permissions model) — adding BEAM_ORIGINS to `host_permissions` is strictly smaller and more Chrome-Web-Store-review-friendly than the broad `tabs` permission (which grants title/url visibility into every open tab on every site), and satisfies Security Checklist item 4's minimal-permission bar. |
| `apps/extension/src/background.js` | Service worker. Listens on `chrome.runtime.onMessageExternal` (D6 primary channel) and `chrome.runtime.onMessage` (popup relay, D7). Handler: `chrome.cookies.get({url: "https://www.linkedin.com", name: "li_at"})` + `navigator.userAgent`-equivalent (service workers have no `navigator.userAgent` in the page sense — use `self.navigator.userAgent`, confirm in step 2). Replies `{ok: true, cookie, userAgent}` or `{ok: false, reason: "not_signed_in"}` on the SAME message port (structurally scoped to the initiating tab/sender — no broadcast). Never logs cookie/UA (SPEC AC8). **VALIDATE addition (D10/OI-3 resolution):** also handles `{type: "register-nonce", nonce}` on the D6 channel (Chrome-sender-verified — only a genuine Beam-origin page can call this), storing `nonce` keyed by `sender.tab.id` in an in-memory `Map`; when relaying a D7 popup-triggered response to `content.js`, includes the nonce registered for that `tabId` in the outgoing payload. |
| `apps/extension/src/content.js` | Injected only on Beam origins (dev/staging/prod — see `apps/extension/src/known-origins.js`). Two jobs: (a) detection marker — dispatch `CustomEvent("beam-extension-detected")` + set `document.documentElement.dataset.beamExtension = "1"` as DOM-attribute fallback for first paint (D5); (b) popup-relay listener — `chrome.runtime.onMessage` from the popup, forwards via a single `window.postMessage({source: "beam-extension", nonce, ...}, beamOrigin)` call into the page (D7). **VALIDATE addition:** `content.js` never generates or inspects the `nonce` — it only passes through whatever `background.js` attached, since background→content is a same-extension Chrome-enforced channel and content→page is the only page-readable leg. |
| `apps/extension/src/popup.html` + `apps/extension/src/popup.js` | Secondary trigger (D4). Shows connection state, "Connect now" button. On click: `chrome.tabs.query({url: beamOriginPatterns})` → if no matching tab, show "open your Beam dashboard tab" message (SPEC AC4) → else `chrome.tabs.sendMessage(tabId, {type: "beam-connect-request"})` to that tab's content script. |
| `apps/extension/src/known-origins.js` | Shared constant module: `KNOWN_EXTENSION_ID` placeholder (real value assigned at Chrome Web Store listing creation — see Open Item OI-4) + `BEAM_ORIGINS` array (`https://getbeam.fyi`, dev `http://localhost:3000`, staging origin — confirm exact staging hostname in step 1 research). Imported by `content.js`; mirrored (NOT imported, see Blast Radius note) into the dashboard-side constant. |
| `apps/extension/scripts/build.js` or `package.json` esbuild script | Mirrors `apps/pixel/package.json`'s `build`/`size` scripts — one esbuild invocation per extension JS entry point (background, content, popup), `--target=es2017`, MV3-safe (no dynamic `import()` in service worker unless `type: "module"` is set in manifest — confirm in step 2). |
| `apps/extension/package.json` | `devDependencies`: `@playwright/test`, `esbuild` (pin same versions as `apps/pixel/package.json`: `^1.60.0` / `0.24.0`). Scripts: `build`, `test`, `test:e2e`. |
| `apps/extension/playwright.config.ts` | New — Playwright's persistent-context pattern for loading an unpacked MV3 extension (`chromium.launchPersistentContext(userDataDir, {args: ["--disable-extensions-except=...", "--load-extension=..."]})`). **OI-1 RESOLVED by VALIDATE (empirical probe, 25-07-26):** confirmed viable — see Verification Evidence AC1 note. |
| `apps/extension/e2e/*.spec.ts` + `apps/extension/e2e/fixtures/*.html` | Mirrors `apps/pixel/e2e/` structure. See Verification Evidence for the AC→spec map. |
| `apps/extension/README.md` | Install instructions (unpacked dev build) + store-submission notes (permission justifications, privacy policy pointer) — populated fully in the store-readiness step. |

### MODIFY — `apps/web/src/app/dashboard/social-accounts/page.tsx`

- Add `useEffect` extension-detection listener: listens for `CustomEvent("beam-extension-detected")` AND checks `document.documentElement.dataset.beamExtension === "1"` on mount (covers both the event-timing race and first-paint case per D5). Sets `extensionDetected` state.
- Conditionally render a new "Connect with extension" / "Refresh connection" button inside the existing `LinkedIn outreach` `Card` (same card as the manual form at ~line 188-309), positioned above or alongside the manual `<form>` — manual form stays untouched and always renders (SPEC: extension is additive, never a replacement).
- New handler for the primary channel (D6): `chrome.runtime.sendMessage(KNOWN_EXTENSION_ID, {type: "beam-connect-request"}, (response) => {...})`. Guard: `typeof chrome !== "undefined" && chrome.runtime` (extension APIs only exist when the extension is installed; page JS calling `chrome.runtime.sendMessage` with an explicit extension ID works even without the extension installed on Chrome — it just errors/no-ops, must wrap in try/catch and treat as "not detected").
- **VALIDATE addition (D10):** on mount, once extension detection succeeds, generate a random nonce (e.g. `crypto.randomUUID()`) and send it to the extension via the SAME D6 channel: `chrome.runtime.sendMessage(KNOWN_EXTENSION_ID, {type: "register-nonce", nonce})`. Keep the nonce in component state (never expose it in the DOM/a CustomEvent — it must only ever travel over the Chrome-sender-verified D6 channel until the single controlled reveal in the D7 response).
- New handler for the secondary/popup channel (D7): `window.addEventListener("message", handler)` where `handler` verifies `event.origin === window.location.origin` (or the exact expected content-script injection origin) AND `event.data?.source === "beam-extension"` AND **`event.data?.nonce === the nonce this page generated and registered`** before trusting the payload (SPEC AC6 — dashboard must reject anything not verifiably from the known extension). **OI-3 RESOLVED by VALIDATE:** origin+source-string checking alone is NOT sufficient for the D7 path — a locally co-resident malicious extension with its own `content_scripts.matches` on a Beam origin runs in the SAME page context, so `event.origin` would legitimately read as the Beam origin and the `source: "beam-extension"` string is public/reverse-engineerable from the shipped bundle; such an extension could forge or replay a fake response. The D6-registered nonce (never exposed on any page-readable surface until the one legitimate response) closes this: a copy-cat extension cannot predict it. This mitigation defeats **forgery** (satisfies AC6's literal requirement that a copy-cat extension "cannot trigger the same flow"). It does NOT fully close a narrower residual: `window.postMessage` broadcasts to every listener on the page, so a malicious co-resident extension COULD still *observe* (not forge) a legitimate in-flight D7 transfer at the exact moment it occurs. This residual is accepted for v1 — it does not exceed the general "a malicious extension is installed" threat model any MV3 cookie-reading extension already lives with, and the PRIMARY trigger (D6, used in the common case per D4) has no such exposure at all. Documented here, not silently dropped.
- On successful response from either channel: call the **existing unchanged** `api.enableLinkedInOutreach(cookie, userAgent)` mutation (already wired at ~line 222-229) — no new API client method needed.
- Preserve the ToS warning banner unconditionally (already renders above the form at line 204-208; extension button must render inside/after this, never before or bypassing it — SPEC AC7).
- No `console.log`/logger call anywhere in the new code path that includes the cookie or UA value (SPEC AC8) — response handler must not log the raw `response` object.
- Add a `KNOWN_EXTENSION_ID` + Beam-origin-verification constant on the dashboard side (mirrors `apps/extension/src/known-origins.js` — see Blast Radius note below for why these are NOT a shared imported module).
- Firefox/Safari (SPEC AC9): no `chrome` global exists — the detection guard above naturally no-ops; only the manual form renders. No separate branch needed, but add one explicit code comment marking this as the AC9 guarantee so a future refactor doesn't accidentally add a broken "install extension" prompt for unsupported browsers.
- **VALIDATE addition (infra gap found — execute-agent instruction, not a plan-fix):** `apps/web` has no `@types/chrome` (or any chrome-extension ambient types) anywhere in the repo today, and the codebase convention is TypeScript strict mode / no `any` (`process/context/all-context.md`). Referencing the global `chrome` object in `page.tsx` needs either (a) add `@types/chrome` as a new `apps/web` devDependency, or (b) a small local ambient declaration file (e.g. `apps/web/src/types/chrome-extension.d.ts`) declaring only the minimal shape used (`chrome.runtime.sendMessage`, `chrome.runtime.lastError`). Prefer (b) — smaller footprint, avoids pulling a full chrome-types package into a Next.js app that has no other chrome-extension surface. Execute-agent: pick one, do not skip typing this as `any`.

### Blast Radius note — why `known-origins.js` is duplicated, not shared

`apps/extension/` and `apps/web/` are two separate build/deploy targets (extension bundle vs Next.js
app) with no existing shared-package plumbing between them (no `packages/shared` in this repo's
`apps/` layout). Do NOT introduce a new cross-app import path or workspace package for this single
constant — that would expand blast radius into build tooling. Instead: the same two literal values
(`KNOWN_EXTENSION_ID`, `BEAM_ORIGINS`) are defined independently in both places with a code comment
in each pointing at the other ("keep in sync with apps/extension/src/known-origins.js"). This is a
deliberate small-drift-risk tradeoff, not an oversight — flag in Test Infra Improvement Notes.

---

## Public Contracts

- **No new backend endpoint, schema, or CORS change** (D2, locked). This plan touches ZERO files under `apps/api/`.
- **New browser-extension-to-page contract** (not a backend contract, but a real interface other code must respect going forward):
  - Message shape: `{type: "beam-connect-request"}` in, `{ok: boolean, cookie?: string, userAgent?: string, reason?: string}` out (primary D6 channel) or `{source: "beam-extension", nonce: string, ok, cookie?, userAgent?, reason?}` (D7 postMessage channel — `nonce` added by VALIDATE, see D10/OI-3; needs a `source` discriminator since `window.postMessage` has no separate channel typing).
  - New D6-only message: `{type: "register-nonce", nonce: string}` — dashboard → extension, no reply expected (added by VALIDATE, D10).
  - `KNOWN_EXTENSION_ID` becomes a real contract the moment the extension is published — the dashboard's `chrome.runtime.sendMessage(KNOWN_EXTENSION_ID, ...)` call hardcodes it. **This ID does not exist until the extension is first uploaded (even as a draft) to the Chrome Web Store Developer Dashboard** — see Open Item OI-4, this blocks final wiring of the dashboard-side constant.
- **`existing` contract reused unchanged**: `api.enableLinkedInOutreach(sessionCookie, userAgent, label?)` → `POST /api/v1/social/accounts/linkedin/outreach-connect` (`apps/web/src/lib/api.ts:989`). Confirmed identical request shape; no client-side change to this method.

---

## Blast Radius

| Surface | Files | Risk class |
|---|---|---|
| NEW package `apps/extension/` | ~10-12 new files (manifest, background, content, popup×2, known-origins, build config, package.json, playwright config, e2e specs+fixtures, README) | New runtime surface; cookie-reading extension = elevated review bar, but reuses an existing secret-handling discipline (never log/store) already proven in `apps/api` |
| `apps/web/src/app/dashboard/social-accounts/page.tsx` | 1 file, additive changes only (~70-110 new lines: detection effect, nonce registration, 2 message handlers, 1 conditional button block, 1 constants block) | Medium — new cross-origin messaging surface on an existing authenticated page; existing manual form path is untouched (regression risk is low but must be explicitly verified — see AC9 test) |
| Backend (`apps/api/**`) | 0 files | None — explicitly out of scope (D2) |
| Total distinct files touched/created | ~11-13 | High-risk class present: **auth/identity-adjacent** (LinkedIn session cookie handling) and **trust-boundary/secrets logic** (per orchestration.md High-Risk Classes) — requires Hybrid-minimum test tier throughout, satisfied below |

No schema, no migration, no new public backend API surface, no billing/credits touch.

---

## Security Checklist (derived from SPEC AC5 / AC6 / AC8)

1. **Cookie only reaches the legitimate Beam origin.** Enforced structurally by `externally_connectable.matches` in the manifest scoping which pages may even open a channel to the extension (Chrome enforces this natively for the primary D6 channel — a page NOT in `matches` cannot call `chrome.runtime.sendMessage(KNOWN_EXTENSION_ID, ...)` and get a response at all). For the D7 popup/content-script path, `content.js` itself is only injected into `BEAM_ORIGINS` matches (via `content_scripts.matches`), so a malicious page cannot receive the relayed `postMessage` unless it IS a Beam origin page.
2. **Dashboard verifies the sender before trusting a message.** Primary channel: Chrome's `externally_connectable` sender verification is structural (the dashboard receives replies only from a channel it itself opened to `KNOWN_EXTENSION_ID` — a copy-cat extension has a different ID and the page never targets it). Popup channel: page-side `window.addEventListener("message", ...)` MUST check `event.origin` matches the page's own origin (content script injects same-origin) AND `event.data.source === "beam-extension"` AND **(VALIDATE, D10) `event.data.nonce` matches the nonce this page generated and registered with the extension over the D6 channel** before trusting the payload. **OI-3 RESOLVED:** origin+source alone was judged insufficient — see the page.tsx Touchpoints entry above for the full threat-model writeup (a co-resident copy-cat extension runs in the same page context, defeating origin-check, and the `source` string is publicly known from the shipped bundle). The nonce closes the *forgery* gap (AC6). A narrower residual — a co-resident malicious extension *observing* a legitimate in-flight D7 transfer via postMessage's broadcast nature — is accepted for v1 and documented, not silently dropped; it does not exceed the general "malicious extension installed" threat model and does not affect the D6 primary path at all.
3. **No logging/storage of cookie or UA.** Grep-checkable rule for EXECUTE: zero `console.log`/`logger.*`/`localStorage`/`chrome.storage` calls anywhere in the diff that reference the `cookie`, `response`, or `userAgent` variables from the connect flow. Static check + runtime Playwright assertion (see Verification Evidence AC8 row).
4. **Minimum permission set.** `manifest.json` requests only: `cookies`, `host_permissions: ["*://*.linkedin.com/*", ...BEAM_ORIGINS]` (BEAM_ORIGINS added by VALIDATE to resolve OI-2 — see Touchpoints), `externally_connectable` (not a runtime permission, no user-facing grant). No `<all_urls>`, no `tabs`, no `activeTab` beyond what's needed, no `scripting`.
5. **ToS warning cannot be bypassed via the faster path.** Both connect paths funnel into the same `enableLinkedInOutreach` mutation on the same page below the existing warning banner — there is no code path that calls the backend endpoint without the banner having already rendered on the page (component-level guarantee, not a runtime check — verified by AC7 test).

---

## Acceptance Criteria

This plan implements the 10 SPEC acceptance criteria verbatim (see SPEC file for full text): AC1
one-click connect with extension installed + logged in; AC2 backend contract unchanged; AC3 clear
"not signed in" message, never a silent empty-cookie send; AC4 clear "open your dashboard" message
when no matching Beam tab is open; AC5 cookie never reaches a non-Beam origin; AC6 dashboard
verifies the message came from the known extension before acting; AC7 ToS warning always shown on
the extension path too; AC8 cookie/UA never logged or client-stored; AC9 Firefox/Safari users see
only the existing manual form, no broken UI; AC10 refresh/reconnect uses the identical one-click
flow as first connect. Each is mapped to an exact test gate in Verification Evidence below.

## Phase Completion Rules

This is a single COMPLEX plan (not a phase program) — there is one completion state, not phased
✅/🚧/⏳ status tracking. The plan is **CODE DONE** when Steps 1-8 are implemented and every row in
Verification Evidence is green (Fully-Automated/Hybrid tiers actually passing; Hybrid tiers with a
documented precondition met). It is **VERIFIED** only after a human has confirmed the end-to-end
unpacked-extension flow works against a real signed-in LinkedIn session in a real browser (VALIDATE's
empirical probe confirmed the underlying cookie-read mechanism works — see AC1 note — but that probe
used a fake seeded cookie, not a real LinkedIn session; the one residual real-session confirmation is
still a human step). Step 9 (Chrome Web Store submission prep) is tracked independently and does NOT
gate CODE DONE — per Step 9's note, actual store submission is a separate manual, days-long human
action.

## Implementation Checklist

See "Implementation Steps (ordered)" below — each of the 9 steps is an implementation-checklist
phase with its own explicit gate criteria.

## Implementation Steps (ordered)

Functional build is validated (unpacked) BEFORE store-submission prep begins — store review can
take days and should not gate functional correctness feedback.

### Step 1 — Extension skeleton + package scaffolding
- Create `apps/extension/` directory structure mirroring `apps/pixel/`.
- Write `manifest.json` (MV3, minimal permissions per Security Checklist item 4 — `host_permissions` includes both `*.linkedin.com` and BEAM_ORIGINS per OI-2 resolution; no `tabs` permission).
- Write `package.json` (esbuild + `@playwright/test`, pinned to match `apps/pixel/package.json` versions), build script.
- Confirm exact Beam dev/staging/prod origin hostnames (grep `NEXT_PUBLIC_API_URL` / deploy config) and populate `known-origins.js` `BEAM_ORIGINS` (leave `KNOWN_EXTENSION_ID` as a documented `"PENDING_STORE_LISTING"` placeholder — OI-4).
- **Gate:** `cd apps/extension && npm run build` succeeds; `manifest.json` passes `chrome://extensions` "Load unpacked" with zero manifest errors (manual, cheap-local, one-time smoke — not a repeatable automated gate, done once here to catch structural manifest mistakes early).

### Step 2 — Background service worker: cookie read
- Implement `background.js` `chrome.cookies.get({url: "https://www.linkedin.com", name: "li_at"})`.
- Confirm exact MV3 service-worker API for reading UA (`self.navigator.userAgent` — verify this exists in the MV3 service-worker global scope; if not, UA must come from the content-script/page side instead — this is a mechanical API-shape question, resolve by reading MDN/Chrome docs at implementation time, not by guessing).
- Handle "not signed in" (`cookies.get` returns `null`) → structured `{ok: false, reason: "not_signed_in"}` reply (SPEC AC3).
- **Gate:** AC3 test (extension-side unit test, mocked `chrome.cookies.get` → `null`).

### Step 3 — Primary messaging channel (D6, `externally_connectable`)
- Add `externally_connectable.matches` to manifest.
- Implement `chrome.runtime.onMessageExternal` listener in `background.js` wired to the Step 2 cookie-read logic.
- Implement the `{type: "register-nonce", nonce}` handler (D10) storing nonce keyed by `sender.tab.id`.
- **Gate:** AC1 groundwork — messaging round-trip test (mocked/stubbed, see AC1 Verification Evidence row).

### Step 4 — Dashboard integration (primary channel)
- Modify `social-accounts/page.tsx`: detection `useEffect`, conditional button, `chrome.runtime.sendMessage` handler, wire successful response into existing `outreachMut.mutate()` (adapt to accept extension-sourced cookie/UA instead of only form state — smallest-diff approach: set `liCookie`/`liUserAgent` state from the extension response, then call the same `outreachMut.mutate()` used by the manual form, OR call `api.enableLinkedInOutreach` directly with the extension values; prefer the latter to avoid a submit-through-state race — confirm exact wiring choice in EXECUTE against current component state shape).
- Add dashboard-side sender/origin verification for the primary channel path (structurally satisfied by `externally_connectable`, but add a defensive `chrome.runtime.lastError` check).
- Generate + register the D7 nonce (D10) immediately after successful detection, over the D6 channel.
- Add the `@types/chrome` or local ambient-types fix (see page.tsx Touchpoints entry).
- **Gate:** AC1 (happy path e2e — Hybrid), AC6 (wrong-sender rejection — Fully-Automated), AC7 (ToS banner still shows — Fully-Automated).

### Step 5 — Detection mechanism (D5) + Firefox/Safari fallback (AC9)
- Implement `content.js` injection + `CustomEvent`/DOM-attribute dual detection.
- Confirm dashboard `useEffect` correctly handles: (a) extension present, script already ran before React hydration → DOM attribute path; (b) extension present, script runs after mount → event listener path; (c) extension absent / non-Chromium browser → neither fires, manual form only.
- **Gate:** AC9 (no extension present → only manual form renders, Fully-Automated).

### Step 6 — Popup path (D7, secondary trigger, AC4)
- Implement `popup.html`/`popup.js`: `chrome.tabs.query` for a matching Beam tab (host_permissions now cover BEAM_ORIGINS per OI-2 resolution, so `url`/`title` are populated without the `tabs` permission).
- No matching tab → "open your dashboard" message, no success state (AC4).
- Matching tab found → `chrome.tabs.sendMessage` to that tab's `content.js`.
- Implement `content.js` relay: `chrome.runtime.onMessage` (from popup) → single `window.postMessage({source: "beam-extension", nonce, ...}, targetOrigin)` into the page — `nonce` is the value `background.js` looked up for that `tabId` (D10).
- Add dashboard-side `message` event listener with origin + `source` + **`nonce`** verification (Security Checklist item 2; OI-3 resolved by D10).
- **Gate:** AC4 (Fully-Automated, mocked `chrome.tabs` query), AC10 (refresh/reconnect reuses the identical flow — Hybrid, same harness as AC1).

### Step 7 — Security hardening pass (AC5, AC8, AC6 full coverage)
- Manifest review checklist (Security Checklist item 4) — confirm no `<all_urls>`, no `tabs`, confirm `host_permissions` scoped exactly to `*.linkedin.com` + BEAM_ORIGINS.
- Spoofed-origin test: attempt to trigger the connect flow from a non-Beam-origin page loaded in the same persistent Playwright context; assert extension/dashboard reject it (AC5, AC6).
- **VALIDATE addition:** nonce-forgery test — from a page loaded at a Beam origin (same-origin, simulating a co-resident copy-cat extension's content script), fire a `window.postMessage({source: "beam-extension", ok: true, cookie: "attacker-value"}, origin)` with a missing/wrong `nonce` and assert the dashboard does NOT call `enableLinkedInOutreach` (extends AC6 coverage to the D7 path specifically, per D10).
- Grep-based no-logging check across the full diff (AC8).
- Runtime Playwright assertion: no `chrome.storage` writes occur during a full connect flow (AC8).
- **Gate:** AC5, AC6 (full, including the nonce-forgery scenario), AC8.

### Step 8 — Test infra wrap-up + regression pass
- Run the full `apps/extension/e2e` suite plus the modified `apps/web/e2e` suite (if any existing spec touches `social-accounts` — check for overlap; extend or add a new spec file rather than duplicating).
- Run backend regression (`tests/integration/test_social_accounts_list.py` — the only existing backend test file for this router; see Verification Evidence AC2 note on scope) to prove D2/AC2 — must pass unmodified.
- Run `apps/web` lint (`npm run lint`) on the modified page.
- **Gate:** all Verification Evidence rows green; AC2 regression-run confirmed.

### Step 9 — Chrome Web Store submission prep (separate late workstream, D9)
- Write privacy policy content covering: what data the extension reads (`li_at` cookie value, User-Agent string), where it goes (only the user's own Beam dashboard tab, over a locally-scoped browser message channel — never to a third-party server directly from the extension), and that Beam's existing backend privacy/ToS terms govern what happens after that (link to Beam's existing privacy policy page if one exists — confirm URL in this step; otherwise flag as a prerequisite blocker for submission, not for this plan's functional scope).
- Per-permission justification text for the Chrome Web Store review form: `cookies` (read the LinkedIn session cookie the user explicitly opts into sharing), `host_permissions: *.linkedin.com` (required to read the cookie — HttpOnly, cannot be read by the page) + BEAM_ORIGINS (required to detect the user's own dashboard tab for the popup path, scoped only to Beam's own origins), `externally_connectable` (restrict cross-extension messaging to Beam's own dashboard origins only).
- Store listing assets checklist: 128×128 icon, at least one 1280×800 (or 640×400) promotional/screenshot image, short description (≤132 chars), detailed description, category (Productivity), support/homepage URL.
- Populate `apps/extension/README.md` with both the unpacked-dev-install instructions (already usable after Step 1) and the store-listing metadata for future maintainers.
- **Note (non-gate):** actual submission to the Chrome Web Store Developer Dashboard, obtaining the real `KNOWN_EXTENSION_ID`, and waiting through store review are manual, days-long, human-operator actions outside EXECUTE's scope — EXECUTE's job is to leave the extension submission-ready (all assets, policy text, and justifications written) with the `KNOWN_EXTENSION_ID` placeholder clearly marked as the one remaining manual step. This step never blocks marking the plan CODE DONE.

---

## Open Items — VALIDATE Resolution (25-07-26)

| ID | Question | Resolution |
|---|---|---|
| OI-1 (SPEC OQ5) | Can a `li_at`-shaped `HttpOnly` cookie be simulated such that `chrome.cookies.get` reads it inside a Playwright-loaded MV3 extension? | **RESOLVED — VIABLE.** VALIDATE ran a cheap-local empirical probe (disposable MV3 extension + `chromium.launchPersistentContext` + `context.addCookies()`, no mocked linkedin.com origin needed at all — the fake cookie was seeded directly into the browser's cookie jar with `context.addCookies([{name: "li_at", domain: ".linkedin.com", httpOnly: true, secure: true, ...}])` and read back via `serviceWorker.evaluate(() => chrome.cookies.get(...))`). Result: the extension's service worker read the seeded value exactly as written, with zero navigation to any linkedin.com origin (mocked or real). AC1/AC10 can be fully Hybrid-automated with NO residual manual/agent-probe step for the cookie-read mechanism itself — better than the plan's original assumption of needing a "mocked linkedin.com origin." (A separate, smaller residual remains for full human VERIFIED sign-off against a *real* LinkedIn session — see Phase Completion Rules — but that is expected and does not block CODE DONE.) |
| OI-2 | Does the popup path need the `tabs` permission? | **RESOLVED.** No — add BEAM_ORIGINS to `host_permissions` instead (see Touchpoints/Security Checklist item 4). Smaller, more Store-review-friendly than `tabs`. |
| OI-3 | Is origin+source-string checking enough for the D7 popup channel, or is a nonce needed? | **RESOLVED — nonce required, added as D10.** A co-resident malicious extension with `content_scripts.matches` on a Beam origin runs in the same page context (defeats origin-check) and can read the public `source: "beam-extension"` string from the shipped bundle (defeats the discriminator alone). A D6-registered, never-page-exposed nonce closes the forgery gap and satisfies AC6 for the D7 path. See page.tsx Touchpoints entry and Security Checklist item 2 for the full writeup, including the one accepted residual (broadcast-observability, not forgery, on the D7 path only). |
| OI-4 | `KNOWN_EXTENSION_ID` does not exist until first Chrome Web Store upload | **CONFIRMED acceptable, unchanged.** This is a genuine sequencing dependency, correctly scoped: EXECUTE ships with a clearly-marked placeholder constant; this blocks only the real production wiring (Step 9's manual store-submission action), never CODE DONE. No circular dependency — VALIDATE confirms this sequencing is sound. |

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Playwright extension e2e: unpacked MV3 extension loaded into persistent context, fake `li_at` seeded via `context.addCookies()` (no mocked-origin navigation needed — see OI-1 resolution), dashboard opened, connect clicked, outreach card reaches "connected" | Hybrid — **OI-1 empirically resolved by VALIDATE, no residual realism gap** | AC1 |
| `git diff --name-only -- apps/api/` returns empty (the deterministic proof of "contract unchanged" — D2); `tests/integration/test_social_accounts_list.py` (the only existing backend test file touching this router — confirmed by VALIDATE; it does NOT itself exercise the `outreach-connect`/`outreach-status` endpoints, so it is a courtesy regression check, not endpoint-specific coverage) re-run unmodified and green | Fully-Automated | AC2 |
| Extension unit test: `chrome.cookies.get` mocked to return `null` for `li_at` → asserts `{ok: false, reason: "not_signed_in"}` reply, no dashboard handoff attempted | Fully-Automated | AC3 |
| Extension test: `chrome.tabs.query` mocked to return zero matching Beam tabs → asserts "open your dashboard" message shown, no success state | Fully-Automated | AC4 |
| Manifest review checklist (`host_permissions` scoped to `*.linkedin.com` + BEAM_ORIGINS, no `<all_urls>`, no `tabs`) + Playwright test: spoofed non-Beam-origin page attempts to trigger connect flow inside the same persistent context → asserts rejection (content script not injected / channel not opened) | Hybrid | AC5 |
| Dashboard-side unit/integration test: `message`/`chrome.runtime.sendMessage` event fabricated with wrong origin or missing `source` discriminator → asserts no `enableLinkedInOutreach` call fires. **VALIDATE addition:** a second case — correct origin AND correct `source` string but missing/wrong `nonce` (simulating a co-resident copy-cat extension, per D10/OI-3) → asserts no call fires either | Fully-Automated | AC6 |
| Component/e2e assertion: ToS warning banner text present and visible on the LinkedIn outreach card regardless of manual-form vs extension-button connect path | Fully-Automated | AC7 |
| Static grep check: no `console.log`/`logger.*`/`localStorage`/`chrome.storage` call in the diff references `cookie`, `response`, or `userAgent` from the connect flow, PLUS one runtime Playwright assertion of zero `chrome.storage` writes during a full connect flow | Hybrid | AC8 |
| Playwright e2e (extension NOT loaded — default/existing test config): only the pre-existing manual cookie-paste form renders, no extension-specific UI artifact | Fully-Automated | AC9 |
| Same Playwright extension harness as AC1, reused against a seeded "connected but stale" outreach account state, clicking the refresh-labeled button → asserts identical message flow + backend call as AC1 | Hybrid | AC10 |

Known-gap vacuous-green note: none of the 10 SPEC ACs are assigned Known-Gap as a terminal state.
OI-1 was the closest thing to a residual and VALIDATE resolved it empirically (VIABLE, no gap). All
10 ACs carry a Fully-Automated or Hybrid gate — this plan does not rely on Known-Gap for any
developed behavior (Net-Gate vacuous-green ban satisfied).

---

## Test Infra Improvement Notes

- `apps/extension/` will be the SECOND browser-extension-shaped Playwright harness in this repo after `apps/pixel/e2e/` (which tests a tracking script, not an MV3 extension) — the genuinely new Playwright API surface (`launchPersistentContext` + `--load-extension` + `context.addCookies()` + `serviceWorker.evaluate()`) is now VALIDATE-probed and confirmed working (see OI-1 resolution) — EXECUTE can build on the probe's exact technique rather than rediscovering it.
- **VALIDATE finding — CI coverage gap (accepted, matches existing precedent, not a new defect):** `.github/workflows/test.yml` has no job for `apps/pixel/e2e` today — that suite is local-only, never run in CI. `apps/extension/e2e` will follow the exact same pattern (local-only, not CI-wired) unless a new CI job is added. This is NOT a regression introduced by this plan — it matches the repo's existing, already-accepted convention for `apps/pixel`. Recorded here as an Open Gap (see Validate Contract) rather than a blocking plan-fix, per YAGNI — adding a new CI job is a reasonable follow-up but out of this plan's scope.
- The duplicated `known-origins.js` constant (extension side) vs the dashboard-side constant (Blast Radius note above) is a deliberate small drift-risk tradeoff — flag as a candidate for a future shared-constants mechanism if a third consumer of `BEAM_ORIGINS`/`KNOWN_EXTENSION_ID` ever appears, but do not build that abstraction now (YAGNI).
- No existing `apps/web/e2e/` spec currently covers `social-accounts` — confirm during EXECUTE whether a new spec file is needed there in addition to the `apps/extension/e2e/` suite, since the dashboard-side handlers are also independently testable without the extension loaded (e.g. AC6's fabricated-message test can run as a plain Vitest/RTL-style test on the page component in isolation, if such a test setup exists for `apps/web` — confirm test runner availability for isolated component tests in `apps/web` at EXECUTE time; `all-tests.md` does not currently document a component-test lane for `apps/web` beyond Playwright e2e).
- **VALIDATE finding — no `@types/chrome` in repo:** see page.tsx Touchpoints entry — execute-agent must add either the devDependency or a local ambient `.d.ts` before referencing the `chrome` global in strict-mode TypeScript.

---

## Resume and Execution Handoff

1. **Selected plan file path:** `process/features/campaigns-outreach/active/linkedin-extension_25-07-26/linkedin-extension_PLAN_25-07-26.md`
2. **Last completed phase or step:** VALIDATE complete — Gate: PASS. Plan text updated in place with 3 supplements (D10 nonce protocol / OI-3, OI-2 host_permissions resolution, OI-1 empirical probe resolution) plus 2 execute-agent instructions (AC2 test-reference correction, `@types/chrome` typing gap).
3. **Validate-contract status:** written below — PASS.
4. **Supporting context files loaded:** `process/context/all-context.md`, `process/features/campaigns-outreach/_GUIDE.md`, `process/context/tests/all-tests.md`, `apps/web/src/app/dashboard/social-accounts/page.tsx`, `apps/web/src/lib/api.ts`, `apps/pixel/package.json` + `apps/pixel/e2e/` + `apps/pixel/playwright.config.ts` (build/test precedent), `.github/workflows/test.yml` (CI wiring check), `tests/integration/test_social_accounts_list.py` (AC2 test-reference check), the locked SPEC file.
5. **Next step for a fresh agent picking up mid-execution:** run EXECUTE Steps 1-8 in order (Step 9 store-prep is independent and can run in parallel with or after Steps 1-8 once Step 1's origin/scaffolding work is done). Steps 3, 4, and 6 now include the D10 nonce-protocol wiring — read those steps' updated text before starting, not just the original SPEC/INNOVATE decisions.

## Validate Contract

Status: PASS
Date: 25-07-26
date: 2026-07-25
generated-by: outer-pvl

Parallel strategy: parallel-subagents (Layer 1: 4 dimension agents; Layer 2: 4 section agents — apps/extension/ package, page.tsx modifications, security/message-shape cross-cutting, verification evidence/test plan — all independent, no cross-agent coordination needed, results synthesized after)
Rationale: Score 3/7 (S2 schema/API/auth-adjacent surface present via cookie handling, S6 high-risk class present — auth/identity-adjacent + trust-boundary/secrets, S7 not met — 11-13 files is under the 5+ threshold read strictly but blast-radius risk class alone already qualifies MEDIUM tier) → parallel subagents, not agent-team (no section depends on another section's in-flight findings; the one cross-cutting item — nonce protocol — was resolved by the security dimension and folded into the plan text directly rather than requiring live coordination between agents).

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC1 | Extension installed + LinkedIn signed in → one-click connect reaches "connected" state | Hybrid | `cd apps/extension && npm run test:e2e` — Playwright persistent-context extension e2e, fake `li_at` seeded via `context.addCookies()` (OI-1-probed technique), asserts outreach card → "connected" | A |
| AC2 | Backend contract unchanged — zero `apps/api/**` files touched | Fully-Automated | `git diff --name-only -- apps/api/` (must be empty) AND `.venv/bin/python -m pytest tests/integration/test_social_accounts_list.py -q` (courtesy regression, not endpoint-specific — see AC2 Verification Evidence note) | A |
| AC3 | Not signed into LinkedIn → clear message, no silent empty-cookie send | Fully-Automated | `cd apps/extension && npm run test` — unit test, `chrome.cookies.get` mocked → `null`, asserts `{ok:false, reason:"not_signed_in"}` | B |
| AC4 | No matching Beam tab open → "open your dashboard" message, no success state | Fully-Automated | `cd apps/extension && npm run test` — unit test, `chrome.tabs.query` mocked → `[]`, asserts prompt shown | B |
| AC5 | Cookie never reaches a non-Beam origin | Hybrid | Manifest review checklist (`host_permissions` scoped to `*.linkedin.com` + BEAM_ORIGINS only) + `cd apps/extension && npm run test:e2e` spoofed-origin spec | B |
| AC6 | Dashboard only accepts a verifiably-extension-sourced message (incl. nonce-forgery case, D10) | Fully-Automated | `cd apps/web && npm run test:e2e` (or isolated component test if a lane exists — confirm at EXECUTE) — fabricated wrong-origin/missing-source case AND fabricated correct-origin+source/missing-nonce case, both assert no `enableLinkedInOutreach` call | B |
| AC7 | ToS warning shown on extension path too | Fully-Automated | `cd apps/web && npm run test:e2e` — banner text visible assertion, extension button path | B |
| AC8 | Cookie/UA never logged or client-stored | Hybrid | grep check (`git diff` scoped to `cookie\|userAgent\|response` + logger/storage calls, expect zero) + `cd apps/extension && npm run test:e2e` runtime `chrome.storage` write-count assertion | B |
| AC9 | Firefox/Safari (no `chrome` global) → manual form only, no broken UI | Fully-Automated | `cd apps/web && npm run test:e2e` — existing default Playwright config (no extension loaded) | B |
| AC10 | Refresh/reconnect reuses identical flow as first connect | Hybrid | `cd apps/extension && npm run test:e2e` — same harness as AC1, seeded "connected but stale" state, refresh-labeled button | A |

gap-resolution legend:
- A — proven now (gate passes in this cycle) — n/a pre-EXECUTE; these become A once EXECUTE lands the code these tests target. Currently pre-code, so read as "will be proven at EXECUTE Step 8 regression pass."
- B — fixed in this plan (gate added by this plan's checklist, code not yet written)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

Note: since this plan is pre-EXECUTE, no gate has actually run yet — all 10 rows are "B" in the strict
C-4 sense (the gate is specified and will be added by this plan's Implementation Checklist); the "A"
marking above on AC1/AC10 reflects that VALIDATE already ran the underlying mechanism once (the OI-1
probe) and confirmed it works, which is stronger pre-EXECUTE evidence than the other rows have, not a
claim that the actual test files exist yet.

Legacy line form (retained for existing validate-contract consumers):
- apps/extension (cookie read, messaging, popup): Fully-automated: `cd apps/extension && npm run test` | Hybrid: `cd apps/extension && npm run test:e2e` (persistent-context MV3 load, OI-1-probed) | agent-probe: none required | known-gap: none
- apps/web social-accounts page: Fully-automated: `cd apps/web && npm run test:e2e` (message-verification, ToS banner, AC9 no-extension case) | hybrid: n/a (component-level checks are fully automatable here)
- backend regression (AC2): Fully-automated: `git diff --name-only -- apps/api/` (empty) + `.venv/bin/python -m pytest tests/integration/test_social_accounts_list.py -q`

Dimension findings:
- Infra fit: CONCERN → resolved via plan note — `apps/extension` will not be CI-wired (matches existing `apps/pixel` precedent, not a new defect); `@types/chrome` gap identified and written into Touchpoints as an execute-agent instruction.
- Test coverage: CONCERN → resolved via plan fix — AC2's proving-test reference corrected to the actual existing file (`tests/integration/test_social_accounts_list.py`) with an explicit note that it does not cover the outreach-connect endpoint itself; the real AC2 proof is the `git diff` zero-backend-files check, which is solid. OI-1 empirically resolved VIABLE (see above) — upgrades confidence on AC1/AC10, no downgrade to agent-probe needed.
- Breaking changes: PASS — confirmed zero `apps/api/**` files in Touchpoints/Blast Radius; `page.tsx` changes are additive-only; `typeof chrome !== "undefined"` guard is safe on Firefox/Safari (never throws), correctly satisfies AC9.
- Security surface: CONCERN → resolved via plan supplement (D10) — OI-3 judged a REAL security requirement (not optional hardening) because AC6 explicitly requires copy-cat-extension resistance and the original origin+source-string check is forgeable by a co-resident malicious extension in the same page context. Nonce protocol (D10) added to Locked Decisions, Touchpoints (background.js/content.js/page.tsx), Public Contracts message shape, Security Checklist item 2, Steps 3/4/6/7, and Verification Evidence AC6. One narrower residual (broadcast-observability of a legitimate in-flight D7 transfer) is explicitly accepted and documented, not silently dropped — it does not exceed the general "malicious extension installed" threat model and does not affect the D6 primary path.

Open gaps:
- `apps/extension/e2e` not wired into `.github/workflows/test.yml` CI — known-gap: documented as NEW PLAN REQUIRED — see Test Infra Improvement Notes (matches existing `apps/pixel` precedent, not a regression; a future CI-hardening plan can add both `apps/pixel` and `apps/extension` in one pass).
- Full human VERIFIED sign-off against a real LinkedIn session (Phase Completion Rules) remains a manual step after CODE DONE — expected, not a plan defect.
- `KNOWN_EXTENSION_ID` real value is genuinely unavailable until Step 9's Chrome Web Store draft upload (OI-4) — confirmed acceptable sequencing, not a hidden circular dependency.

What this coverage does NOT prove:
- AC1/AC10 Hybrid gates prove the mechanism works against a *fake, locally-seeded* cookie — they do not prove behavior against LinkedIn's real cookie format/expiry/rotation semantics, or that LinkedIn hasn't changed the `li_at` cookie's attributes since this plan was written. That gap is the human VERIFIED step, not automatable.
- AC5's spoofed-origin Playwright test proves the extension rejects a scripted attempt from within the same test harness — it is not a full adversarial red-team pass (explicitly out of scope for v1 per SPEC AC5's own strategy note).
- AC6's nonce-forgery test proves the specific D10 mechanism as designed defeats forgery; it does not prove resistance against an attacker who has also compromised the dashboard page itself (XSS) — that is a different, unaddressed threat class outside this plan's scope (the dumb-pipe architecture assumes the Beam page itself is trustworthy).
- AC8's grep check proves no literal `console.log`/`logger.*`/`localStorage`/`chrome.storage` call references the named variables in the diff — it does not prove no OTHER code path (e.g. a browser devtools extension, or Chrome's own debugging surfaces) could observe the value; that is outside any application-level control.
- The CI-not-wired gap means none of the above gates run automatically on every PR — they must be run manually (or via local pre-push hook) until a follow-up CI plan lands.
(Required until C3 is implemented — temporary C3 mitigation)

Gate: PASS (no FAILs; 3 CONCERNs found and fixed directly in the plan text — D10 nonce protocol for security, OI-2 host_permissions resolution for infra, AC2 test-reference correction for test coverage; 1 accepted non-blocking gap — CI wiring, matching existing repo precedent)
Accepted by: session (VALIDATE, 25-07-26) — CI-not-wired gap accepted as matching existing `apps/pixel` precedent (see Open gaps); no other gaps required user acceptance since all 3 CONCERNs were resolved by direct plan-text fixes rather than left open.

## Autonomous Goal Block

SESSION GOAL: Ship the LinkedIn Outreach Connect browser extension (apps/extension/) — replace
manual DevTools li_at cookie-copy with a one-click "dumb pipe" connect flow into the existing,
unchanged backend endpoint.
Charter + umbrella plan: N/A — single COMPLEX plan (no phase program / umbrella).
Autonomy: standard /goal autonomous execution rules apply once EXECUTE begins — CONDITIONAL
EVL findings get fixed and retried; BLOCKED items go to backlog with a note and execution
continues on the remaining steps; irreversible/outward-facing actions (e.g. actually submitting
to the Chrome Web Store, Step 9's final submission) require explicit human action and are never
auto-performed.
Hard stop conditions / safety constraints:
- Never let the extension call the Beam backend directly or hold a Clerk JWT (D1, dumb-pipe architecture) — any deviation is a hard stop, return to PLAN.
- Never touch apps/api/** (D2, backend contract frozen) — any change there is a hard stop.
- Never widen manifest permissions beyond cookies + host_permissions(*.linkedin.com + BEAM_ORIGINS) + externally_connectable (Security Checklist item 4) — no <all_urls>, no tabs, no scripting.
- Never log or client-store the li_at cookie or User-Agent value anywhere (AC8) — any such call found in review is a hard stop until removed.
- Never bypass or weaken the D10 nonce check on the D7 popup channel, and never remove the ToS warning banner from any connect path (AC7).
- Never mark the plan VERIFIED (only CODE DONE) without an actual human confirming the flow against a real signed-in LinkedIn session (Phase Completion Rules).
Next phase: EXECUTE — process/features/campaigns-outreach/active/linkedin-extension_25-07-26/linkedin-extension_PLAN_25-07-26.md, Steps 1-8 in order (Step 9 may run in parallel once Step 1's scaffolding lands).
Validate contract: inline in this plan file (## Validate Contract section above) — Gate: PASS, 25-07-26.
Execute start: fully-auto commands: `cd apps/extension && npm run build && npm run test`, `cd apps/web && npm run lint`, `git diff --name-only -- apps/api/` (expect empty) | e2e spec: `cd apps/extension && npm run test:e2e` (persistent-context MV3 load, OI-1-probed technique) + `cd apps/web && npm run test:e2e` | probe scenario: none required (OI-1 already empirically probed by VALIDATE) | high-risk pack: yes — auth/identity-adjacent (LinkedIn session cookie) + trust-boundary/secrets logic, manual-first evidence pack recommended before Step 9's real Chrome Web Store submission (not before CODE DONE).

## Next Step

Validate-contract written — Gate: PASS. Say **ENTER EXECUTE MODE** to begin implementation of Steps
1-8 (Step 9 store-prep can run in parallel once Step 1 is done). Read the VALIDATE-added D10 nonce
protocol in Steps 3/4/6/7 before starting — it is a required part of the implementation, not optional
hardening.
