# Phase 3 EXECUTE report — tenant ceilings, timeout, x20–x30 runbook

Date: 18-08-26
Status: **DONE_WITH_CONCERNS**
Plan: `plans/260818-0032-scale-ready-getbeam/phase-03-tenant-ceilings-timeout-and-x20-x30-runbook.md`

Implement Phase 3 only. Tester re-runs P1+P2+P3 after. No commit, no push, no Railway env, no prod migrate.

## Code

| Finding | Change |
|---|---|
| F3 | Site ceiling is **hard 429, 0 INSERT**. Velocity (P4) stays flag-but-store. Generic body (`Too many requests. Please retry later.`) — no site_id / limit leak. Warning log has `site_id` (not IP). |
| Ceiling default | `site_ingest_limit_per_minute=155` (7d p99=31 × 5, prod `hylcleqxlkdblibpdhhm`, 2026-08-18). Flag still `False`. |
| CF spoof | `CF-Connecting-IP` honoured only when `request.client.host` is in bundled CF CIDRs (`https://www.cloudflare.com/ips/`). Direct origin (8.8.8.8 / 1.2.3.4) ignored. Flag stays `True` (getbeam.fyi identity). |
| F5 | `get_db`: `SET LOCAL statement_timeout` to configured ms (no-op if 0). Sweep `_sweep_one_site` + retention purge sessions: `SET LOCAL statement_timeout = 0` before work, re-applied after each retention COMMIT. Dies at COMMIT so pool cannot leak 0 into a request. Engine default still 0. |
| Pool comments | Stale 15-client → live `max_connections=60`. `db_pool_size=3` / `db_max_overflow=2` unchanged. |
| Runbook | `docs/deployment-guide.md` §Scale-ready x20–x30: trigger table verbatim, operator flags after Phase 1 soak, migrate-then-deploy `c3f6a9d1e8b2`, Pro at 85% disk or before paid customer. |

Defaults still safe if Railway forgotten: `site_ingest_limit_enabled=False`, `db_statement_timeout_ms=0`.

## Tests

Phase 3 files touched: **45 passed**

```
.venv\Scripts\python.exe -m pytest tests/unit/test_ip_resolution.py tests/integration/test_db_statement_timeout.py tests/integration/test_ingest_abuse_hardening.py -q
```

- IP unit: spoof from 8.8.8.8 / 1.2.3.4 ignored; header trusted when peer is `172.64.0.1` (bundled `172.64.0.0/13`).
- Ceiling: 12 diverse-IP requests, limit=5 → some 204 then 429; row count == number of 204s; `assert 429 in statuses`. Per-IP 100/min test unchanged (still expects 429 on forged XFF).
- Timeout: existing AC11 still pass. New: request-like `SET LOCAL 500ms` kills `pg_sleep(2)`; sweep-like `SET LOCAL 0` on a 500ms engine survives `pg_sleep(2)`; COMMIT then next checkout is killed again (no leak). Analog of 30s vs 31s — no real 31s wait.

Full P1+P2+P3 regression is the tester's job.

Docker Desktop was down at first cook; started `infra-postgres-1` + `infra-redis-1` for the gate. Redis asyncio `__del__` noise after pytest teardown (event loop closed) — not a failure.

## Operator leftovers (not this cook)

1. **Phase 1:** soak / Railway `AGGREGATION_INCREMENTAL_ENABLED` still off.
2. **Phase 2:** prod Alembic `c3f6a9d1e8b2` not applied.
3. **Phase 3 flags:** do **not** set `SITE_INGEST_LIMIT_ENABLED`, `SITE_INGEST_LIMIT_PER_MINUTE=155`, or `DB_STATEMENT_TIMEOUT_MS=30000` until Phase 1 soak is green.
4. **Pro / pause buildtolaunch / pg_dump → R2:** operator, runbook only.

## Files changed

- `apps/api/config.py`
- `apps/api/models/database.py`
- `apps/api/services/rate_limiter.py`
- `apps/api/services/ip_resolution.py`
- `apps/api/routers/events.py`
- `apps/api/jobs/scheduler.py`
- `apps/api/services/retention.py`
- `tests/unit/test_ip_resolution.py`
- `tests/integration/test_ingest_abuse_hardening.py`
- `tests/integration/test_db_statement_timeout.py`
- `docs/deployment-guide.md`
- `plans/260818-0032-scale-ready-getbeam/phase-03-tenant-ceilings-timeout-and-x20-x30-runbook.md` (status + checkboxes)

No commit. No push.

## Next

- Tester: full P1+P2+P3 safety re-test.
- Operator after soak: Railway flags + prod migrate `c3f6a9d1e8b2` (Phase 2) before live ceiling/timeout.
