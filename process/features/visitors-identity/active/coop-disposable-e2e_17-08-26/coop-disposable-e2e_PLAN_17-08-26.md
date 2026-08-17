---
name: plan:coop-disposable-e2e
description: "Real disposable-container e2e lane proving identity-coop Phase 1 + Phase 2a in production shape — migration truth, lifespan/scheduler, pooled topology, two-process replica, scale, and scenario-43"
date: 17-08-26
feature: visitors-identity
---

# Coop Disposable-Container E2E Lane — PLAN (17-08-26)

**TL;DR:** Build 8 pieces of test infrastructure so that the identity-coop expiry/accrual path is
exercised the way production actually runs it — schema from `alembic`, app booted through its ASGI
**lifespan** (so the APScheduler job really fires), a prod-shaped connection pool, and two OS
processes racing the advisory lock — all against throwaway Postgres/Redis containers on
non-default ports. Today none of that is true, and **8 defect classes can ship fully green.**

Complexity: **COMPLEX** (single plan, one phase — not a phase program). Test-infrastructure only;
zero production source behavior changes.

**Date**: 17-08-26
**Status**: PLANNED (not validated, not executed)
**Complexity**: COMPLEX
**Feature**: visitors-identity

## Overview

This plan builds a real, isolated, disposable-container end-to-end test lane that proves the
identity-coop **Phase 1 + Phase 2a** behavior in **production shape**. Today the shared test lane
builds its schema from ORM metadata rather than migrations, and never runs the ASGI lifespan, so
the scheduler that drives coop expiry in production is executed by no test at any tier. This plan
adds 8 pieces of test infrastructure, each with falsifiable gates and mandatory mutation probes,
to close 8 identified defect classes. It touches only `tests/`, `scripts/`, and one line of
`requirements.txt` — no `apps/` source file is modified.

Testing context: `process/context/tests/all-tests.md` is the routing entry point for this work;
follow its downstream chain (container/e2e docs, debugging gotchas) before writing any lane test.
Post-phase testing is defined in the Verification Evidence table below (DE-1 through DE-21) and in
Phase Completion Rules.

---

---

## Why This Exists

The user found breakage **by hand** in the shared test lane after earlier e2e work "missed a lot."
A read-only research pass on 17-08-26 established that **8 defect classes can ship fully green
today.** Two root causes dominate:

1. **`tests/conftest.py:133` builds the schema with `Base.metadata.create_all`, never `alembic`.**
   The tests therefore validate the *models*, and the migrations are validated by nothing. A
   model-present / migration-absent divergence (e.g. a unique index declared on the ORM class but
   never emitted by a migration) is **undetectable in that direction** — every test passes, and
   production gets a table without the constraint.
2. **`httpx.ASGITransport` does not run the ASGI lifespan.** `apps/api/main.py:62,93-110,114`
   calls `start_scheduler()` / `stop_scheduler()` from the lifespan handler. Because no test ever
   triggers lifespan, `start_scheduler()` and `_coop_expiry_sweep_job` are executed by **NO test
   at any tier.** The boot gate (`scheduler.py:743 if settings.identity_coop_enabled:`), the
   `add_job` registration at `:744-752`, and the wrapper's runtime re-check at `:314-317` are all
   unproven code.

This lane closes both, plus the multi-connection, multi-process, and scale blind spots that follow
from them.

### Verified ground truth (cited, not re-derived)

| Fact | Anchor |
|---|---|
| Prod boot = `alembic upgrade head && uvicorn`; no `--workers` ⇒ 1 worker/container, N replicas ⇒ **N schedulers** | `Dockerfile` CMD; `railway.json` builder `DOCKERFILE`, healthcheck `/health` |
| Scheduler start/stop live in lifespan | `apps/api/main.py:62,93-110,114` |
| `AsyncIOScheduler()`; coop job gated at boot | `apps/api/jobs/scheduler.py:29`; `:743` `if settings.identity_coop_enabled:` wrapping `add_job(_coop_expiry_sweep_job, ...)` `:744-752` |
| Wrapper re-checks the flag at runtime (do-not-delete comment) | `scheduler.py:310-312` (comment), `:314-317` (re-check) |
| Wrapper opens the **global** `async_session` | `scheduler.py:16`; `apps/api/models/database.py:78` |
| Test pool `pool_size=5`; prod pool `3 + 2` overflow | `tests/conftest.py:95`; `models/database.py:70-71`; `config.py:90-91`. SQLAlchemy QueuePool is FIFO (`use_lifo=False`) |
| conftest DB name hardcoded `retarget_agent_test`; per-test `drop_all` → `DROP TYPE` → `create_all` | `tests/conftest.py:24-27`, `:127-143` |
| Global `async_session` patched in only **three** modules — `scheduler.py` is **not** among them | `tests/conftest.py:199-212` (`demo`, `events`, `visitors_helpers`) |
| Index parity pairs (model ↔ migration) | `uq_coop_accrued_site_email`: `models/identity_coop.py:85-91` ↔ `e7b3d5f19c46`; `uq_coop_ledger_expire_per_lot`: `:140-145` ↔ `b7e4d21a9c58:41-47` |
| Sweep selects **every** lapsed lot globally — no site filter, no LIMIT, no batching; per-lot SELECT + INSERT + `commit()` | `services/identity_coop.py:563-576`, `:588-602` |
| Orphan guard is a `WHERE EXISTS` | `services/identity_coop.py:522-527` |
| Live alembic head `b7e4d21a9c58` (pinned-DSN derivation, `results.tsv` row 30) — **re-derive live before any apply; never trust a written head** | identity-coop `results.tsv` row 30 |
| Repo `.env` `DATABASE_URL` → **Supabase PRODUCTION**; `apps/api/migrations/env.py` has **no** local-host guard | `all-context.md` §Open Questions; memory `getbeam-env-points-to-supabase-prod` |
| `apps/web/.env.local` points the browser at the **PROD API** | memory `getbeam-env-local-points-web-at-prod-api` |
| Alembic offline `--sql` needs an explicit `<from>:<to>` range | `b7d3e9f1a4c2_add_ad_connections.py` calls `sa.inspect(bind)` |
| Docker CLI is at `/Applications/Docker.app/Contents/Resources/bin/docker`; detect via `lsof -nP -iTCP -sTCP:LISTEN`, **never** `which docker` | memory `docker-runs-but-cli-not-on-path` |
| No credentials needed. Clerk already bypassed in e2e by design; coop has no dashboard surface until Phase 3 | `playwright.config.ts:50` blanks keys; `e2e/auth.setup.ts` uses legacy JWT `demo@getbeam.fyi` |
| `email_validator.validate_email` does a **live MX lookup** on the accrual path, neutralised only by the `no_mx` fixture | `tests/integration/test_identity_coop_contribution.py:582-590` |
| Resource ceiling: 2 parallel postgres+redis pairs (~1.0 GB incl. pytest RSS ~350 MB each). Repo default is serialization (`playwright.config.ts` `workers: 1`; Phase 2a mandates the integration lane SERIALIZED) | measured 17-08-26 |

### The 8 defect classes this lane closes

| # | Defect class | Why it ships green today | Closed by item |
|---|---|---|---|
| 1 | Model declares an index/constraint the migration never creates | conftest uses `create_all`, so the model IS the schema under test | 2 |
| 2 | Migration is unrunnable / wrong on a **non-empty** DB | no test ever runs a migration at all | 2, 3 |
| 3 | Scheduler job never registers (boot gate wrong, wrong interval/jitter) | lifespan never runs in tests | 4 |
| 4 | Sweep wrapper broken end-to-end (global session, runtime flag re-check) | `scheduler.py`'s `async_session` is not patched and is never called | 4 |
| 5 | Advisory lock never actually acquired / released across connections | single-pool, single-session tests can't observe cross-connection lock state | 5 |
| 6 | Sweep does not scale (unbounded global SELECT, per-lot commit, long connection hold) | no scale fixture exists | 7 |
| 7 | Boundary/crash/orphan semantics undefined or wrong | scenarios never written | 4, 5, 8 |
| 8 | Multi-replica duplicate work (N containers ⇒ N schedulers) | impossible in one process | 6 |
| **9** | **Production itself masks table-level migration divergence** — the `Dockerfile` runs `alembic upgrade head` and then `apps/api/main.py`'s lifespan runs `Base.metadata.create_all` on the global engine, silently re-creating any table a migration failed to create | nothing looks at it; the app boots green | recorded as a **finding** (C-4b) — out of scope to fix here |

---

## Goals

1. Prove Phase 1 + Phase 2a coop behavior **in production shape**: alembic-built schema, real
   lifespan, prod-parity pool, ≥2 connections, ≥2 processes.
2. Every new gate is **falsifiable** — it must go RED against a stated broken implementation.
3. Zero behavior change to the default test lane and zero production source changes.

## Non-Goals

- No Phase 3 (contributor dashboard) surface. No UI, no Playwright.
- No production DDL, no deployed flag-ON proof (see Known Gaps K-3).
- No change to `identity_coop.py` service logic. If a gate goes RED against current source, that
  is a **finding to report**, not a licence to edit the service in this plan.

---

## Decisions

**D-E2E-1 (scenario 43 — previously undefined; user decision 17-08-26).**
The sweep **DOES** expire lots belonging to a site whose `contribution_enabled` has since been
turned OFF.
*Rationale (record verbatim in the gate):* expiry is a property of **the lot** (90-day life), not
of the site's current opt-in status. Opting out stops **new accrual only**. Freezing existing
credits on opt-out would create an *opt-out-to-preserve-credits-forever* exploit.
Gate: **DE-8** below.

**D-E2E-2.** The migration-truth lane is **opt-in**, not a default flip. The default lane
(`create_all`) must remain **byte-identical in behavior** — the concurrent EVL work and every
existing suite depend on it.

**D-E2E-3.** Every lane gets its **own container** on a **unique non-default host port**, never
`5433`/`6379`. This is the single mitigation that simultaneously solves DB-name collision, stray
Redis poisoning, and PG ENUM teardown.

**D-E2E-4.** Lanes are **sequenced by default**. Parallelism (max 2 container pairs) buys
wall-clock only and is opt-in via an explicit flag.

**D-E2E-5.** Non-vacuity is enforced by **mutation probes**, not by assertion review. Mandatory
for items 2, 4, 5.

---

## Touchpoints

| Path | Read / Change | Note |
|---|---|---|
| `tests/conftest.py` | **read only — ZERO lines changed** | Supplement F-4: the alembic build moved entirely into the lane conftest. The root conftest is not touched at all. |
| `pyproject.toml` | change (2 lines) | register the `disposable` marker **and** add a real exclusion — a marker alone excludes nothing (F-5) |
| `scripts/e2e-disposable.sh` | new | repo has **never** had one |
| `tests/e2e_disposable/` | new dir | lane-scoped conftest (owns the alembic build) + specs |
| `requirements.txt` | change (1 line) | `asgi-lifespan` — test-only dep; rationale recorded under Known Gaps (C-8) |
| `apps/api/routers/sites.py` | **read only** | `delete_site` at `:341-345` explicitly deletes `identity_contribution_events` **and** `identity_credit_ledger` ("H1: close the site_id-reuse gap"). Governs DE-16/DE-17. |
| `apps/api/jobs/scheduler.py` | **read only** | boot gate, wrapper, `async_session` import |
| `apps/api/services/identity_coop.py` | **read only** | sweep, orphan guard, accrual |
| `apps/api/models/identity_coop.py` | **read only** | index declarations |
| `apps/api/migrations/versions/e7b3d5f19c46*.py`, `b7e4d21a9c58*.py` | **read only** (mutation probes revert) | index parity |
| `apps/api/models/database.py`, `apps/api/config.py` | **read only** | pool sizing |
| this task folder | new artifacts | plan, registry, reports |

---

## Public Contracts

This plan exposes **no new runtime contract**. It creates one **developer-facing** contract:

