---
name: plan:identity-coop-phase-2b-spend-wiring
description: "Identity Co-op — Phase 2b: wire credit spend into the monthly allowance (read gate + SPEND write, savepoint failure posture, per-user advisory lock, dashboard parity)"
date: 16-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
  phase: phase-2b
---

# Phase 2b — Spend Wiring

**Program:** identity-coop
**Umbrella plan:** `process/features/visitors-identity/active/identity-coop_07-08-26/identity-coop-umbrella_PLAN_07-08-26.md`
Complexity: COMPLEX (phase of a 4-phase program — 1, 2a, 2b, 3)
**Phase status: ⏳ PLANNED — not the next executable phase.**
Status: ⏳ PLANNED
Date: 16-08-26 (created 17-08-26 at the Phase 2 split)
**Report destination:** `process/features/visitors-identity/active/identity-coop_07-08-26/phase-2b-spend-wiring_REPORT_16-08-26.md`

**TL;DR** — Make earned credits actually buy monthly identity-resolution allowance: read credits in
`check_usage_allowed`, write the FIFO `SPEND` row in `increment_usage` on a SAVEPOINT, serialize the
draw with a per-**user** blocking advisory lock, and fix the dashboard/gate limit divergence. Nothing
here ships until Phase 2a is LIVE.

---

## Overview

See Purpose and Why This Plan Exists below for the narrative; this phase is one leg of the
identity-coop phase program. Ordering, gates, and program state live in the umbrella plan. This is
the **spend half** of the pre-split Phase 2; the consumption + expiry half is Phase 2a.

---

## Why This Plan Exists (the split, recorded 17-08-26)

Five PVL cycles plus three independent adversarial rounds produced a **stable design core** — the
savepoint posture, lock acyclicity, REVERSE idempotence, and the K-4 orphan premise all survived
repeated attack. But every fix cycle produced a NEW defect of one class: **a gate that passes on the
implementation it exists to forbid** (vacuous-green). Root cause is phase SIZE: one plan covering
ledger vocabulary + consumption aggregation + expiry sweep + spend wiring + locking + failure posture
cannot be gated coherently. **The user chose the split over more PVL cycles (explicit decision,
16-08-26.)** This plan carries the spend half.

---

## Entry Gate — **NOT MET**

| Link | Required state |
|---|---|
| **Phase 2a LIVE** | `phase-2-consumption-spend_PLAN_07-08-26.md` (Phase 2a) must be ✅ VERIFIED **and merged**, with `expire_lapsed_lots`, `spendable_lots`, S-10b stamping, and the S-4 clamp all shipped. 2b's SPEND writer inherits the stamping contract from 2a's live code — building it against an unshipped 2a re-opens F-1. |
| Phase 2a G-18 leg 5 green | The positive expiry proof must be green, i.e. the sweep demonstrably fires. A never-firing sweep plus a live spend path produces a ledger whose EXPIRE side is silently absent. |
| Constraint (d) — `coop_terms_version` | Still a PLACEHOLDER digest; legal review + re-pin required before ANY flag flip. 2b must not assume a flag can be flipped for a live gate (K-3). |
| K-4 orphan SPEND | **PRE-FLAG-FLIP BLOCKER carried by this phase** (see Known-Gaps). Must be closed before `identity_coop_enabled` is flipped ON — not before EXECUTE. |
| Alembic head | Re-derive LIVE with `DATABASE_URL` pinned to `localhost`. 2b expects **no new migration**; if one appears, that is a scope finding. |

---

## Purpose

Phase 2a made credits countable and expirable. Phase 2b makes them **spendable**: a user at their
monthly plan limit who holds spendable co-op credit gets additional resolutions, and each one writes
an auditable negative `SPEND` row against the drawn lot.

---

## Blast Radius

Risk class: **billing/credits** (auth-adjacent enforcement path). Hybrid gate minimum.

| File | Change | Budget |
|---|---|---|
| `apps/api/services/identity_coop.py` | `spend_credits` (FIFO draw, per-user lock, S-10b stamping, S-5 clamp) | **~140 lines added** |
| `apps/api/services/billing.py` | read gate in `check_usage_allowed` + SPEND write in `increment_usage` (incl. the `.returning(...)` + `get_effective_plan`/`get_effective_limit` derivation (S-13), the **SAVEPOINT** block + anti-simplification comment (S-13b), and the two NEW imports `settings` + coop service (C3-4)); **no signature changes** | **≤70 lines** |
| `apps/api/routers/billing.py` | `monthly_limit` extended by spendable co-op credit behind the `identity_coop_enabled` short-circuit + `is not None` unlimited guard (S-15b / C-4) | **~7 lines** |
| `tests/integration/test_identity_coop_spend.py` | NEW — carries G-5, G-6, G-7, G-8, G-10, G-14, G-16. Declares `pytestmark = pytest.mark.integration` (S-26). | **~510 lines** |
| `phase-blast-radius-registry.md` | Phase 2b claim entry | **1-2 lines** |

