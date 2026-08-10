---
phase: canary-onboarding-phase-2-frontend
date: 2026-08-10
status: COMPLETE
feature: onboarding-canary
plan: process/features/onboarding-canary/active/canary-onboarding_10-08-26/canary-onboarding_PLAN_10-08-26.md
---

# Phase 2 — React chat shell (no canary)

Live step order after this phase: `welcome → site → install → done`.
`canary_go / canary_listen / canary_reveal / confirm` exist in `STEP_ORDER`, in
`SCRIPT`, and in the reducer, but are unreachable: `CANARY_ENABLED = false`
makes `nextStep("welcome")` return `"site"`. Phase 3 flips one constant.

## What Was Done

### Created — pure `src/lib` modules (all five)

| File | Contents |
|---|---|
| `apps/web/src/lib/onboarding-flow.ts` | `StepId`, `STEP_ORDER` (8), `CANARY_STEPS`, `CANARY_ENABLED`, `FlowState`, `FlowEvent`, `flowReducer`, `nextStep`, `sanitizeResumeStep`, `typingDelay`, `load/save/clearFlowState` (`beam_onboarding_v2`, `StorageLike` injectable for node tests) |
| `apps/web/src/lib/onboarding-script.ts` | All copy as data (`Record<StepId, Line[]>`, plain strings) + `interpolate` / `linesFor` |
| `apps/web/src/lib/beam-fingerprint.ts` | Verbatim fp2 port; `hash128()` exported separately (node-testable), `canvasFp`, `webglFp`, `fpComponents`, `fpParts`, `beamFingerprint` |
| `apps/web/src/lib/canary-format.ts` | `formatPlace`, `formatNetwork`, `formatPageLine`, `isUserOwnedNetwork` + response types mirroring `build_geo`/`build_network` |
| `apps/web/src/lib/canary-reveal-mode.ts` | `chooseRevealMode(response, tileState) → "map" \| "text" \| "skip"` |

### Created — tests (86 new assertions across 4 files)

`onboarding-flow.test.ts` (39), `canary-format.test.ts` (26),
`canary-reveal-mode.test.ts` (13), `beam-fingerprint.test.ts` (8).

### Created — components

`apps/web/src/components/onboarding/`: `onboarding-flow.tsx` (useReducer owner,
imports the CSS), `chat-transcript.tsx`, `chat-controls.tsx`,
`cross-tenant-disclosure.tsx`, `classic-onboarding.tsx`,
`steps/{welcome,site,install,done}-step.tsx`, `use-message-queue.ts`,
`use-auto-scroll.ts`, `use-reduced-motion.ts`.
Plus `apps/web/src/styles/onboarding-chat.css`.

### Modified

- `apps/web/src/app/dashboard/onboarding/page.tsx` → thin router (37 lines,
  was 348). Keeps all three required things (below).
- `apps/web/src/components/beam-mascot.tsx` → `palette?: "tour" | "chat"`;
  rects encoded per palette; grid-sync cross-reference comment added.
- `apps/web/public/beam/onboarding-mascot.js` → grid-sync cross-reference
  comment only. No behavioural change; still a plain `<script>`.

### Deleted

- `apps/web/src/components/onboarding-welcome-chat.tsx` (195 lines). Its three
  `LINES` are now `SCRIPT.welcome`. Deleting it also removed the runtime Google
  Fonts `<link>` injection, the runtime `/beam/onboarding.css` injection, the
  `chatRef.innerHTML = ""` StrictMode hack, and the `dangerouslySetInnerHTML`.

### NOT touched (Phase 4 follow-ups, per plan)

`apps/web/public/beam/onboarding-app.js`, `onboarding-steps.js`,
`onboarding.css`, `onboarding.html`; the `next.config.mjs` `/onboarding`
rewrite; `apps/web/src/app/onboarding/page.tsx`. Nothing under `apps/api`.

## Cross-tenant disclosure — CONFIRMED INTACT

Extracted verbatim into `components/onboarding/cross-tenant-disclosure.tsx`,
keeping `data-testid="cross-tenant-disclosure"` and the literal string
`cross-tenant identity`, rendered outside the `detecting` branch. It is now
used by **both** install surfaces (classic form and chat), so they cannot
drift. The live assertion passes:

```
✓ e2e/onboarding.spec.ts:253 › AC-9: cross-tenant disclosure is visible on the pixel-install step (2.1s)
```

## Test Gate Outcomes

| Gate | Result |
|---|---|
| `npx vitest run` (apps/web) | **141 passed / 8 files / 0 failed** (was 55; +86 new) |
| `npx tsc --noEmit` (apps/web) | **clean, exit 0** |
| `npm run build` (apps/web) | **✓ Compiled successfully, exit 0.** `/dashboard/onboarding` 12 kB / 113 kB First Load; shared First Load JS **87.6 kB, unchanged** |
| `e2e/onboarding.spec.ts` | **14 passed / 1 failed** — the one failure is outside this phase's blast radius (below) |
| Manual smoke of `?welcome=1` | 8 progress dots, 3 welcome lines, welcome→site (canary skipped), **0 runtime Google-font links**, "Exit to dashboard" visible (no fixed overlay), classic path unchanged, **0 console/page errors** |

### The one e2e failure

