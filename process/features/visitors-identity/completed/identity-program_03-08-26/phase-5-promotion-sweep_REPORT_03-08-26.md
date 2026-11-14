---
phase: phase-5-promotion-sweep
date: 2026-08-05
status: COMPLETE_WITH_GAPS
feature: visitors-identity
plan: process/features/visitors-identity/active/identity-program_03-08-26/phase-5-promotion-sweep_PLAN_03-08-26.md
---

# Phase 5 — Click→Verified Promotion Sweep — EXECUTE report

**TL;DR:** Implemented as planned. New `promotion_sweep_runner.py` + thin scheduler wrapper +
default-OFF feature flag + 4 integration tests. Unit lane: 1628 passed / 1 failed — the single
failure is a pre-existing, date-rollover-caused break in a CONCURRENT session's `timeseries.py`
test, unrelated to this phase. Integration legs are Docker-gated known-gaps (no Docker in this
environment, pre-named at VALIDATE).

## What Was Done

| Checklist | Outcome |
|---|---|
| A0 | `apps/api/services/promotion_sweep_runner.py` created (heavy logic, trigger-agnostic, mirrors `resolution_runner.py`). `_promotion_sweep_job()` thin wrapper added to `apps/api/jobs/scheduler.py`. `promotion_sweep_enabled: bool = False`, `promotion_sweep_interval_minutes: int = 2`, `promotion_sweep_window_floor_minutes: int = 15` added to `config.py`. Registration gated `if settings.promotion_sweep_enabled:` (matching `changelog_sync` / `connection_nudge`). NOT placed in `apps/api/tasks/` (Celery-only). |
| A1 | Registered at 2-minute cadence with explicit `jitter=15`, `misfire_grace_time=60` — manually verified, and now also AST-asserted by the existing `test_scheduler_job_config.py` gate. |
| A2 | Query: `VisitorEmail.source == "utm"` AND `created_at >= cutoff` joined to `Visitor` with `identity_status.not_in(("identified","merged"))`, `.distinct()`, capped at `PROMOTION_SWEEP_MAX_PER_RUN = 200`. No query-level `do_not_resolve` filter — inherited from `resolve()`'s first two guards, as the plan specifies. |
| A3 | Calls `IdentityResolver(db).resolve(visitor)`. Defensive check implemented: for a non-merged promotion, if `identified.resolution_provider` is outside `_DETERMINISTIC_PROVIDERS`, the run logs `promotion_sweep_unexpected_paid_provider` at ERROR and increments an `unexpected_paid` counter, which the tests assert is `0`. |
| A4 | Idempotency rests on (a) the query excluding both terminal statuses, and (b) `_save_identified`'s IntegrityError fallback. A Postgres advisory lock (`beam_promotion_sweep`) WAS mirrored from `resolution_runner.py` (optional per contract) for single-flight across replicas; it fails open on SQLite. |
| A5 | Window = `max(2 * cadence, promotion_sweep_window_floor_minutes)` → **15 minutes** at the default 2-minute cadence. Residual sustained-outage risk documented in the module docstring and in the config comment. |
| B1/B2 | 2-min cadence + 15-min window sits inside the 5-min SLA. `/ingest` is untouched — the sweep is a separate scheduled job; asserted by `test_ingest_does_not_block_on_resolution`. |
| C1/C1a/C2/C3 | `tests/integration/test_promotion_sweep.py` written — 4 tests, collect clean. C1a asserts the confirmed POINTER semantics (`merged` + `canonical_visitor_id` → phantom, phantom row untouched, no duplicate identity row), NOT `identified` on the click-derived visitor. |

Alembic head re-verified live before EXECUTE: `e9d2a4c71f68`, single head, no drift. No migration authored (none needed).

## What Was Skipped or Deferred

- Live integration run of `tests/integration/test_promotion_sweep.py` — no Docker in this
  environment (`which docker` → NOT FOUND). Pre-named at VALIDATE (C-4 note), not silently absorbed.

## Test Gate Outcomes

