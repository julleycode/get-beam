---
name: report:linkedin-extension
date: 25-07-26
phase: update-process
status: COMPLETE_WITH_GAPS
feature: campaigns-outreach
plan: process/features/campaigns-outreach/active/linkedin-extension_25-07-26/linkedin-extension_PLAN_25-07-26.md
---

# LinkedIn Outreach Connect Extension — UPDATE PROCESS Closeout

## What Was Done

Full RIPER-5 cycle (RESEARCH → SPEC → INNOVATE → PLAN → VALIDATE(Gate: PASS) → EXECUTE →
EVL) shipped `apps/extension/` — a Chrome/Edge MV3 browser extension that replaces the manual
DevTools `li_at` cookie-copy flow with a one-click LinkedIn outreach connect. Architecture is a
"dumb pipe": the extension never holds a Clerk JWT or calls the Beam API directly; it hands the
cookie to the already-open dashboard tab, which calls the existing, unchanged
`POST /api/v1/social/accounts/linkedin/outreach-connect`. Backend touched: 0 files (confirmed —
see Test Gate Outcomes).

New package `apps/extension/` (manifest, background service worker, content script, popup,
known-origins constants, esbuild build script, Playwright persistent-context e2e harness, unit
tests, PRIVACY.md/STORE-LISTING.md/README.md store-prep docs). Dashboard side:
`apps/web/src/app/dashboard/social-accounts/page.tsx` gained extension detection, a "Connect with
extension" button, D6 nonce registration/issuance, and a verified `message` handler; plus a new
`apps/web/e2e/linkedin-outreach-extension.spec.ts` and a small ambient `chrome-extension.d.ts` type
file. Shipped in two commits: `89d924d` (feat, code) and `646689e` (process, SPEC+PLAN).

## What Was Skipped/Deferred

- **Human VERIFIED sign-off** against a real signed-in LinkedIn session — Phase Completion Rules
  require this before the plan can move from CODE DONE to VERIFIED; sandbox cannot do this (no
  real LinkedIn account/session available). Not a backlog item — it is an inherent human-only step
  documented in the plan itself.
- **3 web-e2e specs needing the full dev stack** — the sandbox has no way to boot
  `apps/web`'s dev server against a live backend/Postgres, so AC6 (dashboard-side)/AC7 (ToS
  banner)/AC9 (no-extension fallback) coverage in `apps/web/e2e/linkedin-outreach-extension.spec.ts`
  is written but unexecuted this session. → backlog NOTE below.
- **Backend regression** (`tests/integration/test_social_accounts_list.py`) needs Postgres, not
  available in sandbox. AC2's real proof — `git diff --name-only -- apps/api/` on the feature's own
  commit returning empty — was independently confirmed instead (see Test Gate Outcomes). →
  backlog NOTE below.
- **`KNOWN_EXTENSION_ID`** now a **dev-pinned id** (`ejllllimjoomfaacgbedjjelljciicii`, derived from
  the manifest `key` — stable across machines, so unpacked testing works without per-load patching;
  updated 25-07-26). Still pending: at first Chrome Web Store upload the store assigns its own id —
  remove the manifest `key` and swap this id in `known-origins.js` + the dashboard mirror (OI-4).
- ~~**Real extension icon**~~ — DONE (25-07-26): real Beam brand mark shipped at 4 sizes
  (`icons/icon-{16,32,48,128}.png`) from `icons/icon.svg`; manifest `icons` + `action.default_icon`
  wired to all four. Was a placeholder.
- **Chrome Web Store submission workstream** (Step 9 in the plan) — privacy policy hosting,
  per-permission justification text, listing assets, actual submission — drafted
  (`PRIVACY.md`, `STORE-LISTING.md`) but submission itself is an explicit manual, days-long,
  human-operator action per the plan's own Step 9 note. Never gates CODE DONE.
- **`apps/extension/e2e` not CI-wired** — matches the existing `apps/pixel/e2e` precedent
  (also not CI-wired). Documented as an accepted, non-regressive gap in the plan's Open gaps.

## Test Gate Outcomes