| Contract | Shape | Stability |
|---|---|---|
| `scripts/e2e-disposable.sh <lane-name>` | prints `DATABASE_URL=...` and `REDIS_URL=...` on stdout, exits non-zero and prints nothing on refusal; unconditional teardown on any exit | new; treat as stable once merged |
| `tests/e2e_disposable/conftest.py` session-scoped `disposable_engine` fixture | owns `DROP TABLE IF EXISTS alembic_version` → `alembic upgrade head` → engine creation; lane-local, never imported by the root conftest | new (supersedes the withdrawn `E2E_DISPOSABLE_ALEMBIC` root-conftest branch, F-4) |
| `pyproject.toml` `addopts = "--ignore=tests/e2e_disposable"` (+ registered `disposable` marker, + module-level `pytestmark` in every lane spec) | the default `pytest` invocation **does not collect or import** `tests/e2e_disposable/`, because the exclusion is **path-based**. (E-4: a `-m 'not disposable'` marker filter would NOT achieve this — `-m` deselects *after* collection, so every lane module is still imported; the marker is retained for selection and as defence in depth only.) | new; **changes the default invocation for every suite in the repo** — DE-1 must run AFTER this lands, not before |

**Explicit non-contract:** nothing in `apps/api/**` changes. `identity_coop_enabled` and every
other repo-default-OFF flag stays OFF in `.env`; the lane sets flags per-process/per-test only.

---

## Blast Radius

Risk class: **test-infrastructure + shared-fixture** (touching `tests/conftest.py` is the only
elevated-risk item — it is read by every suite in the repo). No auth/billing/schema/API/deploy
surface.

| File | Diff budget | Constraint |
|---|---|---|
| `tests/conftest.py` | **0 added, 0 removed, 0 modified** | Not touched. The alembic build lives in the lane conftest (F-4). Enforced mechanically by DE-1 (`git diff --numstat` = 0/0). |
| `pyproject.toml` | **≤ 4 lines** (marker registration + `addopts` + the `asgi-lifespan` entry in the existing `test` extra, C-17) | Real exclusion, not marker-only (F-5). Changes the default invocation repo-wide. |
| `scripts/e2e-disposable.sh` | new, ≤ 150 lines | must refuse non-localhost DSN |
| `tests/e2e_disposable/conftest.py` | new, ≤ 250 lines | lane-scoped; must not import from the root conftest's engine fixture. Owns the session-scoped alembic build AND the in-process DSN guard (C-10). |
| `tests/e2e_disposable/test_migration_truth.py` | new, ≤ 150 lines | items 2, 3 |
| `tests/e2e_disposable/test_lifespan_scheduler.py` | new, ≤ 250 lines | item 4 + scenarios |
| `tests/e2e_disposable/test_pool_topology.py` | new, ≤ 200 lines | item 5 |
| `tests/e2e_disposable/test_two_process_replica.py` | new, ≤ 250 lines | item 6 (spawns children) |
| `tests/e2e_disposable/_replica_child.py` | new, ≤ 100 lines | child entrypoint for item 6 |
| `tests/e2e_disposable/test_scale_sweep.py` | new, ≤ 150 lines | item 7 |
| `tests/e2e_disposable/test_scenario_43.py` | new, ≤ 100 lines | item 8 |
| `tests/e2e_disposable/test_helper_guard.py` | new, ≤ 120 lines | DE-19 + DE-20 — the helper's own gates had no home file (C-7) |
| `requirements.txt` | +1 line | `asgi-lifespan` |
| task folder artifacts | n/a | plan, `results.tsv`, reports |

**Packages touched:** `tests/`, `scripts/`, `requirements.txt`, `pyproject.toml`. **Zero** `apps/` files modified. **Zero** lines changed in `tests/conftest.py`.

---

## Isolation Hazards and Mitigations

| Hazard | Mechanism | Mitigation (must be implemented, not assumed) |
|---|---|---|
| Shared `retarget_agent_test` DB collides between two pytest processes | DB name hardcoded at `conftest.py:24-27`; two runs `drop_all` each other mid-test | Per-lane **container** with its own host port; `DATABASE_URL` exported **before pytest starts** |
| Cross-event-loop flakiness on the global `async_session` engine — victim shifts with collection order | `models/database.py:78` creates one engine at import; a second loop borrowing its connections detonates elsewhere | Dedicated **process** per lane. For item 4 the global engine is unavoidable by design (the wrapper uses it) — therefore `DATABASE_URL` must be exported **before import**, never patched after |
| Stray Redis on 6379 poisons the unit lane (memory: `unit-tests-assume-no-local-redis`) | conftest defaults `REDIS_URL` to `:6379/15` | Lane gets its **own Redis on a non-6379 port** and exports `REDIS_URL`; no `docker stop infra-redis-1` dance needed |
| PG native ENUM teardown residue | `conftest.py:127-143` hand-drops enum types | Free — the container is thrown away; nothing to clean |
| Pool FIFO/size divergence hides connection-hold and lock bugs | test `pool_size=5` vs prod `3+2`, `use_lifo=False` | Pin the lane engine to `pool_size=3, max_overflow=2` |
| Live MX lookup on the accrual path makes gates network-dependent/flaky | `email_validator.validate_email` | Reuse the `no_mx` fixture pattern from `test_identity_coop_contribution.py:582-590` in the lane conftest |
| A lifespan boot **repairs** table-level migration divergence before the migration-truth assertions run | `apps/api/main.py`'s lifespan calls `Base.metadata.create_all` on the global engine at every boot (C-4) | The migration-truth lane runs against its **own** container/DB with **no lifespan boot**. Never share one container between the migration-truth lane and the lifespan lane |
| A direct `pytest tests/e2e_disposable/` reaches the shared dev DB (`:5433`) or PROD and `drop_all`s it | the shell helper's refusal protects only the helper path; `conftest.py:24` `setdefault` silently falls through | Session-scoped autouse in-process guard in the lane conftest: localhost host **and** port ∉ {5432, 5433, 6543}, else hard-fail (C-10, gate DE-21) |
| An unpinned alembic/DB command hits **Supabase PRODUCTION** | repo `.env` `DATABASE_URL`; `migrations/env.py` has no guard | Every command in this lane pins `DATABASE_URL` inline; the helper script **refuses** a non-localhost DSN (precedent: `scripts/refresh_ip_org.py --allow-remote`) |

---

## Implementation Checklist

### Section A — Disposable stack helper (item 1)

1. Create `scripts/e2e-disposable.sh`. Resolve the docker binary by probing
   `/Applications/Docker.app/Contents/Resources/bin/docker` first, then `command -v docker`.
   Never rely on `which docker` alone (memory: `docker-runs-but-cli-not-on-path`).
2. Add a daemon-liveness precheck using `lsof -nP -iTCP -sTCP:LISTEN` plus a `docker info` probe;
   exit with a clear message (not a stack trace) when the daemon is down.
3. Allocate a **unique free host port pair** per lane (bind-probe an ephemeral port, then reserve;
   never `5433` or `6379`). Derive unique container names as `e2e-<lane>-pg-<port>` /
   `e2e-<lane>-redis-<port>`.
4. Launch `postgres:16-alpine` and `redis:7-alpine` with `--rm`, **no named volume**, and
   `--tmpfs /var/lib/postgresql/data` where practical for speed.
5. Poll readiness (`pg_isready` / `redis-cli ping`) with a bounded timeout; fail loudly on timeout.
6. Emit exactly two lines on stdout: `DATABASE_URL=postgresql+asyncpg://...@localhost:<port>/...`
   and `REDIS_URL=redis://localhost:<port>/0`.
7. Implement a **localhost refusal guard**: if a caller passes an override DSN whose host is not
   `localhost`/`127.0.0.1`, refuse and exit non-zero unless `--allow-remote` is given. Unparseable
   host ⇒ refuse. Mirror `scripts/refresh_ip_org.py`.
8. Install `trap 'teardown' EXIT INT TERM` so containers are removed **unconditionally**, including
   on failure and on Ctrl-C.
9. Enforce the resource ceiling: refuse to start if 2 `e2e-*` container pairs are already running.

### Section B — Migration-truth lane (items 2 + 3)

10. **(F-4 — supersedes the withdrawn root-conftest branch.)** Do **not** edit `tests/conftest.py`
    at all. Add a **session-scoped** `disposable_engine` fixture in
    `tests/e2e_disposable/conftest.py` that owns the whole schema build:
    (a) `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` — **(C-12) this is mandatory and the
    only accepted implementation.** Do **not** substitute the weaker `DROP TABLE IF EXISTS
    alembic_version` plus model `drop_all`: that removes only tables present in the ORM metadata, so
    any table a migration creates but the ORM never declares survives and makes the next
    `upgrade head` fail on an existing object. (Verified safe: `grep -rn "CREATE EXTENSION"
    apps/api/migrations/versions/` returns **zero** matches, so no extension is dropped.)
    (b) `alembic -c apps/api/alembic.ini upgrade head` as a subprocess with `DATABASE_URL` pinned
    inline to the disposable DSN; (c) create the lane engine.
    **(F-3 — why (a) is mandatory.)** `alembic_version` is created by alembic's own DDL and appears
    nowhere in `Base.metadata`, so `Base.metadata.drop_all` leaves it **stamped at head**. The next
    `upgrade head` then applies **zero** revisions against an empty schema and every test after the
    first runs with no tables — the exact "empty-but-stamped, silently no-ops" shape recorded in
    memory `getbeam-local-dev-db-rebuild-recipe`. The build must also be **session-scoped**, never
    per-test: `migrations/env.py:_do_run_migrations` wraps the whole chain in a single
    `context.begin_transaction()` (no `transaction_per_migration`), so a per-test rebuild of 60+
    revisions is prohibitively slow.
11. The root `tests/conftest.py` diff must be **exactly zero lines** in both directions. The lane
    conftest must not import the root conftest's engine fixture (Blast Radius constraint) — with
    the build living lane-side, the two constraints no longer conflict.
12. Re-derive the live head with a pinned DSN before the first apply. Do not hardcode
    `b7e4d21a9c58` in any assertion — assert against `alembic heads` output at runtime.
12b. **(C-10 — in-process fail-closed DSN guard.)** Add a **session-scoped autouse** guard in
    `tests/e2e_disposable/conftest.py` that hard-fails unless the resolved `DATABASE_URL` host is
    `localhost`/`127.0.0.1` **and** the port is **none of** `5432`, `5433`, `6543`. Rationale: the
    shell helper's refusal protects only the helper path; a developer running
    `pytest tests/e2e_disposable/` directly falls through to `conftest.py:24`'s `setdefault`, hits
    the shared local dev DB on `:5433` (or, with the repo dotenv, Supabase PROD), and the fixture
    then `drop_all`s it. Unparseable DSN ⇒ refuse.
    **(C-15 — make the ordering explicit.)** Declare the lane engine fixture as
    `def disposable_engine(_dsn_guard): ...` so the guard-before-engine dependency is explicit rather
    than resting on pytest's default autouse ordering (which does place a session-scoped autouse
    fixture first today, but a future refactor could silently invert it). Note the guard fires at
    fixture time — i.e. **after** `tests/conftest.py:24`'s `setdefault` and after
    `models/database.py`'s import-time `create_async_engine`. That is harmless (engine creation is
    lazy; no connection is opened at import) and the guard still precedes every destructive
    statement.
13. Add `tests/e2e_disposable/test_migration_truth.py`: assert that after `upgrade head`, both
    `uq_coop_accrued_site_email` and `uq_coop_ledger_expire_per_lot` exist in `pg_indexes`, **and**
    assert behaviorally that a duplicate insert violating each one raises `IntegrityError`.
14. **Mutation probe (mandatory).** Temporarily delete
    `op.create_index("uq_coop_ledger_expire_per_lot", ...)` from `b7e4d21a9c58`, run the lane, and
    record that DE-2 goes **RED**. Revert the migration file afterwards and re-run to confirm GREEN.
    A gate that only asserts index presence via `pg_indexes` and passes because the ORM created it
    is exactly the failure this plan exists to prevent — the probe is the proof it is not.
15. Add a **non-empty-DB migration fixture**: seed the pre-migration schema (`downgrade` to the
    revision below `b7e4d21a9c58`), insert rows that would **violate** the new unique index, then
    `upgrade head` and assert a **clean abort** — the transaction rolls back with no partial state
    (index absent, rows unchanged, alembic version unchanged).
    **(C-11 — mandatory restore to head.)** `disposable_engine` builds the schema **once per
    session**, so a clean abort by definition leaves the DB **at the downgraded revision**. Every
    test collected after DE-11 in that session would then run without
    `uq_coop_ledger_expire_per_lot`, silently turning DE-2/DE-9b/DE-10-shaped assertions vacuous.
    DE-11 and DE-12 must therefore restore `upgrade head` in an explicit teardown, or use a
    dedicated function-scoped rebuild fixture used by those two tests only. State the restore
    explicitly in the test file — never rely on collection order.
