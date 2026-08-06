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

**VALIDATE 07-08-26 (2nd outer-PVL pass) re-derivation of this gate — supersedes the 1st pass:**
- `identity-vocab-reconcile_07-08-26`: **NOT literal `Gate: PASS`.** Actual state is `Gate:
  CONDITIONAL`, explicitly user-accepted at PLAN supplement cycle 9, EXECUTED, merged onto
  `devjulley`. Satisfies the *intent* (the `identity_resolver.py` churn has settled and shipped) but
  not the literal wording. Wording gap, not a hard blocker on its own.
- SPEC A `graph-erasure-compliance_07-08-26`: **EXECUTE is now COMPLETE — this changed since the 1st
  pass.** `graph-erasure-compliance_REPORT_07-08-26.md` exists (`status: COMPLETE_WITH_GAPS`), all 30
  checklist items applied, 1165/1165 unit tests green, migration `d1a6c4e93f27` landed, and
  `services/graph_erasure.py` / `models/erasure_request.py` / the `_upsert_beam_identity` write
  boundary are all present on disk (verified by direct read). **But it is NOT LIVE.** Its own report
  states `CODE DONE`, not `EVL GREEN`: the 14 integration gates (T-I1…T-I10) are written and
  collect cleanly but have **never executed** (Docker down — independently re-confirmed this pass,
  `docker info` fails), the migration live round-trip is **deferred, not passed**, and nothing is
  deployed (branch `devjulley`, unpushed; `graph_erasure_sweep_enabled` default `True` has never run
  anywhere real).
- `alembic heads` (Entry Gate item 4): **NOW MET.** Live run this pass —
  `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` → **`d1a6c4e93f27` (head)`,
  exactly ONE head**. The 1st pass's claim of FIVE heads was a hand-parse artifact (it could not run
  alembic) and is **retracted**. A1's STOP-and-re-chain condition will not fire. Still re-derive
  live at EXECUTE time — this repo's head moves on a roughly daily cadence.
- **Conclusion: Entry Gate is still UNMET, now on ONE criterion instead of two** — SPEC A's "LIVE"
  half. Per this section's own rule, Phase 1 must report BLOCKED and must not partially execute.
  See Validate Contract.

---

## Locked Constraints Inherited From the Umbrella

- Read access is UNCONDITIONAL (AC-2 model (a)). This phase MUST NOT add any gate to the graph read path.
- Flags default OFF. No production enablement.
- No purge / retro-attribution / retro-credit of pre-program rows.
- No PII in logs. Contribution events key on `email_bidx` (blind index), never plaintext email.
- Hook described by call-graph position only, never line number.

---

## PLAN Decisions Settled at PVL Supplement (07-08-26, cycle 1)

Five decisions the 2nd outer-PVL contract explicitly deferred to PLAN. All are now LOCKED.
They resolve F2, F3, C1, C3, C5, C6, C8.

### D-A (resolves F2) — accrual is gated on a real graph write; `_upsert_beam_identity` returns `bool`

**Decision: resolution shape (a).** `_upsert_beam_identity` changes signature from `-> None` to
`-> bool`: `True` only when the upsert statement actually executed, `False` on every one of its
three early no-op returns (missing fingerprint/email; `visitor.do_not_resolve`; an
`is_email_suppressed_any(..., GRAPH_WRITE_BLOCKING_SCOPES)` tombstone). The hook is gated on that
return value.

**D4's diff budget is RAISED from ≤ 6 to ≤ 12 changed lines in `identity_resolver.py`**, with this
rationale on record:

- This is the **billing/credits** high-risk class. A ledger that mints a credit for a write that
  never happened is a correctness defect in the money surface, which outranks a self-imposed
  diff-cosmetic budget. The budget existed to limit cross-program collision risk, not to make an
  accounting hook lie.
- Shape (b) (hook inside `_upsert_beam_identity`) was REJECTED: it buries a credit-accounting call
  inside a privacy write-boundary function and contradicts the call-graph anchor that both this
  plan and `phase-blast-radius-registry.md` line 19 declare. Relocating that anchor mid-program is
  a worse cross-program signal than 6 extra lines.
- Shape (c) (re-derive the three no-op conditions inside `identity_coop.py`) was REJECTED: it
  triples the drift surface and is the exact option that already produced the C1 and F3 defects.
- Collision cost is bounded: `_upsert_beam_identity` has **exactly one production caller**
  (`identity_resolver.py:1252`, verified live 07-08-26). No other module reads its return.
- Test compatibility: existing tests that `await resolver._upsert_beam_identity(...)` never assert
  the return, and tests that replace it with `AsyncMock()` get a truthy Mock — which would make the
  hook fire, but it stays inert because `identity_coop_enabled` defaults `False`. No test rewrite
  required. F-new-1 below asserts this explicitly.

### D-B (resolves F3 + C1) — no bidx-bearing co-op row is written when the graph write was blocked

**Decision: option (a) — write NOTHING.** When `_upsert_beam_identity` returns `False`, the hook does
not fire at all: no contribution event, no `excluded_reason='erased'` row, no ledger row. C2 step 4's
own suppression re-check is **DELETED** (see C2 below).

Rationale: `ERASURE_TARGETS = ("beam_identity_graph",)` (`models/erasure_request.py:31`, verified
live). Any co-op row carrying an `email_bidx` for an erased person is unreachable by SPEC A's sweep —
a new record of a person created *after* their erasure. Adding the co-op tables to `ERASURE_TARGETS`
(option b) was REJECTED: umbrella line 94 forbids this program from changing SPEC A's mechanics, and
it would widen SPEC A's sweep blast radius after SPEC A is already code-frozen.

**SPEC A sweep semantics stay intact** — untouched: this decision only removes a would-be new target,
it changes nothing about the sweep, `ERASURE_TARGETS`, or the write boundary itself.

**Privacy invariant (new, testable):** `identity_contribution_events` may contain an `email_bidx`
**only** for a person for whom a `beam_identity_graph` write succeeded. Proven by
`test_erased_person_leaves_no_new_bidx_row` and `test_blocked_graph_write_accrues_nothing`.

C1 is resolved as a side effect: the co-op module no longer re-lists ANY suppression scope, so the
`erased`-only narrowness cannot exist. The single source of truth stays
`GRAPH_WRITE_BLOCKING_SCOPES` + `is_email_suppressed_any` inside the resolver's own boundary. This
also resolves the C2 "duplicated gate" concern by deletion rather than by widening.

### D-C (resolves C3) — fraud gate covers `is_bot_suspect` as well as `is_abuse_flagged`

`record_contribution`'s signature gains `is_bot_suspect: bool`. Either flag True ⇒
`accrued=False`, `excluded_reason='fraud_flagged'`, no ledger row. Matches SPEC AC-9's
"`is_abuse_flagged` / `is_bot_suspect` (or equivalent)". Both columns exist on `Visitor`
(`models/visitor.py:105` and `:207` — verified live). `excluded_reason` vocabulary becomes
`'fraud_flagged' | 'duplicate' | NULL` (`'abuse_flagged'` and `'erased'` are both retired:
the first is subsumed, the second can no longer occur by D-B).

### D-D (resolves C6) — ledger stays `site_id`-scoped; Phase 2 aggregates per-user at gate time

**Decision: NO `user_id` column on `identity_credit_ledger`.** The ledger keeps `site_id` only.

Rationale: `site_id` is the attribution unit and matches `beam_identity_graph.source_site_id`'s
shape; `user_id` is always derivable via `Site.user_id`, so storing it would be denormalized state
that silently goes stale if a site is ever reassigned to another user. Attribution must follow the
site that earned the credit.

**Phase-2 consequence (binding, recorded here because the schema freezes after Phase 1):** Phase 2's
spend gate must aggregate the ledger **across all of a user's sites** by joining
`identity_credit_ledger.site_id → sites.site_id → sites.user_id`, then apply the resulting balance at
`billing.check_usage_allowed(db, user_id)`'s `user_id`-scoped decision point
(`services/billing.py:94`). Phase 2 MUST NOT add a per-site monthly gate (the daily resolution
budget is explicitly out of its scope) and MUST NOT add a `user_id` column to the frozen schema.
This consequence is mirrored into `phase-blast-radius-registry.md` §Phase 2.

### D-E (resolves C8) — accrual is once per `(site_id, email_bidx)` for all time, not once per day

The event table's `(site_id, email_bidx, contributed_on)` unique key stays as-is (per-day audit
granularity). But **accrual** gets its own, stricter uniqueness:

**Partial unique index `uq_coop_accrued_site_email` on `(site_id, email_bidx) WHERE accrued IS
TRUE`.** A site earns at most ONE credit per identity, ever. A repeat resolve on a later day still
records an event row (`accrued=False`, `excluded_reason='duplicate'`) for auditability, but mints no
credit.

Rationale: SPEC line 63 says "every **new** graph write is counted as a contribution", and
`_upsert_beam_identity` uses `on_conflict_do_update` — so a repeat resolve of an
already-graph-held person is an UPDATE, not new data. Without this index the plan mints a fresh
credit every calendar day forever for the same person, which is credit inflation on the money
surface. Enforced in the DB (not only in service code) so it cannot be bypassed by a concurrent
race.

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
- `apps/api/migrations/versions/{rev}_add_identity_coop_tables.py` (NEW — **path corrected at
  VALIDATE 07-08-26; plan originally said `apps/api/alembic/versions/`, which does not exist. See
  Validate Contract Finding L2-A1.**)
- `apps/api/migrations/versions/{rev}_add_site_contribution_enabled.py` (NEW — path corrected, same as above)
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
| `excluded_reason` | String(30), nullable | `'fraud_flagged'` / `'duplicate'` / NULL — **vocabulary settled at PVL supplement 07-08-26 (D-C, D-B): `'abuse_flagged'` is subsumed by `'fraud_flagged'`, and `'erased'` is retired because no row is ever written for a blocked graph write** |
| `created_at` | DateTime(tz), server_default now() | |

**Unique constraint `uq_coop_contrib_site_email_day` on `(site_id, email_bidx, contributed_on)`.**
This is the merge-awareness mechanism (AC-3): a person resolved twice under two `visitor_id`s on
the same day produces ONE contribution row via `ON CONFLICT DO NOTHING`. It is keyed on neither
`visitor_id` nor graph-row id, so the 5-file merged-visitor gap is structurally irrelevant here.

**VALIDATE confirms this mechanism is even stronger than described:** direct read of
`identity_resolver.py::_save_identified` (lines ~1117-1144) shows the SECOND resolve of the same
`(site_id, email)` under a different `visitor_id` is caught by an existing ORM-level email-dedup
check and **returns early at line 1144, before ever reaching the `_upsert_beam_identity` /
contribution-hook call site at line 1252.** The DB-level unique constraint is still correctly
required as the belt-and-suspenders guard against the true concurrent-race case (two requests
both passing the ORM check before either commits) — but the common sequential-duplicate case never
even reaches the hook. No defect; this is a positive confirmation.

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

**VALIDATE confirms no collision:** none of these four settings, `Site.contribution_enabled`, or
any of `apps/api/models/identity_coop.py` / `apps/api/services/identity_coop.py` /
`apps/api/routers/identity_coop.py` currently exist on disk. Clean to create.

---

## Implementation Checklist

### Step A — Models and migrations

- [ ] A1. Run `alembic -c apps/api/alembic.ini heads` LIVE. Record the single head in the phase report. If more than one head is returned, STOP and re-chain — never force-merge. **VALIDATE 07-08-26 (2nd pass) — RETRACTS the 1st pass's "five heads" claim.** The 1st pass could not run alembic and hand-parsed the revision headers. This pass ran the real command: `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` → **`d1a6c4e93f27` (head)` — exactly ONE head.** Chain tail (via `history -r-6:head`): `f1a7c3e05b92 → a4f2b8c15d70 → b8e3f6a2c904 → c9f4a7b31e85 → d1a6c4e93f27`. Historical branchpoints (`b7e1a2c9d4f0`, `f1a9c4d7e2b8`) exist but the DAG converges to one head. **A1's STOP condition will NOT fire.** Neither `e6b2d4a1c837` (umbrella) nor `c9f4a7b31e85` (SPEC A's report) is the head any more — `d1a6c4e93f27` chained onto `c9f4a7b31e85`. Still re-run `alembic heads` LIVE at EXECUTE time and record the value: four migrations landed in this repo within the last day, so treat every head string written in any of these documents as expired.**
- [ ] A2. Create `apps/api/models/identity_coop.py` with the three models above (`ContributionEvent`, `CreditLedgerEntry`, `ContributionConsentAcceptance`), Python 3.11 type-hint syntax only, following the `apps/api/models/identity_signal.py` shape.
- [ ] A3. Add `contribution_enabled: Mapped[bool] = mapped_column(default=False, nullable=False, server_default="false")` to `apps/api/models/site.py`, with an inline comment mirroring the `auto_identify_enabled` comment style.
- [ ] A4. Generate migration `add_identity_coop_tables` chaining onto the head from A1, creating all three tables plus indexes, the `uq_coop_contrib_site_email_day` unique constraint, **and the partial unique index `uq_coop_accrued_site_email` on `(site_id, email_bidx) WHERE accrued IS TRUE` (D-E — the once-per-identity accrual rule; must be a DB constraint, not service-code-only)**. **Write it to `apps/api/migrations/versions/` — confirmed via `apps/api/alembic.ini`'s `script_location = %(here)s/migrations`. `apps/api/alembic/versions/` does not exist and is not scanned by Alembic; a file written there is silently invisible to every `alembic` command.**
- [ ] A5. Generate migration `add_site_contribution_enabled` chaining onto A4, adding the `sites.contribution_enabled` column with `server_default='false'`. **Same corrected path: `apps/api/migrations/versions/`.**
- [ ] A6. Ensure both models are imported where SQLAlchemy mapper registration requires it (mirror how `identity_signal` is registered) — unit tests constructing ORM objects need `import apps.api.main` first or SQLAlchemy raises `InvalidRequestError`.
- [ ] A7. Offline-validate: `alembic -c apps/api/alembic.ini upgrade <head_from_A1>:head --sql` — explicit range required (unscoped `head --sql` fails mid-chain on `b7d3e9f1a4c2`).

