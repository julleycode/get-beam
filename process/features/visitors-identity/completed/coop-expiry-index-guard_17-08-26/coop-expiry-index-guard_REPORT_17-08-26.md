---
phase: coop-expiry-index-guard
date: 2026-08-17
status: COMPLETE_WITH_GAPS
feature: visitors-identity
plan: process/features/visitors-identity/active/coop-expiry-index-guard_17-08-26/coop-expiry-index-guard_PLAN_17-08-26.md
---

# EXECUTE report — co-op expiry index guard (F-B)

**TL;DR** — All 8 checklist steps applied. All 8 gates green (G1–G8). All 3 mandatory mutation
probes went RED with the correct mechanism and were reverted byte-exact (sha256-verified). One
real regression was found and fixed (DE-3 cross-test event-loop pollution caused by the new
G5a test). Three diff-budget breaches, all prose/test-length only — logic was not reshaped.
Status is **CODE DONE**, not `✅ VERIFIED`: user confirmation is still outstanding, and the
flag-OFF-only known-gap stands.

## What Was Done

| Step | Status |
|---|---|
| 1 — `_EXPIRE_INDEX_NAME`/`_TABLE`, `_index_verified`, `CoopExpiryIndexMissing` | done |
| 2 — `assert_expire_index(db)`, D3 predicate, positive-only cache, no try/except | done |
| 3 — guard called as FIRST statement of `run_coop_expiry_sweep`, before `_try_acquire_lock`; D1 docstring note | done |
| 4 — `CoopExpirySystemicFailure` with D4 docstring | done |
| 5 — `attempted` (before the `try`), `skipped`, `failures += 1` in the untouched `except` | done |
| 6 — post-loop `processed = attempted - skipped; if processed >= 1 and failures == processed:` + docstring | done |
| 7 — `tests/unit/test_coop_expiry_guard.py`, 5 legs, E2 applied | done |
| 8 — `tests/e2e_disposable/test_expiry_index_guard.py`, G1/G2/G4/G5, autouse cold-cache fixture, E3 applied | done |

E1 and E4 required no action: supplement cycle 2 had already folded them into the plan body
(caller table reads "8 call statements, 7 non-scheduler", no `test_diag_de5.py` row,
`test_lifespan_scheduler.py:280` correct, `test_identity_coop_ledger.py:745` enumerated; Goal 4
already scoped to "inside the loop"). E2, E3, E5 applied during execution.

