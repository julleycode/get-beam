# Phase 1 EXECUTE report — incremental aggregation soak (code only)

Date: 18-08-26
Status: DONE_WITH_CONCERNS
Concern: integration pytest did not run — localhost:5433 and :6379 not listening; Docker CLI not on PATH.

## Code

| Finding | Change |
|---|---|
| F2 | `events.py` ingest `created_at=datetime.utcnow()` — never `event.ts` |
| F6 | `_background_aggregate` stamps via `advance_watermark` after successful full run (`since=None`), clock from `SELECT now()` before the read. Aggregator still stamps only when `since is not None`. Sweep does not stamp. |
| F7 | `acquired is None` + flag ON → ingest skips agg (`aggregation_ingest_skipped_redis_degraded`). Flag OFF still fail-open. |
| F8 | `aggregation_debounce.RunLock` — token mutex, refresh while held, `release` in `finally` (leftover cooldown so flag-OFF debounce tests stay valid). Sweep shares `debounce_key`. |
| F9 | `scheduler.run_aggregation_watermark_bootstrap` — sequential full+stamp for sites with events and NULL watermark. Not registered in `start_scheduler` (job-count AST gate). Does not flip the flag. |
| Default | `config.py` `aggregation_incremental_enabled: bool = False` untouched. No Railway env change. |

## Tests

Unit (ran): 31 passed
```
.venv\Scripts\python.exe -m pytest tests/unit/test_aggregation_mutex.py tests/unit/test_aggregation_sweep_failopen.py tests/unit/test_aggregation_sweep_full_recompute.py tests/unit/test_aggregation_ingest_failopen.py tests/unit/test_aggregation_bootstrap.py tests/unit/test_scheduler_job_config.py -q
```

Integration (blocked): ConnectionRefusedError on :5433 / :6379
```
pytest tests/integration/test_visitor_aggregation_incremental.py tests/integration/test_aggregation_debounce.py tests/integration/test_aggregation_watermark_bootstrap.py
```

## Operator leftover

1. Start local Postgres:5433 + Redis:6379 and re-run the integration file list above.
2. Run `asyncio.run(run_aggregation_watermark_bootstrap())` on prod (or staging) until every site with events has `last_aggregated_at`.
3. Soak canary one prod site, then set Railway `AGGREGATION_INCREMENTAL_ENABLED=true`. Rollback = flag false.
