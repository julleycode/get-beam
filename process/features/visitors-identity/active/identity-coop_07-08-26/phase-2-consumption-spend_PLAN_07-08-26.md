---
name: plan:identity-coop-phase-2-consumption-spend
description: "Identity Co-op — Phase 2: read-only consumption aggregation, FIFO lot expiry, and credit spend against monthly allowance"
date: 07-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
  phase: phase-2
---

# Phase 2 — Consumption Aggregation + Spend

**Program:** identity-coop
**Umbrella plan:** `process/features/visitors-identity/active/identity-coop_07-08-26/identity-coop-umbrella_PLAN_07-08-26.md`
Complexity: COMPLEX (phase of a 3-phase program)
Phase status: ⏳ PLANNED
Status: ⏳ PLANNED
Date: 07-08-26
**Report destination:** `process/features/visitors-identity/active/identity-coop_07-08-26/phase-2-consumption-spend_REPORT_07-08-26.md`

**TL;DR** — Make the ledger economically real: count consumption with ZERO new write surface
(read-only aggregation over `api_usage_logs`), implement FIFO lot expiry with explicit `EXPIRE`
entries, and wire credit spend into `monthly_limit` (never `daily_resolution_budget`). Ends with
the AC-8 randomized exact-reconciliation property test.

---

## Overview

See Purpose below for the narrative; this phase is one leg of the identity-coop phase program.
Ordering, gates, and program state live in the umbrella plan.

---

## Purpose

Phase 1 proved credits can be earned. This phase proves they can be counted against, spent, and
expired — with the ledger reconciling exactly. The core constraint is that consumption measurement
adds **no new write surface**: the graph-served identification is already logged, so consumption is
purely a query.

---

## Entry Gate

- Phase 1 exit gate passed: all three tables live, `contribution_enabled` wired, hook in place, accrual proven.
- Fresh RESEARCH pass confirms the `api_usage_logs` write path for `beam_identity_network` is unchanged.
- `alembic -c apps/api/alembic.ini heads` re-run LIVE (the chain may have moved since Phase 1).

---

## Corrected Consumption Source (verified 07-08-26 — read this before implementing)

INNOVATE named `resolution_logs`. **That table is wrong.** Direct code read confirms:

- `_log_owned_resolution(visitor, provider)` inside the Save+Log block of
  `apps/api/services/identity_resolver.py` calls `log_api_call(...)`
  (`apps/api/services/usage_logger.py`), which writes an **`ApiUsageLog` row into
  `api_usage_logs`** — `provider='beam_identity_network'`, `category='identity'`,
  `cost_usd=0.0`, `success=True`, `site_id`, `visitor_id`, in the SAME transaction as the identity save.
- `_log_resolution(...)` is the paid-provider path that writes `ResolutionLog` into `resolution_logs`
  (and separately mirrors into `api_usage_logs` with a real cost).
- `beam_identity_network ∈ OWNED_FREE_PROVIDERS` in `apps/api/services/identity_classification.py`
  — confirmed, so the owned-log branch fires for every graph-served identification.

**Therefore:** consumption = read-only aggregation over `api_usage_logs` WHERE
`provider = 'beam_identity_network' AND category = 'identity' AND success IS TRUE`, grouped by
`site_id`. Provider-purchased resolutions are structurally separate (non-zero `cost_usd`, different
providers) — AC-4's "does not increment the provider-spend counter" assertion falls out of the data
shape, not new plumbing.

**Do NOT add any write to the read path.** If the aggregation appears to need a new column, stop
and re-plan — that is the failure mode this decision exists to prevent.

---

## Blast Radius

Risk class: **billing/credits + schema/migration**. Hybrid gate minimum.

- `apps/api/services/identity_coop.py` (MODIFIED — aggregation, spend, expiry functions)
- `apps/api/services/billing.py` (MODIFIED — `monthly_limit` extended by spendable credit)
- `apps/api/tasks/` (NEW task module or added task — expiry sweep)
- `apps/api/config.py` (MODIFIED — sweep cadence setting, default inert)
- `apps/api/alembic/versions/{rev}_add_coop_ledger_indexes.py` (NEW — only if the reconciliation query needs a covering index; skip if not needed)
- `tests/unit/test_identity_coop_ledger.py` (NEW)
- `tests/integration/test_identity_coop_spend.py` (NEW)

