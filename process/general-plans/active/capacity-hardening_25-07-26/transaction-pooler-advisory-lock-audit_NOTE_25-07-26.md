---
name: note:transaction-pooler-advisory-lock-audit
description: "Blocks the Supabase 6543 transaction-pooler port change — retention.py holds advisory locks across statements"
date: 25-07-26
---

# Transaction-pooler (6543) advisory-lock audit — OPEN

**TL;DR** — Phase 4b ships port-aware pool code that is safe under either pooler,
but the port change itself must NOT be recommended until this audit closes.
`apps/api/services/retention.py` holds a Postgres advisory lock **across
statements**, which the Supabase transaction pooler does not support.

## Why this blocks the port change

The session pooler (port 5432) gives each client a dedicated backend for the life
of the connection, so `pg_try_advisory_lock` taken in one statement is still held
in the next. The transaction pooler (6543) multiplexes backends **per
transaction** — session-scoped state (advisory locks held across statements,
`SET`-based session settings) is not guaranteed to survive between statements.

## The affected code

| Site | What it does |
|---|---|
| `apps/api/services/retention.py:64` | `SELECT pg_try_advisory_lock(hashtext(:key))` on an outer session |
| `apps/api/services/retention.py:76` | `SELECT pg_advisory_unlock(hashtext(:key))` on that same outer session |
| `apps/api/services/retention.py:116` / `:122` | outer lock session + inner delete session — the lock is held across the entire purge, spanning many statements |
| `apps/api/services/retention.py:177` / `:183` | same shape for the `agent_fetch_events` purge (Handoff H1), separate lock key |

Under 6543 the outer lock could be silently released (or taken on a different
backend than the unlock), which would either (a) let two replicas purge
concurrently — the single-flight guarantee this lock exists to provide — or
(b) leak a lock that is never unlocked.

Note also the **2-connection reservation**: each purge holds an outer lock
session plus an inner delete session simultaneously. That reservation is
documented in the `config.py` 4b pool math and applies under either pooler.

## What closing this audit requires

1. A real Supabase 6543 endpoint (cannot be simulated — local Postgres has no
   pooler in front of it). Cost class: `needs-live-provider`.
2. Verify whether the outer advisory lock survives across the inner delete
   session's statements when routed through 6543.
3. If it does not: replace the advisory lock with a transaction-scoped
   equivalent (`pg_advisory_xact_lock` inside a single transaction) or an
   application-level single-flight (the Redis debounce pattern already used by
   `services/aggregation_debounce.py`), before any port change.

## Status

- **OPEN.** Phase 4b's code is port-aware and safe under either pooler; the
  defaults are identical in both modes, so nothing changes until an operator acts.
- `DATABASE_URL`'s current port is **unanswered** (Phase 0 item P0.3, operator-only).
- Until this closes, do **not** recommend moving `DATABASE_URL` to port 6543.