**5 files.** No migration expected.

**Explicitly NOT touched:** `apps/api/services/identity_resolver.py` (empty diff is an exit gate,
G-13), `Site.daily_resolution_budget`, the BODY of `get_effective_limit`, `spendable_balance`'s
QUERY at `identity_coop.py:242-247` (Constraint 11), `apps/api/routers/visitors_helpers.py`
(read-only semantic consumer — C-5, **no code change**), `apps/api/tasks/`, `visitor_aggregator`,
`apps/api/models/identity_coop.py` (2b adds no vocabulary — REVERSE is K-1).

---

## Decisions Carried Verbatim From the Pre-Split Phase 2

> **Provenance note (honesty, 17-08-26).** The narrative bodies of P2-D3 and P2-D6 lived only in the
> pre-split working copy that the 2a rewrite replaced. What follows is their **operative content**,
> reproduced verbatim from the checklist items (C3, C4), supplement items (S-13, S-13b, S-14, S-15,
> S-15b, S-15c, S-16), Constraints (9, 12b, 16, 17), and gate texts (G-5, G-6, G-7, G-10, G-16) that
> restated them — those restatements are the parts EXECUTE actually consumes. The archived cycle-5
> validate-contract in `phase-2-consumption-spend_PLAN_07-08-26.md` retains the surrounding
> discussion. **PVL should re-derive the rationale from source rather than trusting a summary.**

### P2-D3 — Read credits in `check_usage_allowed`, write SPEND in `increment_usage` (the crux)

**Read side.** Inside `check_usage_allowed` (`apps/api/services/billing.py:94`), AFTER the limit
computation (`:110`) and at the comparison (`:130`) — when `limit is not None and count >= limit`,
compute user-level spendable credit via the D-D join
(`identity_credit_ledger.site_id → sites.site_id → sites.user_id == user_id`) and allow when
`count < limit + credit`. **Short-circuit on `settings.identity_coop_enabled` before any coop
query**, so flag-off billing is byte-identical (proves G-8).

**Write side.** Inside `increment_usage`: when the post-increment counter exceeds
`plan_limit + referral_bonus`, draw **1 credit FIFO by `expires_at` ASC across ALL the user's sites'
lots** (pooled at spend time), writing one `SPEND` row stamped with **the drawn lot's own `site_id`**
(attribution preserved) and that lot's `spendable_at`/`expires_at` (S-10b/S-16), reason
`monthly_allowance_spend`. Same transaction as the counter increment — `increment_usage` commits at
`services/billing.py:147` (the former `:141` citation is stale; locate by the `async def
increment_usage` symbol); **no second commit**, and issue the SPEND insert BEFORE that commit.

**Threshold derivation (exact, S-13):**
1. Add `.returning(User.monthly_identified_count)` to the existing `update(User)` statement — a
   re-`select()` is racy and is **rejected**. Use `scalar_one_or_none()` + **early return**: today a
   nonexistent user is a silent no-op, and that behavior must be preserved explicitly.
2. Derive the ceiling with `get_effective_plan(user.plan, user.current_period_end)` →
   `get_effective_limit(effective_plan, user.bonus_monthly_quota)` (`billing.py:60-65`) — the
   identical pair `check_usage_allowed` uses at `:108-110`. Raw `user.plan` would let a lapsed paid
   plan draw at the wrong threshold.
3. `limit is None` (unlimited) returns before any coop query.

**Imports (C3-4 — neither exists today).** `apps/api/services/billing.py` imports only datetime /
typing / structlog / sqlalchemy / `models.user` (`:1-10`). Both the read short-circuit and the write
path require adding **`from apps.api.config import settings`** AND an import of
`apps.api.services.identity_coop`. **Check for a circular import at EXECUTE** (`identity_coop` must
not import `billing`); if a cycle exists, use a function-local import inside `increment_usage` /
`check_usage_allowed` rather than restructuring either module. The ≤70-line budget absorbs both.

**No signature change** to `check_usage_allowed`, `increment_usage`, or `get_effective_limit`
(Constraint 9) — but **signature freeze does NOT imply semantic freeze.** The "no signature change ⇒
no call-site audit" inference is **DELETED as unsound** (C-4/C-5). The **5-caller census** stands:
- 3 enforcement callers pairing `check_usage_allowed` with `increment_usage` — `routers/visitors.py:953`
  (increment at `:969`), `tasks/resolution_tasks.py:120` (increment `:135`),
  `services/resolution_runner.py:161` (increment `:178`). No edit needed, but **audited, not assumed**.
