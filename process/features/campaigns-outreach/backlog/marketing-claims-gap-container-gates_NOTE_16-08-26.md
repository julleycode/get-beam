---
name: note:marketing-claims-gap-container-gates
description: "Consolidated container-blocked gate list for the 3-phase marketing-claims-gap program — every Hybrid/integration/migration gate unrun (Docker daemon down all session); exact re-run commands; flag-OFF-only evidence is vacuous per ip-org G8/G10"
date: 16-08-26
metadata:
  node_type: memory
  type: note
  feature: campaigns-outreach
---

# Marketing Claims Gap — Container-Blocked Gates (all 3 phases)

**Priority:** HIGH — these gates block VERIFIED classification and archival of the entire
`marketing-claims-gap_16-08-26` program. **No flag-ON positive case has ever executed.**

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
export TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5433/postgres"
```

Always pin `DATABASE_URL` to `localhost:5433` in the command environment for every
alembic/DB invocation — repo `.env` points at Supabase PROD and `migrations/env.py` has no
local-host guard.

## Phase 1 — Demo booking

| Gate | Re-run command |
|---|---|
| AC-1/5/6 integration (booking-URL CRUD, draft render, goal-preset endpoint) | `.venv/bin/python3.11 -m pytest tests/integration -q -k "booking or demo_booked"` |
| AC-8 migration round-trip `e4b1d78c3a05` | `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/postgres .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head` then `... downgrade e4b1d78c3a05^` then `... upgrade head` |

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
