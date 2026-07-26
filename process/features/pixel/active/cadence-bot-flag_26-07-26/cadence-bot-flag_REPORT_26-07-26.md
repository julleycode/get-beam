---
phase: cadence-bot-flag
date: 2026-07-26
status: COMPLETE_WITH_GAPS
feature: pixel
plan: process/features/pixel/active/cadence-bot-flag_26-07-26/cadence-bot-flag_PLAN_26-07-26.md
---

# Cadence Bot Flag — EXECUTE Report

TL;DR: all 15 plan steps implemented; 25/25 unit + 7/7 integration + 602-test full unit lane green,
web typecheck clean, migration offline-validated both directions and NOT live-applied. 4 pre-accepted
known-gaps carried unchanged. Classification: **Keep in active/testing** (AC-8/AC-9 Agent-Probe
manual render checks not yet performed).

## What Was Done

| Step | Item | Status |
|---|---|---|
| 0 | Live migration-head re-verify (`d5b1f7c3a908`, single head) | DONE |
| 1 | `config.py` — 6 new `# ─── Cadence bot flag ───` settings, all default OFF/bounded | DONE |
| 2 | Migration `e6b2d4a1c837_add_cadence_bot_flag.py`, chained on the live head | DONE (offline-validated only) |
| 3 | `services/cadence_bot_flag.py` — 3 pure functions, zero I/O | DONE |
| 4 | `tests/unit/test_cadence_bot_flag.py` — 25 tests | DONE (green) |
| 5 | `services/cadence_bot_flag_sweep.py` — bounded-read sweep, sticky OR-merge, fail-open | DONE |
| 6 | `jobs/scheduler.py` — `_cadence_bot_flag_sweep_job` + registration (jitter=90, grace=300) | DONE |
| 7 | `models/visitor.py` — `is_bot_suspect` on `Visitor` + `IdentifiedVisitor` | DONE |
| 8 | Regression proof: `visitor_aggregator.py` untouched | DONE (0 lines changed) |
| 9 | Regression proof: `is_emailable_identity()` untouched, still 3 params | DONE (0 lines changed) |
| 10 | `schemas/visitors.py` — `is_bot_suspect: bool = False` on `VisitorOut` | DONE |
| 11 | AC-5 structural-isolation grep bundle | DONE (code-level clean; matches are docstring prose only) |
| 12 | Detail-page badge + sidebar `InfoRow` | DONE (Agent-Probe check pending) |
| 13 | List-page per-row badge | DONE (Agent-Probe check pending) |
| 14 | `tests/integration/test_cadence_bot_flag.py` — 7 tests | DONE (green) |
| 15 | AC-14 operator runbook (inline in plan) | DONE |

## Touched Files

```
apps/api/config.py                                                (append-only block)
apps/api/models/visitor.py
apps/api/schemas/visitors.py
apps/api/jobs/scheduler.py
apps/api/services/cadence_bot_flag.py                             (new)
apps/api/services/cadence_bot_flag_sweep.py                       (new)
apps/api/migrations/versions/e6b2d4a1c837_add_cadence_bot_flag.py (new)
apps/web/src/lib/api-types.ts                                     (deviation 4)
apps/web/src/app/dashboard/visitors/page.tsx
apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx
tests/unit/test_cadence_bot_flag.py                               (new)
tests/integration/test_cadence_bot_flag.py                        (new)
tests/unit/test_scheduler_job_config.py                           (deviation 1)
process/features/pixel/active/cadence-bot-flag_26-07-26/cadence-bot-flag_PLAN_26-07-26.md
```

No file outside the plan's blast radius was modified. `routers/events.py`,
`visitor_aggregator.py`, `identity_classification.py` all show 0 changed lines.

## Test Gate Outcomes

