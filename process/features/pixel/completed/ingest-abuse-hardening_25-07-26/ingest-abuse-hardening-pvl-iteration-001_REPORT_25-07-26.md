---
domain: plan
iteration: 1
date: 2026-07-25
gaps_found: 2
fail_count: 1
concern_count: 1
applied_count: 2
backlogged_count: 0
all_clear: false
consecutive_all_clear: 0
saturation_status: ACTIVE
new_gaps: 0
loop_status: CONTINUE
---

# PVL Iteration 001 — ingest-abuse-hardening

## Summary

PVL cycle 1 of the plan-validate-fix loop. Validate pass 1 (`generated-by: outer-pvl`) returned
`Gate: BLOCKED` with 2 actionable plan gaps. Both applied by `vc-plan-agent` in supplement mode.
Zero gaps backlogged. Loop continues — `vc-validate-agent` re-spawns from V1 against the
supplemented plan.

Plan under loop: `ingest-abuse-hardening_PLAN_25-07-26.md`
Auto-accepted under /goal: no (interactive session, user invoked `ENTER VALIDATE MODE`)

## Findings (validate pass 1)

### S1 — AC-4b outreach-safety test was aspirational — SEVERITY: FAIL

The two tests the plan named to prove AC-4 (`test_flagged_identity_never_emailable`,
`test_is_emailable_identity_abuse_flag_overrides_provider`) construct an already-flagged
`IdentifiedVisitor` directly. They prove `is_emailable_identity()` behaves correctly *given*
correct input — they never exercise whether the abuse flag actually reaches that input. The
entire `Event → Visitor → IdentifiedVisitor` propagation chain could be broken and both tests
would still pass. This is the plan's single most important safety guarantee (an abuse-flagged
visitor must never be emailable), so an aspirational test here is a FAIL, not a CONCERN.

### S2 — Propagation guidance cited the wrong precedent — SEVERITY: CONCERN

Phase 4 checklist item 4 told EXECUTE to mirror `source_agent_visit_id`'s placement. Validate
confirmed via `identity_resolver.py` that `source_agent_visit_id` never touches `Visitor` at all —
it is a call-parameter, not a column that flows through the aggregator. Following that guidance
would send EXECUTE down a path that cannot work.

## Fixes Applied

| Gap | Section edited | Change |
|---|---|---|
| S1 | Phase 4 checklist item 8 | Added `test_abuse_flag_propagates_event_to_identified_visitor` as the load-bearing first bullet: inserts flagged `Event` rows → runs the real `aggregate_visitors_for_site` → asserts `Visitor.is_abuse_flagged` → drives `_save_identified` → asserts `IdentifiedVisitor.is_abuse_flagged` and `is_emailable_identity()` rejection. Marked Docker-gated integration tier. Existing two tests downgraded to "secondary, isolation-only". |
| S2 | Phase 4 checklist item 4 | Replaced the `source_agent_visit_id` guidance with the verified precedent: `Event.optout` → `BOOL_OR(optout) AS do_not_resolve` in the aggregator raw-SQL CTE (`visitor_aggregator.py:267,300`) → `_upsert_visitor` sticky merge via `on_conflict_do_update` (`:151-238`, sticky clause `:234`). Also confirmed `visitor: Visitor` is an in-scope param of `_save_identified()` (`identity_resolver.py:713-819`), so `visitor.is_abuse_flagged` can be read straight into the `IdentifiedVisitor(...)` constructor, same shape as the existing `source_agent_visit_id=agent_marker` line at `:804`. |
| S1+S2 | P4 Known-Gap paragraph | Replaced "propagation mechanism not traced line-by-line" with a "Resolved at VALIDATE" note citing the confirmed chain and the new test. |
| S1 | AC→Phase→Test mapping + Verification Evidence tables | AC-4/AC-4b rows updated to name the new end-to-end test and separate it from the isolation-only regressions. |

Verification note: the fix agent independently re-read `visitor_aggregator.py` and
`identity_resolver.py` rather than trusting the validate agent's claim. Both claims confirmed.

## Backlogged

None. Both gaps were in scope and applied this cycle.

## Non-blocking items resolved inside the validate-contract (not plan gaps)

E1–E4 execute-agent instructions were written directly into the `## Validate Contract` section by
`vc-validate-agent` and did not require a plan-body edit:

- **E1** — AC-9 PII lint: confirmed no PII-lint/CI mechanism exists anywhere in this repo. The
  plan's "CONDITIONAL if not found" hedge is now firmed to a mandatory manual-review checklist item.
- **E2** — P5 observability endpoint's "current Redis status" is boot-time only, not a live check;
  wording corrected so it does not overclaim.
- **E3/E4** — minor `_storage_uri()` double-call and related cleanups.

## Facts source-confirmed during validate pass 1 (previously assumed)

- `slowapi` second-limiter ordering is viable: FastAPI resolves all `Depends()` params before
  calling the (slowapi-wrapped) endpoint, so a `Depends()`-based `site_id` stash works. This was
  the plan's biggest open question — now resolved from `slowapi/extension.py` + `fastapi/routing.py`,
  not hoped.
- `visitor_aggregator.py::aggregate_visitors_for_site` genuinely uses a raw `text()` query with
  `WHERE site_id = :site_id` only, bypassing the ORM. The plan's CRITICAL edit target is correct.
- Alembic head `a9f2c1e7b4d6` confirmed current (no child migration references it).

## Next Step

Re-spawn `vc-validate-agent` from V1 against the supplemented plan. Cap: 10 cycles.
Plateau check: 3 cycles without gap-count improvement.
