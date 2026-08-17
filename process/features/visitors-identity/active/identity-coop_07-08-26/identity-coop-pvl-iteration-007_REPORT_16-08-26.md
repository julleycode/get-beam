---
name: report:identity-coop-pvl-iteration-007
description: "PVL cycle 7 (16-08-26) — cycle-3 re-validate verdict: Gate CONDITIONAL, 0 FAILs; savepoint mechanism proven in pinned SQLAlchemy source; 2 instruction-class residuals (E-S1/E-S2); awaiting user acceptance + EXECUTE"
date: 16-08-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
  phase: phase-1-ledger-substrate
  iteration: 7
---

# PVL Iteration 007 — Cycle-3 verdict: CONDITIONAL, converged (16-08-26)

## Verdict

`Gate: CONDITIONAL` — 0 FAILs. Supplement contract cycle 3 written in place (supersedes cycle 2).
Gap trajectory across the loop: 8 → 4 → 0 FAILs + 2 instruction-class residuals. SATURATED.

## Source-verified closures

- **SUP2-F1:** savepoint mechanism proven against pinned SQLAlchemy
  (`session.py:1084-1089` — BEGIN_NESTED not in the is_begin tuple → session flushes BEFORE the
  SAVEPOINT is emitted → the ErasureRequest INSERT lands ahead of the savepoint and
  `ROLLBACK TO SAVEPOINT` cannot discard it). SG-15 distinguishes savepoint vs bare try/except
  (fake-savepoint pattern; also self-protecting against empty-bidx vacuity).
- **SUP2-C1:** whole-function monkeypatch keeps all 5 legs meaningful; SG-9 non-vacuous
  (guard precedes digest branch).
- **SUP2-C2:** 9 `-k` selectors extracted independently, 0 collisions, exactly one checklist item
  per selector; budget arithmetic ~430 vs ≤480; shorthand resolves under single-file and split.
- **SUP2-C3:** replacement docstring accurate post-S2; ~7 vs ≤8 lines.

## Residuals (instruction-class — no plan edit needed)

- **E-S1** (from N-A): name the SG-15 unit test to match `-k tombstone_write_failure`
  (today: 27 deselected, exit 5 — loud).
- **E-S2** (from N-B): unit-file budget ~35-45 realistic vs ≤30 written — treat as bookkeeping,
  extend `_scalar_result` fake for `.scalars().all()`.
- **E-S3:** use the `monkeypatch` fixture, NOT `setattr` (leak would poison SG-9/SG-10 which
  need the flag OFF).

## Known-gaps for acceptance

1. SG-16 optional Hybrid leg: without it, Postgres honouring the savepoint is unproven
   (SG-15 proves entry only). Docker IS available — implementable.
2. Multi-process concurrency probe for the H2 window: not gated (sequential window covered).

## Status

EXECUTE mechanical gate (b) satisfied (results.tsv ≥3 lines, ≥1 fix cycle). Awaiting user
acceptance of the CONDITIONAL + explicit ENTER EXECUTE MODE. No self-acceptance performed.
