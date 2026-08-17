---
name: note:marketing-claims-gap-container-gates
description: "RESOLVED 17-08-26 — container gates for the marketing-claims-gap program all ran after Docker came back up; one source defect (icp_fit silent no-op) found flag-ON and fixed; all 3 phases VERIFIED. Kept for the corrected DB credentials + re-run command patterns"
date: 16-08-26
metadata:
  node_type: memory
  type: note
  feature: campaigns-outreach
---

# Marketing Claims Gap — Container-Blocked Gates (all 3 phases)

## ✅ RESOLVED 17-08-26

Docker daemon came back up (infra-postgres-1 `:5433` + infra-redis-1 `:6379`); **every gate
below ran.** Outcome (full evidence:
`completed/marketing-claims-gap_16-08-26/container-gate-closure-evl-iteration-002_REPORT_17-08-26.md`):

- Phase 1: booking/goal-preset integration 6/6 PASS; migration `e4b1d78c3a05` round-trip clean.
- Phase 2: first flag-ON run exposed a **real source defect** — the vacuity warning below was
  vindicated. `visitor_aggregator.py`'s icp_fit bulk write raised `InvalidRequestError`
  (SQLAlchemy 2 ORM bulk path), swallowed by the contract-mandated try/except → icp_fit NEVER
  persisted with `icp_fit_enabled=true`. Fixed via Core-table write (`update(Visitor.__table__)`).
  Post-fix: `test_icp_fit_persistence.py` 10/10; migration `f6a3c81d5e27` round-trip clean.
- Phase 3: benchmark/digest flag-ON+OFF pairing 7/7 both ways (non-vacuous); a never-executed
  test in `test_outcomes_report.py` fixed (missing function-local import), now 8/8; migration
  `a8c2f47e91b6` round-trip clean.
- Full chain live-round-tripped from an EMPTY DB, single head `a8c2f47e91b6`; unit 2926/2 zero
  drift; independent EVL confirmation (round 3) green; non-vacuity checks (a)–(e) all PASS.
- Exit condition met → all 3 phases + umbrella re-classified ✅ VERIFIED; task folder archived
  to `process/features/campaigns-outreach/completed/marketing-claims-gap_16-08-26/`.
- Residual (operator): prod flags `icp_fit_enabled` / `campaign_benchmark_enabled` remain OFF.

**Kept (still useful):** the corrected DB credentials in §Setup below
(`retarget` / `retarget_dev` / db `retarget_agent`; pytest lane uses `retarget_agent_test`)
and the pinned-alembic re-run patterns.

---

**Original note (historical) follows.**

**Priority:** ~~HIGH~~ (resolved) — these gates blocked VERIFIED classification and archival of the
`marketing-claims-gap_16-08-26` program. **No flag-ON positive case had executed as of 16-08-26.**

**Problem:** The Docker daemon was down for the whole 16-08-26 session
(`~/.docker/run/docker.sock` missing — a NEW failure mode distinct from the documented
"CLI off PATH" gotcha; the `lsof` check was run and genuinely showed no listeners). Postgres
`:5433` and Redis `:6379` were absent. Native `:5432` exists but is **FORBIDDEN** for
integration runs — conftest `drop_all` destroys the dev DB
(memory: `getbeam-local-dev-db-rebuild-recipe`).

**Vacuity precedent:** per ip-org contract errata G8/G10, a gate that passes with the feature
flag OFF proves nothing. `icp_fit_enabled` and `campaign_benchmark_enabled` shipped default
OFF; Phase 1's `booking_url` is data (not a flag) but its integration legs are equally unrun.
Do NOT mark any of these ACs met on flag-OFF evidence.

## Setup (once Docker is available)

```bash
open -a Docker   # or start Docker Desktop; wait for the daemon
lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'   # must show BOTH before proceeding
docker compose -f infra/docker-compose.yml up -d     # CLI at /Applications/Docker.app/Contents/Resources/bin/docker if off PATH
export TEST_DATABASE_URL="postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test"
# Credentials come from infra/docker-compose.yml: user `retarget` / password `retarget_dev` /
# db `retarget_agent`. The pytest lane uses the separate `retarget_agent_test` database.
# (Corrected post-EVL 17-08-26 — the earlier postgres/postgres/postgres values were wrong
# and would fail authentication.)
```

Always pin `DATABASE_URL` to `localhost:5433` in the command environment for every
alembic/DB invocation — repo `.env` points at Supabase PROD and `migrations/env.py` has no
local-host guard.

## Phase 1 — Demo booking

| Gate | Re-run command |
|---|---|
| AC-1/5/6 integration (booking-URL CRUD, draft render, goal-preset endpoint) | `.venv/bin/python3.11 -m pytest tests/integration -q -k "booking or demo_booked"` |
| AC-8 migration round-trip `e4b1d78c3a05` | `DATABASE_URL=postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head` then `... downgrade e4b1d78c3a05^` then `... upgrade head` |

## Phase 2 — ICP-fit scoring (flag-ON precondition: `icp_fit_enabled=true` in the test env)

| Gate | Re-run command |
|---|---|
| AC-6/7/8/9/15/16 flag-ON persistence + detail surface | `.venv/bin/python3.11 -m pytest tests/integration/test_icp_fit_persistence.py -q` |
| AC-10 migration round-trip `f6a3c81d5e27` | same pinned-alembic pattern as Phase 1, targeting `f6a3c81d5e27` |

Also closes the named known-gap: since-is-None gating + raise containment currently verified
by source read only — the pinning tests are in this blocked file.

## Phase 3 — Learning loop + benchmarks (flag-ON precondition: `campaign_benchmark_enabled=true`)

| Gate | Re-run command |
|---|---|
| AC-4/5/6/7 flag-ON+OFF pairing (benchmark job k-floor, digest line, prompt injection) | `.venv/bin/python3.11 -m pytest tests/integration -q -k "benchmark or outcome_digest"` |
| AC-11 migration round-trip `a8c2f47e91b6` (current head) | same pinned-alembic pattern, targeting `a8c2f47e91b6` |

## Exit condition

All rows above green with flag-ON preconditions named → re-classify the three phase plans and
umbrella toward ✅ VERIFIED, then archive the task folder
`process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/` to `completed/`.
Full context: `marketing-claims-gap_REPORT_16-08-26.md` in the task folder.
