---
name: plan:engage-learning-agent-phase-3-superseded
description: "SUPERSEDED — the former Phase 3 was split into Phase 3a (learning) and Phase 3b (autonomy surface) on 17-08-26; this file is a pointer plus preserved cycle-1..3 validate-contract history"
date: 17-08-26
feature: campaigns-outreach
metadata:
  node_type: memory
  type: plan
  feature: campaigns-outreach
  phase: phase-3-superseded
---

# Phase 3 — SUPERSEDED (split into 3a + 3b on 17-08-26)

**Date**: 17-08-26
**Complexity**: COMPLEX
**Status**: ⛔ SUPERSEDED — do not execute, do not validate, do not supplement this file

> **This plan no longer exists as an executable phase.** It was split at PVL cycle 4.

## Overview

| Former Phase 3 content | Now lives in |
|---|---|
| Steps A + B — pure `autonomy_gate()`, `select_strategy_from_outcomes`, `determine_draft_mode` wiring; AC-13 | `phase-3a-learning_PLAN_17-08-26.md` |
| Steps C–G — `DraftStatus` enum, autonomous-send driver, six rails, prompt-safety fence, guardrail text; AC-11, AC-12, AC-14…AC-20 | `phase-3b-autonomy_PLAN_17-08-26.md` |

**Why the split happened.** The umbrella recorded a revisit condition at PVL cycle 2: *"if Phase 3
stalls at EXECUTE or a third PVL cycle lands new FAILs in the rails, revisit this decision."* It
triggered. Cycles 2 and 3 each produced FAILs that lived **inside the previous cycle's own fix text**,
and every one of them was in Steps C–G. Steps A and B drew **zero findings across all three cycles**.
Splitting isolates the volatile surface (schema migration, enum widening, outward-facing posting,
five doc surfaces, five web files) from the stable one (two pure functions, no schema, no side effects).

**Routing rules for any agent that lands here:**

- EXECUTE target → `phase-3a-learning_PLAN_17-08-26.md` or `phase-3b-autonomy_PLAN_17-08-26.md`. Never this file.
- PVL target → the same two files. Each is NEW and needs its own V1–V7 pass; neither inherits a PASS.
- Dependency order → 3a needs Phase 1; 3b needs 3a **and** Phase 2.
- The cycle-3 gaps this file's contract records (FAIL 1 audit schema, FAIL 2 outcome write site, N1–N4)
  are all closed in `phase-3b-autonomy_PLAN_17-08-26.md`, not here.

## Implementation Checklist

None — this file is a pointer. See the two successor plans above.

## Acceptance Criteria

None — AC-13 moved to Phase 3a; AC-11, AC-12 and AC-14…AC-20 moved to Phase 3b. The umbrella's
AC coverage map is authoritative.

## Phase Completion Rules

Not applicable. This file can never reach CODE DONE, TESTING, or VERIFIED — it is superseded.
Its successors carry their own completion rules.

## Touchpoints

None. This file touches no source. (Historical touchpoints are preserved in the contract below and
in the two successor plans.)

## Public Contracts

None.

## Blast Radius

None — pointer only.

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| (none — superseded pointer) | — | See `phase-3a-learning_PLAN_17-08-26.md` and `phase-3b-autonomy_PLAN_17-08-26.md` |

## Test Infra Improvement Notes

(none — carried forward into the two successor plans)

## Resume and Execution Handoff

1. Selected plan file path: **do not select this file.** Use `phase-3a-learning_PLAN_17-08-26.md` or `phase-3b-autonomy_PLAN_17-08-26.md`.
2. Last completed phase or step: superseded 17-08-26 at PVL cycle 4.
3. Validate-contract status: historical only — the cycle-3 contract below is preserved for audit and is NOT a live gate.
4. Supporting context files loaded: the umbrella plan, the SPEC, and the two successor plans.
5. Next step for a fresh agent: open the umbrella plan's Phase Ordering table and pick 3a or 3b.

## Execute Anchor