- 2 **read-only** consumers whose displayed semantics change: `routers/billing.py:317` (and the
  `:328` `monthly_limit` expression — see S-15b) and `routers/visitors_helpers.py:284`
  (`_skip_reason` → `monthly_plan_limit_reached`; credits suppress the limit-reached copy — intended).
  **Both live under `routers/`, not `services/`** — the earlier `services/visitors_helpers.py`
  citation was a wrong package path.

**Accepted display consequence (M-2).** After credits are spent, `count > monthly_limit` on
`GET /billing/status` is **expected display**, not a bug — asserted as such in G-16 leg 4.

### P2-D6 — Co-op draw failures are SWALLOWED inside `increment_usage`; the counter is authoritative

The counter is the enforcement record. A co-op draw failure must never cost the user an already-
delivered resolution, and must never 500 a request that succeeded.

**The savepoint shape (mandatory, S-13b / F3-1) — a bare `try/except` is FORBIDDEN:**

```
try:
    async with db.begin_nested():        # SAVEPOINT
        ...coop draw: user read → D-D join → advisory lock → SPEND insert...
except Exception:
    logger.exception("coop_spend_failed", user_id=…)   # no PII
# exactly ONE commit(), here — never inside the except
```

**Why a bare `try/except` is a defect, not a simplification:** a DB-level error inside the block
aborts the enclosing transaction, so the later commit raises (`PendingRollbackError`) and the counter
is **LOST** *and* the exception escapes to the unwrapped caller — both outcomes P2-D6 exists to
prevent. Only pure-Python failures behave otherwise, which is exactly why the G-7 gate needs its
genuine-DB-error leg. Precedents to cite in the source comment: `services/identity_coop.py:175`,
`routers/sites.py:206`, and the verbatim anti-simplification warning at
`services/graph_erasure.py:218-231`.

- **`pg_advisory_xact_lock` is transaction-scoped and is NOT released by the savepoint rollback.**
  Harmless — **do not "fix" it.**
- The counter `UPDATE` itself stays **OUTSIDE** the try, so a failure there keeps today's behavior
  byte-for-byte (Constraint 17).
- **Never re-raise** — no exception may escape `increment_usage` from the coop path
  (`routers/visitors.py:969` calls it **unwrapped**; a propagating exception 500s a request that
  actually succeeded).
- Rationale: `record_contribution` already committed (`services/identity_coop.py:157,202`), so
  rolling back the counter would make the resolution **FREE**.
- **Accepted consequence:** a swallowed failure leaves a counter increment with no SPEND row (ledger
  under-reports; the counter remains the enforcement record).

**Batch-kill blast radius (adversarial, load-bearing for G-7 leg vi).** A poisoned session does not
stop at one request: `check_usage_allowed` (`resolution_runner.py:161`) sits **OUTSIDE** the
per-visitor `try` (`:172`, `except` at `:182`) while `increment_usage` (`:178`) sits **inside** — so
under a bare try/except an aborted transaction kills the whole **BATCH**, not one visitor. Same shape
at `tasks/resolution_tasks.py:120` / `:135`.

### S-14 — the draw lock is `pg_advisory_xact_lock`, BLOCKING, keyed on `user_id`

The FIFO draw lock is keyed on **`user_id`** (the draw is user-pooled); Phase 1's per-site lock is
necessary but **insufficient**. **The call MUST be `SELECT pg_advisory_xact_lock(hashtext(:key))`
with `key = str(user_id)`.** The ubiquitous `pg_try_advisory_lock` + skip-on-False shape is
**FORBIDDEN on the draw path** (Constraint 16) — it silently forgives spends.

---

## Findings Carried Verbatim (do NOT re-derive)

### F5-1 — OPEN FAIL, must be fixed in this phase

**G-6 as currently written cannot discriminate try-and-skip.** `increment_usage`'s counter `UPDATE`
takes a **users-row exclusive lock held to COMMIT**, so two concurrent same-user calls **serialize
BEFORE reaching the advisory lock**. `pg_try_advisory_lock` would therefore always return `True`, and
both the correct and the try-and-skip shapes conserve identically — **S-14's motivating scenario is
impossible via this caller.** The gate proves nothing about the lock it exists to justify.

**FIX (both parts mandatory):**
1. Add a G-6 leg that drives **`spend_credits()` directly from N distinct sessions** (bypassing
   `increment_usage`, so no users-row lock is taken), asserting **exactly N SPEND rows** for a user
   holding ≥N spendable credits.
2. Add a **Fully-Automated grep gate** asserting `pg_try_advisory_lock` never appears on the draw
   path.