~7 files. `identity_resolver.py` is NOT touched in this phase.

---

## Spend Semantics (decided, do not re-open)

| Question | Decision |
|---|---|
| What do credits buy? | Additional **monthly** identity-resolution allowance. `monthly_limit` (see `apps/api/routers/billing.py`) is effectively `plan_monthly_limit + spendable_credit_balance`. |
| Do credits raise `daily_resolution_budget`? | **No.** Raising the daily cap changes the abuse blast-radius math the P3 ingest-ceiling work exists to bound. The daily cap is untouched. |
| Exchange rate | **1 credit = 1 resolution unit of monthly allowance.** |
| Draw order | **FIFO by `expires_at` ascending** — oldest-expiring lot is spent first, so credit is never wasted. |
| Expiry | Lot-based: each `ACCRUE` row carries `expires_at = created_at + 90 days`. Excluded at read time; a sweep writes an explicit `EXPIRE` row (negative amount, `lot_id` set) so expiry is auditable, not silent. |
| Hold | A lot is not spendable until `now >= spendable_at` (`created_at + 24h`), giving the batch `cadence_bot_flag` sweep time to catch slow bot patterns. |

---

## Implementation Checklist

### Step A — Consumption aggregation (read-only)

- [ ] A1. Add `async def consumption_count(db, site_id, *, since=None, until=None) -> int` to `apps/api/services/identity_coop.py` — a single SELECT COUNT over `api_usage_logs` filtered as stated in the Corrected Consumption Source section above. No writes, no new columns.
- [ ] A2. Exclude erased rows: filter out consumption events whose underlying identity `email_bidx` appears in `SuppressionEntry(scope="erased")`, using the same blind-index join `resolve()` already performs (SPEC A interface obligation). If `api_usage_logs` carries no `email_bidx`, join via `visitor_id → IdentifiedVisitor.email_bidx`; document the exact join in the phase report.
- [ ] A3. Add `async def contribution_count(db, site_id, *, since=None, until=None) -> int` over `identity_contribution_events`, excluding rows with a non-NULL `excluded_reason`.
- [ ] A4. Assert with `EXPLAIN` (recorded in the phase report) that both queries hit an index; add a migration for a covering index ONLY if they do not.

### Step B — FIFO lot accounting and expiry

- [ ] B1. Add `async def spendable_lots(db, site_id) -> list[CreditLedgerEntry]` — `ACCRUE` rows where `now >= spendable_at` and `now < expires_at`, minus already-drawn amounts per `lot_id`, ordered by `expires_at` ASC.
- [ ] B2. Rewrite `spendable_balance(db, site_id)` as `SUM(amount)` over ALL ledger rows whose lot is currently live (ACCRUE minus its SPEND/EXPIRE draws) — so the balance is always derivable from history alone (AC-8).
- [ ] B3. Add `async def expire_lapsed_lots(db) -> int` — for each `ACCRUE` lot past `expires_at` with a non-zero remaining amount, write ONE `EXPIRE` row with `amount = -remaining`, `lot_id`, `reason='lot_expired'`. Must be **idempotent**: re-running writes zero additional rows (**AC-7**).
- [ ] B4. Register the sweep as a scheduled task following the existing APScheduler/Celery pattern in `apps/api/tasks/`, gated on `identity_coop_enabled` (default OFF ⇒ the job is inert).
- [ ] B5. Add `coop_expiry_sweep_interval_minutes: int = 60` to `apps/api/config.py`. Inert while the flag is OFF.

### Step C — Spend against monthly allowance

- [ ] C1. Add `async def spend_credits(db, site_id, amount, *, reason) -> int` — draws FIFO across `spendable_lots`, writing one `SPEND` row per lot drawn (negative `amount`, `lot_id` set). Returns the amount actually spent (may be less than requested). Never allows the balance to go negative.
- [ ] C2. Use a row-level lock or an advisory lock keyed on `site_id` around the draw, mirroring the `referral_activation.py` advisory-lock precedent, so two concurrent spends cannot double-draw one lot.
- [ ] C3. In `apps/api/services/billing.py`, extend the effective monthly limit: `effective_monthly_limit = plan_monthly_limit + await spendable_balance(db, site_id)`, gated on `settings.identity_coop_enabled` (flag OFF ⇒ byte-identical behavior to today).
- [ ] C4. Wire the actual decrement at the point a resolution consumes monthly allowance beyond the plan limit — call `spend_credits(..., reason='monthly_allowance_spend')`. Do NOT touch `Site.daily_resolution_budget` anywhere in this phase.
- [ ] C5. Add a `MOCK_EXTERNAL_APIS=true` guard check: confirm no new external call was introduced (this phase should introduce none — record it explicitly).

