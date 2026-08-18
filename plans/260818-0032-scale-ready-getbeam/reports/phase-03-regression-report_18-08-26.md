# Phase 3 regression re-test (P1+P2+P3)

**TL;DR:** PASS — Phase 1 46/46, Phase 2 58/58, Phase 3 49/49. Total 153 passed, 0 failed. Debounce fixture `_FakeSession.execute` confirmed. Safety flags still default OFF.

[MODE: TEST] Confirm-only after debounce fixture fix. No production code changes. Postgres :5433 + Redis :6379 healthy. PYTHONPATH pin. Independently re-ran every listed pytest command.

## Lane table

| lane | passed | failed | duration |
|---|---|---|---|
| Phase 1 aggregation | 46 | 0 | 123.73s |
| Phase 2 event_id / alembic / ingest | 58 | 0 | 113.74s |
| Phase 3 ceiling / CF / timeout | 49 | 0 | 70.75s |
| **Total** | **153** | **0** | **~308s** |

Infra: `infra-postgres-1` healthy `0.0.0.0:5433`, `infra-redis-1` healthy `0.0.0.0:6379`.

## Failures

None.

Prior run (same session, before fixture fix): 4 debounce failures in `tests/integration/test_aggregation_debounce.py` (`assert 0 == 1` because `_FakeSession` lacked `execute` after Phase 3 F5 `apply_long_job_statement_timeout`). This confirm-only re-run is 100% green.

Fixture now:

```60:72:tests/integration/test_aggregation_debounce.py
    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def execute(self, *_a, **_k):
            class _Result:
                def scalar(self):
                    return None

            return _Result()
```

## Safety invariant checklist

| invariant | result | evidence |
|---|---|---|
| `aggregation_incremental_enabled` default False | PASS | `apps/api/config.py:125` `bool = False` |
| `site_ingest_limit_enabled` default False | PASS | `apps/api/config.py:290` `bool = False` |
| `db_statement_timeout_ms` default 0 | PASS | `apps/api/config.py:63` `int = 0` |
| `event_id` required in schemas | PASS | `apps/api/schemas/events.py:25` `Field(..., min_length=1, max_length=64)` |
| UniqueConstraint `site_id`+`event_id` | PASS | `apps/api/models/event.py:81` `uq_events_site_event_id` |
| `alembic current` localhost only, no supabase host | PASS | host=`localhost` port=`5433` `contains_supabase=False`; stdout `c3f6a9d1e8b2 (head)`. P3 added no revision. |

Pinned DSN for alembic: `postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent`. `APP_ENV=development`. Output did not print a supabase host.

## Notes

- Redis `Event loop is closed` at Phase 2/3 teardown: known noise (`process/context/tests/all-tests.md`), not a fail.
- Phase 2 also printed 1 warning: `RuntimeWarning: coroutine 'Connection._cancel' was never awaited` — teardown noise, exit 0.
- Phase 1 aggregation debounce mutex is now re-verified after the F5 timeout hook.
- Risk gate file still `mustStopBeforeFinalize=true` for human/ops (public ingest 429, CF IP trust, timeout flags). That is not a pytest blocker.

Harness: `plans/260818-0032-scale-ready-getbeam/reports/harness/phase-03/verification.json`

**Status: DONE** — 0 failures across all three lanes.
