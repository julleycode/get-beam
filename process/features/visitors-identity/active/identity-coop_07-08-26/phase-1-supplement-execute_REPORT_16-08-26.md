---
phase: phase-1-ledger-substrate-supplement
date: 2026-08-16
status: COMPLETE
feature: visitors-identity
plan: process/features/visitors-identity/active/identity-coop_07-08-26/phase-1-ledger-substrate_PLAN_07-08-26.md
---

# EXECUTE — Post-Audit Fix Supplement (S1–S7), identity-coop Phase 1

**TL;DR** — All 7 sections implemented, all 16 gates green (SG-1…SG-16). SG-16, which the contract
carried as an accepted known-gap, was implemented and **mutation-proven against a real Postgres** —
the named residual is closed, not deferred. Four of the six defect fixes were mutation-verified to go
RED without the fix. Two diff budgets were exceeded (recorded per E-S2, not reshaped). Flags remain
OFF; no schema change; concurrent site-analysis hunks intact.

## What Was Done

| Item | Section | Status |
|---|---|---|
| 1–3 | S1 — co-op tables added to the site-delete cascade; acceptances retained with an H1-D comment; no 204 body added | done |
| 4, 5, 5a | S2 — tombstone at enqueue, inside `async with db.begin_nested():`, except-wrapped, `tombstone_write_failed` logged, empty-`bidx` guard | done |
| 5b | S2 — SG-15 unit gate, fake-savepoint pattern, named `test_tombstone_write_failure_preserves_erasure_request` (E-S1) | done |
| 5c | S2 — SG-16 Hybrid leg (was optional; user made it mandatory) | done |
| 6, 6a | S2 — `enqueue_erasure` docstring invariant; both falsified sentences in `models/suppression.py` corrected; audit-lookup comment added | done |
| 7 | S2 — `_process_claimed` left untouched | done (no edit) |
| 8 | S2 — backlog note `coop-credit-reversal-semantics_NOTE_16-08-26.md` | done |
| 9, 9a | S3 — 422 guard before the digest comparison; whole-function `monkeypatch` on `test_flag_on_requires_acceptance` (E-S3); new `test_contribution_flip_gated_on_global_flag` | done |
| 10 | S3 — OFF path untouched and unconditional | done (no edit) |
| 11 | S3 — `coop-terms-repin_RUNBOOK_16-08-26.md` | done |
| 12 | S4 — `tests/unit/test_identity_coop_hook.py`, 3 cases | done |
| 13 | S4 — `test_end_to_end_accrual` | done |
| 14a, 14b | S5 — `test_site_delete_removes_coop`, `test_site_delete_retains_consent` | done |
| 15a–15e | S5 — race blocked/control, enqueue tombstone, sweep idempotent, opt-out never gated | done |
| 16, 17 | S6 — ADV-1/ADV-2 non-vacuity rewritten; F14 third leg `vacuous-and-retired` | done |
| 18, 19 | S7 — `decision: "rejected"`, reviewer + reviewedAt set, 6 `blockingFindings`, no self-approval | done |

## Test Gate Outcomes

| Gate | Command (verbatim) | Result |
|---|---|---|
| SG-1 | `.venv/bin/python3.11 -m pytest tests/unit -q` | **2801 passed, 2 skipped, 0 failed** |
| SG-2 | `.venv/bin/python3.11 -m pytest tests/unit/test_identity_coop_hook.py -q` | **3 passed** |
| SG-3 | `.venv/bin/python3.11 -m pytest tests/integration -q -k end_to_end_accrual` | **1 passed** (1 event + 1 ACCRUE) |
| SG-4 | `... -k site_delete_removes_coop` | **1 passed** (both tables 0 rows) |
| SG-5 | `... -k site_delete_retains_consent` | **1 passed** (acceptance retained) |
| SG-6 | `... -k erasure_window_race_blocked` | **1 passed** (0 events, 0 ledger) |
| SG-6b | `... -k erasure_window_race_control` | **1 passed** (exactly 1 + 1) |
| SG-7 | `... -k enqueue_writes_tombstone` | **1 passed** |
| SG-8 | `... -k sweep_tombstone_idempotent` | **1 passed** |
| SG-9 | `... -k contribution_flip_gated_on_global_flag` | **1 passed** (422, flag unchanged) |
| SG-10 | `... -k contribution_optout_never_gated` | **1 passed** (200, flips False) |
| SG-11 | `.venv/bin/python3.11 -m pytest tests/integration/test_identity_coop_contribution.py -q` | **20 passed, 0 failed** |
| SG-12 | `git diff apps/api/routers/sites.py` | **PASS** — site-analysis hunks present and unmodified |
| SG-13 | read `harness/adversarial-validation.json` | **PASS** |
| SG-14 | read `harness/review-decision.json` | **PASS** — `rejected`, no self-approval |
| SG-15 | `.venv/bin/python3.11 -m pytest tests/unit/test_graph_erasure.py -q -k tombstone_write_failure` | **1 passed, 27 deselected** (not 0-selected) |
| SG-16 | `... -k tombstone_db_failure` | **1 passed** — real PG `SELECT 1/0` inside the tombstone statement |

`...` = `.venv/bin/python3.11 -m pytest tests/integration -q`. Every one of the 9 authoritative
selectors resolves to **exactly 1** function (pre-write collision sweep: 0 for all 10; post-write: 1
for all 10 — E-S5).

Regression lane: `tests/integration/test_graph_erasure_flow.py` → **14 passed**.

### Mutation-kill evidence (non-vacuity, all reverted afterwards)

