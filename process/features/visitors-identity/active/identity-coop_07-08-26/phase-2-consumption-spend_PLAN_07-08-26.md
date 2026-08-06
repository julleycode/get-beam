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

**VALIDATE re-verification (07-08-26, this cycle):** re-read directly. `_log_owned_resolution`
(`identity_resolver.py:1415-1440`) confirmed verbatim — `provider not in OWNED_FREE_PROVIDERS` early
return, else `log_api_call(db=self.db, site_id=visitor.site_id, visitor_id=visitor.visitor_id,
provider=provider, category="identity", success=True, cost_usd=0.0, response_time_ms=0)`.
`OWNED_FREE_PROVIDERS` (`identity_classification.py:74-79`) = `{form_capture, fingerprint_match,
beam_identity_network, svid_reconcile}` — all four log to `api_usage_logs` with `category="identity"`,
so the `provider='beam_identity_network'` filter is load-bearing to isolate graph-served consumption
specifically from the other three owned-free paths. **Claim confirmed correct as stated.**

---

## Blast Radius

Risk class: **billing/credits + schema/migration**. Hybrid gate minimum.

- `apps/api/services/identity_coop.py` (MODIFIED — aggregation, spend, expiry functions)
- `apps/api/services/billing.py` (MODIFIED — `monthly_limit` extended by spendable credit)
- `apps/api/tasks/` (NEW task module or added task — expiry sweep)
- `apps/api/jobs/scheduler.py` (MODIFIED — `scheduler.add_job(...)` registration call, gated on
  `identity_coop_enabled`; **added by VALIDATE 07-08-26, was missing** — see Findings)
- `apps/api/config.py` (MODIFIED — sweep cadence setting, default inert)
- `apps/api/migrations/versions/{rev}_add_coop_ledger_indexes.py` (NEW — only if the reconciliation
  query needs a covering index; skip if not needed. **Path corrected by VALIDATE 07-08-26** — the
  real migrations directory is `apps/api/migrations/versions/`; `apps/api/alembic/versions/` does
  not exist anywhere in this repo, only `apps/api/alembic.ini` (the config file) does. See Findings.)
- `tests/unit/test_identity_coop_ledger.py` (NEW)
- `tests/integration/test_identity_coop_spend.py` (NEW)

~8 files (was ~7 — `apps/api/jobs/scheduler.py` added). `identity_resolver.py` is NOT touched in
this phase.

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

**VALIDATE finding (07-08-26) — spend-target wiring point is unresolved, see Findings F1.** The
codebase's real monthly enforcement gate, `check_usage_allowed(db, user_id)`
(`apps/api/services/billing.py:94`), is keyed on `User.id` / `User.monthly_identified_count`, not
`Site.id`. The credit ledger throughout Phases 1-2 is `site_id`-scoped. Step C below does not yet
say how a site-scoped balance reaches a user-scoped gate. This must be resolved before EXECUTE on
Step C — see Implementation Checklist C3/C4 and Findings F1.

---

## Implementation Checklist

### Step A — Consumption aggregation (read-only)

