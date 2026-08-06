---
name: plan:identity-coop-phase-1-ledger-substrate
description: "Identity Co-op — Phase 1: contribution-event log, credit ledger, consent acceptance, per-site opt-in flag, and the fraud-gated hook"
date: 07-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
  phase: phase-1
---

# Phase 1 — Ledger + Contribution Substrate

**Program:** identity-coop
**Umbrella plan:** `process/features/visitors-identity/active/identity-coop_07-08-26/identity-coop-umbrella_PLAN_07-08-26.md`
Complexity: COMPLEX (phase of a 3-phase program)
Phase status: ⏳ PLANNED — blocked on two upstream dependencies
Status: ⏳ PLANNED — blocked on two upstream dependencies
Date: 07-08-26
**Report destination:** `process/features/visitors-identity/active/identity-coop_07-08-26/phase-1-ledger-substrate_REPORT_07-08-26.md`

**TL;DR** — Build the measurement + reciprocity substrate: 3 new tables, 1 new `sites` column
(7-layer wiring), 1 new service module, and a ~2-line best-effort hook inside `_save_identified`.
No dashboard, no spend, no expiry sweep. Every flag OFF.

---

## Overview

See Purpose below for the narrative; this phase is one leg of the identity-coop phase program.
Ordering, gates, and program state live in the umbrella plan.

---

## Purpose

Nothing can be paid out before it is measured. This phase builds the foundation the whole co-op
rests on: an append-only contribution-event log keyed to structurally dedupe merged duplicates, an
append-only credit ledger with per-lot expiry metadata, an append-only consent-acceptance audit
trail, and a per-site opt-in flag that defaults OFF. The only change inside the contested
`identity_resolver.py` is a ~2-line conditional call — all logic lives in a new module.

---

## Entry Gate

- `identity-vocab-reconcile_07-08-26` has reached `Gate: PASS` or has been explicitly descoped.
- SPEC A `graph-erasure-compliance_07-08-26` has completed EXECUTE and is LIVE (not merely planned).
- Fresh RESEARCH pass confirms `_save_identified` / `_upsert_beam_identity` call-graph shape has not
  materially changed under the concurrent workstreams.
- `alembic -c apps/api/alembic.ini heads` run LIVE, returns a single head; that head is recorded in
  the phase report and used as `down_revision`.

If either upstream dependency is unmet: report BLOCKED. Do NOT partially execute.

---

## Locked Constraints Inherited From the Umbrella

- Read access is UNCONDITIONAL (AC-2 model (a)). This phase MUST NOT add any gate to the graph read path.
- Flags default OFF. No production enablement.
- No purge / retro-attribution / retro-credit of pre-program rows.
- No PII in logs. Contribution events key on `email_bidx` (blind index), never plaintext email.
- Hook described by call-graph position only, never line number.

---

## Blast Radius

Risk class: **billing/credits + schema/migration**. Hybrid gate minimum.

- `apps/api/models/identity_coop.py` (NEW)
- `apps/api/services/identity_coop.py` (NEW)
- `apps/api/models/site.py` (MODIFIED — one additive column)
- `apps/api/config.py` (MODIFIED — one settings block, all defaults OFF/inert)
- `apps/api/services/identity_resolver.py` (MODIFIED — ~2 lines)
- `apps/api/schemas/sites.py` (MODIFIED — one additive optional field)
- `apps/api/routers/sites.py` (MODIFIED — flag flip guarded by acceptance)
- `apps/api/alembic/versions/{rev}_add_identity_coop_tables.py` (NEW)
- `apps/api/alembic/versions/{rev}_add_site_contribution_enabled.py` (NEW)
- `tests/unit/test_identity_coop.py` (NEW)
- `tests/integration/test_identity_coop_contribution.py` (NEW)

~11 files. Diff footprint inside the contested `identity_resolver.py`: ~2 lines.

---

## Data Model Decisions

### `identity_contribution_events` (append-only)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `site_id` | String(50), NOT NULL | attribution unit; matches `beam_identity_graph.source_site_id` shape |
| `email_bidx` | String(64), NOT NULL, indexed | **blind index only — never plaintext email** |
| `contributed_on` | Date, NOT NULL | day bucket |
| `source_provider` | String(50) | which provider produced the identification |
| `accrued` | Boolean, NOT NULL, default False | did this event pass the fraud gate and produce a ledger row |
| `excluded_reason` | String(30), nullable | `'abuse_flagged'` / `'erased'` / `'duplicate'` / NULL |
| `created_at` | DateTime(tz), server_default now() | |