**This file is NOT an execute anchor.** The execute anchors are
`phase-3a-learning_PLAN_17-08-26.md` and `phase-3b-autonomy_PLAN_17-08-26.md`. Supporting phase files
(read-only context): the umbrella plan and the locked SPEC in this task folder. Context routing for
the successors is unchanged — `process/context/all-context.md` plus
`process/context/tests/all-tests.md` (Test Procedure / post-phase testing lives in each successor plan).

---

## Next Step

Route to `phase-3a-learning_PLAN_17-08-26.md` (PVL from V1) or, once 3a and Phase 2 are met,
`phase-3b-autonomy_PLAN_17-08-26.md`. Do not ENTER EXECUTE MODE against this file.

---

## Preserved Contract History (cycles 1–3, read-only)

The section below is the cycle-3 validate-contract as written against the pre-split plan. It is kept
readable for audit — the closure audits in it are the evidence that the cycle-1 and cycle-2 fixes were
genuine. It is **not** a live gate and must not be used to authorize execution of anything.

## Validate Contract

Status: BLOCKED
Date: 17-08-26
date: 2026-08-17
generated-by: outer-pvl
supersedes: 2026-08-17 (outer-pvl, PVL cycle 2) — cycle-2 Gaps 1–3 and C2-1…C2-8 re-derived against real source; Gaps 2 and 3 and all eight CONCERNs confirmed CLOSED, Gap 1's resolution introduced two new FAILs in its own text

Parallel strategy: sequential (no Agent tool in this environment — Layer 1 dimensions and Layer 2 sections executed sequentially in-agent against real source)
Rationale: signal score 6/7 (S1, S2, S4, S5, S6, S7). Dominant signal: S6 — outward-facing autonomous public posting plus a first-of-kind native-PG-enum migration.

### Net Gate Derivation

| Layer 1 dimension | Status |
|---|---|
| Infra fit | PASS |
| Test coverage | CONCERN |
| Breaking changes | CONCERN |
| Security surface | FAIL |

| Layer 2 section | Status |
|---|---|
| Step A — pure autonomy gate | PASS |
| Step B — outcome-driven strategy selection | PASS |
| Step C — enum, driver, consumer audit | FAIL |
| Step D — the six rails | FAIL |
| Step E — prompt-safety fence | PASS |
| Step F — guardrail text | PASS |
| Step G — tests | CONCERN |

**Totals: 2 FAILs / 4 CONCERNs / 5 PASSes → Net Gate: BLOCKED**

Trajectory: cycle 1 = 7 FAILs / 9 CONCERNs → cycle 2 = 3 / 8 → cycle 3 = **2 / 4**. Both cycle-3 FAILs live inside text this supplement newly wrote (the audit-as-durable-marker design and the two-entry audit split). See §Split-revisit signal below — this pattern is itself a finding.

---

### Cycle-2 closures — RE-DERIVED against real code

