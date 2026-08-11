---
node_type: note
type: backlog-note
feature: visitors-identity
date: 09-08-26
status: open
kind: test-building-stub
plan: process/features/visitors-identity/completed/privacy-hold-clear_09-08-26/privacy-hold-clear_PLAN_09-08-26.md
blocks: [AC-1, AC-2, AC-3, AC-6, AC-13-presence]
---

# Backlog stub — privacy-hold Clear web e2e (Clerk auth-harness residual)

**TL;DR:** The Hybrid e2e legs for the privacy-hold Clear UI (SPEC AC-1/2/3/6 +
AC-13 copy-presence) are written in `apps/web/e2e/visitors.spec.ts` but stay
CONDITIONAL — they need an authenticated dashboard session on a site that has a
`do_not_resolve=true` visitor, which depends on the shared **Clerk Playwright
auth-harness** (a recurring repo-wide known gap). They are `test.skip`-guarded,
not left to fail. This is the test-building stub that tracks closing them.

## Why deferred (not a source bug)

- The clear endpoint + backend behavior are fully proven by Fully-Automated
  integration gates (`tests/integration/test_privacy_hold_clear.py`, 8/8 green:
  AC-4/5/7/8/9/10/11). Those do NOT exercise the rendered banner/button/confirm
  wiring — that is the Hybrid e2e half.
- The web app has **no React component-test runner** (only Playwright e2e), so
  AC-2 ("web component test" in SPEC) lands as an e2e leg too.
- Same auth-harness gap as billing/exports, ads-audiences Phase 1, and
  cadence-bot-flag — see `process/context/tests/all-tests.md` Known Gaps.

## What is already on disk

`apps/web/e2e/visitors.spec.ts` → `test.describe("Visitors — privacy hold clear")`
with 5 legs mapped to the plan's V-e2e-* scenarios:
- `V-e2e-banner` (AC-1) — "Privacy hold" state + "policy block, not a usage limit"
- `V-e2e-button-visibility` (AC-2) — Clear button present on held rows
- `V-e2e-confirm-dialog` (AC-3) — dialog opens; Cancel = no-op
- `V-e2e-copy-presence` (AC-13 presence) — deliberate / this-site-only / suppression markers
- `V-e2e-post-clear-ui` (AC-6) — after confirm, Identify returns

They are skipped unless `E2E_PRIVACY_HOLD_VISITOR="<held visitor_id>"` is exported.

## Clearing conditions

1. A shared Clerk Playwright auth-harness (signed-in dashboard session) exists.
2. A seed path creates a `do_not_resolve=true` visitor on the signed-in site.
3. Export `E2E_PRIVACY_HOLD_VISITOR=<that visitor_id>` and run
   `cd apps/web && npm run test:e2e`. Flip the legs green; then AC-1/2/3/6 move
   from CONDITIONAL to proven and this note is resolved.

## Related residual (separate)

AC-13 **legal-adequacy** (counsel review) is a distinct Known-Gap tracked in
`privacy-copy-counsel-review_NOTE_07-08-26.md`. The copy shipped here is an honest
placeholder — strictly better than the prior dead-end — and does not block.
