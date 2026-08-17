---
name: report:private-beta-apply-form-pvl-iteration-004
description: "PVL supplement cycle 5 — F10 split below the Clerk boundary; first cycle to self-catch an unsatisfiable gate before recording it"
date: 15-08-26
feature: onboarding-canary
metadata:
  node_type: report
  type: pvl-iteration
  cycle: 5
  domain: plan
---

# PVL Iteration 004 — private-beta-apply-form

## Input

Validate cycle 5: `Gate: BLOCKED` — 1 FAIL, 2 CONCERNs. The FAIL was the **6th
instance** of the plan's dominant defect class, and it had been *introduced by
cycle 3's own fix* — missed by cycle 4's audit because that audit re-checked
pre-existing gates rather than newly-written ones.

## The FAIL and its resolution

Gate F10 could not pass against a correct implementation:
`apps/web/playwright.config.ts:53` blanks the Clerk keys for the entire e2e
webServer ("Disable Clerk auth for E2E"), and both F10 assertions sit behind
`HAS_CLERK` guards. Route publicity was never the constraint — with the key empty,
`middleware.ts:15` never installs Clerk middleware at all. `reuseExistingServer`
made it additionally non-deterministic (green locally, red in CI).

**Orchestrator decision applied — split, rejecting all three offered options:**

- **F10a (Fully-Automated):** pure helper `buildSignUpHref(search)` in
  `apps/web/src/lib/signup-href.ts`, called by `signup/page.tsx`, unit-tested with
  3 vitest cases. No Clerk, no browser, deterministic. This is real automated proof
  of the exact FAIL-A defect (a literal string dropping the query) and satisfies
  AC-13's automated half.
- **F10b (Hybrid, known gap):** the browser end-to-end leg, precondition named
  (Clerk-enabled Playwright server — absent in this repo), no spec written, folded
  into the existing shared Clerk-harness backlog stub. Skip-guarding forbidden.

Module choice was justified against existing convention rather than invented:
`utils.ts` is `cn()`-only, `onboarding-flow.ts` is the chat reducer, `plans.ts` is
billing metadata; single-concern `src/lib/` modules with colocated tests already
exist (`canary-format`, `privacy-optout`, `fetch-beacon`).

## CONCERNs closed

- Section E step 1's discovery command now includes `letter.html` — measured **9
  hits** (index 5 + letter 1 + steps.js 3), with L9/L555 marked expected prose noise
  in a *discovery* command and an explicit warning against narrowing it to E1's
  assertion pattern.
- `playwright.config.ts` recorded as explicitly NOT touched, added to Read-only,
  contributing 0 to blast radius.

## Blast radius 20 → 21

Measured derivation: Changed table 22 rows − 1 duplicate (`waitlist.py` listed
twice) = 21 distinct. Delta −1 +2: removes the dead
`e2e/invite-token-delivery.spec.ts` (artifact of the unsatisfiable gate), adds
`signup-href.ts` + `signup-href.test.ts`. It moved, and the plan says so.

## The self-audit worked — first time

Every command written this cycle was **executed pre-fix**: F10a vitest → `No test
files found`; call-site grep → rc=1; `ls signup-href.ts` → absent; `npm test` →
167 passed / 10 files (170 recorded as the post-fix target); Section E grep → 9
hits. All fail in the correct direction.

**It caught its own defect before recording it:** F10a's call-site assertion was
unsatisfiable as first written, because no implementation section instructed anyone
to call the helper. Fixed by rewriting Section F.6 step 1 *before* the gate was
recorded. This is the first cycle in which an instance of the dominant class was
stopped before entering the plan.

## Loop lessons recorded in the plan

1. Fixes that introduce new gates must have those gates executed **in the same
   cycle that writes them**. Auditing only pre-existing gates is how instances 5
   and 6 survived.
2. **Playwright cannot prove any Clerk-gated browser behavior in this repo**
   (`playwright.config.ts:53` blanks the keys; `:56` makes it ambient-dependent).
   Future gates must use the F10a pattern (assert below the boundary) or the F10b
   pattern (Hybrid with a named precondition).

## Validator state

0 failures, 0 warnings, 840 lines, 16 `##` sections. No unsatisfiable F10 command
survives anywhere; remaining mentions are prohibitions or the historical audit
record.

## Running defect-class count

6 instances across 5 cycles (4 gates, 1 probe, 1 gate introduced by a fix), plus
1 caught pre-record by self-audit. Yield per cycle is falling: 8 → 12 → 7 → 3.

## Next step

Re-spawn vc-validate-agent from V1 (PVL cycle 7). If BLOCKED again on the same
class, stop the loop and route to EXECUTE with residual gaps as executor
instructions.