| Cycle-2 finding | Verdict | Evidence re-checked this cycle |
|---|---|---|
| **Gap 1** — no durable autonomy marker | **PARTIALLY CLOSED** | The *durability* half is genuinely proven. The decision row is written at flip time into the driver's session, and I verified **all five** `send_draft` failure paths commit rather than roll back: `:175`, `:191`, `:205` (commit then re-raise), `:236`, and `:244` (`send_draft_no_target` → `status = failed` → `await db.commit()`). So a decision row added before `send_draft` survives every `sent → failed` transition. G23's assertion is achievable. **But the schema and the write-site set are not** → FAILs 1 and 2 below. |
| **Gap 2** — sibling-helper transaction semantics | **CLOSED** | The pure-selection-helper design is sound against the real body. Verified `_auto_reject_siblings` (`drafts.py:386-411`) mutates, calls `_save_voice_example` per sibling, and commits internally; verified `_save_voice_example` (`:417`) itself does `db.add(example)` + `await db.commit()`. Returning IDs only, leaving the human endpoint's mutation+commit untouched, and having the driver apply rejections in its own transaction is byte-compatible for the human path and clean for the driver. |
| **Gap 3** — AC-20 surface set | **CLOSED** | All five greps verified to match TODAY, so all five can fail: `all-context.md` "Never build auto-send" (1 hit), `all-context.md` case-insensitive "never auto-send" (1), `README.md` (1), `apps/web/src/app/llms.txt/route.ts` "never auto-sends" (1), `apps/web/src/components/page-help.tsx` "nothing sends without your approval" (1). `docs/*` and `marketing/*` are named as deliberate exclusions. |
| C2-1 draft-card ungated | **CLOSED** | `draft-card.tsx` added to the 4-file `auto_approved` grep. |
| C2-2 tsc baseline | **CLOSED** | Gate switched to `npm run build` (typechecks in-context) instead of bare `npx tsc --noEmit`. |
| C2-3 package manager | **CLOSED** | npm named explicitly; `package-lock.json` identified as the tracked lockfile and the pnpm files as ambient. |
| C2-4 voice-example pollution | **CLOSED** | C6b2 forbids the driver calling `_save_voice_example`; G21 asserts zero new rows from the machine path **with a human-path positive control in the same test** — non-vacuous. |
| C2-5 dwell floor | **CLOSED** | `engage_autonomy_min_draft_age_minutes: int = 30` added to D7 and to the C5.1 predicate; gated by G22. |
| C2-6 per-iteration re-check | **CLOSED** | C5.1b states the in-loop status re-read explicitly and ties G19 to it. |
| C2-7 plaintext email | **CLOSED** | D5b: plaintext is never logged, never persisted, never entered into the audit row. |
| C2-8 rail-vs-quality tier split | **CLOSED** | One-paragraph reconciliation added to Blast Radius. |

---

### FAILs (cycle 3 — both inside the supplement's own new text)

**FAIL 1 — The `engage_autonomy_audit` schema is underspecified for the marker role Gap 1 assigns it: no `draft_id` column and no entry-kind discriminator.**

Gap 1's entire resolution rests on two queries:
- C3b (retry): `EXISTS (SELECT 1 FROM engage_autonomy_audit WHERE draft_id = :id)`
- C5.1 (eligibility): `NOT EXISTS (SELECT 1 FROM engage_autonomy_audit WHERE draft_id = drafts.id)`

But D5's column list — site, contact reference (blind index/ciphertext), playbook/strategy, `sample_n`, `positive_rate`, gate reason, timestamp; plus outcome + platform id — **contains no `draft_id`**, and neither does the Touchpoints entry (`models/engage_autonomy_audit.py` — "NEW append-only audit model"). Repo-wide, `draft_id` appears in the plan only inside these two query strings and the Redis idempotency key. Both queries are therefore unwritable against the declared schema.

Separately, D5 defines **two entry kinds in one append-only table with no discriminator column**. G23 (`test_audit_decision_row_written_at_flip_time`) must assert "the decision entry exists BEFORE `send_draft` is called" — that assertion cannot be expressed without a way to say *which* row is the decision row. Nullness of the outcome field is an implicit discriminator at best, and is never stated.

Resolution needed: add `draft_id` (FK → `drafts.id`) with an index, and an explicit `entry_type` (or equivalent) column, to D5 and to the model's Touchpoints description.

**FAIL 2 — The outcome entry cannot be written where the registry licenses it. `failed` and `undone` have no legal write site.**

D5 states the outcome entry carries `sent / failed / undone` and "rides the registry-licensed `sender.py` edit #4, committing in the SAME transaction as the send-status flip at `sender.py:215-216`."

`:215` is the **success branch only** (`draft.status = DraftStatus.sent`). Verified against source:
- `failed` is written at **five other sites** — `:175`, `:191`, `:205`, `:236`, `:244` — each with its own `await db.commit()`. Writing a `failed` outcome row at each means five additional `sender.py` edit sites.
- `undone` is written from the undo action in `routers/drafts.py`, not from `sender.py` at all.