### Step D — Tests

- [ ] D1. `tests/integration/test_identity_coop_spend.py::test_graph_hit_increments_consumption_not_provider_spend` — a graph-served resolve increments the graph-consumption count and does NOT increment provider spend; a provider-purchased resolve does the inverse (**AC-4**).
- [ ] D2. `tests/integration/test_identity_coop_spend.py::test_spend_decrements_balance_and_writes_ledger_row` — a spend writes a negative-amount `SPEND` row with `site_id`, `reason`, `timestamp`, and lowers the balance by exactly that amount (**AC-6**).
- [ ] D3. `tests/unit/test_identity_coop_ledger.py::test_expired_credit_excluded_and_expiry_row_written` — a lot past `expires_at` is excluded from spendable balance AND an `EXPIRE` ledger row explains why (**AC-7**).
- [ ] D4. `tests/unit/test_identity_coop_ledger.py::test_expiry_sweep_is_idempotent` — running `expire_lapsed_lots` twice writes zero additional rows.
- [ ] D5. `tests/unit/test_identity_coop_ledger.py::test_ledger_reconciles_exactly` — **the AC-8 property test**: after a randomized sequence of at least 200 accrue/spend/expire operations, assert `sum(all ledger amounts for live lots) == spendable_balance(site)` exactly, with no drift (**AC-8**).
- [ ] D6. `tests/unit/test_identity_coop_ledger.py::test_hold_window_blocks_spend` — a lot inside its 24h `spendable_at` hold cannot be spent.
- [ ] D7. `tests/unit/test_identity_coop_ledger.py::test_daily_budget_untouched` — assert `Site.daily_resolution_budget` is identical before and after a credit spend.
- [ ] D8. `tests/integration/test_identity_coop_spend.py::test_flag_off_billing_behavior_unchanged` — with `identity_coop_enabled=False`, the effective monthly limit equals the plan limit exactly (no drift for existing customers).

### Step E — Migration (conditional)

- [ ] E1. Only if A4 showed a missing index: run `alembic heads` LIVE, chain a `add_coop_ledger_indexes` migration onto it, offline-validate with an explicit `<from>:<to>` range, and round-trip on a disposable Postgres. If no index is needed, record "no migration required in Phase 2" in the phase report.

---

## Exit Gate

```bash
# Unit lane (includes the AC-8 randomized reconciliation property test)
.venv/bin/python3.11 -m pytest tests/unit -m unit -q
# Expected: exit 0

# Integration lane
.venv/bin/python3.11 -m pytest tests/ -m integration -q
# Expected: exit 0

# Read-path purity guard — no new write surface added to the consumption path
git diff apps/api/services/identity_resolver.py
# Expected: EMPTY (this phase must not touch the resolver at all)

# Conditional migration validation (only if Step E ran)
alembic -c apps/api/alembic.ini heads
alembic -c apps/api/alembic.ini upgrade <recorded_head>:head --sql
# Expected: single head; exit 0
```

- All checklist items checked.
- AC-8 property test passes with ≥200 randomized operations, zero drift.
- `identity_coop_enabled=False` produces byte-identical billing behavior to today, proven by D8.
- `Site.daily_resolution_budget` provably untouched (D7).
- Phase report written to the report destination above.

---

## Acceptance Criteria

- **AC-4** — a graph-served resolve increments graph consumption and NOT provider spend; a provider-purchased resolve does the inverse.
- **AC-6** — a spend decrements the balance and writes a negative-amount `SPEND` ledger row with site_id, reason, timestamp.
- **AC-7** — a credit past its 90-day expiry is excluded from spendable balance AND an `EXPIRE` ledger row explains why; the sweep is idempotent.
- **AC-8** — after ≥200 randomized accrue/spend/expire operations, `sum(ledger) == spendable balance` exactly, zero drift.
- `Site.daily_resolution_budget` is provably untouched by any credit spend.
- With `identity_coop_enabled=False`, billing behavior is byte-identical to today.
- `apps/api/services/identity_resolver.py` diff is EMPTY for this phase.

