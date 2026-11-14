---
name: note:roster-precision-lost
description: "roster-precision Part A code, its plan/SPEC/validate-contract, and the Part B wiring plan were never committed and are lost; any roster ranking work needs a fresh design through PLAN + VALIDATE"
date: 14-11-26
feature: visitors-identity
---

# roster-precision — work lost, redesign required

**Status:** open — nothing to resume. Found by the 14-11-26 repo audit.

## Bottom line

Everything from the 07-08-26 roster-precision effort is gone. It was never committed. The audit
checked every ref (branches, tags, the deleted-branch SHAs in
`process/general-plans/backlog/deleted-branches-backup_NOTE_14-11-26.md`) and the disk: there is no
copy of the code, the tests, the plan, the SPEC, the validate-contract, or the Part B plan.

## What it was (from the context doc written at the time — the only surviving record)

- **Goal:** make the Hunter/Apollo company-level contact pick informed instead of arbitrary.
  Hunter already returns (and bills for) 5 employees; `hunter.py` kept `emails[0]` and discarded 4.
- **Part A (`roster-precision_07-08-26`)** — reported as shipped + EVL-green but uncommitted:
  - `apps/api/services/roster_ranking.py` — ~392 lines, zero imports, pure deterministic scorer:
    page-to-role affinity, geo affinity, weighted score, a degradation rule that drops a missing
    signal from BOTH numerator and denominator, deterministic tie-break.
  - `tests/unit/test_roster_ranking.py` — 44 tests.
  - It was never called by anything (dead code until Part B).
- **Part B (`roster-precision-wiring_07-08-26`)** — planned, never validated: roster retention,
  exclusion + suppression + a site-wide `email_bidx` merge-collision guard, redaction of all
  candidates, `IdentifiedVisitor.roster_selection` JSONB + migration, a `roster_excluded` ledger
  outcome, merge-preserving upsert, detail-endpoint surface, flag `roster_precision_enabled`
  default OFF.
- **Invariant it carried:** nothing becomes emailable — `is_emailable_identity("hunter")` stays
  `False`.

## What is lost

| Artifact | State |
|---|---|
| `apps/api/services/roster_ranking.py` | lost (never committed) |
| `tests/unit/test_roster_ranking.py` (44 tests) | lost |
| Part A plan, SPEC, validate-contract, PVL cycle reports | lost |
| Part B plan (`roster-precision-wiring_07-08-26`) | lost |
| The four PVL cycles of findings (F-H1, F-H2-rev, F-H3, F3, F6, the seven-site `identity_status` census, fixture shapes) | lost — only their names survive in old context text |

## What survives

- The ranking **pattern**, re-derived in the archived plan
  `process/features/visitors-identity/completed/ip-best-selection-retrigger_09-08-26/ip-best-selection-retrigger_PLAN_09-08-26.md`
  (around line 256: "the recovered `roster_ranking` contract — that file was never committed … a
  pattern to re-derive, not code to reuse"; and the ranking-key table that reuses the
  drop-from-numerator-and-denominator abstain rule). It is a pattern reference, not code.

## Rules for any restart

1. Treat it as a new feature: RESEARCH, SPEC, PLAN, VALIDATE from V1. Do not try to "resume".
2. Do not trust the lost PVL finding names as a checklist — re-derive against current `main`
   (the resolver, ledger taxonomy, and identity vocabulary have all changed since 07-08-26).
3. Keep the invariant: a company-level pick never becomes emailable.
4. Test baselines must be re-measured. Any unit count that includes "+44 roster tests" (the old
   "1324 passed") is not reproducible.

## Lesson

"Shipped + EVL-green, uncommitted" is not shipped. Work that is not committed can vanish with the
worktree. Commit at EVL-green before closing a session.
