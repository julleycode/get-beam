---
name: report:engage-learning-agent-pvl-iteration-005
description: "PVL cycle 5 — P1 stands CONDITIONAL, P2 reaches CONDITIONAL 0-FAIL; 3a/3b re-BLOCKED by the config-key move's own propagation misses (3 FAILs); peer-session findings folded in"
date: 17-08-26
feature: campaigns-outreach
metadata:
  node_type: report
  type: pvl-iteration
  cycle: 5
---

# PVL Iteration 005 — engage-learning-agent

## Verdicts (cycle 5)

| Plan | Gate | FAILs | CONCERNs | Note |
|---|---|---|---|---|
| phase-1-signal-acquisition | CONDITIONAL (stands, cycle-4 contract) | 0 | — | R1–R4 label fixes applied in cycle-5 supplement |
| phase-2-memory-privacy | **CONDITIONAL** | 0 | 2 (label-class C5-1/C5-2) | First 0-FAIL for P2; EXECUTE-eligible once acceptances recorded |
| phase-3a-learning | BLOCKED | 1 | 1 | Signature `(stats, min_outcomes, min_positive_rate)` applied at A1 only; Public Contracts/Overview still say `(stats, config)` |
| phase-3b-autonomy | BLOCKED | 2 | 3 | Duplicated Steps A/B survive under the MOVED banner (A3 re-adds the moved config keys; B1–B5 violate ai_reply ownership); driver neither passes nor is gated on operator thresholds — hardcoded `(stats, 20, 0.4)` would pass every gate (icp_fit silent-no-op class) |

All 7 cycle-4 findings verified closed. New-FAIL source = the cycle-5 move's own propagation, caught by the NEW-DESIGN CHECK the orchestrator ordered.

## Peer-session coordination (same worktree, session "Beam data flywheel three levers")

Ownership settled: this session keeps engage-learning-agent PLAN/PVL; peer dropped its held PLAN; peer's SPEC remains the locked input. Peer surfaces (e2e_disposable lane, coop files) disjoint from this program. all-context.md ordering agreed: peer edits first (identity-coop status), this program's AC-20 edit is string-anchored and lands at 3b EXECUTE after. Peer committed `jobs/scheduler.py` + `test_scheduler_job_config.py` count bump (25→26) tonight — re-derive-at-EXECUTE rule already covers this. Peer INNOVATE findings cross-checked: attribution-mint-in-sender and fence-same-phase already covered; poisoning largely covered (exact linkage + per-reply dedup + DISTINCT-contact rate) with two residues adopted: (1) author ≠ own-account exclusion added to P1 D2 + gate; (2) accrual-rate sanity cap → backlog stub (defense-in-depth). Peer's `ON CONFLICT`-without-index silent-failure case (asyncpg InvalidColumnReferenceError swallowed per-row) noted as extra falsifier context in P1 test-infra notes.

## Orchestrator decisions for cycle-6 supplement (binding)

- 3a: propagate explicit-arg signature to Public Contracts (:144) + Overview (:67); umbrella :566 moves engage_autonomy.py to the 3a file list.
- 3b: DELETE duplicated Step A/B blocks (banner stays); C5 passes `settings.engage_autonomy_min_outcomes`/`_min_positive_rate` explicitly; NEW G28 — override both config values, run driver, assert decision flips + no numeric literals at the call site; stale signatures :71/:248 propagated; entry-gate import-assert for autonomy_gate + select_strategy_from_outcomes; AC-11 note (proven by G2 + G28 together).
- P2: delete the stale four-gate phrase + its self-falsifying parenthetical; F4d evidence-row rename.
- P1: D2 gains author ≠ own-account exclusion (site's own posting account cannot produce reply_received) + gate leg; backlog stub for accrual-rate cap; InvalidColumnReferenceError falsifier noted. P1 validator does a scoped delta-check on D2/F-series only.
- Plan-agent standing rule: a MOVED banner MUST be accompanied by deletion of the moved block, verified mechanically; duplicate scan gains a cross-plan dimension for split plans.

## Pending USER decisions (unchanged)

KG-1 handle-rename drift; AC-4 site-link-offer backlog stub.