**Where the real try-and-skip loss surface lives:** contention with the **sweep / reverse paths**,
which hold the user lock **WITHOUT touching the users row** — those are the callers that can actually
reach the advisory lock concurrently with a draw.

### Gap 5 / M3-4 — G-7 leg (v) names an impossible injection

G-7's DB-level-error leg proposed forcing an `IntegrityError` by inserting a **duplicate ledger row**.
**`identity_credit_ledger` has NO unique constraint** — three plain indexes at
`models/identity_coop.py:129-131`; the partial-unique index is on **`identity_contribution_events`**,
a different table. **Mandate instead:** `await session.execute(text("SELECT 1/0"))` **or** a NOT NULL
violation on `identity_credit_ledger.reason`. **Warning:** adding a unique index to make the original
injection work would violate the no-DDL constraint — do not.

### Additional verbatim carries

- **G-6-vs-G-10/S-17 regime split (state it in the test docstring so a future reader does not
  "restore" a deny assertion):** credits **remaining** ⇒ a lost spend is a **defect**; credits
  **exhausted** ⇒ an un-backed increment is **bounded, accepted noise**. The property that kills
  try-and-skip is **CONSERVATION, not denial** — N credits + N concurrent calls ⇒ fewer than N SPEND
  rows is the defect signature. There is **no deny channel** in this design (the counter `UPDATE` is
  outside the try, `increment_usage` returns `None`, no exception may escape), so any gate demanding
  "one call is blocked/denied" is **UNPASSABLE by a correct implementation** and must not be written.
- **`.returning()` must use `scalar_one_or_none()` + early return** — today a nonexistent user is a
  silent no-op; preserve that explicitly.
- **The unlimited-plan `None` guard on the `routers/billing.py` `monthly_limit` fix is mandatory**
  (S-15b / C2-4): without `if settings.identity_coop_enabled and monthly_limit is not None:` this
  raises `TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'` for every Max/unlimited
  user hitting `GET /billing/status`. The read gate already handles `limit is None`; the router side
  did not.
- **Distinct sessions are mandatory for every concurrency test** — precedent
  `tests/integration/test_campaign_double_send.py:113-122`
  (`async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)` +
  `asyncio.gather(..., return_exceptions=True)`, **one session per coroutine**);
  `tests/conftest.py:92-96` creates the engine with `pool_size=5`, which supports N=3. A SHARED
  `AsyncSession` produces **no contention at all** — asyncpg serializes on one connection — so the
  gate would be vacuous.
- **`SET LOCAL lock_timeout = '5s'` in every concurrency gate coroutine** (or wrap the gather in a
  pytest timeout). Blocking `pg_advisory_xact_lock` in the SERIALIZED shared-`retarget_agent_test`
  lane otherwise hangs the entire integration run with no diagnostic if a holder errors before commit.

---

## Implementation Checklist

> IDs are **stable identifiers** preserved from the pre-split Phase 2 (S-5, S-13.., S-17, G-5..G-16).
> Do NOT renumber.

### Step C — Spend against monthly allowance

- [ ] C1. Add `async def spend_credits(db, site_id_or_user, amount, *, reason) -> int` to `apps/api/services/identity_coop.py` — draws FIFO across the user's `spendable_lots`, writing one `SPEND` row per lot drawn (negative `amount`, `lot_id` set, **stamped per S-10b with the drawn lot's `spendable_at`/`expires_at`**, `site_id` = **the drawn lot's own** `site_id` per S-16). Returns the amount actually spent (may be less than requested). Never allows the balance to go negative.
- [ ] C2. **S-14** — take `SELECT pg_advisory_xact_lock(hashtext(:key))` with `key = str(user_id)` around the draw. BLOCKING, transaction-scoped. `pg_try_advisory_lock` is FORBIDDEN here (Constraint 16).
- [ ] C3. **P2-D3 read side** — implement exactly as stated above in `check_usage_allowed`. Short-circuit on `settings.identity_coop_enabled` before any coop query. No signature change.
- [ ] C4. **P2-D3 write side** — implement exactly as stated above in `increment_usage`, on the S-13b savepoint. Do NOT touch `Site.daily_resolution_budget` (`models/site.py:23`) anywhere in this phase.
- [ ] C5. Confirm no new external call was introduced (this phase introduces none) — record it explicitly in the phase report.
- [ ] S-5. `spend_credits` treats `balance <= 0` as zero spendable — **no spend may ever create a negative balance.**
- [ ] S-13. Threshold derivation + imports + circular-import check, per P2-D3 above. Budget ~30 lines in `billing.py`.
- [ ] S-13b. Savepoint failure posture, per P2-D6 above. Budget ~12 lines.
- [ ] S-15. Read-path short-circuit + the (unsound) no-audit inference deletion — the P2-D3 census IS the audit.
- [ ] S-15b. `routers/billing.py` `monthly_limit` extension with the `is not None` unlimited guard. **Locate by the `monthly_limit=get_effective_limit(` string, not by line.** Reuse the SAME user-level spendable-credit helper the read gate uses — no second query shape. Budget ~7 lines.
- [ ] S-15c. **No code change** — record in the phase report that `routers/visitors_helpers.py:284` is a second read-only semantic consumer whose behavior change is intended.
- [ ] S-16. Each SPEND row stamped with the drawn lot's own `site_id` + that lot's `spendable_at`/`expires_at`.
- [ ] S-17. Edge-case tests (billing surface — Critical/High only) in `tests/integration/test_identity_coop_spend.py`, including the **L-3 TOCTOU bounded-noise** case and the monthly-reset case. Gated by G-10.
- [ ] S-17b. **K-4 orphan SPEND** — record as an accepted known-gap AND a **pre-flag-flip blocker** (below). No code change in this phase.
- [ ] S-25 / S-26. Budget sweep, `-k` selector re-grep, and the module-level `pytestmark = pytest.mark.integration` declaration on the new test file.