The umbrella's licensed-edit table (row 4) reads: *"Pre-`post_comment` idempotency key + kill-switch/ceiling re-check, AND the same-transaction audit-row write at `:215`"*, immediately followed by *"Any fifth edit is a BLOCKED condition to surface, never to absorb."* So the plan is in one of two states, and both are defects:

- (a) the outcome entry is success-only — contradicting D5's own value list, and leaving **every failed autonomous send with no outcome row**, which makes AC-17's "full audit" incomplete precisely for the cases an operator most needs to audit; or
- (b) five unlicensed `sender.py` edits are required — which the registry defines as a BLOCKED condition to surface, not to absorb.

This conflict did not exist at cycle 2 (a single audit row at `:215`); it was created by the two-entry split introduced to resolve Gap 1.
Resolution needed: pick a design and reconcile it with the registry — either write the outcome row from the DRIVER after `send_draft` returns (driver-owned file, no registry change, no fifth edit), or expand licensed edit #4 to enumerate all six sites.

---

### CONCERNs (cycle 3 — all new, all consequences of the Gap-1 resolution)

| # | Finding | Severity | Proposed fix |
|---|---|---|---|
| N1 | **Permanent exclusion.** C5.1's `NOT EXISTS` predicate combined with C6c's kill-switch fallback creates a one-way door: a draft that flips to `auto_approved` (decision row written) and is then reverted to `pending` by the fallback can **never** be re-selected by the driver, because the audit row persists forever. Toggling the kill switch off and on therefore permanently drains the autonomous queue into the human queue. Fail-safe in direction, but unstated and untested — G7b only asserts the revert, not re-eligibility afterwards. | CONCERN | State the intended behavior, and either scope the predicate (e.g. exclude rows superseded by a fallback) or add a gate asserting the permanent-exclusion is deliberate. |
| N2 | **Human retry becomes an autonomous send.** C3b restores `auto_approved` on retry. Because sender edit #4 re-checks the kill switches, a human clicking Retry on their own failed draft gets refused whenever autonomy is subsequently OFF — the draft becomes un-retryable. It is also semantically odd to classify an explicit human click as autonomous. | CONCERN | Decide: restore `auto_approved` but exempt human-initiated retry from the kill-switch re-check, or restore to `pending` and let the human re-approve. Gate whichever is chosen. |
| N3 | **Commit ordering is load-bearing but unstated.** G23 depends on the decision row being in the session (or committed) before `send_draft` runs. All five failure paths commit — verified — so the row survives either way; but the plan never says whether the driver commits its own transaction before calling `send_draft`, and the sibling rejections + flip + decision row are described as "its OWN transaction" while `send_draft` owns the next commit. | CONCERN | State the commit boundary explicitly in C5 step 4. |
| N4 | **AC-17 "full audit" is incomplete under FAIL 2 branch (a).** G10 asserts audit completeness on the success path only. If the outcome entry stays success-only, no gate would ever catch the missing failed-send audit rows. | CONCERN | Add a failed-send audit assertion to G10 once FAIL 2 is resolved. |

---

### PASSes (verified this cycle)

- **Step A / Step B / Step E** — unchanged since cycle 2 and re-confirmed: gate signature structurally excludes model output; `_get_preferred_strategy` (`ai_reply.py:204`) and `determine_draft_mode` (`:261`) exist; `_sanitize_content` (`:111-119`) does not strip `<`/`>` while `prompt_safety.clean_text` (`:51`) does.
- **Step F — guardrail text: now genuinely complete.** Five greps, all verified to match today, covering both the served public route and the in-product copy. `docs/*` and `marketing/*` named as deliberate exclusions.
- **Infra fit** — driver home, scheduler job, `_LOCK_KEY` precedent (`services/outcome_digest.py:40`), Phase 1 `Draft.site_id` + A1c fail-closed, disposable-container migration DSN with the full docker path, isolated `ALTER TYPE … ADD VALUE` under AUTOCOMMIT, and a type-recreate downgrade that is safe because `draftstatus` is referenced by exactly one column (`cd811a8b1f32_baseline_schema.py:459`).
- **Structural validator:** 0 failures, 0 warnings (917 lines).
- **Infra available now:** PG:5433 and Redis:6379 LISTENing; `.venv/bin/python3.11` resolves.

