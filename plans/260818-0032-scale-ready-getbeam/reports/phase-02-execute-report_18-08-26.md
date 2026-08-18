# Phase 2 EXECUTE report — disk and event_id survival on Free

Date: 18-08-26
Status: **DONE_WITH_CONCERNS**
Plan: `plans/260818-0032-scale-ready-getbeam/phase-02-disk-and-event-id-survival-on-free.md`

User override: cook continued despite Phase 1 operator leftovers (F9/soak/flag). Railway aggregation flag **not** flipped. Phase 3 **not** cooked. No commit, no push, no prod migration.

## Code

| Finding | Change |
|---|---|
| F4 | `schemas/events.py` `event_id` required (`str = Field(..., min_length=1, max_length=64)`). Missing/empty → Pydantic error → `_parse_event_batch` 400, 0 INSERT. Pixel unchanged. |
| F1 | ORM unique is `UniqueConstraint("site_id", "event_id", name="uq_events_site_event_id")`. Column still nullable. Ingest `on_conflict_do_nothing(index_elements=["site_id", "event_id"])`. Same id, different site → both rows. |
| F1 alembic | Revision `c3f6a9d1e8b2` revises live head `b7e3c9a4f215`: backfill NULL `event_id` via `gen_random_uuid()::text`, drop `uq_events_event_id`, create unique `(site_id, event_id)`. Offline-validated with explicit range (not `upgrade head --sql`). |
| F10 retention | `_retention_purge_job` logs every run including `deleted=0`. Existing `retention_purge` job got `next_run_time=+75s` (still 24 `add_job` calls). Offset stays below `aggregation_sweep` 90s. |
| F10 alembic | `assert_safe_alembic_dsn` in `apps/api/alembic_dsn_guard.py`; `env.py` calls it online + offline. `APP_ENV` in `{local,development,test,ci}` + non-localhost host → `SystemExit` mentioning **prod DSN blocked**. Localhost + development still allowed. Production env + prod DSN still allowed (operator apply). |
| Untouched | `aggregation_tasks.py`. `aggregation_incremental_enabled` default **False**. Ingest 429 ceilings. Pixel. `rpki_roas`. No NOT NULL on `events.event_id`. |

## Alembic

- Disk heads before write: `b7e3c9a4f215`. After write: `c3f6a9d1e8b2` revises `b7e3c9a4f215`.
- Offline SQL (`alembic upgrade b7e3c9a4f215:c3f6a9d1e8b2 --sql`): UPDATE NULL uuids → DROP INDEX `uq_events_event_id` → ADD CONSTRAINT `uq_events_site_event_id UNIQUE (site_id, event_id)`.
- **Local docker :5433 applied.** Current was `f4b9d2a71c68`; upgrade applied `b7e3c9a4f215` then `c3f6a9d1e8b2`. Now `c3f6a9d1e8b2 (head)`.
- Local NULL `event_id` before/after: **0 / 0** (324 events — not the prod 682). Constraint present: `uq_events_site_event_id`.
- **Prod `hylcleqxlkdblibpdhhm` NOT touched.** No `alembic upgrade`, no `apply_migration`, no backfill. Live `event_id IS NULL` remains **682**.

DSN used for local apply: `postgresql+asyncpg://…@localhost:5433/retarget_agent` with `APP_ENV=development`. Guard passed.

## Tests

Unit + ingest (required): **85 passed**
```
.venv\Scripts\python.exe -m pytest tests/unit/test_scheduler_job_config.py tests/unit/test_alembic_env_dsn_guard.py tests/unit/test_farbled_ingest_boundary.py tests/unit/test_agent_sig_ingest_boundary.py tests/unit/test_optout.py tests/integration/test_events_ingest.py -q
```

Other `/ingest` fixtures given `event_id`: **56 passed**
```
pytest tests/integration/test_agent_marker_handoff.py tests/integration/test_agent_sig_persistence.py tests/integration/test_promotion_sweep.py tests/integration/test_cadence_bot_flag.py tests/integration/test_pii_dual_write.py tests/integration/test_site_delete.py tests/integration/test_campaign_start_beam.py tests/integration/test_ingest_abuse_hardening.py -q
```

Scheduler AST gate still **24 add_job / 21 interval**. Retention has `next_run_time`. Gotcha covered: missing `event_id` tests send a real browser User-Agent (`is_bot("")` is True).

## Operator leftovers (not this cook)

1. **Phase 1:** F9 watermark bootstrap, soak, Railway `AGGREGATION_INCREMENTAL_ENABLED` still off. User override: continue anyway. Flag not flipped here.
2. **Prod backfill / unique:** 682 NULL `event_id` on `hylcleqxlkdblibpdhhm`; unique still global until this revision is applied by an operator with `APP_ENV=production`. Do **not** apply with `APP_ENV=local|development|test|ci` — guard will abort.
3. **`buildtolaunch` / `lnhymfqslmbdpklkpqwp`:** still ACTIVE_HEALTHY. Not paused from code (out of scope). Pause only if unused — operator decision.
4. **Disk:** local cook did not ingest `rpki_roas`. Prod Free ~424 MB unchanged by this cook.
5. **NOT NULL** on `events.event_id` deferred until 24h of zero null inserts after prod backfill.

## Files changed

- `apps/api/schemas/events.py`
- `apps/api/models/event.py`
- `apps/api/routers/events.py`
- `apps/api/jobs/scheduler.py`
- `apps/api/migrations/env.py`
- `apps/api/alembic_dsn_guard.py` (new)
- `apps/api/migrations/versions/c3f6a9d1e8b2_events_site_event_id_unique.py` (new)
- `tests/integration/test_events_ingest.py` (+ F1/F4 cases; uuid on fixtures)
- `tests/unit/test_scheduler_job_config.py`
- `tests/unit/test_alembic_env_dsn_guard.py` (new)
- `tests/unit/test_farbled_ingest_boundary.py`
- `tests/unit/test_agent_sig_ingest_boundary.py`
- `tests/unit/test_optout.py`
- ingest fixtures: `test_agent_marker_handoff.py`, `test_agent_sig_persistence.py`, `test_promotion_sweep.py`, `test_cadence_bot_flag.py`, `test_pii_dual_write.py`, `test_site_delete.py`, `test_campaign_start_beam.py`, `test_ingest_abuse_hardening.py`

No commit. No push.

## Next

- Operator: apply `c3f6a9d1e8b2` to prod with `APP_ENV=production` (after backup). Re-count `event_id IS NULL` live — do not hardcode 682.
- Operator: pause `buildtolaunch` if unused.
- Then Phase 3 (tenant ceilings / timeout / x20-x30 runbook) — not this session.