### Step D — Tests

- [ ] D1. `test_graph_hit_increments_consumption_not_provider_spend` (**AC-4** — the provider-spend half 2a could not prove).
- [ ] D2. `test_spend_decrements_balance_and_writes_ledger_row` (**AC-6**).
- [ ] D7. `test_daily_budget_untouched` — `Site.daily_resolution_budget` identical before and after a credit spend (G-14).
- [ ] D8. `test_flag_off_billing_behavior_unchanged` — with `identity_coop_enabled=False` the effective monthly limit equals the plan limit exactly, and **zero coop queries are issued** (G-8).
- [ ] D6b. `test_hold_window_blocks_spend` — the spend-side half: a lot inside its 24h hold cannot be **spent** (2a proved only that it is not *returned/counted*).

---

## Constraints (hard, non-negotiable)

> Numbers are stable identifiers shared with Phase 2a and the K-1 note. Do NOT renumber.

1. **All flags stay OFF** during EXECUTE. `identity_coop_enabled` and every `contribution_enabled` remain OFF; production exposure is NONE.
2. **No schema change.** No DDL, no migration, no `LEDGER_ENTRY_TYPES` edit (REVERSE is K-1).
3. **`DATABASE_URL` pinning is mandatory** for every alembic or DB-script invocation.
4. **Integration runs are SERIALIZED**; no stray local Redis on 6379.
5. **`git diff HEAD -- apps/api/services/identity_resolver.py` must stay EMPTY.**
6. **`Site.daily_resolution_budget` is untouched.**
8. **No `user_id` column on the ledger; no per-site monthly gate** (Phase 1 D-D freeze). The user-level view is a **JOIN at read/draw time**, never a column.
9. **No signature change** to `check_usage_allowed`, `increment_usage`, or `get_effective_limit` — but signature freeze does **NOT** imply semantic freeze; the 5-caller census is mandatory, not optional.
10. **Every flag-flipping test uses the `monkeypatch` fixture for the whole function**, never bare `setattr`.
11. **`spendable_balance`'s query shape is frozen.**
12. **Every non-ACCRUE ledger row carries its source lot's `spendable_at`/`expires_at`** — here, SPEND.
12b. **No writer may produce a negative spendable balance.** `spend_credits` is clamped by S-5. **SCOPE (adversarial M-B):** per-writer clamping composes **only under serialized writers**; `spendable_balance` is a frozen FLAT SUM with no per-lot floor. In 2b the balance-reducing writers are `spend_credits` (user-locked) and 2a's `expire_lapsed_lots` (single-instance sweep). **If K-1's unlocked `reverse_credit` is ever built, it MUST take the same user-keyed lock** or 12b stops composing — that requirement travels with K-1.
13. **The AC-8 oracle is never "unconditional."** Same sanctioned clock mechanisms as 2a.
14. **No gate may require a real deployment flag flip** (K-3).
16. **No repo-precedent copying for the FIFO draw lock.** Blocking `pg_advisory_xact_lock`; the `pg_try_advisory_lock` + skip-on-False shape is FORBIDDEN there.
17. **No exception may escape `increment_usage` from the co-op path**, and the counter is committed regardless of co-op outcome.

---

## Exit Gate

```bash
.venv/bin/python3.11 -m pytest tests/unit -q
.venv/bin/python3.11 -m pytest tests/ -m integration -q          # SERIALIZED; PG :5433 + Redis 6379
git diff HEAD --quiet --exit-code -- apps/api/services/identity_resolver.py
grep -rn "pg_try_advisory_lock" apps/api/services/identity_coop.py apps/api/services/billing.py
# Expected: NO match on the draw path (F5-1 fix, part 2)
```