- [ ] A1. Add `async def consumption_count(db, site_id, *, since=None, until=None) -> int` to `apps/api/services/identity_coop.py` — a single SELECT COUNT over `api_usage_logs` filtered as stated in the Corrected Consumption Source section above. No writes, no new columns.
- [ ] A2. Exclude erased rows: filter out consumption events whose underlying identity `email_bidx` appears in `SuppressionEntry(scope="erased")`, using the same blind-index join `resolve()` already performs (SPEC A interface obligation). **VALIDATE 07-08-26 — join path confirmed feasible and now specified exactly:** `api_usage_logs` has no PII/bidx column, but `api_usage_logs.visitor_id` + `api_usage_logs.site_id` uniquely match `identified_visitors` via `uq_identified_site_visitor (site_id, visitor_id)`. `IdentifiedVisitor.email_bidx` (`apps/api/models/visitor.py:227`) exists and is auto-populated on every insert/update by the `before_insert`/`before_update` mapper hook `_sync_identity_pii` (`apps/api/services/pii_encryption_hooks.py:33-36`), using the SAME `email_hash()` function `SuppressionEntry.email_hash` (`apps/api/models/suppression.py`) is written with by the erasure sweep — so the two blind-index values are directly comparable. Join: `api_usage_logs JOIN identified_visitors ON (site_id, visitor_id) → WHERE identified_visitors.email_bidx NOT IN (SELECT email_hash FROM suppression_list WHERE scope='erased')`. **Caveat not yet resolved (Findings F5):** `email_bidx` backfill completeness for `IdentifiedVisitor` rows created before the Phase-05 PII-encryption hook was registered is unverified — if any pre-hook row has a NULL `email_bidx`, the exclusion silently fails to exclude it. Add a checklist item to confirm backfill coverage (or add a defensive test) before treating this exclusion as proven.
- [ ] A3. Add `async def contribution_count(db, site_id, *, since=None, until=None) -> int` over `identity_contribution_events`, excluding rows with a non-NULL `excluded_reason`.
- [ ] A4. Assert with `EXPLAIN` (recorded in the phase report) that both queries hit an index; add a migration for a covering index ONLY if they do not.
- [ ] A5. **(NEW — VALIDATE 07-08-26, Findings F4)** Add a test proving A2's erased-row exclusion actually excludes: an `IdentifiedVisitor` row's `email_bidx` present in `SuppressionEntry(scope='erased')` must not be counted in `consumption_count`. No test in the current Step D list proves this SPEC-required behavior (SPEC A's interface obligation) — see Findings F4.

### Step B — FIFO lot accounting and expiry

- [ ] B1. Add `async def spendable_lots(db, site_id) -> list[CreditLedgerEntry]` — `ACCRUE` rows where `now >= spendable_at` and `now < expires_at`, minus already-drawn amounts per `lot_id`, ordered by `expires_at` ASC.
- [ ] B2. Rewrite `spendable_balance(db, site_id)` as `SUM(amount)` over ALL ledger rows whose lot is currently live (ACCRUE minus its SPEND/EXPIRE draws) — so the balance is always derivable from history alone (AC-8). **VALIDATE 07-08-26 (Findings F6):** state explicitly in the docstring/phase report whether this balance INCLUDES or EXCLUDES lots still inside their 24h hold window. As written it is ambiguous, and that ambiguity affects both the AC-8 reconciliation semantics and what Phase 3's dashboard will display as "available credit."
- [ ] B3. Add `async def expire_lapsed_lots(db) -> int` — for each `ACCRUE` lot past `expires_at` with a non-zero remaining amount, write ONE `EXPIRE` row with `amount = -remaining`, `lot_id`, `reason='lot_expired'`. Must be **idempotent**: re-running writes zero additional rows (**AC-7**).
- [ ] B4. Register the sweep as a scheduled task following the existing APScheduler/Celery pattern. **VALIDATE 07-08-26 (Findings F2) — corrected:** the job function lives in `apps/api/tasks/`, but the actual registration call (`scheduler.add_job(...)`) happens in `apps/api/jobs/scheduler.py` (confirmed live pattern — see e.g. `if settings.graph_erasure_sweep_enabled: scheduler.add_job(...)` at `jobs/scheduler.py:674-675`). Both files must be touched; `apps/api/jobs/scheduler.py` was missing from Blast Radius/Touchpoints and has been added above. Gate the `add_job` call on `identity_coop_enabled` (default OFF ⇒ the job is inert).
- [ ] B5. Add `coop_expiry_sweep_interval_minutes: int = 60` to `apps/api/config.py`. Inert while the flag is OFF.

### Step C — Spend against monthly allowance

- [ ] C1. Add `async def spend_credits(db, site_id, amount, *, reason) -> int` — draws FIFO across `spendable_lots`, writing one `SPEND` row per lot drawn (negative `amount`, `lot_id` set). Returns the amount actually spent (may be less than requested). Never allows the balance to go negative.
- [ ] C2. Use a row-level lock or an advisory lock keyed on `site_id` around the draw, mirroring the `referral_activation.py` advisory-lock precedent (that precedent uses one GLOBAL lock key for its whole sweep — this phase needs a PER-SITE key, e.g. `pg_try_advisory_lock(hashtext(site_id))`, not the same global key), so two concurrent spends cannot double-draw one lot.
- [ ] C3. **VALIDATE 07-08-26 — BLOCKING GAP, see Findings F1. Do not implement as originally stated without first resolving this.** Original text: "In `apps/api/services/billing.py`, extend the effective monthly limit: `effective_monthly_limit = plan_monthly_limit + await spendable_balance(db, site_id)`, gated on `settings.identity_coop_enabled`." **Problem:** the function this is meant to extend, `get_effective_limit(plan, bonus_monthly_quota)` (`billing.py:60`), takes no `site_id` — it is called exclusively from `check_usage_allowed(db, user_id)` (`billing.py:94`) and the billing-summary endpoint (`routers/billing.py:328`), both of which are scoped to `User`, not `Site`. `User.monthly_identified_count` is the counter actually compared against the limit, and one `User` can own multiple `Site`s. The credit ledger is `site_id`-scoped throughout Phases 1-2 and the SPEC's dashboard requirement (AC-11) is explicitly site-scoped. **This checklist item must be rewritten to state one of:** (a) `check_usage_allowed`/`increment_usage`/`get_effective_limit` are extended to accept `site_id` and the effective limit sums `spendable_balance` for that one site only (multi-site users would need per-site tracking added to the enforcement path — a real code change beyond what's listed), or (b) credit extends the limit at the `User` level by summing `spendable_balance` across every site owned by that user (changes the SPEC's "credits belong to the contributing site" framing into "credits pool at the account level once spent"), or (c) some other explicit resolution. Whichever is chosen must be written into this plan before EXECUTE — this is not a detail EXECUTE should improvise.
- [ ] C4. Wire the actual decrement at the point a resolution consumes monthly allowance beyond the plan limit — call `spend_credits(..., reason='monthly_allowance_spend')`. **The exact call site depends on how C3 is resolved** — most likely inside `check_usage_allowed`/`increment_usage`, which will need a `site_id` parameter added to their signatures (currently `check_usage_allowed(db, user_id)`). Do NOT touch `Site.daily_resolution_budget` anywhere in this phase.
- [ ] C5. Add a `MOCK_EXTERNAL_APIS=true` guard check: confirm no new external call was introduced (this phase should introduce none — record it explicitly).

### Step D — Tests

- [ ] D1. `tests/integration/test_identity_coop_spend.py::test_graph_hit_increments_consumption_not_provider_spend` — a graph-served resolve increments the graph-consumption count and does NOT increment provider spend; a provider-purchased resolve does the inverse (**AC-4**).
- [ ] D2. `tests/integration/test_identity_coop_spend.py::test_spend_decrements_balance_and_writes_ledger_row` — a spend writes a negative-amount `SPEND` row with `site_id`, `reason`, `timestamp`, and lowers the balance by exactly that amount (**AC-6**).
- [ ] D3. `tests/unit/test_identity_coop_ledger.py::test_expired_credit_excluded_and_expiry_row_written` — a lot past `expires_at` is excluded from spendable balance AND an `EXPIRE` ledger row explains why (**AC-7**).
- [ ] D4. `tests/unit/test_identity_coop_ledger.py::test_expiry_sweep_is_idempotent` — running `expire_lapsed_lots` twice writes zero additional rows.
- [ ] D5. `tests/unit/test_identity_coop_ledger.py::test_ledger_reconciles_exactly` — **the AC-8 property test**: after a randomized sequence of at least 200 accrue/spend/expire operations, assert `sum(all ledger amounts for live lots) == spendable_balance(site)` exactly, with no drift (**AC-8**). **VALIDATE 07-08-26 (Findings F7) — tighten before EXECUTE:** the expected-value side of this assertion MUST be computed independently of `spendable_balance()`'s own "live lot" filter logic (e.g. an unconditional `SELECT SUM(amount) FROM credit_ledger_entries WHERE site_id=:s` with no lot-liveness predicate at all, which is algebraically equivalent to the true balance as long as SPEND/EXPIRE amounts always net exactly against their source lot — or a value tracked independently in the test harness as operations are generated). As currently worded the test risks being tautological if it recomputes "live lots" using the same code path the implementation uses to answer the same question.
- [ ] D6. `tests/unit/test_identity_coop_ledger.py::test_hold_window_blocks_spend` — a lot inside its 24h `spendable_at` hold cannot be spent.
- [ ] D7. `tests/unit/test_identity_coop_ledger.py::test_daily_budget_untouched` — assert `Site.daily_resolution_budget` is identical before and after a credit spend.
- [ ] D8. `tests/integration/test_identity_coop_spend.py::test_flag_off_billing_behavior_unchanged` — with `identity_coop_enabled=False`, the effective monthly limit equals the plan limit exactly (no drift for existing customers).
- [ ] D9. **(NEW — VALIDATE 07-08-26, Findings F4)** `tests/unit/test_identity_coop_ledger.py::test_erased_row_excluded_from_consumption_count` — see A5. Proves the SPEC A interface obligation (erased-row exclusion) that no existing test in this list covers.

### Step E — Migration (conditional)

- [ ] E1. Only if A4 showed a missing index: run `alembic heads` LIVE, chain an `add_coop_ledger_indexes` migration onto it under `apps/api/migrations/versions/` (**path corrected — VALIDATE 07-08-26; NOT `apps/api/alembic/versions/`, which does not exist**), offline-validate with an explicit `<from>:<to>` range, and round-trip on a disposable Postgres. If no index is needed, record "no migration required in Phase 2" in the phase report.

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

**VALIDATE 07-08-26 note:** none of the commands above can currently be run to green — see
Findings F0. `apps/api/services/identity_coop.py` and `apps/api/models/identity_coop.py` do not
exist in this repo on any branch (confirmed by `find`/`git log --all`); Phase 1 has not executed.
This exit gate is unreachable until Phase 1 ships.

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

- Phase 1 exit gate not passed (no ledger to spend from). **VALIDATE 07-08-26: this blocker is
  ACTIVE right now — see Findings F0.**
- The erased-row exclusion join (A2) turns out to require a new column on `api_usage_logs` — that would be a new write surface on the read path. Stop, record, and re-plan rather than adding it. (VALIDATE 07-08-26: not the case — a join through `identified_visitors` is feasible without any new column; see A2 above.)
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
- `apps/api/tasks/` (expiry sweep job function)
- `apps/api/jobs/scheduler.py` (expiry sweep registration — **added VALIDATE 07-08-26**, see Findings F2)
- `apps/api/config.py`
- `apps/api/models/api_usage.py` / `apps/api/services/usage_logger.py` (READ ONLY)
- `apps/api/models/identity_coop.py` (READ ONLY — schema fixed in Phase 1)
- `apps/api/models/visitor.py` (READ ONLY — `IdentifiedVisitor.email_bidx` join key for A2)
- `apps/api/models/suppression.py` (READ ONLY — `SuppressionEntry.email_hash` join key for A2)
- `apps/api/migrations/versions/` (conditional index migration only — **path corrected VALIDATE 07-08-26**)
- `tests/unit/test_identity_coop_ledger.py` (NEW)
- `tests/integration/test_identity_coop_spend.py` (NEW)

---

## Public Contracts

- `api_usage_logs` write path UNCHANGED — consumption is read-only.
- `apps/api/services/identity_resolver.py` UNCHANGED in this phase (empty diff is an exit gate).
- `Site.daily_resolution_budget` semantics UNCHANGED.
- Billing behavior with `identity_coop_enabled=False` is byte-identical to today.
- New internal service functions only; no new HTTP surface in this phase.
- **VALIDATE 07-08-26 addition:** if C3 is resolved via option (a) or (b) above, `check_usage_allowed`
  / `increment_usage` / `get_effective_limit` signatures change (new `site_id` parameter). Every
  existing call site of these three functions (`routers/visitors.py:947`, `routers/visitors_helpers.py:280`,
  `tasks/resolution_tasks.py:120`, `services/resolution_runner.py:161`, `routers/billing.py:317,328`)
  must be updated consistently or the change is not additive — this belongs in Blast Radius once C3
  is resolved, and is currently NOT listed.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `test_graph_hit_increments_consumption_not_provider_spend` | Fully-Automated | AC-4 |
| `test_spend_decrements_balance_and_writes_ledger_row` | Fully-Automated | AC-6 |
| `test_expired_credit_excluded_and_expiry_row_written` | Fully-Automated | AC-7 |
| `test_ledger_reconciles_exactly` (≥200 randomized ops, independent oracle — see D5 note) | Fully-Automated | AC-8 |
| `test_expiry_sweep_is_idempotent` | Fully-Automated | AC-7 (durability) |
| `test_hold_window_blocks_spend` | Fully-Automated | Fraud-resistance residual mitigation |
| `test_daily_budget_untouched` | Fully-Automated | Spend-target decision (monthly, not daily) |
| `test_flag_off_billing_behavior_unchanged` | Fully-Automated | Flag-default-OFF precedent |
| `test_erased_row_excluded_from_consumption_count` (**NEW, D9**) | Fully-Automated | SPEC A interface obligation (erased-row exclusion) — previously unproven |
| `git diff apps/api/services/identity_resolver.py` empty | Fully-Automated | Zero-new-write-surface constraint |
| Conditional migration round-trip on disposable Postgres | Hybrid (precondition: disposable Postgres container) | Schema/migration high-risk class |

---

## Test Infra Improvement Notes

- (VALIDATE 07-08-26) This repo has no existing test asserting `User.monthly_identified_count` vs.
  a `site_id`-scoped credit balance interaction — whichever C3 resolution is chosen will need new
  test infra for multi-site-per-user scenarios that does not exist today.

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/visitors-identity/active/identity-coop_07-08-26/phase-2-consumption-spend_PLAN_07-08-26.md`
- Last completed step: not started (Phase 1 has not executed — see Validate Contract)
- Validate-contract status: written 07-08-26, **Gate: BLOCKED** (outer-pvl, cycle 0)
- Supporting context files loaded: umbrella plan, Phase 1 plan + report, `process/context/tests/all-tests.md`, `process/context/all-context.md`
- Next step: do NOT spawn EXECUTE. Wait for (1) SPEC A `graph-erasure-compliance_07-08-26` to go LIVE and (2) Phase 1 (`phase-1-ledger-substrate_PLAN_07-08-26.md`) to reach its own exit gate. Once both hold, re-run RESEARCH (Step 1) for this phase, fold in the plan-text fixes below via PLAN-SUPPLEMENT, then re-run PVL from V1.

---

## Validate Contract

Status: BLOCKED
Date: 07-08-26
date: 2026-08-07
generated-by: outer-pvl

Parallel strategy: sequential (single-pass; no Agent tool available in this session — every
Layer 1/Layer 2 investigation below was performed directly by this agent, not fanned out to
sub-agents. Disclosed per fan-out rules; re-run with real fan-out recommended if/when this plan
is re-validated after Phase 1 ships, per `vc-agent-strategy-compare` HIGH-signal scoring — this
plan touches billing/credits + schema/migration + multi-tenancy, 8 blast-radius files.)
Rationale: single agent, no team/parallel tooling in this invocation's tool grant.

### Entry Gate / Dependency Chain — the headline finding

The chain the umbrella states as a hard precondition is **not satisfied**:

| Link | Status |
|---|---|
| `identity-vocab-reconcile_07-08-26` PASS/descoped | **Effectively cleared.** `Status: EXECUTED — result accepted by the user. Gate: CONDITIONAL, accepted.` Changes are merged and live on `devjulley`. Not a literal `Gate: PASS`, but explicitly user-accepted, which the sibling `graph-erasure-compliance` plan itself already treats as satisfying this link. |
| SPEC A `graph-erasure-compliance_07-08-26` LIVE | **NOT cleared.** Plan status: `ACCEPTED — EXECUTE-READY... EVL is NOT run` per its own report — `Classification: Keep in active/testing... CODE DONE, not EVL GREEN`. 14 integration/Hybrid gates deferred (Docker down). Not merged to `main` (the report's own "Deploy warning" describes what happens *when* pushed — future tense, meaning it has not been pushed yet). **Not LIVE by the umbrella's own definition ("must complete EXECUTE and be LIVE, not merely planned").** |
| Phase 1 (`phase-1-ledger-substrate_PLAN_07-08-26.md`) exit gate | **NOT cleared — Phase 1 has not started.** Phase 1's own status is `⏳ PLANNED — blocked on two upstream dependencies`. Confirmed by direct filesystem check: `apps/api/models/identity_coop.py` and `apps/api/services/identity_coop.py` do not exist anywhere in this repo (`find` returns nothing; `git log --all` for both paths returns nothing — never committed on any branch). |

**Conclusion, stated plainly:** the dependency chain is broken at two points, not one. SPEC A is
code-complete but not live. Phase 1 has not been executed at all — the very files Phase 2's own
Blast Radius says to MODIFY do not exist yet. Phase 2's own stated Entry Gate ("Phase 1 exit gate
passed: all three tables live, `contribution_enabled` wired, hook in place, accrual proven") is
unmet. **This alone makes the plan not EXECUTE-ready today, independent of the plan's internal
quality.** This is a program-sequencing fact, not a plan defect a supplement cycle can fix — the
correct action is to wait for Phase 1 and SPEC A, not to edit this plan further right now.

### Net Gate Derivation

#### Layer 1 dimensions

| Layer 1 dimensions | Status |
|---|---|
| Infra fit | FAIL — dependency chain unmet (see Entry Gate above); scheduler registration touchpoint (`apps/api/jobs/scheduler.py`) was missing, now added |
| Test coverage | CONCERN — 2 tests added (A5/D9 erased-row exclusion; was entirely untested), AC-8 test (D5) risked tautology, now flagged for a fix before EXECUTE |
| Breaking changes | CONCERN — Step C3's `monthly_limit` wiring point does not match the real code architecture (user-scoped enforcement vs. site-scoped ledger); resolving it will touch 5+ additional call sites not currently in Blast Radius |
| Security surface | PASS — no PII in new writes; `email_bidx`/`email_hash` blind-index joins only, matching existing patterns; multi-tenancy filtering unaffected in this phase (no new HTTP surface) |

#### Layer 2 sections

| Layer 2 sections | Status |
|---|---|
| Step A — Consumption aggregation | CONCERN — mechanically sound and re-verified correct against source (`_log_owned_resolution`/`OWNED_FREE_PROVIDERS` claim confirmed exactly as stated); erased-row join (A2) is feasible and now specified, but had zero proving test until this cycle added D9; historical `email_bidx` backfill completeness is unverified (Findings F5) |
| Step B — FIFO lot accounting/expiry | CONCERN — mechanically consistent with Phase 1's `CreditLedgerEntry` schema; scheduler registration site was missing from Blast Radius (fixed); `spendable_balance`'s hold-window inclusion/exclusion semantics are ambiguous (Findings F6) |
| Step C — Spend against monthly allowance | FAIL — C3's core wiring claim does not match the real `check_usage_allowed`/`get_effective_limit` architecture (user-scoped, not site-scoped); C1/C2 (FIFO draw + per-site advisory lock) are sound in isolation but depend on C3 landing first |
| Step D — Tests | CONCERN — 8 of 10 gates well-specified; D5 (AC-8) needs an independent-oracle fix; A2's exclusion behavior had no test (added as D9) |
| Step E — Migration (conditional) | CONCERN (now resolved by this cycle's edit) — file path cited throughout the plan (`apps/api/alembic/versions/...`) does not exist in this repo; corrected to `apps/api/migrations/versions/...` in all locations in this document |

**Totals: 3 FAILs / 6 CONCERNs / 1 PASS** (Entry Gate + Infra fit + Step C, counted once as the
Entry-Gate FAIL drives Infra fit's FAIL; Step C is an independent, second, plan-content FAIL)

**→ Net Gate: BLOCKED**

### Findings (full list, with fixable-defect vs. documentable-gap classification)

| # | Finding | Class | Severity |
|---|---|---|---|
| F0 | Dependency chain unmet: SPEC A not LIVE, Phase 1 not executed, `identity_coop.py`/`models/identity_coop.py` do not exist anywhere in the repo | **Documentable gap** — not fixable by editing this plan; wait for Phase 1 + SPEC A | BLOCKING |
| F1 | Step C3/C4 `monthly_limit` wiring targets a function (`get_effective_limit`) with no `site_id` parameter; real enforcement (`check_usage_allowed`) is `User`-scoped, not `Site`-scoped; ledger is `Site`-scoped throughout | **Fixable defect** — needs an explicit design decision + checklist rewrite before EXECUTE (see C3 edit above for the 3 stated options) | HIGH |
| F2 | `apps/api/jobs/scheduler.py` (the real `add_job` registration site) missing from Blast Radius/Touchpoints | **Fixable defect** — corrected in this cycle's edit | MEDIUM |
| F3 | Migration file path cited as `apps/api/alembic/versions/...` throughout; real path is `apps/api/migrations/versions/...`; `apps/api/alembic/` does not exist | **Fixable defect** — corrected in this cycle's edit (all instances) | LOW |
| F4 | No test proves A2's erased-row exclusion (SPEC A interface obligation) | **Fixable defect** — added A5/D9 in this cycle's edit | MEDIUM |
| F5 | Historical `IdentifiedVisitor.email_bidx` backfill completeness (rows predating the Phase-05 PII-encryption hook) is unverified; if incomplete, the erasure exclusion silently under-excludes | **Documentable gap** — flag as a known-gap or add a backfill-coverage check at RESEARCH/EXECUTE time; not blocking on its own | MEDIUM |
| F6 | `spendable_balance`'s inclusion/exclusion of hold-window (not-yet-spendable) amounts is unstated, affecting both AC-8 and the Phase 3 dashboard's meaning of "balance" | **Fixable defect** — needs one sentence of explicit design decision before EXECUTE | LOW-MEDIUM |
| F7 | D5 (AC-8 property test) risks tautology if its "expected" side reuses the same "live lot" filter the implementation uses | **Fixable defect** — reworded in this cycle's edit to require an independent oracle | MEDIUM |

### What this coverage does NOT prove

- None of the Exit Gate commands can currently be run — `identity_coop.py` does not exist. Nothing
  in this contract proves the plan's CODE works; it proves the plan's TEXT is (now, after this
  cycle's edits) internally consistent with the real codebase architecture, modulo the two
  remaining FAILs (F0 dependency chain, F1 spend-target wiring) that must be resolved before a
  future PVL cycle can reach PASS/CONDITIONAL.
- Does not prove the eventual `check_usage_allowed`/`get_effective_limit` signature change (once
  C3 is resolved) is backward-compatible with all 5+ existing call sites — that requires a fresh
  Layer 1 breaking-changes pass once C3's resolution is written into the plan.
- Does not prove `IdentifiedVisitor.email_bidx` is actually non-NULL for the historical row
  population in any real environment (F5) — this needs a live-data check, not a plan-text check.
- Does not include a live/Docker Hybrid-tier run of anything — Docker is down in this environment
  (matches every other recent plan's known-gap posture).

### Open gaps

- F0 (blocking — program sequencing, not a plan defect)
- F5 (documentable known-gap candidate — historical backfill verification)
- Docker-gated Hybrid tier (standing known-gap across this whole program, per umbrella)

Gate: BLOCKED
Accepted by: PENDING
