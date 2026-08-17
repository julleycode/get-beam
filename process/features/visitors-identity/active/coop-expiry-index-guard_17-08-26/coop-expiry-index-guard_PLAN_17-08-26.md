---
name: plan:coop-expiry-index-guard
description: "Turn the silent co-op expiry failure caused by a missing uq_coop_ledger_expire_per_lot index into a loud, fail-closed error (F-B guard)"
date: 17-08-26
feature: visitors-identity
---

# Co-op Expiry Index Guard (F-B) — SIMPLE Plan

**TL;DR** — `expire_lapsed_lots`' `ON CONFLICT (lot_id) WHERE entry_type = 'EXPIRE'` needs the partial
unique index `uq_coop_ledger_expire_per_lot`. Without it, **every** insert raises, the mandated per-lot
`except Exception` (C-1) swallows it, and the sweep returns "success" having expired nothing. Fix =
two small fail-closed guards in the co-op service layer + four falsifiable gates. No schema change, no
flag flip, no new migration.

**Date**: 17-08-26
**Status**: PLANNED, VALIDATED, not executed — PVL is complete. Cycle-2 contract returned
`Gate: CONDITIONAL`; its four CONCERNs (A caller-inventory accuracy, B raising-leg exception type,
C G5 leg (a) DSN binding, D Goal 4 scoping) were transcribed into this plan body as E1-E5 by
supplement cycle 2 on 17-08-26. **EXECUTE is licensed** on that accepted-CONDITIONAL basis; no
source file has been touched yet.
**Complexity**: SIMPLE — 8 checklist steps, 2 source files touched (+2 new test files), ~65 source lines.
**Feature**: visitors-identity

### Phase Completion Rules

This is a single-phase SIMPLE plan; the rules below are the completion bar for it.

| Status | Meaning |
|---|---|
| `PLANNED` | Plan written. No source touched. Current state. |
| `CODE DONE` | Checklist steps 1-8 applied; unit gates (G3, G6, G7) green. **Not** a completion state. |
| `✅ VERIFIED` | CODE DONE **plus** every Hybrid gate (G1, G2, G4, G5, G8-integration, G8-disposable) run green on a disposable Postgres, **plus** both mandatory mutation probes (G1's guard-line removal, G4's `failures += 1` removal) observed RED, **plus** User Confirmation — the user has confirmed working. Absent explicit user-confirmed sign-off the status stays `CODE DONE`. |

Hard rules:
- A gate that stays green under its named mutation is **invalid** — rewrite it; do not accept it.
- `CODE DONE` is never reported as done. Only `✅ VERIFIED` closes this plan.
- **`✅ VERIFIED` here means *proven on a disposable Postgres only*.** Production behaviour on the
  first `identity_coop_enabled` flip is unproven by every tier in this plan. Flag-OFF-only evidence
  is vacuous (ip-org G8/G10; the icp_fit silent no-op survived 4 PVL + 2 EVL passes on exactly this
  kind of evidence). Do not read `✅ VERIFIED` as "safe in prod".
- Testing context: read `process/context/tests/all-tests.md` and its routing chain before running any
  gate. Post-phase testing (the EVL confirmation re-run of every gate command by an independent
  tester) is required before UPDATE PROCESS — the execute agent's own green run does not substitute.

---

## Overview

### The finding (F-B), verified twice

`apps/api/services/identity_coop.py:515-529` (`_EXPIRE_INSERT_SQL`) ends with:

```
ON CONFLICT (lot_id) WHERE entry_type = 'EXPIRE' DO NOTHING
```

That inference clause requires the partial unique index `uq_coop_ledger_expire_per_lot`
(created by migration `b7e4d21a9c58_add_coop_expire_unique.py`). If the index is absent, PostgreSQL
cannot infer an arbiter and **every** insert raises:

```
asyncpg.exceptions.InvalidColumnReferenceError:
  there is no unique or exclusion constraint matching the ON CONFLICT specification
```

`identity_coop.py:604-607`'s per-lot `except Exception` — added as C-1 in the Phase 2a plan so one bad
lot cannot wedge the tick — catches it, logs `coop_expire_lot_failed`, and `continue`s. The loop
finishes, `expire_lapsed_lots` returns `written = 0`, `run_coop_expiry_sweep` returns `0`, the
scheduler wrapper logs nothing at all. **The sweep completes "successfully" having expired nothing** —
a silent failure on a billing surface, observable only as per-lot log spam nobody is watching.

Evidence: EVL confirmation run 17-08-26 observed the exact exception and the swallowed-log behaviour
on a disposable Postgres with the index dropped —
`process/features/visitors-identity/active/coop-disposable-e2e_17-08-26/harness/evl-lane-confirmation-17-08-26.json`.
The execute agent independently observed the same class earlier.

### Why this is live risk, not theoretical

`b7e4d21a9c58` has **never been applied to production** (`identity_coop_enabled` has never been ON
anywhere). The first real environment to run this sweep will be the first test of whether the index is
present. There is currently no mechanism that would tell anyone it is not.

### User decision (17-08-26)

Build the **startup assertion**: turn the silent failure into a loud one. Chosen over a backlog note
and over folding it into Phase 2b.

---

## Design Decisions (all four decided — nothing left open)

### D1 — Where the guard lives: **the sweep entrypoint** (`run_coop_expiry_sweep`)

| Candidate | Verdict | Why |
|---|---|---|
| App startup (`apps/api/main.py` lifespan) | **Rejected** | Two independent blockers. (a) **Blast radius**: a missing index would fail the boot of the *entire* API for a feature that is default-OFF and has never run anywhere. (b) **Plumbing**: `start_scheduler()` (`scheduler.py:615`) is **sync** and takes no session; an async `pg_indexes` probe cannot run there without either making it async or opening a second sync connection at boot. Both are more change than the guard itself. |
| Scheduler registration (`scheduler.py:743`, inside `if settings.identity_coop_enabled:`) | **Rejected** | Correct blast radius (flag-gated), but blocked by the same sync-`start_scheduler` plumbing problem, and it only covers the *registration* path — it misses a runtime flag flip in a process that booted flag-OFF, and misses every direct caller (`_replica_child.py`, disposable-lane tests, any future Celery/CLI trigger). |
| **Sweep entrypoint (`run_coop_expiry_sweep`)** | **CHOSEN** | Already `async`, already holds an `AsyncSession` — **zero new plumbing**. Covers all three entry paths uniformly (scheduler registration, in-wrapper runtime-flip check at `scheduler.py:317`, and direct callers). Runs before the advisory lock, so a guard trip never leaks a lock. Self-healing: if the index appears later (operator applies `b7e4d21a9c58`), the next tick proceeds with no restart. Cheapest of the three (one indexed catalog query, cached per process). |

**Flag-interaction note (why this is not a boot check):** with `identity_coop_enabled` OFF the job is
never registered at all (`scheduler.py:743`), so a boot-time check would fire on every deployment that
never intended to run the sweep — including every deployment that exists today. Guarding at the sweep
entrypoint means the check runs **exactly when someone actually tries to expire credits**, which is the
only moment the index matters.

**Loudness compensation.** The sweep entrypoint is one layer below the scheduler, so the guard's raise
surfaces via `_coop_expiry_sweep_job`'s existing `logger.exception("coop_expiry_sweep_crashed")`
(`scheduler.py:325`). To make that distinguishable from ordinary crashes the guard also emits its own
dedicated `logger.error("coop_expiry_index_missing", ...)` before raising, and raises a **named**
exception type — not a bare `Exception`. Two distinct, greppable events on a billing surface. D4
(below) is the belt to this brace. Both new ERROR events are gate-asserted (G1, G4, G5) — emission is
part of the deliverable, not a side effect.

### D2 — Fail-closed (raise), not fail-loud-and-skip

**Decision: fail-closed. The guard raises.**

Repo precedent for money/PII surfaces is fail-closed: `validate_production` fails startup on missing
prod encryption keys; `scripts/refresh_ip_org.py` refuses a non-local DSN unless `--allow-remote`, and
an unparseable DSN refuses rather than proceeds.

Rationale specific to F-B: log-at-ERROR-and-skip produces exactly the same *observable outcome as the
bug* — a sweep that ran and expired nothing. The only difference would be the log line, and "the log
line nobody watched" is the failure mode being fixed. A raise propagates a non-zero-signal event to the
wrapper's `logger.exception`, which carries a stack trace and a distinct event name.

Explicit non-goal: the raise must **not** be allowed to wedge the scheduler. It is caught by the
existing wrapper try/except, so the process stays healthy and the next tick retries — which is what
makes the self-healing property in D1 work.

**Deliberate asymmetry with the advisory lock:** `_try_acquire_lock` returns `None` on error and the
sweep proceeds (fail-OPEN), because a duplicate sweep is harmless. That precedent does **not** transfer
here: a missing index is not a benign degradation, it is a total functional failure. Recorded so a
future reader does not "harmonise" the two.

### D3 — How the check is performed

Exact predicate (one indexed catalog lookup, `pg_indexes` — same shape the disposable lane's
`_index_exists` helper already uses, so the gate and the guard agree on the definition of "present"):

```sql
SELECT 1 FROM pg_indexes
WHERE schemaname = current_schema()
  AND tablename  = 'identity_credit_ledger'
  AND indexname  = 'uq_coop_ledger_expire_per_lot'
```

`tablename` is pinned as well as `indexname` so an unrelated index of the same name on another table
cannot satisfy the guard.

**Caching: positive-only, once per process.** A module-level `_index_verified: bool = False` in
`coop_expiry_sweep.py`. Set to `True` on the first successful check and never re-queried thereafter
(cost: one query per process lifetime). A **negative** result is never cached — every subsequent tick
re-queries, which is precisely what delivers D1's self-healing property when an operator applies
`b7e4d21a9c58` to a running fleet.

**Test-hygiene consequence (do not skip this):** `_index_verified` is *process*-lifetime state, not
per-test state. Any test that runs the sweep against a healthy schema poisons it `True` for every
later test in the same pytest process — including, most dangerously, G2 poisoning G1 inside the same
new file. Every guard-dependent gate must therefore start from a **cold cache**; see checklist step 8's
mandatory autouse fixture.

Errors querying `pg_indexes` itself (connection dead, permissions) are **not** treated as "index
present": they propagate, matching D2.

### D4 — The per-lot `except Exception`: keep it, add a systemic-failure abort

**Decision: do NOT narrow the exception type. Add an all-lots-failed abort instead.**

Narrowing to e.g. `IntegrityError` was considered and rejected: C-1's whole purpose is that *any*
unforeseen per-lot fault must not wedge the tick, and the specific exception here
(`InvalidColumnReferenceError`, wrapped by SQLAlchemy as `ProgrammingError`) is not the only systemic
fault that can present per-lot. Narrowing swaps one silent-failure class for another.

Instead: `expire_lapsed_lots` counts failures. When **every** lot the loop actually processed failed,
the systemic explanation is overwhelmingly more likely than "all N lots are individually bad", so the
function raises `CoopExpirySystemicFailure` after the loop instead of returning `0`.