- All checklist items checked; G-5..G-16 green.
- **G-6's direct-`spend_credits` leg is green** (F5-1 fix, part 1) — the `increment_usage` leg alone does not satisfy G-6.
- **G-7 leg (v) uses `SELECT 1/0` or a `reason` NOT NULL violation** — never the impossible duplicate-row injection (Gap 5).
- `Site.daily_resolution_budget` provably untouched; resolver diff empty.
- Phase report written to the report destination above.

---

## Acceptance Criteria

- **AC-4** — a graph-served resolve increments graph consumption and NOT provider spend; a provider-purchased resolve does the inverse.
- **AC-6** — a spend decrements the balance and writes a negative-amount `SPEND` ledger row with `site_id`, `reason`, `timestamp`.
- With `identity_coop_enabled=False`, billing behavior is byte-identical to today, and **zero coop queries are issued**.
- `Site.daily_resolution_budget` is provably untouched by any credit spend.
- `GET /billing/status`'s `monthly_limit` equals the ceiling `check_usage_allowed` actually enforces (no 52/50 divergence), and an unlimited plan returns `monthly_limit: null` with a 200 — never a `TypeError`/500.

---

## Phase Completion Rules

- 🔨 **CODE DONE** — all checklist items checked, no test evidence yet.
- 🧪 **TESTING** — both pytest lanes running; failures fixed inline.
- ✅ **VERIFIED** — both lanes exit 0, G-5..G-16 green **including G-6b and G-6c**, resolver diff empty, validate-contract written (non-placeholder), and the outcome explicitly confirmed by the user.
- 🚧 **BLOCKED** — Phase 2a not LIVE, or a circular import between `billing` and `identity_coop` cannot be resolved with a function-local import.
- A green G-6a without G-6b does NOT prove the advisory lock (F5-1) and does NOT satisfy this phase.
- K-4 stays open at ✅ VERIFIED — it is a **pre-flag-flip** blocker, not a pre-EXECUTE one.

---

## Phase Loop Progress

- [ ] 0. ENTRY GATE — Phase 2a LIVE (see Entry Gate above). **Currently NOT MET.**
- [ ] 1. RESEARCH
- [ ] 2. INNOVATE
- [ ] 3. PLAN-SUPPLEMENT
- [ ] 4. PVL — full V1-V7 **from V1**; this plan has never been validated
- [ ] 5. EXECUTE
- [ ] 6. EVL
- [ ] 7. UPDATE PROCESS

---

## Touchpoints

**MODIFIED / NEW (5 files):** `apps/api/services/identity_coop.py`, `apps/api/services/billing.py`,
`apps/api/routers/billing.py`, `tests/integration/test_identity_coop_spend.py` (NEW),
`phase-blast-radius-registry.md`.

**READ ONLY (audited, not edited):** `apps/api/routers/visitors.py:953,:969`,
`apps/api/tasks/resolution_tasks.py:120,:135`, `apps/api/services/resolution_runner.py:161,:178`,
`apps/api/routers/visitors_helpers.py:284`, `apps/api/models/site.py`,
`apps/api/models/identity_coop.py`, `apps/api/services/identity_resolver.py` (empty-diff exit gate).

---

## Public Contracts

