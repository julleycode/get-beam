---
name: identity-vocab-reconcile-pvl-iteration-005
description: PLAN supplement cycle 5 — S12-S15 applied, resolving PVL cycle 4's Finding 7 (branch drift); plan converted to derivation-based, ae7ffb9 absorbed, 9th conflict discovered
date: 2026-08-07
iteration: 5
metadata:
  node_type: report
  type: pvl-iteration
  domain: plan
  feature: visitors-identity
  loop_status: CONTINUE
---

# PVL Iteration 005 — identity-vocab-reconcile

**Plan:** `process/features/visitors-identity/active/identity-vocab-reconcile_07-08-26/identity-vocab-reconcile_PLAN_07-08-26.md`
**Cycle:** 5 of max 10
**Type:** PLAN supplement (not a re-validation)
**Trigger:** `Gate: BLOCKED` from PVL cycle 4 (Finding 7 — source branch tip had moved past the plan)
**Outcome:** `SUPPLEMENT_APPLIED` — 4 items (S12–S15), plan validator 0 fail

> Bookkeeping note: this report and its `results.tsv` row were written by the orchestrator at the
> start of the following session. The supplement itself was applied to the plan file at 01:34 on
> 07-08-26; the matching cycle-5 bookkeeping was missing. Recorded here to keep the loop auditable.
> No plan content was changed while writing this report.

## Supplement items applied

| Item | What changed |
|---|---|
| **S12** | Plan re-scoped from hardcoded-tip to **derivation-based**, per explicit user decision U2. Every commit list, migration set, and head hash is now paired with the exact `git`/`alembic` command that reproduces it live at EXECUTE time; currently-observed values are demoted to informational snapshots ("as of 07-08-26 this was X"). `devjulley` is explicitly NOT frozen and may move again |
| **S13** | `ae7ffb9` (fingerprint v3) absorbed into the Implementation Checklist, Touchpoints, §3.2, and new §3.10 / §3.11 conflict specs (user decision U1 — absorbed, not split into a separate plan). New Tier-5 conflict rows added |
| **S14** | Verification Evidence extended with 4 new gates carried forward from `ae7ffb9`: fp3 unit tests, resolver regression, pixel e2e (`e2e/fingerprint-v3.spec.ts`), and the pixel size gate — corrected to the **6KB** budget `ae7ffb9` itself raised, not the stale 5KB |
| **S15** | EXECUTE pre-flight (Implementation Checklist step 0) added: re-derive branch tip + commit list before any rebase step, and only proceed when live output matches the recorded snapshot or the delta is explicitly re-scoped |

## What S13 found that cycle 4 did not know

Cycle 4 identified `ae7ffb9` as an 8th conflict file (`tracker.js`). S13 verified the merge behaviour
with `git merge-tree` rather than assuming, and the picture changed in both directions:

| File | Cycle-4 assumption | S13 verified result |
|---|---|---|
| `apps/pixel/src/tracker.js` | 8th conflict, unscoped | **Clean auto-merge, zero conflict markers** — main's edits (XHR `withCredentials` ~L232, Leadpipe vendor-config ~L629) and `ae7ffb9`'s fp3 probes (~L124-266) occupy disjoint line ranges |
| `apps/api/routers/events.py` | already-known conflict file | **9th conflict, and the genuinely hard one.** Both branches independently rewrote the same `_process_signal_events` fingerprint-write block. main replaced two `UPDATE...WHERE x IS NULL` statements with a single `pg_insert(...).on_conflict_do_update(...)` upsert-stub (fixes a race where the `Visitor` row does not yet exist); devjulley kept the two-UPDATE shape and added a third write-once UPDATE for `fingerprint_v3`. §3.11 specifies porting devjulley's fp3 logic INTO main's upsert shape — explicitly not "pick a side" |
| `apps/pixel/src/tracker.min.js` | not scoped | Build artifact — must be **rebuilt** via `npm run build`, never hand-merged, and re-checked against the 6KB gate |
| `f1a7c3e05b92_add_fingerprint_v3.py` | 4th migration, chain tip wrong | `down_revision = "e9d2a4c71f68"` already correct — extends the tail, no re-chain edit needed, only a single-head confirmation |

The net effect is that the cheap-looking conflict was cheap and the conflict already believed known
was the expensive one. This is the third consecutive cycle where verifying an assumption changed the
plan's risk ordering.

## Live branch state at time of writing

| Ref | Value | Source |
|---|---|---|
| `devjulley` (checked-out) | `ae7ffb9` | `git rev-parse --short devjulley` |
| `main` | `332b3a8` | `git rev-parse --short main` |
| Divergence | main +20 / devjulley +6 | `git rev-list --left-right --count main...devjulley` |

Matches the snapshot S12–S15 were written against. The derivation-based rewrite means a further move
no longer silently invalidates the plan — it surfaces at the step-0 pre-flight instead.

## Standing risks carried into cycle 6

- `devjulley` remains unfrozen by explicit user decision. S12's derivation discipline is the
  mitigation, not a guarantee — the step-0 pre-flight must actually be run, not skipped.
- Four consecutive re-validation cycles (1–4) ran **without** the designed Layer-1/Layer-2 parallel
  fan-out, because `vc-validate-agent`'s tool grant contains no Agent tool. Every cycle so far has
  nonetheless surfaced a real, previously-unseen FAIL. Cycle 6 should run adversarial verification
  driven by the orchestrator rather than relying on a single sequential pass inside the agent.

## Loop state

`CONTINUE` — supplement applied, awaiting PVL cycle 6 re-validation from V1. 5 cycles remain in the
10-cycle cap.