16. Add the happy-path counterpart: populated-but-valid DB migrates cleanly and the index appears.
17. Where an offline `--sql` check is used anywhere in this lane, always pass an explicit
    `<from>:<to>` range (`b7d3e9f1a4c2_add_ad_connections.py` calls `sa.inspect(bind)` and breaks
    an unscoped offline run).

### Section C — Real-process lifespan harness (item 4)

18. Add `asgi-lifespan` to `requirements.txt`, annotated inline as test-only, **and also add it to
    the existing `[project.optional-dependencies] test` extra in `pyproject.toml`** (C-17).
19. **(C-3 — corrected.)** Only **`DATABASE_URL`** (and `REDIS_URL`) genuinely must precede import:
    the global engine is built at import time in `models/database.py`, so it cannot be retrofitted.
    Both must be **exported before the pytest process starts** (the helper prints them); the lane
    conftest **asserts** their value rather than setting them. Do **NOT** set
    `IDENTITY_COOP_ENABLED` before import — `start_scheduler()` reads
    `settings.identity_coop_enabled` at **call time** (`scheduler.py:743`) and the wrapper re-reads
    it at run time (`:314-317`). Setting it via env before import buys nothing and makes the
    boot-ON (DE-3) and boot-OFF (DE-4) gates **mutually exclusive in one process**, since
    `apps.api.config` cannot be re-imported with different env. Monkeypatch
    `settings.identity_coop_enabled` instead — the repo's own `coop_on` fixture
    (`test_identity_coop_contribution.py:575-579`) already does exactly this.
20. Boot the app through `LifespanManager(app)` so `main.py:93-110` actually runs `start_scheduler()`.
    Plain `ASGITransport` does **not** run lifespan — state this in a comment at the fixture.
21. Add `tests/e2e_disposable/test_lifespan_scheduler.py` gate: assert `scheduler.get_jobs()`
    contains a job id matching `coop_expiry_sweep`, and assert its **interval**, **jitter**, and
    **misfire_grace_time** equal the values at `scheduler.py:744-752`.
22. Add the boot-OFF gate: with `settings.identity_coop_enabled` monkeypatched to `False`
    **before `start_scheduler()` is called** (not before import — see item 19), assert **zero**
    coop jobs are registered (proves the `:743` gate). Both DE-3 and DE-4 therefore run in the
    same pytest process.
23. Add the runtime-OFF gate (K-5): register the job with the flag ON, then flip
    `settings.identity_coop_enabled` to `False` and force a run; assert the wrapper's `:314-317`
    re-check short-circuits and writes nothing.
24. Add the **end-to-end scheduler write** gate: seed one lapsed lot, force `next_run_time` to now,
    let the **scheduler** (not a direct service call) run, and assert an EXPIRE row was written —
    proving the wrapper's global `async_session` path works. This is the path `conftest.py:199-212`
    never patches.
25. **Mutation probe (mandatory).** Comment out the `add_job(...)` call at `scheduler.py:744-752`,
    confirm gates DE-3 and DE-5 go **RED**, then revert and re-confirm GREEN.
26. Add the **boundary** scenario: a lot with `expires_at == now` exactly. **(C-6 — the scenario is
    not constructible as originally written.)** Both the sweep (`identity_coop.py:558`) and
    `spendable_balance` (`:254`) compute `now = datetime.now(timezone.utc)` **internally**;
    `spendable_balance(db, site_id)` takes no `now` parameter and neither `freezegun` nor
    `time-machine` is installed. Fix: monkeypatch `apps.api.services.identity_coop.datetime` to a
    fixed `T` — one patch covers both call sites because both live in that module — seed
    `expires_at = T`, then assert swept (`<= T` true) **and** excluded from spendable (`> T` false),
    with no window in which it is counted twice or dropped by both.
    **(C-14 — seed `spendable_at` in the past, or the gate passes for the wrong reason.)**
    `spendable_balance` (`identity_coop.py:254-261`) excludes a lot when `spendable_at > now` **as
    well as** when `expires_at <= now`. A lot seeded with `expires_at = T` and the default hold
    (`created_at + coop_credit_hold_hours`) is excluded from the balance because it is still *held*,
    not because it expired — so the "excluded from spendable" half would be green even under a broken
    expiry predicate (the service docstring warns about exactly this). Seed `spendable_at` in the
    past (or monkeypatch `coop_credit_hold_hours` to 0) so the expiry predicate is the only remaining
    discriminator.
27. Add the **mid-run crash** scenario: kill/abort the sweep after N lots are committed; assert the
    already-processed lots are durable (per-lot `commit()` at `:588-602`) and the next tick resumes
    from the remainder without reprocessing.
28. Add the **aborted-transaction** scenario: force the session into an aborted state and assert
    the `finally` unlock still executes (an exception path that defeats the unlock leaves the
    advisory lock held forever — assert the lock is free afterwards from a different connection).

### Section D — Pooled / multi-connection topology (item 5)

29. Add `tests/e2e_disposable/test_pool_topology.py` with an engine pinned to
    `pool_size=3, max_overflow=2` (prod parity per `models/database.py:70-71` + `config.py:90-91`).
30. Drive ≥2 concurrent sessions via `asyncio.gather` following the precedent at
    `tests/integration/test_campaign_double_send.py:113-122`.
31. Re-probe `pg_advisory_unlock` from a **different connection** than the one that acquired it;
    assert the probe observes the lock as held during the sweep and free after.
32. **(F-1 — the original formulation of this gate is vacuous. Read the root-cause note below.)**
    Prove **acquisition** by observing the **lock itself**, never by observing rows written:
    (a) from a **third** connection, `SELECT pg_try_advisory_lock(hashtext('coop_expiry_sweep'))`
    MUST return **false** while the winner holds it (release it immediately if it returns true);
    (b) assert the loser's `run_coop_expiry_sweep` took the `got is False` branch — observable via
    the `coop_expiry_sweep_skipped_locked` structlog event (or a `_lot_remaining` call counter that
    must be exactly 0 for the loser).
    `_LOCK_KEY` MUST be imported from `services/coop_expiry_sweep.py`, never re-spelled in the test
    — the module docstring already warns that re-spelling makes the gate pass unconditionally.
    **(C-13 — remove the timing dependency; do not rely on catching a live sweep mid-hold.)** A probe
    that runs after release returns TRUE and fails the assertion — flaky-RED, not vacuous-GREEN, but
    still unacceptable. Construct it deterministically instead: acquire the lock **directly in the
    test** on connection 1 via `pg_try_advisory_lock(hashtext(_LOCK_KEY))` (with `_LOCK_KEY`
    imported), run `run_coop_expiry_sweep` on connection 2, and probe from connection 3. No race.
    *Why the original wording failed:* `coop_expiry_sweep.py` states the lock is **EFFICIENCY-ONLY**
    and that correctness comes from `uq_coop_ledger_expire_per_lot`. With the lock stubbed out, the
    second sweep runs, every INSERT hits `ON CONFLICT (lot_id) WHERE entry_type='EXPIRE' DO NOTHING`,
    `rowcount` is 0, and the sweep reports **0 rows written** — indistinguishable from
    "refused because the lock was held". Row counts are **lock-blind**.
33. **Mutation probe (mandatory).** Stub the advisory-lock acquisition to always return `True`
    without taking a lock; confirm DE-6 goes **RED** under the item-32 formulation; revert and
    re-run GREEN.
34. **(F-2 + orchestrator correction — split into two distinct scenarios.)**
    (a) **Orphan-guard scenario (the real DE-16a). (E-1 — do NOT implement the earlier
    "delete the ACCRUE lot row" formulation; it is vacuous.)** `_lot_remaining`
    (`identity_coop.py:479-498`) is a raw `SUM(amount) WHERE lot_id = :lot_id`, and an ACCRUE row
    **is its own lot** (`ledger.lot_id = ledger.id`, `:202`; model comment
    `models/identity_coop.py` "ACCRUE: own id"). Deleting the ACCRUE lot row therefore drives
    `SUM = 0` → `remaining = max(0, 0) = 0` → the **`continue` at `:589-590`** fires and
    `_EXPIRE_INSERT_SQL` is **never executed at all**, so no orphan EXPIRE row appears **with or
    without** the `WHERE EXISTS` guard and removing the guard leaves the gate GREEN.
    *Required implementation:* the mutation must keep `SUM(amount) > 0` for the lot while making the
    `EXISTS` predicate FALSE. Use a **mid-flight `site_id` rewrite** (no schema or enum change
    needed):
    1. Monkeypatch `apps.api.services.identity_coop._lot_remaining` with a wrapper that, on first
       call, issues `UPDATE identity_credit_ledger SET site_id = 'e2e-moved' WHERE id = :lot_id`
       **and commits on a separate connection**, then delegates to the real `_lot_remaining` (which
       still returns +N, because `lot_id` is untouched).
    2. The sweep's `:site_id` bind is the snapshot taken by the set-level SELECT **before** the
       update, so `EXISTS (... AND site_id = CAST(:site_id AS varchar))` is now FALSE while
       `remaining > 0`.
    3. Assert `SELECT count(*) ... WHERE lot_id = X AND entry_type = 'EXPIRE'` is **0** and the sweep
       did not raise.
    4. Mutation probe: delete the `WHERE EXISTS (...)` clause from `_EXPIRE_INSERT_SQL` → the count
       becomes 1 → DE-16a **RED**. Revert and re-confirm GREEN.
    *Do not pre-mutate before the sweep starts:* changing `site_id` beforehand makes the snapshot
    carry the NEW value (the lapsed SELECT has no site filter), and changing `entry_type` beforehand
    removes the row from the lapsed set (`:571` filters `entry_type == "ACCRUE"`). Both pre-mutations
    are themselves vacuous. The mutation must be mid-flight.
    (b) **Site-deleted scenario (separate, re-labelled).** Delete the site and assert the sweep does
    not raise. This proves robustness, **not** the orphan guard — deleting a `Site` row directly
    leaves the ledger intact (there is no ForeignKey on `identity_credit_ledger.site_id`;
    `models/identity_coop.py:148` is a bare `String(50)`), so the EXISTS clause stays TRUE either
    way and the guard's presence is invisible to it. Use the **router** path
    (`routers/sites.py` `delete_site`) for the realistic variant — see DE-17.

### Section E — Two-process replica simulation (item 6)

35. Add `tests/e2e_disposable/_replica_child.py`: a standalone entrypoint that reads
    `DATABASE_URL` from env, boots the sweep, and prints a machine-readable result line. This must
    be a real OS process — this is the **only** item that genuinely cannot be done in-process
    (prod runs N replicas ⇒ N `AsyncIOScheduler` instances against one DB).
36. Add `tests/e2e_disposable/test_two_process_replica.py`: launch **two** children against the
    **same** disposable DB, both running the sweep concurrently. **(C-2 — the two halves have
    different RED conditions; do not conflate them.)**
    (a) **one-winner half:** `_replica_child.py` MUST print a machine-readable
    `acquired=<bool> written=<n>` line; assert `sum(acquired) == 1`. **Only this half is falsified
    by removing the lock.** **(C-13 — add a start barrier.)** Two children that do not genuinely
    overlap both acquire and `sum(acquired) == 2` (flaky-RED). Gate the children on a shared start
    barrier (a shared row/file or `multiprocessing.Barrier`) and seed enough lots that the critical
    section outlasts child startup.
    (b) **no-duplicate-rows half:** assert exactly one EXPIRE row per lot. **(E-3 — the previously
    stated falsifier is false.)** `pg_try_advisory_lock` is session-scoped and the two children hold
    two separate connections, so with the lock intact exactly one child ever enters
    `expire_lapsed_lots` (`coop_expiry_sweep.py:76-82`) and the loser writes nothing — removing
    `uq_coop_ledger_expire_per_lot` **alone** therefore still yields exactly one EXPIRE row per lot
    and leaves DE-9b **GREEN**. The index is a *backstop* that is only observable once the lock is
    disabled. Its RED condition is therefore **"remove `uq_coop_ledger_expire_per_lot` *while* the
    advisory lock is stubbed out"**, and DE-9b's falsification MUST be run in that deliberate
    lock-disabled configuration. It is **not** "removing the lock" on its own (row counts are
    lock-blind). DE-9a keeps its own stated RED condition ("removing the lock"). Closes class 8 /
    K-2.