| Gate | Command | Result |
|---|---|---|
| regression (Fully-Automated) | `.venv/bin/python3.11 -m pytest tests/unit -q` | 1628 passed, **1 failed**, 2 skipped — failure is pre-existing/unrelated (see below) |
| scheduler AST gate | `.venv/bin/python3.11 -m pytest tests/unit/test_scheduler_job_config.py -q` | 12 passed |
| web typecheck | `cd apps/web && npx tsc --noEmit` | exit 0 (no-op; backend-only phase) |
| AC11-a/b/c + safety-1 (Hybrid) | `.venv/bin/python3.11 -m pytest tests/integration/test_promotion_sweep.py -q` | **KNOWN-GAP — Docker unavailable.** `--collect-only` → 4 tests collected clean (imports/syntax valid) |

**Unit-lane failure analysis (not attributable to Phase 5):**
`tests/unit/test_candidate_call_sites.py::TestTimeseries::test_query_counts_candidate_rows_separately`
fails with `RuntimeError: coroutine raised StopIteration`. Root cause: the test hardcodes the date
`"2026-08-04"` and does `next(p for p in out["series"] if p["date"] == "2026-08-04")`; today is
2026-08-05, so the generated series no longer contains that date and `next()` raises. It is a
date-rollover break in a **concurrent session's** files (`timeseries.py` / `kpi.py` /
`test_candidate_call_sites.py`, all mtime 2026-08-04, modified before this session started). It
fails identically in isolation and touches none of Phase 5's files. Total test count is unchanged
vs the 1629 baseline (1628 + 1 = 1629) — Phase 5 introduced zero new failures.

## Plan Deviations

1. **`tests/unit/test_scheduler_job_config.py` edited (not named in Touchpoints).** Within
   blast-radius. That AST gate asserts an exact scheduler inventory (16 total / 14 interval) and
   its own docstring instructs re-deriving the arithmetic when a job is added ("never relax this
   gate"). Updated to 17 / 15 / 2 with the provenance line appended. Adding the job without this
   edit would have made the gate red.
2. **`IdentityResolver(db)` rather than the literal `IdentityResolver(db, redis_client)`.** Same
   behavior — the constructor's `redis_client` defaults to `None` and self-resolves via
   `get_redis()`. Matches the `resolution_runner.py` precedent exactly. Naming-level only.
3. **Advisory lock included** (contract marked it optional). Consistency with the established
   sweep convention; fails open where advisory locks are unavailable.

No hard-stop-class deviations. `identity_resolver.py` unchanged (0 lines). `is_emailable_identity`
unchanged. Phase 2 guard / Phase 3 decoration / Phase 4 import surfaces untouched.

## Test Infra Gaps Found

- No Docker in the EXECUTE environment → all 4 Hybrid gates unrunnable. Pre-named at VALIDATE.
- `validate_email` performs a live MX DNS lookup on the promotion path; the integration test
  autouse-patches it for determinism. Worth knowing for any future test on this path.

## Closeout Packet

- Selected plan: `process/features/visitors-identity/active/identity-program_03-08-26/phase-5-promotion-sweep_PLAN_03-08-26.md`
- Finished: A0–A5, B1–B2, C1/C1a/C2/C3 (written).
- Verified: unit lane (no new failures), scheduler AST gate, web typecheck, import smoke, test collection.
- Unverified: the 4 Hybrid integration gates (Docker).
- Classification: **Keep in active/testing** — code-complete, but AC11's proving tests are unrun.
- Follow-up plan stubs created: none (the Docker gap is the pre-existing program-wide known-gap class).
- CONTEXT_PARTIAL items: none.

## Forward Preview

- **Test Infra Found:** no Docker; `validate_email` needs patching in tests on the promotion path;
  `test_scheduler_job_config.py` must have its arithmetic re-derived by any phase adding a job.
- **Blast Radius Changes:** new `apps/api/services/promotion_sweep_runner.py`; `jobs/scheduler.py`
  now has 17 `add_job` calls; `config.py` gained 3 `promotion_sweep_*` settings (all default-OFF /
  inert). No schema change, no migration, alembic head still `e9d2a4c71f68`.
- **Commands to Stay Green:** `.venv/bin/python3.11 -m pytest tests/unit -q` (expect 1628/1 with the
  unrelated date-rollover failure until the concurrent session fixes `test_candidate_call_sites.py`).
- **Dependency Changes:** none.
- **Phase 6 note:** this sweep is the mechanism that starts producing `merged` click-derived rows in
  volume — the tracked double-count risk at
  `process/features/visitors-identity/backlog/merged-visitor-consumer-awareness_NOTE_04-08-26.md`
  goes from theoretical to active with this phase's rollout.