### Step B — Config

- [ ] B1. Add the four settings above to `apps/api/config.py` under a `## ─── Identity co-op (Phase 1) ───` block, with an inline comment stating the required rollout order: erasure LIVE → flag ON per-site → never before legal review.
- [ ] B2. Assert in a unit test that all four defaults are OFF/inert and that `identity_coop_enabled is False`.

### Step C — Service module (all logic lives here)

- [ ] C1. Create `apps/api/services/identity_coop.py`. It MUST NOT import `identity_resolver` at module level (no circular import); it takes a plain `AsyncSession`, `Site`/`Visitor`, and the resolved data — no shared state.
- [ ] C2. Implement `async def record_contribution(db, *, site_id, email_bidx, source_provider, is_abuse_flagged, is_bot_suspect, contributed_on) -> None`:
      1. Insert the contribution event with `ON CONFLICT (site_id, email_bidx, contributed_on) DO NOTHING` (merge-awareness, AC-3).
      2. If the insert was a no-op (duplicate), return — no accrual.
      3. If `is_abuse_flagged` **or `is_bot_suspect`** is True: set `accrued=False`, `excluded_reason='fraud_flagged'`, return without accrual (AC-9 — the EVENT is still recorded; only ACCRUAL is gated). **Widened at PVL supplement 07-08-26 per D-C; `Visitor.is_bot_suspect` (`models/visitor.py:207`) is now consulted.**
      4. **(REWRITTEN at PVL supplement 07-08-26 — see D-B. Supersedes everything the two prior
      validate passes wrote about this step.)** There is **NO suppression check in this module at
      all.** `record_contribution` is only ever called when `_upsert_beam_identity` returned `True`
      (D-A), which means the resolver's own write boundary already cleared `do_not_resolve` and all
      of `GRAPH_WRITE_BLOCKING_SCOPES` + `"all"`. The co-op module therefore must NOT import
      `SuppressionEntry`, must NOT re-list any scope literal, and must NOT write any row for a
      blocked write. Deleting this check is what resolves F3, C1, and C2 at once: no bidx-bearing
      co-op row can exist for an erased person, so the fact that the co-op tables sit outside
      `ERASURE_TARGETS` becomes harmless instead of a privacy defect.
      4b. Enforce the once-per-identity accrual rule (D-E): attempt the `ACCRUE` insert against the
      partial unique index `uq_coop_accrued_site_email`; on conflict, set the event's
      `excluded_reason='duplicate'`, leave `accrued=False`, and return without accrual.
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
      **VALIDATE 07-08-26 confirms this anchor resolves cleanly against the live tree: the
      `_upsert_beam_identity(visitor, data, provider)` call is at line 1252 (as of this cycle),
      immediately followed by the best-effort hot-alert block at lines 1254-1260 — inserting the
      hook between them is exactly the described position, no ambiguity, no collision with either
      of the two other concurrent workstreams that also touch this file. The general local-import
      precedent cited is real (confirmed at lines 129, 164, 204 of the same file — e.g. `from
      apps.api.services.suppression import is_email_suppressed`), though the specific function
      named (`_log_owned_resolution`) is itself same-file, not an external local import — a minor
      citation imprecision, not a feasibility problem.**
      **VALIDATE 07-08-26 (2nd pass) — FAIL: the hook as specified accrues credit when NO graph
      write happened.** `_upsert_beam_identity` returns **`None`** (`-> None`, line 1264-1266) and
      silently returns early in three cases before writing anything: (1) `if not fp or not email:
      return` (1270-71); (2) `visitor.do_not_resolve` truthy ⇒ `graph_write_blocked`, return
      (1279-85); (3) `is_email_suppressed_any(..., GRAPH_WRITE_BLOCKING_SCOPES)` truthy ⇒ same
      return. Case (2) and (3) are NEW — SPEC A's write boundary landed after this plan was
      written. Because the return carries no signal, the caller cannot know whether a row was
      written, so a hook placed after the call counts a contribution that did not occur. SPEC AC-3
      ("every graph write attributable to an opted-in site is counted") and SPEC line 63 ("every new
      graph write ... is counted as a contribution") define a contribution AS the graph write, so
      this is a direct AC-3/AC-5 violation, not a nit. Three resolution shapes, all with costs —
      pick one at PLAN, do not let D4's line budget pick it: (a) change `_upsert_beam_identity` to
      return `bool` and gate the hook on it (most faithful; changes a signature inside a file three
      programs contest, and BREAKS D4's ≤6-line cap); (b) move the hook INSIDE
      `_upsert_beam_identity` after the successful insert (smallest truthful diff; relocates the
      call-graph position this plan and the registry both describe); (c) re-derive all three no-op
      conditions inside `identity_coop.py` (no resolver change; triples the drift surface — this is
      the option that produced the C2-step-4 defects above).
      **SETTLED at PVL supplement 07-08-26 — shape (a). See §PLAN Decisions D-A.** The hook becomes:
      ```
      wrote = await self._upsert_beam_identity(visitor, data, provider)
      if wrote and settings.identity_coop_enabled and site_contribution_enabled:
          await record_contribution(...)
      ```
      and `_upsert_beam_identity`'s signature changes `-> None` → `-> bool` (`True` only where the
      upsert statement executed; `False` at each of its three early returns). Exactly one production
      caller exists, verified live. D4's budget is raised to ≤ 12 lines to pay for it.
- [ ] D2. Resolve `site_contribution_enabled` by loading the `Site` row's `contribution_enabled` in the same session — do NOT add a second network/DB round-trip on the hot path if the resolver already has the Site loaded; if it does not, use a single scalar select and cache on the resolver instance for the request. **VALIDATE 07-08-26 confirms: the resolver does NOT cache a `Site` ORM instance anywhere in its state (`__init__` only holds `db` and `redis_client`; the only `Site` touch in the whole file is a narrow `select(Site.url)` at one call site). The "already loaded" branch will not apply in the general case — implementers should expect the fallback (single scalar select, cached on the resolver instance for the request) to be the path actually taken. Not a defect: the plan's own fallback instruction already covers this correctly.**
- [ ] D3. Compute `email_bidx` via the existing `apps.api.services.pii_crypto.email_hash` — the same function `_upsert_beam_identity` already uses. Never pass plaintext email into the co-op module.
- [ ] D4. Verify the diff inside `identity_resolver.py` is **≤ 12 lines** total (hook + local import + the `-> bool` signature change and its three `return False` / one `return True` edits). **Budget RAISED from ≤ 6 at PVL supplement 07-08-26 — rationale in §PLAN Decisions D-A; the ≤ 6 figure is superseded everywhere it appears in this document.** If it is larger than 12, the logic leaked out of `identity_coop.py` — move it back.

- [ ] D5. Apply the `-> bool` change inside `_upsert_beam_identity` itself: `return False` at each of the three existing early-return guards (no fingerprint/email; `do_not_resolve`; `is_email_suppressed_any(..., GRAPH_WRITE_BLOCKING_SCOPES)`), `return True` after the upsert statement executes, and `return False` in the `except` path. Do NOT change the guards' logic or ordering — only the returned value. Update the docstring.

### Step E — 7-layer flag wiring (layers 1-4; UI layers land in Phase 3)

- [ ] E1. `apps/api/schemas/sites.py` — add `contribution_enabled: bool | None = None` to the site update schema and `contribution_enabled: bool` to the site read schema.
- [ ] E2. `apps/api/routers/sites.py` — in the site-update handler, reject any request setting `contribution_enabled=True` unless a `terms_version` acceptance is supplied; write the acceptance row via `record_consent_acceptance` in the SAME transaction as the flag flip (AC-10 automated leg). Setting it to `False` requires no acceptance.
- [ ] E4. **Minimal `terms_version` validator (added at PVL supplement 07-08-26 — resolves C5's vacuous-guard half).** Add `coop_terms_version: str` to the Phase 1 config block, pinned to the hex digest of the current policy text. `routers/sites.py` rejects `422` unless the submitted `terms_version` is a 64-char lowercase hex string **and** equals `settings.coop_terms_version`. This is deliberately a constant compare, not a module: the full `coop_terms.py` (multi-version history, migration between versions) still lands in Phase 3 and supersedes this check. Without E4, E2's guard is satisfied by `terms_version="x"` against a field the data model calls "an immutable snapshot hash of the exact policy text".
- [ ] E3. Confirm the site-update handler already filters `Site.user_id == user.id` and returns 404 (never 403) for a foreign `site_id`. Add a test if not covered.

### Step F — Tests

- [ ] F1. `tests/integration/test_identity_coop_contribution.py::test_flag_off_produces_zero_contributions` — a full resolve cycle on a site with `contribution_enabled=False` writes zero contribution-event rows and zero ledger rows (**AC-1**).
- [ ] F2. `tests/integration/test_identity_coop_contribution.py::test_non_contributor_still_receives_graph_matches` — a site with `contribution_enabled=False` STILL receives a graph-served identification (**AC-2, model (a)**).
- [ ] F3. `tests/unit/test_identity_coop.py::test_merged_duplicate_counts_once` — two resolves of the same email under two different `visitor_id`s on the same day produce exactly ONE contribution event (**AC-3**).
- [ ] F4. `tests/integration/test_identity_coop_contribution.py::test_qualifying_contribution_writes_ledger_row` — one qualifying contribution ⇒ exactly one positive `ACCRUE` row with `site_id`, `reason`, `created_at`, `expires_at`, `spendable_at` (**AC-5**).
- [ ] F5. `tests/integration/test_identity_coop_contribution.py::test_abuse_flagged_visitor_earns_no_credit` — a resolve driven by `visitor.is_abuse_flagged=True` produces a contribution EVENT with `excluded_reason='abuse_flagged'` and ZERO ledger rows, even though the graph write still occurs (**AC-9**).
- [ ] ~~F6~~. **RETIRED at PVL supplement 07-08-26 (D-B) — do not write this test.** Superseded by F9/F10: the co-op module no longer performs its own suppression check, so there is no in-module `erased` branch left to exercise. Original text: `tests/unit/test_identity_coop.py::test_erased_row_earns_no_credit` — an `email_bidx` present in `SuppressionEntry(scope="erased")` yields `excluded_reason='erased'` and zero accrual (SPEC A interface).
- [ ] F7. `tests/unit/test_identity_coop.py::test_grandfathered_rows_contribute_zero` — a pre-existing `beam_identity_graph` row with no matching contribution event contributes 0 to any site's ledger (**AC-12**).
- [ ] F8. `tests/unit/test_identity_coop.py::test_coop_failure_does_not_break_identification` — force `record_contribution` to raise; assert `_save_identified` still returns the `IdentifiedVisitor`.

- [ ] F9. `tests/unit/test_identity_coop.py::test_blocked_graph_write_accrues_nothing` — one case per `_upsert_beam_identity` no-op path (missing fingerprint; `do_not_resolve=True`; a `do_not_process` tombstone; an `all` tombstone): assert ZERO contribution-event rows AND zero ledger rows (**F2 / D-A / D-B**).
- [ ] F10. `tests/unit/test_identity_coop.py::test_erased_person_leaves_no_new_bidx_row` — after an erasure tombstone exists, a resolve attempt for that person leaves `identity_contribution_events` with no row bearing their `email_bidx` (**F3 / D-B privacy invariant**).
- [ ] F11. `tests/unit/test_identity_coop.py::test_bot_suspect_visitor_earns_no_credit` — `visitor.is_bot_suspect=True` ⇒ event with `excluded_reason='fraud_flagged'`, zero ledger rows (**AC-9 / D-C**).
- [ ] F12. `tests/unit/test_identity_coop.py::test_second_day_resolve_accrues_no_second_credit` — same `(site_id, email_bidx)` resolved on two different days ⇒ two event rows, the second `accrued=False, excluded_reason='duplicate'`, and exactly ONE ledger row total (**AC-5 / D-E**).
- [ ] F13. `tests/integration/test_identity_coop_contribution.py::test_flag_on_requires_acceptance` — `PATCH` setting `contribution_enabled=True` with no `terms_version` ⇒ 422 and flag unchanged; with a wrong-format or non-matching `terms_version` ⇒ 422; with the pinned version ⇒ 200 and exactly one acceptance row written in the same transaction (**AC-10 automated leg / E4**).
- [ ] F14. `tests/unit/test_identity_coop.py::test_upsert_returns_bool_and_existing_callers_unaffected` — `_upsert_beam_identity` returns `True` on a successful write and `False` on each guard path; and with `identity_coop_enabled=False` the hook stays inert even when the function is `AsyncMock`-replaced (**D-A test-compatibility claim**).

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
# VALIDATE 07-08-26 (2nd pass): live run returns exactly ONE head, d1a6c4e93f27. The 1st pass's
# "5 heads" claim is retracted. Re-derive live at EXECUTE time anyway — the head moves daily.

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
- **AC-9** — a resolve driven by `is_abuse_flagged=True` **or `is_bot_suspect=True`** traffic yields a contribution EVENT but zero credit accrual. **(Widened at PVL supplement 07-08-26 — D-C.)**
- **AC-10** — `contribution_enabled` cannot flip ON via the API without a validated `terms_version` and an acceptance row written in the same transaction. **(Adopted into Phase 1 at PVL supplement 07-08-26 — resolves C5. Phase 1 owns the automated leg because E2/E4 build it here; Phase 3 still owns the full `coop_terms.py` versioning module and the UX leg, and supersedes E4's constant compare. The umbrella Coverage Map's Phase-3-only assignment is amended to "Phase 1 (automated leg) + Phase 3 (module + UX)".)**
- **AC-12** — pre-program `beam_identity_graph` rows contribute 0 to any site's ledger.
- **Privacy invariant (D-B)** — no `identity_contribution_events` row bearing an `email_bidx` may exist for a person whose graph write was blocked. This is the standing guarantee that the co-op tables' absence from `ERASURE_TARGETS` is harmless.
- **Accrual uniqueness (D-E)** — at most one credit per `(site_id, email_bidx)` for all time, DB-enforced.
- SPEC A interface: an `email_bidx` tombstoned under ANY of `GRAPH_WRITE_BLOCKING_SCOPES`
  (`erased`, `do_not_process`) or `all` yields zero accrual **and leaves no co-op row at all**.
  **(Widened at VALIDATE 07-08-26 2nd pass — was `erased` only. Re-shaped at PVL supplement
  07-08-26 per D-B: enforced by the resolver's own boundary via the `bool` return, NOT by a second
  copy of the scope list inside `identity_coop.py`.)**
- A co-op failure never breaks a successful identification.

**PVL supplement 07-08-26 — all three gaps below are now CLOSED** (AC-10 adopted above with the E4
validator; AC-9 widened above; the no-graph-write case is covered by F9/F10/F14). The original
findings are retained verbatim for audit:

**VALIDATE 07-08-26 (2nd pass) — gaps in this AC list itself:**
- **AC-10's automated leg is built by E2 but appears nowhere in this list or in Verification
  Evidence.** The umbrella's Coverage Map assigns AC-10 to Phase 3, so as written this phase's EVL
  can go green having never exercised the acceptance guard it builds. Additionally `terms_version`
  has no validator until Phase 3's `coop_terms.py`, so a client sending `terms_version="x"`
  satisfies E2 — a vacuous guard on a field the data model calls "an immutable snapshot hash of the
  exact policy text". Add a proving gate here or move E2 to Phase 3; do not leave it orphaned.
- **AC-9's fraud gate is narrower than the SPEC's.** SPEC AC-9 names "`is_abuse_flagged` /
  `is_bot_suspect` (or equivalent)". `record_contribution`'s signature (C2) takes only
  `is_abuse_flagged`; `Visitor.is_bot_suspect` exists (`models/visitor.py:105`) and is never
  consulted. Widen the signature and add a test.
- **A no-graph-write case is untested.** No test drives a resolve where `_upsert_beam_identity`
  no-ops and asserts zero accrual — the exact hole that lets the D1 FAIL ship EVL-green.

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
- SPEC A `graph-erasure-compliance_07-08-26` not LIVE — the resolver's write boundary (which D-A/D-B now depend on for the `False` return) is `CODE DONE`, not `EVL GREEN`, and is undeployed. **This is the ONLY remaining blocker after the 07-08-26 PVL supplement; it is a Step-0 dependency block, not a plan defect.**
- `alembic heads` returns more than one head and re-chaining would require touching another program's migration.
- Docker unavailable ⇒ the G2 round-trip cannot run. Record as a Known-Gap + backlog stub and keep the phase gate **CONDITIONAL** (do not mark ✅ VERIFIED on offline `--sql` alone).
- The hook diff inside `identity_resolver.py` cannot be kept small because a concurrent workstream restructured `_save_identified`.

**VALIDATE 07-08-26: the second bullet is confirmed TRUE right now** — see Entry Gate section
above and the Validate Contract below. This is the active, live blocking condition for this cycle.

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner
loop `R → I → P → PVL → E → EVL → UP` SKIPS SPEC.

- [ ] 1. RESEARCH — research-agent: upstream dependency status confirmed; `identity_resolver.py` drift checked; test context loaded
- [ ] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: this plan updated; Inner Loop Refresh Note if sections changed (or "n/a — research clean")
- [x] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md` — **Gate: BLOCKED (07-08-26, 2nd outer-PVL pass; supersedes the 1st). Now 3 FAILs: (F1) Entry Gate — SPEC A's EXECUTE is COMPLETE but it is `CODE DONE`, not `EVL GREEN`, and nothing is deployed, so "LIVE" is unmet; external, not plan-fixable. (F2) the hook accrues credit even when `_upsert_beam_identity` no-ops — plan-fixable NOW. (F3) an erased person gets a new `email_bidx` row outside `ERASURE_TARGETS` — plan-fixable NOW. The 1st pass's "five alembic heads" FAIL is RETRACTED: live run returns one head, `d1a6c4e93f27`. F2 and F3 are independent of F1 — a PVL supplement cycle can clear both while F1 stays open, leaving a single external blocker.**
- [ ] 5. EXECUTE — all checklist items done; per-section test gates run and green
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** If step 4 is unchecked or `## Validate Contract`
reads "(placeholder — ...)", the orchestrator must spawn vc-validate-agent first.

- [x] 3b. PVL SUPPLEMENT (07-08-26, cycle 1) — F2, F3, C1, C2, C3, C5, C6, C8 addressed in plan text via §PLAN Decisions D-A…D-E. **F1 remains open and is NOT plan-fixable.** Re-run PVL from V1 when SPEC A goes LIVE.

**Do NOT spawn vc-execute-agent for this phase.** Status: **Dependency-BLOCKED — entry gate SPEC A
not LIVE; files never modified.** Gate is BLOCKED on F1 only. Re-check the Entry Gate section
above before any further action on this phase.

---

## Touchpoints

- `apps/api/models/identity_coop.py` (NEW)
- `apps/api/services/identity_coop.py` (NEW)
- `apps/api/models/site.py`
- `apps/api/config.py`
- `apps/api/services/identity_resolver.py` (~2-line hook, call-graph-positioned — **see the D1 FAIL note: the fix for it may legitimately grow this footprint**)
- `apps/api/schemas/sites.py`
- `apps/api/routers/sites.py`
- `apps/api/services/pii_crypto.py` (READ ONLY — `email_hash`)
- `apps/api/services/identity_classification.py` (READ ONLY — `OWNED_FREE_PROVIDERS`)
- `apps/api/services/graph_erasure.py` (READ ONLY — `GRAPH_WRITE_BLOCKING_SCOPES`; **added at VALIDATE 07-08-26 2nd pass, required by the widened C2 step 4**)
- `apps/api/models/suppression.py` (READ ONLY — `SuppressionEntry.email_hash`, `scope`)
- `apps/api/migrations/versions/` (2 new migrations — **path corrected from `apps/api/alembic/versions/`, see Validate Contract**)
- `tests/unit/test_identity_coop.py` (NEW)
- `tests/integration/test_identity_coop_contribution.py` (NEW)

---

## Public Contracts

- `_save_identified` return type and existing side effects UNCHANGED; the hook is additive and best-effort.
- **`_upsert_beam_identity` return type CHANGES `None` → `bool` (PVL supplement 07-08-26, D-A).** Private method (leading underscore), exactly one production caller (`identity_resolver.py:1252`), no cross-module consumer. Callers ignoring the return are unaffected. Its write behaviour, guards, and guard ordering are UNCHANGED — only the returned value is added.
- `PATCH /api/v1/sites/{site_id}` returns **422** when `contribution_enabled=True` is submitted with a missing, malformed, or non-current `terms_version` (E4).
- Graph READ path UNCHANGED — no contribution gate added (AC-2 model (a)).
- `api_usage_logs` / `resolution_logs` write paths UNCHANGED.
- `PATCH /api/v1/sites/{site_id}` gains one additive optional boolean; setting it to `True` now requires an accompanying `terms_version`. Existing fields unchanged.
- Pixel consent banner UNCHANGED.

**VALIDATE confirms:** no unlisted consumers found for any of the above; `_save_identified`'s
early-return paths (email-dedup merge at line 1134/1144, `_log_owned_resolution` at 1175, the
conflict-upsert path returning at 1243) all occur BEFORE the hook's insertion point at line 1252, so
none of them are affected by this phase's change. **2nd-pass caveat:** `_upsert_beam_identity`'s
`-> None` signature is also unchanged as planned — which is exactly what enables the D1 FAIL, so
"unchanged" is not costless here. If the F2 fix takes shape (a), this bullet list gains a row. **PVL supplement 07-08-26: shape (a)
WAS chosen, and the row has been added above.**

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
| `test_erased_row_earns_no_credit` | Fully-Automated | SPEC A interface obligation — **RETIRED at PVL supplement 07-08-26 and replaced by `test_blocked_graph_write_accrues_nothing`: under D-B the co-op module no longer performs a suppression check of its own, so there is nothing left for this test to exercise. F6 is removed from Step F.** |
| `test_coop_failure_does_not_break_identification` | Fully-Automated | Best-effort hook contract |
| `alembic upgrade <head>:head --sql` exits 0 | Fully-Automated | Migration-currency constraint |
| Disposable-Postgres round-trip clean | Hybrid (precondition: disposable Postgres container) | Schema/migration high-risk class |
| `git diff --stat apps/api/services/identity_resolver.py` ≤ 12 lines | Fully-Automated | Collision-minimization constraint (**budget re-set from 6 → 12 at PVL supplement 07-08-26, D-A**) |
| `test_blocked_graph_write_accrues_nothing` (NEW) | Fully-Automated | AC-3 / AC-5 — no graph write ⇒ no credit |
| `test_bot_suspect_visitor_earns_no_credit` (NEW) | Fully-Automated | AC-9 (`is_bot_suspect` half) |
| `test_flag_on_requires_acceptance` (NEW) | Fully-Automated | AC-10 automated leg (currently orphaned) |
| `test_erased_person_leaves_no_new_bidx_row` (NEW) | Fully-Automated | Erasure completeness vs `ERASURE_TARGETS` — D-B privacy invariant |
| `test_second_day_resolve_accrues_no_second_credit` (NEW) | Fully-Automated | AC-5 / D-E accrual uniqueness (no daily credit minting) |
| `test_upsert_returns_bool_and_existing_callers_unaffected` (NEW) | Fully-Automated | D-A signature change is behaviour-preserving for existing callers |
| `uq_coop_accrued_site_email` partial unique index present after `upgrade head` | Hybrid (precondition: disposable Postgres container) | D-E enforced in the DB, not only in service code |
| 5-artifact high-risk evidence pack under `.../identity-coop_07-08-26/harness/` | Agent-Probe | billing/credits + schema/migration high-risk class (`vc-risk-evidence-pack`) |

---

## Test Infra Improvement Notes

- Docker was unavailable for this validate pass (`docker info` fails), as it was for SPEC A's
  EXECUTE. Every Hybrid gate in this program is therefore permanently deferred in this environment.
  Standing repo-wide gap, not specific to this phase.

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/visitors-identity/active/identity-coop_07-08-26/phase-1-ledger-substrate_PLAN_07-08-26.md`
- Last completed step: PVL SUPPLEMENT (07-08-26, cycle 1) — 8 gaps addressed in plan text; prior step was VALIDATE 2nd outer-PVL pass, Gate: BLOCKED
- Validate-contract status: written, BLOCKED (07-08-26, 2nd pass, supersedes the 1st)
- Supporting context files loaded: `process/context/all-context.md`, `process/context/tests/all-tests.md`, `identity-coop_SPEC_07-08-26.md`, umbrella plan, `phase-blast-radius-registry.md`, `graph-erasure-compliance_07-08-26` plan + REPORT + results.tsv, `identity-vocab-reconcile_07-08-26` plan
- Next step (PVL supplement 07-08-26): **track (1) is now DONE** — F2, F3, C1, C2, C3, C5, C6, C8 are
  settled in plan text (§PLAN Decisions D-A…D-E). Phase 1 is **Dependency-BLOCKED** on F1 alone.
  Dependency + re-entry conditions are recorded in
  `process/features/visitors-identity/backlog/identity-coop-entry-gate-spec-a-live_NOTE_07-08-26.md`.
  Do NOT spawn vc-execute-agent. The 5-artifact high-risk evidence pack under
  `.../identity-coop_07-08-26/harness/` is still required before EXECUTE. Original two tracks: **(1)** F2 and F3 are
  plan-fixable now — a PVL supplement cycle can clear both without waiting on anything external.
  **(2)** F1 needs SPEC A `graph-erasure-compliance_07-08-26` to reach EVL GREEN (Docker up, 14
  integration gates + migration live round-trip run) and ship, OR the umbrella to explicitly
  redefine "LIVE" with user acceptance recorded. When re-running PVL, re-derive `alembic heads` LIVE
  again and re-check `identity_resolver.py` drift — both moved between the 1st and 2nd passes.

---

## Validate Contract

Status: BLOCKED
Date: 07-08-26
date: 2026-08-07
generated-by: outer-pvl
supersedes: 2026-08-07 (outer-pvl) — re-validated against the live working tree after SPEC A's EXECUTE landed and 4 new migrations appeared. This contract CORRECTS two factual errors in the prior one (see "Corrections to the prior contract" below) and adds two findings the prior cycle could not see because the code it depends on did not exist yet.

Parallel strategy: sequential (single-context pass)
Rationale: 7-signal score **4/7** — S2 (schema/migration + billing/credits surface), S4 (phase-program
membership), S6 (high-risk class named in the plan), S7 (11-file blast radius). Score 4 → HIGH →
workflow or agent-team would be the from-scratch recommendation. This agent has no Agent tool grant
this session, so Layer 1 (4 dimensions) and Layer 2 (8 sections) ran as ONE sequential pass, not a
true parallel fan-out. Disclosed per this task's fan-out-disclosure constraint.

### Corrections to the prior contract (both were wrong; both are now settled with live evidence)

1. **"FIVE alembic heads" was FALSE.** The prior cycle could not run `alembic` (it reported a
   sandbox block on `.venv`) and hand-parsed the revision headers instead, concluding 5 heads. This
   session ran the real command: `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` →
   **`d1a6c4e93f27` (head)`** — exactly ONE head. Chain tail confirmed via `history -r-6:head`:
   `f1a7c3e05b92 → a4f2b8c15d70 → b8e3f6a2c904 → c9f4a7b31e85 → d1a6c4e93f27`. Historical
   branchpoints exist (`b7e1a2c9d4f0`, `f1a9c4d7e2b8`) but the DAG converges. **Entry Gate item 4
   is MET; checklist A1's STOP-and-re-chain condition will NOT fire.** Neither `e6b2d4a1c837` (cited
   by the umbrella) nor `c9f4a7b31e85` (cited by this task's prompt and by SPEC A's report) is the
   head any more — `d1a6c4e93f27` chained onto `c9f4a7b31e85` when SPEC A's migration landed. A1
   must still re-derive live at EXECUTE time; the head moves on roughly a daily cadence in this repo.
2. **`.venv` is NOT blocked this session.** `alembic 1.13.3` imports and runs. Every finding below
   is from a live command or a direct file read, not from inference.
3. **Prior FAIL "migration directory path" is RESOLVED in the plan body** (Blast Radius,
   Touchpoints, A4, A5 all now say `apps/api/migrations/versions/`; confirmed correct against
   `apps/api/alembic.ini` `script_location = %(here)s/migrations` and 64 revision files present).
   The sibling `phase-blast-radius-registry.md` line 22 **still says `apps/api/alembic/versions/`** —
   outside this agent's write scope, carried forward as CONCERN C4.

### Net Gate Derivation

**Layer 1 dimensions**

| Layer 1 dimensions | Status |
|---|---|
| Infra fit | CONCERN |
| Test coverage | CONCERN |
| Breaking changes | PASS |
| Security surface | FAIL |

**Layer 2 sections**

| Layer 2 sections | Status |
|---|---|
| Entry Gate / dependency status | FAIL |
| Section A — Models and migrations | PASS |
| Section B — Config | PASS |
| Section C — Service module | FAIL |
| Section D — The hook | CONCERN |
| Section E — 7-layer flag wiring | CONCERN |
| Section F — Tests | CONCERN |
| Section G — Migration round-trip | PASS (environmental Known-Gap — Docker confirmed DOWN this session; already correctly downgraded to CONDITIONAL by the plan's own Phase Completion Rules) |

**Totals: 3 FAILs / 5 CONCERNs / 4 PASSes**

**→ Net Gate: BLOCKED**

Net-gate vacuous-green check: not applicable to a terminal PASS here, but recorded — no developed
behavior in this phase rests on Known-Gap alone. The only Known-Gap (Docker round-trip) covers a
behavior that also has a Fully-Automated offline `--sql` gate.

### The FAILs, by kind and resolution path

**F1 — Entry Gate unmet: SPEC A completed EXECUTE but is NOT LIVE. (External blocker. NOT
plan-fixable.)**
State advanced materially since the prior cycle — SPEC A `graph-erasure-compliance_07-08-26` is no
longer "planned": its EXECUTE report exists (`graph-erasure-compliance_REPORT_07-08-26.md`,
`status: COMPLETE_WITH_GAPS`, all 30 checklist items applied, 1165/1165 unit tests green,
`d1a6c4e93f27` migration landed, `graph_erasure.py` / `erasure_request.py` / the
`_upsert_beam_identity` write boundary all present on disk and verified by direct read this cycle).
So the FIRST half of the Entry Gate ("has completed EXECUTE") is now **MET**.
The SECOND half ("and is LIVE (not merely planned)") is **UNMET**, on the report's own words:
- The report states the phase is `CODE DONE`, **not** `EVL GREEN` — verbatim, at its own line 181.
- 14 integration gates (T-I1…T-I10) are **written but never executed** — Docker down. Independently
  re-confirmed this cycle: `docker info` fails.
- The migration live round-trip is **deferred, not passed** (offline `--sql` only).
- Nothing is deployed. Branch is `devjulley`, unpushed. `graph_erasure_sweep_enabled` (default
  `True`, a stated deviation) has never run in any real environment.
The umbrella states the bar as "LIVE (not merely planned)" in 8 separate places (lines 26-27, 94,
112-113, 150, 177-184, 258, 264, 485). The program's own stated rationale for that bar — paying
credit before erasure works is a *worse* legal position than today's status quo — is about erasure
**functioning**, not existing as unverified code. No PVL supplement cycle can clear this.
**This is the dominant reason for BLOCKED.**

**F2 — Credit accrues even when NO graph write happened. (Correctness defect. Plan-fixable, but the
fix breaks the plan's own ≤6-line footprint claim — see D-tension below.)**
This finding did not exist last cycle: it is created by SPEC A's write-boundary guard, which landed
between the two cycles.
- SPEC AC-3: *"Every graph write attributable to an opted-in site is counted against that site."*
  SPEC line 63: *"every **new graph write** it produces is counted as a contribution."* A
  contribution IS a graph write. That is the SPEC's definition.
- The plan's hook (D1) fires **immediately after** `await self._upsert_beam_identity(visitor, data,
  provider)` (verified at `identity_resolver.py:1252`).
- `_upsert_beam_identity` returns **`None`** (`-> None`, verified at line 1264-1266) and **silently
  returns early in three distinct cases** before writing anything:
  1. `if not fp or not email: return` (line 1270-1271) — no fingerprint ⇒ no graph row;
  2. `if getattr(visitor, "do_not_resolve", False)` ⇒ `graph_write_blocked`, return (line 1279-1285)
     — a GPC/DNT visitor;
  3. `await is_email_suppressed_any(self.db, email, GRAPH_WRITE_BLOCKING_SCOPES)` ⇒ same return —
     an erased or `do_not_process` person.
- Because the return type carries no signal, **the caller cannot tell whether a row was written.**
  The hook therefore records a contribution event and accrues a credit for a resolve that
  contributed nothing. Directly violates AC-3 and AC-5.
- The plan's C2 step 4 only *partially* compensates, and does so by **duplicating** the gate inside
  `identity_coop.py` — two independent implementations of one rule, free to drift. See C1 for how
  they already diverge.
Resolution shapes (a PLAN decision, not this agent's to make): (a) change
`_upsert_beam_identity` to return `bool` and gate the hook on it — cleanest, honours the SPEC
definition exactly, but adds a return-type change + call-site change inside the contested file;
(b) move the hook INSIDE `_upsert_beam_identity` after the successful insert — smallest truthful
footprint, but relocates the "call-graph position" the whole plan and registry describe;
(c) re-derive all three no-op conditions inside `identity_coop.py` — no resolver change, but
triples the drift surface and is the option that produced C1.

**F3 — Security surface: an erased person gets a NEW `email_bidx`-keyed row that erasure cannot
reach. (Privacy regression against the program that just shipped. Plan-fixable.)**
- `ERASURE_TARGETS = ("beam_identity_graph",)` — verified at `apps/api/models/erasure_request.py:31`.
  The co-op's new `identity_contribution_events` table is **not** an erasure target, and Phase 1
  does not add it.
- The plan's C2 step 4 **deliberately writes the event row anyway** for an erased person, setting
  `excluded_reason='erased'` and skipping only the *accrual*. So a person who exercised GDPR
  erasure gets a brand-new blind-index-keyed row created **after** their erasure completed, in a
  table SPEC A's sweep will never touch. The erasure becomes provably incomplete for anyone who
  revisits any opted-in site.
- Blind-indexed is not out of scope: `email_bidx` is exactly the key SPEC A tombstones and sweeps
  on, and `SuppressionEntry.email_hash` is the same `pii_crypto.email_hash()` output (verified
  `suppression.py:43`, `identity_resolver.py:1299`). If `email_bidx` were not identifying, the
  erasure program would not need to delete it.
Required fix shape: either (a) do not write the event at all when the graph write was blocked (the
natural consequence of fixing F2), or (b) add `identity_contribution_events` to `ERASURE_TARGETS`
and to the sweep's delete set — which is a change to SPEC A's mechanics and therefore, per the
umbrella's own line 94, **out of this program's scope** and needs SPEC A to own it.

### Dimension findings

- **Infra fit: CONCERN** — migration directory now correct in the plan body and confirmed against
  `alembic.ini`; live `alembic heads` returns a single head `d1a6c4e93f27` so Section A is
  mechanically clean. Residual: `phase-blast-radius-registry.md:22` still cites the non-existent
  `apps/api/alembic/versions/` (C4), and every head value written into any of these four documents
  is already stale — A1's live re-derivation is the only trustworthy source.
- **Test coverage: CONCERN** — the 8 planned tests are correctly tiered Fully-Automated against
  model shapes verified this cycle (`Visitor.is_abuse_flagged` at `visitor.py:97`,
  `Visitor.is_bot_suspect` at `visitor.py:105`, `SuppressionEntry.email_hash` at
  `suppression.py:37`, `pii_crypto.email_hash` at line 66, `OWNED_FREE_PROVIDERS` at
  `identity_classification.py:74`). But the suite has **three holes that would let F2, F3, C1 and
  C3 ship EVL-green**: (i) no test drives a resolve where `_upsert_beam_identity` no-ops
  (`do_not_resolve=True`, missing fingerprint, `do_not_process`/`all` tombstone) and asserts zero
  accrual; (ii) no test at all for E2's acceptance-guarded flag flip — AC-10 appears nowhere in
  Phase 1's Acceptance Criteria list or Verification Evidence table (C5); (iii) `is_bot_suspect` is
  never exercised though SPEC AC-9 names it (C3). Hybrid round-trip is a legitimate environmental
  Known-Gap (Docker confirmed down).
- **Breaking changes: PASS** — Public Contracts section is accurate and re-verified. `_save_identified`'s
  early-return paths (email-dedup merge at line 1134/1144, `_log_owned_resolution` at 1175, the
  conflict-upsert path returning at 1243) all occur BEFORE the hook anchor at 1252, so none are
  affected. `_upsert_beam_identity`'s signature is unchanged by this phase as planned — noting that
  this is precisely what enables F2, so keeping it unchanged is not costless. `PATCH
  /api/v1/sites/{site_id}` addition is additive and the existing single `await db.commit()` at
  `routers/sites.py:341` makes E2's same-transaction requirement naturally satisfiable.
- **Security surface: FAIL** — see F3. Secondary findings, all real but individually non-blocking:
  the blind-index-only PII discipline is otherwise correct (C2 step 4's `email_hash` column-name
  correction from last cycle is verified right, and the plan correctly refuses to call
  `is_email_suppressed()` because it takes plaintext); the best-effort try/except (C4 in the
  checklist) with keys-only logging is correct; multi-tenancy is preserved because `update_site`
  already routes through `verify_site_access(db, site_id, user)` (`routers/sites.py:324`) which is
  the 404-not-403 helper — though E3 does not name it (C7). **High-risk class confirmed:
  billing/credits + schema/migration. Per `vc-risk-evidence-pack`, EXECUTE on this phase requires
  the manual-first 5-artifact evidence pack in the task folder's `harness/` subdir before the work
  may be called ready; it does not exist yet.**

### Section-level detail (Layer 2)

- **Section A — PASS.** Mechanical feasibility clean: `apps/api/models/identity_coop.py`,
  `apps/api/services/identity_coop.py`, `apps/api/routers/identity_coop.py` all absent (verified
  `ls` → No such file). No `contribution_enabled` anywhere in `models/site.py`, `schemas/sites.py`,
  `routers/sites.py`. No `identity_coop_*` / `coop_credit_*` in `config.py`. Single alembic head.
  Migration dir correct. Nothing to collide with.
- **Section B — PASS.** Four settings, all default OFF/inert, follows the
  `agent_detection_enabled` / `company_graph_enabled` / `identity_signals_enabled` precedent.
- **Section C — FAIL.** See F2 + F3, plus C1 and C3.
- **Section D — CONCERN.** The anchor is exact and unambiguous: `_upsert_beam_identity(visitor,
  data, provider)` at line 1252, with the best-effort hot-alert block at 1254-1260 immediately
  after; inserting between them is exactly the described position. No collision with SPEC A's
  change (which lives INSIDE `_upsert_beam_identity` at 1272-1285) nor with the vocab-reconcile
  work. Local-import precedent is real (lines 129, 164, 203-204, 224, 309, 692, 1090, 1256, 1276-77,
  1291, 1343, 1424). D2's fallback is the correct expectation: the resolver caches no `Site` ORM
  instance — the only `Site` touch in the file is `select(Site.url)` at line 149.
  **The concern is the D4 tension:** D4 caps the resolver diff at ≤6 lines, but the F2 fix most
  faithful to the SPEC (return `bool` from `_upsert_beam_identity` and branch on it) necessarily
  changes that function's signature, its `-> None` annotation, and at least one `return` statement
  inside it. Either D4's budget or the SPEC's definition of a contribution has to give. That is a
  PLAN decision this contract cannot make.
- **Section E — CONCERN.** Mechanically feasible (`SiteUpdate` at `schemas/sites.py:45`, `SiteOut`
  at line 16, `auto_identify_enabled` precedent at lines 26/57, single commit at `routers/sites.py:341`).
  Two gaps: C5 (the guard has no proving gate in this phase and `terms_version` has no validator
  until Phase 3's `coop_terms.py`, so a client sending `terms_version="x"` satisfies it — a vacuous
  guard against a field the data model calls an "immutable snapshot hash of the exact policy text")
  and C7 (`verify_site_access` not named).
- **Section F — CONCERN.** See Test coverage above.
- **Section G — PASS with Known-Gap.** Docker independently confirmed down. The plan's own Phase
  Completion Rules already forbid promoting to ✅ VERIFIED on offline `--sql` alone. Correct as written.

### Open gaps

- **F1 — Entry Gate unmet (SPEC A not LIVE)** — hard external blocker. NOT a known-gap; EXECUTE
  cannot start. Clears when SPEC A reaches EVL GREEN (its 14 integration gates + migration
  round-trip run with Docker up) **and** ships, OR when the umbrella explicitly redefines "LIVE"
  and the user accepts that redefinition here.
- **F2 — accrual not conditioned on the graph write** — plan-fixable; requires a PLAN decision
  between the three resolution shapes above, one of which conflicts with D4's ≤6-line budget.
- **F3 — `identity_contribution_events` outside `ERASURE_TARGETS`** — plan-fixable if resolved as
  "never write the event when the graph write was blocked"; otherwise it becomes a SPEC A scope
  change, which the umbrella forbids this program from making.
- **C1 — suppression scope set too narrow.** Verified: `GRAPH_WRITE_BLOCKING_SCOPES = ("erased",
  "do_not_process")` (`graph_erasure.py:78`) and `is_email_suppressed_any` also matches `"all"`
  (`suppression.py:44`). So the resolver blocks graph writes on **three** scopes; the plan's C2
  step 4 checks only `scope == "erased"`. A `do_not_process` or `all` tombstone therefore blocks the
  graph write while still accruing credit. Widen C2 step 4 to reuse
  `GRAPH_WRITE_BLOCKING_SCOPES` (import the constant, do not re-list the strings).
- **C2 — duplicated gate.** C2 step 4 re-implements the resolver's write boundary inside
  `identity_coop.py`. Even once widened, it is a second copy of a privacy rule that SPEC A owns.
  Prefer a design where the co-op reads the outcome instead of re-deriving the condition.
- **C3 — fraud gate narrower than SPEC AC-9.** AC-9 names "`is_abuse_flagged` / `is_bot_suspect`
  (or equivalent)" and references `referral_activation.py`'s gate shape. `record_contribution`'s
  signature takes only `is_abuse_flagged`; `Visitor.is_bot_suspect` exists (`visitor.py:105`) and is
  never consulted. F5 tests only the abuse flag.
- **C4 — registry migration path** — `phase-blast-radius-registry.md:22` still says
  `apps/api/alembic/versions/` (also wrong in Phase 2's entry at line 43). Out of this agent's
  write scope. Orchestrator / registry owner to correct.
- **C5 — AC-10 orphaned across the phase boundary.** Phase 1's E2 builds AC-10's automated leg, but
  AC-10 appears in neither Phase 1's Acceptance Criteria list nor its Verification Evidence table
  (the umbrella's Coverage Map assigns AC-10 to Phase 3). Phase 1 EVL can therefore go green having
  never exercised the guard it built, and the terms module that gives `terms_version` meaning does
  not exist until Phase 3.
- **C6 — ledger scope vs the only enforcement gate.** `identity_credit_ledger` is `site_id`-scoped
  (this phase's decision, and the registry declares the schema **frozen after Phase 1**). The only
  monthly enforcement point is `billing.check_usage_allowed(db, user_id)` keyed on
  `User.monthly_identified_count` (`services/billing.py:94-128`) — `user_id`-scoped. The only
  per-site gate is the daily resolution budget, which Phase 2 is explicitly forbidden from touching.
  Phase 2's AC-6 ("credits are spendable") inherits an unresolvable scope mismatch from a schema
  Phase 1 freezes. Decide the reconciliation HERE, while the schema is still open.
- **C7 — `verify_site_access` not named in E3.** Minor citation gap; the check E3 asks for already
  exists via that helper (`routers/sites.py:324`).
- **C8 — daily re-accrual on an already-owned identity.** The unique key is `(site_id, email_bidx,
  contributed_on)` — per DAY. `_upsert_beam_identity` uses `on_conflict_do_update`, so a repeat
  resolve of a person the graph already holds is an UPDATE, not a new row, yet it mints a fresh
  credit every calendar day forever. SPEC line 63 says "every **new** graph write"; the plan counts
  every write. Whether that is intended is a locked-decision question, not a defect this contract
  adjudicates — but it should be answered before the schema freezes.
- **Docker round-trip (Known-Gap, environmental)** — `docker info` fails this session, same as SPEC
  A's EXECUTE. Carried as gap-resolution D; backlog stub required at EXECUTE/EVL if still down.
- **High-risk evidence pack absent (Known-Gap, procedural)** — billing/credits + schema/migration
  are two of the six high-risk classes. The 5-artifact pack (`risk-gate.json`,
  `context-snippets.json`, `verification.json`, `review-decision.json`,
  `adversarial-validation.json`) must exist under
  `process/features/visitors-identity/active/identity-coop_07-08-26/harness/` before this phase's
  work may be called ready. It does not exist. Manual-first by design; not a blocking hook.

### Test gates (C3 5-column table — ADDITIVE)

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 | flag OFF ⇒ zero counted contributions | Fully-Automated | `tests/integration/test_identity_coop_contribution.py::test_flag_off_produces_zero_contributions` | B |
| AC-2 | non-contributor still gets graph-served matches | Fully-Automated | `tests/integration/test_identity_coop_contribution.py::test_non_contributor_still_receives_graph_matches` | B |
| AC-3 | merge-aware contribution counting | Fully-Automated | `tests/unit/test_identity_coop.py::test_merged_duplicate_counts_once` | B |
| AC-3 / AC-5 (F2) | a resolve where the graph write NO-OPS accrues zero credit — one case per no-op path: missing fingerprint, `do_not_resolve=True`, `do_not_process` tombstone, `all` tombstone | Fully-Automated | `tests/unit/test_identity_coop.py::test_blocked_graph_write_accrues_nothing` (NEW — does not exist in the plan; must be added by the F2 fix) | B |
| AC-5 | qualifying contribution ⇒ one ACCRUE row | Fully-Automated | `tests/integration/test_identity_coop_contribution.py::test_qualifying_contribution_writes_ledger_row` | B |
| AC-9 | abuse-flagged traffic ⇒ zero accrual | Fully-Automated | `tests/integration/test_identity_coop_contribution.py::test_abuse_flagged_visitor_earns_no_credit` | B |
| AC-9 (C3) | `is_bot_suspect=True` traffic ⇒ zero accrual | Fully-Automated | `tests/unit/test_identity_coop.py::test_bot_suspect_visitor_earns_no_credit` (NEW — must be added) | B |
| SPEC A interface (C1) | erased **and** `do_not_process` **and** `all` tombstones each ⇒ zero accrual, using `GRAPH_WRITE_BLOCKING_SCOPES` not a re-listed literal | Fully-Automated | `tests/unit/test_identity_coop.py::test_erased_row_earns_no_credit` (EXISTS, must be widened to all three scopes) | B |
| AC-12 | grandfathered rows contribute 0 | Fully-Automated | `tests/unit/test_identity_coop.py::test_grandfathered_rows_contribute_zero` | B |
| best-effort hook contract | co-op failure never breaks identification | Fully-Automated | `tests/unit/test_identity_coop.py::test_coop_failure_does_not_break_identification` | B |
| AC-10 automated leg (C5) | `contribution_enabled=True` via API is rejected without a `terms_version`, and accepted only with an acceptance row written in the SAME transaction | Fully-Automated | `tests/integration/test_identity_coop_contribution.py::test_flag_on_requires_acceptance` (NEW — E2 currently has no proving gate in this phase) | B |
| F3 — erasure completeness | after an erasure completes, a subsequent resolve of that person creates NO new `email_bidx`-keyed row in `identity_contribution_events` | Fully-Automated | `tests/unit/test_identity_coop.py::test_erased_person_leaves_no_new_bidx_row` (NEW) | B |
| migration currency | offline `--sql` validation clean, explicit range | Fully-Automated | `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade <head_from_A1>:head --sql` | B |
| schema/migration high-risk class | live round-trip on disposable Postgres | Hybrid (precondition: disposable Postgres container) | `upgrade head → downgrade -1 → downgrade -1 → upgrade head` | D — `docker info` fails this session; backlog stub required at EXECUTE/EVL if still down |
| collision-minimization | `identity_resolver.py` diff ≤ 6 lines | Fully-Automated | `git diff --stat apps/api/services/identity_resolver.py` | B — **note the D4 tension: the F2 fix may legitimately exceed this budget; re-set the number as part of the F2 decision rather than letting the guard force the wrong fix** |
| Entry Gate (F1) | SPEC A EVL GREEN + LIVE, and vocab-reconcile cleared, before EXECUTE | Agent-Probe (status re-derivation from sibling plan + report files, plus `docker info`) | manual status re-check of both dependency plans at the start of every future PVL/EXECUTE attempt | C — deferred until SPEC A's Hybrid tier runs and ships |
| high-risk evidence pack | 5-artifact manual-first pack exists and records an explicit APPROVE/REJECT | Agent-Probe | `.claude/skills/vc-risk-evidence-pack/scripts/validate-risk-artifacts.mjs` against `.../identity-coop_07-08-26/harness/` | C — due at EXECUTE, before the phase may be called ready |

gap-resolution legend: A — proven now; B — fixed in this plan (gate added by this plan's checklist,
not yet run); C — deferred to a named later phase/plan; D — backlog test-building stub (named
residual; keep-active; continue).

C-4 reconciliation: every row uses only the 3 proving strategies (Fully-Automated / Hybrid /
Agent-Probe). Known-Gap is never a `strategy:` value here — the Docker-gated round-trip is Hybrid
with an explicit precondition, carried as residual D.

Legacy line form (retained so existing validate-contract consumers still parse):
- Tests F1-F8 plus the 5 NEW gates above: Fully-Automated (commands as named)
- Migration offline `--sql` + `git diff --stat` guard: Fully-Automated
- Disposable-Postgres round-trip: Hybrid, precondition: disposable Postgres container running
- Entry Gate dependency re-check: Agent-Probe, description: re-derive both upstream plans' status
  and `docker info` before every future PVL/EXECUTE attempt on this phase
- High-risk evidence pack: Agent-Probe, description: 5-artifact pack present with explicit reviewer decision

**Failing stub — AC-1:**
```
test("should assert flag OFF produces zero contribution events and zero ledger rows across a full resolve cycle", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_flag_off_produces_zero_contributions")
})
```

**Failing stub — AC-2:**
```
test("should assert a non-contributing site still receives graph-served identifications", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_non_contributor_still_receives_graph_matches")
})
```

**Failing stub — AC-3:**
```
test("should assert two resolves of the same email under two visitor_ids on the same day produce exactly one contribution event", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_merged_duplicate_counts_once")
})
```

**Failing stub — AC-3 / AC-5 (F2, NEW):**
```
test("should assert a resolve where the graph write no-ops accrues zero credit, one case per no-op path", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_blocked_graph_write_accrues_nothing")
})
```

**Failing stub — AC-5:**
```
test("should assert one qualifying contribution writes exactly one positive ACCRUE ledger row", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_qualifying_contribution_writes_ledger_row")
})
```

**Failing stub — AC-9:**
```
test("should assert abuse-flagged traffic produces a contribution event with zero ledger accrual", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_abuse_flagged_visitor_earns_no_credit")
})
```

**Failing stub — AC-9 (C3, NEW):**
```
test("should assert is_bot_suspect traffic earns no credit", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_bot_suspect_visitor_earns_no_credit")
})
```

**Failing stub — SPEC A interface (C1, widened):**
```
test("should assert erased and do_not_process and all tombstones each yield zero accrual via GRAPH_WRITE_BLOCKING_SCOPES", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_erased_row_earns_no_credit")
})
```

**Failing stub — AC-12:**
```
test("should assert grandfathered pre-program graph rows contribute zero to any site's ledger", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_grandfathered_rows_contribute_zero")
})
```

**Failing stub — best-effort hook contract:**
```
test("should assert a forced record_contribution failure never breaks _save_identified's return", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_coop_failure_does_not_break_identification")
})
```

**Failing stub — AC-10 automated leg (C5, NEW):**
```
test("should assert contribution_enabled cannot be set true without a terms_version and writes the acceptance row in the same transaction", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_flag_on_requires_acceptance")
})
```

**Failing stub — F3 erasure completeness (NEW):**
```
test("should assert an erased person's later resolve creates no new email_bidx row in identity_contribution_events", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_erased_person_leaves_no_new_bidx_row")
})
```

(Hybrid and Agent-Probe rows do not receive stubs, per policy.)

### What this coverage does NOT prove

- **No code was executed against this phase's behavior.** Zero of the 8 planned tests (or the 5 new
  ones named above) exist on disk. This cycle proved only: mechanical feasibility (anchors resolve,
  no file collisions), factual correctness of the plan's field/path/head claims against the live
  working tree, and semantic consistency against the SPEC. It did not run a single co-op code path.
- **The Hybrid tier proves nothing this cycle.** `docker info` fails; the disposable-Postgres
  round-trip has never run for this phase.
- **`alembic heads` is a snapshot, not a guarantee.** `d1a6c4e93f27` was the single head at the
  moment this command ran. Four migrations appeared in this repo in the last day and the head has
  moved at least twice during this program's lifetime. A1's live re-derivation at EXECUTE time is
  the only trustworthy value; treat every head string in these four documents as expired.
- **Nothing here proves SPEC A's erasure actually works.** This cycle confirmed the *interface*
  exists and is queryable (`SuppressionEntry.email_hash`, `GRAPH_WRITE_BLOCKING_SCOPES`,
  `ERASURE_TARGETS`, the write-boundary guard at `identity_resolver.py:1272-1285`) by direct read.
  Whether the sweep drains correctly, whether the transaction boundaries hold under a real
  Postgres, and whether the queue recovers from a mid-row crash are all SPEC A's own unrun
  integration gates — the exact gates that make F1 a blocker.
- **F2's resolution is not chosen.** Three shapes are named; each has a cost; none is validated.
  Whichever is picked needs its own re-validation, because option (a) changes a function signature
  inside a file three programs contest.
- **C6 is diagnosed, not solved.** This contract shows the `site_id`-vs-`user_id` mismatch exists
  and that Phase 1 is where the schema freezes. It does not prescribe the reconciliation, and no
  test in any phase currently covers it.
- **C8's intent is unadjudicated.** Whether daily re-accrual on an already-owned identity is a
  feature or a leak is a product decision. This contract only establishes that the plan as written
  produces it.
- **The "LIVE" judgment is a reading, not an adjudication.** F1 rests on interpreting "LIVE (not
  merely planned)" as excluding "code-complete with an unrun Hybrid tier and nothing deployed". The
  umbrella's 8 restatements and the program's own legal rationale support that reading. A user is
  entitled to overrule it — explicitly, in writing, in the `Accepted by:` field below.

Gate: BLOCKED

Accepted by: PENDING — no FAIL or CONCERN in this contract has been accepted by the user or by this
session. Per this task's enumerated STOP-BLOCK (item 4), this validate-agent does not self-accept
its own findings, and it did not write `results.tsv`. The orchestrator or user must choose one of:
(a) wait for SPEC A `graph-erasure-compliance_07-08-26` to reach EVL GREEN (Docker up, 14
integration gates + migration round-trip run) and ship, then re-run PVL from V1; (b) explicitly
redefine the umbrella's "LIVE" bar and record that redefinition plus its acceptance here; or (c)
descope Phase 1. Note that F2 and F3 are independent of F1 and are plan-fixable NOW — a PVL
supplement cycle can resolve both while F1 remains open, which would leave a single external
blocker instead of three.
