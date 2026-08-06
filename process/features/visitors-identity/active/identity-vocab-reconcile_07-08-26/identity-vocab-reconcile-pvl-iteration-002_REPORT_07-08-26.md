---
name: identity-vocab-reconcile-pvl-iteration-002
description: PVL cycle 2 re-validation — cycle 1's fixes hold, but D10's emailability-flag design is unimplementable and breaks devjulley's own guardrail tests; Gate BLOCKED
date: 2026-08-07
iteration: 2
metadata:
  node_type: report
  type: pvl-iteration
  domain: plan
  feature: visitors-identity
  loop_status: CONTINUE
---

# PVL Iteration 002 — identity-vocab-reconcile

**Plan:** `process/features/visitors-identity/active/identity-vocab-reconcile_07-08-26/identity-vocab-reconcile_PLAN_07-08-26.md`
**Cycle:** 2 of max 10
**Trigger:** `SUPPLEMENT_APPLIED` from cycle 1 → re-validate from V1
**Verdict:** `Gate: BLOCKED` (2 FAIL / 1 CONCERN)

## Cycle 1 fixes — independently re-verified, all hold

| Item | Re-derivation method | Result |
|---|---|---|
| S1 migration sequencing | Chain re-run through the real `alembic` CLI rather than a hand-parser | Holds. Corrected order is sound |
| S2 blast radius = 35 | Fresh `git grep -c` on both branches | Confirmed: 5 production + 30 test across 10 files |
| S3 spot-check files | Read file bodies on `devjulley` | All 3 already clean |
| Checklist renumbering | Cross-reference audit | Internally consistent, no stale step pointers |

## New FAILs — the D10 design does not work

**F4 — signature contradiction.** The plan's "exact signature (binding)" for `is_emailable_identity()` carries no `identity_status` parameter, but the body logic it is supposed to implement (`is_verified_identity(identity_status)`) requires one. At none of the 5 production call sites is `identity_status` in scope where the gate runs. The specified function cannot be written.

**F5 — decisive: devjulley's own tests forbid this exact change.** Reading the four devjulley test files that call `is_emailable_identity()` turned up pre-existing, deliberate assertions that D10 would break:

- `test_is_emailable_identity_still_takes_exactly_three_params` — docstring: *"Hard constraint: this phase must not widen the emailability signature."*
- A second test whose docstring states it exists *"to catch a future change that 'helpfully' folds the candidate tier into `is_emailable_identity`"* — precisely what D10 does.

The locked program SPEC says the same independently: the candidate gate belongs *"not in `is_emailable_identity()` itself."* devjulley's engineers built this boundary on purpose. Crossing it contradicts locked decision **D3** (all devjulley additions survive intact).

**C6 — hard-stop wording inaccurate.** D10's OFF-state is not "zero production behavior change" as the plan's Hard Stop claims: it opens a flag-independent path to emailing someone via the confirm-candidate action alone.

## Root cause

D10 originated as VALIDATE cycle-1 instruction E4 and was relayed into supplement cycle 1 as a binding orchestrator decision. E4 answered the OFF-state *semantics* question correctly (confirm-gated is the right behavior) but attached it to the wrong *implementation site* — inside the shared helper instead of at the call sites. Cycle 2 caught it by reading the test bodies, which cycle 1 did not do.

## Recommended resolution (folded into the plan by the validate pass)

Keep `is_emailable_identity()` at its unmodified 3-parameter signature. Implement the confirm-gate as a **wrapper check at the 5 production call sites**, ANDed with the untouched helper. This preserves D2 (wide emailability rule), D3 (devjulley's tests and boundary survive), SPEC AC2, and D10's intended semantics — only the implementation site moves.

## Fan-out disclosure

No Agent/Task tool was available to the validate agent again this cycle. It ran a single sequential deep-verification pass instead of the designed Layer-1/Layer-2 parallel fan-out, and disclosed this explicitly rather than substituting silently. Same limitation as cycle 1, recorded so the confidence attached to this contract stays auditable. Note that the single-pass approach did find what cycle 1 missed — the gap was depth of reading (test bodies), not parallelism.

## Loop state

`CONTINUE` — supplement cycle 3 redesigns §3.1 / §3.7 / §4 / §6 per the recommended direction, then re-validate from V1. Structural validator on the plan: 0 failures, 0 warnings. Docker still unavailable; migration live round-trip remains a documented known-gap, not blocking.
