---
name: identity-vocab-reconcile-pvl-iteration-006
description: PVL cycle 6 re-validation — Gate CONDITIONAL, BLOCKED streak broken; orchestrator-driven adversarial fan-out converged on the events.py svid-gate bug and found 2 further defects the contract missed
date: 2026-08-07
iteration: 6
metadata:
  node_type: report
  type: pvl-iteration
  domain: plan
  feature: visitors-identity
  loop_status: CONTINUE
---

# PVL Iteration 006 — identity-vocab-reconcile

**Plan:** `process/features/visitors-identity/active/identity-vocab-reconcile_07-08-26/identity-vocab-reconcile_PLAN_07-08-26.md`
**Cycle:** 6 of max 10
**Trigger:** `SUPPLEMENT_APPLIED` from cycle 5 → re-validate from V1
**Verdict:** `Gate: CONDITIONAL` (0 FAIL, 2 CONCERN in-contract; **2 further defects found externally, not in the contract**)
**Loop state:** `CONTINUE` — supplement cycle 7 required. Not terminal.

## What changed methodologically this cycle

Cycles 1–5 all ran a single sequential pass inside `vc-validate-agent`, because that agent's tool
grant contains no Agent tool and the designed Layer-1/Layer-2 fan-out therefore cannot run inside it.
Every one of those cycles still surfaced a real FAIL, which suggested the single-pass was leaving
findings on the table.

This cycle the **orchestrator supplied the parallel coverage externally**: `vc-validate-agent` ran
its V1–V7 spine while two independent adversarial verifier agents ran concurrently, each instructed
to *refute* rather than confirm, and to default to REFUTED when a claim could not be positively
reproduced from their own command output.

The result justifies the change: one finding was independently reproduced by two agents (strong
signal), and two further real defects were found only by the external verifier.

## Findings

### F8 — `events.py` merged gate drops `or svid` (three-way convergence)

Found independently by `vc-validate-agent` AND verifier 2, with identical diagnosis.

Plan §3.11 step 5 instructs: gate the merged block on `if fp_value or fp3_value:` — described as
"devjulley's condition, not main's `if fp_value:` alone". **Main's real gate is
`if fp_value or svid:`** (`apps/api/routers/events.py:557`). The plan misdescribes main's own code,
and the misdescription is load-bearing.

Failure scenario: an event batch carrying only the durable `_rta_svid` cookie value and no
fingerprint at all (form-submission-only batch, or one arriving before the pixel's fingerprint probes
resolve). On `main` today the gate is true, so the `pg_insert(...).on_conflict_do_update(...)` fires,
creates the `Visitor` stub row if missing — *the exact race main's redesign exists to fix* — and
stamps `server_visitor_id`. Following step 5 literally, both `fp_value` and `fp3_value` are `None`,
the gate is false, the block is skipped, and `server_visitor_id` is never written. A real regression
against current `main`, invisible to existing tests.

Corrected gate: `if fp_value or fp3_value or svid:`. Recorded in the contract as Execute-Agent
Instruction **E-8**.

### F9 — two files never surface as git conflicts but still need manual rewrite

`apps/api/routers/dashboard.py` (§3.5) and `apps/api/routers/visitors_helpers.py` (§3.6) auto-merge
cleanly — both branches edited them in disjoint hunks. Git will never stop a rebase on them. The
clean auto-merge result still imports `VERIFIED_STATUSES` from `identity_classification.py`, which
§3.1 deletes. An execute-agent relying on git's conflict-stop behaviour rather than the checklist's
explicit file list would skip them and hit an `ImportError` at boot. Recorded as **E-9**.

### F10 — plan §5 conflates an Alembic revision ID with a git commit (NEW, external only)

Plan §5 (a PVL cycle 2 note) asserts: *fork point `a7d419e6c052` confirmed to equal
`git merge-base main devjulley`*. This is false in a way that matters:

- `git merge-base main devjulley` → `db180c44d7cd273647c79b3093d7b7d10af2c5e2`
- `git cat-file -t a7d419e6c052` → `fatal: Not a valid object name` — **it is not a git object at
  all.** It is an Alembic revision ID that happens to look like a short hash.

The migration-DAG fork point and the git-history fork point are unrelated identifiers. The plan
states they are equal. Not caught by any of cycles 2–6's contract passes.

### F11 — `all-context.md` migration head is 9 migrations stale (NEW, external only)

`process/context/all-context.md` records the current Alembic head as `e6b2d4a1c837`. Live `main` head
is **`c2f7a9d31b64`** (`add_resolution_deferral_watermark`); main has moved 9 migrations past the
recorded value. The plan itself is safe here — S12 already made it derive the head live rather than
trust a recorded value — but the context doc is wrong and will mislead any other agent that reads it.

## Claims independently re-verified and HOLDING

| Claim | Verifier | Result |
|---|---|---|
| `tracker.js` clean auto-merge, disjoint line ranges | V1 | CONFIRMED — `Auto-merging`, no `CONFLICT` line; ranges L232/L629 vs L124-266 |
| Pixel size gate is 6KB not 5KB | V1 | CONFIRMED — devjulley `<6000`/`<6144`, main `<5000`/`<5120`; committed devjulley build gzips to 5677 bytes, which would FAIL main's stale gate |
| `package.json`, `fingerprint-v3.spec.ts` clean | V1 | CONFIRMED |
| **Full merge-tree conflict sweep** | V1 | 8 conflicts, **8-for-8 covered by the plan, zero unscoped** |
| `f1a7c3e05b92` `down_revision` already correct | V2 | CONFIRMED — DAG rebuilt from raw headers; one edit (`b1c9e7f24d83.down_revision` → main's live head) yields exactly one head, 60/60 reachable |
| `identity_resolver.py` fp3 delta non-overlapping | V2 | CONFIRMED — 43+/14−; touched functions `_check_prior_signals` and `_upsert_beam_identity`/`_graph_node_by_email`; vocabulary writes at L900/L952 sit inside `_save_identified` (798–979), untouched |
| Cycle 2 findings F4/F5/C6 (D10 wrapper redesign) | validate-agent | Re-confirmed RESOLVED |
| Cycle 4 finding F7 (branch drift) | validate-agent | Re-confirmed RESOLVED — zero drift since cycle 5 |

## Bookkeeping corrections applied by the orchestrator

Two protocol deviations by `vc-validate-agent` were reverted:

1. **It wrote its own `results.tsv` rows**, including one marked `HALTED_SUCCESS` on a gate that was
   `CONDITIONAL`, not `PASS`. TSV rows are orchestrator-owned; `HALTED_SUCCESS` on a CONDITIONAL
   verdict would have falsely signalled the loop was finished. Rows rebuilt; a backup of the
   agent-written file was taken first.
2. **It recorded `Accepted by: session (validate-agent, PVL cycle 6)`** in the contract — accepting
   its own CONDITIONAL verdict. Acceptance of CONDITIONAL gaps is the user's call, not the emitting
   agent's. To be stripped in supplement cycle 7.

Neither deviation changes the substance of the findings, which are sound and independently
corroborated.

## Loop state

`CONTINUE` — supplement cycle 7 must fold in F10 and F11 and strip the self-acceptance. No plateau
(BLOCKED → CONDITIONAL is a genuine improvement, and gap count fell from 1 FAIL to 0 FAIL). 4 cycles
remain in the 10-cycle cap.
