---
name: report:outlier-traffic-damping-deferred-gates
description: "Open known-gaps left by the outlier/internal-traffic damping build — live migration round-trip, Hybrid integration lane, company-level totals"
date: 27-07-26
metadata:
  node_type: memory
  type: report
  feature: general-plans
  phase: "n/a"
---

# Outlier / internal-traffic damping — deferred gates

Source plan: `process/general-plans/active/outlier-traffic-damping_27-07-26/outlier-traffic-damping_PLAN_27-07-26.md`
Status at EXECUTE close (27-07-26): CODE DONE with 3 open gaps. None block CODE DONE
(the plan's Phase Completion Rules anticipate exactly this), all block `✅ VERIFIED`
and any production enable.

## 1. Live migration round-trip (Docker-gated) — OPEN

Migration `f3a7c9e21b48_add_internal_traffic_damping` is offline `--sql` validated clean in
BOTH directions. It has NOT been round-tripped against a real Postgres: the Docker daemon
was down in the EXECUTE environment (`docker ps` → connection refused).

Exact commands to close this gap:

```bash
docker compose -f infra/docker-compose.yml up -d postgres redis
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads   # re-confirm head first
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini downgrade -1
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head
```

Note the repo-wide gotcha: OFFLINE `--sql` runs need an explicit `<from>:<to>` range
(`upgrade b1e7f3c9d425:f3a7c9e21b48 --sql`); the `head` / `-1` shorthand only works for
LIVE runs. This migration joins the queue already pending production live-apply.

## 2. Hybrid integration lane — OPEN (same Docker cause)

`tests/integration/test_outlier_traffic_damping.py` was written (9 tests covering aggregate
exclusion, flag-but-store, resolution deprioritisation, reversibility on both surfaces,
override-wins-both-directions, per-site no-op) but never executed — same missing Docker daemon.

```bash
docker compose -f infra/docker-compose.yml up -d postgres redis
.venv/bin/python3.11 -m pytest tests/integration/test_outlier_traffic_damping.py -m integration -q
.venv/bin/python3.11 -m pytest tests/ -m integration -q -k "digest or aggregator or resolution"
```

Note: this gap is NOT vacuously green. The same reversibility and override-precedence
guarantees have real Fully-Automated unit coverage underneath
(`tests/unit/test_outlier_traffic_damping.py`, 28 tests, green) — the integration lane is an
additional DB-facing residual on top, not the sole gate.

## 3. Company-level total distortion — OPEN, out of scope by design

`apps/api/routers/companies.py` totals are accumulated by `_upsert_company`'s
`companies.total_pageviews + EXCLUDED.total_pageviews` increment-on-conflict merge in
`visitor_aggregator.py`, not by a filtered SELECT. Excluding outlier visitors there means
changing an accumulator, which is a structurally larger change than this plan's scope.
An outlier visitor's volume therefore still inflates their company's totals.

## 4. Threshold calibration before any production enable — OPEN (operator action)

`outlier_traffic_damping_outlier_threshold` (20.0) and
`outlier_traffic_damping_min_engagement_ratio` (0.1) are conservative PLACEHOLDERS, not
calibrated values. The documented rollout order in `apps/api/config.py` must be followed:
live-apply the migration → tune both thresholds against the site's real per-visitor
event-count distribution → only then flip `internal_damping_enabled` on for ONE site and
compare before/after. Never enable across all sites at once.