`onboarding.spec.ts:366 › Per-site management › Site settings dialog shows
pixel snippet + cookie consent`. It navigates to **`/dashboard/visitors`** and
clicks the SiteSelector gear — it never loads `/dashboard/onboarding`. It fails
in isolation as well as in-suite. The only uncommitted edits in that page's
component tree are the **concurrent session's** `browser-capture-card.tsx`
(+37 lines) and `api-types.ts` (+11), both already dirty at the start of this
session (`visitor-widgets.tsx → browser-capture-card.tsx`). Not attributable to
this phase and not touched.

### The e2e harness: what actually blocked it (answering the plan's question)

`demo@getbeam.fyi` was **NOT seeded** on this machine — I created it. Three
further environment facts had to be resolved before any authed leg could run,
none of which are code defects:

1. **Port 3000 is occupied by an unrelated local app** (`phantommm`). The
   committed `playwright.config.ts` has `reuseExistingServer: !CI`, so it would
   have silently driven that app instead of Beam. Worked around with a
   throwaway config on port 3100 (**deleted after the run**; the committed
   config is untouched).
2. **`apps/web/.env.local` supplies a `NEXT_PUBLIC_API_URL` that is not this
   machine's API**, so the dashboard talked to a different backend than
   `auth.setup.ts` logged into → 401 → `/login`. Pinned to
   `http://localhost:8000` for the run.
3. **CORS**: `main.py` allows `localhost:3000/3001` plus `settings.frontend_url`,
   so port 3100 preflights 400'd until the API was started with
   `FRONTEND_URL=http://localhost:3100`.

The API was run against the **local dev DB (`localhost:5433`)** with
`DATABASE_URL` explicitly pinned — never the `.env` Supabase production DSN.

## Plan Deviations

1. **`src/styles/onboarding-chat.css` is 21KB, not the plan's "near 12KB"
   estimate.** Lines 6-33 (`:root`, `*`, `html,body`, `body`) are deleted and
   the custom properties re-scoped under `.ob-root` as specified, and every
   named selector is dropped (`.ob-plan*`, `.ob-toggle`, `.ob-auth-*`,
   `.ob-draftcard`, `.ob-dash*`, `.ob-checklist`, plus `.ob-cl-*`,
   `.ob-visitor`, `.ob-subcard`, `.ob-modal*`, `.ob-celebrate`, `.ob-confetti`,
   `.ob-profile`, `.ob-avatar`, `.ob-mini`). The residual is a ~1.7KB header
   comment plus the sections the chat actually uses. Down from 25KB.
2. **Fonts**: the plan says load Fraunces + DM Mono via `next/font/google`.
   `src/app/layout.tsx:10-12` **already** loads both, exposing `--font-serif`
   and `--font-mono` on `<body>`. The CSS consumes those variables instead of
   adding a second `next/font` call — same outcome, no duplicate font fetch,
   and no build-time network dependency. Verified: 0 runtime
   `fonts.googleapis.com` links on the page.
3. **The bare add-site form was extracted, not deleted**, to
   `components/onboarding/classic-onboarding.tsx` (verbatim). The plan's
   "`?welcome=1` distinction" requires it, and all 14 committed e2e legs drive
   it. `page.tsx` is the thin router.
4. **Resume precedence**: `?site=&step=install` now wins over `?welcome=1`. The
   old page started at `welcome` and let an effect override to `install`;
   routing at the top is equivalent and avoids flashing the intro at someone
   returning to finish an install.
5. **"retry-once"** was interpreted as platform detection: `PLATFORM_FAILED`
   retries exactly once, then falls back to `platform: "unknown"`. Unit-tested.
6. **Step files are named `*-step.tsx`** (`welcome-step.tsx` …) rather than the
   plan's bare `steps/*.tsx`, for greppability.

## Test Infra Gaps Found

- `CONTEXT_PARTIAL: apps/web/.env.local and .env` — both blocked by the privacy
  hook, so `NEXT_PUBLIC_API_URL`'s actual value is unverified; it was overridden
  rather than read.
- **Local dev DB now carries seed data I created**: user `demo@getbeam.fyi` /
  `password123`, with `users.plan` set to `'max'` (Free caps at 1 site and the
  spec creates a site per test without cleaning up between them). Sites created
  during the runs were deleted; 0 remain.
- No committed spec covers `?welcome=1`. The chat surface was verified by a
  scratchpad Playwright script only. `onboarding-canary.spec.ts` is Phase 3
  work per the plan; a `?welcome=1` leg should land with it.
- The committed `playwright.config.ts` `reuseExistingServer: !CI` on port 3000
  is a live foot-gun: an unrelated app on 3000 produces confusing failures
  rather than a port conflict.

## Forward Preview

**Test infra found** — the three-part harness recipe above (free port + pinned
`NEXT_PUBLIC_API_URL` + `FRONTEND_URL` for CORS + local `DATABASE_URL`) is what
Phase 3's `onboarding-canary.spec.ts` will need.

**Blast radius changes** — Phase 3 adds `canary-listen.tsx`, `canary-map.tsx`,
`canary-reveal.tsx`, `identity-feedback-form.tsx` under
`components/onboarding/`, plus `steps/` entries for the four dormant steps. It
flips `CANARY_ENABLED` in `src/lib/onboarding-flow.ts` — that single constant is
the whole switch. `.ob-map*` CSS is already in place.

**Commands to stay green** —
`cd apps/web && npx vitest run && npx tsc --noEmit && npm run build`, plus
`npx playwright test e2e/onboarding.spec.ts` once port 3000 is free.

**Dependency changes** — none. Leaflet (`leaflet@^1.9` + `@types/leaflet`)
arrives in Phase 3 and must land in the onboarding route chunk only; re-check
that shared First Load JS stays at 87.6 kB after adding it.