---

### Test gates (C3 5-column)

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-11 | Gate is a pure function of outcome history | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_engage_autonomy.py::test_autonomy_gate_pure_function_of_outcome_history -q` | B |
| AC-11 | Fabricated model confidence cannot unlock autonomy — driven through the C5 driver | Fully-Automated | `…::test_model_confidence_field_cannot_unlock_autonomy -q` | B |
| AC-11 | Gate module imports no model/session/mutable global | Fully-Automated | `…::test_autonomy_gate_module_is_pure -q` | B |
| AC-12 | Fresh site never autosends | Fully-Automated | `ENGAGE_AUTONOMOUS_SEND_ENABLED=true ENGAGE_OUTCOME_LEARNING_ENABLED=true ENGAGE_SOCIAL_SEND_HOURLY_CEILING=20 .venv/bin/python3.11 -m pytest tests/integration/test_engage_autonomous_send.py::test_fresh_site_never_autosends -q` (per-site switch fixture-set) | B |
| AC-13 | Outcomes shift approach selection | Fully-Automated | `…pytest tests/unit/test_engage_autonomy.py::test_approach_selection_shifts_with_outcome_history -q` | B |
| AC-14 | Flags default OFF | Fully-Automated | `…::test_engage_autonomy_flags_default_off -q` | B |
| AC-14 | Dual kill switch halts, incl. in-flight race | Fully-Automated | `…pytest tests/integration/test_engage_autonomous_send.py::test_kill_switch_halts_autonomous_sends_immediately -q` | B |
| AC-14 | Fallback returns `auto_approved` → `pending` | Fully-Automated | `…::test_kill_switch_fallback_returns_auto_approved_to_pending -q` | B — does NOT cover re-eligibility (N1) |
| AC-15 | Ceiling queues excess; Redis error fails CLOSED | Fully-Automated | `…::test_social_send_ceiling_queues_excess -q` | B |
| AC-16 | Crisis routes to human queue; neutral control; timeout fails closed | Fully-Automated | `…::test_crisis_thread_routes_to_human_queue -q` | B |
| AC-16 (residual) | Lexicon quality on a human-reviewed corpus | Agent-Probe | no crisis-thread fixture corpus exists in-repo | D — accepted residual |
| AC-17 | Audit completeness (success path) | Fully-Automated | `…::test_autonomous_send_audit_record_completeness -q` | B — **blocked by FAILs 1 and 2**; incomplete for failed sends (N4) |
| AC-17 | Decision row written at flip time, survives `sent → failed` | Fully-Automated | `…::test_audit_decision_row_written_at_flip_time -q` | B — **blocked by FAIL 1** (no `draft_id`, no discriminator to assert on) |
| AC-17 | Undo deletes platform post + audits | Fully-Automated | `…::test_undo_deletes_platform_post_and_audits -q` (stub `PlatformService`, precedent `tests/integration/test_sender_token_refresh.py:86`) | B |
| AC-17 (residual) | Live X `DELETE /2/tweets/:id` | Hybrid | needs-live-provider, double opt-in | D — accepted residual |
| AC-18 | Suppressed contact blocked, non-vacuous control | Fully-Automated | `…::test_suppressed_contact_blocks_autonomous_social_send -q` | B |
| AC-18 | Unlinkable contact never autosends (fail-closed) | Fully-Automated | `…::test_unlinkable_contact_never_autosends -q` | B — stricter-than-SPEC, recorded below |
| AC-19 | Prompt fence unforgeable | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_engage_prompt_safety.py::test_engage_prompt_inputs_pass_prompt_safety_fence -q` | B |
| AC-20 | Guardrail text amended on all five carrying surfaces | Fully-Automated | the five F5 greps — **all verified to match today, so all five can fail** | A/B — design verified complete |
| V5 | Two siblings, exactly one posts | Fully-Automated | `…::test_two_sibling_drafts_only_one_posts -q` | B — depends on C5.1b in-loop re-check |
| V5 | Pending sibling of an auto-sent draft auto-rejected | Fully-Automated | `…::test_pending_sibling_of_auto_sent_draft_is_auto_rejected -q` | B |
| Gap 7 | Machine-rejected siblings never feed `voice_examples`, human path still does | Fully-Automated | `…::test_machine_rejected_siblings_do_not_feed_voice_examples -q` | B — non-vacuous (positive control in the same test) |
| Gap 8 | Draft younger than the dwell floor is not autosent | Fully-Automated | `…::test_draft_younger_than_dwell_floor_is_not_autosent -q` | B |
| C1 | Retry of an autonomous draft never becomes `approved` | Fully-Automated | `…::test_retry_of_auto_approved_draft_never_becomes_approved -q` | B — **blocked by FAIL 1** (EXISTS query unwritable); see N2 |
| D9 | `auto_approved` rows present in the API response | Fully-Automated | `…::test_auto_approved_drafts_visible_in_dashboard_surfaces -q` — in-file note: does NOT prove the rendered surface | B |
| D9 | Web surfaces carry the new value | Fully-Automated | `cd apps/web && npm run lint && npm run build` + `grep -rn "auto_approved"` across the FOUR named web files (api-types, status-badge, draft-card, drafts/page) | B — C2-1/C2-2/C2-3 all closed |
| D9 (residual) | Rendered drafts page / badge / card | Hybrid | blocked on the Clerk Playwright auth harness | D — accepted residual |
| Retry | Idempotency prevents double post | Fully-Automated | `…::test_idempotency_key_prevents_double_post -q` | B |
| Schema | Enum migration up→down→up (type-recreate downgrade) | Hybrid | disposable `postgres:16-alpine` on :55435 via the full docker path; `upgrade head` → `downgrade -2` → `upgrade head` | B |
| Schema | Second migration (audit table + `Site` column) up→down→up | Hybrid | same disposable container | B — schema itself blocked by FAIL 1 |
| Entry | Phase 1 + Phase 2 deliverables importable | Fully-Automated | `.venv/bin/python3.11 -c "from apps.api.models.engage_outcome import EngageOutcome; from apps.api.services.engage_track_record import compute_track_record; print('phase 1+2 present')"` | A |
| Regression | Unit lane (incl. re-derived scheduler counts) + full integration lane | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -m unit -q`; `.venv/bin/python3.11 -m pytest tests/ -m integration -q` | A |

gap-resolution legend: A — proven now; B — fixed in this plan; C — deferred to a named later phase; D — backlog test-building stub (named residual).

C-4 note: `strategy:` carries only Fully-Automated / Hybrid / Agent-Probe. Known-Gap is never a strategy; it appears only as gap-resolution D.

**Recorded deviation — AC-18 is deliberately stricter than the SPEC.** D4 fails CLOSED for both the multi-row-handle case and the no-email-link case (the majority social case), so unlinkable contacts are never auto-sent to at all. This narrows autonomy's reach in exchange for eliminating the fail-open hole that made cycle-1's AC-18 vacuous. Intentional; must not be "corrected" back at EXECUTE.

---

### Dimension findings

- Infra fit: PASS — driver, scheduler job, lock key, site key, both migrations, and the disposable-container path all check out against real files.
- Test coverage: CONCERN — 24 gates with real syntax and non-vacuous controls (G21's positive control is a genuine improvement); three gates (G10, G18, G23) are blocked by FAILs 1–2 rather than by test design, and G7b does not cover N1's re-eligibility case.
- Breaking changes: CONCERN — the enum widening and all five web surfaces are now correctly owned, gated, and reconciled; residual risk is the unstated one-way state transitions (N1, N2).
- Security surface: FAIL — the audit trail is the phase's accountability mechanism for autonomous public posting, and as specified it cannot be queried (no `draft_id`), cannot distinguish decision from outcome, and has no legal write site for `failed` or `undone`. An autonomous send that fails would leave an audit trail that neither reconstructs why it was allowed nor records what happened.
- Step A: PASS. Step B: PASS. Step C: FAIL (FAIL 1's queries live here). Step D: FAIL (FAIL 2 lives in D5). Step E: PASS. Step F: PASS. Step G: CONCERN.

---

### Split-revisit signal — YES, triggered

The coordinator asked whether FAILs found in this supplement's own new text trigger the umbrella's 3a/3b split-revisit signal. **They do, and this cycle is the clearest evidence yet.**

Both cycle-3 FAILs were *created by* the cycle-2 fix, not merely uncovered by it: the audit-as-durable-marker decision (resolving Gap 1) is what introduced the unqueryable schema, and the two-entry split is what introduced the illegal write sites. Cycle 1 → 2 also showed this pattern once (the C3b retry fix was written without a data source). Three cycles in, the phase is at the size where each fix has a meaningful chance of introducing a new defect inside the fix — that is the signal that the unit of change is too large to validate as one artifact, independent of whether any individual finding is severe.

The split remains the same shape recommended at cycle 2, and it is now better supported: **3a = Steps A + B** (pure `autonomy_gate` + `select_strategy_from_outcomes` + `determine_draft_mode` wiring behind `engage_outcome_learning_enabled`) — no schema, no migration, no web file, no send path, no outward behavior change, and notably **zero findings in any of the three cycles**. **3b = Steps C–G** — the enum, the driver, the audit table, all six rails, the guardrail amendment, and the web surfaces; every FAIL from all three cycles lives here. Splitting does not resolve FAILs 1 or 2, but it stops a clean, thrice-validated workstream from being re-validated on every 3b supplement cycle.

---

### Proposed plan updates (NOT applied — this agent's write scope is this section only)

| # | What changes | Where in plan | Why |
|---|---|---|---|
| P1 | Add `draft_id` (FK → `drafts.id`, indexed) and an explicit `entry_type` discriminator to the audit model spec | D5 + Touchpoints | FAIL 1 |
| P2 | Give `failed` and `undone` a legal write site — preferred: the DRIVER writes the outcome row after `send_draft` returns (driver-owned file, no registry change); alternative: expand licensed edit #4 to all six sites (registry amendment) | D5 + umbrella licensed-edit table | FAIL 2 |
| P3 | State the intended post-fallback re-eligibility behavior and gate it | C5.1 + C6c + G7b | N1 |
| P4 | Decide human-retry semantics (exempt from kill-switch re-check, or restore to `pending`) and gate it | C3b + G18 | N2 |
| P5 | State the driver's commit boundary relative to `send_draft` | C5 step 4 | N3 |
| P6 | Add a failed-send audit assertion to G10 | Step G | N4 |

### Execute-agent instructions (carried forward once the gate clears)

| # | Instruction | Trigger condition |
|---|---|---|
| E1 | Re-derive the live alembic head with `DATABASE_URL` pinned to a local/disposable DSN before writing either migration. Never run alembic with repo `.env` loaded — it points at Supabase PROD. | Migration step entry |
| E2 | The enum migration file contains ONLY the `ALTER TYPE`. No data step, no other DDL, no use of the new value in the same transaction. | Step C1b entry |
| E3 | `sender.py` gets licensed edits #3 and #4 and nothing else. A fifth edit is a BLOCKED condition to surface, never to absorb. | Step C/D entry |
| E4 | `routers/drafts.py:272` stays the only writer of human `approved`. | Step C3b entry |
| E5 | The extracted sibling helper returns IDs only — no mutation, no `_save_voice_example`, no commit. The human approve endpoint's observable behavior must be unchanged. | Step C6b entry |
| E6 | Record the full corrected-grep `DraftStatus` consumer list verbatim in the phase report, including all five Python consumers in C4e. | Before marking Step C done |
| E7 | Compose `clean_text` into `_sanitize_content`; do not delete the existing regex sanitization. | Step E entry |
| E8 | Re-derive `tests/unit/test_scheduler_job_config.py` inventory counts in the same commit as the scheduler append — the test AST-walks and asserts hardcoded counts. | Step C5b entry |
| E9 | Every rail lands with its gate in the same change. No rail may be marked done on a known-gap. | Step D entry |

### Backlog artifacts required

| Artifact | Location | What it tracks |
|---|---|---|
| `engage-crisis-lexicon-sample-set_NOTE_17-08-26.md` | `process/features/campaigns-outreach/backlog/` | AC-16 Agent-Probe residual — human-reviewed crisis-thread corpus |
| `engage-undo-live-platform-delete_NOTE_17-08-26.md` | `process/features/campaigns-outreach/backlog/` | AC-17 Hybrid residual — live X `DELETE /2/tweets/:id`, double opt-in |
| `engage-autonomy-web-render-harness_NOTE_17-08-26.md` | `process/features/campaigns-outreach/backlog/` | Rendered drafts-page / badge / card / undo verification, blocked on the Clerk Playwright auth harness |

---

Known gaps (accepted postures — excluded from the FAIL/CONCERN count):
- Live X platform-delete undo — Hybrid, needs-live-provider, double opt-in required.
- Crisis-detector lexicon quality — Agent-Probe; no crisis-thread fixture corpus exists in-repo.
- `N=20` / `R=0.4` / `ceiling=20` / `dwell=30` — placeholder-conservative, tune-from-observed operator values, not gates.
- DISTINCT-contact positive-rate counting — depends on Phase 2's `engage_outcomes.contact_bidx`; annotated as Phase-2-dependent.
- Rendered web-surface verification — Hybrid residual, blocked on the Clerk Playwright auth harness.
- Phase 1 and Phase 2 deliverables are not on disk yet; the mechanical entry-gate command is expected to fail until they land.

Open gaps: FAILs 1 and 2 plus CONCERNs N1–N4, all listed above.

What this coverage does NOT prove:
- The Python lanes prove backend behavior only. `npm run lint` + `npm run build` prove the TS union compiles and the literals are present; **no gate proves a rendered `auto_approved` badge, tab, or card action** — that leg is a named Hybrid residual.
- The flag-ON integration legs run against a stub `PlatformService`. They prove nothing about real X API semantics, rate limits, error codes, or whether a real post was created or deleted.
- The disposable-container round-trip proves both migrations apply and reverse on an empty PG **with zero `auto_approved` rows present**. It proves nothing about downgrading a database that already holds `auto_approved` rows — the guard refuses that case, so production downgrade after any autonomous send is effectively one-way.
- The five AC-20 greps prove exact strings are absent from five named files. They do not prove the replacement text is coherent, and they deliberately exclude `docs/*` and `marketing/*`.
- AC-18 is proven only for the email-linked path; unlinkable contacts are proven to be excluded from autonomy entirely, which is a different (stronger) guarantee than "suppression was checked".
- G23 proves a decision row survives one `sent → failed` transition. It does not prove the audit trail is queryable or complete — that is exactly what FAILs 1 and 2 leave open.
- No gate covers re-eligibility after a kill-switch fallback (N1) or human-retry semantics under a disabled switch (N2).
- PG:5433 and Redis:6379 were confirmed LISTENing at validate time (17-08-26). That is not a CI-runnability guarantee.

Gate: BLOCKED (2 unresolved FAILs: audit schema lacks `draft_id` and an entry-kind discriminator; outcome-entry `failed`/`undone` have no registry-legal write site)
Accepted by: not accepted — BLOCKED gate. vc-validate-agent does not self-accept its own verdict; returns to vc-plan-agent for the cycle-4 supplement.