37. Add the two-process **accrual race**: both children accrue for the same `(site, email)`;
    assert `uq_coop_accrued_site_email` collapses them to one row and neither process crashes
    with an unhandled `IntegrityError`.
38. Add the **site deleted then RE-CREATED with the same `site_id`** scenario. **Delete via the
    real router path** (`routers/sites.py` `delete_site`), which at `:341-345` explicitly issues
    `DELETE FROM identity_contribution_events` and `DELETE FROM identity_credit_ledger` for that
    `site_id` under the comment "H1: close the site_id-reuse gap for spendable co-op credit".
    Assert the re-created site's balance is **zero**. Expected GREEN — Phase 1's H1 fix is intact.
    Additionally record the **residual** (see Known Gaps): there is **no ForeignKey** on
    `identity_credit_ledger.site_id`, so any delete path that bypasses `delete_site` (manual SQL, a
    future code path, a bulk admin operation) would leave orphan ledger rows with **no DB-level
    guarantee**. That is a hardening observation for the backlog, not a live defect.

### Section F — Scale fixture (item 7)

39. Add `tests/e2e_disposable/test_scale_sweep.py`: seed **≥10,000 lapsed lots** (bulk insert, not
    ORM per-row).
40. Measure and record: total sweep wall-clock, DB round-trip count, and maximum connection hold
    duration. The sweep selects **every** lapsed lot globally with no site filter, no LIMIT and no
    batching (`:563-576`), then does SELECT + INSERT + `commit()` **per lot** (`:588-602`) — so the
    work is O(3n) per-lot operations, of which only **2n** are visible to `before_cursor_execute`
    (COMMIT is not; see item 41 / E-2). Commits are counted separately.
41. **(C-5 threshold, corrected by E-2 — specified here in the plan, not deferred to EXECUTE.)**
    The hard FAIL is **structural and environment-independent**: **DB round-trips MUST be
    ≤ 2n + 10** (≤ **20,010** at n = 10,000). Derivation: `before_cursor_execute` fires only for
    statements executed through the DBAPI **cursor**; `session.commit()` goes through the DBAPI
    connection's `commit()` (and asyncpg's `BEGIN` through its transaction API), so **COMMIT is
    invisible to the counter**. The real measured shape is therefore `1` set-level SELECT
    (`identity_coop.py:563-576`) + `2` per lot (`_lot_remaining` SELECT + `_EXPIRE_INSERT_SQL`,
    `:588-602`) = **2n + 1 ≈ 20,001**, not 3n + 1. The former `3n + 10 = 30,010` ceiling left ~10,000
    of slack, so an entire extra per-lot round-trip (2n+1 → 3n+1 = 30,001) still PASSED — exactly the
    regression DE-18 names as its RED condition. Measure with a SQLAlchemy `before_cursor_execute`
    event counter registered on the lane engine, and record in the test docstring that COMMIT is not
    counted by it. **Additionally** count commits separately via SQLAlchemy's `ConnectionEvents.commit`
    hook, asserting **commits ≤ n + 5**. **Scope the counter to the sweep window**: reset it
    immediately before `run_coop_expiry_sweep` and read it immediately after, so the 10k-row bulk seed
    and the assertion queries are not counted.
    Wall-clock is environment-dependent: record it with a generous ceiling of **120 s** at
    n = 10,000 on a local container, as an **observation, not the gate**. Max single-connection hold
    equals the whole sweep by construction (one session throughout) — record it, do not gate it.

### Section G — Scenario 43 (item 8, D-E2E-1)

42. Add `tests/e2e_disposable/test_scenario_43.py`: seed a site with `contribution_enabled=True`,
    accrue a lot, then set `contribution_enabled=False`, then run the sweep past the lot's expiry.
    Assert the lot **IS** expired (an EXPIRE row is written).
43. Assert the complementary half: with `contribution_enabled=False`, **new** accrual is refused —
    proving opt-out stops new accrual only.
44. Record D-E2E-1's rationale verbatim as a docstring on the test so the intent survives the next
    reader: expiry is a property of the lot; freezing on opt-out would create an
    opt-out-to-preserve-credits-forever exploit.

### Section H — Wiring and closeout

45. **(F-5 — a registered marker excludes NOTHING.)** `pyproject.toml` sets
    `testpaths = ["tests"]` and has **no `addopts`**, so registering `disposable` in `markers = [...]`
    only silences the unknown-marker warning — a bare `pytest` still **collects and imports** every
    module under `tests/e2e_disposable/` (firing the `asgi-lifespan` import and any module-level env
    manipulation inside the normal unit lane). Therefore do BOTH: register the marker AND add a real
    exclusion. **(E-4 — `-m` is the WRONG primary mechanism; do not implement it as such.)** pytest
    applies `-m` as a **deselection filter applied after collection**, and collection imports every
    module under `testpaths = ["tests"]` — including `tests/e2e_disposable/conftest.py` and every lane
    spec. Two consequences: (i) module-level side effects in the lane still fire during a bare
    `pytest`; (ii) the exclusion silently depends on **every future lane file remembering the
    marker** — a file that omits it is collected *and executed* in the default run.
    *Required implementation:* make the **path-based** exclusion primary —
    `addopts = "--ignore=tests/e2e_disposable"` (or `collect_ignore_glob` — which must live in
    `pyproject.toml`, not the root conftest, since `tests/conftest.py` is 0/0/0). Keep the
    `disposable` marker registration for **selection**, and add `pytestmark = pytest.mark.disposable`
    at module level in **every** lane spec as defence in depth. Because `addopts` changes the default
    invocation for **every** suite in the repo, DE-1 must be run **after** this change lands, never
    before. DE-1(b) alone cannot detect a lane leak — `pytest tests/unit` / `pytest tests/integration`
    are path-scoped and would never collect `tests/e2e_disposable/` regardless — so DE-1 also carries
    a third leg: a bare `.venv/bin/python3.11 -m pytest --collect-only -q` from the repo root must
    list **zero** items under `tests/e2e_disposable/`.