Properties this buys:
- No threshold to tune, no config knob — the predicate is "all of them".
- A **single** bad lot in a batch of 2+ still logs-and-continues exactly as C-1 requires.
- It fires **even if the D1/D3 index guard is bypassed** (guard removed, index dropped mid-tick,
  a different systemic fault entirely). This is the independent second layer.
- A batch of exactly 1 processed lot that fails does raise. Accepted: on a billing surface, "the only
  lot we tried to expire failed" is worth surfacing, and the wrapper contains the blast radius.

#### The real loop shape (verified against source — an earlier draft of this section was wrong)

An earlier revision of this plan claimed *"lots skipped for `remaining == 0` are `continue`d before the
try body"*. **That is false, and the counter design must not be derived from it.** The actual loop
(`identity_coop.py:585-607`) puts both the `_lot_remaining` round-trip and the skip **inside** the try:

```
lot_id_str = str(lot_id)          # the only statement before the try
try:
    remaining = max(0, await _lot_remaining(db, lot_id))   # DB round-trip, INSIDE the try
    if remaining == 0:
        continue                                            # the skip, INSIDE the try
    ... insert ... await db.commit() ... written += rowcount
except Exception:                 # noqa: BLE001 — C-1, must not be narrowed
    await db.rollback()
    logger.exception("coop_expire_lot_failed", lot_id=lot_id_str)
    continue
```

Consequence for counter placement: if `attempted` were incremented *after* the `remaining == 0`
`continue`, a lot whose `_lot_remaining` itself raises — dead session, **pool exhaustion on the
prod-parity 3+2 pool**, aborted transaction, permission denied — would increment `failures` but
**never** `attempted`. A batch where every lot fails that way yields `attempted == 0, failures == N`;
the predicate `attempted >= 1 and failures == attempted` is **False**; nothing raises. That is exactly
the silent sweep this plan exists to abolish, it contradicts Goal 2 ("a systemic every-lot failure of
**any** cause surfaces"), and it makes `failures > attempted` naturally reachable — a state G3
otherwise treats as a mis-implementation signature. The F-B case itself is unaffected (there
`_lot_remaining` succeeds and the *insert* raises), which is precisely why this hole would survive
every gate unless deliberately targeted (G3 leg (e) does).

**Therefore three counters, with `attempted` incremented at the TOP of the loop body, before the `try`:**

| Counter | Incremented | Meaning |
|---|---|---|
| `attempted` | first statement of the loop body, **before** the `try` | every lot the loop entered — so a pre-attempt fault is still counted |
| `skipped` | on the `remaining == 0` branch, immediately before its `continue` | lots deliberately not processed (already zero-remaining) |
| `failures` | inside the existing `except Exception`, after `logger.exception` | lots that faulted for any reason, at any point in the try |

Abort predicate:

```
processed = attempted - skipped
if processed >= 1 and failures == processed:
```

This is behaviourally identical for every case the old `attempted >= 1 and failures == attempted` form
handled correctly, and additionally: closes the pre-attempt-failure class, and makes
`failures > processed` structurally impossible (every failure is inside a lot that incremented
`attempted` and did not reach the `skipped` branch).

---

## Goals

1. A missing `uq_coop_ledger_expire_per_lot` makes the co-op expiry sweep fail **loudly and
   identifiably**, instead of silently returning `0`.
2. A systemic every-lot failure of any cause surfaces, even without the index guard — including a
   fault that occurs *before* the insert is attempted (D4).
3. The healthy path is unchanged: same rows written, same return value, one extra catalog query per
   process.
4. C-1's single-bad-lot isolation **inside the loop** is preserved verbatim (rollback + log +
   continue, unchanged); the all-processed-failed abort is a post-loop addition (D4).

## Non-Goals / Out of Scope