---

## Phase Completion Rules

- 🔨 **CODE DONE** — all checklist items checked, no test evidence yet.
- 🧪 **TESTING** — both pytest lanes running; failures fixed inline.
- ✅ **VERIFIED** — both lanes exit 0 including the AC-8 property test at zero drift, the resolver
  diff is empty, and the validate-contract is written (non-placeholder).
- 🚧 **BLOCKED** — Phase 1 exit gate unmet, or the erased-row exclusion would require a new write
  surface on the read path.
- AC-8 drift is a correctness blocker, never a known-gap.

---

## Blockers That Would Justify BLOCKED Status

- Phase 1 exit gate not passed (no ledger to spend from).
- The erased-row exclusion join (A2) turns out to require a new column on `api_usage_logs` — that would be a new write surface on the read path. Stop, record, and re-plan rather than adding it.
- Docker unavailable ⇒ the conditional migration round-trip cannot run. Known-Gap + backlog stub; keep the gate **CONDITIONAL**.
- The AC-8 property test cannot reach zero drift — this is a correctness blocker, not a known-gap. Do not accept a "close enough" balance.

---

## Phase Loop Progress

- [ ] 1. RESEARCH — research-agent: Phase 1 report read; `api_usage_logs` write path re-confirmed; test context loaded
- [ ] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: this plan updated; Inner Loop Refresh Note if sections changed (or "n/a — research clean")
- [ ] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md`
- [ ] 5. EXECUTE — all checklist items done; per-section test gates run and green
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** A placeholder `## Validate Contract` = blocked.

---

## Touchpoints

- `apps/api/services/identity_coop.py`
- `apps/api/services/billing.py`
- `apps/api/tasks/` (expiry sweep registration)
- `apps/api/config.py`
- `apps/api/models/api_usage.py` / `apps/api/services/usage_logger.py` (READ ONLY)
- `apps/api/models/identity_coop.py` (READ ONLY — schema fixed in Phase 1)
- `apps/api/alembic/versions/` (conditional index migration only)
- `tests/unit/test_identity_coop_ledger.py` (NEW)
- `tests/integration/test_identity_coop_spend.py` (NEW)

---

## Public Contracts

- `api_usage_logs` write path UNCHANGED — consumption is read-only.
- `apps/api/services/identity_resolver.py` UNCHANGED in this phase (empty diff is an exit gate).
- `Site.daily_resolution_budget` semantics UNCHANGED.
- Billing behavior with `identity_coop_enabled=False` is byte-identical to today.
- New internal service functions only; no new HTTP surface in this phase.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `test_graph_hit_increments_consumption_not_provider_spend` | Fully-Automated | AC-4 |
| `test_spend_decrements_balance_and_writes_ledger_row` | Fully-Automated | AC-6 |
| `test_expired_credit_excluded_and_expiry_row_written` | Fully-Automated | AC-7 |
| `test_ledger_reconciles_exactly` (≥200 randomized ops) | Fully-Automated | AC-8 |
| `test_expiry_sweep_is_idempotent` | Fully-Automated | AC-7 (durability) |
| `test_hold_window_blocks_spend` | Fully-Automated | Fraud-resistance residual mitigation |
| `test_daily_budget_untouched` | Fully-Automated | Spend-target decision (monthly, not daily) |
| `test_flag_off_billing_behavior_unchanged` | Fully-Automated | Flag-default-OFF precedent |
| `git diff apps/api/services/identity_resolver.py` empty | Fully-Automated | Zero-new-write-surface constraint |
| Conditional migration round-trip on disposable Postgres | Hybrid (precondition: disposable Postgres container) | Schema/migration high-risk class |

---

## Test Infra Improvement Notes

(none identified yet)

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/visitors-identity/active/identity-coop_07-08-26/phase-2-consumption-spend_PLAN_07-08-26.md`
- Last completed step: not started
- Validate-contract status: pending
- Supporting context files loaded: umbrella plan, Phase 1 plan + report, `process/context/tests/all-tests.md`
- Next step: confirm Phase 1 exit gate passed, then spawn vc-research-agent for RESEARCH (Step 1)

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
