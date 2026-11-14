---
name: report:coop-disposable-e2e-lane-runbook
description: "How to run the disposable-container coop e2e lane (helper -> export -> pytest), sequenced by default"
date: 17-08-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
  phase: coop-disposable-e2e
---

# Disposable coop e2e lane — invocation runbook

**TL;DR:** `./scripts/e2e-disposable.sh <lane> -- .venv/bin/python3.11 -m pytest tests/e2e_disposable/<file> -p no:randomly -q`. One container pair per file, sequenced. Never run the whole directory in one container.

## Why it is not a normal pytest lane

`pyproject.toml` carries `addopts = "--ignore=tests/e2e_disposable"`, so a bare
`pytest` never collects **or imports** this directory. That exclusion is
**path-based on purpose**: `-m 'not disposable'` deselects only *after*
collection, so module-level side effects would still fire. The `disposable`
marker is registered for *selection* and applied as `pytestmark` in every lane
module as defence in depth.

## Invocation

```bash
# one file, own throwaway containers, torn down unconditionally
./scripts/e2e-disposable.sh mig  -- .venv/bin/python3.11 -m pytest tests/e2e_disposable/test_migration_truth.py -p no:randomly -q

# hold a stack for interactive work (Ctrl-C tears it down)
./scripts/e2e-disposable.sh dev
# then, in another shell, paste the two printed lines:
export DATABASE_URL=... REDIS_URL=...
.venv/bin/python3.11 -m pytest tests/e2e_disposable/test_pool_topology.py -q
```

`pytest` must be invoked as `.venv/bin/python3.11 -m pytest` — the `.venv/bin/pytest`
shebang still points at a pre-move path and fails.

## Sequencing rules (do not batch these together)

1. **`test_migration_truth.py` gets its OWN container.** `apps/api/main.py`'s
   lifespan runs `Base.metadata.create_all` on the global engine at every boot,
   which silently re-creates any table a migration failed to create. Sharing a
   container with `test_lifespan_scheduler.py` would let a lifespan boot *repair*
   the divergence before the migration-truth assertions run.
2. **Max 2 concurrent container pairs** (~1.0 GB with pytest RSS ~350 MB each).
   The helper refuses to start a third. Default is one at a time.
3. `test_scale_sweep.py` seeds 10,000 rows and takes ~25 s — run it alone.

## Safety

- Every alembic/DB command in the lane pins `DATABASE_URL` inline. The repo
  `.env` points at **Supabase PRODUCTION** and `apps/api/migrations/env.py` has
  no local-host guard.
- The shell helper refuses a non-localhost `--dsn` without `--allow-remote`;
  an unparseable host also refuses, and a refusing helper prints nothing on stdout.
- The lane's own session-scoped autouse guard (`_dsn_guard`) hard-fails unless
  the host is localhost **and** the port is not 5432 / 5433 / 6543 — so a direct
  `pytest tests/e2e_disposable/` can never `DROP SCHEMA` the shared dev DB.
- Teardown is unconditional (`trap ... EXIT INT TERM`), including on SIGINT.

## Gate → file map

| Gates | File |
|---|---|
| DE-2, DE-11, DE-12 | `test_migration_truth.py` |
| DE-3, DE-4, DE-5, DE-5b, DE-13, DE-14, DE-15 | `test_lifespan_scheduler.py` |
| DE-6, DE-7, DE-16a, DE-16b | `test_pool_topology.py` |
| DE-9a, DE-9b, DE-10, DE-17 | `test_two_process_replica.py` (+ `_replica_child.py`) |
| DE-18 | `test_scale_sweep.py` |
| DE-8 | `test_scenario_43.py` |
| DE-19, DE-20, DE-21 | `test_helper_guard.py` |
| DE-1 | not a lane test — see the phase report (numstat + collect-only + unit/integration) |