- No schema change and no new migration — the index already exists in `b7e4d21a9c58`.
- No flag flip; `identity_coop_enabled` stays default OFF.
- No change to `spendable_balance`'s query (frozen).
- No change to `identity_resolver.py` (diff must stay empty).
- No boot-time / `main.py` check (rejected in D1).
- No new alembic guard in `migrations/env.py` (tracked separately in the ip-org follow-ups note).
- Not fixing the advisory-lock pool-connection residual (accepted, documented in
  `run_coop_expiry_sweep`'s docstring).

---

## Touchpoints

| File | Change | Diff budget |
|---|---|---|
| `apps/api/services/coop_expiry_sweep.py` | Add `CoopExpiryIndexMissing`, `_EXPIRE_INDEX_NAME`, `_index_verified` module cache, `assert_expire_index(db)`; call it at the top of `run_coop_expiry_sweep` **before** `_try_acquire_lock`. | **≤ 50 added lines**, 1 added call line in `run_coop_expiry_sweep` |
| `apps/api/services/identity_coop.py` | Add `CoopExpirySystemicFailure`; add `attempted`/`skipped`/`failures` counters in `expire_lapsed_lots`; raise after the loop when `processed >= 1 and failures == processed`. | **≤ 25 added lines, 0 lines deleted**. The `except Exception` block body is unchanged apart from one `failures += 1`; the `remaining == 0` branch gains one `skipped += 1`. |
| `tests/e2e_disposable/test_expiry_index_guard.py` | **New file** — gates G1, G2, G4, G5 (see Verification Evidence), plus the mandatory cold-cache autouse fixture. Reuses the existing `at_pre_expire_unique` fixture pattern. | ≤ 200 lines |
| `tests/unit/test_coop_expiry_guard.py` | **New file** — gate G3 (systemic abort logic, no DB), 5 legs. | ≤ 150 lines |
| `apps/api/jobs/scheduler.py` | **READ ONLY** — no edit. Referenced for the wrapper's existing `except`. | 0 |
| `apps/api/services/identity_resolver.py` | **FROZEN** — diff must be empty. | 0 |
| `apps/api/models/identity_coop.py` | **READ ONLY** — the ORM mirror of the partial unique index at `:141` is what keeps the integration lane safe (see Risks). Do not remove it. | 0 |

**Read for context (no edit):** `apps/api/migrations/versions/b7e4d21a9c58_add_coop_expire_unique.py`,
`tests/e2e_disposable/conftest.py`, `tests/e2e_disposable/test_migration_truth.py`,
`apps/api/models/identity_coop.py:141`.

## Public Contracts

| Contract | Before | After | Breaking? |
|---|---|---|---|
| `run_coop_expiry_sweep(db) -> int` | Returns rows written; never raises for a missing index | Same signature; may now raise `CoopExpiryIndexMissing` | No. Full caller inventory below; all are either inside a try/except or run against a schema where the index is present. |
| `expire_lapsed_lots(db) -> int` | Returns rows written; never raises | Same signature; may now raise `CoopExpirySystemicFailure` | No. Single-lot-failure behaviour in a multi-lot batch is byte-identical; the all-failed case is the intended new behaviour. |
| DB schema | — | **unchanged** | No |
| HTTP/API surface | — | **unchanged** | No |
| Config / flags | — | **unchanged**; no new setting | No |
| Log events | `coop_expire_lot_failed` | + `coop_expiry_index_missing` (ERROR), + `coop_expiry_all_lots_failed` (ERROR) | Additive |

**Full caller inventory of `run_coop_expiry_sweep` (enumerated: 8 call statements, 7 non-scheduler):**

| Caller | Schema source | Safe because |
|---|---|---|
| `apps/api/jobs/scheduler.py:~320` (`_coop_expiry_sweep_job`) | prod / any | Already wrapped in `except Exception: logger.exception("coop_expiry_sweep_crashed")` (`:324-325`) |
| `tests/e2e_disposable/_replica_child.py:69` | `alembic upgrade head` | index present ⇒ guard is a no-op |
| `tests/e2e_disposable/test_pool_topology.py:110`, `:157` | `alembic upgrade head` | same |
| `tests/e2e_disposable/test_scale_sweep.py:88` | `alembic upgrade head` | same |
| `tests/e2e_disposable/test_lifespan_scheduler.py:280` | `alembic upgrade head` | same |
| `tests/integration/test_identity_coop_ledger.py:617`, `:634` | **`Base.metadata.create_all` — NOT alembic** | The partial unique index is **mirrored in the ORM** at `apps/api/models/identity_coop.py:141` (`__table_args__`, `postgresql_where=text("entry_type = 'EXPIRE'")`), so `create_all` does create it. **This, not "runs alembic", is the reason the integration lane is safe.** Removing that `Index(...)` from `__table_args__` would break this lane loudly — which is a feature, not a hazard. |

New exception types are exported from their defining modules; nothing else imports them except the
new tests and (already-existing) generic `except Exception` handlers.

## Blast Radius

- **Files changed:** 2 source + 2 new test files. **Zero** existing test files modified.
- **Packages:** `apps/api/services` only.
- **Risk class:** **billing / credits** (high-risk class — co-op credit ledger). Per
  `vc-test-coverage-plan`, high-risk class ⇒ minimum Hybrid tier gate; satisfied by G1/G2/G4/G5 below.
- **Runtime reachability:** all new code is reachable **only** from the co-op expiry sweep, which is
  registered only when `identity_coop_enabled` is True — currently ON in no environment. Flag-OFF
  behaviour change is provably nil (nothing calls into it). **That same fact is why no gate in this
  plan can prove prod behaviour** — see Phase Completion Rules and Known Gaps.
- **Rollback:** revert the two source diffs. No data written, no schema touched, no migration.

---

## Implementation Checklist

1. **`apps/api/services/coop_expiry_sweep.py`** — add module constants and exception:
   `_EXPIRE_INDEX_NAME = "uq_coop_ledger_expire_per_lot"`, `_EXPIRE_INDEX_TABLE =
   "identity_credit_ledger"`, `_index_verified: bool = False`, and
   `class CoopExpiryIndexMissing(RuntimeError)` with a docstring stating why this is fail-closed
   (cite D2 + the `validate_production` precedent) and why it is deliberately NOT fail-open like
   `_try_acquire_lock`.

2. **`coop_expiry_sweep.py`** — add `async def assert_expire_index(db: AsyncSession) -> None`:
   return immediately when the module-level `_index_verified` is True; otherwise run the exact D3
   `pg_indexes` predicate; on hit set `_index_verified = True` and return; on miss call
   `logger.error("coop_expiry_index_missing", index=_EXPIRE_INDEX_NAME, table=_EXPIRE_INDEX_TABLE)`
   and `raise CoopExpiryIndexMissing(...)` with a message naming the index, the migration revision
   `b7e4d21a9c58`, and the consequence ("ON CONFLICT cannot infer an arbiter; every EXPIRE insert
   would fail silently"). Do **not** wrap the catalog query in try/except — a query error propagates
   (D3). Add a comment stating that the negative result is deliberately not cached, **and** that the
   positive cache is process-lifetime so tests must reset `_index_verified` (step 8).

3. **`coop_expiry_sweep.py`** — call `await assert_expire_index(db)` as the **first** statement of
   `run_coop_expiry_sweep`, strictly **before** `_try_acquire_lock`, so a guard trip cannot leak an
   advisory lock. Extend the function docstring with a two-sentence note on why the guard sits here
   and not at boot (D1) — future readers must not "move it up" to `main.py`.

4. **`apps/api/services/identity_coop.py`** — add `class CoopExpirySystemicFailure(RuntimeError)`
   near the top with a docstring citing D4: it exists because C-1's per-lot `except Exception` is
   load-bearing and must NOT be narrowed, so the systemic case is detected by counting instead.

5. **`identity_coop.py` `expire_lapsed_lots`** — initialise `attempted = 0`, `skipped = 0`,
   `failures = 0` alongside `written = 0`. Then, **matching the real loop shape documented in D4**:
   - increment `attempted` as the **first statement of the loop body, BEFORE the `try`** (next to the
     existing `lot_id_str = str(lot_id)` snapshot). It must NOT be placed after the `remaining == 0`
     `continue` — that skip lives *inside* the try, and placing the increment after it re-opens the
     pre-attempt-failure hole D4 describes.
   - increment `skipped` on the `remaining == 0` branch, immediately before its `continue`.
   - add `failures += 1` inside the existing `except Exception` block, after the `logger.exception`
     and before `continue`.
   **Do not otherwise modify the except block, and do not narrow its exception type.**

6. **`identity_coop.py` `expire_lapsed_lots`** — after the loop, before `return written`:
   ```
   processed = attempted - skipped
   if processed >= 1 and failures == processed:
       logger.error("coop_expiry_all_lots_failed", processed=processed, skipped=skipped)
       raise CoopExpirySystemicFailure(...)
   ```
   Message must state the count and the likely cause (missing `uq_coop_ledger_expire_per_lot`, or a
   dead session / exhausted pool). Update the function docstring: state that a single failed lot in a
   multi-lot batch still logs-and-continues, that an all-processed-lots-failed batch aborts, and that
   `skipped` lots are excluded from both sides of the predicate.
   **Docstring-edit caution (G6):** `spendable_balance` is referenced at `identity_coop.py:547`, inside
   this very docstring. Keep that mention byte-identical — G6 greps for added/removed lines containing
   it.

7. **`tests/unit/test_coop_expiry_guard.py`** (new) — gate G3. No DB. Drive `expire_lapsed_lots` with
   a stubbed session whose `execute` raises for a chosen subset of lots.

   **MANDATORY (E2) — typed assertions and a shape-aware stub; do not relax either:**
   - **Every raising leg uses `pytest.raises(CoopExpirySystemicFailure)` explicitly — never bare
     `Exception`.** This binds legs (b), (d) and (e), not only (b).
   - **The stub must let the initial lapsed-lot `SELECT` succeed**, raising only from `_lot_remaining`
     onward (three distinct `execute` shapes: lapsed-lot select `.all()`, `_lot_remaining`
     `.scalar_one()`, the `text(_EXPIRE_INSERT_SQL)` insert `.rowcount`).
   Why (so nobody relaxes it later): `expire_lapsed_lots` runs its lapsed-lot `SELECT` at
   `identity_coop.py:563-576` **outside any try**, so a naive stub that raises on any `execute` raises
   there and propagates a **raw** exception — and because `CoopExpirySystemicFailure` IS an
   `Exception`, a leg written as `pytest.raises(Exception)` would pass against the exact FAIL-1 bug it
   exists to forbid.

   **Five legs:**
   (a) 3 lots, 1 EXPIRE insert fails ⇒ returns 2, **no** raise;
   (b) 3 lots, all 3 fail ⇒ raises `CoopExpirySystemicFailure`;
   (c) 0 lapsed lots ⇒ returns 0, no raise;
   (d) **mixed batch** — 1 lot with `remaining == 0` + 1 lot whose EXPIRE insert raises ⇒ **MUST**
       raise (this is the only leg that can falsify skip-exclusion; legs (a)-(c) cannot);
   (e) **pre-attempt failure** — 2 lots whose `_lot_remaining` raises ⇒ **MUST** raise (the FAIL-1
       regression gate: RED against the old `attempted >= 1 and failures == attempted` predicate with
       a post-skip increment, GREEN against step 5/6's corrected form).

8. **`tests/e2e_disposable/test_expiry_index_guard.py`** (new) — gates G1, G2, G4, G5. Reuse the
   existing lane fixtures (`disposable_engine`, `disposable_dsn`, `disposable_db`, `clean_coop`,
   `coop_on`) and helper coroutines (`seed_lapsed_lot`, `expire_row_count`), and **copy the
   `at_pre_expire_unique` fixture pattern from `test_migration_truth.py:145-166` verbatim** —
   including the `finally:` restore to `alembic upgrade head` and its post-restore `_index_exists`
   assertion, which is what stops a downgraded DB from silently making every later test in the session
   vacuous (C-11). Mark `pytestmark = pytest.mark.disposable`. Every alembic invocation goes through
   the lane's `alembic_or_raise(disposable_dsn, ...)`, which pins the DSN — never a bare `alembic` call.

   **MANDATORY — cold-cache autouse fixture (do not omit; this file is the one place G2 can poison
   G1):**
   ```
   @pytest.fixture(autouse=True)
   def _cold_index_cache(monkeypatch):
       monkeypatch.setattr(coop_expiry_sweep, "_index_verified", False)
   ```
   Rationale: `_index_verified` is process-lifetime (D3). Without this, G2 (healthy schema) sets it
   `True` and G1 then returns early instead of raising — G1 goes RED for the wrong reason, and G1's
   mandatory mutation probe is **already RED before the mutation**, recording a false non-vacuity
   proof. G5 leg (b) likewise requires a cold cache at entry. Every guard-dependent gate in this plan
   assumes a cold cache; state that in the file's module docstring too.

---

## Acceptance Criteria

- **AC-1** — With `uq_coop_ledger_expire_per_lot` absent, `run_coop_expiry_sweep` raises
  `CoopExpiryIndexMissing`, emits `coop_expiry_index_missing`, and writes **zero** ledger rows.
  *proven by:* G1 — `strategy: Hybrid`
- **AC-2** — With the index present, `run_coop_expiry_sweep` behaves exactly as today: guard is a
  no-op, correct EXPIRE rows written, no new exception. *proven by:* G2 — `strategy: Hybrid`
- **AC-3** — The systemic abort discriminates all-processed-failed from one-failed, from
  all-skipped, from mixed skip+fail, and fires on pre-attempt failures. *proven by:* G3 —
  `strategy: Fully-Automated`
- **AC-4** — The systemic abort fires on a real missing-index database **even when the index guard is
  monkeypatched out**, emitting `coop_expiry_all_lots_failed`, proving the two layers are independent.
  *proven by:* G4 — `strategy: Hybrid`
- **AC-5** — The guard raise never wedges the scheduler: `_coop_expiry_sweep_job` swallows it (both
  `coop_expiry_index_missing` and `coop_expiry_sweep_crashed` observed) and the next tick retries;
  when the index is restored the sweep proceeds without a process restart (positive-only cache, D3).
  *proven by:* G5 — `strategy: Hybrid`
- **AC-6** — `identity_resolver.py` diff is empty and `spendable_balance`'s query is byte-identical.
  *proven by:* G6 — `strategy: Fully-Automated`
- **AC-7** — No schema change: `alembic heads` is unchanged and no new file exists under
  `apps/api/migrations/versions/`. *proven by:* G7 — `strategy: Fully-Automated`

---

## Verification Evidence

Every gate names the broken implementation that turns it RED. This program has had **eight**
recurrences of a gate that passed on the implementation it existed to forbid (most recently a lock
probe that passed because it drew from the same connection pool) — so each row below carries an
explicit mutation, and G1 and G4 are *mutation-proven*, not merely asserted. **No row may be a bare
"did not raise" assertion.**

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| **G1 — guard FIRES when the index is absent.** In `tests/e2e_disposable/test_expiry_index_guard.py` (cold `_index_verified` via the step-8 autouse fixture), under the `at_pre_expire_unique` fixture (alembic downgrade to `a8c2f47e91b6`, restore guaranteed in `finally`): seed ≥1 lapsed ACCRUE lot, then inside `structlog.testing.capture_logs()` wrap `run_coop_expiry_sweep(db)` in `pytest.raises(CoopExpiryIndexMissing)`; assert the captured events include **`coop_expiry_index_missing`** (this is what proves the *guard* fired rather than some other failure), **and** assert `expire_row_count == 0` for that lot afterwards. **Corrected RED mechanism (supersedes the earlier narrative):** with D4 in place, deleting the guard does **not** make the call return `0` — the code then raises `CoopExpirySystemicFailure` instead. G1 still goes RED (the two classes are `RuntimeError` *siblings*, so `pytest.raises` isinstance-matching does not cross-match — verified), so the gate is valid; but the probe alone no longer distinguishes "guard works" from "D4 works", which is why the log assertion above is load-bearing. **Mandatory mutation probe 1 (run and record):** delete the `await assert_expire_index(db)` line — MUST go RED. **Mandatory mutation probe 2 (run and record):** delete that line **and** the `failures += 1` line together — this is the mutation that reproduces the true pre-fix `return 0` silent behaviour, and MUST go RED. A gate that stays green under either mutation is invalid and must be rewritten before it is accepted. | Hybrid — precondition: disposable Postgres via `scripts/e2e-disposable.sh` | AC-1 |
| **G2 — guard does NOT fire in the healthy case.** Same file, default (post-`upgrade head`) schema: seed one lapsed lot, call `run_coop_expiry_sweep`, assert it returns `1`, assert `expire_row_count(lot) == 1`, and assert the amount equals `-remaining`. Second leg: call it a second time and assert it returns `0` and still `expire_row_count == 1` (idempotence preserved). **Turns RED when:** the guard's `pg_indexes` predicate is wrong (e.g. `schemaname` pinned to a schema that does not exist, or `tablename` misspelled) so it raises on a healthy DB. **Second mutation:** flip the guard's hit/miss branches — must go RED. **Ordering note:** G2 must not be relied on to run after G1 — the autouse cold-cache fixture makes intra-file order irrelevant, which is the point of mandating it rather than trusting alphabetical collection. | Hybrid — same precondition | AC-2 |
| **G3 — systemic abort discriminates all-failed from one-failed, all-skipped, mixed, and pre-attempt.** `tests/unit/test_coop_expiry_guard.py`, no DB. Stub session; **five** legs: (a) 3 lots / 1 raising ⇒ returns 2, no exception; (b) 3 lots / 3 raising ⇒ `pytest.raises(CoopExpirySystemicFailure)`; (c) 0 lapsed lots ⇒ returns 0, no exception; **(d) mixed batch — 1 lot with `remaining == 0` + 1 lot whose insert raises ⇒ MUST raise**; **(e) 2 lots whose `_lot_remaining` raises before any insert ⇒ MUST raise**. **Turns RED when:** the predicate is written as `failures >= 1` (leg (a) then wrongly raises); as `failures > processed` (leg (b) then wrongly passes); **when `skipped` is not subtracted — leg (d) then computes `processed = 2, failures = 1` and wrongly does NOT raise** (legs (a)-(c) all stay green under this bug, which is why (d) exists); or **when `attempted` is incremented after the `remaining == 0` continue — leg (e) then computes `processed = 0` and wrongly does NOT raise** (the FAIL-1 hole; every other leg stays green under it). Note the corrected direction: miscounting skips causes an **under**-fire, not a spurious raise. | Fully-Automated — `.venv/bin/python3.11 -m pytest tests/unit/test_coop_expiry_guard.py` | AC-3 |
| **G4 — the two layers are independent.** Same disposable file, under `at_pre_expire_unique`, with the guard neutralised at a **named** site: `monkeypatch.setattr(coop_expiry_sweep, "assert_expire_index", _noop)` (module-global lookup at call time; alternatively poison the positive cache with `monkeypatch.setattr(coop_expiry_sweep, "_index_verified", True)` — state which one the test uses). Seed **2** lapsed lots, call `run_coop_expiry_sweep` inside `capture_logs()`, assert `pytest.raises(CoopExpirySystemicFailure)` **and** that `coop_expiry_all_lots_failed` was emitted. **This is the gate that proves the fix does not depend on a single point.** **Turns RED when:** the systemic counter is never incremented, the abort is placed inside the loop instead of after it, or the fix relies solely on the index guard. Asserting the exception *type* (not merely "something raised") is what catches a wrong patch site — a mis-patched guard raises `CoopExpiryIndexMissing` and the gate goes RED. **Mandatory mutation probe:** remove the `failures += 1` line and re-run — MUST go RED. | Hybrid — same precondition | AC-4 |
| **G5 — no scheduler wedge + self-heal.** Same disposable file, cold cache. **Leg (a):** under `at_pre_expire_unique` with `coop_on`, **first assert that the engine behind `scheduler.async_session` resolves to the disposable DSN** (mandatory — do not invoke the wrapper without it: `_coop_expiry_sweep_job()` takes its session from `scheduler.async_session`, a binding no other gate in this plan uses and which the repo's unpinned-`DATABASE_URL`-reaches-Supabase-PROD foot-gun makes unsafe to assume), then wrap `await _coop_expiry_sweep_job()` in `structlog.testing.capture_logs()` (the pattern already used at `test_pool_topology.py:110`) and assert **both** `coop_expiry_index_missing` (proves the guard actually fired — not that the flag failed to take, not that the guard was deleted) **and** `coop_expiry_sweep_crashed` (proves the wrapper caught it rather than the job short-circuiting at its `if not settings.identity_coop_enabled: return`) are present, and that the call returned normally. A bare "did not raise" assertion here is forbidden — it passes under at least three implementations that prove nothing. **Leg (b):** within one process, call `run_coop_expiry_sweep` while downgraded (expect raise), then `alembic_or_raise(dsn, "upgrade", "head")`, then call again — it must now succeed, proving the **negative** result was not cached. **Turns RED when:** the miss result is cached (leg (b) keeps raising after the index is restored), the guard raise escapes the wrapper, or the guard never fired (leg (a)'s log assertion). | Hybrid — same precondition | AC-5 |
| **G6 — frozen-surface check.** `git diff --stat -- apps/api/services/identity_resolver.py` is empty AND `git diff -U0 -- apps/api/services/identity_coop.py \| grep -c '^[+-].*spendable_balance'` returns 0. **`-U0` plus the `^[+-]` anchor are mandatory:** a plain `git diff \| grep -c` counts *context* lines, and `spendable_balance` sits at `identity_coop.py:547` inside the very docstring step 6 mandates editing — with default `-U3` a slightly different insertion point puts it in a context hunk and false-REDs the gate. **Turns RED when:** any edit lands in the resolver or actually adds/removes a line mentioning the balance query. | Fully-Automated — shell, no DB | AC-6 |
| **G7 — no schema change.** `git status --porcelain apps/api/migrations/versions/` is empty, and `DATABASE_URL=<pinned-local> .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` reports the same single head as before the change. **Turns RED when:** a migration file is added. | Fully-Automated — **DATABASE_URL MUST be pinned** (see Safety) | AC-7 |
| **G8 — regression: existing co-op suites unchanged.** Scope, corrected: **(i)** `tests/integration/test_identity_coop_ledger.py` (needs local PG on :5433) at baseline counts, and **(ii) a full disposable-lane re-run via `scripts/e2e-disposable.sh`** at baseline counts. **The disposable lane is mandatory here, not optional** — the tests most exposed to the D4 abort (`test_de16a`, `test_de14`, `test_de7`, `test_de8`) live there and nowhere else. **The unit leg (`pytest tests/unit/ -k coop`) is a cheap smoke ONLY and carries no regression value:** grep-verified, **no test under `tests/unit/` calls `expire_lapsed_lots` or `run_coop_expiry_sweep`**, so it structurally cannot regress the D4 change. **Turns RED when:** the systemic abort mis-fires against real fixtures. | Hybrid (integration on :5433) + Hybrid (full disposable-lane re-run); unit smoke is Fully-Automated but non-proving | AC-3 regression |

### Falsifiability summary

| Gate | Named broken implementation it forbids |
|---|---|
| G1 | Guard absent, or fail-open, or a raise that came from somewhere other than the guard (log-asserted); mutation 2 forbids the true pre-fix `return 0` |
| G2 | Guard predicate wrong / branches inverted (false alarm on healthy DB) |
| G3 (a) | `failures >= 1` |
| G3 (b) | `failures > processed` |
| G3 (d) | `skipped` not subtracted (under-fire on a mixed batch) — **the only skip-exclusion falsifier** |
| G3 (e) | `attempted` incremented after the skip (FAIL-1 pre-attempt-failure hole) |
| G4 | Systemic counter never incremented; single-point-of-failure fix; wrong monkeypatch site |
| G5 | Negative result cached (no self-heal); raise escapes the wrapper; guard never fired / flag never took |
| G6 | Resolver / balance-query drift (with `-U0` so context lines cannot false-RED it) |
| G7 | Accidental migration |
| G8 | D4 abort mis-fires against the disposable lane's real fixtures |

Note: G3 leg (c) (0 lapsed lots) is retained as a boundary smoke, but it is **not** credited with
catching skip-miscounting — with zero lots `attempted == 0` under every implementation, correct or
not. Legs (d) and (e) are the real falsifiers.

### Safety rules for every gate

- **Never run a bare `alembic` command.** The repo `.env` `DATABASE_URL` points at Supabase **PROD**
  and `apps/api/migrations/env.py` has no local-host guard. Inside the disposable lane use
  `alembic_or_raise(disposable_dsn, ...)` (pins the DSN). Outside it, prefix explicitly:
  `DATABASE_URL=postgresql+asyncpg://…@localhost:5433/… .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini …`.
- **Never run `pytest tests/e2e_disposable/` directly** — `tests/conftest.py:24`'s `setdefault` falls
  through to the shared dev DB on :5433 and would `DROP SCHEMA` it. Always go through
  `scripts/e2e-disposable.sh`; the lane's own DE-19/DE-21 guards enforce this.
- Use `.venv/bin/python3.11 -m pytest`, never `.venv/bin/pytest` (broken shebang).

---

## Test Infra Improvement Notes

- The disposable lane's `at_pre_expire_unique` fixture (currently local to
  `test_migration_truth.py:145`) is now needed by a second file. **Do not duplicate it by
  copy-paste-and-drift**: the checklist step 8 says copy the pattern, but if EXECUTE finds a clean
  lift, promote it to `tests/e2e_disposable/conftest.py` unchanged (including the C-11 restore
  assertion) and import it from both files. Record which route was taken in the phase report.
- **Process-lifetime module caches need an autouse reset fixture, and this is a generalisable lane
  hazard.** `coop_expiry_sweep._index_verified` is the instance here (step 8's mandatory fixture),
  but any `_verified`/`_checked`-style module flag has the same property: one healthy-path test
  silently disarms every later negative-path test in the process, and — worse — disarms the
  *mutation probes* that are supposed to prove those tests non-vacuous. When adding future
  guard-style caches, add the reset fixture in the same patch.
- **Generalisable falsifier pattern (contributed from an adjacent feature session):** the
  `InvalidColumnReferenceError` silent-swallow shape here is not specific to co-op expiry. **Any
  `ON CONFLICT ... WHERE ...` upsert whose partial index could be absent has the same failure mode** —
  the statement raises for a *schema* reason, a broad `except` treats it as a per-row fault, and the
  batch reports success having written nothing. When testing such an upsert, the falsifier is: drop
  the arbiter index, run the batch, and assert it fails **loudly** — not merely that it "did not
  write duplicates". Worth reaching for whenever a new partial-index upsert lands.
- No other test-infra gaps identified at plan time.

---

## Dependencies, Risks, and Rollback

| Item | Detail |
|---|---|
| **Dependency** | The disposable-e2e lane (`scripts/e2e-disposable.sh`, `tests/e2e_disposable/`, DE-1…DE-21, built 17-08-26) must be runnable. G1/G2/G4/G5 have no other home — the shared lane builds its schema with `Base.metadata.create_all`, so index-*absence* is structurally untestable there (the ORM mirror always creates it). |
| **Concurrency (live, 17-08-26)** | A debugger agent is investigating a flaky test in `tests/e2e_disposable/` using containers and the DB. EXECUTE must confirm that investigation has finished before running any gate in that lane. |
| **Risk: G4 false confidence** | If `assert_expire_index` is patched at the wrong import site, G4 could pass because the guard fired instead of the counter. Mitigations, all three: G4 names the patch site explicitly (`coop_expiry_sweep.assert_expire_index`); G4 asserts the exception **type** is `CoopExpirySystemicFailure`, not merely that *something* raised (a wrong patch site yields `CoopExpiryIndexMissing` ⇒ RED); and the mandatory `failures += 1` removal mutation must turn it RED. |
| **Risk: stale positive cache makes a negative gate vacuous** | `_index_verified` is process-lifetime; G2 running before G1 in the same file would disarm G1 **and** its mutation probe. Closed by step 8's mandatory autouse cold-cache fixture. Do not rely on alphabetical collection order. |
| **Risk: systemic abort mis-fires** | A legitimate single-processed-lot batch that fails for an unrelated reason now raises. Contained by the wrapper's `except`; surfaced by G8 regression. Accepted per D4. |
| **Risk: direct callers** | Seven non-scheduler call sites exist (full inventory in Public Contracts). The disposable-lane callers run against `alembic upgrade head`; **the integration-lane callers (`test_identity_coop_ledger.py:617/634`) do NOT — that lane uses `Base.metadata.create_all`.** They are safe because the partial unique index is mirrored in the ORM at `apps/api/models/identity_coop.py:141`. G8's two mandatory legs (integration + full disposable re-run) confirm both. |
| **Verified: no existing test breaks under D4** | Established by enumeration of all 8 call statements (7 non-scheduler), not assumed. `test_de16a` (`test_pool_topology.py:185`) — the `WHERE EXISTS` block is a **rowcount-0 no-op, not an exception**, so `failures` stays 0 with `processed == 1` ⇒ no raise (this was the single most likely regression, and it is safe). `test_de14` (`test_lifespan_scheduler.py:190`) raises `KeyboardInterrupt`, a **BaseException** that escapes `except Exception` before any counter is touched; its resume leg has 3 successes. Idempotence re-runs (`integration:447/516`, `test_de7`) hit the `remaining == 0` skip for every lot ⇒ `processed == 0` ⇒ predicate false. `test_de6` returns at `got is False`, never entering the loop. `tests/integration/test_identity_coop_ledger.py:745` (randomised drift harness) — iteration k lapses one lot while every previously expired lot is still lapsed with `remaining == 0`, so `attempted = k`, `skipped = k-1`, `processed = 1`, `failures = 0` ⇒ no raise. **Safe.** |
| **Rollback** | `git revert` the two source diffs. No data written, no schema touched, no migration, no flag flipped. Rollback is complete and instant. |

---

## Resume and Execution Handoff

1. **Selected plan file:**
   `process/features/visitors-identity/active/coop-expiry-index-guard_17-08-26/coop-expiry-index-guard_PLAN_17-08-26.md`
2. **Last completed phase/step:** PLAN written 17-08-26; **PVL supplement cycle 1 applied 17-08-26**
   (FAIL-1…FAIL-3 + CONCERN-1…CONCERN-6 folded in). No source file has been touched. No gate has been
   run. Checklist steps 1–8 are all outstanding.
3. **Validate-contract status:** **WRITTEN — `Gate: CONDITIONAL`, accepted; EXECUTE is licensed.**
   The `## Validate Contract` section below is the cycle-2 verdict. **Accepted-CONDITIONAL basis
   (stated here so the license is auditable rather than implied):**
   - The four cycle-2 CONCERNs — **A** caller-inventory accuracy, **B** raising-leg exception type,
     **C** G5 leg (a) DSN binding, **D** Goal 4 scoping — have each been transcribed into this plan
     body as execute-agent instructions **E1-E5**; none remains merely advisory.
   - The two pre-declared residuals both fail in the **safe direction**: an INVALID index
     false-greens the guard, but every lot then fails so D4's systemic abort fires loudly; a
     `pg_indexes` catalog-query error propagates **before** `_try_acquire_lock`, so it takes no
     advisory lock and can leak none.
   - The **flag-OFF-only known-gap stands**: `✅ VERIFIED` on this plan means *disposable-Postgres-
     proven only*. Production behaviour on the first `identity_coop_enabled` flip remains unproven by
     every tier here — that path belongs to the operator runbook, not this plan.
4. **Supporting context loaded:** `apps/api/services/identity_coop.py` (`_EXPIRE_INSERT_SQL` 515-529,
   `expire_lapsed_lots` 532-609 — real loop shape re-read at supplement time),
   `apps/api/services/coop_expiry_sweep.py` (full),
   `apps/api/jobs/scheduler.py` (wrapper 300-326, registration 742-752),
   `apps/api/models/identity_coop.py:141` (ORM index mirror),
   `apps/api/migrations/versions/b7e4d21a9c58_add_coop_expire_unique.py`,
   `tests/e2e_disposable/conftest.py` (fixture inventory),
   `tests/e2e_disposable/test_migration_truth.py` (`at_pre_expire_unique` pattern 145-166),
   `process/context/all-context.md`.
5. **Next step for a fresh agent: EXECUTE.** PVL is complete and the accepted-CONDITIONAL contract
   in item 3 licenses it; no further validate cycle is required. When EXECUTE starts: confirm
   the concurrent debugger investigation in `tests/e2e_disposable/` has finished, then work checklist
   steps 1→8 in order, running each gate at the end of its owning step rather than batching to the
   end. G1 and G4's **mandatory mutation probes are gating** — a gate that stays green under its named
   mutation must be rewritten, not accepted.
   **Read before believing any green result:** every Hybrid gate here runs on a **disposable
   Postgres**. Passing them all means the guard is proven *there*. It does **not** prove prod
   behaviour on the first `identity_coop_enabled` flip — no tier in this plan can, because the flag is
   OFF everywhere. Flag-OFF-only evidence is vacuous (ip-org G8/G10; icp_fit's silent no-op survived
   4 PVL + 2 EVL passes on exactly this evidence shape). Report `✅ VERIFIED` with that qualifier
   attached, and hand the prod path to the operator runbook for the first flag flip.

---

## Known Gaps

| Gap | Status |
|---|---|
| No production-environment proof. The guard is proven on a disposable Postgres only; prod behaviour on the first flag-ON deploy is unproven by any tier here. Reinforces the standing lesson: **flag-OFF-only evidence is vacuous** (ip-org G8/G10; icp_fit silent no-op survived 4 PVL + 2 EVL passes on flag-OFF evidence). **Also restated in Phase Completion Rules and Resume/Handoff step 5 so the implementer meets it before the gates, not after.** | Accepted known-gap. The prod path is the operator runbook for the first `identity_coop_enabled` flip, not this plan. |
| `apps/api/migrations/env.py` still has no local-host guard, so any unpinned alembic invocation reaches Supabase PROD. Out of scope here; every gate compensates by pinning `DATABASE_URL`. | Tracked in `process/features/visitors-identity/backlog/ip-org-followups_NOTE_07-08-26.md`. |
| The advisory-lock pool-connection residual (unlock may execute on a different connection and no-op) is untouched and unproven by this plan. | Pre-existing, accepted; documented in `run_coop_expiry_sweep`'s docstring and the capacity-hardening advisory-lock audit note. |
| No gate proves the guard's behaviour when the `pg_indexes` query itself errors (dead connection / permission denied). D3 says it propagates; that path is asserted by code reading, not by a test. | Accepted known-gap — cost of a fault-injected catalog query outweighs the value; the outcome (propagate) is the same fail-closed direction as a miss. |
| An **INVALID** index (left behind by a failed `CREATE INDEX CONCURRENTLY`) is still listed by `pg_indexes`, so the guard would pass while `ON CONFLICT` still fails. Not gated. | Accepted known-gap — surfaced by D4's systemic abort instead (every lot would fail ⇒ raise), which is the second layer working as designed. |

---

## Validate Contract

Status: CONDITIONAL
Date: 17-08-26
date: 2026-08-17
generated-by: inner-pvl: coop-expiry-index-guard
supersedes: 2026-08-17 (inner-pvl: coop-expiry-index-guard) — PVL cycle 2 re-validated from V1 against the supplemented plan body; cycle 1's BLOCKED verdict is stale

Parallel strategy: sequential
Rationale: Signal score 1/7 (S6 high-risk class **billing/credits** — yes; S1 multi-package — no,
one package; S2 schema/API — no; S3 3+ directions — no; S4 phase program — no; S5 user depth — no;
S7 5+ files — no, 4 files). Cycle 1 was the substantive fan-out-equivalent pass; cycle 2 is a
confirmation pass over one design thread (guard + three counters) whose semantics must be walked
once, coherently, against one source file. A fan-out would re-derive the same loop semantics N
times. Agent count: 1. Cost guard: not triggered.

---

### Net gate derivation

| Layer 1 dimension | Status |
|---|---|
| Infra fit | PASS |
| Test coverage | CONCERN |
| Breaking changes | CONCERN |
| Security surface | PASS |

| Layer 2 section | Status |
|---|---|
| D1 — guard placement | PASS |
| D2/D3 — fail-closed + positive-only cache + cold-cache fixture | PASS |
| D4 — systemic-failure abort (the FAIL-1 fix) | PASS |
| Verification Evidence (G1–G8) | CONCERN |
| Touchpoints / Blast Radius / caller inventory | CONCERN |
| Known Gaps | PASS |

**Totals: 0 FAILs / 4 CONCERNs / 6 PASSes → Net Gate: CONDITIONAL**

Cycle-1 disposition: **all 3 FAILs resolved, all 6 CONCERNs resolved.** The 4 CONCERNs below are
new findings from this cycle, each with a one-line fix routed as an execute-agent instruction.

---

### Cycle-1 findings — verified resolved

| Cycle-1 finding | Resolution verified in this cycle |
|---|---|
| **FAIL-1** — counter placement leaves the pre-attempt-failure class undetected | **RESOLVED.** Walked against `identity_coop.py:586-607`. `attempted` at the top of the loop body before the `try`; `skipped` on the `remaining == 0` branch; `processed = attempted - skipped`. See Q-1 walk-through below — all five sub-cases correct. |
| **FAIL-2** — G5 leg (a) was a bare "did not raise" | **RESOLVED.** Leg (a) now asserts **both** `coop_expiry_index_missing` and `coop_expiry_sweep_crashed` inside `capture_logs()`. All three named false-pass modes closed (see Q-2). |
| **FAIL-3** — G3 could not falsify skip-exclusion | **RESOLVED.** Legs (d) mixed skip+fail and (e) pre-attempt failure both added, and both are genuine falsifiers (see Q-2). |
| **CONCERN-1** — `_index_verified` cache poisoning | **RESOLVED.** Mandatory autouse `_cold_index_cache` fixture, correctly function-scoped (see Q-3). |
| **CONCERN-2** — G1's RED narrative wrong once D4 exists; log events ungated | **RESOLVED.** Narrative corrected, `coop_expiry_index_missing` asserted in G1, `coop_expiry_all_lots_failed` asserted in G4, second mutation recorded (see Q-4). |
| **CONCERN-3** — caller-inventory rationale false for the integration lane | **RESOLVED on the rationale** (ORM-mirror claim confirmed verbatim against source), **but the table itself introduced 3 factual errors** → new CONCERN-A. |
| **CONCERN-4** — G8's unit leg vacuous, disposable leg missing | **RESOLVED.** Disposable-lane re-run is now mandatory in the G8 row; the unit leg is explicitly demoted to a non-proving smoke. |
| **CONCERN-5** — G6 `-U0` form; G4 patch site unnamed | **RESOLVED, and independently validated.** `test_lifespan_scheduler.py:277` already uses `monkeypatch.setattr(coop_expiry_sweep, "expire_lapsed_lots", ...)` successfully, proving module-global late-binding works for exactly the pattern G4 specifies. |
| **CONCERN-6** — flag-OFF-only known-gap not where the implementer reads it | **RESOLVED.** Now stated in Phase Completion Rules, Resume/Handoff step 5, **and** Known Gaps — three encounters before the gates. |

---

### Q-1 — the FAIL-1 counter redesign, walked against real source

Real loop re-read at `apps/api/services/identity_coop.py:579-609`. `lot_id_str = str(lot_id)` at
:586 is the only statement before the `try`; `_lot_remaining` (:588) and the `remaining == 0`
`continue` (:589-590) are both **inside** the try; `except Exception` at :604-607 does
`rollback` → `logger.exception` → `continue`. **The plan's D4 code excerpt matches source exactly**,
including statement order inside the except. Line citations (`_EXPIRE_INSERT_SQL` 515-529,
`expire_lapsed_lots` 532-609, `spendable_balance` at :547) all verified accurate.

| Sub-question | Verdict |
|---|---|
| **(a) Does the placement close the hole?** | **YES.** All lots failing inside `_lot_remaining`: each lot increments `attempted` before the `try`, then `_lot_remaining` raises → `except` → `failures += 1`. Result `attempted = N, skipped = 0, failures = N`, `processed = N ≥ 1`, `failures == processed` → **raises**. The class FAIL-1 named (dead session, pool exhaustion on the 3+2 prod-parity pool, aborted txn, permission denied) is now covered. |
| **(b) Is `failures > processed` reachable?** | **NO — structurally impossible.** `skipped += 1` is immediately followed by `continue`; nothing between them can raise (integer increment), so a lot cannot land in both `skipped` and `failures`. Every lot contributes exactly 1 to `attempted` and at most 1 to `{skipped, failures}` ⇒ `failures ≤ attempted − skipped = processed`. The plan's claim is correct. Nothing mis-fires. |
| **(c) Empty lapsed set must not raise** | **CONFIRMED.** Loop body never executes; `processed = 0`; `processed >= 1` is False → no raise. |
| **(d) Single processed lot that fails DOES raise — is that coherent?** | **Decided explicitly and coherently.** D4 states it verbatim ("A batch of exactly 1 processed lot that fails does raise. Accepted: on a billing surface…the wrapper contains the blast radius"). C-1's isolation is preserved **at the loop level** verbatim — rollback + log + continue are untouched, no lot wedges the tick. **Minor wording tension:** Goal 4 says C-1 isolation is "preserved verbatim", which over-reads for the 1-lot case (the loop is verbatim; the post-loop return is not). Mechanically harmless — G3 leg (d) is `processed == 1` and MUST raise, so a defensive `processed >= 2` mis-implementation goes RED. Recorded as CONCERN-D. |
| **(e) Does D4's prose match the real code?** | **YES — no residual false narrative.** The supplement's "The real loop shape (verified against source — an earlier draft of this section was wrong)" subsection is accurate line-for-line, explicitly retracts the old claim, and derives the counter placement from the true shape. |

**Independent D4-regression re-verification (not taken from the plan).** Every forced-failure call
site re-walked:
- `test_de16a` (`test_pool_topology.py:~209`) — the `WHERE EXISTS` block is a **rowcount-0 no-op, not
  an exception**, and the test asserts `remaining > 0` at call time (so the skip did not fire).
  `attempted = 1, skipped = 0, failures = 0, processed = 1`, `0 == 1` False → **no raise. Safe.**
  This was the most likely regression and it is confirmed safe against source.
- `test_de14` (`test_lifespan_scheduler.py:~241`) — `KeyboardInterrupt` is a **BaseException**, escapes
  `except Exception`, propagates out of `expire_lapsed_lots` before the post-loop predicate is ever
  reached. Resume leg: 5 lots, 2 already expired → `skipped = 2`, 3 succeed → `failures = 0` → no raise. **Safe.**
- `test_de15` (`test_lifespan_scheduler.py:277`) — replaces `expire_lapsed_lots` wholesale; D4 code never runs. **Safe.**
- `test_de16b` (`test_pool_topology.py:~241`), `test_de8` (`test_scenario_43.py:44`) — all lots succeed, `failures = 0`. **Safe.**
- `tests/integration/test_identity_coop_ledger.py:745` (randomised drift harness) — **not enumerated by
  the plan.** Each iteration lapses one lot and calls `expire_lapsed_lots` while every previously
  expired lot is still in the lapsed set with `remaining == 0`. Iteration k: `attempted = k`,
  `skipped = k−1`, `processed = 1`, `failures = 0` → no raise. **Safe** — but note it drives the
  `processed == 1` regime repeatedly, which is exactly the regime D4 accepted as raise-worthy.
**Conclusion: no existing test regresses under D4.** Independently confirmed.

---

### Q-2 — the new gate legs

**G3 leg (d) — mixed skip + fail.** Genuine falsifier. Under the "skipped not subtracted" bug:
`attempted = 2, failures = 1`, `processed` computed as 2 → `1 == 2` False → **no raise → RED**.
Under the correct form: `processed = 1, failures = 1` → raises. Legs (a)–(c) all stay green under
that bug, confirming (d) is the only skip-exclusion falsifier. ✅

**G3 leg (e) — pre-attempt failure.** Genuine falsifier. Under the FAIL-1 bug (increment after the
skip): `attempted = 0, failures = 2`, `processed = 0` → **no raise → RED**. Under the corrected
form: `attempted = 2, skipped = 0, processed = 2, failures = 2` → raises. ✅ **But see CONCERN-B —
the stub must be shape-aware and the assertion must be typed, or this leg can go green against the
very bug it exists to forbid.**

**G5 leg (a) — `capture_logs()` two-event form.** Closes all three false-pass modes cycle 1 named:
(i) guard never fired / cache already True → `coop_expiry_index_missing` absent → RED (belt-and-braces
with the step-8 cold-cache fixture); (ii) `coop_on` did not take and the wrapper returned at
`scheduler.py:317-318` → **neither** event present → RED; (iii) guard deleted → the miss event is
absent → RED (D4 would still raise, so `coop_expiry_sweep_crashed` alone would have passed a
one-event assertion — this is precisely why both are required). ✅ `structlog.testing.capture_logs()`
captures both `logger.error` and `logger.exception` from `structlog.get_logger()`, and the pattern is
already in use at `test_pool_topology.py:110`. Verified.

---

### Q-3 — the cold-cache fixture

**Correct, and correctly scoped.** `@pytest.fixture(autouse=True)` with no `scope=` is
function-scoped, and requesting `monkeypatch` **forces** function scope (a module-scoped fixture
requesting `monkeypatch` raises). Autouse applies to every test in the module, so it runs setup
before **each** test including G1 — intra-file collection order is genuinely irrelevant, which is
the stated point. monkeypatch teardown restores the pre-fixture value, but the next test's fixture
sets `False` again before its body, so every test starts cold regardless of what any predecessor
leaked. **The "G2 poisons G1 so its mutation probe is pre-RED" hazard is removed.** ✅

---

### Q-4 — G1's corrected RED narrative and the second mutation

**Sibling cross-match: confirmed impossible in both directions.** `CoopExpiryIndexMissing(RuntimeError)`
(step 1, `coop_expiry_sweep`) and `CoopExpirySystemicFailure(RuntimeError)` (step 4, `identity_coop`)
are siblings — neither subclasses the other — so `pytest.raises` isinstance-matching cannot cross-match.
G1's `pytest.raises(CoopExpiryIndexMissing)` will not swallow a `CoopExpirySystemicFailure`, and G4's
`pytest.raises(CoopExpirySystemicFailure)` will not swallow a `CoopExpiryIndexMissing` from a
mis-patched guard. ✅

**Both mutations specified unambiguously:**
- **Mutation 1** — delete `await assert_expire_index(db)`. Code then raises `CoopExpirySystemicFailure`
  (≥1 lapsed lot, insert fails, `processed = 1, failures = 1`). G1 goes RED for **two independent
  reasons**: the type does not match, and `coop_expiry_index_missing` is absent from the captured logs. ✅
- **Mutation 2** — delete that line **and** `failures += 1` together. Then `failures = 0, processed = 1`
  → predicate False → returns `0`. This exactly reproduces the true pre-fix silent behaviour, and G1
  goes RED on "no exception raised". ✅
Each mutation names an exact line; neither is ambiguous.

---

### Q-5 — new-gap sweep

| Item | Verdict |
|---|---|
| **`identity_coop.py` ≤ 25 added lines** | Tight but achievable: exception class + docstring ≈ 8, three counter inits 3, three increments 3, post-loop block 4-6, docstring additions 3-5 ⇒ ≈ 21-25. At the ceiling. Advisory budget, not a gate — noted, not a finding. |
| **`coop_expiry_sweep.py` ≤ 50 added lines** | Comfortable for constants + exception + `assert_expire_index` + docstring note. |
| **Test files 200 / 150** | 200 for four disposable gates plus a copied `at_pre_expire_unique` (~22 lines, verified at `test_migration_truth.py:145-166`) is tight but workable; 150 for five G3 legs plus a **three-shape** stub session is tight (see CONCERN-B). |
| **Caller table completeness** | **3 factual errors → CONCERN-A.** Conclusion (no breakage) independently re-verified TRUE. |
| **ORM-mirror rationale** | **CONFIRMED VERBATIM.** `apps/api/models/identity_coop.py:140-145` carries the `Index("uq_coop_ledger_expire_per_lot", "lot_id", unique=True, postgresql_where=text("entry_type = 'EXPIRE'"))`, and its own source comment reads "Mirrored here (not only in the migration) because the integration schema is built by Base.metadata.create_all, never alembic." The corrected rationale is exactly right, and the "removing it would break the lane loudly — a feature" framing is sound. ✅ |
| **G6 `-U0` grep form** | Correct. `spendable_balance` confirmed at `identity_coop.py:547`, inside the very docstring step 6 mandates editing. `-U0` plus the `^[+-]` anchor is the right and necessary form. ✅ |
| **G4 named patch site** | Correct **and independently validated**: `test_lifespan_scheduler.py:277` already does `monkeypatch.setattr(coop_expiry_sweep, "expire_lapsed_lots", _abort_then_raise)` and it works, proving `run_coop_expiry_sweep`'s module-global late-binding is patchable exactly as G4 specifies. ✅ |
| **Flag-OFF-only known-gap placement** | Now in Phase Completion Rules, Resume step 5, and Known Gaps — the implementer meets it three times before touching a gate. ✅ |
| **New contradiction introduced this round?** | One minor wording tension (Goal 4 vs D4's accepted single-lot raise) → CONCERN-D. No substantive contradiction. |

---

### Secondary — the two ungated residuals: is "fails in the safe direction" actually true?

**1. INVALID index still listed by `pg_indexes` — TRUE, verified by reasoning through the full path.**
An invalid index (failed `CREATE INDEX CONCURRENTLY`) is not usable for `ON CONFLICT` arbiter
inference, so every EXPIRE insert still raises `InvalidColumnReferenceError`. The guard passes
(layer 1 false-green, correctly acknowledged), but every lot then fails ⇒ `failures == processed` ⇒
`CoopExpirySystemicFailure` ⇒ `coop_expiry_all_lots_failed` + `coop_expiry_sweep_crashed`. **Loud, in
the safe direction — this is D4's independent second layer doing exactly its job.** Residual caveat:
if the batch is entirely skipped (`processed == 0`) nothing raises, but nothing needed writing either,
so there is no silent loss. Known-gap correctly accepted.

**2. `pg_indexes` catalog-query error path — TRUE, and better than the plan claims.** The guard is the
**first** statement of `run_coop_expiry_sweep`, strictly before `_try_acquire_lock`, so a propagating
catalog error takes no advisory lock and therefore cannot leak one; the wrapper's
`except Exception: logger.exception("coop_expiry_sweep_crashed")` catches it; zero rows written.
**Fail-closed, loud, no lock leak.** One nuance worth recording: this path emits only the generic
crash event, **not** `coop_expiry_index_missing`, so an operator grepping for the dedicated event will
not find it. Still loud; less identifiable. Known-gap correctly accepted.

---

### CONCERNs (all four are new to cycle 2; each has a one-line fix)

**CONCERN-A — the caller inventory has three factual errors; the conclusion survives them.**
Verified by grep against the working tree:
- **`tests/e2e_disposable/test_diag_de5.py` does not exist.** The lane contains `_replica_child.py`,
  `conftest.py`, `test_helper_guard.py`, `test_lifespan_scheduler.py`, `test_migration_truth.py`,
  `test_pool_topology.py`, `test_scale_sweep.py`, `test_scenario_43.py`, `test_two_process_replica.py`.
  The caller table's `test_diag_de5.py` row is a **phantom**.
- **`test_lifespan_scheduler.py:248` is the wrong line.** The real `run_coop_expiry_sweep` call is at
  **:280** (import at :267); :250 is an `expire_lapsed_lots` call.
- **"enumerated, 15 call sites" is wrong.** Real `run_coop_expiry_sweep` **call statements** = **8**
  (integration 617/634, lifespan 280, pool_topology 110/157, `_replica_child` 69, scale_sweep 88,
  scheduler 322). "15" is the grep-line count including imports and docstring mentions. The Risks
  row's "**Seven** non-scheduler call sites" is **correct**; the header contradicts it.
Direction of harm: none — a phantom caller cannot break, and the safety conclusion was independently
re-verified TRUE this cycle. But the plan's D4-safety argument explicitly rests on *enumeration
completeness* ("Established by enumeration of all 15 call sites, not assumed"), so a wrong roster
weakens the warrant.
*Fix (execute-agent instruction E1):* delete the `test_diag_de5.py` row, correct `:248` → `:280`,
change "15 call sites" → "8 call statements (7 non-scheduler)". Add `tests/integration/test_identity_coop_ledger.py:745`
to the D4-regression enumeration with its verdict (`processed == 1, failures == 0` per iteration → safe).

**CONCERN-B — G3's stub must be shape-aware and every raising leg must assert the exception TYPE, or
leg (e) can go green against the exact bug it exists to forbid.**
`expire_lapsed_lots` runs its lapsed-lot `SELECT` at `identity_coop.py:563-576` — **outside any try**.
The stub session must therefore serve three distinct `execute` shapes: (1) the lapsed-lot select
(`.all()`), (2) `_lot_remaining`'s select (`.scalar_one()`), (3) the `text(_EXPIRE_INSERT_SQL)` insert
(`.rowcount`). Leg (e) must raise on shape **2 only**. A naive stub that raises on *any* `execute`
raises at shape 1, and `expire_lapsed_lots` then propagates a **raw** exception from outside the loop.
If leg (e) is written as `pytest.raises(Exception)` — and `CoopExpirySystemicFailure` is an `Exception`
subclass, so the loose form looks correct — **leg (e) passes against the buggy FAIL-1 predicate too**.
That is a gate green on the implementation it exists to forbid: recurrence class #9 in waiting, in the
single most important new leg of this supplement. Checklist step 7 names the type only for leg (b);
legs (d) and (e) say "MUST raise" untyped.
*Fix (execute-agent instruction E2):* every raising leg of G3 uses
`pytest.raises(CoopExpirySystemicFailure)` explicitly — **never** bare `Exception` — and the stub must
let the initial lapsed-lot query succeed, raising only on the per-lot query the leg targets.

**CONCERN-C — G5 leg (a) is the only gate that uses a session the plan neither controls nor mentions.**
`_coop_expiry_sweep_job()` does `async with async_session() as db` — `scheduler.py`'s **module-level**
sessionmaker, bound to the app engine from `DATABASE_URL`, **not** the lane's `disposable_engine`.
Every other gate in this plan takes an explicitly lane-bound session (`disposable_db`, or
`async_sessionmaker(disposable_engine, …)`). The lane is aware of this: `test_lifespan_scheduler.py:89`
documents that "`scheduler.py`'s module-level `async_session` … `tests/conftest.py:199-212` never
patches", and DE-5 depends on `scripts/e2e-disposable.sh` having exported the ephemeral DSN as
`DATABASE_URL` before pytest starts. So it very likely already works — but the plan asserts nothing
about it, on a billing surface, in a repo whose documented foot-gun is that an unpinned `DATABASE_URL`
reaches Supabase PROD. If `async_session` were bound to the shared dev DB instead, leg (a) would run a
real sweep against it (the dev DB **has** the index, so the guard would pass, no miss event would be
emitted, and the leg would go RED for a confusing reason after writing EXPIRE rows into the dev DB).
*Fix (execute-agent instruction E3):* G5 leg (a) asserts, before invoking the wrapper, that the engine
behind `scheduler.async_session` resolves to the disposable DSN (or bind/monkeypatch it explicitly to
the lane engine). One assertion. Also add `tests/e2e_disposable/test_lifespan_scheduler.py` (`_run_job_now`
docstring, `:85-115`) to the plan's "Read for context" list — it is the file that documents this path.

**CONCERN-D — Goal 4's "C-1's single-bad-lot isolation is preserved verbatim" over-reads for the
1-processed-lot case.** The **loop** behaviour is verbatim (rollback + log + continue, no wedge); the
**function** return is not — a 1-lot batch that fails now raises, which D4 decides explicitly and
accepts. Mechanically harmless: G3 leg (d) is a `processed == 1` case that MUST raise, so a defensive
`processed >= 2` mis-reading goes RED.
*Fix (execute-agent instruction E4):* reword Goal 4 to "C-1's single-bad-lot isolation **inside the
loop** is preserved verbatim; the all-processed-failed abort is a post-loop addition (D4)."

---

### Execute-agent instructions

| # | Instruction | Trigger condition |
|---|---|---|
| E1 | Correct the caller inventory while editing: drop the phantom `test_diag_de5.py` row, fix `test_lifespan_scheduler.py:248` → `:280`, replace "15 call sites" with "8 call statements (7 non-scheduler)", and add `tests/integration/test_identity_coop_ledger.py:745` to the D4-regression enumeration. Record the correction in the phase report. | Before/while writing checklist steps 5-6 |
| E2 | In `tests/unit/test_coop_expiry_guard.py`, every raising leg asserts `pytest.raises(CoopExpirySystemicFailure)` explicitly — never bare `Exception`. The stub session must let the initial lapsed-lot `SELECT` succeed and raise only on the specific per-lot query the leg targets (three execute shapes: lapsed select `.all()`, `_lot_remaining` `.scalar_one()`, insert `.rowcount`). | Checklist step 7 |
| E3 | In G5 leg (a), assert the engine behind `scheduler.async_session` resolves to the disposable DSN before invoking `_coop_expiry_sweep_job()` (or bind it explicitly to the lane engine). Do not invoke the wrapper without that assertion. | Checklist step 8, G5 leg (a) |
| E4 | Reword Goal 4 to scope C-1 preservation to the loop body, per D4's accepted 1-processed-lot raise. | While editing the Goals section |
| E5 | The `## Autonomous Goal Block`'s "Next phase" line still reads "PVL RE-VALIDATE" and is stale w.r.t. this contract. The orchestrator refreshes it at the /goal emit; the execute agent must not treat it as current routing. | Before EXECUTE |

---

### Test gates

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 | Guard raises `CoopExpiryIndexMissing`, emits `coop_expiry_index_missing`, writes zero rows when the index is absent | Fully-Automated | G1 in `tests/e2e_disposable/test_expiry_index_guard.py` under `at_pre_expire_unique` + cold `_index_verified`, via `scripts/e2e-disposable.sh`; mutation probes 1 and 2 both mandatory | B |
| AC-2 | Healthy schema: guard is a no-op, correct row written, idempotent on re-run | Fully-Automated | G2, same file/lane; second leg asserts return 0 and count still 1; branch-flip mutation | B |
| AC-3 | Systemic abort discriminates all-failed / one-failed / all-skipped / mixed skip+fail / pre-attempt failure | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_coop_expiry_guard.py` — legs (a)-(e); **every raising leg typed to `CoopExpirySystemicFailure` per E2** | B |
| AC-4 | The index guard and the systemic counter are independent layers | Fully-Automated | G4, same lane, `monkeypatch.setattr(coop_expiry_sweep, "assert_expire_index", _noop)`, 2 lapsed lots, `pytest.raises(CoopExpirySystemicFailure)` + `coop_expiry_all_lots_failed` assertion; mandatory `failures += 1` removal probe | B |
| AC-5 | Guard raise never wedges the scheduler; positive-only cache self-heals | Hybrid | G5 leg (a) — `_coop_expiry_sweep_job()` under `coop_on` with **both** log events asserted **and the E3 session-binding assertion**; leg (b) — raise → `alembic_or_raise(dsn, "upgrade", "head")` → succeeds in the same process. Precondition: disposable Postgres via `scripts/e2e-disposable.sh`; `scheduler.async_session` bound to the disposable DSN | B |
| AC-6 | `identity_resolver.py` frozen; `spendable_balance` query untouched | Fully-Automated | `git diff --stat -- apps/api/services/identity_resolver.py` empty AND `git diff -U0 -- apps/api/services/identity_coop.py \| grep -c '^[+-].*spendable_balance'` == 0 | B |
| AC-7 | No schema change | Fully-Automated | `git status --porcelain apps/api/migrations/versions/` empty AND `DATABASE_URL=<pinned-local> .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` unchanged | A |
| AC-3-reg | No existing co-op test regresses under the D4 abort | Hybrid | G8 — `tests/integration/test_identity_coop_ledger.py` (local PG on :5433) **plus a full disposable-lane re-run** at baseline counts. Unit leg is a non-proving smoke | B |
| — | `pg_indexes` catalog query itself errors (dead connection / permissions) | — | none | D — named residual; verified this cycle to fail loudly with no lock leak (guard precedes `_try_acquire_lock`), emitting only the generic `coop_expiry_sweep_crashed` |
| — | INVALID index (failed `CREATE INDEX CONCURRENTLY`) still listed by `pg_indexes` | — | none | D — named residual; verified this cycle: guard false-greens, D4's abort then fires loudly. Layer 2 working as designed |
| — | Production behaviour on the first `identity_coop_enabled` flip | — | none | D — named residual; operator runbook, not this plan. Flag-OFF-only evidence is vacuous |
| — | `coop_expiry_index_missing` / `coop_expiry_all_lots_failed` greppability in a real log pipeline | — | none | D — named residual; `capture_logs()` proves emission, not pipeline visibility |

gap-resolution legend: A — proven now · B — fixed in this plan · C — deferred to a named later
phase · D — backlog test-building stub (named residual; keep-active; continue).

C-4 reconciliation: the `strategy` column carries only the three proving strategies
(Fully-Automated / Hybrid / Agent-Probe). Known-Gap is never a strategy value — the residual rows
above carry gap-resolution **D** and prove nothing by themselves.

Note on AC-1/AC-2/AC-4 strategy: these run inside `scripts/e2e-disposable.sh`, which provisions its
own ephemeral Postgres — deterministic and self-contained once Docker is up, hence Fully-Automated
rather than Hybrid. AC-5 stays **Hybrid** because leg (a) additionally depends on the ambient
`scheduler.async_session` binding (CONCERN-C / E3), and AC-3-reg stays Hybrid because its integration
half requires the shared local PG on :5433.

Legacy line form (for existing validate-contract consumers):
- Guard fires / no-op / independence: [Fully-automated: `scripts/e2e-disposable.sh` covering `tests/e2e_disposable/test_expiry_index_guard.py` — cold `_index_verified`]
- Systemic abort logic: [Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_coop_expiry_guard.py`]
- Scheduler no-wedge + self-heal: [hybrid: same lane + precondition `scheduler.async_session` bound to the disposable DSN]
- Frozen surfaces: [Fully-automated: `git diff -U0` checks, no DB]
- No schema change: [Fully-automated: `git status --porcelain` + pinned-DSN `alembic heads`]
- Regression: [hybrid: `tests/integration/test_identity_coop_ledger.py` + full disposable-lane re-run — precondition: local PG on :5433]
- Catalog-query error path / INVALID index / prod flag-ON behaviour / log-pipeline visibility: [known-gap: documented]

**Failing stubs (Fully-Automated rows only):**

```
test("should return 2 and not raise when 3 lots are attempted and exactly 1 fails", () => { throw new Error("NOT IMPLEMENTED — TDD stub: 3 lots / 1 fails ⇒ returns 2, no raise") })
test("should raise CoopExpirySystemicFailure when all 3 attempted lots fail", () => { throw new Error("NOT IMPLEMENTED — TDD stub: 3 lots / 3 fail ⇒ raises CoopExpirySystemicFailure (typed, never bare Exception)") })
test("should return 0 and not raise when there are no lapsed lots", () => { throw new Error("NOT IMPLEMENTED — TDD stub: 0 lapsed lots ⇒ returns 0, no raise") })
test("should raise CoopExpirySystemicFailure when a batch is one skipped lot plus one failing lot", () => { throw new Error("NOT IMPLEMENTED — TDD stub: mixed skip+fail ⇒ raises (skip-exclusion falsifier)") })
test("should raise CoopExpirySystemicFailure when every lot fails inside _lot_remaining before the insert", () => { throw new Error("NOT IMPLEMENTED — TDD stub: pre-attempt failures ⇒ raises (FAIL-1 regression); stub must let the lapsed-lot SELECT succeed") })
test("should raise CoopExpiryIndexMissing and emit coop_expiry_index_missing when the index is absent", () => { throw new Error("NOT IMPLEMENTED — TDD stub: G1 guard fires, zero rows written") })
test("should be a no-op on a healthy schema and stay idempotent on re-run", () => { throw new Error("NOT IMPLEMENTED — TDD stub: G2 healthy path") })
test("should raise CoopExpirySystemicFailure with the guard no-op'd, proving two independent layers", () => { throw new Error("NOT IMPLEMENTED — TDD stub: G4 independence") })
test("should keep identity_resolver.py diff empty and spendable_balance query byte-identical", () => { throw new Error("NOT IMPLEMENTED — TDD stub: frozen-surface check") })
test("should add no migration file and leave alembic heads unchanged", () => { throw new Error("NOT IMPLEMENTED — TDD stub: no schema change") })
```

---

### Dimension findings

- **Infra fit: PASS** — D1's placement re-verified against source: `run_coop_expiry_sweep`'s first
  statement is `got = await _try_acquire_lock(db)` (`coop_expiry_sweep.py:76`), so inserting the guard
  above it is mechanically trivial and provably prevents a lock leak on every failure path including
  the catalog-query error path. `start_scheduler()` is sync (`scheduler.py:615`) and the registration
  is flag-gated — both D1 rejections remain factually correct.
- **Test coverage: CONCERN** — CONCERN-B (G3 stub shape + untyped raising legs can make the FAIL-1
  regression leg vacuous) and CONCERN-C (G5 leg (a)'s uncontrolled session). Every AC otherwise has a
  Fully-Automated or Hybrid gate with a named mutation; no developed behaviour rests on Known-Gap alone.
- **Breaking changes: CONCERN** — CONCERN-A: three factual errors in the caller inventory (phantom
  file, wrong line, wrong count). The conclusion (no breakage; no existing test regresses under D4)
  was independently re-verified TRUE this cycle by walking every forced-failure call site.
- **Security surface: PASS** — no auth, PII, secret, or trust-boundary surface. The `pg_indexes`
  predicate takes no user input. Billing/credits risk class correctly declared and correctly routed to
  a Hybrid-minimum gate set. Fail-closed is the safe direction for a credit ledger. The repo's
  prod-DSN foot-gun is explicitly guarded in the plan's Safety rules; CONCERN-C is the one place the
  plan leaves a DB binding unasserted, and its fix is one assertion.
- **D1 guard placement: PASS**
- **D2/D3 cache + cold-cache fixture: PASS** — positive-only caching genuinely self-heals; the autouse
  fixture is correctly function-scoped and removes the G2→G1 poisoning hazard entirely.
- **D4 systemic abort: PASS** — the central FAIL-1 fix is correct on all five sub-questions. The hole
  is closed, `failures > processed` is structurally impossible, the empty and single-lot boundaries
  behave as decided, and the rewritten prose matches source with no residual false narrative.
- **Verification Evidence (G1–G8): CONCERN** — CONCERN-B, CONCERN-C.
- **Touchpoints / Blast Radius: CONCERN** — CONCERN-A; `identity_coop.py`'s ≤25-line budget is at its
  ceiling; `test_lifespan_scheduler.py` should be added to "Read for context" for G5.
- **Known Gaps: PASS** — both previously ungated residuals were judged this cycle and **do** fail in
  the safe direction (see Secondary above); the flag-OFF-only gap is now restated where the
  implementer will meet it.

---

### Open gaps

- `pg_indexes` catalog-query error path: known-gap: documented — verified this cycle to propagate
  before the advisory lock is taken, so it is loud, writes nothing, and leaks no lock.
- INVALID index still listed by `pg_indexes`: known-gap: documented — verified this cycle that D4's
  systemic abort fires, so the outcome is loud rather than silent.
- Production behaviour on the first `identity_coop_enabled` flip: known-gap: documented — the standing
  flag-OFF-only-evidence trap (ip-org G8/G10; icp_fit's silent no-op survived 4 PVL + 2 EVL passes on
  exactly this evidence shape).
- `migrations/env.py` local-host guard: known-gap: documented as NEW PLAN REQUIRED — tracked in
  `process/features/visitors-identity/backlog/ip-org-followups_NOTE_07-08-26.md`.
- Advisory-lock pool-connection residual: known-gap: documented, pre-existing, out of scope.
- Log-pipeline visibility of the two new ERROR events: known-gap — emission is provable in-test,
  greppability in a real pipeline is not.

### What this coverage does NOT prove

- **G1/G2/G4/G5 (disposable lane)** — prove behaviour against a throwaway Postgres built by
  `alembic upgrade head` on an ephemeral port, single process, no competing pool consumer. They do
  **not** prove: behaviour on Supabase prod; behaviour under concurrent pool pressure; behaviour when
  the index exists but is INVALID (the guard passes — only D4's abort covers it, and that path is
  itself ungated); behaviour across a fleet where some processes cached a positive result before an
  operator dropped the index.
- **G3 (unit)** — proves the counter arithmetic against a stubbed session only. It does **not** prove
  the real loop's exception surface matches the stub's, nor that a real `InvalidColumnReferenceError`
  is raised at the same statement the stub raises at. With E2 unapplied it would additionally not
  prove leg (e) at all.
- **G5 leg (a)** — proves the wrapper swallows the raise and both events are emitted **in-process**.
  It does **not** prove the events are visible in a deployed log pipeline, and (absent E3) it does not
  prove which database the wrapper's own session was pointed at.
- **G6** — proves the two named files/queries did not change in the working tree. It does **not** prove
  there is no behavioural coupling to the resolver elsewhere.
- **G7** — proves no migration file was added and the head is unchanged. It does **not** prove the
  index is present in any deployed environment; `b7e4d21a9c58` has still never been applied to prod.
- **G8** — proves existing suites pass at baseline counts. It does **not** prove the D4 abort is
  correct, only that it does not mis-fire against fixtures that exist today.
- **Nothing here proves prod behaviour on the first `identity_coop_enabled` flip.** `✅ VERIFIED` on
  this plan means *proven on a disposable Postgres*, nothing more.

Gate: CONDITIONAL (0 FAILs; 4 CONCERNs — A caller-inventory factual errors, B G3 stub shape +
untyped raising legs, C G5 leg (a) uncontrolled session binding, D Goal 4 wording. All four have
one-line fixes routed as execute-agent instructions E1–E4. All 3 cycle-1 FAILs and all 6 cycle-1
CONCERNs are resolved.)

Accepted by: **PENDING — not accepted by this agent.** This is a CONDITIONAL verdict and this agent
does not self-accept its own verdict. The four CONCERNs are **not** pre-declared known-gaps; they are
new cycle-2 findings. Routing is the orchestrator's: either (a) accept the four CONCERNs on the
record with E1–E4 carried into EXECUTE as binding instructions, or (b) run one more supplement cycle
folding E1–E4 into the plan body. Option (a) is proportionate for a SIMPLE plan whose central fix is
verified correct and whose four residuals are each a single sentence — but the choice, and the
written acceptance, belong to the orchestrator or the user, not to this agent.

---

## Autonomous Goal Block

```
SESSION GOAL: Close finding F-B — make the missing uq_coop_ledger_expire_per_lot index a loud,
fail-closed error instead of a silent co-op expiry sweep that expires nothing.
Charter + umbrella plan: N/A — single SIMPLE plan (not a registered phase of
process/features/visitors-identity/active/identity-coop_07-08-26/identity-coop-umbrella_PLAN_07-08-26.md).
Autonomy: standard /goal rules — self-decide reversible steps; hard stop on any irreversible or
outward-facing action not named in this contract.
Hard stop conditions / safety constraints:
- Never run a plain `alembic` command. The repo .env DATABASE_URL points at Supabase PRODUCTION and
  apps/api/migrations/env.py has no local-host guard. Inside the disposable lane use
  alembic_or_raise(disposable_dsn, ...); outside it, put DATABASE_URL=<localhost:5433 DSN> in front
  of the command.
- Never run `pytest tests/e2e_disposable/` directly — tests/conftest.py falls through to the shared
  dev DB on :5433 and would DROP its schema. Always go through scripts/e2e-disposable.sh.
- Confirm the concurrent debugger investigation in tests/e2e_disposable/ has finished before running
  any gate in that lane.
- Use .venv/bin/python3.11 -m pytest, never .venv/bin/pytest (broken shebang).
- Do not flip identity_coop_enabled. Do not add a migration. Do not touch identity_resolver.py.
- A gate that stays green under its named mutation is invalid — rewrite it, never accept it.
Next phase: EXECUTE — PVL is complete. Cycle-2 validation returned CONDITIONAL and supplement
cycle 2 has folded E1-E5 into the plan body; no further PVL cycle is required.
Validate contract: inline in plan (## Validate Contract — cycle-2 verdict, CONDITIONAL; E1-E4 applied
to the plan body by supplement cycle 2)
Execute start: fully-auto `.venv/bin/python3.11 -m pytest tests/unit/test_coop_expiry_guard.py`
| disposable-lane `scripts/e2e-disposable.sh` for tests/e2e_disposable/test_expiry_index_guard.py |
probe scenario: none | high-risk pack: yes (billing/credits class).
```

---

**Next:** Supplement cycle 2 applied (E1-E5 folded into the plan body against the cycle-2
CONDITIONAL contract). PVL is complete; EXECUTE is next.