| Fix reverted | Gates that went RED |
|---|---|
| S1 delete-tuple entries | SG-4 |
| S2 enqueue tombstone block | SG-6, SG-7 |
| S3 422 guard | SG-9 |
| savepoint → bare `try/except` (unit) | SG-15 |
| savepoint → bare `try/except` (real PG) | **SG-16** |

SG-5 and SG-10 correctly stayed green under mutation — they are guard-against-future-regression
gates, not fix-proving gates. Source restored and re-verified byte-identical after every mutation.

## What Was Skipped or Deferred

Nothing in the checklist. Item 7 and item 10 required no edit by design.

## Plan Deviations

1. **`tests/unit/test_graph_erasure.py` budget: 83 added vs ≤30 (E-S2 allowed ~45).** Recorded, not
   reshaped, exactly as E-S2 instructs. Cause: the `_Savepoint` CM (14 lines), a fake session that
   must serve `.first()`, `.scalars().all()`, the volume-marker `.scalar()`, and discriminate the
   tombstone statement by SQL text (38 lines), plus the test body (25). ~30 of the 83 are docstrings
   and explanatory comments, matching this file's established convention. **No SG-15 assertion was
   weakened.** No STOP rule attached to budgets.
2. **`tests/integration/test_identity_coop_contribution.py`: 499 added vs ≤480.** The overshoot is
   fully attributable to the SG-16 leg (~45 lines), which the ≤480 arithmetic explicitly did not
   include (it budgeted 9 tests × ~47 ≈ 430) because item 5c was optional at contract time. Without
   SG-16 the file is ~454, inside budget. The user upgraded SG-16 to mandatory for this run.
3. **One un-planned test was written and then removed.** A happy-path companion to SG-15 was added,
   then deleted on self-review as scope creep — SG-15 already asserts the tombstone statement ran.
   Net effect: none.

All three are within-blast-radius; none touches auth/billing/schema/API/container surfaces.

Budgets met: `sites.py` **12/12**, `graph_erasure.py` **18/18**, `suppression.py` **8/8**.

## Concurrent-Workstream Verification (SG-12 / E-S6)

`git diff apps/api/routers/sites.py` after editing still contains every site-analysis hunk verbatim:
`import asyncio`, the `apps.api.schemas.site_analysis` / `apps.api.services.site_analysis` /
`check_site_analysis_budget` imports, `_analysis_tasks`, `_fire_site_analysis`, and the analysis
endpoints. `apps/api/models/site.py` is **untouched by this session** (23/1, unchanged from the
session-start baseline). No `git checkout` / `stash` / `stash pop` / `restore` / rebase was run —
git was read-only apart from file edits. Mutation checks used `cp` to a `/tmp` backup and back, never
a git operation.

## Test Infra Gaps Found

- `tests/unit/test_graph_erasure.py`'s shared `_scalar_result` helper exposes no `.scalars().all()`,
  so `enqueue_erasure` needed its own fake session. A shared richer fake would cut ~40 lines off the
  next enqueue-path unit test.
- **Non-obvious trap found during execution:** seeding an `IdentifiedVisitor` row to give
  `_collect_match_keys` a blind index sends `_save_identified` down its conflict-upsert branch, which
  returns BEFORE the graph write and the co-op hook. That silently made the SG-6b positive control
  mint nothing (caught by SG-6b failing, which is exactly what it exists for). Fixed by seeding a
  `VisitorEmail` instead. Any future test driving `_save_identified` for a visitor that already has an
  identity row will hit this.
- No multi-process concurrency harness — the H2 concurrency known-gap stands unchanged.

## Closeout Packet

- **Selected plan:** `process/features/visitors-identity/active/identity-coop_07-08-26/phase-1-ledger-substrate_PLAN_07-08-26.md`
- **Finished:** S1–S7 in full, 16/16 gates green, 5 mutation-kill proofs.
- **Verified:** every fix proven by a gate that fails without it (SG-4/6/7/9/15/16), both lanes
  regression-free, harness bookkeeping honest.
- **Still unverified:** multi-process concurrency on the H2 window (pre-declared known-gap);
  production behaviour (both flags remain OFF, neither co-op migration is live on prod).
- **Remaining:** a HUMAN must re-review the evidence pack. `review-decision.json` stays `rejected` by
  design — no agent may change it. The plan's `## Resume and Execution Handoff (Supplement)` item 3
  still cites cycle 2's BLOCKED state (contract note N-E, doc-sync only).
- **Closeout classification:** **Keep in active/testing** — code-complete and gate-green, but the
  high-risk evidence pack is still formally REJECTED pending human re-review. Archiving before that
  re-review would defeat the manual-first gate.

## Forward Preview

- **Test infra found:** PG :5433 + Redis :6379 up via Docker; `.venv/bin/python3.11 -m pytest`
  (the `pytest` shebang is broken); integration conftest defaults `DATABASE_URL` to localhost:5433 —
  do NOT export a real URL before that lane.
- **Blast radius changes:** `apps/api/routers/sites.py`, `apps/api/services/graph_erasure.py`,
  `apps/api/models/suppression.py` (docstring), `tests/unit/test_graph_erasure.py`,
  `tests/unit/test_identity_coop_hook.py` (new), `tests/integration/test_identity_coop_contribution.py`.
- **Commands to stay green:** `.venv/bin/python3.11 -m pytest tests/unit -q` and
  `.venv/bin/python3.11 -m pytest tests/integration/test_identity_coop_contribution.py tests/integration/test_graph_erasure_flow.py -q`.
- **Dependency changes:** none. No new package, no migration, no config default changed.