- **No signature change** to `check_usage_allowed`, `increment_usage`, `get_effective_limit` (Constraint 9).
- **Semantics DO change** for 2 read-only consumers: `routers/billing.py` (`monthly_limit` now includes credit) and `routers/visitors_helpers.py:284` (`_skip_reason` copy suppressed when credits exist). Both intended, both recorded.
- `api_usage_logs` write path UNCHANGED; `identity_resolver.py` UNCHANGED.
- `Site.daily_resolution_budget` semantics UNCHANGED.
- `LEDGER_ENTRY_TYPES` UNCHANGED.
- New scheduled surface: none.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| **G-5** `-k "coop_fifo_user_pooled_draw"` — a 2-site user's oldest-`expires_at` lot is drawn first regardless of which site triggered; the SPEND row carries the **drawn lot's** `site_id` | Hybrid (PG) | P2-D3 write side / S-16 |
| **G-6a** `-k "coop_concurrent_increment_no_double_draw"` — N concurrent over-limit `increment_usage` calls for ONE user holding ≥N spendable credits produce **EXACTLY N SPEND rows**; counter delta equals SPEND count. Run at N=2 and N=3. Distinct sessions + `SET LOCAL lock_timeout = '5s'` mandatory. **Negative leg:** with 1 spendable credit and 2 concurrent over-limit calls, assert **exactly 1 SPEND row**, **counter delta == 2**, `spendable_balance == 0` — the un-backed increment is the **bounded** S-17 accepted noise (assert bounded, never zero). **This gate does NOT prove the lock** — see G-6b. | Hybrid (PG, distinct sessions) | conservation / S-17 regime split |
| **G-6b (NEW — F5-1 fix, part 1)** `-k "coop_spend_credits_direct_concurrency"` — drive **`spend_credits()` directly from N distinct sessions**, bypassing `increment_usage` (so no users-row exclusive lock is taken and the advisory lock is actually reached), for a user holding ≥N spendable credits; assert **exactly N SPEND rows**. Docstring must state: `increment_usage`'s users-row lock serializes callers BEFORE the advisory lock, so the G-6a path can never discriminate try-and-skip. | Hybrid (PG, distinct sessions, `lock_timeout`) | **S-14 / Constraint 16 — the only gate that proves the lock** |
| **G-6c (NEW — F5-1 fix, part 2)** `grep -rn "pg_try_advisory_lock" apps/api/services/identity_coop.py apps/api/services/billing.py` → **no match on the draw path** | **Fully-Automated** | Constraint 16 |
| **G-7** `-k "coop_spend_failure_swallowed"` — force the failure INSIDE `increment_usage`, between the counter `UPDATE` and its `await db.commit()` (`billing.py:142-146` then `:147` — locate by symbol). Assert the DECIDED posture, not atomicity: (i) the counter increment **IS committed** — read back from a **SEPARATE, fresh session after the call returns**; (ii) **no SPEND row exists**; (iii) **no exception escapes**; (iv) invoke the unwrapped route path (`routers/visitors.py:969`) and assert **no 500 reaches the caller**. **Leg (iv) construction cost, named so EXECUTE cannot drop it as "covered by (iii)":** needs (1) auth override, (2) site access, (3) the `is_resolution_candidate` gate, (4) a monkeypatched `IdentityResolver.resolve`. Precedent `tests/integration/test_usage_limits.py`. | Hybrid (PG) | P2-D6 |
| **G-7 leg (v) — MANDATORY, without it the gate is VACUOUS** | Hybrid (PG) | P2-D6 / savepoint shape |
| **G-7 leg (vi) — batch-kill** | Hybrid (PG) | P2-D6 blast radius |
| **G-8** `-k "coop_flag_off_billing_unchanged"` — with `identity_coop_enabled=False` the effective limit equals the plan limit exactly and **zero coop queries are issued** | Hybrid (PG) | flag-default-OFF precedent |
| **G-10** `-k "coop_edge"` — all seven S-17 cases (six original + the L-3 TOCTOU bounded-noise case) | Hybrid (PG) | S-17 |
| **G-14** `-k "coop_daily_budget_untouched"` | Hybrid (PG) | spend-target decision (monthly, not daily) |
| **G-16** `-k "coop_status_limit_matches_gate"` — four legs: (1) **pre-spend parity** — for a user at/over the plan limit holding ≥1 spendable credit, `GET /billing/status`'s `monthly_limit` equals the ceiling `check_usage_allowed` enforces; (2) **seeding precondition** — "holding ≥1 spendable credit" requires a lot whose `spendable_at` is already past, so seed it explicitly or `monkeypatch` `coop_credit_hold_hours=0` (the 24h hold otherwise makes this leg vacuous); (3) **unlimited plan** — a Max/unlimited user gets a **200 with `monthly_limit: null`**, NOT a `TypeError`/500; (4) **post-spend** — `count > monthly_limit` asserted as **expected display**. Flag OFF ⇒ response byte-identical. | Hybrid (PG) | C-4 / S-15b |
| **G-13** `git diff HEAD --quiet --exit-code -- apps/api/services/identity_resolver.py` | Fully-Automated | zero-new-write-surface |
| **G-11 / G-12** unit + integration lanes | Fully-Automated / Hybrid | P2-D4 |

### G-7 leg (v) — GENUINE DB-LEVEL ERROR (mandatory)

The monkeypatched Python `raise` in the base gate does **NOT** abort the Postgres transaction, so all
four legs (i)-(iv) pass green on the **defective bare-`try` implementation** — the gate cannot
distinguish the defective shape from the correct savepoint shape, and it is the sole proof of P2-D6.
Leg (v) therefore injects a **real DB error inside the coop block** and asserts the SAME four
properties, **each read back from a fresh session after the call returns**. Under a bare `try/except`
this leg FAILS on both (i) (counter lost — `PendingRollbackError` on the commit) and (iii) (exception
escapes). **Keep the Python-raise leg — it covers the pure-Python half.**

