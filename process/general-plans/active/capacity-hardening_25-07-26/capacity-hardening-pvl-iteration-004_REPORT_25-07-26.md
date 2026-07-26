# PVL Iteration 004 — capacity-hardening (loop close)

Date: 2026-07-25
Loop: PVL (plan-validate-fix)
Cycle: 3 re-validation (loop-closing pass)
Plan: capacity-hardening_PLAN_25-07-26.md
Verdict: Gate: CONDITIONAL (verbatim) — 0 FAIL / 5 CONCERN / 4 PASS

## Trajectory

| Cycle | FAIL | CONCERN | PASS |
|---|---|---|---|
| 1 (baseline validate) | 2 (3 gap-rows) | 6 | 1 |
| 2 (revalidate) | 2 | 2 | 5 |
| 3 (revalidate, close) | 0 | 5 | 4 |

## Cycle-3 supplement verification

- Gap 10 confirmed: zero celery references in Dockerfile/railway.json/docker-compose; re-derived ordering holds
- Gap 11 correctly sited (scheduler.py, config convention, _aggregate_all shape) — 3 delivery holes found, fixed in-contract
- Gap 12 confirmed: beat table matches source; NOTE on disk; 3-clause exit gate sound

## 5 accepted CONCERNs — binding execute instructions (NOT optional)

| # | Issue | Binding fix |
|---|---|---|
| 1 | Sweep starvation on hot sites (per-ingest debounce always wins SET NX) + fail-open wrong direction (full-vs-incremental race inflates counters) + missing next_run_time (repo precedent: resolution_sweep "effectively never ran") | E16 4-part yield-marker protocol, E17 flag-conditional fail-open, E18 boot offset; gates AC-V5/V6/V7 |
| 2 | Beat-ban only half-automatable (Railway dashboard command unreadable by grep) | AC-V8 repo-side + operator item P0.5 + E21 |
| 3 | Jitter counts stale in 4 places (11 add_job today → 12 post-Phase-3) | corrected; E20 AST-derived counts |
| 4 | Items 8 vs 11c conflict (sweep mirroring watermark-aware _aggregate_all inherits incremental branch → re-creates cycle-2 FAIL-A) | E19; gate AC-V10 |
| 5 | Phase 4 count regression from cycle-3 edits | corrected in plan body |

## Loop close

- results.tsv: header + baseline + 3 cycle rows + final row (HALTED_SUCCESS) — VALIDATE→EXECUTE mechanical gate satisfied
- Contract: generated-by outer-pvl, date 2026-07-25, supersedes cycle-2, validator 0 failures
- Next: /goal block emission → ENTER EXECUTE MODE (explicit user command required)
- Operator pre-EXECUTE items: P0.1-P0.4 + new P0.5 (Railway dashboard: confirm no worker service AND no -B/beat command)
