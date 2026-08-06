---
name: note:site-id-lifecycle-migration-live-roundtrip
description: "Deferred Docker-gated gates for site-id-lifecycle: migration live round-trip + the whole integration lane (AC1/AC2/AC5/AC8/AC9)"
date: 04-08-26
feature: pixel
---

# Deferred Docker-gated gates — site-id-lifecycle (04-08-26)

Created per the plan's Validate Contract §VI / Execute-Agent Instruction E3. Matches the
`ingest-abuse-hardening-deferred-gates` / `cadence-bot-flag-deferred-gates` precedent.

**Blocker (re-confirmed at EXECUTE, 04-08-26):** no container runtime exists in the execute
environment — `docker`, `colima`, and `podman` are all `command not found`. The integration
lane's Postgres (localhost:5433) is therefore unreachable
(`OSError: [Errno 61] Connect call failed ('127.0.0.1', 5433)`).

## Open gate 1 — migration live round-trip

Migration: `apps/api/migrations/versions/e9d2a4c71f68_add_site_tombstones.py`
(chained off live head `c2f8a5d31e97`, re-confirmed fresh at EXECUTE per E1).

- **Done:** offline `--sql` validation, BOTH directions, exit 0:
  - `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade c2f8a5d31e97:head --sql`
  - `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini downgrade head:c2f8a5d31e97 --sql`
- **Still open:** live `upgrade head` → `downgrade -1` → `upgrade head` on a disposable
  Postgres container.
- **Note:** re-run `alembic heads` immediately before any live apply — `c2f8a5d31e97` is
  itself an UNCOMMITTED file from a concurrent session, and the head has drifted repeatedly.
- Railway auto-applies `alembic upgrade head` on boot, so merging to `main` IS the prod apply.

## Open gate 2 — whole integration lane (written but never executed)

New tests are on disk and syntax-checked, but have never run:

- `tests/integration/test_site_delete.py::TestSiteIdReclaim` —
  `test_delete_then_recreate_same_domain_reuses_site_id` (AC1),
  `test_recreate_outside_reclaim_window_gets_fresh_id` (AC1 window bound),
  `test_foreign_tombstone_not_reused` (AC5/AC8 cross-tenant isolation — the plan's
  highest-risk surface)
- `tests/integration/test_events_ingest.py::TestUnknownSiteObservability` —
  `test_unknown_site_logs_structured_event` (AC2),
  `test_counter_failure_does_not_break_the_403` (fail-open)
- Existing AC9 regression cases (`test_invalid_site_returns_403`,
  `test_deleted_site_403_expires_svid_cookie`) — unmodified but not re-run.

## To close

```bash
docker compose -f infra/docker-compose.yml up -d postgres redis
.venv/bin/python3.11 -m pytest tests/integration/test_site_delete.py tests/integration/test_events_ingest.py -q
.venv/bin/python3.11 -m pytest tests/ -m integration -q          # full-lane regression
# then, on a disposable Postgres:
alembic -c apps/api/alembic.ini upgrade head && \
  alembic -c apps/api/alembic.ini downgrade -1 && \
  alembic -c apps/api/alembic.ini upgrade head
```

Until both gates are green, the plan stays CONDITIONAL and must NOT be marked `✅ VERIFIED`.
