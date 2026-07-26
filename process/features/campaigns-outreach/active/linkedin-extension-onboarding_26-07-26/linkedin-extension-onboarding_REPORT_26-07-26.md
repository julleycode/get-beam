---
phase: linkedin-extension-onboarding
date: 2026-07-26
status: COMPLETE_WITH_GAPS
feature: campaigns-outreach
plan: process/features/campaigns-outreach/active/linkedin-extension-onboarding_26-07-26/linkedin-extension-onboarding_PLAN_26-07-26.md
---

# EXECUTE report — LinkedIn extension onboarding wizard

TL;DR: All 8 implementation steps landed. Every runnable gate is green (ext unit 13/13, ext e2e
10/10, web vitest 45/45, tsc clean, lint clean, manifest diff empty). The 10 `apps/web` Playwright
specs are written and enumerating but **could not execute** — no Docker (no Postgres) and
`playwright.config.ts` invokes a missing `python` binary. That is the exact Open gap the plan's
validate-contract already predicted.

## What Was Done

**Step 1 — extension probe.** `connect-logic.js`: extracted one shared internal
`readLinkedInCookieValue(chromeApi)`; `readLinkedInSession()` now calls it (public shape unchanged);
new exported `checkLinkedInSignedIn(chromeApi)` returns `{signedIn:true}` /
`{signedIn:false, reason}` with **no `cookie`/`userAgent` key on either branch**. `background.js`:
added the `beam-session-check` branch to the existing `onMessageExternal` listener, with an inline
comment recording *why* no nonce is required on this D6-only leg.

**Step 2 — extension e2e.** New `apps/extension/e2e/session-check.spec.ts` (3 specs): Beam-origin
gets `{signedIn:true}` with `Object.keys(...) === ["signedIn"]`; not-signed-in branch keys are
exactly `["reason","signedIn"]`; non-Beam origin (127.0.0.1:3999) gets no response. Fixtures gained
a `trySessionCheck()` on both `dashboard.html` and `attacker.html`.

**Step 3 — shared hook.** New `apps/web/src/lib/use-linkedin-extension-status.ts`: lifts the card's
detection `useEffect` verbatim (DOM marker + `beam-extension-detected` + D7 message listener with
origin/source/nonce verification), owns the nonce registration, the `beam-session-check` probe, the
one-click `connect()`, and the D3 wiring (`visibilitychange` + `focus` one-shot; 2s backstop poll
capped at 30 attempts; `clearInterval` + `removeEventListener` on unmount; `resetPoll()` for step
change; `retry()` = exactly one fresh check). Exports pure `computeWizardStepIndex()` and
`isChromeOrEdgeUserAgent()`.

**Step 4 — wizard + ToS extraction.** New `linkedin-tos-warning.tsx` (verbatim extraction, zero
rendered-output change at the original site) and `linkedin-connect-wizard.tsx` (4 steps, dialog-
hosted, numbered-circle progress bar copied from the onboarding page, step index derived live from
props on every render, `resetPoll()` on step change).

**Step 5 — card integration.** `social-accounts/page.tsx`: single `useLinkedInExtensionStatus()`
call site; existing "Connect with extension" block rewired to the hook with identical rendered
behavior; new "Connect LinkedIn" guided-setup launcher (Chrome/Edge only); `?connectLinkedIn=1`
read on mount then stripped via `router.replace`; manual form wrapped in an "Advanced: paste your
login key manually" `<details>`; inner component + `Suspense` wrapper for `useSearchParams`.

**Step 6 — copy.** Step 2 says "install it, then click I've installed it" and never promises silent
detection (asserted negatively in the spec). Permission-transparency block renders BEFORE the
install CTA (DOM-order assertion). No "cookie"/"DevTools"/"session token" in any wizard step
(asserted negatively); `li_at` vocabulary confined to the advanced form, unchanged.

**Step 7 — tests.** New `apps/web/e2e/linkedin-connect-wizard.spec.ts` (10 specs, AC1–AC4, AC7–AC13);
`linkedin-outreach-extension.spec.ts` extended with a launcher-presence assertion (its 2 existing
regression tests unmodified); `connect-logic.test.mjs` extended with 4 AC5 key-presence tests.

**Step 8 — backlog notes.** D13 rejection note + the web-e2e environment-gap note.

## What Was Skipped or Deferred

- Nothing from the checklist was skipped.
- `apps/web && npm run test:e2e` execution deferred to an environment with Docker (see Test Infra
  Gaps below).
- Manual/visual dev-server smoke (Step 5 gate) not performed — the dev stack named in the handoff
  was not actually running (all three ports dead) and cannot be started without Postgres.

## Test Gate Outcomes

| Gate | Result |
|---|---|
| `cd apps/extension && npm test` | **13/13 pass** (9 pre-existing + 4 new AC5) |
| `cd apps/extension && npm run build` | **clean** |
| `cd apps/extension && npm run test:e2e` | **10/10 pass** (7 pre-existing + 3 new) |
| `cd apps/web && npx vitest run` | **45/45 pass** (39 pre-existing + 6 new) |
| `cd apps/web && npx tsc --noEmit` | **clean** (covers `e2e/**` — tsconfig include is `**/*.ts`) |
| `cd apps/web && npm run lint` | **clean** |
| `git diff apps/extension/manifest.json` | **empty** — zero new permissions (D13 rejection proven) |
| `cd apps/web && npm run test:e2e` | **ENVIRONMENT-BLOCKED**: `/bin/sh: python: command not found`, `Exit code: 127`; `docker info` → down. `--list` confirms all 13 tests parse/enumerate. |