**Injection mechanism (Gap 5 / M3-4 — the original is impossible):** use
`await session.execute(text("SELECT 1/0"))` **or** a NOT NULL violation on
`identity_credit_ledger.reason`. The originally-specified duplicate-ledger-row `IntegrityError` is
**unwritable — `identity_credit_ledger` has NO unique constraint** (three plain indexes at
`models/identity_coop.py:129-131`; the partial-unique index is on `identity_contribution_events`).
**Adding a unique index to make it work would violate the no-DDL constraint — do not.**

### G-7 leg (vi) — batch-kill

Drive `run_resolution_for_site` (`services/resolution_runner.py`) with 2+ visitors, force the
DB-level coop error on visitor N, and assert visitor N+1 still processes. `check_usage_allowed`
(`:161`) sits **OUTSIDE** the per-visitor `try` (`except` at `:182`) while `increment_usage` (`:178`)
sits inside, so under a bare try/except the aborted transaction kills the whole BATCH. If a full
runner leg proves too costly, an equivalent minimal leg is acceptable: after the forced DB-level
failure, assert a SUBSEQUENT `check_usage_allowed(db, user_id)` **on the same session** succeeds.

### Known-Gaps

| ID | Gap | Status |
|---|---|---|
| **K-4** | **Orphan SPEND row surviving a concurrent site delete.** The site-delete cascade (`routers/sites.py:344-345`) deletes site A's `identity_contribution_events` + `identity_credit_ledger` rows, but a SPEND row **inserted concurrently** and stamped `site_id = A` (the drawn lot's site, per S-16) survives — leaving a lone negative row: phantom debt that suppresses the user's OTHER sites' credits, and that any re-created site reusing `site_id = A` (the **designed** reclaim at `routers/sites.py:167-194`) would inherit, silently swallowing its first accrued credit. That is precisely the resurrection class the cascade exists to close. | **Accepted ONLY WHILE FLAGS ARE OFF — PRE-FLAG-FLIP BLOCKER.** No shared lock; bounded by the S-4/S-5 clamps to "can only zero a balance, never grant"; flags OFF ⇒ production exposure NONE; detectable by a dangling `lot_id`. **MUST be closed before `identity_coop_enabled` is flipped on.** |
| **K-1** | REVERSE / clawback-debt semantics | Backlogged — `backlog/coop-credit-reversal-semantics_NOTE_16-08-26.md`. Gate stays CONDITIONAL on this row. |
| **K-2** | Multi-process concurrency on the H2 enqueue→sweep window | Inherited accepted (constraint e) |
| **K-3** | Any live flag-on gate | Blocked by constraint d (`coop_terms_version` placeholder pending legal re-pin) |

---

## Test Infra Improvement Notes

- **Multi-site-per-user fixture infra does not exist today.** This repo has no test asserting `User.monthly_identified_count` against a `site_id`-scoped credit balance. P2-D3's user-pooled draw needs it — G-5/G-6 must build it.
- **No existing test forces a rollback around `increment_usage`.** G-7 needs one, plus a **second fresh session** to observe the committed counter afterwards. No fresh-session read-back helper exists in the integration conftest today.
- **The concurrency harness DOES exist** — `tests/integration/test_campaign_double_send.py:113-122` (`async_sessionmaker` + `asyncio.gather`, one session per coroutine); `tests/conftest.py:92-96` uses `pool_size=5`, supporting N=3. G-6 is built by COPYING that precedent, not by building new infra. What genuinely does not exist is a **lock-timeout guard** for a blocking advisory lock in the serialized lane — G-6 adds `SET LOCAL lock_timeout` itself.
- **No clock-control mechanism exists** (no freezegun/time-machine). Use `monkeypatch.setattr(settings, "coop_credit_hold_hours", 0)` (read at call time, `identity_coop.py:194`) and/or seeded past `spendable_at` (precedent `test_identity_coop_contribution.py:384-412`).

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/visitors-identity/active/identity-coop_07-08-26/phase-2b-spend-wiring_PLAN_16-08-26.md`
- Last completed step: **created 17-08-26 at the Phase 2 split.** No RESEARCH/INNOVATE/PVL has run against this scope.
- Validate-contract status: **NOT WRITTEN.** This plan has never been validated. **Inner PVL from V1 is required** before any EXECUTE.
- Supporting context files loaded: `phase-2-consumption-spend_PLAN_07-08-26.md` (Phase 2a, incl. its archived cycle-5 contract), umbrella plan, Phase 1 plan + reports, `phase-blast-radius-registry.md`, `backlog/coop-credit-reversal-semantics_NOTE_16-08-26.md`, `process/context/tests/all-tests.md`, `process/context/all-context.md`
- Next step: **do nothing until Phase 2a is LIVE.** Then run the inner loop from Step 1 (RESEARCH) and PVL from V1, with an independent adversarial verifier instructed to REFUTE (default verdict REFUTED) — external verifiers found the top defect in every prior cycle on this program.

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