**Unique constraint `uq_coop_contrib_site_email_day` on `(site_id, email_bidx, contributed_on)`.**
This is the merge-awareness mechanism (AC-3): a person resolved twice under two `visitor_id`s on
the same day produces ONE contribution row via `ON CONFLICT DO NOTHING`. It is keyed on neither
`visitor_id` nor graph-row id, so the 5-file merged-visitor gap is structurally irrelevant here.

### `identity_credit_ledger` (append-only, lot-based)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `site_id` | String(50), NOT NULL, indexed | |
| `entry_type` | String(10), NOT NULL | `ACCRUE` / `SPEND` / `EXPIRE` |
| `amount` | Integer, NOT NULL | positive for ACCRUE; negative for SPEND and EXPIRE |
| `reason` | String(100), NOT NULL | e.g. `'contribution'`, `'monthly_allowance_spend'`, `'lot_expired'` |
| `lot_id` | UUID, nullable, indexed | ACCRUE rows: own id. SPEND/EXPIRE rows: the ACCRUE lot they draw from |
| `spendable_at` | DateTime(tz), nullable | ACCRUE only — `created_at + provisional hold` (24h) |
| `expires_at` | DateTime(tz), nullable, indexed | ACCRUE only — `created_at + 90 days` |
| `contribution_event_id` | UUID, nullable | ACCRUE only — provenance back to the event |
| `created_at` | DateTime(tz), server_default now() | |

Balance is DERIVED (`SUM(amount)` over unexpired, past-hold rows), never a mutable column (AC-8).
Read-time filtering mirrors the `identity_signals.decay_confidence()` precedent; the sweep in
Phase 2 makes expiry an explicit auditable event.

### `identity_contribution_consent_acceptances` (append-only)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `site_id` | String(50), NOT NULL, indexed | |
| `terms_version` | String(64), NOT NULL | **immutable snapshot hash of the exact policy text**, never a live pointer to editable copy |
| `accepted_at` | DateTime(tz), NOT NULL | |
| `accepted_by_user_id` | UUID, NOT NULL | |

The flag is mutable (can be toggled off and on); this trail is not. The flag cannot flip ON via API
without an acceptance row written in the same transaction (AC-10 automated leg).

---

## Config Settings (all default OFF/inert)

```
identity_coop_enabled: bool = False
coop_credit_per_contribution: int = 1
coop_credit_expiry_days: int = 90
coop_credit_hold_hours: int = 24
```

Follows the `agent_detection_enabled` / `company_graph_enabled` / `identity_signals_enabled`
operator-gated precedent exactly. Flipping any of these ON in a real environment is a separate,
explicit, later operator action — never part of this phase.

---

## Implementation Checklist

### Step A — Models and migrations

- [ ] A1. Run `alembic -c apps/api/alembic.ini heads` LIVE. Record the single head in the phase report. If more than one head is returned, STOP and re-chain — never force-merge.
- [ ] A2. Create `apps/api/models/identity_coop.py` with the three models above (`ContributionEvent`, `CreditLedgerEntry`, `ContributionConsentAcceptance`), Python 3.11 type-hint syntax only, following the `apps/api/models/identity_signal.py` shape.
- [ ] A3. Add `contribution_enabled: Mapped[bool] = mapped_column(default=False, nullable=False, server_default="false")` to `apps/api/models/site.py`, with an inline comment mirroring the `auto_identify_enabled` comment style.
- [ ] A4. Generate migration `add_identity_coop_tables` chaining onto the head from A1, creating all three tables plus indexes and the `uq_coop_contrib_site_email_day` unique constraint.
- [ ] A5. Generate migration `add_site_contribution_enabled` chaining onto A4, adding the `sites.contribution_enabled` column with `server_default='false'`.
- [ ] A6. Ensure both models are imported where SQLAlchemy mapper registration requires it (mirror how `identity_signal` is registered) — unit tests constructing ORM objects need `import apps.api.main` first or SQLAlchemy raises `InvalidRequestError`.
- [ ] A7. Offline-validate: `alembic -c apps/api/alembic.ini upgrade <head_from_A1>:head --sql` — explicit range required (unscoped `head --sql` fails mid-chain on `b7d3e9f1a4c2`).

### Step B — Config

- [ ] B1. Add the four settings above to `apps/api/config.py` under a `## ─── Identity co-op (Phase 1) ───` block, with an inline comment stating the required rollout order: erasure LIVE → flag ON per-site → never before legal review.
- [ ] B2. Assert in a unit test that all four defaults are OFF/inert and that `identity_coop_enabled is False`.

