---
name: pii-at-rest-pvl-iteration-002
description: PVL cycle 2 trigger — V1 re-run BLOCKED on census-mechanism FAILs (grep scope holes)
date: 2026-08-07
metadata:
  type: pvl-iteration-report
  plan: pii-at-rest_PLAN_22-07-26.md
  cycle: 2
  loop: PVL
---

# PVL Iteration 002 — pii-at-rest

**Verdict pass 2:** `Gate: BLOCKED` — cycle 1's 6 gaps all independently confirmed closed; 3 NEW mechanical FAILs found by the validator's own census.

## New FAILs

- **F4** census short by 2 predicate sites: `identity_resolver.py:1351` (`full_name.isnot(None)` — no `full_name_bidx` column exists → THIRD edit shape; inside a try/except that swallows to debug-log → silent post-Phase-5 failure degrading owned-data path into paid re-resolution) + `jobs/backfill_enrichment.py:62` (`email.is_not`). Plus 5 read sites in daily_digest/job_change_detector/graph_erasure/backfill_enrichment/resolution_tasks.
- **F5 (root cause)** the plan's self-correction greps structurally CANNOT find these: (1) scope only `services routers` (+`agents` in Phase 4 gate) — never `apps/api/jobs/` or `apps/api/tasks/`; (2) `email\.isnot(` misses the `.is_not(` spelling; (3) NOT-NULL grep never includes `full_name`.
- **F6** AC3/AC6 `-k` filter collects 54/2076 tests, excluding covering tests for 5 census sites (incl. 3 of the 4 added in cycle 1).

CONCERNs: C7 `contact_importer.py:167` is projection not filter (consumer `:178` compares plaintext — coordinated 3-line edit needed); C8 anchors drifting live (113→130 uncommitted same-day); C9 script 321 vs 322 lines.

## Orchestrator decision (recorded)

Gap-class rule (b) letter says backlog-and-stop after 1 cycle. **Overridden for ONE final cycle** under autopilot decision policy, rationale: F5 repairs the *mechanism* that produced a wrong census on two consecutive passes — exact precedent social-context-merge, which converged on pass 3 after the same class of fix. Text-only, reversible, cheap. Hard cap for this run: if pass 3 is not PASS/convergent-CONDITIONAL, plan goes to backlog note + hold.

**Run-disposition (pre-decided):** regardless of pass-3 verdict, pii-at-rest does NOT EXECUTE inside this autopilot run. Phases 3-5 are high-risk schema/data-migration (destructive Phase 5), Docker is down (no migration round-trip evidence possible → EVL cannot go green), the high-risk evidence pack does not exist, and the Phase-1 backfill RUN (GDPR prerequisite) is a live-DB operator action. Target end-state this run: converged validate-contract + explicit prerequisites list.

**Next:** supplement cycle 2 (sequential, single vc-plan-agent opus — fixes interdependent: fix greps → re-derive → widen gates).
