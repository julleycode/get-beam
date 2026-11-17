# Phase 1 tester report — incremental aggregation soak

Date: 18-08-26
Status: DONE_WITH_CONCERNS (gate FAIL)
TL;DR: Unit 31/31 green. Integration 26/27; F2 HTTP test bot-dropped for missing User-Agent. F6/F8/F9 empirically proven. F2/F7 unit-only. Flag default still False.

## Diff-aware mode

Analyzed blast-radius files: `events.py`, `aggregation_debounce.py`, `visitor_aggregator.py`, `scheduler.py` plus the listed unit/integration files.
Ran mapped gates only. Did not implement features. Did not commit. Did not start Phase 2.

## Config check

`apps/api/config.py:127` still `aggregation_incremental_enabled: bool = False`.

## Unit (31 passed / 0 failed, 3.45s)

| File | Pass | Fail |
|---|---|---|
| tests/unit/test_aggregation_mutex.py | 3 | 0 |
| tests/unit/test_aggregation_sweep_failopen.py | 5 | 0 |
| tests/unit/test_aggregation_sweep_full_recompute.py | 6 | 0 |
| tests/unit/test_aggregation_ingest_failopen.py | 3 | 0 |
| tests/unit/test_aggregation_bootstrap.py | 2 | 0 |
| tests/unit/test_scheduler_job_config.py | 12 | 0 |

## Integration (26 passed / 1 failed, 64.24s)

Infra: Postgres :5433 and Redis :6379 listening.

| File | Pass | Fail |
|---|---|---|
| tests/integration/test_visitor_aggregation_incremental.py | 10 | 0 |
| tests/integration/test_aggregation_debounce.py | 6 | 0 |
| tests/integration/test_aggregation_watermark_bootstrap.py | 3 | 1 |
| tests/integration/test_visitor_aggregation.py | 7 | 0 |

### Failure

`TestFutureEventTs::test_future_ts_does_not_inflate_pageviews_on_second_incremental`

```
sqlalchemy.exc.NoResultFound: No row was found when one was required
  tests/integration/test_aggregation_watermark_bootstrap.py:282
  select(Event).where(Event.event_id == "evt-future-ts-1")
```

HTTP ingest returned 204, then no Event row.

Diagnosis: POST headers are only `Content-Type`. Ingest bot-filters on the **request** User-Agent (`events.py` ~189-196). `is_bot("")` is True, so ingest 204s without insert. Body `user_agent` is unused by that filter. Sibling ingest tests always send `User-Agent: _BROWSER_UA`.

This is a test fixture gap, not an aggregator `created_at` regression. Product F2 (`created_at=datetime.utcnow()` at `events.py:460`) is present but the HTTP path never stored a row, so future-`ts` non-inflation is **not** empirically proven.

Likely one-line fix (orchestrator / debugger owns it): add `"User-Agent": _BROWSER_UA` to the ingest POST headers.

## Finding proof

| Finding | Empirically proven vs unit-mocked |
|---|---|
| F2 server `created_at`, never `event.ts` | Unit-mocked only (source string). HTTP behavioral proof FAIL. |
| F6 stamp only after full `_background_aggregate`; sweep does not stamp | Empirically proven (Postgres). |
| F7 Redis down + flag ON → skip ingest agg | Unit-mocked only. |
| F8 mutex held until `finally`, not 60s cooldown | Empirically proven (Redis). |
| F9 sequential fleet bootstrap | Empirically proven (Postgres). Job not in `start_scheduler` (intentional AST gate). |

## Not proven

- Prod soak canary
- Railway `AGGREGATION_INCREMENTAL_ENABLED=true`
- F2 future-`ts` no double-count via real ingest
- F7 ingest skip against real Redis-down