### Step C — Service module (all logic lives here)

- [ ] C1. Create `apps/api/services/identity_coop.py`. It MUST NOT import `identity_resolver` at module level (no circular import); it takes a plain `AsyncSession`, `Site`/`Visitor`, and the resolved data — no shared state.
- [ ] C2. Implement `async def record_contribution(db, *, site_id, email_bidx, source_provider, is_abuse_flagged, contributed_on) -> None`:
      1. Insert the contribution event with `ON CONFLICT (site_id, email_bidx, contributed_on) DO NOTHING` (merge-awareness, AC-3).
      2. If the insert was a no-op (duplicate), return — no accrual.
      3. If `is_abuse_flagged` is True: set `accrued=False`, `excluded_reason='abuse_flagged'`, return without accrual (AC-9 — the EVENT is still recorded; only ACCRUAL is gated).
      4. If the row's `email_bidx` matches a `SuppressionEntry(scope="erased")` blind index: set `excluded_reason='erased'`, return without accrual (SPEC A interface obligation).
      5. Otherwise write ONE `ACCRUE` ledger row: `amount=settings.coop_credit_per_contribution`, `lot_id=<own id>`, `spendable_at=now+coop_credit_hold_hours`, `expires_at=now+coop_credit_expiry_days`, `reason='contribution'`, `contribution_event_id=<event id>`; and set the event's `accrued=True`.