**Test-infra route (recorded per the plan's note):** `at_pre_expire_unique` was **copied**, not
promoted to `conftest.py` — the Blast Radius mandates zero edits to existing test files. Drift was
minimised by *importing* `_PRE_EXPIRE_UNIQUE` and `_index_exists` from `test_migration_truth`
rather than duplicating them (same precedent as `test_de15` importing `_probe_lock_is_free`).

## Test Gate Outcomes

| Gate | Command (verbatim) | Result |
|---|---|---|
| G1 | `./scripts/e2e-disposable.sh guard -- .venv/bin/python3.11 -m pytest tests/e2e_disposable/test_expiry_index_guard.py -q -p no:randomly` | PASS |
| G2 | same run | PASS |
| G3 | `.venv/bin/python3.11 -m pytest tests/unit/test_coop_expiry_guard.py -q` | **5 passed** |
| G4 | same disposable run | PASS |
| G5 (a+b) | same disposable run | PASS |
| — | disposable file total | **5 passed in 33.15s** (re-confirmed after probes: 5 passed in 34.64s) |
| G6a | `git diff --stat -- apps/api/services/identity_resolver.py` | **empty** |
| G6b | `git diff -U0 -- apps/api/services/identity_coop.py \| grep -c '^[+-].*spendable_balance'` | **0** |
| G7a | `git status --porcelain apps/api/migrations/versions/` | only `?? c5a91f3e07d4_add_engage_outcomes.py` — a **concurrent session's** file, not mine. Scoped to this plan: empty. |
| G7b | `DATABASE_URL=postgresql+asyncpg://…@localhost:5433/beam .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` | `c5a91f3e07d4 (head)` — single head, **re-derived live**; this plan added no revision |
| G8 (i) | `.venv/bin/python3.11 -m pytest tests/integration/test_identity_coop_ledger.py -q` | **12 passed** |
| G8 (ii) | `./scripts/e2e-disposable.sh full2 -- .venv/bin/python3.11 -m pytest tests/e2e_disposable/ -q` | **42 passed** (= 37 baseline + 5 new) |
| G8 (smoke) | `.venv/bin/python3.11 -m pytest tests/unit/ -k coop -q` | 30 passed (non-proving) |

**Live alembic head re-derived at EXECUTE time: `c5a91f3e07d4`** — moved since the plan was
written (the concurrent session's `add_engage_outcomes`). Confirms the standing rule: never trust a
written-down head.

## Mutation Probes (all mandatory ones run)

| Probe | Mutation | Result | Mechanism observed |
|---|---|---|---|
| G1-1 | delete `await assert_expire_index(db)` | **RED** | raised sibling `CoopExpirySystemicFailure` (`identity_coop.py:637`) — type mismatch, and `coop_expiry_index_missing` absent |
| G1-2 | delete that line **and** `failures += 1` | **RED** | `DID NOT RAISE` at line 100 — reproduces the true pre-fix `return 0` silent behaviour |
| G4 | delete `failures += 1` | **RED** | `DID NOT RAISE` at line 163 |
| G3-d (extra) | `processed = attempted` (skip not subtracted) | **RED** on leg (d) only | confirms (d) is the sole skip-exclusion falsifier |
| G3-e (extra) | `attempted += 1` moved after the skip (FAIL-1) | **RED** on legs (d)+(e) | confirms the FAIL-1 regression gate is non-vacuous |

**Byte-exact revert proof:** `shasum -a 256` after every probe matched the pre-probe baseline
(`fa4c007e…` for `coop_expiry_sweep.py`, `2eeef08c…` for `identity_coop.py`); `git status` for both
files shows only the intended modification. Full lane re-confirmed GREEN after restore.

## Plan Deviations

1. **Diff-budget breaches (3).** Reported, not reshaped — logic is exactly as planned.
   | File | Budget | Actual | Note |
   |---|---|---|---|
   | `coop_expiry_sweep.py` | ≤50 +1 | **70 added / 0 deleted** | ~37 are code; the excess is entirely plan-MANDATED prose (D2 rationale + `validate_production` precedent + not-fail-open note, D3 comment, D1 two-sentence docstring note, the step-2 test-hygiene comment). One trimming pass was already applied (81 → 70). |
   | `identity_coop.py` | ≤25 added, 0 deleted | **34 added / 0 deleted** | ~18 are code; excess is the D4 exception docstring + the mandated `expire_lapsed_lots` docstring update. Trimmed 37 → 34. **0 lines deleted, as required.** |
   | `test_expiry_index_guard.py` | ≤200 | **229** | +29 for the copied fixture, the E3 assertion, and the DE-3 pollution fix below. |
   | `test_coop_expiry_guard.py` | ≤150 | 129 | within budget |
   Further trimming would have meant deleting documentation the checklist explicitly mandates.

2. **One test-file line added that the plan did not specify** — see the regression below. It is a
   teardown, not a relaxation: no assertion was weakened or removed.

## Regression Found and Fixed (not pre-existing)

The first full-lane run was **1 failed / 41 passed** —
`test_lifespan_scheduler.py::test_de3_coop_job_registered_with_correct_trigger`, with
`RuntimeError: Event loop is closed` and `coroutine 'Connection._cancel' was never awaited`.

Classified properly rather than dismissed as the known lane flake:
- baseline (my source reverted to HEAD content, new test file excluded): **37 passed, DE-3 green**
- `test_lifespan_scheduler.py` alone, with my change: **7 passed**
- ⇒ genuinely caused by the new file, only in full-lane order.

Cause: `test_g5a` is the **only** test in the lane that drives the app's *global*
`models.database.engine` (via `scheduler.async_session`, per E3) from its own event loop; it left a
pooled asyncpg connection bound to a loop that then closed, and the next file's global-session test
died on it. Fix: `await database.engine.dispose()` in a `finally` inside `test_g5a`. Full lane
re-run: **42 passed**. This is a lane hazard worth generalising — any test that touches the app's
module-level engine from a per-test loop must dispose it.

## Test Infra Gaps Found

- The global-engine disposal hazard above — candidate for an autouse lane fixture rather than a
  per-test `finally`, if a third test ever needs the global session.
- `at_pre_expire_unique` now lives in two files. Promotion to `conftest.py` remains the right
  end-state but is blocked by this plan's zero-existing-test-edit constraint.

## Concurrency / Safety Compliance

- **HEAD did not move:** `6a5b02d` before and after.
- **`git stash list` is still 11.** No stash, rebase, checkout, commit, or push was run. The only
  git writes were `git show HEAD:<path> > <path>` (a file write, used twice to obtain baselines) —
  both reverted byte-exact from `/tmp` backups, sha256-verified.
- **No forbidden path touched.** `git status` shows my edits confined to
  `apps/api/services/{coop_expiry_sweep,identity_coop}.py` + the two new test files. The other
  modified/untracked files (`config.py`, `main.py`, `drafts.py`, `auto_drafter.py`,
  `engagement_tracker.py`, `sender.py`, `platforms/*`, `engage_outcome*`, `c5a91f3e07d4`,
  `apps/web/`, `PRODUCT_ROADMAP.md`, campaigns-outreach/onboarding-canary) are the concurrent
  sessions' and were never opened for edit.
- **Every disposable container torn down:** `docker ps | grep -c '^e2e-'` = **0**. Six lanes were
  used sequentially (`guard`, `probe`, `base`, `a1`, `b1`, `full2`), never more than one at a time
  (ceiling 2).
- **No bare alembic ever run.** Inside the lane via `alembic_or_raise(disposable_dsn, …)`; outside
  it with `DATABASE_URL=…localhost:5433…` prefixed inline. `identity_coop_enabled` never flipped in
  `.env` — only monkeypatched per test via `coop_on`.

## Residuals That Fired

None of the pre-declared residuals fired during execution. All four remain open and unchanged:
INVALID-index false-green, `pg_indexes` catalog-error path, log-pipeline greppability, and the
**flag-OFF-only production gap** — `b7e4d21a9c58` is still unapplied to prod and no tier here can
prove first-flip behaviour.

## Closeout Packet

- **Selected plan:** `process/features/visitors-identity/active/coop-expiry-index-guard_17-08-26/coop-expiry-index-guard_PLAN_17-08-26.md`
- **Finished:** checklist steps 1–8; gates G1–G8; 3 mandatory + 2 extra mutation probes; one real
  regression found and fixed.
- **Verified:** on a disposable Postgres and the shared local PG only.
- **Unverified:** production behaviour on the first `identity_coop_enabled` flip; INVALID-index and
  catalog-error paths; log-pipeline visibility.
- **Remaining:** EVL independent re-run; user confirmation to move `CODE DONE` → `✅ VERIFIED`;
  operator runbook for the first flag flip.
- **Classification:** **Keep in active/testing** — `CODE DONE`, awaiting EVL + user confirmation.

## Forward Preview

- **Test infra found:** disposable lane healthy (42 tests); global-engine disposal hazard documented.
- **Blast radius changes:** none beyond plan (2 source + 2 new test files).
- **Commands to stay green:** `.venv/bin/python3.11 -m pytest tests/unit/test_coop_expiry_guard.py -q`;
  `./scripts/e2e-disposable.sh <lane> -- .venv/bin/python3.11 -m pytest tests/e2e_disposable/ -q`;
  `.venv/bin/python3.11 -m pytest tests/integration/test_identity_coop_ledger.py -q`.
- **Dependency changes:** none. No migration, no flag, no new package.
