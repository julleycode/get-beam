# PVL iteration 003 — reveal-display-policy

**Date:** 17-08-26
**Loop:** plan-validate (PVL), cycle 3 — re-validate from V1 + transcription supplement
**Verdict:** `Gate: CONDITIONAL` (0 FAIL / 2 CONCERN H1-H2 + NOTEs) — **terminal classification**
**Supplement:** cycle 3 transcription-only, 8/8 applied with grep-proofs, validator 0 failures 0 warnings
**Orchestrator spot-check:** PASS — all cycle-3 edits present in plan body; only remaining old-text hits are deliberate evidence citations inside the Validate Contract (lines 557/558/575, section starts :491). No validate cycle 4 needed (coop-disposable cycle-3 transcription precedent).

## Cycle 3 verification highlights

- Both cycle-2 FAILs verified closed against source (not against supplement claims).
- Blast radius independently re-derived: 14 files / 7 test files — supplement's arithmetic CORRECT.
- AC-12 proven non-vacuous: 7 user-facing banned-token strings enumerated repo-wide, 7 covered.
- Advisory validator warning: half-right claim — regex genuinely non-matching (mechanical), semantics fine; cleared incidentally.
- Live baselines: unit 1963p/2s, vitest 185p, crosscheck 33p, integration 661 collected (537 figure was stale).
- H1 root-caused live: integration errors were shared-:5433 contention from sibling session PID 23769 — now documented as execute-instructions E-11/E-12 (never grounds to punt a gate).

## Terminal state

`Gate: CONDITIONAL` is the plan's DESIGNED terminal state — the flag-ON display path is structurally ungated pre-flip (icp_fit precedent: flag-OFF-only evidence is vacuous). PASS is impossible by construction.

## Residuals requiring explicit user acceptance before EXECUTE

1. Flag-ON display path has no automated gate until `location_reveal_enabled` flips — closed post-deploy by manual probe (documented in plan known-gaps).
2. Real-network matrix (real VPN + real mobile hotspot reveal checks) — backlog stub `reveal-policy-real-network-matrix_NOTE_17-08-26.md`, mandatory before any prod flag flip.

## Loop summary (4F/4C → 2F/4C → 0F/2C → 0F/0 open)

| Cycle | Verdict | Closed | New |
|---|---|---|---|
| 1 | BLOCKED 4F/4C | — | design sound, checklist under-specified |
| 2 | BLOCKED 2F/4C (+verifier 15 findings) | 6/8 | scan-scope vacuity, wrong deletion ranges, ghost-applies |
| 3 | CONDITIONAL 0F/2C | all | bookkeeping only; transcription supplement closed them |

Anti-ghost-apply grep-proof mechanism (added cycle 2) held: zero declared-but-not-applied recurrences in cycles 2-3.

## EXECUTE handoff constraints (carry verbatim into execute-agent prompt)

- E-11/E-12/E-13 (baseline-first, shared-DB contention ≠ regression, hash 3e2ddb5)
- Cross-session: demo.py:603-614 X API public_metrics call = DO NOT restructure (session dd dependency); no mutating git (stash list must stay 11, HEAD de6261c at handoff); no docker container kills (sibling debugger lane live); stage-by-exact-path only, never bulk-add apps/web/public/beam/ (user's uncommitted index.html +306 lines sits there); scratchpad files prefixed reveal-policy-*.
- Section ordering: 25a funnel decider FIRST in G; 30a/31a-31b baselines BEFORE new legs.