Re-run independently this session (Deep Mode — do not rely on execute-agent's self-report):

| Gate | Command | Result |
|---|---|---|
| Extension unit tests | `cd apps/extension && npm run test` | ✅ 9/9 pass |
| Extension e2e (AC1, AC5, AC6 nonce-forgery, AC8, AC10) | `cd apps/extension && npm run test:e2e` | ✅ 7/7 pass |
| `apps/web` lint | `cd apps/web && npm run lint` | ✅ clean, no warnings/errors |
| AC2 backend-contract-unchanged proof | `git show --stat 89d924d` — 0 `apps/api/**` files in the feature commit | ✅ confirmed (0 files) |
| AC2 backend regression (`test_social_accounts_list.py`) | needs Postgres | ⏭️ not run (sandbox has no Postgres) — known-gap, backlog NOTE below |
| `apps/web/e2e/linkedin-outreach-extension.spec.ts` (AC6/AC7/AC9) | needs full dev stack (Next dev server + backend) | ⏭️ not run — known-gap, backlog NOTE below |

Note: the current worktree has 13 unrelated dirty `apps/api/` files from other concurrent work
(ads-audiences, ingest-abuse-hardening, handoff-detection), so a raw `git diff --name-only --
apps/api/` against the working tree is NOT a valid AC2 proof right now — the correct proof is the
feature's own commit (`89d924d`), which is clean.

## Plan Deviations

None. Implementation matched the VALIDATE-supplemented plan (D10 nonce protocol, OI-2
`host_permissions` resolution, OI-1 empirical probe) exactly — Steps 1-8 all landed as specified,
Step 9 partially landed (docs drafted, submission itself correctly deferred).

## Test Infra Gaps Found

1. `apps/web` has no lightweight component-test lane (only Playwright e2e) — the plan's Test Infra
   Improvement Notes flagged this as an open question; confirmed still true. AC6's
   fabricated-message case could run faster as an isolated component test if such a lane existed.
   → not urgent, no backlog NOTE (matches pre-existing repo convention, out of this plan's scope).
2. `apps/extension/e2e` and `apps/web/e2e` both require a real browser + (for the web suite) a live
   dev server — neither is CI-wired. Matches existing `apps/pixel/e2e` precedent, not a new
   regression, but is a growing gap (3 Playwright suites now local-only).

## SPEC Achievement

10/10 SPEC acceptance criteria scored. Per the vacuous-green ban, a criterion is "met" only when
proven by a PASSING automated/hybrid gate this session (not by unexecuted specs or plan-author claims).

| AC | Criterion | Status | Evidence |
|---|---|---|---|
| AC1 | One-click connect reaches connected state | ✅ met | `connect.spec.ts` passed this session |
| AC2 | Backend contract unchanged | ✅ met | `git show --stat 89d924d` confirms 0 `apps/api/**` files; regression pytest unrun (Postgres unavailable) — does not weaken this AC since the primary proof (zero backend files) is deterministic and confirmed |
| AC3 | Not-signed-in → clear message, no silent empty cookie | ✅ met | unit test passed this session |
| AC4 | No matching Beam tab → "open dashboard" message | ✅ met | unit test passed this session |
| AC5 | Cookie never reaches non-Beam origin | ✅ met | `spoofed-origin.spec.ts` (2 cases) passed this session |
| AC6 | Dashboard verifies extension-sourced message (nonce) | ⚠️ partially met | `nonce-forgery.spec.ts` (extension-side, D7 forgery case) passed this session; the dashboard-side `apps/web/e2e` spec exists but did not run this session (no dev stack) — see backlog NOTE |
| AC7 | ToS warning shown on extension path | ⚠️ unmet this session | spec written (`linkedin-outreach-extension.spec.ts`) but unexecuted — needs full dev stack |
| AC8 | Cookie/UA never logged/stored | ✅ met | `no-storage.spec.ts` passed this session |
| AC9 | Firefox/Safari → manual form only | ⚠️ unmet this session | spec written but unexecuted — needs full dev stack |
| AC10 | Refresh/reconnect reuses identical flow | ✅ met | `connect.spec.ts` passed this session |

7/10 fully met with a fresh passing gate this session. AC6 partially met (extension-side leg
proven; dashboard-side leg written but unexecuted). AC7 and AC9 unmet this session purely due to
sandbox environment limits (no dev server), not code defects — both specs exist and were reported
green by execute-agent's EVL confirmation earlier in the same session; this UPDATE PROCESS
Deep-Mode re-check could not independently reproduce them given no dev stack available here.

**Backlog NOTE required:** unexecuted-this-session gates (AC6 dashboard leg, AC7, AC9,
`test_social_accounts_list.py` regression) → written to
`process/features/campaigns-outreach/backlog/linkedin-extension-dev-stack-gates_NOTE_25-07-26.md`.

## Closeout Packet

1. **Selected plan path:** `process/features/campaigns-outreach/active/linkedin-extension_25-07-26/linkedin-extension_PLAN_25-07-26.md`
2. **Closeout classification:** **Keep in active/testing** — implementation is CODE DONE (all 10
   ACs have a written gate, 7/10 independently re-confirmed green this session), but human VERIFIED
   sign-off against a real LinkedIn session and the 3 dev-stack-gated web-e2e specs are still
   pending. Per instruction, NOT archived to `completed/`.
3. **What was finished:** see "What Was Done" above.
4. **Verified vs unverified:** Verified this session (Deep Mode, independent re-run): extension unit
   9/9, extension e2e 7/7, `apps/web` lint clean, AC2 zero-backend-files. Still unverified: 3
   `apps/web/e2e` cases (AC6 dashboard leg/AC7/AC9 — need full dev stack), backend regression pytest
   (needs Postgres), and the human real-LinkedIn-session sign-off.
4b. **Validate-contract compliance:** present, inline in plan (`## Validate Contract`), Gate: PASS,
    dated 25-07-26, `generated-by: outer-pvl`.
5. **Cleanup done vs still needed:** Done this session — plan status section added, closeout report
   written, `_GUIDE.md` active list updated, `all-context.md` Repository Structure updated
   (surgical, 1 line block), backlog NOTE written for the 4 unrun gates. Still needed: the human
   VERIFIED sign-off, the 3 web-e2e runs, the Postgres-gated regression, real
   `KNOWN_EXTENSION_ID`, and actual Chrome Web Store submission (Step 9). (Real icon asset: DONE 25-07-26.)
6. **Next valid state:** Keep the plan active and continue validation on the same selected plan —
   next concrete action is running the 3 `apps/web/e2e` cases + the backend regression against a
   real dev stack (outside this sandbox), then the human LinkedIn-session sign-off.
7. **Commit checkpoint:** N/A this session — user explicitly instructed no commits; both feature
   commits (`89d924d`, `646689e`) already landed in a prior session. The `process/context/all-context.md`
   and this task folder's new REPORT/backlog-NOTE files remain uncommitted, per instruction (orchestrator
   handles commits separately).
8. Regression status: N/A (single COMPLEX plan, not a phase program — no prior-phase overlapping
   surfaces to regression-check).
9. **SPEC achievement:** see "SPEC Achievement" section above — 7/10 fully re-confirmed green this
   session, 3 unmet-this-session due to sandbox dev-stack limits (not code defects), 1 backlog NOTE
   written.

## Forward Preview

### Test Infra Found
- `apps/extension/e2e` — new second Playwright-MV3-extension harness (after the OI-1 probe
  technique), confirmed working end-to-end this session.
- `apps/web/e2e/linkedin-outreach-extension.spec.ts` — new spec, needs full dev stack to run.

### Blast Radius Changes
Matches plan exactly: `apps/extension/` (new package, ~14 files incl. docs/icons/build config) +
`apps/web/src/app/dashboard/social-accounts/page.tsx` (additive) + 1 new `apps/web/e2e` spec + 1
ambient `.d.ts` file. Zero `apps/api/**` files (confirmed). No schema/migration.

### Commands to Stay Green
```
cd apps/extension && npm run test
cd apps/extension && npm run test:e2e
cd apps/web && npm run lint
cd apps/web && npm run test:e2e -- linkedin-outreach-extension.spec.ts   # needs dev stack
.venv/bin/python -m pytest tests/integration/test_social_accounts_list.py -q   # needs Postgres
git show --stat 89d924d   # AC2 zero-backend-files proof (commit-scoped, not worktree-scoped)
```

### Dependency Changes
New `apps/extension/package.json` devDependencies: `esbuild`, `@playwright/test` (pinned to match
`apps/pixel/package.json`). New `apps/web` devDependency/ambient type: `apps/web/src/types/chrome-extension.d.ts`
(local ambient declaration, not an npm package — avoided pulling in a full `@types/chrome` package
per the plan's stated preference).

## Drift Signal Scoring

Signals: (a) files touched this UPDATE PROCESS session: 1 (`all-context.md`, surgical) → +1. (b1)
harness files (`.claude/`, `.codex/`): 0. (b2) `all-context.md`/`README.md`/`AGENTS.md`/protocol
docs: 1 (`all-context.md`) → +1. (c) 3+ memory-worthy observations this UPDATE PROCESS session: yes
(dirty-worktree AC2 proof caveat, dev-stack gate gaps, MV3-extension-testing precedent) → +1. (d)
feature-folder structural change: 1 new backlog NOTE file → +1. (e) validate-contract deviation:
none.

Score: 4/6 → **HIGH**.

Strongly recommend UPDATE PROCESS -- harness/protocol files touched.

(Note: this UPDATE PROCESS session IS itself the recommended action — already in progress.)

## Next Recommended State

Keep `linkedin-extension_25-07-26` in `active/`. Next concrete action: run the 3 web-e2e cases +
backend regression against a real dev stack + Postgres, then obtain human VERIFIED sign-off against
a real LinkedIn session, per the plan's own Phase Completion Rules. Only then archive to
`completed/`.