45b. **(C-7 — the helper's own gates had no home and no run step.)** Add
    `tests/e2e_disposable/test_helper_guard.py` (≤ 120 lines) that invokes
    `scripts/e2e-disposable.sh` via subprocess and asserts DE-19 + DE-20: a remote DSN without
    `--allow-remote` exits non-zero and prints nothing; an unparseable host refuses; a SIGINT
    mid-run leaves no `e2e-*` container. Cite `scripts/e2e-local.sh` as the closest shell precedent
    (a script that forces the local stack and hard-refuses anything remote) alongside
    `scripts/refresh_ip_org.py`.
46. Add a short README stanza inside this task folder documenting the exact lane invocation
    sequence (helper → export → pytest), sequenced by default.
47. Run `node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs` on this plan.

---

## Verification Evidence

Every gate below states the **broken implementation it turns RED**. Non-vacuity is a **stated
requirement of this plan**, and mutation probes are **mandatory** for items 2, 4, and 5
(DE-2, DE-3/DE-5, DE-6).

### ROOT CAUSE: row-count assertions are lock-blind (read before adding any gate)

This phase's history is now **seven** recurrences of "a gate that passes on the implementation it
exists to forbid". The PVL supplement of 17-08-26 found the fifth, sixth and seventh —
**F-1 (DE-6), F-2 (DE-16), and C-2 (DE-9)** — and all three trace to **one** root cause:

> `uq_coop_ledger_expire_per_lot` + `ON CONFLICT (lot_id) WHERE entry_type='EXPIRE' DO NOTHING`
> makes every EXPIRE insert idempotent. A sweep that **ran without the lock** therefore reports the
> same `rowcount = 0` as a sweep that was **refused because the lock was held**. Row counts cannot
> distinguish them: **row-count assertions are lock-blind.**

Standing rule for this plan and any successor: **any gate whose only assertion is a row count must
be checked against this root cause before it is accepted.** If the behavior under test is a lock, a
guard, or an ordering property, assert on that mechanism directly (a third-connection
`pg_try_advisory_lock` probe, an `acquired=` flag printed by the child process, a call counter, a
named structlog event) — never on how many rows appeared.

### Gate-ID renumbering (C-9)

This plan's gates are prefixed **`DE-`** (`DE-1` … `DE-21`) to end the collision with identity-coop
**Phase 2a's** own `DE-1` … `DE-23` — both plans are cited in the same documents, and
`services/coop_expiry_sweep.py`'s `_LOCK_KEY` comment refers to a *different* `DE-20`. Mapping is
identity: `DE-N` ≡ this plan's former `G-N`. Any bare `G-N` in the `## Validate Contract` section
below predates the renumbering and means `DE-N` unless explicitly written "Phase-2a G-N".

| Gate / Scenario | Strategy | Proves SPEC criterion | Goes RED against |
|---|---|---|---|
| **DE-1** Default lane unchanged — **three legs** (C-1 + E-4): (a) mechanical: `git diff --numstat tests/conftest.py` reports **0 additions and 0 deletions**; (b) behavioral: `pytest tests/unit -q` and `pytest tests/integration -q` both green, run **after** the `pyproject.toml` `addopts` change lands; (c) collection: a bare `.venv/bin/python3.11 -m pytest --collect-only -q` from the repo root lists **zero** items under `tests/e2e_disposable/` — leg (b) is path-scoped and cannot detect a lane leak at all (E-4) | **Hybrid** (integration lane needs PG/Redis — it was mis-tiered Fully-Automated) | D-E2E-2 (default byte-identical) | any edit to `tests/conftest.py` at all; any `addopts` change that swallows existing suites |
| **DE-2** Index parity: `uq_coop_ledger_expire_per_lot` + `uq_coop_accrued_site_email` exist after `alembic upgrade head` and reject duplicates | Hybrid (disposable PG) | class 1 — model/migration divergence | **mutation probe**: delete `op.create_index(...)` from `b7e4d21a9c58` ⇒ must FAIL |
| **DE-3** Coop job registered with correct interval/jitter/misfire after real lifespan boot | Hybrid | class 3 — job never registers | **mutation probe**: comment out `add_job` at `scheduler.py:744-752` ⇒ must FAIL |
| **DE-4** Boot-OFF: zero coop jobs when `identity_coop_enabled=false` before import | Hybrid | `scheduler.py:743` boot gate | removing the `if settings.identity_coop_enabled:` guard |
| **DE-5** Scheduler-driven EXPIRE write via the global `async_session` | Hybrid | class 4 — wrapper broken end-to-end | **same probe as DE-3**; also any change breaking `scheduler.py:16` session import |
| **DE-5b** Runtime-OFF re-check (K-5) writes nothing | Hybrid | `scheduler.py:314-317` | deleting the runtime re-check (the `:310-312` do-not-delete comment) |
| **DE-6** Advisory lock **acquired** — proven from a **third connection** (`pg_try_advisory_lock` returns false while held) **and** by the loser taking the `got is False` branch (`coop_expiry_sweep_skipped_locked` event). **Never by row count** — see the root-cause note above | Hybrid | class 5, Phase-2a G-20 residual (i) | **mutation probe**: stub lock acquisition to return `True` without locking ⇒ must FAIL (it did NOT fail under the original row-count formulation — F-1) |
| **DE-7** Advisory lock observed held/free from a **different** connection | Hybrid | class 5 | a lock scoped to the session rather than the connection |
| **DE-8** Scenario 43 (D-E2E-1): lot expires despite `contribution_enabled=False`; new accrual refused | **Hybrid** (needs a live PG for the ledger write) | D-E2E-1 | any implementation that skips lots for opted-out sites (the exploit) |
| **DE-9a** Two processes, **one winner**: `sum(acquired) == 1` from `_replica_child.py`'s `acquired=<bool> written=<n>` line | Hybrid (2 OS procs) | class 8 / K-2 — N replicas ⇒ N schedulers | removing the advisory lock (this half only) |
| **DE-9b** Two processes, **no duplicate rows**: exactly one EXPIRE row per lot | Hybrid (2 OS procs) | class 8 | removing `uq_coop_ledger_expire_per_lot` **while the advisory lock is stubbed out** — with the lock intact only one child ever enters the sweep, so removing the index alone leaves this GREEN (E-3). **NOT** falsified by removing the lock alone (C-2) |
| **DE-10** Two-process accrual race collapses to one row, no unhandled `IntegrityError` | Hybrid | class 8 | missing unique index or unhandled conflict |
| **DE-11** Non-empty-DB migration aborts cleanly on violating rows — no partial state | Hybrid | class 2 | a migration that leaves a half-applied schema |
| **DE-12** Populated-but-valid DB migrates cleanly | Hybrid | class 2 | over-strict migration that fails on legitimate data |
| **DE-13** Boundary `expires_at == now` (constructed by monkeypatching `apps.api.services.identity_coop.datetime` to a fixed `T` — C-6): expired by sweep **and** excluded from spendable balance | **Hybrid** (needs the ledger write) | class 7 | `<`/`>=` predicate drift creating a double-count or drop-by-both window |
| **DE-14** Mid-run crash: processed lots durable, next tick resumes, no reprocessing | Hybrid | class 7 | a single wrapping transaction instead of per-lot commit |
| **DE-15** Aborted transaction still releases the lock (`finally` survives) | Hybrid | class 7 | an exception path that bypasses the unlock ⇒ lock held forever |
| **DE-16a** Orphan guard: a **mid-flight `site_id` rewrite** (via a `_lot_remaining` wrapper that `UPDATE`s + commits on a separate connection) makes the `EXISTS` predicate FALSE while `SUM(amount) > 0` ⇒ no orphan EXPIRE row, no raise (E-1) | Hybrid | `services/identity_coop.py:522-527` | removing the `WHERE EXISTS` clause from `_EXPIRE_INSERT_SQL`. (Both earlier mutations were vacuous: "delete the Site" left it GREEN because there is no FK on `identity_credit_ledger.site_id` (F-2); "delete the ACCRUE lot row" drives `_lot_remaining` to 0 so the `continue` at `:589-590` fires and the INSERT never runs at all (E-1)) |
| **DE-16b** Site row deleted mid-sweep ⇒ sweep does not raise | Hybrid | robustness only — explicitly **not** an orphan-guard proof | an unguarded attribute/row access on the missing site |
| **DE-17** Site deleted **via `routers/sites.py` `delete_site`** then re-created with the same `site_id` ⇒ balance is zero, nothing resurrects | Hybrid | class 7 (uncovered leg) | a `delete_site` that stops deleting `identity_credit_ledger` / `identity_contribution_events` (Phase 1's H1 fix, `sites.py:341-345`). **Expected GREEN** — see the pre-declared-findings note |
| **DE-18** Scale: 10k lapsed lots — hard FAIL at **round-trips > 2n + 10** (> 20,010), measured via a `before_cursor_execute` counter **scoped to the sweep window**, plus a separate `ConnectionEvents.commit` counter asserting **commits ≤ n + 5** (COMMIT is invisible to `before_cursor_execute`; real shape is 2n+1, so the former 3n+10 ceiling let a whole extra per-lot round-trip pass — E-2). Wall-clock (ceiling 120 s) and connection hold are **recorded observations, not gates** | Hybrid | class 6 | any change adding a per-lot round-trip (e.g. an extra SELECT in the loop) |
| **DE-19** Helper refuses a non-localhost DSN without `--allow-remote`; unparseable host ⇒ refuse. **Home file: `tests/e2e_disposable/test_helper_guard.py`** (C-7) | Hybrid (docker daemon) | prod-safety constraint | a helper that would let an alembic command reach Supabase PROD |
| **DE-20** Helper teardown is unconditional (containers gone after failure and after SIGINT). **Home file: `test_helper_guard.py`** | Hybrid (docker daemon) | resource-ceiling constraint | a teardown only on the success path |
| **DE-21** In-process DSN guard (C-10): a direct `pytest tests/e2e_disposable/` against a non-localhost host, or against port 5432/5433/6543, **hard-fails at session setup before any `drop_all`** | Fully-Automated | prod-safety constraint | a lane that trusts `conftest.py:24`'s `setdefault` and wipes the shared dev DB |

**Mutation-probe protocol:** each probe edits exactly one line/block, runs only the affected gate,
records RED, then **reverts and re-runs to confirm GREEN**. A probe left un-reverted is a
worse outcome than no probe — the revert-and-confirm step is part of the gate, not cleanup.

### Pre-declared findings (gates expected to fire — report, do not fix here)

Declared **now** so a RED result is a recorded expectation rather than a mid-EXECUTE surprise.

| Gate | Expectation | Why | Follow-up path on RED |
|---|---|---|---|
| **DE-13** (boundary) | may fire | the `<= now` / `> now` split is only correct if the two predicates are evaluated against the same instant; the monkeypatched-`datetime` construction is the first time this is checked at all | backlog NOTE in this task folder; no follow-up plan unless the window is real |
| **DE-18** (scale) | may fire | the sweep selects **every** lapsed lot globally with no site filter, no LIMIT and no batching, then commits per lot — O(2n) *counted* round-trips (+ n commits, counted separately) is the *designed* shape, so the gate fires only on a regression past 2n + 10 (E-2) | backlog NOTE; batching would be its own plan |
| **DE-7** (unlock on a recycled connection) | **likely to fire** | `coop_expiry_sweep.py`'s own docstring already records the accepted residual: the per-lot `commit()` can return the session's connection to the pool, so the unlock may run on a **different** connection and silently no-op. Section D's prod-parity `pool_size=3, max_overflow=2` pool is *exactly* the condition that surfaces it | record as a confirmed residual against the existing docstring; backlog NOTE |

**Explicitly NOT pre-declared: DE-17.** An earlier reading concluded that deleting a Site orphans
the ledger and lets a re-created `site_id` inherit its balance — a billing-surface defect. **That
conclusion is wrong and must not be propagated.** `apps/api/routers/sites.py` `delete_site` at
`:341-345` explicitly issues `DELETE FROM identity_contribution_events` and
`DELETE FROM identity_credit_ledger` for the `site_id`, under the comment "H1: close the
site_id-reuse gap for spendable co-op credit". Phase 1's H1 fix is intact and the user's Phase 1
approval stands. DE-17 is therefore expected **GREEN**, and no follow-up plan is pre-declared.
The genuine residual — recorded in Known Gaps, **not** as a live bug — is that there is no
ForeignKey on `identity_credit_ledger.site_id` (`models/identity_coop.py:148` is a bare
`String(50)`), so any delete path that bypasses `delete_site` leaves orphan ledger rows with no
DB-level guarantee. That is a hardening observation for the backlog.

---

## Test Infra Improvement Notes

(none identified yet — populate during EXECUTE/EVL. Expected candidates: whether the alembic branch
should eventually become the default lane once green, and whether `no_mx` belongs in the root
conftest rather than duplicated per lane.)

---

## Risks

| Risk | Mitigation |
|---|---|
| ~~Editing `tests/conftest.py` while an EVL agent is mid-run against it~~ — **retired by F-4**: the root conftest is now zero-diff | Residual: the lane still shares the docker daemon and the developer's ports. Confirm no other agent is mid-run against a container before Section B. Sections A, F, G remain independent and can start first |
| Changing `pyproject.toml` `addopts` alters the default `pytest` invocation for **every** suite in the repo | Land it in Section H **before** running DE-1, and make DE-1's behavioral leg the proof that no existing suite was swallowed |
| The alembic lane is slow (full chain per test session) | Session-scoped engine; the container is per-lane, not per-test |
| Item 6's child processes leak on failure | The helper's `trap` teardown plus explicit child `terminate()` in a fixture `finally` |
| A gate goes RED against current source | That is a **finding**, reported in the phase report — not a licence to edit `identity_coop.py` under this plan |
| Docker daemon genuinely down (distinct from CLI-off-PATH; observed 16-08-26) | Helper's `docker info` probe fails loudly with the distinguishing message |

---

## Constraints (non-negotiable)

- Repo-default-OFF flags **stay OFF in `.env`**. The lane sets them per-test/per-process only, and
  never edits `.env`.
- **No production DDL.** Every alembic/DB command pins `DATABASE_URL` inline to the disposable DSN.
- The helper **refuses** a non-localhost DSN (precedent `scripts/refresh_ip_org.py --allow-remote`).
- Teardown is **unconditional** (`trap ... EXIT INT TERM`).
- **Max 2 concurrent container pairs**; lanes sequenced by default.
- Alembic offline `--sql` always uses an explicit `<from>:<to>` range.
- Detect docker via `lsof`, never `which docker`.
- The lane hard-fails in-process on any DSN that is not localhost, or whose port is 5432/5433/6543.
- **No gate may assert a lock, guard, or ordering property by row count alone** — see the
  lock-blind root-cause note under Verification Evidence.

---

## Known Gaps

- **K-3 (carried):** no deployed flag-ON proof. Legally blocked pending the `coop_terms_version`
  re-pin. This lane proves production *shape*, not production *deployment*.
- Live MX behavior is neutralised by `no_mx`, so real `email_validator` DNS behavior stays unproven.
- Redis is provisioned per lane but coop logic is Postgres-only; the Redis container exists to
  isolate the lane from a stray 6379, not because a Redis path is under test.
- The scale threshold in DE-18 is a **stated ceiling**, not a production SLO — production sweep
  volume is unmeasured.
- **No ForeignKey on `identity_credit_ledger.site_id`** (`models/identity_coop.py:148` is a bare
  `String(50)`). The real delete path (`routers/sites.py` `delete_site:341-345`) removes the coop
  rows explicitly, so there is **no live defect** — but there is no DB-level guarantee for any
  delete path that bypasses it (manual SQL, a future code path, a bulk admin operation). Hardening
  observation for the backlog; DE-17 covers the router path only.
- **C-8 — `asgi-lifespan` ships in the production image.** `Dockerfile:10-11` installs
  `requirements.txt`, so adding a test-only dep there is a real (if tiny) deviation from "zero
  production changes". **(C-17 — wording corrected; the conclusion is unchanged.)** `pyproject.toml`
  **already has** a `[project.optional-dependencies] test` table (it lists
  `pytest`/`pytest-asyncio`/`httpx`/`fakeredis`), so the earlier claim "there is no `[project]`
  table" was imprecise. The extra is nonetheless **not installable in this repo**: there is no
  `[project]` `name`/`version` and no `[build-system]`, so `pip install .[test]` fails. Decision:
  keep `asgi-lifespan` in `requirements.txt`, annotate it inline as test-only, **and also add it to
  that existing `test` extra** so the test-only intent is recorded where a future `[project]` fix
  would pick it up. Record the deviation here so the "zero production changes" claim stays honest.
- **C-4b / defect class 9 — production masks table-level migration divergence.** The `Dockerfile`
  runs `alembic upgrade head`, then `apps/api/main.py`'s lifespan runs `Base.metadata.create_all` on
  the global engine, silently re-creating any table a migration failed to create. Index-level
  divergence still survives (`create_all(checkfirst=True)` skips existing tables entirely, so the
  DE-2 probe stays falsifiable). Recorded as a finding; fixing it is out of scope here.

---


## Acceptance Criteria

| ID | Criterion | proven by | strategy |
|---|---|---|---|
| AC-1 | The default test lane is provably untouched (`tests/conftest.py` 0/0 diff) and stays green after the `addopts` change | DE-1 (both legs) | Hybrid |
| AC-2 | A model-declared index missing from its migration is detectable | DE-2 (+ mutation probe) | Hybrid |
| AC-3 | Migrations are proven correct on a non-empty DB, both abort and happy path | DE-11, DE-12 | Hybrid |
| AC-4 | The coop expiry job is proven to register at boot with correct interval/jitter/misfire, and not to register when the flag is off | DE-3, DE-4 (+ mutation probe) | Hybrid |
| AC-5 | The scheduler itself writes an EXPIRE row through the global session, and the runtime flag re-check short-circuits | DE-5, DE-5b | Hybrid |
| AC-6 | The advisory lock is proven **acquired** (not just released) via a third-connection probe and the loser's skip branch — never via row counts | DE-6, DE-7 (+ mutation probe) | Hybrid |
| AC-7 | Two OS processes against one DB produce exactly one **lock winner** (DE-9a) and no duplicate rows (DE-9b) — the two halves have different RED conditions | DE-9a, DE-9b, DE-10 | Hybrid |
| AC-8 | Scenario 43 (D-E2E-1) is gated: lots expire despite opt-out; new accrual is refused | DE-8 | Hybrid |
| AC-9 | Boundary, mid-run crash, aborted-transaction, orphan (ACCRUE-row mutation), site-delete robustness, and site-recreate-via-router semantics are gated | DE-13, DE-14, DE-15, DE-16a, DE-16b, DE-17 | Hybrid |
| AC-10 | Sweep scale is measured against the stated hard FAIL of round-trips ≤ 2n + 10, plus commits ≤ n + 5 on a separate counter (E-2) | DE-18 | Hybrid |
| AC-11 | The helper refuses non-localhost DSNs and tears down unconditionally, proven by a real test file | DE-19, DE-20 (`test_helper_guard.py`) | Hybrid |
| AC-12 | A direct `pytest` invocation cannot reach the shared dev DB or PROD — the lane refuses at session setup | DE-21 | Fully-Automated |

Known-Gap residuals (K-3, live MX, Redis, scale SLO) are recorded in Known Gaps and keep their
related gates **CONDITIONAL** — they are never a terminal PASS for developed behavior.

---

## Phase Completion Rules

This plan is a single phase. It advances state only as follows:

- **PLANNED** — plan written, no source touched. (Current state.)
- **VALIDATED** — vc-validate-agent has written the `## Validate Contract` section with a
  `Gate: PASS` or an explicitly accepted `Gate: CONDITIONAL`. EXECUTE may not begin before this.
- **CODE DONE** — all checklist Sections A–H implemented; each section's own gates run green at
  the end of that section (per-section gate loop, not batched to the end).
- **✅ VERIFIED** — set only after explicit user confirmation of the evidence, and requires ALL of:
  1. every gate DE-1 … DE-21 (including DE-9a/DE-9b and DE-16a/DE-16b) run and recorded, with each
     result attributed to a named lane run;
  2. all three **mandatory mutation probes** (DE-2, DE-3/DE-5, DE-6) recorded RED-then-reverted-GREEN;
  3. the independent EVL confirmation run (spawned vc-tester re-running the validate-contract gate
     commands) green — execute-agent's own iterate-until-green loop does not substitute;
  4. no container left running and no `tests/conftest.py` default-path behavior change (DE-1 green);
  5. every unresolved gap written to a backlog NOTE in this task folder.

Code-only completion is **CODE DONE**, never VERIFIED. A gate that goes RED against current
`apps/api/` source is reported as a finding and does **not** block VERIFIED for this
test-infrastructure phase — but it must be recorded in the phase report and routed to its own plan.

---

## Resume and Execution Handoff

1. **Selected plan file:**
   `process/features/visitors-identity/active/coop-disposable-e2e_17-08-26/coop-disposable-e2e_PLAN_17-08-26.md`
2. **Last completed phase/step:** PLAN written 17-08-26; **PVL supplement cycle 1 applied 17-08-26**
   (5 FAILs + 10 CONCERNs from the `Gate: BLOCKED` contract, Gaps 1-15). No source files touched.
3. **Validate-contract status:** written 17-08-26, `Gate: BLOCKED`. This supplement addresses all 15
   gaps; **PVL must re-run from V1**. EXECUTE is not authorised until the re-validation returns
   PASS or an explicitly accepted CONDITIONAL.
4. **Supporting context loaded:** `process/context/all-context.md`; identity-coop task folder
   (`identity-coop_07-08-26/`) including `results.tsv` row 30; `tests/conftest.py` (:24-27, :95,
   :127-143, :199-212) verified read-only during planning.
5. **Next step for a fresh agent:** re-run VALIDATE (PVL from V1) on this plan. Then, at EXECUTE,
   start with **Section A** (helper script — fully independent), then **Section H's `pyproject.toml`
   exclusion** (it changes the default invocation, so DE-1 must run after it), then Section B.
   `tests/conftest.py` is now **zero-diff**, so the previous "defer Section B until the concurrent
   EVL run finishes" blocker no longer applies to the root conftest — but still confirm no other
   agent is mid-run against the shared test DB before touching containers. Do not run pytest,
   docker, or any DB command before that confirmation.

---

## Validate Contract

Status: CONDITIONAL
Date: 17-08-26
date: 2026-08-17
generated-by: inner-pvl: coop-disposable-e2e
supersedes: 2026-08-17 (inner-pvl: coop-disposable-e2e — cycle 1, Gate: BLOCKED) — cycle 2 re-validation after supplement cycle 1 applied all 15 gaps

PVL cycle: 2 (cycle 1 = BLOCKED, 5 FAILs + 10 CONCERNs; supplement cycle 1 applied 17-08-26)

Parallel strategy: sequential (Sections A→B→C→D→E), with parallel-subagents permitted for the
independent leaf specs (F scale, G scenario-43) once Section A's helper exists.
Rationale: signal score 2/7 (S6 — migration files are temporarily edited by the mandatory mutation
probes; S7 — 12 files in blast radius). Dominant signal: S7. The B→C→D→E dependency chain
(container → conftest → lane engine) overrides the MEDIUM threshold's default parallel recommendation.
Model: opus for every leg (source-adjacent test infrastructure).

### Net gate derivation

| Layer 1 dimension | Status |
|---|---|
| Infra fit | CONCERN |
| Test coverage | CONCERN |
| Breaking changes | CONCERN |
| Security surface | PASS |

| Layer 2 section | Status |
|---|---|
| A — Disposable stack helper (item 1) | PASS |
| B — Migration-truth lane (items 2+3) | CONCERN |
| C — Real-process lifespan harness (item 4) | CONCERN |
| D — Pooled/multi-connection topology (item 5) | CONCERN |
| E — Two-process replica (item 6) | CONCERN |
| F — Scale fixture (item 7) | CONCERN |
| G — Scenario 43 (item 8) | PASS |
| H — Wiring and closeout | CONCERN |

**Totals: 0 FAILs / 9 CONCERNs / 3 PASSes → Net Gate: CONDITIONAL**

Every cycle-1 FAIL (F-1 … F-5) is verified CLOSED (see §Cycle-1 fix verification). Cycle 2 found no
new FAIL. It did find **four fresh instances of the program's recurring vacuous-gate class** — this
is now the **eighth through eleventh** recurrence, and **three of the four live in text the cycle-1
supplement itself wrote**. Each has a fully-specified mechanical correction (E-1 … E-4 below), so
they are carried as binding execute-agent instructions rather than a third supplement cycle. **A
gate listed in E-1 … E-4 MUST NOT be implemented as the plan currently words it.**

### Cycle-1 fix verification (all five FAILs CLOSED)

| Cycle-1 FAIL | Verdict | Evidence |
|---|---|---|
| **F-1** — DE-6 lock probe vacuous | **CLOSED** | The new formulation is genuinely falsifiable in **both** legs. Verified against `services/coop_expiry_sweep.py`: `_LOCK_KEY = "coop_expiry_sweep"` (:29) and `pg_try_advisory_lock(hashtext(:key))` (:36). With acquisition stubbed to return `True` without locking: (a) the third-connection probe finds the key unheld → returns TRUE → the "MUST return false" assertion FAILS → RED; (b) no caller reaches `got is False` (:77) → `coop_expiry_sweep_skipped_locked` (:78) is never emitted → RED. `_LOCK_KEY` is importable (module-level name). `structlog` capture has three in-repo precedents (`tests/unit/test_site_analysis.py`, `tests/unit/test_graph_erasure.py`, `tests/integration/test_privacy_hold_clear.py`), so leg (b) is implementable today. |
| **F-2** — DE-16 orphan gate vacuous | **CLOSED as stated, but the replacement is ALSO vacuous** — see **E-1**. The split into DE-16a (orphan guard) / DE-16b (robustness only) is correct and the re-labelling is right; the *mutation* chosen for DE-16a still cannot flip the gate. |
| **F-3** — `alembic_version` survives `drop_all` | **CLOSED** | `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` removes `alembic_version` (it lives in `public` and appears nowhere in `Base.metadata`), leaving a true clean slate for a repeated `upgrade head`. No collateral hazard found: `grep -rn "CREATE EXTENSION" apps/api/migrations/versions/` returns **zero** matches, so no extension is dropped; the `cidr` GiST opclass used by ip-org is core PG, not an extension. `search_path` (`"$user", public`) still resolves. The disposable `postgres:16-alpine` superuser owns the recreated schema. Session-scoping is correct: `migrations/env.py:_do_run_migrations` wraps the whole chain in one `context.begin_transaction()`. Residual: **C-11** (DE-11 leaves the session schema downgraded) and **C-12** (the "at minimum" fallback). |
| **F-4** — conftest 0-modified budget unachievable | **CLOSED** | Moving the build into `tests/e2e_disposable/conftest.py` as session-scoped `disposable_engine` makes the root-conftest budget 0/0/0 genuinely achievable, and removes the Blast-Radius contradiction (the lane conftest no longer needs the root engine fixture). Touchpoints, Blast Radius, DE-1(a) and the Resume section are mutually consistent on this. |
| **F-5** — marker registration excludes nothing | **CLOSED in diagnosis, NOT in the chosen fix** — see **E-4**. The plan correctly identifies that a bare `pytest` imports the lane, then names `-m 'not disposable'` as the primary mechanism, which does not solve the problem it just described. |

### CONCERNs — binding execute-agent instructions (E-1 … E-4 are mandatory)

**E-1 (highest priority) — DE-16a's mutation cannot flip the gate; the `remaining == 0`
short-circuit masks the `WHERE EXISTS` guard entirely.** *(checklist 34(a), DE-16a row.)*
`_lot_remaining` (`identity_coop.py:479-498`) is a raw `SUM(amount) WHERE lot_id = :lot_id`, and an
ACCRUE row **is its own lot** (`ledger.lot_id = ledger.id`, `:202`; model comment
`models/identity_coop.py` "ACCRUE: own id"). Deleting the ACCRUE lot row therefore drives
`SUM = 0` → `remaining = max(0, 0) = 0` → **`continue` at `:589-590`** → `_EXPIRE_INSERT_SQL` is
**never executed at all**. No orphan EXPIRE row appears **with or without** the `WHERE EXISTS`
guard, so removing the guard leaves DE-16a GREEN. This is the same failure shape as cycle-1's F-2,
one layer deeper.
*Required implementation (do NOT implement item 34(a) as written):* the mutation must keep
`SUM(amount) > 0` for the lot while making the `EXISTS` predicate FALSE. Use a **mid-flight
`site_id` rewrite**, which needs no schema or enum change:
1. Monkeypatch `apps.api.services.identity_coop._lot_remaining` with a wrapper that, on first call,
   issues `UPDATE identity_credit_ledger SET site_id = 'e2e-moved' WHERE id = :lot_id` **and commits
   on a separate connection**, then delegates to the real `_lot_remaining` (which still returns +N,
   because `lot_id` is untouched).
2. The sweep's `:site_id` bind is the snapshot taken by the set-level SELECT **before** the update,
   so `EXISTS (... AND site_id = CAST(:site_id AS varchar))` is now FALSE while `remaining > 0`.
3. Assert `SELECT count(*) ... WHERE lot_id = X AND entry_type = 'EXPIRE'` is **0** and the sweep did
   not raise.
4. Mutation probe: delete the `WHERE EXISTS (...)` clause from `_EXPIRE_INSERT_SQL` → the count
   becomes 1 → DE-16a **RED**. Revert and re-confirm GREEN.
*Do not pre-mutate before the sweep starts:* changing `site_id` beforehand makes the snapshot carry
the NEW value (the lapsed SELECT has no site filter), and changing `entry_type` beforehand removes
the row from the lapsed set (`:571` filters `entry_type == "ACCRUE"`). Both pre-mutations are
themselves vacuous. The mutation must be mid-flight.

**E-2 — DE-18's threshold is loose by ~n and is blind to its own stated RED condition.**
*(checklist 41, DE-18 row.)* SQLAlchemy's `before_cursor_execute` fires only for statements executed
through the DBAPI cursor. `session.commit()` goes through the DBAPI connection's `commit()` (and
asyncpg's `BEGIN` goes through its transaction API), so **COMMIT is invisible to the counter**. The
real measured shape is therefore `1` set-level SELECT + `2` per lot (`_lot_remaining` SELECT +
`_EXPIRE_INSERT_SQL`) = **2n + 1 ≈ 20,001** at n = 10,000, not 3n + 1. Against a `3n + 10 = 30,010`
ceiling that leaves ~10,000 of slack — an entire extra per-lot round-trip (2n+1 → 3n+1 = 30,001)
still **PASSES**, which is exactly the regression DE-18 names as its RED condition.
*Required implementation:* set the hard FAIL at **round-trips ≤ 2n + 10 (≤ 20,010 at n = 10,000)**,
record in the test docstring that COMMIT is not counted by `before_cursor_execute`, and **additionally**
count commits separately via SQLAlchemy's `ConnectionEvents.commit` hook, asserting commits ≤ n + 5.
Also **scope the counter to the sweep window**: reset it immediately before `run_coop_expiry_sweep`
and read it immediately after, so the 10k-row bulk seed and the assertion queries are not counted.

**E-3 — DE-9b's stated RED condition is false: with the lock intact, removing the unique index
changes nothing.** *(checklist 36(b), DE-9b row.)* `pg_try_advisory_lock` is session-scoped and the
two children hold two separate connections, so exactly one child ever enters `expire_lapsed_lots`
(`coop_expiry_sweep.py:76-82`). The loser writes nothing. Removing `uq_coop_ledger_expire_per_lot`
alone therefore still yields exactly one EXPIRE row per lot → DE-9b stays **GREEN**. The index is a
*backstop* that is only observable once the lock is disabled.
*Required implementation:* restate DE-9b's RED condition as **"removing `uq_coop_ledger_expire_per_lot`
*while* the advisory lock is stubbed out"**, and run DE-9b's falsification in that deliberate
lock-disabled configuration. DE-9a (`sum(acquired) == 1`) keeps its stated RED condition
("removing the lock") — that one is verified correct.

**E-4 — `addopts = "-m 'not disposable'"` does not prevent collection or import, and the Public
Contracts row asserting that it does is factually wrong.** *(checklist 45, Public Contracts row 3.)*
pytest applies `-m` as a **deselection filter after collection**; collection imports every module
under `testpaths = ["tests"]`, including `tests/e2e_disposable/conftest.py` and every lane spec.
Two consequences: (i) module-level side effects in the lane still fire during a bare `pytest`;
(ii) the exclusion silently depends on **every future lane file remembering the marker** — a file
that omits it is collected *and executed* in the default run.
*Required implementation:* make the **path-based** exclusion primary — `--ignore=tests/e2e_disposable`
in `addopts` (or `collect_ignore_glob = ["e2e_disposable/*"]` in the root conftest, which is
0-diff-safe only if placed in `pyproject.toml` instead, since `tests/conftest.py` is 0/0/0). Keep
the `disposable` marker registration for selection, and add `pytestmark = pytest.mark.disposable`
at module level in **every** lane spec as defence in depth. Correct the Public Contracts row to say
what the chosen mechanism actually does. Additionally, **DE-1(b) as written cannot detect this leak
at all** — `pytest tests/unit -q` and `pytest tests/integration -q` are path-scoped and would never
collect `tests/e2e_disposable/` regardless. Add a third DE-1 leg: a bare
`.venv/bin/python3.11 -m pytest --collect-only -q` from the repo root must list **zero** items under
`tests/e2e_disposable/`.

**C-11 — DE-11's downgrade mutates the session-scoped schema for every later test.** *(checklist 15.)*
`disposable_engine` builds the schema **once per session**. DE-11 downgrades below `b7e4d21a9c58`,
seeds violating rows, and asserts a clean abort — which by definition leaves the DB **at the
downgraded revision**. Every test collected after DE-11 in that session then runs without
`uq_coop_ledger_expire_per_lot`, silently turning DE-2/DE-9b/DE-10-shaped assertions vacuous.
*Fix:* give the down/up tests (DE-11, DE-12) an explicit teardown that restores `upgrade head`, or a
dedicated function-scoped rebuild fixture used by those two tests only. State the restore explicitly
in the test file — do not rely on collection order.

**C-12 — the "at minimum" fallback in checklist item 10(a) is strictly weaker and should be
dropped.** `DROP TABLE IF EXISTS alembic_version` + `Base.metadata.drop_all` only removes tables
present in the ORM metadata; any table a migration creates but the ORM does not declare survives and
makes the next `upgrade head` fail on an existing object. Mandate the `DROP SCHEMA public CASCADE;
CREATE SCHEMA public;` form as the only accepted implementation.

**C-13 — DE-6(a) and DE-9a have no specified synchronisation, so both are timing-dependent.**
DE-6(a) requires the third-connection probe to run **while** the winner holds the lock; DE-9a
requires the two child processes to genuinely overlap. Neither the plan nor the checklist specifies
a hold window or a barrier. Both failure modes are noisy-RED rather than vacuous-GREEN (a probe that
runs after release returns TRUE and fails the assertion; two non-overlapping children both acquire
and `sum(acquired) == 2`), so this is flakiness, not vacuity. *Fix:* for DE-6, acquire the lock
**directly in the test** on connection 1 (`pg_try_advisory_lock(hashtext(_LOCK_KEY))` with `_LOCK_KEY`
imported), run the sweep on connection 2, probe from connection 3 — fully deterministic, no race. For
DE-9a, add a start barrier (both children wait on a row/file/`multiprocessing.Barrier`) and seed
enough lots that the critical section outlasts child startup.

**C-14 — DE-13 must seed `spendable_at <= T` or it passes for the wrong reason.** *(checklist 26.)*
`spendable_balance` (`identity_coop.py:254-261`) excludes a lot when `spendable_at > now` **as well
as** when `expires_at <= now`. A lot seeded with `expires_at = T` and a default hold
(`created_at + coop_credit_hold_hours`) is excluded from the balance because it is still *held*, not
because it expired — so the "excluded from spendable" half would be green under a broken expiry
predicate. The service docstring warns about exactly this. *Fix:* seed `spendable_at` in the past (or
monkeypatch `coop_credit_hold_hours` to 0) so the only remaining discriminator is the expiry
predicate. The `datetime` monkeypatch itself is verified sound: `identity_coop.py` does
`from datetime import date, datetime, timedelta, timezone` at module level, and both call sites
(`:254` and the sweep's `now` in `expire_lapsed_lots`) resolve through that one module attribute.

**C-15 — DE-21's guard should depend on `disposable_engine` explicitly rather than on pytest's
implicit autouse ordering.** *(checklist 12b.)* Default pytest behaviour does place a session-scoped
autouse fixture before a session-scoped requested fixture, so the guard **does** fire before any
`DROP SCHEMA` / `upgrade head` as designed — verified sound, not vacuous. But the ordering is
implicit and a future refactor could silently invert it. *Fix (hardening):* declare
`def disposable_engine(_dsn_guard): ...` so the dependency is explicit. Also note the guard fires at
fixture time, i.e. **after** `tests/conftest.py:24`'s `setdefault` and after
`models/database.py`'s import-time `create_async_engine` — that is harmless (engine creation is
lazy, no connection is opened at import) and the guard still precedes every destructive statement.

**C-16 — gate-count drift in prose.** §Overview ("DE-1 through DE-20"), the C-9 renumbering note
("`DE-1` … `DE-20`") and the Autonomous Goal Block ("gates DE-1..DE-20") all understate the range;
§Phase Completion Rules correctly says DE-1 … DE-21 (plus DE-5b, DE-9a/b, DE-16a/b). Cosmetic —
reconcile to **DE-1 … DE-21** in all four places during EXECUTE.

**C-17 — `pyproject.toml` already has a `[project.optional-dependencies] test` table.** C-8's
rationale is materially correct (there is no `[project] name`/`version` and no `[build-system]`, so
`pip install .[test]` fails), but the plan's wording "there is no `[project]` table" is imprecise —
the `test` extra already lists `pytest`/`pytest-asyncio`/`httpx`/`fakeredis`. Keeping `asgi-lifespan`
in `requirements.txt` remains the right call; also add it to that existing `test` extra so the
test-only intent is recorded where a future `[project]` fix would pick it up.

### Verified-sound (no action) — checked this cycle, explicitly not findings

- **DE-17 is expected GREEN and is correctly NOT pre-declared.** Re-verified directly:
  `apps/api/routers/sites.py` `delete_site` iterates a table list that explicitly includes
  `identity_contribution_events` **and** `identity_credit_ledger`, issuing
  `DELETE FROM {table} WHERE site_id = :sid` under the comment "H1: close the site_id-reuse gap for
  spendable co-op credit". Phase 1's H1 fix is intact. Cycle 1's R-1 ("deleting a Site orphans the
  ledger ⇒ billing defect") is **withdrawn and must not be re-propagated**. The absence of a
  ForeignKey on `identity_credit_ledger.site_id` (`models/identity_coop.py`, bare `String(50)`) is
  real but irrelevant to the router path; it stays a backlog hardening observation.
- **DE-6's fix is genuinely non-vacuous** (both legs verified RED under the stub) — the single most
  important cycle-1 repair, and it holds.
- **DE-3 / DE-4 / DE-5b**: verified against source — boot gate `if settings.identity_coop_enabled:`
  wrapping `scheduler.add_job(..., id="coop_expiry_sweep", jitter=90, misfire_grace_time=300)`, and
  the wrapper's runtime re-check with its do-not-delete comment. C-3's monkeypatch-the-settings-attr
  fix is correct: the flag is read at call time and at run time, never at import.
- **C-4 verified**: `apps/api/main.py`'s lifespan runs `Base.metadata.create_all` on the global
  engine at every boot ("harmless safety net" comment). The plan's mitigation — the migration-truth
  lane gets its own container with no lifespan boot — is the right one, and defect class 9 is
  correctly recorded as a finding rather than fixed here.
- **`asgi-lifespan` is confirmed absent** from `requirements.txt`.
- **Prod pool parity**: `models/database.py` uses `pool_size=settings.db_pool_size`,
  `max_overflow=settings.db_max_overflow` (defaults 3/2), so the lane's 3+2 pin is correct parity.
- **Section A (helper)** and **Section G (scenario 43)** pass unchanged from cycle 1.
- **Structural validator**: `node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs`
  on this plan → **0 failures, 0 warnings** (1009 lines).
- **Every path named in Touchpoints and Blast Radius resolves on disk** except the eleven files this
  plan creates. Touchpoints ⇄ Blast Radius are consistent (both carry `pyproject.toml` and
  `test_helper_guard.py`).

### Test gates

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 | Default lane byte-identical; lane never collected in the default run | Hybrid | `git diff --numstat tests/conftest.py` → 0/0; `.venv/bin/python3.11 -m pytest --collect-only -q` lists zero `tests/e2e_disposable/` items; `.venv/bin/python3.11 -m pytest tests/unit -q` and `... tests/integration -q` green | B (E-4) |
| AC-2 | Model-declared index missing from its migration is detectable | Hybrid | `pytest tests/e2e_disposable/test_migration_truth.py` + mutation probe on `b7e4d21a9c58` | A |
| AC-3 | Migrations correct on a non-empty DB (abort + happy path) | Hybrid | same file (DE-11, DE-12) | B (C-11 restore step) |
| AC-4 | Coop job registers at boot with correct interval/jitter/misfire; not when flag off | Hybrid | `pytest tests/e2e_disposable/test_lifespan_scheduler.py` + `add_job` mutation probe | A |
| AC-5 | Scheduler itself writes EXPIRE via the global session; runtime re-check short-circuits | Hybrid | same file (DE-5, DE-5b) | A |
| AC-6 | Advisory lock proven **acquired** across connections, never by row count | Hybrid | `pytest tests/e2e_disposable/test_pool_topology.py` + stubbed-lock mutation probe | B (C-13 determinism) |
| AC-7 | Two OS processes: exactly one lock winner (DE-9a) and no duplicate rows (DE-9b) | Hybrid | `pytest tests/e2e_disposable/test_two_process_replica.py` | B (E-3, C-13) |
| AC-8 | Scenario 43: lot expires despite opt-out; new accrual refused | Hybrid | `pytest tests/e2e_disposable/test_scenario_43.py` | A |
| AC-9 | Boundary / crash / aborted-txn / orphan / site-recreate semantics gated | Hybrid | `test_lifespan_scheduler.py` + `test_pool_topology.py` + `test_two_process_replica.py` | **B (E-1 orphan mutation, C-14 boundary seeding)** |
| AC-10 | Sweep scale measured against a threshold that can actually fail | Hybrid | `pytest tests/e2e_disposable/test_scale_sweep.py`; hard FAIL at round-trips > 2n + 10 | **B (E-2)** |
| AC-11 | Helper refuses non-localhost DSNs; teardown unconditional | Hybrid | `pytest tests/e2e_disposable/test_helper_guard.py` | A |
| AC-12 | A direct `pytest` cannot reach the shared dev DB or PROD | Hybrid | `pytest tests/e2e_disposable/test_helper_guard.py` DE-21 leg (needs a live non-conforming DSN to assert the refusal) | B (C-15 explicit fixture dependency) |
| K-3 | Deployed flag-ON proof | — | — | **D — known-gap residual; legally blocked pending the `coop_terms_version` re-pin** |

gap-resolution legend: A = proven now · B = fixed in this plan (via E-1 … E-4 / C-11 … C-15) ·
C = deferred to a named later plan · D = backlog test-building stub (named residual).

Note on strategies: **no row is Fully-Automated.** AC-12/DE-21 was labelled Fully-Automated in the
plan, but proving the guard *refuses* requires exporting a non-conforming DSN and observing a hard
fail, which the lane can only stage alongside the helper — it is **Hybrid**. Consequently **no TDD
failing stubs are emitted** (stubs are mandated for Fully-Automated rows only).

Legacy line form:
- migration truth: [hybrid: `pytest tests/e2e_disposable/test_migration_truth.py` + disposable PG container]
- lifespan/scheduler: [hybrid: `pytest tests/e2e_disposable/test_lifespan_scheduler.py` + disposable PG container]
- lock topology: [hybrid: `pytest tests/e2e_disposable/test_pool_topology.py` + disposable PG container]
- two-process replica: [hybrid: `pytest tests/e2e_disposable/test_two_process_replica.py` + disposable PG container + 2 child procs]
- scale: [hybrid: `pytest tests/e2e_disposable/test_scale_sweep.py` + disposable PG container]
- scenario 43: [hybrid: `pytest tests/e2e_disposable/test_scenario_43.py` + disposable PG container]
- helper guard + DSN guard: [hybrid: `pytest tests/e2e_disposable/test_helper_guard.py` + docker daemon]
- default-lane regression: [hybrid: `pytest --collect-only -q` (fully-automated) + `pytest tests/unit -q` (fully-automated) + `pytest tests/integration -q` (needs PG/Redis)]
- deployed flag-ON: [known-gap: documented — K-3, blocked on `coop_terms_version` re-pin]

Dimension findings:
- Infra fit: CONCERN — F-3/F-4 verified closed (DROP SCHEMA is clean, no extensions in the repo, root conftest genuinely 0/0/0), but `-m` deselects without preventing import (E-4), DE-11's downgrade leaves the session-scoped schema off head (C-11), and the item-10 "at minimum" fallback is strictly weaker (C-12).
- Test coverage: CONCERN — DE-6 is now genuinely falsifiable (F-1 closed), but DE-16a's mutation cannot flip its gate (E-1), DE-18's threshold is loose by ~n and blind to its stated RED condition (E-2), DE-9b's stated falsifier is wrong (E-3), DE-13 needs `spendable_at` seeding (C-14), and DE-6/DE-9a have no synchronisation (C-13).
- Breaking changes: CONCERN — the `addopts` change alters the default invocation repo-wide and DE-1(b) as written cannot detect a lane leak (E-4); `requirements.txt` ships to the prod image (C-8, accepted with rationale; C-17 refines it).
- Security surface: PASS — all five safety MUSTs remain non-negotiable in §Constraints; the shell-helper refusal plus the in-process session-scoped autouse DSN guard (localhost AND port ∉ {5432,5433,6543}) is genuine defence in depth, and it fires before any destructive statement. Worst case for a mis-invoked lane is a hard session-setup failure, not data loss. C-15 is hardening only.
- Section A (helper): PASS — C-7 closed: `test_helper_guard.py` now has a home file, a Blast Radius budget, and a run step; refusal, unconditional `trap` teardown, and the 2-pair ceiling are all specified.
- Section B (migration truth): CONCERN — C-11, C-12. The DE-2 probe itself is genuinely falsifiable once the lane builds from alembic.
- Section C (lifespan): CONCERN — C-14. C-3 (monkeypatch the settings attribute; export only `DATABASE_URL`/`REDIS_URL` before the process starts) and C-4 (own container, no lifespan boot) are both verified correct against source.
- Section D (pool topology): CONCERN — E-1 (DE-16a vacuous), C-13 (DE-6 timing). DE-6's core fix is sound; DE-16b is correctly re-labelled robustness-only.
- Section E (two-process): CONCERN — E-3 (DE-9b falsifier), C-13 (overlap barrier). DE-9a's `sum(acquired) == 1` formulation and its stated RED condition are verified correct; specify how `_try_acquire_lock`'s `None` return maps into the printed `acquired=` value.
- Section F (scale): CONCERN — E-2 (threshold and counter scope).
- Section G (scenario 43): PASS — unchanged from cycle 1; both halves constructible and falsifiable.
- Section H (wiring): CONCERN — E-4; `pyproject.toml` is now correctly present in both Touchpoints and Blast Radius.

Open gaps:
- K-3 (carried): no deployed flag-ON proof — known-gap: documented as NEW PLAN REQUIRED; legally blocked pending the `coop_terms_version` re-pin. This lane proves production *shape*, never production *deployment*.
- Live `email_validator` MX behaviour stays unproven (neutralised by the `no_mx` fixture).
- Redis is provisioned only to isolate the lane from a stray 6379; no Redis code path is under test.
- DE-18's ceiling is a stated lane ceiling, not a production SLO — production sweep volume is unmeasured.
- Production masks table-level migration divergence via the lifespan `create_all` (C-4b / defect class 9) — record as a finding; out of scope here.
- No ForeignKey on `identity_credit_ledger.site_id` — hardening observation for the backlog, **not** a live defect (DE-17 covers the router path and is expected GREEN).
- Pre-declared findings remain **DE-13, DE-18, DE-7** only. **DE-17 is explicitly not pre-declared** and cycle 1's R-1 is withdrawn.

What this coverage does NOT prove:
- `pytest tests/e2e_disposable/*` proves behaviour against a throwaway `postgres:16-alpine` on an ephemeral port. It does **not** prove behaviour against Supabase's pooler — and DE-21 structurally forbids ports 5432/5433/6543, so the lane can never exercise the `DB_POOLER_MODE` branch or `build_connect_args`'s `"supabase" in url` prepared-statement disabling. Transaction- vs session-mode pooling changes advisory-lock semantics materially.
- The two-process replica gate proves two OS processes against one DB. It does **not** prove N > 2 replicas, cross-container clock skew, or a scheduler restarted mid-sweep by a rolling deploy.
- The migration-truth gates prove the two coop indexes exist and reject duplicates after `upgrade head` on an empty and a populated DB. They do **not** prove any other model/migration pair in the repo, and they do **not** detect table-level divergence in any lane that boots the app.
- The scale gate proves round-trip and commit counts at n = 10,000 on a local container. It does **not** prove production sweep volume, contention under real concurrent write load, or statement-timeout interaction.
- The lock gates prove acquisition and refusal at the Postgres advisory-lock tier. They do **not** prove the release leg survives connection recycling — the documented accepted residual (DE-7, pre-declared).
- DE-16a (once corrected per E-1) proves the `WHERE EXISTS` guard blocks an orphan EXPIRE under an artificially divergent `site_id`. It does **not** prove the guard's *documented* scenario (a site delete cascading the ledger away), because that scenario is unreachable — there is no cascade, and deleting the ACCRUE row zeroes `_lot_remaining` before the guard is ever consulted.
- DE-1 proves the existing suites stay green and the lane is not collected. It does **not** prove the default lane executes byte-identical statements beyond the mechanical `git diff --numstat` leg.
- Nothing here proves the coop feature works with `identity_coop_enabled=true` in a deployed environment (K-3).

Gate: CONDITIONAL

This CONDITIONAL does **not** rest only on pre-declared known-gaps. It rests on:
1. **Pre-declared known-gaps / residuals:** K-3 (deployed flag-ON, gap-resolution D), DE-13
   (boundary), DE-18 (scale shape), DE-7 (unlock on a recycled connection), live MX behaviour,
   Redis non-coverage, defect class 9, and the missing `identity_credit_ledger.site_id` FK.
2. **Four binding execute-agent corrections — E-1, E-2, E-3, E-4 — which MUST be applied to the
   plan text before the corresponding gate is implemented.** Each names a gate that, as currently
   worded, passes on the implementation it exists to forbid. Implementing DE-16a, DE-18, DE-9b, or
   the `addopts` exclusion as written would produce vacuous evidence, and the associated mutation
   probe would record a false non-vacuity proof.
3. **Six precision fixes — C-11 … C-17** (schema restore after DE-11, mandate DROP SCHEMA,
   synchronisation for DE-6/DE-9a, `spendable_at` seeding for DE-13, explicit guard ordering,
   DE-1…DE-21 prose reconciliation, the existing `test` extra).

Accepted by: **PENDING** — not accepted by this agent. Per the cycle-2 STOP-BLOCK this agent does
not self-accept its own CONDITIONAL verdict. The orchestrator/user must either (a) accept this
CONDITIONAL with E-1 … E-4 carried as binding execute-agent instructions, or (b) run PVL supplement
cycle 2 to fold E-1 … E-4 and C-11 … C-17 into the plan text and re-validate.

---

## Autonomous Goal Block

```
SESSION GOAL: Build the disposable-container coop e2e lane (8 infra items, gates DE-1..DE-21) so identity-coop Phase 1 + Phase 2a are exercised in production shape — alembic-built schema, real ASGI lifespan, prod-parity pool, two OS processes.
Charter + umbrella plan: N/A — single plan, one phase (not a phase program). Sibling program umbrella: process/features/visitors-identity/active/identity-coop_07-08-26/identity-coop-umbrella_PLAN_07-08-26.md (informational only).
Autonomy: standing consent for reversible test-infra edits under tests/, scripts/, requirements.txt, pyproject.toml. Auto-proceed on all gate/fix cycles. Blocked items -> backlog NOTE in this task folder, continue.
Hard stop conditions / safety constraints:
- Never run an alembic or DB command without DATABASE_URL pinned inline to the disposable DSN. The repo dotenv points at Supabase PRODUCTION and migrations/env.py has no local-host guard.
- The helper script must refuse any non-localhost DSN without --allow-remote; an unparseable host also refuses.
- Container teardown is unconditional (trap ... EXIT INT TERM). Never leave an e2e-* container running.
- Max 2 concurrent container pairs. Lanes run one at a time by default.
- Never edit the repo dotenv. Never flip a repo-default-OFF flag globally — per-process/per-test only.
- Do not start Section B while another agent is running against tests/conftest.py.
- No edits to apps/api/** . A gate that goes RED against current source is a FINDING to report, never a licence to change the service.
- Every mutation probe must be reverted and re-run GREEN before the section closes.
Next phase: PVL re-run from V1. Supplement cycle 1 applied 17-08-26 — all 15 gaps (F-1..F-5, C-1..C-10) addressed in plan text. EXECUTE is still not authorised until re-validation returns PASS or an explicitly accepted CONDITIONAL.
Validate contract: inline in this plan (## Validate Contract), Gate: BLOCKED as of 17-08-26 — stale, superseded by supplement cycle 1; the validate agent owns rewriting it.
Execute start: (not yet authorised) — after re-validation, start with Section A (scripts/e2e-disposable.sh, fully independent), then Section H's pyproject.toml exclusion (DE-1 must run AFTER it), then Section B (tests/conftest.py is now zero-diff, so the old EVL blocker no longer applies to it). High-risk pack: no.
Standing rule: no gate may assert a lock, guard, or ordering property by row count alone — row counts are lock-blind (ON CONFLICT DO NOTHING + uq_coop_ledger_expire_per_lot).
```