- [ ] C3. Implement `async def spendable_balance(db, site_id) -> int` — `SUM(amount)` over ledger rows where the lot is past `spendable_at` and not past `expires_at`. Read-time computed, never a stored column. (Phase 2 extends this; the Phase 1 version proves AC-8's shape.)
- [ ] C4. Wrap the whole `record_contribution` body in try/except; log `structlog.warning("coop_contribution_failed", error=str(exc))` on failure — keys/ids only, NEVER PII. A co-op failure must never break a successful identification.
- [ ] C5. Implement `async def record_consent_acceptance(db, *, site_id, terms_version, user_id) -> None` — append-only insert, no update path.

### Step D — The hook (~2 lines in the contested file)

- [ ] D1. In `apps/api/services/identity_resolver.py`, **immediately after the `_upsert_beam_identity(visitor, data, provider)` call inside `_save_identified`** (NOT by line number — locate the call), insert:
      ```
      if settings.identity_coop_enabled and site_contribution_enabled:
          await record_contribution(...)
      ```
      Import `record_contribution` INSIDE the function (local import), matching the
      `_log_owned_resolution` local-import precedent, to avoid any module-load circularity.
- [ ] D2. Resolve `site_contribution_enabled` by loading the `Site` row's `contribution_enabled` in the same session — do NOT add a second network/DB round-trip on the hot path if the resolver already has the Site loaded; if it does not, use a single scalar select and cache on the resolver instance for the request.
- [ ] D3. Compute `email_bidx` via the existing `apps.api.services.pii_crypto.email_hash` — the same function `_upsert_beam_identity` already uses. Never pass plaintext email into the co-op module.
- [ ] D4. Verify the diff inside `identity_resolver.py` is ≤ 6 lines total (hook + local import). If it is larger, the logic leaked out of `identity_coop.py` — move it back.

### Step E — 7-layer flag wiring (layers 1-4; UI layers land in Phase 3)

- [ ] E1. `apps/api/schemas/sites.py` — add `contribution_enabled: bool | None = None` to the site update schema and `contribution_enabled: bool` to the site read schema.
- [ ] E2. `apps/api/routers/sites.py` — in the site-update handler, reject any request setting `contribution_enabled=True` unless a `terms_version` acceptance is supplied; write the acceptance row via `record_consent_acceptance` in the SAME transaction as the flag flip (AC-10 automated leg). Setting it to `False` requires no acceptance.
- [ ] E3. Confirm the site-update handler already filters `Site.user_id == user.id` and returns 404 (never 403) for a foreign `site_id`. Add a test if not covered.

### Step F — Tests

- [ ] F1. `tests/integration/test_identity_coop_contribution.py::test_flag_off_produces_zero_contributions` — a full resolve cycle on a site with `contribution_enabled=False` writes zero contribution-event rows and zero ledger rows (**AC-1**).
- [ ] F2. `tests/integration/test_identity_coop_contribution.py::test_non_contributor_still_receives_graph_matches` — a site with `contribution_enabled=False` STILL receives a graph-served identification (**AC-2, model (a)**).
- [ ] F3. `tests/unit/test_identity_coop.py::test_merged_duplicate_counts_once` — two resolves of the same email under two different `visitor_id`s on the same day produce exactly ONE contribution event (**AC-3**).
- [ ] F4. `tests/integration/test_identity_coop_contribution.py::test_qualifying_contribution_writes_ledger_row` — one qualifying contribution ⇒ exactly one positive `ACCRUE` row with `site_id`, `reason`, `created_at`, `expires_at`, `spendable_at` (**AC-5**).
- [ ] F5. `tests/integration/test_identity_coop_contribution.py::test_abuse_flagged_visitor_earns_no_credit` — a resolve driven by `visitor.is_abuse_flagged=True` produces a contribution EVENT with `excluded_reason='abuse_flagged'` and ZERO ledger rows, even though the graph write still occurs (**AC-9**).
- [ ] F6. `tests/unit/test_identity_coop.py::test_erased_row_earns_no_credit` — an `email_bidx` present in `SuppressionEntry(scope="erased")` yields `excluded_reason='erased'` and zero accrual (SPEC A interface).
- [ ] F7. `tests/unit/test_identity_coop.py::test_grandfathered_rows_contribute_zero` — a pre-existing `beam_identity_graph` row with no matching contribution event contributes 0 to any site's ledger (**AC-12**).
- [ ] F8. `tests/unit/test_identity_coop.py::test_coop_failure_does_not_break_identification` — force `record_contribution` to raise; assert `_save_identified` still returns the `IdentifiedVisitor`.

### Step G — Migration round-trip

- [ ] G1. Bring up a DISPOSABLE Postgres (`docker compose -f infra/docker-compose.yml up -d postgres`, or an ad-hoc container). NEVER a shared/prod database.
- [ ] G2. Run `upgrade head` → `downgrade -1` → `downgrade -1` → `upgrade head`; assert clean both directions. Record the exact commands and output in the phase report.

---

## Exit Gate

```bash
# Unit lane
.venv/bin/python3.11 -m pytest tests/unit -m unit -q
# Expected: exit 0, including the 4 new unit tests

# Integration lane
.venv/bin/python3.11 -m pytest tests/ -m integration -q
# Expected: exit 0, including the 4 new integration tests

# Alembic head currency (run LIVE, do not hardcode)
alembic -c apps/api/alembic.ini heads
# Expected: exactly one head, equal to the Phase 1 migration revision

# Offline SQL validation with an EXPLICIT range (unscoped head --sql fails mid-chain)
alembic -c apps/api/alembic.ini upgrade <head_recorded_at_A1>:head --sql
# Expected: exit 0, DDL emitted for all three tables + the sites column

# Diff footprint guard on the contested file
git diff --stat apps/api/services/identity_resolver.py
# Expected: <= 6 changed lines
```

- All checklist items checked.
- `identity_coop_enabled` and `Site.contribution_enabled` both default OFF, proven by test.
- Disposable-Postgres migration round-trip clean (Hybrid gate).
- Phase report written to the report destination above.

---

## Acceptance Criteria

- **AC-1** — `contribution_enabled` defaults OFF for every site; while OFF a resolve cycle produces zero counted contributions.
- **AC-2** — a non-contributing site STILL receives graph-served identifications (model (a), read unconditional).
- **AC-3** — the same email resolved twice under two `visitor_id`s on the same day yields exactly one contribution event.
- **AC-5** — one qualifying contribution yields exactly one positive `ACCRUE` ledger row with site_id, reason, timestamp, expires_at.
- **AC-9** — a resolve driven by `is_abuse_flagged=True` traffic yields a contribution EVENT but zero credit accrual.
- **AC-12** — pre-program `beam_identity_graph` rows contribute 0 to any site's ledger.
- SPEC A interface: an `email_bidx` tombstoned via `SuppressionEntry(scope="erased")` yields zero accrual.
- A co-op failure never breaks a successful identification.

---

## Phase Completion Rules

- 🔨 **CODE DONE** — all checklist items checked, code written, no test evidence yet.
- 🧪 **TESTING** — unit + integration lanes running; failures being fixed inline.
- ✅ **VERIFIED** — both pytest lanes exit 0, offline `--sql` validation clean, disposable-Postgres
  round-trip clean, validate-contract written (non-placeholder), and the phase report records the
  live `alembic heads` value used as `down_revision`.
- 🚧 **BLOCKED** — an upstream dependency is unmet, or `alembic heads` returned multiple heads.
- Docker unavailable ⇒ the round-trip becomes a Known-Gap + backlog stub and the phase gate stays
  **CONDITIONAL**; it may NOT be promoted to ✅ VERIFIED on offline `--sql` alone.

---

## Blockers That Would Justify BLOCKED Status

- `identity-vocab-reconcile_07-08-26` still `Gate: BLOCKED` and not descoped.
- SPEC A `graph-erasure-compliance_07-08-26` not LIVE — the erased-row exclusion in C2 step 4 has no `SuppressionEntry(scope="erased")` surface to filter against.
- `alembic heads` returns more than one head and re-chaining would require touching another program's migration.
- Docker unavailable ⇒ the G2 round-trip cannot run. Record as a Known-Gap + backlog stub and keep the phase gate **CONDITIONAL** (do not mark ✅ VERIFIED on offline `--sql` alone).
- The hook diff inside `identity_resolver.py` cannot be kept small because a concurrent workstream restructured `_save_identified`.

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner
loop `R → I → P → PVL → E → EVL → UP` SKIPS SPEC.

- [ ] 1. RESEARCH — research-agent: upstream dependency status confirmed; `identity_resolver.py` drift checked; test context loaded
- [ ] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: this plan updated; Inner Loop Refresh Note if sections changed (or "n/a — research clean")
- [ ] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md`
- [ ] 5. EXECUTE — all checklist items done; per-section test gates run and green
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** If step 4 is unchecked or `## Validate Contract`
reads "(placeholder — ...)", the orchestrator must spawn vc-validate-agent first.

---

## Touchpoints

- `apps/api/models/identity_coop.py` (NEW)
- `apps/api/services/identity_coop.py` (NEW)
- `apps/api/models/site.py`
- `apps/api/config.py`
- `apps/api/services/identity_resolver.py` (~2-line hook, call-graph-positioned)
- `apps/api/schemas/sites.py`
- `apps/api/routers/sites.py`
- `apps/api/services/pii_crypto.py` (READ ONLY — `email_hash`)
- `apps/api/services/identity_classification.py` (READ ONLY — `OWNED_FREE_PROVIDERS`)
- `apps/api/alembic/versions/` (2 new migrations)
- `tests/unit/test_identity_coop.py` (NEW)
- `tests/integration/test_identity_coop_contribution.py` (NEW)

---

## Public Contracts

- `_save_identified` return type and existing side effects UNCHANGED; the hook is additive and best-effort.
- Graph READ path UNCHANGED — no contribution gate added (AC-2 model (a)).
- `api_usage_logs` / `resolution_logs` write paths UNCHANGED.
- `PATCH /api/v1/sites/{site_id}` gains one additive optional boolean; setting it to `True` now requires an accompanying `terms_version`. Existing fields unchanged.
- Pixel consent banner UNCHANGED.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `test_flag_off_produces_zero_contributions` | Fully-Automated | AC-1 |
| `test_non_contributor_still_receives_graph_matches` | Fully-Automated | AC-2 |
| `test_merged_duplicate_counts_once` | Fully-Automated | AC-3 |
| `test_qualifying_contribution_writes_ledger_row` | Fully-Automated | AC-5 |
| `test_abuse_flagged_visitor_earns_no_credit` | Fully-Automated | AC-9 |
| `test_grandfathered_rows_contribute_zero` | Fully-Automated | AC-12 |
| `test_erased_row_earns_no_credit` | Fully-Automated | SPEC A interface obligation |
| `test_coop_failure_does_not_break_identification` | Fully-Automated | Best-effort hook contract |
| `alembic upgrade <head>:head --sql` exits 0 | Fully-Automated | Migration-currency constraint |
| Disposable-Postgres round-trip clean | Hybrid (precondition: disposable Postgres container) | Schema/migration high-risk class |
| `git diff --stat apps/api/services/identity_resolver.py` ≤ 6 lines | Fully-Automated | Collision-minimization constraint |

---

## Test Infra Improvement Notes

(none identified yet)

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/visitors-identity/active/identity-coop_07-08-26/phase-1-ledger-substrate_PLAN_07-08-26.md`
- Last completed step: not started
- Validate-contract status: pending
- Supporting context files loaded: `process/context/all-context.md`, `process/context/tests/all-tests.md`, `identity-coop_SPEC_07-08-26.md`, umbrella plan
- Next step: confirm both upstream dependencies have cleared, then spawn vc-research-agent for RESEARCH (Step 1)

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
