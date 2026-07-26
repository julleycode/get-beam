# PVL Iteration 001 — capacity-hardening

Date: 2026-07-25
Loop: PVL (plan-validate-fix)
Cycle: 1
Plan: capacity-hardening_PLAN_25-07-26.md
Verdict entering cycle: Gate: BLOCKED (first pass — 3 FAIL-severity gaps, 6 CONCERN)

## Gaps addressed (9/9)

| Gap | Severity | Section | Resolution |
|---|---|---|---|
| 1 | FAIL | phase-3 merge design | Verified 7-column merge table (first_seen removed — insert-only); D6 keep-existing-if-set for first_touch_referrer/ai_source; D7 avg_time_on_page + intent_score DESCOPED to full-recompute-only (no new column/migration) |
| 2 | FAIL | acceptance-criteria | AC1/AC4 re-tiered Fully-Automated → Hybrid (raw-SQL aggregator cannot unit-test), retargeted Docker-gated integration |
| 3 | FAIL | verification-evidence | Parity/boundary gates point at existing integration files; regression surface adds test_optout_flow.py + test_ingest_abuse_hardening.py |
| 4 | CONCERN | phase-0 P0.1 | Key logging → sha256[:12] + xff_len; raw IP banned (PII rule) |
| 5 | CONCERN | phase-1 problem | Restated around dead beat_schedule; *_async_push × celery_worker_enabled truth table added |
| 6 | CONCERN | phase-ordering | Worker deploy (1a) hard-gated behind Phase 3 debounce; order now 1(b) → 2 → 3 → 4 → 1(a) |
| 7 | CONCERN | phase-3 checklist 6 | No-op removed; _upsert_company double-increment risk (lines 414-416) added with mitigation |
| 8 | CONCERN | phase-2 checklist 4 | Marked satisfied by existing 11 tests in test_ip_resolution.py; duplicate-file ban |
| 9 | CONCERN | phase-4 4b/4c | Both asyncpg cache keys preserved; job count corrected to 11 add_job (4 conditional, 1 CronTrigger excluded from jitter assertion) |

## Design decisions locked (orchestrator, conservative defaults — user may override at next gate)

- intent_score + avg_time_on_page: full-recompute-only (staleness bound = hourly beat sweep cadence)
- first_touch_referrer/ai_source: keep-existing-if-set merge (regression test_first_touch_beats_lexicographic_max must stay green)
- Phase 4d (Redis socket_timeout): independently shippable, orderable first in EXECUTE

## New coupling surfaced this cycle

D7 staleness bound depends on hourly beat sweep — the exact surface Gap 5 proves is DEAD today (no deployed worker). Plan now states Phase 3 must not ship flag-ON until an equivalent scheduled full recompute exists. Real Phase 1 ↔ Phase 3 coupling; flagged for validate cycle 2 scrutiny.

## Artifacts

- Plan validator after supplement: 0 failures, 0 warnings (928 lines)
- Next: re-spawn vc-validate-agent from V1