## Plan Deviations

1. **Manual-form collapsible open condition** (within blast radius). Plan said "collapsed by default
   when the wizard is available (Chrome/Edge)". Implemented as collapsed only once
   `extensionDetected` is true. Reason: the plan ALSO mandates the sibling spec
   (`linkedin-outreach-extension.spec.ts`) re-run **unmodified**, and its AC9 test asserts
   `getByLabel(/LinkedIn login key/i)` is *visible* with no extension present — content inside a
   closed `<details>` is not visible, so the literal reading would have broken a non-regression gate
   the same plan requires. This keeps the form de-emphasized behind an "Advanced" summary, satisfies
   D12 (always the only path on Firefox/Safari, where `extensionDetected` is always false), and keeps
   AC12 reachability. Impact: a Chrome user with no extension sees the advanced section expanded.
2. **`known-origins.js` untouched.** Plan made this conditional on finding an existing message-type
   centralization pattern; `background.js` uses inline literals, so `"beam-session-check"` follows
   the same convention (YAGNI, as the plan directed).
3. **`window.history.replaceState` for the reopen param** instead of `router.push`, because the very
   next statement is `location.reload()` — a Next router push would race the reload. Param stripping
   after read uses `router.replace` as planned.

No hard-stop-class deviation. Manifest unchanged; probe shape has no cookie field; exactly one hook
call site; Step 2 copy promises no silent detection; ToS warning on Step 4; zero `apps/api` files.

## Test Infra Gaps Found

- `apps/web/playwright.config.ts` `webServer` uses `python -m uvicorn` on BOTH the CI and non-CI
  branches; this machine has only `python3`/`.venv/bin/python3.11`. Pre-existing, not introduced
  here, deliberately not fixed (out of this plan's blast radius). Classification:
  **harness-drift / stale-command-drift**.
- No Docker daemon → no Postgres → `e2e/auth.setup.ts` cannot provision the test user, so no
  authenticated dashboard route renders. Classification: **environment**.
- `apps/extension/e2e`'s static fixture server binds port 3000, the same port as the web dev server
  — running both suites simultaneously would collide. Worth noting for CI wiring.

## Closeout Packet

- **Selected plan:** `process/features/campaigns-outreach/active/linkedin-extension-onboarding_26-07-26/linkedin-extension-onboarding_PLAN_26-07-26.md`
- **Finished:** Implementation Steps 1–8 in full.
- **Verified:** extension probe (unit + MV3 e2e, incl. cross-origin rejection), pure step
  derivation, typecheck, lint, manifest-unchanged, zero-backend.
- **Unverified:** all 10 wizard e2e specs + the extended sibling regression run; the human
  real-LinkedIn-session VERIFIED step the plan's Phase Completion Rules already require.
- **Remaining cleanup:** run `apps/web` e2e in a Docker-capable environment; replace
  `CHROME_WEB_STORE_URL` placeholder at store publication.
- **Classification: `Keep in active/testing`** — code-complete, but the plan's own Phase Completion
  Rules make CODE DONE contingent on every Verification Evidence row being green, and 11 rows are
  environment-blocked.

## Follow-up stubs created

- `process/features/campaigns-outreach/backlog/linkedin-onboarding-oninstalled-remedy_NOTE_26-07-26.md`
- `process/features/campaigns-outreach/backlog/linkedin-onboarding-web-e2e-env-gap_NOTE_26-07-26.md`

## CONTEXT_PARTIAL items

- `CONTEXT_PARTIAL: dev stack` — the handoff stated the API/web/phantommm stack was running; it was
  not (ports 8000/3000/9100 all unreachable), which is what forced the web-e2e gates to
  environment-blocked.

## Forward Preview

**Test Infra Found:** `apps/extension` node:test + MV3 Playwright (both runnable, zero-infra);
`apps/web` Vitest node lane (runnable, pure logic only — no jsdom/RTL); `apps/web` Playwright
(needs Docker + a `python` binary fix).

**Blast Radius Changes:** +4 new web files (`use-linkedin-extension-status.ts` + its test,
`linkedin-connect-wizard.tsx`, `linkedin-tos-warning.tsx`), 1 web page refactored, 2 extension src
files, 2 extension fixtures, 3 test files extended, 1 new extension spec, 1 new web spec.
`useLinkedInExtensionStatus()` is now a two-consumer contract surface with a hard single-call-site
rule — any third consumer must go through `page.tsx`'s props, not a second hook call.

**Commands to Stay Green:**
```
cd apps/extension && npm test && npm run build && npm run test:e2e
cd apps/web && npx tsc --noEmit && npm run lint && npx vitest run
cd apps/web && npm run test:e2e   # needs docker compose up postgres redis + python fix
git diff apps/extension/manifest.json   # must stay empty
```

**Dependency Changes:** none. No new npm package, no new manifest permission, no backend change.