| Gate | Command | Outcome |
|---|---|---|
| AC-1/2/3/5/11/12/13 | `.venv/bin/python3.11 -m pytest tests/unit/test_cadence_bot_flag.py -m unit -v` | PASS — 25/25 |
| AC-3 non-vacuity | conjunction→`or` mutation, re-run unit suite | PASS — mutation killed (3 failures), restored green |
| AC-4/5/6/7/10 + sweep e2e | `.venv/bin/python3.11 -m pytest tests/integration/test_cadence_bot_flag.py -m integration -v` | PASS — 7/7 |
| Migration upgrade (offline) | `alembic upgrade d5b1f7c3a908:head --sql` | PASS — 2 × `ADD COLUMN ... BOOLEAN DEFAULT false NOT NULL` (scoped range, see deviation 2) |
| Migration downgrade (offline) | `alembic downgrade head:-1 --sql` | PASS — 2 × `DROP COLUMN` |
| Full unit-lane regression | `.venv/bin/python3.11 -m pytest tests/unit -m unit` | PASS — 602 passed / 2 skipped |
| Prior-program regression | `pytest tests/integration/test_ingest_abuse_hardening.py tests/unit/test_agent_origin_exclusion.py` | PASS — 34/34 |
| Web typecheck | `npx tsc --noEmit` (apps/web) | PASS — exit 0 |
| AC-8 detail badge | Agent-Probe manual render check | NOT PERFORMED — CONDITIONAL |
| AC-9 list badge | Agent-Probe manual render check | NOT PERFORMED — CONDITIONAL |
| AC-14 live crawler | Operator runbook, post-deploy | NOT PERFORMED — known-gap by SPEC design |
| Migration live round-trip | disposable Postgres | NOT PERFORMED — known-gap (no `docker` CLI in this env) |

## Plan Deviations

Four, all documented verbatim in the plan's new `## Execution Notes` section; all within blast
radius, none touching a hard-stop surface (no schema-beyond-plan, no auth, no billing, no ingest
path, no emailability):

1. `tests/unit/test_scheduler_job_config.py` job-count arithmetic 12/11 → 13/12 (the tripwire's own
   instruction on adding a job; no assertion weakened).
2. Offline `--sql` upgrade scoped to `d5b1f7c3a908:head` — the unscoped form fails inside the
   unrelated `b7d3e9f1a4c2_add_ad_connections.py` (`sa.inspect(bind)` vs offline `MockConnection`).
3. Sweep cutoff uses naive `datetime.utcnow()` — `events.created_at` is a naive column and asyncpg
   rejects aware bound params. Repo precedent: `visitor_aggregator._decay_multiplier`.
4. `apps/web/src/lib/api-types.ts` gained `is_bot_suspect?: boolean` (type-only, needed for the
   badges to typecheck).

## Test Infra Gaps Found

- **Pre-existing, unrelated:** `b7d3e9f1a4c2_add_ad_connections.py` is not offline-`--sql`-safe
  (`sa.inspect(bind)` on a `MockConnection`). Any future full-chain `alembic upgrade head --sql`
  will fail until that migration guards the inspect call. Not fixable within this plan's scope.
- `apps/web` still has zero React component-render infrastructure (no `@testing-library/react`,
  no jsdom vitest project, zero `.test.tsx`) — the plan's Known-Gap #4 backlog candidate stands.
- `docker` CLI is absent from this environment, although a local Postgres was reachable, so the
  integration lane ran. The migration live round-trip still could not be performed.

## Closeout Packet

- **Selected plan:** `process/features/pixel/active/cadence-bot-flag_26-07-26/cadence-bot-flag_PLAN_26-07-26.md`
- **Finished:** all 15 steps; AC-1–AC-7 and AC-10–AC-13 proven by automated gates.
- **Verified vs unverified:** verified = every Fully-Automated + Hybrid gate in the C3 table, plus
  full-lane regression and web typecheck. Unverified = AC-8/AC-9 (Agent-Probe render), AC-14 (live
  crawler), migration live round-trip.
- **Remaining cleanup:** EVL confirmation run (mandatory); AC-8/AC-9 Agent-Probe checks; then
  backlog notes for the two environment-blocked known-gaps at UPDATE PROCESS.
- **Best next state:** `Keep in active/testing`.

## Follow-up Stubs Created

None as separate files — the 4 known-gaps are already named in the plan's Known-Gaps section and
re-confirmed in `## Execution Notes`. Backlog NOTEs for the migration live round-trip and the
RTL/jsdom infra candidate are UPDATE-PROCESS work if the plan closes first.

## CONTEXT_PARTIAL Items

None.

## Forward Preview

- **Test Infra Found:** unit lane `-m unit` (no external deps); integration lane `-m integration`
  works against the reachable local Postgres; runner is `.venv/bin/python3.11 -m pytest`
  (`.venv/bin/pytest` shebang is broken).
- **Blast Radius Changes:** +2 backend service modules, +1 migration, +2 test files; 2 web page
  edits + 1 web type edit; 1 unrelated tripwire count update.
- **Commands to Stay Green:** `.venv/bin/python3.11 -m pytest tests/unit -m unit` and
  `.venv/bin/python3.11 -m pytest tests/integration/test_cadence_bot_flag.py -m integration`.
- **Dependency Changes:** none — no new package in `requirements.txt` or `apps/web/package.json`.
