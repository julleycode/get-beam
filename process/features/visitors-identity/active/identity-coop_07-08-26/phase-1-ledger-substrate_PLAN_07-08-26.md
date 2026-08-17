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
Phase status: ⏳ PLANNED — entry gate CLEARED 07-08-26, ready for EXECUTE
Status: ⏳ PLANNED — entry gate CLEARED 07-08-26, ready for EXECUTE
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

**SUPERSEDED — the 2nd outer-PVL pass's re-derivation of this gate (which concluded "Entry Gate is
still UNMET") is retracted by the 3rd outer-PVL pass (07-08-26). Authoritative re-derivation:**

- **Entry Gate: CLEARED 07-08-26.** All four conditions verified by the 3rd pass, three of them by
  independent live command:
  1. `identity-vocab-reconcile_07-08-26` — `Gate: CONDITIONAL`, explicitly user-accepted at
     supplement cycle 9, EXECUTED and merged. Satisfies the gate's *intent* (the
     `identity_resolver.py` churn has settled and shipped). Carried as concern **N-VOCAB**, a
     wording gap, not a state gap.
  2. SPEC A `graph-erasure-compliance_07-08-26` — **LIVE.** `tests/integration/test_graph_erasure_flow.py`
     collects exactly 14 tests and its repair commit `81eb4e6` records `14/14` with the integration
     lane moving `478P/23F/17E → 518P/0F/0E` (test-side repairs only, no production behaviour
     altered). Migration `d1a6c4e93f27` round-tripped on a disposable `postgres:16-alpine`.
     Pushed AND deployed: `git branch -r --contains 443ad5e` → `origin/main` and `origin/devjulley`;
     `git rev-list --left-right --count` → 0/0 on both; prod `alembic_version = d1a6c4e93f27`.
  3. Call-graph drift re-check — **anchors unmoved.** Call site
     `await self._upsert_beam_identity(visitor, data, provider)` at line 1252, definition at 1264.
  4. `alembic heads` — live run returns **`d1a6c4e93f27`, exactly ONE head**. A1's
     STOP-and-re-chain condition will not fire. (The 1st pass's "five heads" claim was a hand-parse
     artifact and is retracted.) Still re-derive live at EXECUTE — this repo's head moves on a
     roughly daily cadence.

- **Docker Known-Gap: CLEARED.** `docker info` → server 29.4.2, up. Every Hybrid gate in this phase
  is RUNNABLE and REQUIRED at EXECUTE; none is a deferred residual.

**EXECUTE is authorized for this phase.** See Validate Contract (3rd outer-PVL pass, `Gate:
CONDITIONAL`, doc-sync concerns only, zero behavioural FAILs).

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
`-> bool`: `True` only when the upsert statement actually executed, `False` on every no-op path.
**Corrected at PVL supplement cycle 2 (N3, verified live):** the function has **two** early-return
statements covering **three** conditions — `return` at line 1271 (`if not fp or not email`) and at
line 1285 (the single combined `if getattr(visitor, "do_not_resolve", False) or await
is_email_suppressed_any(...)`) — **plus** an `except` path that currently has NO explicit return
(it falls through to an implicit `None`). There is no third early-return statement; do not hunt for
one. The complete edit set is therefore 4 return-value edits (`return False` at 1271, `return False`
at 1285, `return False` in the `except` path, `return True` immediately after
`await self.db.commit()`) plus the signature and the docstring — 6 touched lines, inside the ≤ 12
budget. The hook is gated on that return value.

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
"`is_abuse_flagged` / `is_bot_suspect` (or equivalent)". Both columns exist on `Visitor`:
`Visitor.is_abuse_flagged` at `models/visitor.py:97` and `Visitor.is_bot_suspect` at
`models/visitor.py:105` (verified live; **citation corrected at PVL supplement cycle 2 (N4) — the
earlier `:207` reference belonged to `IdentifiedVisitor`, a different class**). `excluded_reason` vocabulary becomes
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
coop_terms_version: str = "<64-char lowercase hex digest of the current policy text>"
```

**Five settings, not four** (added at PVL supplement cycle 2 — N2). `coop_terms_version` is
REQUIRED by E4: `routers/sites.py` rejects `422` unless the submitted `terms_version` equals
`settings.coop_terms_version`. It is a pinned version hash (the hex digest of the exact policy
text), not a free-form label. Without it, E4's constant compare references a nonexistent setting.

Follows the `agent_detection_enabled` / `company_graph_enabled` / `identity_signals_enabled`
operator-gated precedent exactly. Flipping any of these ON in a real environment is a separate,
explicit, later operator action — never part of this phase.

**VALIDATE confirms no collision:** none of these five settings, `Site.contribution_enabled`, or
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

- [ ] B1. Add the five settings above to `apps/api/config.py` under a `## ─── Identity co-op (Phase 1) ───` block, with an inline comment stating the required rollout order: erasure LIVE → flag ON per-site → never before legal review.
- [ ] B2. Assert in a unit test that all **five** defaults are OFF/inert and that `identity_coop_enabled is False` (five, not four — `coop_terms_version` was added at PVL supplement cycle 2, N2).

### Step C — Service module (all logic lives here)

- [ ] C1. Create `apps/api/services/identity_coop.py`. It MUST NOT import `identity_resolver` at module level (no circular import); it takes a plain `AsyncSession`, `Site`/`Visitor`, and the resolved data — no shared state.
- [ ] C2. Implement `async def record_contribution(db, *, site_id, email_bidx, source_provider, is_abuse_flagged, is_bot_suspect, contributed_on) -> None`:
      1. Insert the contribution event with `ON CONFLICT (site_id, email_bidx, contributed_on) DO NOTHING` (merge-awareness, AC-3).
      2. If the insert was a no-op (duplicate), return — no accrual.
      3. If `is_abuse_flagged` **or `is_bot_suspect`** is True: set `accrued=False`, `excluded_reason='fraud_flagged'`, return without accrual (AC-9 — the EVENT is still recorded; only ACCRUAL is gated). **Widened at PVL supplement 07-08-26 per D-C; `Visitor.is_bot_suspect` (`models/visitor.py:105`) is now consulted.**
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
      upsert statement executed; `False` on every no-op path — **two** early-return statements plus the
      `except` path, per D5/N3, not three returns). Exactly one production
      caller exists, verified live. D4's budget is raised to ≤ 12 lines to pay for it.
- [ ] D2. Resolve `site_contribution_enabled` by loading the `Site` row's `contribution_enabled` in the same session — do NOT add a second network/DB round-trip on the hot path if the resolver already has the Site loaded; if it does not, use a single scalar select and cache on the resolver instance for the request. **VALIDATE 07-08-26 confirms: the resolver does NOT cache a `Site` ORM instance anywhere in its state (`__init__` only holds `db` and `redis_client`; the only `Site` touch in the whole file is a narrow `select(Site.url)` at one call site). The "already loaded" branch will not apply in the general case — implementers should expect the fallback (single scalar select, cached on the resolver instance for the request) to be the path actually taken. Not a defect: the plan's own fallback instruction already covers this correctly.**
- [ ] D3. Compute `email_bidx` via the existing `apps.api.services.pii_crypto.email_hash` — the same function `_upsert_beam_identity` already uses. Never pass plaintext email into the co-op module.
- [ ] D4. Verify the diff inside `identity_resolver.py` is **≤ 12 lines** total (hook + local import + the `-> bool` signature change and its three `return False` / one `return True` edits — see D5/N3 for the exact edit set). **Budget RAISED from ≤ 6 at PVL supplement 07-08-26 — rationale in §PLAN Decisions D-A; the ≤ 6 figure is superseded everywhere it appears in this document.** If it is larger than 12, the logic leaked out of `identity_coop.py` — move it back.

- [ ] D5. Apply the `-> bool` change inside `_upsert_beam_identity` itself. **Corrected at PVL supplement cycle 2 (N3):** there are **two** early-return statements covering three conditions, not three returns, and the `except` path has **no** explicit return today. The complete edit set is exactly: `return False` at the `if not fp or not email` guard (line 1271 as of 07-08-26); `return False` at the combined `do_not_resolve` / `is_email_suppressed_any(..., GRAPH_WRITE_BLOCKING_SCOPES)` guard (line 1285); `return True` immediately after `await self.db.commit()`; `return False` in the `except` path (adding the explicit return that does not exist yet); signature `-> None` → `-> bool`; docstring updated. Locate by call-graph position, not by these line numbers. Do NOT change the guards' logic or ordering — only the returned value.

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
# Expected: <= 12 changed lines
# (Budget RAISED from 6 → 12 at PVL supplement 07-08-26 per D4/D-A; D4 declares the ≤ 6 figure
#  superseded everywhere it appears in this document, and PVL supplement cycle 2 applies it here —
#  this is the block EXECUTE and EVL copy their commands from. Do NOT reshape the D-A fix to fit 6.)
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

- `identity-vocab-reconcile_07-08-26` still `Gate: BLOCKED` and not descoped. **RESOLVED 07-08-26** — `Gate: CONDITIONAL`, user-accepted, executed, merged (N-VOCAB).
- ~~SPEC A `graph-erasure-compliance_07-08-26` not LIVE~~ — **RESOLVED 07-08-26 (3rd outer-PVL pass).** SPEC A is EVL GREEN (14/14), migration round-tripped, pushed to `origin/main` + `origin/devjulley` at 0/0, and deployed (prod `alembic_version = d1a6c4e93f27`). This is no longer a blocker.
- `alembic heads` returns more than one head and re-chaining would require touching another program's migration.
- Docker unavailable ⇒ the G2 round-trip cannot run. **Not applicable as of 07-08-26 — Docker 29.4.2 is UP, so G1/G2 are REQUIRED, not deferred.** Retained only as the conditional rule should Docker later be down.
- The hook diff inside `identity_resolver.py` cannot be kept small because a concurrent workstream restructured `_save_identified`.

**SUPERSEDED.** The 2nd pass's "the second bullet is confirmed TRUE right now" note is retracted by
the 3rd outer-PVL pass (07-08-26): the entry gate is CLEARED and **no blocking condition is active**.
See the Entry Gate section above and the Validate Contract below.

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner
loop `R → I → P → PVL → E → EVL → UP` SKIPS SPEC.

- [x] 1. RESEARCH — upstream dependency status confirmed; `identity_resolver.py` drift checked; test context loaded. **Evidence: the 3rd outer-PVL contract's fresh live re-derivation (07-08-26)** — SPEC A 14/14 collect + `81eb4e6` in `origin/main`, `443ad5e` on both remotes at 0/0, `alembic heads` single (`d1a6c4e93f27`), call-graph anchors unmoved at 1252/1264, Docker 29.4.2 up. No separate research report needed; the contract IS the research record.
- [x] 2. INNOVATE — approach decided; Decision Summary written. **Satisfied by §PLAN Decisions D-A…D-E (PVL supplement cycle 1)**, each carrying a chosen shape plus explicitly rejected alternatives (D-A shapes (b)/(c) rejected; D-B option (b) rejected; D-D `user_id` column rejected). Re-verified against current source by the 3rd PVL pass.
- [x] 3. PLAN-SUPPLEMENT — plan updated at PVL supplement cycle 2 (07-08-26): P1–P8 doc-sync items from the 3rd outer-PVL contract applied (diff budget 6 → 12, fifth config setting `coop_terms_version`, D5/D-A return-set correction, D-C citation fix, `Dependency-BLOCKED` removal, Docker note, umbrella goal-block + execution state). **No `## Inner Loop Refresh Note` is written: this was a PVL-supplement pass (V7 gap list), not an inner-loop refresh — every item applied was already diagnosed by the current 3rd-pass contract, so no section changed in a way that invalidates it. V1 auto-proceeds on the existing CONDITIONAL contract; no PVL re-run is required.**
- [x] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md` — **CURRENT VERDICT: `Gate: CONDITIONAL` (07-08-26, 3rd outer-PVL pass — see `## Validate Contract`). Zero behavioural FAILs. All three prior FAILs (F1 entry gate, F2 accrual-without-write, F3 erased-person row) are CLEARED with live evidence; the five remaining concerns (N1–N5) are doc-sync items, applied at PVL supplement cycle 2. EXECUTE is authorized.** Superseded history follows for audit only: **Gate: BLOCKED (07-08-26, 2nd outer-PVL pass; supersedes the 1st). Now 3 FAILs: (F1) Entry Gate — SPEC A's EXECUTE is COMPLETE but it is `CODE DONE`, not `EVL GREEN`, and nothing is deployed, so "LIVE" is unmet; external, not plan-fixable. (F2) the hook accrues credit even when `_upsert_beam_identity` no-ops — plan-fixable NOW. (F3) an erased person gets a new `email_bidx` row outside `ERASURE_TARGETS` — plan-fixable NOW. The 1st pass's "five alembic heads" FAIL is RETRACTED: live run returns one head, `d1a6c4e93f27`. F2 and F3 are independent of F1 — a PVL supplement cycle can clear both while F1 stays open, leaving a single external blocker.**
- [ ] 5. EXECUTE — all checklist items done; per-section test gates run and green
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** If step 4 is unchecked or `## Validate Contract`
reads "(placeholder — ...)", the orchestrator must spawn vc-validate-agent first.

- [x] 3b. PVL SUPPLEMENT (07-08-26, cycle 1) — F2, F3, C1, C2, C3, C5, C6, C8 addressed in plan text via §PLAN Decisions D-A…D-E. F1 was open at that time and was NOT plan-fixable; it has since been **CLEARED** externally (SPEC A is LIVE).
- [x] 3c. PVL SUPPLEMENT (07-08-26, cycle 2) — the 3rd outer-PVL contract's P1–P8 doc-sync items applied to this plan, `phase-blast-radius-registry.md`, and the umbrella plan. No behavioural change.

**Status: ready for EXECUTE — entry gate CLEARED 07-08-26; files not yet modified.** The prior
`Dependency-BLOCKED` status and the "Do NOT spawn vc-execute-agent" instruction are **REMOVED**: both
were written when the entry gate was open, and both are now factually stale. All four entry-gate
conditions are verified (see Entry Gate above), the current validate-contract is `Gate: CONDITIONAL`
with zero behavioural FAILs, and inner-loop Steps 1–4 are complete. Next step is Step 5, EXECUTE.

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

- **Docker 29.4.2 available 07-08-26 — Hybrid gates are RUNNABLE and REQUIRED.** The earlier note
  ("Docker unavailable … every Hybrid gate in this program is therefore permanently deferred in this
  environment") is **stale and must not be cited to skip G1/G2**. Every Hybrid gate in this phase
  moves from gap-resolution D (deferred residual) to B (gate added by this plan's checklist,
  runnable at EXECUTE): the migration live round-trip AND the `uq_coop_accrued_site_email`
  partial-index presence + duplicate-`ACCRUE` `IntegrityError` assertion.
- Standing environment caveat (not a gap in this phase): Docker availability in this repo has
  oscillated across sessions. Re-check `docker info` at EXECUTE; if it is down at that moment,
  G1/G2 become a Known-Gap + backlog stub and the phase gate stays CONDITIONAL — but the default
  expectation as of 07-08-26 is that they run.

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/visitors-identity/active/identity-coop_07-08-26/phase-1-ledger-substrate_PLAN_07-08-26.md`
- Last completed step: PVL SUPPLEMENT (07-08-26, cycle 2) — P1–P8 doc-sync items from the 3rd outer-PVL contract applied to this plan, the blast-radius registry, and the umbrella plan. Inner-loop Steps 1, 2, 3 and 4 are all complete.
- Validate-contract status: written, **CONDITIONAL (07-08-26, 3rd outer-PVL pass — supersedes the 2nd pass's BLOCKED)**; zero behavioural FAILs; concerns N1–N5 accepted and now applied
- Supporting context files loaded: `process/context/all-context.md`, `process/context/tests/all-tests.md`, `identity-coop_SPEC_07-08-26.md`, umbrella plan, `phase-blast-radius-registry.md`, `graph-erasure-compliance_07-08-26` plan + REPORT + results.tsv, `identity-vocab-reconcile_07-08-26` plan
- Next step for a fresh agent: **Step 5 — EXECUTE.** The entry gate is CLEARED, the validate-contract
  is CONDITIONAL with zero behavioural FAILs, and all P1–P8 doc-sync items are applied. Start at
  Step A1 and **re-derive `alembic heads` LIVE as the very first action** — `d1a6c4e93f27` was the
  single head at the 3rd PVL pass, but this repo's head moves on a roughly daily cadence, so treat
  every head string in these documents as expired. Then honour the contract's execute-agent
  instructions E-1…E-7 verbatim: diff budget ≤ 12 (not 6); five config settings including
  `coop_terms_version`; D5's exact 4-return edit set (two existing returns + the `except` path + the
  post-commit success return) plus signature and docstring; G1/G2 REQUIRED on a DISPOSABLE Postgres
  only; `email_bidx` from `pii_crypto.email_hash` only, never plaintext.
- **Still required before this phase may be reported ready:** the 5-artifact high-risk evidence pack
  under `process/features/visitors-identity/active/identity-coop_07-08-26/harness/` (billing/credits
  + schema/migration are both high-risk classes). Validate it with
  `node .claude/skills/vc-risk-evidence-pack/scripts/validate-risk-artifacts.mjs`;
  `review-decision.json` needs an explicit APPROVE/REJECT with written rationale, and
  `adversarial-validation.json` must rule out credit-minting-without-a-graph-write and
  erased-person-row-creation. This is an EXECUTE deliverable (E-5), not a gate on starting.
- Resolved dependency note: `process/features/visitors-identity/backlog/identity-coop-entry-gate-spec-a-live_NOTE_07-08-26.md`
  is **RESOLVED** by the 3rd outer-PVL pass and should be marked as such at UPDATE PROCESS.

---

## Validate Contract

Status: CONDITIONAL
Date: 07-08-26
date: 2026-08-07
generated-by: outer-pvl
supersedes: 2026-08-07 (outer-pvl, 2nd pass, Gate: BLOCKED) — F1 (the sole remaining blocker) is
CLEARED. This 3rd outer-PVL pass re-verified the entry gate LIVE against the working tree and the
git remotes, re-verified every D-A…D-E supplement decision against current source, and re-tiered
every Hybrid gate now that Docker is available. No new behavioural FAIL was found. Five doc-sync
CONCERNs (N1–N5) replace the three prior FAILs.

Parallel strategy: sequential (single-context pass)
Rationale: 7-signal score **4/7** — S2 (schema/migration + billing/credits surface), S4
(phase-program membership), S6 (high-risk class named in the plan), S7 (11-file blast radius).
Score 4 → HIGH → workflow or agent-team is the from-scratch recommendation. Deviation stated
explicitly: this agent has no Agent tool grant this session, so Layer 1 (4 dimensions) and Layer 2
(8 sections) ran as ONE sequential pass, not a true parallel fan-out. Every finding below is from a
live command or a direct file read.

### What changed since the 2nd pass (the whole reason this pass exists)

**F1 — Entry Gate: CLEARED.** All four clearing conditions verified this pass, three of them by
independent live command rather than by trusting the record:

| Condition | Evidence gathered THIS pass |
|---|---|
| SPEC A EVL GREEN | `tests/integration/test_graph_erasure_flow.py` collects **exactly 14 tests** (live `pytest --collect-only`). Repair commit `81eb4e6` is in history and its own message records `graph_erasure_flow … → 14/14` and an integration lane moving `478P/23F/17E → 518P/0F/0E`. The 8 previously-blocked gates were repaired **test-side only** (fixtures/asserts), so no production behaviour was altered to make them pass. |
| Migration live round-trip | `d1a6c4e93f27` round-tripped on a disposable `postgres:16-alpine` (64-rev chain from empty, 17-rev down/up) — recorded in the entry-gate note. Not independently re-run this pass (would re-do a proven one-shot). |
| Pushed + deployed | **Independently verified live.** `git branch -r --contains 443ad5e` → `origin/main` AND `origin/devjulley`. `git rev-list --left-right --count` → `main` 0/0 and `devjulley` 0/0 against their remotes. The "unpushed" half of the prior FAIL is factually gone. Railway deploy success + prod `alembic_version = d1a6c4e93f27` are taken from the record (outward call, not re-made here). |
| Items re-derived LIVE | `alembic heads` → **`d1a6c4e93f27` (head)`, exactly ONE head** — unchanged since the 2nd pass, because SPEC A's own migration IS the head. `identity_resolver.py` drift re-check: **anchors unmoved** — call site `await self._upsert_beam_identity(visitor, data, provider)` at line **1252**, definition at line **1264**, exactly as the prompt predicted. The fix-batch and github-reader commits did not perturb this region. |

Entry Gate item 1 (`identity-vocab-reconcile` at literal `Gate: PASS`) remains a **wording** gap, not
a state gap: its actual state is `Gate: CONDITIONAL`, explicitly user-accepted at supplement cycle 9,
EXECUTED and merged. The gate's *intent* — that the `identity_resolver.py` churn has settled and
shipped — is satisfied, and this pass's drift re-check is the direct proof. Carried as N-VOCAB below.

**Docker Known-Gap — CLEARED.** `docker info` → server **29.4.2**, up. Every Hybrid gate in this
phase moves from gap-resolution **D (deferred residual)** to **B (gate added by this plan's
checklist, runnable at EXECUTE)**. The plan's `## Test Infra Improvement Notes` claim that "every
Hybrid gate in this program is therefore permanently deferred in this environment" is now stale and
must not be used to skip G1/G2.

**F2 — CLEARED by D-A, re-verified against source.** `_upsert_beam_identity` is `-> None` at line
1266 with the guards intact; `_upsert_beam_identity` has **exactly one production caller**
(line 1252 — re-grepped this pass, no second caller appeared). D-A's `bool`-return gating is
mechanically applicable.

**F3 — CLEARED by D-B, re-verified against source.** `ERASURE_TARGETS = ("beam_identity_graph",)`
still at `apps/api/models/erasure_request.py:31`. Because D-B writes **nothing** when the graph write
was blocked, the co-op tables' absence from `ERASURE_TARGETS` is harmless rather than a privacy
regression. SPEC A's sweep mechanics are untouched — this decision only declines to create a new
target.

**C1–C8 — all CLEARED, each re-verified:** `GRAPH_WRITE_BLOCKING_SCOPES = ("erased",
"do_not_process")` at `graph_erasure.py:78` and `is_email_suppressed_any` matches
`scope.in_([*scopes, "all"])` at `suppression.py:44` (so the resolver boundary really does cover
three effective scopes, and D-B correctly declines to re-list any of them). `Visitor.is_abuse_flagged`
at `visitor.py:97` and `Visitor.is_bot_suspect` at `visitor.py:105` (D-C). `billing.check_usage_allowed(db, user_id)`
at `services/billing.py:94` (D-D's Phase-2 consequence anchor holds). `phase-blast-radius-registry.md`
migration paths are corrected at lines 23 and 57 (C4 resolved).

**Zero-collision re-confirmed:** `apps/api/models/identity_coop.py`, `apps/api/services/identity_coop.py`,
`apps/api/routers/identity_coop.py` all absent; no `identity_coop_*` / `coop_credit_*` / `coop_terms*`
in `config.py`; no `contribution_enabled` in `models/site.py`, `schemas/sites.py`, or `routers/sites.py`;
`apps/api/migrations/versions/` exists with 65 revisions and `apps/api/alembic/versions/` does **not**
exist (path correction stands). `SiteOut` at `schemas/sites.py:16`, `SiteUpdate` at `:45`,
`auto_identify_enabled` precedent at `:26`/`:57`; `verify_site_access` at `routers/sites.py:324` with
the single `await db.commit()` at `:341` — E2's same-transaction requirement is naturally satisfiable
and E3's check already exists via that helper.

### Net Gate Derivation

**Layer 1 dimensions**

| Layer 1 dimensions | Status |
|---|---|
| Infra fit | PASS |
| Test coverage | PASS |
| Breaking changes | PASS |
| Security surface | CONCERN |

**Layer 2 sections**

| Layer 2 sections | Status |
|---|---|
| Entry Gate / dependency status | PASS (cleared this pass — see table above) |
| Section A — Models and migrations | PASS |
| Section B — Config | CONCERN (N2 — `coop_terms_version` missing from the settings block E4 depends on) |
| Section C — Service module | PASS |
| Section D — The hook | CONCERN (N3 — "three early-return guards" is an off-by-one; there are two `return` statements covering three conditions) |
| Section E — 7-layer flag wiring | PASS |
| Section F — Tests | PASS |
| Section G — Migration round-trip | PASS (Docker 29.4.2 UP — no longer a deferred residual; G1/G2 are runnable and REQUIRED at EXECUTE) |

**Totals: 0 FAILs / 3 CONCERNs / 7 PASSes** (plus N1, N5 and N-VOCAB carried as document-sync
concerns against sections outside this agent's write scope)

**→ Net Gate: CONDITIONAL**

Net-gate vacuous-green check (Step A1): **no developed behaviour in this phase rests on Known-Gap
alone.** Every acceptance criterion has a Fully-Automated proving gate, and the two DB-enforcement
behaviours (migration round-trip, `uq_coop_accrued_site_email`) have runnable Hybrid gates now that
Docker is up. There is no Known-Gap residual carrying a behaviour by itself, so the vacuous-green ban
does not bite — and the gate is CONDITIONAL on document-sync items, not on missing coverage.

### The CONCERNs found by fresh verification (all doc-sync / execute-instruction class)

**N1 — the Exit Gate block still prints `Expected: <= 6 changed lines`.** Plan line 445. D4 (line 386)
raised the budget to ≤ 12 and states "the ≤ 6 figure is superseded everywhere it appears in this
document" — so the supersession is semantically declared but was never applied to the Exit Gate,
which is the block EXECUTE and EVL copy their commands from. Left as-is, a literal EVL run fails the
D-A fix spuriously, or nudges an implementer toward the rejected shapes (b)/(c) to squeeze under 6.
The authoritative number is **≤ 12**.

**N2 — `coop_terms_version` is required by E4 but missing from `## Config Settings`.** The settings
block (plan lines 281–286) lists four settings; E4 (line 394) requires a fifth,
`coop_terms_version: str`, pinned to the policy-text digest. B2 compounds it by asserting "all
**four** defaults are OFF/inert". An implementer following B1/B2 literally never creates
`coop_terms_version`, and E4's constant compare then references a nonexistent setting. Five settings
are required; B2 must assert five.

**N3 — D5/D-A say "three early-return guards"; there are two `return` statements.** Verified live:
`_upsert_beam_identity` returns at line **1271** (`if not fp or not email`) and at line **1285** (the
single combined `if getattr(visitor, "do_not_resolve", False) or await is_email_suppressed_any(...)`).
The three *conditions* are real; they are collapsed into two *returns*. There is additionally **no
explicit return in the `except` path** (lines ~1327-1329 fall through to an implicit `None`). The
correct, complete edit set is therefore: `return False` at 1271 and 1285; `return True` immediately
after `await self.db.commit()`; `return False` in the `except` block; signature `-> None` → `-> bool`;
docstring updated. That is 6 touched lines — comfortably inside the ≤ 12 budget. Behaviourally
harmless (D5 already forbids changing guard logic or ordering) but an implementer hunting a
nonexistent third return will either stall or invent one.

**N4 — minor citation imprecision in D-C.** D-C cites "`models/visitor.py:105` and `:207`" as "Both
columns exist on `Visitor`". `:105` is `Visitor.is_bot_suspect`; `Visitor.is_abuse_flagged` is at
`:97`. The `:199`/`:207` region belongs to `IdentifiedVisitor`, a different class. **The decision is
sound** — both columns do exist on `Visitor` — only the citation conflates two classes. Use 97 and
105.

**N5 — the plan's own Phase Loop Progress still forbids EXECUTE. HIGHEST-PRIORITY ORCHESTRATOR
ACTION.** Plan lines 537–539 read "**Do NOT spawn vc-execute-agent for this phase.** Status:
**Dependency-BLOCKED — entry gate SPEC A not LIVE; files never modified.**", and
`phase-blast-radius-registry.md:35` carries the same `status: Dependency-BLOCKED` line. Both are now
factually stale. This matters mechanically, not cosmetically: the Phase Program Pre-Routing Check
routes a phase whose Step-0 shows `Dependency-BLOCKED` straight to Phase N+1 **without spawning any
agent**. Left unedited, this contract's CONDITIONAL verdict and the plan body's routing instruction
disagree inside one file — the exact plan-body-vs-record disagreement class that has previously let a
downstream agent proceed on ambiguous authority.

**This contract explicitly SUPERSEDES the following stale plan-body passages**, all of which were
written when F1 was open: line 17–18 (`Phase status` / `Status: ⏳ PLANNED — blocked on two upstream
dependencies`), lines 56–78 (the 2nd pass's Entry Gate re-derivation, incl. its "Entry Gate is still
UNMET" conclusion), line 509 (the SPEC-A-not-LIVE blocker bullet), lines 514–515, the Step-4 note at
line 527, the cycle-1 note at line 535, lines 537–539 (the do-not-spawn instruction), the Docker
sentence in `## Test Infra Improvement Notes` (lines 610–612), and the `Next step` paragraph at lines
622–632. Where any of those passages conflicts with this section, **this section wins.**

**N-VOCAB — Entry Gate item 1 wording.** `identity-vocab-reconcile_07-08-26` is `Gate: CONDITIONAL`
(user-accepted, executed, merged), not the literal `Gate: PASS` the Entry Gate names. Accepted as
satisfying the gate's intent; recorded so it is not re-litigated.

**N6 — the umbrella's `## Pre-PVL Conflict Resolution` is still a placeholder.** Non-blocking here:
`## Phase Ordering` declares the three phases **strictly sequential** with no parallel execution, so
there is no concurrent-edit window for the three named candidate surfaces
(`services/identity_coop.py`, `routers/sites.py`, `models/identity_coop.py`). The correct fill is the
trivial one — "No package conflicts — phases are strictly sequential." No `Action: update Phase [X]
blast-radius claim` entries exist, so V1's Action-field completion check passes vacuously.

### Dimension findings

- **Infra fit: PASS** — live `alembic heads` returns exactly ONE head, `d1a6c4e93f27`; A1's
  STOP-and-re-chain condition will not fire. `apps/api/migrations/versions/` confirmed as the real
  script location (65 revisions; `apps/api/alembic/versions/` does not exist) and the path is now
  correct in the plan body AND in `phase-blast-radius-registry.md:23`/`:57`, closing C4. Docker
  29.4.2 is up, so G1/G2 are executable rather than deferred. Residual: every head string written in
  these documents expires quickly — A1's live re-derivation at EXECUTE time remains the only
  trustworthy value.
- **Test coverage: PASS** — the three holes the 2nd pass flagged are closed by F9–F14, and each new
  test's target now verifies against real source: the no-op paths (F9) map to returns at 1271/1285,
  the privacy invariant (F10) to `ERASURE_TARGETS` at `erasure_request.py:31`, the bot half of AC-9
  (F11) to `Visitor.is_bot_suspect:105`, accrual uniqueness (F12) to the D-E partial index, the
  AC-10 leg (F13) to `SiteUpdate:45` + the single commit at `routers/sites.py:341`, and the signature
  compatibility claim (F14) to the single caller at 1252. Two rows the 2nd pass's table had **omitted**
  (F12, F14) and one Hybrid row (the `uq_coop_accrued_site_email` index check) are ADDED below; the
  stale row naming the **retired** `test_erased_row_earns_no_credit` (F6, retired at supplement cycle
  1) is REMOVED. Every Hybrid gate re-tiered D → B.
- **Breaking changes: PASS** — re-verified. `_save_identified`'s early-return paths all occur before
  the hook anchor at 1252, so none are affected. `_upsert_beam_identity` is private, has exactly one
  production caller, and no cross-module consumer reads its return, so `None` → `bool` is
  contract-safe. The `PATCH /api/v1/sites/{site_id}` addition is additive; the new 422 on a
  missing/malformed/non-current `terms_version` is a genuine new response code and is correctly
  declared in `## Public Contracts`.
- **Security surface: CONCERN** — the privacy posture is now correct by construction: D-B's
  write-nothing rule means no `email_bidx`-bearing co-op row can exist for a person whose graph write
  was blocked, so the co-op tables' absence from `ERASURE_TARGETS` is harmless, and the co-op module
  imports no suppression scope of its own (single source of truth stays inside the resolver's
  boundary). Blind-index-only discipline holds (`pii_crypto.email_hash:66`); the best-effort
  try/except logs keys/ids only; multi-tenancy is preserved via `verify_site_access` (404-not-403).
  **The residual CONCERN is procedural, and it is the one thing standing between this plan and a
  clean PASS: the high-risk 5-artifact evidence pack does not exist.**
  `process/features/visitors-identity/active/identity-coop_07-08-26/harness/` is absent (verified —
  no such directory). Per `vc-risk-evidence-pack`, **billing/credits + schema/migration are two of
  the six high-risk classes**, so `risk-gate.json`, `context-snippets.json`, `verification.json`,
  `review-decision.json` and `adversarial-validation.json` must exist there — with an explicit
  APPROVE/REJECT and written rationale in `review-decision.json` — **before this phase's work may be
  called ready.** This is confirmed as an **EXECUTE deliverable** (see E-5 below), manual-first by
  design, not a blocking hook.

### Execute-agent instructions

| # | Instruction | Trigger condition |
|---|---|---|
| E-1 | The `identity_resolver.py` diff budget is **≤ 12 lines**, not 6. Ignore the `Expected: <= 6 changed lines` line in the Exit Gate block (N1) — D4 supersedes it. Do NOT reshape the D-A fix to fit 6. | Step D / Exit Gate |
| E-2 | Create **five** config settings, not four: the four in `## Config Settings` **plus** `coop_terms_version: str` required by E4 (N2). B2's assertion must cover all five and confirm `identity_coop_enabled is False`. | Step B entry |
| E-3 | `_upsert_beam_identity` has **two** `return` statements (lines 1271 and 1285 as of this pass), not three, and **no** explicit return in its `except` block (N3). Apply: `return False` at both existing returns, `return True` immediately after `await self.db.commit()`, `return False` in the `except` path, `-> None` → `-> bool`, docstring updated. Locate by call-graph position, not by these line numbers. Do NOT alter guard logic or ordering. | Step D5 |
| E-4 | **Docker is UP (29.4.2).** G1/G2 are REQUIRED, not deferred. Run the round-trip on a DISPOSABLE Postgres only — never a shared or prod database. Also assert the `uq_coop_accrued_site_email` partial unique index exists after `upgrade head` and that a duplicate `ACCRUE` insert raises `IntegrityError`. The plan's `## Test Infra Improvement Notes` "permanently deferred" sentence is stale — do not cite it to skip G2. | Step G entry |
| E-5 | Produce the 5-artifact high-risk evidence pack in `process/features/visitors-identity/active/identity-coop_07-08-26/harness/` and validate it with `node .claude/skills/vc-risk-evidence-pack/scripts/validate-risk-artifacts.mjs`. `review-decision.json` needs an explicit APPROVE/REJECT with written rationale; `adversarial-validation.json` is required (credit-minting-without-a-graph-write and erased-person-row-creation are the two adversarial scenarios to rule out). Do not report DONE without it. | Before reporting the phase ready |
| E-6 | Re-derive `alembic heads` LIVE as the FIRST action of Step A and record the value in the phase report. `d1a6c4e93f27` was the single head at this pass; this repo's head moves on a roughly daily cadence. Chain both new migrations onto the live value, never onto a head string quoted in any document. | Step A1 |
| E-7 | Take `email_bidx` from `pii_crypto.email_hash` (`:66`) only. Never pass plaintext email into `identity_coop.py`. `structlog` calls in the co-op module log keys/ids only. | Step C / D3 |

### Proposed plan updates (outside this agent's write scope — orchestrator or plan-agent supplement)

| # | What changes | Where in plan | Why |
|---|---|---|---|
| P1 | Replace `Expected: <= 6 changed lines` with `Expected: <= 12 changed lines` | Exit Gate, line 445 | N1 — D4 already declares the supersession; apply it to the block EXECUTE copies from |
| P2 | Add `coop_terms_version: str = "<policy-text digest>"` to the settings block; change B2 from "all four" to "all five" | `## Config Settings` (281-286), B2 (313) | N2 — E4 depends on a setting the block does not list |
| P3 | Reword D5/D-A "three early-return guards" → "two early-return statements covering three conditions, plus the `except` path" | D5 (388), D-A (99-103) | N3 — off-by-one sends the implementer looking for a return that does not exist |
| P4 | Correct D-C's citation to `visitor.py:97` (`is_abuse_flagged`) and `:105` (`is_bot_suspect`); drop `:207` | D-C (149-156) | N4 — `:207` is `IdentifiedVisitor`, a different class |
| P5 | **Remove the `Dependency-BLOCKED` status and the "Do NOT spawn vc-execute-agent" instruction**; set `Phase status`/`Status` to `⏳ PLANNED — entry gate CLEARED 07-08-26, ready for EXECUTE`; update `phase-blast-radius-registry.md:35` the same way | Lines 17-18, 537-539; registry line 35 | **N5 — MUST happen before vc-execute-agent is spawned.** The Pre-Routing Check skips a Dependency-BLOCKED phase entirely, so leaving this text routes Phase 1 past EXECUTE to Phase 2 |
| P6 | Replace the "every Hybrid gate is permanently deferred in this environment" sentence with "Docker 29.4.2 available 07-08-26 — Hybrid gates are runnable and required" | `## Test Infra Improvement Notes` (610-612) | Docker Known-Gap cleared; stale text invites skipping G2 |
| P7 | Fill `## Pre-PVL Conflict Resolution` with "No package conflicts — phases are strictly sequential." | Umbrella, line 500-504 | N6 — placeholder; trivially derivable from `## Phase Ordering` |

### Open gaps

- **High-risk evidence pack absent (procedural, gap-resolution B — due at EXECUTE).** `harness/` does
  not exist. Required before the phase may be called ready. See E-5.
- **N5 doc-sync is a hard precondition, not a nit.** The plan's own Phase Loop Progress still says do
  not spawn execute-agent. P5 must be applied before EXECUTE is spawned.
- **`alembic heads` is a snapshot.** `d1a6c4e93f27` was the single head at this pass. Re-derive live
  at EXECUTE (E-6).
- **`identity-vocab-reconcile` wording gap (N-VOCAB)** — `Gate: CONDITIONAL` user-accepted, not the
  literal `Gate: PASS` the Entry Gate names. Accepted as intent-satisfied.
- **Prod-environment behaviour of the co-op is unproven and out of scope by design.** All flags
  default OFF; enabling `identity_coop_enabled` or any site's `contribution_enabled` in a real
  environment is a separate, explicit, later operator action gated on legal review — never part of
  this phase.
- No out-of-scope gap was deferred to backlog in this PVL cycle. The prior cycle's F1 backlog note
  (`backlog/identity-coop-entry-gate-spec-a-live_NOTE_07-08-26.md`) is **RESOLVED** by this pass and
  should be marked as such at UPDATE PROCESS.

### Test gates (C3 5-column table — ADDITIVE; the legacy line form follows)

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 | flag OFF ⇒ zero contribution events and zero ledger rows across a full resolve cycle | Fully-Automated | `tests/integration/test_identity_coop_contribution.py::test_flag_off_produces_zero_contributions` (F1) | B |
| AC-2 | a non-contributing site STILL receives graph-served identifications (read unconditional) | Fully-Automated | `tests/integration/test_identity_coop_contribution.py::test_non_contributor_still_receives_graph_matches` (F2) | B |
| AC-3 | merge-aware counting — same email, two `visitor_id`s, one day ⇒ exactly one event | Fully-Automated | `tests/unit/test_identity_coop.py::test_merged_duplicate_counts_once` (F3) | B |
| AC-3 / AC-5 (ex-F2, D-A/D-B) | a resolve where the graph write NO-OPS accrues zero credit AND writes zero event rows — one case per path: missing fingerprint; `do_not_resolve=True`; `do_not_process` tombstone; `all` tombstone | Fully-Automated | `tests/unit/test_identity_coop.py::test_blocked_graph_write_accrues_nothing` (F9) | B |
| AC-5 | one qualifying contribution ⇒ exactly one positive `ACCRUE` row with `site_id`, `reason`, `created_at`, `expires_at`, `spendable_at` | Fully-Automated | `tests/integration/test_identity_coop_contribution.py::test_qualifying_contribution_writes_ledger_row` (F4) | B |
| AC-9 (abuse half) | `is_abuse_flagged=True` ⇒ event recorded, `excluded_reason='fraud_flagged'`, zero ledger rows | Fully-Automated | `tests/integration/test_identity_coop_contribution.py::test_abuse_flagged_visitor_earns_no_credit` (F5) | B |
| AC-9 (bot half, D-C) | `is_bot_suspect=True` ⇒ event recorded, `excluded_reason='fraud_flagged'`, zero ledger rows | Fully-Automated | `tests/unit/test_identity_coop.py::test_bot_suspect_visitor_earns_no_credit` (F11) | B |
| Privacy invariant (D-B) | after an erasure tombstone exists, a later resolve of that person leaves NO `email_bidx`-bearing row in `identity_contribution_events` | Fully-Automated | `tests/unit/test_identity_coop.py::test_erased_person_leaves_no_new_bidx_row` (F10) | B |
| Accrual uniqueness (D-E) | same `(site_id, email_bidx)` resolved on two different days ⇒ two event rows (second `accrued=False, excluded_reason='duplicate'`) and exactly ONE ledger row total | Fully-Automated | `tests/unit/test_identity_coop.py::test_second_day_resolve_accrues_no_second_credit` (F12) | B — **ADDED this pass; the 2nd pass's table omitted it** |
| AC-12 | pre-program `beam_identity_graph` rows contribute 0 to any site's ledger | Fully-Automated | `tests/unit/test_identity_coop.py::test_grandfathered_rows_contribute_zero` (F7) | B |
| Best-effort hook contract | a forced `record_contribution` failure never breaks `_save_identified`'s return | Fully-Automated | `tests/unit/test_identity_coop.py::test_coop_failure_does_not_break_identification` (F8) | B |
| AC-10 automated leg + E4 | `contribution_enabled=True` rejected 422 with missing / malformed / non-current `terms_version`; accepted only with the pinned version, writing exactly one acceptance row in the SAME transaction | Fully-Automated | `tests/integration/test_identity_coop_contribution.py::test_flag_on_requires_acceptance` (F13) | B |
| D-A signature compatibility | `_upsert_beam_identity` returns `True` on a successful write and `False` on every guard path; with `identity_coop_enabled=False` the hook stays inert even when the function is `AsyncMock`-replaced | Fully-Automated | `tests/unit/test_identity_coop.py::test_upsert_returns_bool_and_existing_callers_unaffected` (F14) | B — **ADDED this pass; the 2nd pass's table omitted it** |
| Flags-default-OFF constraint | all five Phase 1 settings default OFF/inert and `identity_coop_enabled is False`; `Site.contribution_enabled` defaults `False` | Fully-Automated | B2 assertion in `tests/unit/test_identity_coop.py` | B |
| Migration currency | offline `--sql` validation clean, EXPLICIT revision range (unscoped `head --sql` fails mid-chain on `b7d3e9f1a4c2`) | Fully-Automated | `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade <head_from_A1>:head --sql` | B |
| Unit-lane regression | no regression in the existing unit lane | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` | B |
| Integration-lane regression | no regression in the existing integration lane (baseline 518P/0F/0E at `81eb4e6`) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/ -m integration -q` | B |
| Collision-minimization | `identity_resolver.py` diff **≤ 12 lines** (budget re-set at supplement cycle 1, D-A) | Fully-Automated | `git diff --stat apps/api/services/identity_resolver.py` | B — **number corrected 6 → 12 this pass; the 2nd pass's table still said 6** |
| schema/migration high-risk class | live migration round-trip: `upgrade head → downgrade -1 → downgrade -1 → upgrade head`, clean both directions | Hybrid (precondition: DISPOSABLE Postgres container — **Docker 29.4.2 verified UP this pass**) | `docker compose -f infra/docker-compose.yml up -d postgres` then the four alembic commands (G1/G2) | B — **re-tiered from D; Docker is available, this gate is REQUIRED not deferred** |
| D-E enforced in the DB, not only in service code | `uq_coop_accrued_site_email` partial unique index present after `upgrade head`; a duplicate `ACCRUE` insert raises `IntegrityError` | Hybrid (same precondition) | index-presence query + duplicate-insert assertion against the disposable Postgres | B — **ADDED this pass; the 2nd pass's table omitted it** |
| Entry Gate (ex-F1) | SPEC A EVL GREEN + migration round-tripped + pushed/deployed; `alembic heads` single; `identity_resolver.py` anchors unmoved | Agent-Probe | re-derived live THIS pass: 14/14 collect, `81eb4e6` in `origin/main`, `443ad5e` on both remotes at 0/0, one head `d1a6c4e93f27`, anchors at 1252/1264 | **A — proven now** (was C) |
| high-risk evidence pack | 5-artifact manual-first pack exists under `harness/` and records an explicit APPROVE/REJECT with written rationale | Agent-Probe | `node .claude/skills/vc-risk-evidence-pack/scripts/validate-risk-artifacts.mjs` against `.../identity-coop_07-08-26/harness/` | B — due at EXECUTE (E-5); pack does not exist yet |

gap-resolution legend:
- A — proven now (gate passes in this cycle)
- B — fixed in this plan (gate added by this plan's checklist)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

C-4 reconciliation: the `strategy:` column carries ONLY the 3 proving strategies (Fully-Automated /
Hybrid / Agent-Probe). Known-Gap is never a `strategy:` value here. **No row carries residual D any
more** — the Docker-gated rows became B when Docker came up, and the entry gate became A.

**Row removed this pass:** the 2nd pass's `SPEC A interface (C1)` row named
`tests/unit/test_identity_coop.py::test_erased_row_earns_no_credit` and said it "EXISTS, must be
widened". That test (F6) was **RETIRED** at supplement cycle 1 under D-B — the plan explicitly says
"do not write this test". Its coverage is fully carried by F9 (`test_blocked_graph_write_accrues_nothing`,
which drives all four no-op paths including `do_not_process` and `all`) and F10
(`test_erased_person_leaves_no_new_bidx_row`). Leaving the stale row in would have instructed
execute-agent to write a test the plan forbids.

Legacy line form (retained so existing validate-contract consumers still parse):
- F1-F5, F7-F14 (13 tests; F6 retired) plus the B2 defaults assertion: Fully-automated, commands as named above
- Migration offline `--sql` + both pytest lanes + `git diff --stat` ≤ 12 guard: Fully-automated
- Disposable-Postgres migration round-trip: Hybrid, precondition: disposable Postgres container running (Docker 29.4.2 UP — runnable)
- `uq_coop_accrued_site_email` partial-index presence + duplicate-ACCRUE IntegrityError: Hybrid, same precondition
- Entry Gate dependency re-check: Agent-probe, PROVEN this pass (single head, anchors unmoved, SPEC A 14/14 and pushed)
- High-risk evidence pack: Agent-probe, 5-artifact pack present with explicit reviewer decision — due at EXECUTE

### Failing stubs (Fully-Automated rows only)

Execute-agent translates each skeleton into the repo's pytest form
(`async def test_...(...): ...` with the `@pytest.mark.unit` / `@pytest.mark.integration` marker per
lane); the skeleton names the behaviour so the red-first gate is unambiguous.

**AC-1:**
```
test("should assert flag OFF produces zero contribution events and zero ledger rows across a full resolve cycle", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_flag_off_produces_zero_contributions")
})
```

**AC-2:**
```
test("should assert a non-contributing site still receives graph-served identifications", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_non_contributor_still_receives_graph_matches")
})
```

**AC-3:**
```
test("should assert two resolves of the same email under two visitor_ids on the same day produce exactly one contribution event", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_merged_duplicate_counts_once")
})
```

**AC-3 / AC-5 (D-A/D-B — no graph write ⇒ no credit):**
```
test("should assert a resolve where the graph write no-ops accrues zero credit and writes zero event rows, one case per no-op path", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_blocked_graph_write_accrues_nothing")
})
```

**AC-5:**
```
test("should assert one qualifying contribution writes exactly one positive ACCRUE ledger row", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_qualifying_contribution_writes_ledger_row")
})
```

**AC-9 (abuse half):**
```
test("should assert abuse-flagged traffic produces a contribution event with fraud_flagged and zero ledger accrual", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_abuse_flagged_visitor_earns_no_credit")
})
```

**AC-9 (bot half, D-C):**
```
test("should assert is_bot_suspect traffic produces a fraud_flagged event and earns no credit", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_bot_suspect_visitor_earns_no_credit")
})
```

**Privacy invariant (D-B):**
```
test("should assert an erased person's later resolve creates no new email_bidx row in identity_contribution_events", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_erased_person_leaves_no_new_bidx_row")
})
```

**Accrual uniqueness (D-E):**
```
test("should assert a second-day resolve of the same site and email_bidx records a duplicate event and mints no second credit", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_second_day_resolve_accrues_no_second_credit")
})
```

**AC-12:**
```
test("should assert grandfathered pre-program graph rows contribute zero to any site's ledger", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_grandfathered_rows_contribute_zero")
})
```

**Best-effort hook contract:**
```
test("should assert a forced record_contribution failure never breaks _save_identified's return", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_coop_failure_does_not_break_identification")
})
```

**AC-10 automated leg + E4:**
```
test("should assert contribution_enabled cannot be set true without a valid pinned terms_version and writes the acceptance row in the same transaction", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_flag_on_requires_acceptance")
})
```

**D-A signature compatibility:**
```
test("should assert _upsert_beam_identity returns true on write and false on every guard path, and the hook stays inert when the flag is off", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_upsert_returns_bool_and_existing_callers_unaffected")
})
```

**Flags-default-OFF constraint:**
```
test("should assert all five Phase 1 co-op settings default off or inert and Site.contribution_enabled defaults false", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: B2 config defaults assertion")
})
```

(Hybrid and Agent-Probe rows do not receive stubs, per policy.)

### What this coverage does NOT prove

- **No co-op code path was executed this cycle.** Zero of the 14 planned tests exist on disk. This
  pass proved: the entry gate is genuinely met (three of four conditions by independent live command),
  mechanical feasibility (every anchor, field, path and line number re-verified against the working
  tree), semantic consistency of D-A…D-E against current source, and test-gate-table completeness. It
  ran no co-op logic.
- **`git diff --stat ≤ 12` proves footprint, not correctness.** A 12-line diff can still gate accrual
  on the wrong condition. F9 and F14 are what prove the gating; the diff guard only prevents logic
  leaking out of `identity_coop.py`.
- **The Hybrid gates are RUNNABLE but have not been RUN.** Docker being up removes the excuse, not
  the work. Nothing about the migration round-trip or the `uq_coop_accrued_site_email` index is
  proven until G1/G2 execute at EXECUTE time.
- **SPEC A's erasure is proven at the integration level, not in production.** 14/14
  `test_graph_erasure_flow.py` gates pass against real Postgres and the code is deployed, but the
  8 repaired gates were fixed test-side during the same session that green-lit them, and
  `graph_erasure_sweep_enabled` (default `True`) running correctly under real production load and
  real crash/recovery is still only covered by those integration gates. Phase 1 now depends on that
  boundary *behaviourally* (D-A's `False` path), so a latent defect there would surface as a
  correctness bug on the credit surface.
- **`alembic heads` is a snapshot, not a guarantee.** `d1a6c4e93f27` held at this pass and has held
  since the 2nd pass, but four migrations appeared in this repo inside one day earlier in the
  program. Treat every head string in these documents as expired; A1's live re-derivation is the only
  trustworthy value.
- **Prod enablement is unproven and deliberately untested.** Every flag defaults OFF. Nothing here
  proves the co-op behaves correctly with `identity_coop_enabled=True` under real traffic, and no
  gate in this phase attempts it — that is an explicit later operator action gated on legal review.
- **The doc-sync items (N1, N2, N5, P1–P7) are diagnosed, not applied.** This agent's write scope is
  this contract section only. Until P5 in particular is applied, the plan body still instructs the
  orchestrator not to spawn execute-agent.
- **AC-4, AC-6, AC-7, AC-11 are not in this phase's scope.** Phase 1 covers AC-1, AC-2, AC-3, AC-5,
  AC-9, AC-10 (automated leg), AC-12 plus the D-B/D-E invariants. The remainder belong to Phases 2-3
  per the umbrella's Coverage Map and are proven nowhere yet.
- **C6's reconciliation is decided but unproven.** D-D fixes the ledger at `site_id`-only and binds
  Phase 2 to aggregate via `sites.user_id` at `billing.check_usage_allowed`'s decision point. The
  anchor is verified to exist (`services/billing.py:94`); that the aggregation actually produces the
  right balance is Phase 2's gate, and no test in any phase covers it today.

Gate: CONDITIONAL

Accepted by: orchestrator convergence rule, autopilot run 07-08-26. Zero behavioural FAILs were found
in this pass's fresh verification; F1, F2, F3 and C1-C8 are all cleared with live evidence recorded
above. The accepted concerns, by name: **N1** (Exit Gate still prints the superseded ≤6-line budget),
**N2** (`coop_terms_version` missing from the settings block E4 depends on), **N3** (D5/D-A's
"three early-return guards" off-by-one), **N4** (D-C's `visitor.py:207` citation belongs to
`IdentifiedVisitor`), **N5** (the plan body's stale `Dependency-BLOCKED` status and "Do NOT spawn
vc-execute-agent" instruction — accepted as a doc-sync item, but see the hard precondition below),
**N-VOCAB** (`identity-vocab-reconcile` is `Gate: CONDITIONAL` user-accepted, not literal
`Gate: PASS`), **N6** (umbrella `## Pre-PVL Conflict Resolution` placeholder, moot under strict
sequencing), and the **absent 5-artifact high-risk evidence pack** (accepted as an EXECUTE
deliverable per E-5, not as a permanent gap).

**EXECUTE is unblocked** — meaning the VALIDATE gate no longer blocks it. Two mechanical routing
facts follow, neither of which is a gate deviation:

1. **P5 must be applied before vc-execute-agent is spawned.** While plan lines 537-539 read "Do NOT
   spawn vc-execute-agent for this phase" and `phase-blast-radius-registry.md:35` reads
   `status: Dependency-BLOCKED`, the Phase Program Pre-Routing Check will **skip this phase entirely**
   rather than execute it. The Step-4 checkbox note (line 527) also still summarises the superseded
   3-FAIL BLOCKED verdict and must be replaced with this contract's CONDITIONAL verdict.
2. **The next spawn is vc-research-agent, not vc-execute-agent.** This contract is
   `generated-by: outer-pvl`, and inner-loop Steps 1 (RESEARCH), 2 (INNOVATE) and 3
   (PLAN-SUPPLEMENT) are still unchecked in `## Phase Loop Progress`. Per the Pre-Routing Check the
   orchestrator routes to Step 1 first. This is convenient rather than costly: **Step 3
   PLAN-SUPPLEMENT is exactly the mechanism for applying P1-P7**, and Step 1's RESEARCH brief is
   already written by this contract (re-derive `alembic heads`, re-check the 1252/1264 anchors).
   Step 3 then either writes an `## Inner Loop Refresh Note` — in which case inner PVL re-runs from
   V1 against the corrected plan — or marks "n/a", in which case V1 auto-proceeds on this contract.
   Either path reaches EXECUTE without another BLOCKED verdict, because no behavioural defect
   remains open.

---

## Post-Audit Fix Supplement (16-08-26)

**TL;DR** — The 16-08-26 adversarial re-audit of the already-executed Phase 1 found 3 real defects
(2 HIGH, 1 MEDIUM-live-on-prod), 1 test-coverage hole, and 1 bookkeeping error. The human reviewer
**REJECTED** the evidence pack pending these fixes. This supplement is a scoped fix list — it does
not re-open the Phase 1 design, does not add a schema change, and keeps every flag default OFF.

| ID | Sev | Defect | Chosen fix shape |
|---|---|---|---|
| H1 | HIGH | Site delete cascade omits the 3 co-op tables → deleting + re-creating the same `site_id` resurrects spendable balance | DELETE `identity_contribution_events` + `identity_credit_ledger` with the site; **RETAIN** `identity_contribution_consent_acceptances` (rationale below) |
| H2 | HIGH | Erasure enqueue→sweep window (default 5 min) lets a re-resolve mint a permanent co-op bidx row + credit for an erased person | **Shape (a)**: write the suppression tombstone inside `enqueue_erasure`'s own transaction. Shape (b) rejected — rationale below |
| M2 | MED (live on prod) | `update_site` allows `contribution_enabled=True` gated only on terms-digest, NOT on `settings.identity_coop_enabled` | Gate the True-flip on `identity_coop_enabled` (422, matching the sibling guard); digest re-pin reset becomes a runbook line |
| M3 | MED | Resolver hook wiring has zero test execution — `maybe_record_contribution` happy path never runs | Add 1 unit-lane hook test (flag patched True) + 1 integration test (both flags ON, real accrual row) |
| L1 | LOW | `harness/adversarial-validation.json` cites mock tripwires that can never fire | Correct the non-vacuity claims to cite the real load-bearing signal; retire the F14 third leg as vacuous |
| R1 | — | `harness/review-decision.json` still reads `PENDING USER APPROVE/REJECT` | Record the human's actual verdict: `rejected` |

---

### Design decision H1-D — consent acceptances are RETAINED on site delete

`identity_contribution_consent_acceptances` is an **append-only legal audit trail**: it is the only
evidence that a site owner lawfully opted into the co-op at a specific terms digest and time.
Deleting a consent record is itself a legal/policy act, and destroying the proof-of-lawful-basis
alongside the data it authorised is the wrong default — if a contribution's lawfulness is ever
challenged, the acceptance row is the defence.

**Resurrection risk is already closed by existing code, not by deletion.** A re-created `Site` row
starts with `contribution_enabled=False` (column default), and turning it ON requires a *fresh*
acceptance row written in the same transaction as the flip (`update_site`, AC-10). An inherited
acceptance row is therefore inert — it can never by itself enable contribution. Retention costs
nothing operationally and preserves the audit chain.

**Rejected alternative:** delete acceptances with the site. Rejected because it destroys the audit
trail for contributions that were *already made and already credited to other tenants* — those
contributions do not disappear when the contributing site is deleted, so their lawful-basis record
must not either. **Rejected alternative 2:** retention with a site-tombstone marker column. Rejected
as unnecessary schema churn — `sites` row absence is already the tombstone, derivable by join.

The two *spendable* tables (`identity_contribution_events`, `identity_credit_ledger`) ARE deleted:
a deleted site's credits must not be re-spendable by a re-created site, and the partial-unique
suppression state (`D-E`) must not silently suppress a legitimate new accrual.

### Design decision H2-D — close the window at enqueue, not repair it at sweep

**Shape (a) — tombstone inside `enqueue_erasure`'s transaction — CHOSEN.**

Blast-radius analysis of moving the tombstone from post-sweep to at-request, across all
`is_email_suppressed_any` callers: every caller uses suppression to *withhold* an action (skip
outreach, skip resolution, skip graph write). Writing the tombstone earlier therefore only ever
suppresses **more**, **sooner**, and only ever in response to an explicit erasure request from the
data subject's site. The change is strictly in the fail-safe direction; there is no caller for whom
"suppressed earlier than before" is a regression.

It is also idempotent: `_tombstone_stmt` already uses `on_conflict_do_nothing(["email_hash","scope"])`,
so the sweep's existing write becomes a harmless no-op rather than a conflict. `enqueue_erasure`
already commits its own transaction (documented: the queued request must survive a partially-failed
caller deletion) — the tombstone rides that same commit, so "request queued but not suppressed"
becomes structurally impossible. **No schema change.**

**Shape (b) — add co-op tables to `ERASURE_TARGETS` — REJECTED for this supplement.** Rationale:
(i) with (a) the window is closed *prospectively*, so there is nothing left for a retroactive
repair to fix; (ii) both co-op flags have always been default OFF and neither migration is live on
prod, so **zero pre-existing co-op rows exist anywhere** that would need repairing; (iii) (b)
requires defining credit-reversal semantics, which is a real design question (a REVERSAL ledger row
preserving the append-only invariant — never a DELETE of an accrual — plus a Phase 2 spend-gate
interaction), and that belongs to Phase 2's spend surface, not to a Phase 1 hotfix.

**Deferred, not dropped:** a backlog note must record the reversal-semantics design (`REVERSE` ledger
kind offsetting an `ACCRUE` lot, never deleting it) as a Phase 2 prerequisite, so that if co-op
rows ever exist before an erasure path changes again, the repair shape is already specified.

**Invariant restored:** with (a), "no permanent record of an erased person" holds for the co-op
tables without those tables needing to be erasure targets — because the row is never minted in the
first place.

### Design decision M2-D — 422, not 404

`update_site` already raises `422` for the terms-digest mismatch on the same field in the same
branch. The new global-flag guard is the same class of failure (the request is well-formed but the
requested state is not currently reachable) and must read identically. `404` is reserved in this
router for tenancy leaks (unknown/foreign `site_id`) — using it here would be a category error and
would make a legitimate owner's request look like a missing site. Turning the flag **OFF** stays
unconditional and ungated, unchanged.

---

## Implementation Checklist (Supplement)

### S1 — H1: site delete cascade

1. In `apps/api/routers/sites.py`, add `"identity_contribution_events"` and
   `"identity_credit_ledger"` to the direct-`site_id` delete tuple (~:311-341), appended after
   `"ad_connections"` with a comment naming the resurrection gap they close.
2. Do **not** add `identity_contribution_consent_acceptances` — add an explicit inline comment
   stating it is deliberately retained as a legal audit trail, citing decision H1-D, so a future
   reader does not "fix" the apparent omission.
3. Confirm both new tables appear in the `deleted` dict passed to the `site_deleted` log event (the
   existing loop already assigns `deleted[table] = r.rowcount`, so no code change should be needed).
   **`delete_site` returns `Response(status_code=204)` with no body — the `deleted` dict is log-only.
   Do NOT add a response body or a response model.** (SUP-C4.)

### S2 — H2: close the enqueue→sweep window

4. In `apps/api/services/graph_erasure.py`, inside `enqueue_erasure` (~:182-225): after `db.add(row)`
   and **before** `await db.commit()`, execute `_tombstone_stmt(bidx)` when `bidx` is non-empty.
   Same transaction, same commit — the queued request and the suppression tombstone become atomic.
5. Guard the empty case: skip the statement entirely when `bidx` is falsy (mirrors the existing
   `_identity_signals_delete_stmt` empty-list guard).
5a. **(SUP-C5 + SUP2-F1 — mandatory, do not skip. A bare `try/except` is NOT acceptable here.)**
   The tombstone `execute` MUST run inside a **SAVEPOINT** — `async with db.begin_nested():` — and
   that savepoint block is what the `except` wraps. Exact required shape:

   ```python
   if bidx:
       try:
           async with db.begin_nested():
               await db.execute(_tombstone_stmt(bidx))
       except Exception:  # noqa: BLE001
           logger.warning("tombstone_write_failed", site_id=site_id)  # no PII
   await db.commit()
   ```

   **Why a bare `try/except` fails (do not "simplify" this back):** `AsyncSession.execute()`
   **autoflushes**, so `db.add(row)`'s `ErasureRequest` INSERT is emitted into the SAME transaction
   immediately before the tombstone statement. A DB-level tombstone failure (deadlock, statement
   timeout, connection loss — `on_conflict_do_nothing` removes only the unique-violation case)
   **aborts the whole Postgres transaction**; catching the Python exception does not un-abort it.
   The following `await db.commit()` then either raises `PendingRollbackError` (SQLAlchemy requires
   a rollback before the session is usable again) or is discarded by Postgres as a ROLLBACK — either
   way the flushed `ErasureRequest` row is lost. If it raises, `routers/visitors.py:434-446` rolls
   back and **still** deletes the visitor rows that `_collect_match_keys` names as the ONLY source of
   the match keys, making the erasure permanently unrecoverable. If it does not raise,
   `enqueue_erasure` returns a row id for a row that was never persisted — a **false compliance
   receipt**. Both outcomes are strictly worse than today.

   With the savepoint, a tombstone failure rolls back **only the savepoint**; the outer transaction
   stays usable, the `ErasureRequest` insert and its commit proceed untouched, and behaviour degrades
   to exactly today's (the sweep writes the tombstone later). The "degrades to today's behaviour"
   claim is true **only** with the savepoint.

   Repo idiom — this is the established pattern for "inner statement may fail, outer work must
   survive": `apps/api/services/identity_coop.py:175` and `apps/api/routers/sites.py:206`.
   Budget: ~11 touched lines in `graph_erasure.py`, inside the existing ≤18 budget.
5b. **(SG-15 — must be able to fail against a bare-`try/except` implementation.)** Add the unit gate
   in `tests/unit/test_graph_erasure.py` using the repo's **fake-savepoint** pattern
   (`tests/unit/test_site_limit.py:100-114` — a no-op async CM returned by
   `db.begin_nested = Mock(return_value=_Savepoint())`; see also
   `tests/unit/test_identity_coop.py:105`). The test must:
   - patch the tombstone `execute` to raise;
   - assert **`db.begin_nested` was called** (i.e. the savepoint was entered) — this assertion is
     what makes the gate red against a bare-`try/except` implementation, which never enters one;
   - assert the `ErasureRequest` was still `db.add`-ed **and** `db.commit()` was awaited afterwards
     (the request survives), and that no exception escapes `enqueue_erasure`.
   A plain "patched raise did not escape" assertion is **vacuous** — against a fake session a Python
   raise never aborts a real transaction, so it passes with or without the savepoint. Do not ship the
   vacuous form.
5c. **(Optional, high-risk-class minimum — Hybrid.)** If a DB-level failure can be forced cheaply
   (e.g. a statement-level failure injected inside the tombstone statement against PG :5433), add a
   Hybrid leg asserting the `ErasureRequest` row is still present after `enqueue_erasure` returns.
   Recorded as a known-gap if not implemented — see Test Gates (Supplement).
6. Add a docstring line to `enqueue_erasure` stating the invariant: *"the tombstone is written here,
   not at sweep, so no re-resolve can slip through the sweep-interval window."*
6a. **(SUP-C6 + SUP2-C3.)** Correct **both** falsified sentences in the `"erased"` scope docstring
   at `apps/api/models/suppression.py:23-28`. Today it reads: *"Written by the erasure sweep
   (services/graph_erasure.py) using the stored blind index directly as email_hash, so no plaintext
   is ever needed. Durable audit marker: it records that a person's shared-graph rows were
   hard-deleted."* S2 falsifies the **first** clause (the write now happens at enqueue) **and** the
   **second** (at enqueue time nothing has been deleted yet — the rows are hard-deleted later, by the
   sweep). Replace the whole two-sentence tail with:

   > *"Written at enqueue time by `enqueue_erasure` (services/graph_erasure.py) using the stored
   > blind index directly as email_hash, so no plaintext is ever needed; the sweep's later write is
   > an idempotent no-op via `on_conflict_do_nothing`. Durable audit marker: it records that an
   > erasure was **requested** for this person — the shared-graph rows are hard-deleted by the
   > sweep."*

   Adjust the line-wrapping to match the surrounding docstring's indentation; keep the meaning and
   both corrections. Also add a one-line comment at the operator audit lookup
   (`graph_erasure.py` ~:563-575) noting that `erased_tombstone: True` now means **erasure requested
   or completed**, not completed-only. Documentation only — no behaviour change. Budget for
   `suppression.py`: ≤8 touched lines (raised from ≤3 — the "Written by" clause alone spans 3 lines
   and the "hard-deleted" sentence adds ~3 more).
7. Leave `_process_claimed`'s tombstone write in place unchanged — it is now an idempotent no-op via
   the existing `on_conflict_do_nothing`, and it remains the correct behaviour for rows enqueued by
   any older code path.
8. Write the backlog note deferring shape (b): `process/features/visitors-identity/backlog/
   coop-credit-reversal-semantics_NOTE_16-08-26.md` — records the `REVERSE`-ledger-row design, the
   append-only invariant, and that it is a Phase 2 spend-gate prerequisite.

### S3 — M2: gate the contribution opt-in flip

9. In `apps/api/routers/sites.py` `update_site` (~:417-438): inside `if body.contribution_enabled:`,
   **before** the terms-digest comparison, raise `HTTPException(422, detail="identity co-op is not
   enabled on this deployment")` when `not settings.identity_coop_enabled`.
9a. **(SUP-F1 — mandatory; S3 is not complete without it.)** S3 turns an existing GREEN gate RED:
    `tests/integration/test_identity_coop_contribution.py::test_flag_on_requires_acceptance` step 4
    (~:493-500) PATCHes `contribution_enabled=True` and asserts **200**, but the file never
    monkeypatches `settings.identity_coop_enabled` (it asserts `is False` at :93). Fix in the same
    commit as the guard:
    - monkeypatch `settings.identity_coop_enabled = True` for the **WHOLE test function**
      `test_flag_on_requires_acceptance` (function-scoped `monkeypatch` fixture / `setattr` at the
      top of the test) — **NOT** "the 200-path steps only". **(SUP2-C1.)** Rationale: S3's guard is
      inserted **before** the terms-digest comparison (`routers/sites.py:419-434`), so with the
      global flag left OFF the three existing digest legs (lines ~470-489, including the one the test
      itself labels "the vacuous-guard case the plan called out by name" at ~:476) would
      short-circuit on the new global-flag 422 and **never reach the digest branch at all**. They
      would stay green while proving nothing — they would still pass with the entire digest block
      deleted. That is a silent coverage regression on AC-10's consent gate. Whole-function scoping
      is also the natural pytest shape (`monkeypatch` is function-scoped; "step 4 only" requires
      manual setattr/restore). With it, all five legs keep their original meaning: steps 1-3 reach
      and exercise the digest comparison, step 4 gets 200, step 5's opt-out is ungated either way.
    - **Do not** weaken or delete the existing opt-out leg inside this test — but note it is NOT
      selectable by SG-10's `-k`, so SG-10 needs its own function (item 15e below).
    - **add a NEW, separate negative test function** (its own `def`, named
      `test_contribution_flip_gated_on_global_flag`) asserting **422** when
      `settings.identity_coop_enabled` is False and a *valid* current digest is supplied — this is
      the newly-declared contract change, it is what SG-9 proves, and it is the only place the
      flag-OFF contract is covered once the flag is patched True for the whole function above.
    After this item, SG-1 and SG-11 (`0 failed`) are both satisfiable again.
10. Leave the OFF path untouched and unconditional (opting out is never gated).
11. Add the operator runbook line to the plan's own runbook surface (or a new
    `coop-terms-repin_RUNBOOK_16-08-26.md` in this task folder): *"at any re-pin of
    `coop_terms_version`, run `UPDATE sites SET contribution_enabled=false;` — the digest change
    invalidates all prior acceptances, and every owner must re-accept."* No code needed for the
    reset — the flip guard plus digest comparison already blocks re-enable without fresh consent.

### S4 — M3: prove the resolver hook actually runs

12. Add `tests/unit/test_identity_coop_hook.py`: patch `settings.identity_coop_enabled=True`, drive
    `IdentityResolver._save_identified` with a fake `AsyncSession` and a visitor/data pair that
    produces `wrote_graph is True`, assert `maybe_record_contribution` was invoked with the expected
    `(db, visitor, data, provider)`. Add the mirror case (`wrote_graph is False` → not invoked) and
    the flag-OFF case (flag False → not invoked even when `wrote_graph is True`). Fake session is
    acceptable for this decision half.
**File decision (SUP-F2) — settled once, applies to every S4/S5 item and every SG gate below:**
`tests/integration/test_identity_coop.py` **does not exist**. All new integration legs go **INTO the
existing `tests/integration/test_identity_coop_contribution.py`** (550 lines today, already
`pytestmark = pytest.mark.integration`, already holds the co-op fixtures these legs need). Every
earlier reference to `test_identity_coop.py` in this supplement is superseded by this line.
**Single narrow exception (SUP2-C2 split escape hatch):** if adding the 9 required legs pushes that
file past ~1000 lines, the remainder MAY go into a new `tests/integration/test_identity_coop_supplement.py`.
That is the ONLY permitted second file, and it costs nothing gate-wise — the `...` shorthand runs
over the `tests/integration` **directory**, so every `-k` selector still resolves; only SG-11 must
then name both files. Under ~1000 lines, keep everything in the one existing file.

13. Add integration test function **`test_end_to_end_accrual`** (SG-3) in
    `tests/integration/test_identity_coop_contribution.py`: both `identity_coop_enabled` and
    `site.contribution_enabled` ON, drive a real resolve through `_save_identified` against the real
    DB, assert exactly one `identity_contribution_events` row and one `identity_credit_ledger` ACCRUE
    row land, with the expected `site_id` and non-null `email_bidx`. This is the first end-to-end
    proof the hook mints anything.

**Test-count decision (SUP2-C2) — settled once, authoritative for S4/S5:** the **Test Gates
(Supplement) table's `-k` selectors are authoritative for test count and naming.** Nine (9) distinct
integration test functions are required — one per selector — because a `-k` selector that matches no
function silently selects 0 tests and the gate passes vacuously. The 9 required function names are:

| # | Test function | Gate |
|---|---|---|
| 1 | `test_end_to_end_accrual` | SG-3 |
| 2 | `test_site_delete_removes_coop` | SG-4 |
| 3 | `test_site_delete_retains_consent` | SG-5 |
| 4 | `test_erasure_window_race_blocked` | SG-6 |
| 5 | `test_erasure_window_race_control` | SG-6b |
| 6 | `test_enqueue_writes_tombstone` | SG-7 |
| 7 | `test_sweep_tombstone_idempotent` | SG-8 |
| 8 | `test_contribution_flip_gated_on_global_flag` | SG-9 |
| 9 | `test_contribution_optout_never_gated` | SG-10 |

Naming note: SG-6/SG-6b were renamed from `erasure_window_race` / `erasure_window_race_positive_control`
to `..._blocked` / `..._control` so neither `-k` selector substring-matches the other; each gate's
expected count is now exactly 1 passed. Every name above must be unique enough that its `-k` selects
exactly one function.

### S5 — H1/H2 regression coverage

**One test function per gate — see the SUP2-C2 table above. Do not merge two gates into one
function: a single function cannot substring-match two different `-k` selectors.**

14. **H1 — two separate functions** (item 14 previously described one; that was unsatisfiable):
14a. `test_site_delete_removes_coop` (SG-4): delete a site that has co-op rows; assert
     `identity_contribution_events` and `identity_credit_ledger` both have **0** rows for that
     `site_id`.
14b. `test_site_delete_retains_consent` (SG-5): same delete; assert the
     `identity_contribution_consent_acceptances` row **is still present** (so a future "cleanup" that
     deletes acceptances goes red — proves the second half of H1-D).
15. **H2 — four separate functions** (item 15 previously said "the H2 window-race integration test",
    singular, for four selectors):
15a. `test_erasure_window_race_blocked` (SG-6): both flags patched ON, `enqueue_erasure` for the
     email FIRST, then a full resolve through `_save_identified` **before any sweep run**; assert 0
     event rows and 0 ledger rows for that email.
15b. `test_erasure_window_race_control` (SG-6b): identical setup and resolve **without** the
     preceding `enqueue_erasure`; assert exactly 1 event row and exactly 1 ACCRUE ledger row. This is
     the positive control that makes 15a's zero non-vacuous.
15c. `test_enqueue_writes_tombstone` (SG-7): assert a `suppression_list` row with scope `erased`
     exists immediately after `enqueue_erasure` returns, sweep not yet run (assert via the
     `SuppressionEntry` ORM model).
15d. `test_sweep_tombstone_idempotent` (SG-8): run the sweep after enqueue; assert it raises nothing
     and leaves exactly 1 suppression row.
15e. `test_contribution_optout_never_gated` (SG-10): with the global flag OFF, PATCH
     `contribution_enabled=False`; assert **200** and the flag flips to False. **(SUP2-C2 — SG-10
     previously had no checklist item; the existing opt-out leg lives inside
     `test_flag_on_requires_acceptance` and is not selectable by SG-10's `-k`.)**
     Note `test_contribution_flip_gated_on_global_flag` (SG-9) is created by item 9a.

### S6 — L1: correct the bookkeeping

16. Edit `harness/adversarial-validation.json`: rewrite ADV-1 and ADV-2 non-vacuity claims to cite
    the **real** load-bearing signals — the `wrote is False` / `wrote is True` identity assertions
    against `_upsert_beam_identity`'s `-> bool` return (genuinely red against the prior `None`-returning
    code), and the Hybrid integration legs. Remove the claim that armed mocks on `record_contribution`
    or `session.added` inspection prove anything: the mocks are unreachable from the tested call path
    and `session.added` cannot observe `execute()`-path writes.
17. In the same file, mark the F14 third leg `"status": "vacuous-and-retired"` with a one-line reason.

### S7 — R1: record the human verdict

18. Edit `harness/review-decision.json`: set `"decision": "rejected"`,
    `"reviewer": "Julley Thai (via orchestrator session 16-08-26)"`, `"reviewedAt": "2026-08-16"`.
    Replace `decisionEnumNote` with a note that the rejection is a real human verdict (the validator
    now passes on a valid enum value), that the rejection is scoped to this supplement's 6 defects,
    and that re-approval is expected once every gate in the table below is green.
19. Add a `blockingFindings` entry for each of H1, H2, M2, M3 referencing this supplement's section
    IDs. Do **not** self-approve — the `decision` field stays `rejected` until a human re-reviews.

---

## Blast Radius (Supplement)

| File | Fix | Diff budget | Notes |
|---|---|---|---|
| `apps/api/routers/sites.py` | S1 (2 table names + comment), S3 (4-line guard) | ≤ 12 touched lines | ⚠️ **carries UNCOMMITTED edits from a concurrent site-analysis workstream** — see hazard below |
| `apps/api/services/graph_erasure.py` | S2 (guarded tombstone call inside `db.begin_nested()` savepoint + except + docstring + audit-lookup comment) | ≤ 18 touched lines (~11 expected **with** the savepoint — SUP2-F1 costs no extra budget) | Existing `_tombstone_stmt` reused verbatim |
| `tests/unit/test_identity_coop_hook.py` | S4 (new file) | new, ~90 lines | 3 cases |
| `tests/integration/test_identity_coop_contribution.py` | S4, S5, S3 item 9a (**9 new test functions** + 1 whole-function monkeypatch on an existing test) | **≤ 480 added lines** (raised from ≤190 per SUP2-C2: 9 DB-integration tests × ~50 lines each ≈ 450, matching the file's existing 550 lines / 11 tests average) | **existing file, additive** — path per SUP-F2. **Split escape hatch:** if this file exceeds ~1000 lines, the remaining legs MAY go into a second file `tests/integration/test_identity_coop_supplement.py`; if that happens, the `...` gate shorthand (defined in Test Gates below) already runs over `tests/integration` as a directory so every `-k` gate still resolves, and SG-11 must name **both** files. |
| `tests/unit/test_graph_erasure.py` | S2 item 5b (SG-15 tombstone-failure leg) | ≤ 30 added lines | existing file, additive |
| `harness/adversarial-validation.json` | S6 | ≤ 25 touched lines | bookkeeping only |
| `harness/review-decision.json` | S7 | ≤ 30 touched lines | bookkeeping only |
| `process/features/visitors-identity/backlog/coop-credit-reversal-semantics_NOTE_16-08-26.md` | S2 item 8 | new | |
| `.../identity-coop_07-08-26/coop-terms-repin_RUNBOOK_16-08-26.md` | S3 item 11 | new | |

| `apps/api/models/suppression.py` | S2 item 6a (docstring only — **both** falsified sentences) | **≤ 8 touched lines** (raised from ≤3 per SUP2-C3) | **comment/docstring only — no column, no schema change** |

**Not touched:** `apps/api/models/*` **except the `suppression.py` docstring above** (no schema change anywhere), `apps/api/services/identity_coop.py`,
`apps/api/services/identity_resolver.py`, `apps/api/config.py`, any Alembic migration.

### ⚠️ Concurrent-workstream hazard (read before editing)

`apps/api/routers/sites.py` and `apps/api/models/site.py` currently carry **UNCOMMITTED** edits from
a concurrent site-analysis workstream. The execute agent MUST:

- make every edit **purely additive** (append 2 strings to an existing tuple; insert one new `if`
  branch) — never rewrite or reformat surrounding blocks;
- **never** run `git checkout`, `git stash`, `git stash pop`, `git restore`, or any rebase on these
  files (a prior session lost work exactly this way — see the concurrent-session-rebase memory note);
- verify with `git diff apps/api/routers/sites.py` after editing that the concurrent workstream's
  hunks are still present and unmodified, and record that verification in the phase report;
- treat any disappearance of those hunks as an immediate STOP + report, not something to fix forward.

---

## Constraints (Supplement)

1. **All flags stay default OFF.** `identity_coop_enabled` and `site.contribution_enabled` defaults
   are unchanged. M2's fix makes the opt-in *harder*, never easier.
2. **No schema change.** Neither chosen fix shape requires one. If execution discovers one is
   unavoidable, STOP and re-plan — do not improvise a migration. Should a migration ever become
   necessary: re-derive the live head with `alembic -c apps/api/alembic.ini heads` (believed
   `d7e2b4c81f93`, but re-derive — heads move) and chain on the derived value, never the written one.
3. **`DATABASE_URL` must be pinned to `localhost:5433` for every alembic/DB command.** The repo
   `.env` points at Supabase PROD and `migrations/env.py` has no local-host guard.
4. **No self-approval.** `harness/review-decision.json` `decision` stays `rejected`. Only a human may
   change it.
5. **Scope fence:** this supplement fixes the 6 listed defects. It does not re-open D-A..D-E, does
   not touch Phase 2/3 plans, and does not add co-op tables to `ERASURE_TARGETS`.

---

## Test Gates (Supplement)

**Path note (SUP-F2 + SUP2-C2):** every `...` shorthand below expands to
`.venv/bin/python3.11 -m pytest tests/integration -q` — the **directory**, so each `-k` selector
resolves whether or not the split escape hatch in Blast Radius is used. The 9 selectors below are
authoritative for test naming; every one MUST select **exactly one** function (a selector matching 0
functions passes vacuously).

| # | Gate / Scenario | Strategy | Command | Expected | Proves |
|---|---|---|---|---|---|
| SG-1 | Unit lane green, no regression | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -q` | 0 failed; count ≥ prior baseline + new hook tests | no regression from S1-S4 |
| SG-2 | Hook fires when flag ON and graph write happened | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_identity_coop_hook.py -q` | 3 passed | M3 (decision half) |
| SG-3 | End-to-end accrual row lands in a real DB | Hybrid (needs PG :5433) | `... -k end_to_end_accrual` | 1 passed; exactly 1 event row + 1 ACCRUE ledger row | M3 (DB half) |
| SG-4 | Site delete removes co-op events + ledger | Hybrid | `... -k site_delete_removes_coop` | passed; both tables 0 rows for the deleted `site_id` | H1 |
| SG-5 | Site delete RETAINS the consent acceptance row | Hybrid | `... -k site_delete_retains_consent` | passed; acceptance row still present | H1-D (guards against a future over-delete) |
| SG-6 | **Window race (non-vacuous)** — test fn `test_erasure_window_race_blocked`: with **BOTH** `settings.identity_coop_enabled` **and** `site.contribution_enabled` patched **ON**, enqueue erasure for the email FIRST, then drive a full resolve through `_save_identified` **before any sweep run** | Hybrid | `... -k erasure_window_race_blocked` | passed; **0** `identity_contribution_events` rows and **0** `identity_credit_ledger` rows for that email | H2 (the core fix) |
| SG-6b | **Positive control for SG-6** — test fn `test_erasure_window_race_control` — identical setup and identical resolve, but **WITHOUT** the preceding `enqueue_erasure` | Hybrid | `... -k erasure_window_race_control` | passed; **exactly 1** `identity_contribution_events` row **and exactly 1** ACCRUE ledger row | proves SG-6's zero is caused by the S2 fix, not by an inert hook (closes SUP-C2 vacuity) |
| SG-7 | Tombstone is written at enqueue, not at sweep | Hybrid | `... -k enqueue_writes_tombstone` | passed; a **`suppression_list`** row (table name per `models/suppression.py:31`; assert via the `SuppressionEntry` ORM model) with scope `erased` exists immediately after `enqueue_erasure` returns, sweep not yet run | H2 mechanism (non-vacuity for SG-6) |
| SG-8 | Sweep tombstone write is still idempotent | Hybrid | `... -k sweep_tombstone_idempotent` | passed; running the sweep after enqueue raises nothing and leaves exactly 1 suppression row | H2 no-regression on `_process_claimed` |
| SG-9 | `contribution_enabled=True` rejected when global flag OFF | Hybrid (needs PG :5433 — re-tiered per SUP-C3; `PATCH /sites` coverage lives only in the integration-marked file) | `... -k contribution_flip_gated_on_global_flag` | 422 with the new detail string; `site.contribution_enabled` unchanged | M2 |
| SG-10 | `contribution_enabled=False` still ungated | Hybrid (needs PG :5433 — re-tiered per SUP-C3) | `... -k contribution_optout_never_gated` | 200 with global flag OFF; flag flips to False | M2 (opt-out never blocked) |
| SG-11 | Coop integration lane green | Hybrid | `.venv/bin/python3.11 -m pytest tests/integration/test_identity_coop_contribution.py -q` (**if the split escape hatch was used, name both files**: `... test_identity_coop_contribution.py tests/integration/test_identity_coop_supplement.py -q`) | 0 failed (requires S3 item 9a — the monkeypatch + new 422 leg — or `test_flag_on_requires_acceptance` goes red) | H1+H2+M3 combined |
| SG-12 | Concurrent workstream hunks intact | Agent-Probe | `git diff apps/api/routers/sites.py` | site-analysis hunks present and unmodified alongside the additive co-op edits | concurrent-edit hazard |
| SG-13 | Evidence-pack bookkeeping is honest | Agent-Probe | read `harness/adversarial-validation.json` | ADV-1/ADV-2 cite `wrote is False/True` + integration legs only; F14 third leg marked vacuous-and-retired | L1 |
| SG-14 | Review verdict recorded faithfully | Agent-Probe | read `harness/review-decision.json` | `decision: "rejected"`, reviewer + reviewedAt set, no self-approval | R1 |
| SG-15 | **Tombstone failure never loses the erasure request — and the SAVEPOINT is entered** | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_graph_erasure.py -q -k tombstone_write_failure` | passed; using the fake-savepoint pattern (`tests/unit/test_site_limit.py:100-114`): `db.begin_nested` **was called**, the tombstone execute raised, the `ErasureRequest` was still added and `db.commit()` awaited afterwards, and nothing escaped | SUP-C5 + **SUP2-F1** — the `begin_nested` assertion is what makes this gate RED against a bare-`try/except` implementation; without it the gate is vacuous |
| SG-16 | *(optional, item 5c)* Real DB-level tombstone failure leaves the `ErasureRequest` intact | Hybrid (needs PG :5433) | forced statement failure inside the tombstone statement, then assert the `ErasureRequest` row exists | SUP2-F1 high-risk-class minimum. **If not implemented, this is an accepted known-gap** — SG-15 proves the savepoint is entered, not that Postgres honours it |

**Known gap (accepted):** no gate proves the H2 fix under real concurrency (two processes racing
enqueue and resolve). SG-6 proves the sequential window, which is the actual reported defect; a true
concurrency probe needs multi-process orchestration outside this supplement's scope. Recorded, not
silently dropped.

---

## Verification Evidence (Supplement)

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| SG-4, SG-5 | Hybrid | H1 — deleting a site does not leave spendable credit behind, and does not destroy the consent audit trail |
| SG-6, SG-6b, SG-7, SG-8 | Hybrid | H2 — "no permanent record of an erased person" holds across the enqueue→sweep window; SG-6b is the positive control that makes SG-6's zero non-vacuous |
| SG-15 | Fully-Automated | SUP-C5 + SUP2-F1 — the tombstone write is savepoint-scoped, so a tombstone failure degrades to today's behaviour and never discards the `ErasureRequest` row |
| SG-16 (optional) | Hybrid | SUP2-F1 — the savepoint holds against a real DB-level failure (known-gap if not implemented) |
| SG-9, SG-10 | Hybrid (re-tiered, SUP-C3) | M2 — co-op opt-in is unreachable while the deployment flag is OFF; opt-out is never gated |
| SG-2, SG-3 | Fully-Automated + Hybrid | M3 — the resolver hook is executed, not merely wired |
| SG-1, SG-11 | Fully-Automated + Hybrid | no regression across unit and co-op integration lanes |
| SG-12 | Agent-Probe | concurrent site-analysis workstream survives this edit |
| SG-13, SG-14 | Agent-Probe | L1 + R1 — evidence-pack claims and the human verdict are recorded honestly |

---

## Test Infra Improvement Notes (Supplement)

- The unit lane cannot assert DB-enforced semantics (partial unique index, `ON CONFLICT`), so the
  hook's decision half and its persistence half are proven in different lanes. Disclosed, not hidden.
- No harness exists for multi-process concurrency probes; the H2 concurrency gap above is a direct
  consequence. Candidate future investment.
- The unit lane cannot abort a real transaction, so SG-15 can only prove the savepoint is *entered*
  (via the fake-savepoint pattern), not that Postgres honours it. A cheap statement-level
  failure-injection helper for the integration lane would close that gap (SG-16). **(SUP2-F1.)**
- SG-9/SG-10 were re-tiered Fully-Automated → Hybrid (SUP-C3): `PATCH /api/v1/sites/{site_id}` has no
  unit-lane harness, so router-contract gates cannot run without PG. A fake-session unit harness for
  `update_site` is a candidate future investment that would let contract guards run in the fast lane.
- `tests/integration` remains sensitive to the known conftest DB/Redis isolation gap — if SG-3/4/5/6
  flake, bisect in a clean worktree before attributing the failure to this supplement.

---

## Resume and Execution Handoff (Supplement)

1. **Selected plan file:** `process/features/visitors-identity/active/identity-coop_07-08-26/phase-1-ledger-substrate_PLAN_07-08-26.md` (this file; execute the `## Post-Audit Fix Supplement (16-08-26)` section only).
2. **Last completed step:** Phase 1 EXECUTE complete; evidence pack **REJECTED** by human review 16-08-26. This supplement is the fix list.
3. **Validate-contract status:** `## Validate Contract (Supplement — S1–S7) — PVL cycle 2` below returned `Gate: BLOCKED` on 16-08-26 (SUP2-F1 + SUP2-C1/C2/C3). **PVL-supplement cycle 3 applied 16-08-26** — all 4 gaps addressed: SUP2-F1 (item 5a rewritten to mandate `db.begin_nested()`; 5b/SG-15 strengthened with the fake-savepoint assertion; optional 5c/SG-16 Hybrid leg), SUP2-C1 (item 9a monkeypatches the whole test function; SG-9 gets its own function), SUP2-C2 (9 named integration test functions enumerated, SG-10 given item 15e, item 14 split into 14a/14b, item 15 split into 15a-15e, SG-6/SG-6b renamed to non-overlapping selectors, integration budget ≤190 → ≤480 with a split escape hatch), SUP2-C3 (item 6a corrects both falsified sentences; `suppression.py` budget ≤3 → ≤8). Inner PVL must now **re-run from V1** against this updated supplement before EXECUTE. The original `2026-08-07 (outer-pvl)` contract still covers original Phase 1 scope only.
4. **Supporting context loaded:** `process/context/all-context.md`; `apps/api/routers/sites.py`; `apps/api/services/graph_erasure.py`; `apps/api/models/erasure_request.py`; `apps/api/services/identity_coop.py`; `apps/api/models/identity_coop.py`; `apps/api/services/identity_resolver.py`; `harness/review-decision.json`.
5. **Next step for a fresh agent:** route to VALIDATE for this supplement's scope, then EXECUTE S1→S7 in order. Read the concurrent-workstream hazard above **before** touching `apps/api/routers/sites.py`.


---

## Validate Contract (Supplement — S1–S7) — PVL cycle 3

Status: CONDITIONAL
Date: 16-08-26
date: 2026-08-16
generated-by: inner-pvl: phase-1-supplement
supersedes: 2026-08-16 (inner-pvl: phase-1-supplement, cycle 2) — cycle 3 re-validated the
twice-repaired supplement from V1 against the live working tree and has current evidence. Scope is
unchanged: `## Post-Audit Fix Supplement (16-08-26)` (checklist S1–S7, gates SG-1…SG-16) ONLY. The
`2026-08-07 (outer-pvl)` contract above remains authoritative for original Phase 1 scope (EXECUTED +
EVL green + re-audited green 16-08-26) and is NOT overwritten.

Parallel strategy: sequential (single-context pass)
Rationale: 7-signal score **4/7** — S2 (GDPR-erasure + credit-accrual surface), S4 (phase-program
membership), S6 (high-risk class), S7 (10-file blast radius). Score 4 → HIGH → the from-scratch
recommendation is workflow or agent-team. Deviation stated explicitly: this agent has no Agent tool
grant, so Layer 1 (4 dimensions) and Layer 2 (8 supplement sections) ran as ONE sequential pass.
Every finding below comes from a live command or a direct read of the working tree.

**Contract-staleness note (closes the cycle-2 hazard):** the cycle-2 contract's own gate table was
stale after the SG-6/SG-6b rename and the `...` shorthand redefinition. That contract is **replaced
in full** by this one, and every gate below was **re-derived from the plan's `## Test Gates
(Supplement)` table**, which is authoritative.

### Cycle-2 closure verdict (the reason this pass exists)

| Cycle-2 gap | Closed? | Evidence (live source walk, 16-08-26) |
|---|---|---|
| **SUP2-F1** — bare `try/except` cannot preserve the `ErasureRequest`; SG-15 vacuous | **YES — mechanism verified in the pinned SQLAlchemy source** | Item 5a now mandates `async with db.begin_nested():`. Walked `sqlalchemy==2.0.35` (`.venv/.../orm/session.py:1084-1089`): `SessionTransaction.__init__` runs `self.session.flush()` whenever the origin is NOT `BEGIN`/`AUTOBEGIN` — a SAVEPOINT (`BEGIN_NESTED`) therefore **flushes pending state BEFORE the SAVEPOINT is emitted**. So `db.add(row)`'s `ErasureRequest` INSERT lands in the outer transaction *ahead of* the savepoint, and `ROLLBACK TO SAVEPOINT` cannot discard it; the outer transaction stays usable and `await db.commit()` proceeds. The "degrades to exactly today's behaviour" claim is now **true as written**, and only with the savepoint. Repo idiom citations verified exact: `services/identity_coop.py:175` and `routers/sites.py:206` are both `async with db.begin_nested():`. Autoflush premise verified: `async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)` (`models/database.py:78`) leaves `autoflush=True`, so the bare-`try/except` failure chain item 5a documents is real. |
| **SUP2-F1 (b)** — SG-15 must be able to fail against a bare `try/except` | **YES** | The fake-savepoint pattern is real and reusable: `tests/unit/test_site_limit.py:99-114` defines a no-op async CM `_Savepoint` and installs it via `db.begin_nested = Mock(return_value=_Savepoint())` at :114; a second, richer idiom exists at `tests/unit/test_identity_coop.py:105` (`def begin_nested(self)`). Distinguishing power walked: against the bare-`try/except` implementation `db.begin_nested` is **never called**, so SG-15's mandated `assert db.begin_nested was called` goes RED; against the savepoint implementation the no-op CM lets the patched raise propagate to the `except`, the warning is logged, and `db.commit()` is awaited — GREEN. The two implementations are genuinely separable by the assertion set item 5b lists. Budget: the required shape is 7 code lines + item 6's docstring line + item 6a's audit comment ≈ 9-11 touched lines vs the ≤18 `graph_erasure.py` budget — **achievable**. |
| **SUP2-C1** — "200-path steps only" monkeypatch voids 3 digest legs | **YES** | Guard position re-verified: `routers/sites.py:417` `if body.contribution_enabled is not None:` → `:418` `if body.contribution_enabled:` → `:419` `tv = body.terms_version` → digest 422 at `:421-434` → `record_consent_acceptance` `:435-437` → flip at `:438`. Item 9's insertion point ("inside `if body.contribution_enabled:`, before the terms-digest comparison") is exact. With the flag patched True for the **whole** `test_flag_on_requires_acceptance`, all five legs keep their original meaning: step 1 (`:470`, no `terms_version`) → digest 422; step 2 (`:476`, the named vacuous-guard case) → digest 422; step 3 (`:483`, wrong 64-hex) → digest 422; step 4 (`:491`, pinned) → 200 + 1 acceptance row; step 5 (`:516`, opt-out) → 200, ungated either way. No cross-test damage: the `assert settings.identity_coop_enabled is False` at `:93` lives inside a **different** function (`test_flag_off_produces_zero_contributions`, `:76-122`), and a function-scoped `monkeypatch` restores on teardown. |
| **SUP2-C1 (b)** — new SG-9 contract consistent with the guard position | **YES** | SG-9's test (`test_contribution_flip_gated_on_global_flag`) asserts **422 with a *valid* current digest while the global flag is OFF**. Because the new guard sits strictly *before* the digest comparison, a valid digest removes the digest branch as an alternative explanation — the 422 can only come from the new global-flag guard. Non-vacuous, and it is the only remaining coverage of the flag-OFF contract once the flag is patched True for the whole neighbouring function. |
| **SUP2-C2** — selector/checklist/budget mismatch | **YES — all four sub-parts verified** | (i) **Selector→item coverage:** every `-k` in the authoritative table has exactly one checklist item — SG-3→13, SG-4→14a, SG-5→14b, SG-6→15a, SG-6b→15b, SG-7→15c, SG-8→15d, SG-9→item 9a, SG-10→15e (SG-10 was itemless in cycle 2; item 15e now exists). (ii) **Collision sweep run live** — `grep -rn "def test_.*<selector>" tests/` returns **0 existing matches for all nine** selectors, so each selects exactly one *new* function; the renamed `erasure_window_race_blocked` / `erasure_window_race_control` are mutually non-substring. (iii) **Budget arithmetic sane:** the existing file is 550 lines with 10 test functions and ~75 lines of header/fixtures ⇒ ~47 body-lines per DB-integration test; 9 × 47 ≈ 430 against the ≤480 budget. (iv) **Both file outcomes resolve:** the `...` shorthand now expands to `pytest tests/integration -q` (the **directory**), so every `-k` gate resolves whether the legs stay in `test_identity_coop_contribution.py` or the split hatch to `test_identity_coop_supplement.py` fires; SG-11 is the only gate naming files literally and it already carries the "name both files" clause. |
| **SUP2-C3** — docstring correction incomplete + budget short | **YES** | `models/suppression.py:23-28` re-read verbatim; item 6a's quoted "today it reads" text matches the source **exactly**, and the replacement corrects **both** falsified claims: the *writer* ("Written at enqueue time by `enqueue_erasure` … the sweep's later write is an idempotent no-op via `on_conflict_do_nothing`") and the *meaning* ("it records that an erasure was **requested** … the shared-graph rows are hard-deleted by the sweep"). Both are accurate to post-S2 semantics — the enqueue-time write is what S2 adds, and `_process_claimed`'s later write (`graph_erasure.py:370`) is a no-op via `on_conflict_do_nothing(index_elements=["email_hash","scope"])` at `:327`, matching the unique index `uq_suppression_hash_scope` (`suppression.py:33`). Length: the replacement is ~60 words ⇒ ~6-7 wrapped docstring lines against the raised **≤8** budget, replacing the 5 source lines 24-28. Fits. The companion audit-lookup comment lands at `graph_erasure.py:563-575` (`erased = False` … `scalar_one_or_none() is not None`), verified present. |

### Cross-reference / staleness sweep (V3 new-gap pass)

- **No residual bad file targets.** The only occurrences of `test_identity_coop.py` in the supplement are (a) the paragraph declaring the *integration* file nonexistent and superseding earlier references, and (b) a citation of the genuinely-existing **unit** file `tests/unit/test_identity_coop.py:105`. Different files; not a contradiction.
- **SUP-F2 vs the split escape hatch — no contradiction.** SUP-F2 says "all new integration legs go into the existing file"; the hatch is introduced in the same paragraph as an explicitly-labelled "single narrow exception", is repeated identically in the Blast Radius row, and is gate-neutral because the shorthand runs the directory. Both statements are reconciled in place, not left in tension.
- **Renames fully propagated.** `erasure_window_race_positive_control` survives only inside the explanatory naming note; no gate, checklist item, or blast-radius row still uses the old names. The superseded `≤190` figure likewise appears only inside the "raised from ≤190" audit trail.
- **Numbering is consistent.** Items 1-19 with sub-items 5a/5b/5c, 6a, 9a, 14a/14b, 15a-15e; every sub-item is referenced by the section that owns it, and S5's header now carries the "one function per gate" rule that item 14/15's splits implement.
- **All file anchors re-verified live** against the dirty working tree: `routers/sites.py` delete tuple ends `"ad_connections"` at `:340`, `deleted[table] = r.rowcount` at `:346`, `return Response(status_code=204)` at `:379`; `graph_erasure.enqueue_erasure` at `:182-224` with `db.add(row)` at `:214` immediately preceding `await db.commit()` at `:215`; `_tombstone_stmt` at `:308` taking a `list[str]` (and `bidx` **is** a list); the co-op table names in `models/identity_coop.py` are `identity_contribution_events` (`:77`), `identity_credit_ledger` (`:127`), `identity_contribution_consent_acceptances` (`:172`) — exactly as S1 items 1-2 name them.
- **Plan-artifact validator:** `validate-plan-artifact.mjs` → **0 failures** (3 pre-existing legacy-shape warnings only).
- **Concurrent-workstream hazard still live and still non-overlapping.** `git status` confirms `apps/api/routers/sites.py` and `apps/api/models/site.py` carry uncommitted edits from the site-analysis workstream. SG-12's baseline is unchanged; the purely-additive edit rule and the never-`git-checkout`/`stash` rule remain mandatory.

### Prior confirmations carried forward (NOT re-derived — no cycle-3 edit touched their premises)

| Property | Source of truth | Why not re-derived |
|---|---|---|
| **H2-D fail-safe direction** — every `is_email_suppressed*` caller *withholds* an action, and `("erased","do_not_process")` never reaches the `do_not_email`/`do_not_sell` callers (wildcarding is `"all"` only) | cycle-1 + cycle-2 contracts (11 call sites walked) | Cycle 3 changed only *when* the tombstone is written mechanically (savepoint), not *which* scopes it uses |
| **Conflict target / `_process_claimed` untouched** — Boundary-2 ordering and `tests/unit/test_graph_erasure.py:355-401` unaffected | cycle-2 contract | Item 7 is unchanged this cycle |
| **H1-D independence** — an inherited acceptance row is inert (`Site.contribution_enabled` is `default=False, server_default="false"`, `SiteCreate` does not expose it, `routers/sites.py:438` is the only write path) | cycle-1 + cycle-2 contracts | Cycle 3 did not touch S1 |
| **M2 non-bypassability** — no other write path can flip `contribution_enabled` True | cycle-2 contract | Re-confirmed incidentally: `:438` is still the single assignment |
| **SG-6/SG-6b non-vacuity mechanism** — `GRAPH_WRITE_BLOCKING_SCOPES == _TOMBSTONE_SCOPES`, blocked `_upsert_beam_identity` returns `False`, hook at `identity_resolver.py:1310` never fires; without S2 the write succeeds and mints 1 event + 1 ACCRUE, so SG-6's zero goes RED | cycle-2 contract §"SG-6/SG-6b non-vacuity proof" | The cycle-3 edit renamed the `-k` selectors only. **A test-function rename cannot change the code path being exercised**, so the proof transfers verbatim; only the selector strings changed, and those were re-verified collision-free above |

### Net Gate Derivation

**Layer 1 dimensions**

| Layer 1 dimensions | Status |
|---|---|
| Infra fit | PASS |
| Test coverage | CONCERN |
| Breaking changes | PASS |
| Security surface | PASS |

**Layer 2 sections**

| Layer 2 sections | Status |
|---|---|
| S1 — H1 site delete cascade | PASS |
| S2 — H2 close the enqueue→sweep window | PASS (SUP2-F1 closed — savepoint shape verified against SQLAlchemy 2.0.35 source; SUP2-C3 closed) |
| S3 — M2 gate the contribution opt-in flip | PASS (SUP2-C1 closed — all five legs keep their meaning) |
| S4 — M3 prove the resolver hook runs | PASS |
| S5 — H1/H2 regression coverage | PASS (SUP2-C2 closed — 9 selectors, 9 items, 0 collisions) |
| S6 — L1 correct the bookkeeping | PASS |
| S7 — R1 record the human verdict | PASS |
| Test Gates table SG-1…SG-16 | CONCERN (N-A: SG-15's unit function name is unspecified; N-B: the `test_graph_erasure.py` ≤30-line budget is optimistic) |

**Totals: 0 FAILs / 2 CONCERNs / 7 PASSes** (all 4 cycle-2 gaps confirmed closed and source-verified)

**→ Net Gate: CONDITIONAL**

Net-gate vacuous-green check (Step A1): every developed behavior in this supplement has at least one
Fully-Automated or Hybrid gate that can fail when the behavior is absent — H1 (SG-4/SG-5), H2 window
(SG-6 with SG-6b as positive control), H2 mechanism (SG-7/SG-8), the tombstone fail-safe (SG-15,
now non-vacuous via the `begin_nested` assertion), M2 (SG-9/SG-10), M3 (SG-2/SG-3). **No behavior
rests on Known-Gap alone.** The two named residuals (SG-16 Postgres-honours-the-savepoint, and
multi-process concurrency) are carried as named residuals with written justification, gap-resolution
D — not as the silent reason anything passes.

### CONCERNs (residual, cycle 3 — all closable by execute-agent instruction; none require a plan edit)

**N-A — SG-15's unit test function name is not specified anywhere, so its `-k` currently selects
zero functions. (CONCERN, LOW — loud failure mode.)**

SUP2-C2's fix enumerated the nine *integration* function names but left SG-15's *unit* function
unnamed: item 5b says only "add the unit gate in `tests/unit/test_graph_erasure.py`", while the gate
runs `-k tombstone_write_failure`. Verified live: `pytest tests/unit/test_graph_erasure.py -q -k
tombstone_write_failure` today gives `27 deselected`, **exit code 5**. Mitigating factor (and why
this is not a FAIL): the failure mode is *loud*, not silent — exit 5 is non-zero, so a
name mismatch cannot be mistaken for a green gate by an exit-code check. Closed by instruction E-S1.

**N-B — the `tests/unit/test_graph_erasure.py` ≤30-added-line budget is optimistic (~35-42
realistic). (CONCERN, LOW — advisory budget, no STOP rule attached.)**

`enqueue_erasure` has **no existing unit harness** (grep: the only references in that file are
`inspect.getsource` code-shape assertions at `:485` and `:510`), and the file's shared
`_scalar_result` helper (`:47-51`) exposes `scalar_one_or_none`/`scalar` but **not** `.scalars().all()`
— which `_collect_match_keys` requires at `graph_erasure.py:155`. So SG-15's test must add: a
`_Savepoint` no-op CM (~5 lines), a fake session whose `_execute` discriminates the tombstone
statement by SQL text *and* returns a non-empty email list for the `visitor_emails` select (~14
lines), and the test body (~14 lines). The supplement carries no budget-breach STOP rule (the only
STOP rules are the concurrent-hazard and the no-migration rule), so an overshoot is a bookkeeping
correction, not a blocker. Closed by instruction E-S2.

*Non-vacuity note that protects N-B:* if the fake returns an empty `bidx`, `enqueue_erasure` skips
the tombstone branch entirely and `db.begin_nested` is never called — SG-15's own mandated assertion
then goes RED rather than passing vacuously. The assertion set is self-protecting.

### Informational notes (no action required, not counted toward the gate)

- **N-C (rationale imprecision):** the plan asserts "a `-k` selector that matches no function silently
  selects 0 tests and the gate passes vacuously". Measured: pytest returns **exit code 5** on total
  deselection, so it is loud to an exit-code check (though a human skimming `-q` output sees no
  "failed" line). The enumeration fix is correct and worth keeping regardless; only the stated
  rationale is stronger than the mechanism warrants.
- **N-D (arithmetic nit):** the Blast Radius row cites "550 lines / 11 tests"; the file actually has
  **10** test functions. Using body-lines-per-test (~47) rather than raw file lines, the ≤480 budget
  still holds with ~50 lines of margin. Conclusion unchanged.
- **N-E (doc-sync, outside this agent's write scope):** `## Resume and Execution Handoff (Supplement)`
  item 3 still describes cycle 2's `Gate: BLOCKED` as the current state. It is now superseded by this
  contract. Orchestrator or plan-agent should refresh that line; no gate depends on it.

### Dimension findings

- **Infra fit: PASS** — every anchor re-verified live against the CURRENT dirty working tree (see the
  cross-reference sweep above). The savepoint shape is not merely idiomatic but **mechanically
  correct on the pinned stack**, proven by reading `sqlalchemy/orm/session.py:1084-1089` rather than
  by analogy. Diff budgets: `sites.py` ~10-11 vs ≤12 (tight, achievable), `graph_erasure.py` ~9-11 vs
  ≤18 **with** the savepoint, `suppression.py` ~7 vs the raised ≤8, integration ~430 vs ≤480. Only
  `test_graph_erasure.py`'s ≤30 is optimistic (N-B). No schema change is required by any fix shape,
  so Constraint 2 holds. Plan-artifact validator: 0 failures.
- **Test coverage: CONCERN** — the SUP2-C2 class is genuinely closed for the integration lane (9
  selectors ↔ 9 checklist items, 0 collisions verified live, both file outcomes resolve), and SG-15
  is now non-vacuous by construction. The residual is that the same "name the function behind the
  selector" discipline was not applied to SG-15 itself (N-A), plus the N-B budget. Independently
  correct: SG-2's "3 passed" matches item 12's three cases; SG-6b remains a true positive control;
  the multi-process concurrency known-gap is correctly named rather than silently dropped; SG-16 is
  correctly declared optional-with-known-gap rather than assumed.
- **Breaking changes: PASS** — SUP2-C1's closure removes the last contract hazard: with the
  whole-function monkeypatch, `test_flag_on_requires_acceptance` keeps all five legs meaningful while
  the new 422 contract gets its own dedicated function (SG-9), so SG-1 and SG-11 are jointly
  satisfiable. Everything else stays contract-safe: S1 appends to an internal tuple and item 3
  forbids adding a 204 body; S2 adds a write inside an existing transaction with no signature change;
  item 7 leaves `_process_claimed` untouched, so the module's Boundary-2 contract and
  `tests/unit/test_graph_erasure.py:355-401` are unaffected. **Boundary 1** (`enqueue_erasure` commits
  its own insert so the queued request survives a partially-failed caller deletion) is now
  *preserved* by the prescribed shape — the property cycle 2 found broken.
- **Security surface: PASS** — the supplement's compliance fail-safe now holds as written on the GDPR
  erasure path, and the plan's claim about it is true rather than aspirational. Carried forward
  un-re-derived (premises untouched): H2-D's fail-safe direction across all eleven
  `is_email_suppressed*` call sites; H1-D's inertness; M2's non-bypassability; `verify_site_access`
  firing 404 first for a foreign site. The scope fence holds — no schema change, `ERASURE_TARGETS`
  untouched, all flags default OFF, and `harness/review-decision.json` stays `rejected` (no
  self-approval).

### Execute-agent instructions

| # | Instruction | Trigger condition |
|---|---|---|
| E-S1 | **Name SG-15's unit test so its selector matches exactly one function.** Use `test_tombstone_write_failure_preserves_erasure_request` (contains the `tombstone_write_failure` substring SG-15's `-k` requires). Before reporting SG-15 green, confirm the run reports `1 passed`, not `N deselected` — an unmatched `-k` exits 5 with zero tests run. (Closes N-A.) | S2 item 5b |
| E-S2 | **The `tests/unit/test_graph_erasure.py` ≤30-line budget may be exceeded up to ~45 added lines; record the actual figure in the phase report instead of reshaping the test to fit.** The overshoot is structural: `_scalar_result` (`:47-51`) has no `.scalars().all()`, which `_collect_match_keys` needs at `graph_erasure.py:155`, and no fake session covers `enqueue_erasure`. Do NOT weaken any of SG-15's four assertions to save lines. (Closes N-B.) | S2 item 5b |
| E-S3 | **Use the function-scoped `monkeypatch` fixture — not a bare `settings.identity_coop_enabled = True` `setattr`** — for item 9a's whole-function patch. `monkeypatch` restores on teardown; a bare setattr leaks the flag ON into `test_contribution_flip_gated_on_global_flag` (SG-9) and `test_contribution_optout_never_gated` (SG-10), both of which require the global flag **OFF**, silently inverting them. Item 9a's parenthetical offers both; only the fixture form is safe here. | S3 item 9a |
| E-S4 | **The savepoint in item 5a is load-bearing and must not be "simplified".** `async with db.begin_nested():` is what flushes the `ErasureRequest` INSERT *ahead of* the SAVEPOINT (SQLAlchemy 2.0.35, `orm/session.py:1084-1089`), so a savepoint rollback cannot discard it. Reverting to a bare `try/except` re-opens SUP2-F1 (false compliance receipt / permanent match-key loss). If a reviewer asks for the simpler form, STOP and cite this line. | S2 item 5a |
| E-S5 | **Re-run the collision sweep before writing tests if the tree has moved.** `grep -rn "def test_.*<selector>" tests/` must return 0 for each of the 9 selectors before you add the functions, and exactly 1 afterwards. Record the post-write counts in the phase report. | S4/S5 entry |
| E-S6 | **Concurrent-workstream hazard is still live.** `apps/api/routers/sites.py` and `apps/api/models/site.py` carry uncommitted third-party edits. Every S1/S3 edit must be purely additive; never run `git checkout`/`stash`/`stash pop`/`restore`/rebase on these files; verify with `git diff apps/api/routers/sites.py` afterwards and record the verification (SG-12). | S1 / S3 entry |
| E-S7 | **Pin `DATABASE_URL=postgresql+asyncpg://…@localhost:5433/…` for every Hybrid gate and any DB command.** The repo `.env` points at Supabase PROD and `migrations/env.py` has no local-host guard. | Any Hybrid gate |

### Test gates (C3 5-column table — ADDITIVE; the legacy line form follows)

Re-derived from the plan's `## Test Gates (Supplement)` table (authoritative). `...` = `.venv/bin/python3.11 -m pytest tests/integration -q` (the **directory**, so every selector resolves under either file outcome).

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| SG-1 | No regression in the unit lane after S1–S4 | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -q` → 0 failed, count ≥ baseline + new hook tests | B |
| SG-2 | Resolver hook fires iff flag ON **and** graph write happened | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_identity_coop_hook.py -q` → 3 passed | B |
| SG-3 | Hook actually mints an accrual against a real DB | Hybrid (PG :5433) | `... -k end_to_end_accrual` → 1 passed; exactly 1 event + 1 ACCRUE row | B |
| SG-4 | Site delete removes co-op events + ledger | Hybrid (PG :5433) | `... -k site_delete_removes_coop` → both tables 0 rows for the deleted `site_id` | B |
| SG-5 | Site delete RETAINS the consent acceptance row (H1-D) | Hybrid (PG :5433) | `... -k site_delete_retains_consent` → acceptance row still present | B |
| SG-6 | Erasure enqueued before a resolve blocks the accrual (the H2 fix) | Hybrid (PG :5433) | `... -k erasure_window_race_blocked` → 0 event rows, 0 ledger rows | B |
| SG-6b | Positive control: same resolve without the enqueue DOES mint | Hybrid (PG :5433) | `... -k erasure_window_race_control` → exactly 1 event + 1 ACCRUE row | B |
| SG-7 | The tombstone exists at enqueue, before any sweep | Hybrid (PG :5433) | `... -k enqueue_writes_tombstone` → `suppression_list` row, scope `erased`, via the `SuppressionEntry` ORM | B |
| SG-8 | The sweep's later tombstone write stays idempotent | Hybrid (PG :5433) | `... -k sweep_tombstone_idempotent` → sweep raises nothing, exactly 1 suppression row | B |
| SG-9 | `contribution_enabled=True` is rejected while the deployment flag is OFF | Hybrid (PG :5433) | `... -k contribution_flip_gated_on_global_flag` → 422 + flag unchanged, with a **valid** digest supplied | B |
| SG-10 | Opting OUT is never gated | Hybrid (PG :5433) | `... -k contribution_optout_never_gated` → 200 with global flag OFF; flag flips False | B |
| SG-11 | Co-op integration lane green (requires item 9a) | Hybrid (PG :5433) | `.venv/bin/python3.11 -m pytest tests/integration/test_identity_coop_contribution.py -q` (+ `tests/integration/test_identity_coop_supplement.py` if the split hatch fired) → 0 failed | B |
| SG-12 | Concurrent site-analysis hunks survive the S1/S3 edits | Agent-Probe | `git diff apps/api/routers/sites.py` — site-analysis hunks present and unmodified alongside the additive co-op edits | B |
| SG-13 | Evidence-pack non-vacuity claims are honest | Agent-Probe | read `harness/adversarial-validation.json` — ADV-1/ADV-2 cite `wrote is False/True` + integration legs only; F14 third leg `vacuous-and-retired` | B |
| SG-14 | The human verdict is recorded faithfully, with no self-approval | Agent-Probe | read `harness/review-decision.json` — `decision: "rejected"`, reviewer + reviewedAt set | B |
| SG-15 | A tombstone failure never loses the `ErasureRequest`, **and the SAVEPOINT is entered** | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_graph_erasure.py -q -k tombstone_write_failure` → 1 passed; asserts `db.begin_nested` **was called**, the tombstone execute raised, the `ErasureRequest` was still added, `db.commit()` was awaited, nothing escaped | B (name the function per E-S1) |
| SG-16 | Postgres actually honours the savepoint under a real DB-level failure | Hybrid (PG :5433) | forced statement failure inside the tombstone statement, then assert the `ErasureRequest` row exists | **D** — named residual; SG-15 proves the savepoint is *entered*, not that the server honours it |

gap-resolution legend: A — proven now; B — gate added by this plan's checklist; C — deferred to a
named later phase; D — backlog test-building stub (named residual; keep-active; continue).

Legacy line form (retained so existing validate-contract consumers still parse):

- Unit lane / hook decision half: [Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit -q`] | [Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_identity_coop_hook.py -q`]
- Tombstone fail-safe: [Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_graph_erasure.py -q -k tombstone_write_failure`]
- Co-op DB behavior (H1/H2/M2/M3): [hybrid: `.venv/bin/python3.11 -m pytest tests/integration -q -k <selector>` + precondition: Postgres on :5433, `DATABASE_URL` pinned local]
- Co-op integration lane: [hybrid: `.venv/bin/python3.11 -m pytest tests/integration/test_identity_coop_contribution.py -q` + precondition: PG :5433]
- Concurrent-edit + evidence-pack honesty: [agent-probe: `git diff apps/api/routers/sites.py`; read `harness/adversarial-validation.json`; read `harness/review-decision.json`]
- Savepoint honoured by the server: [known-gap: documented — SG-16 optional, named residual]

### Failing stubs (Fully-Automated rows only)

SG-2:

```
test("should invoke maybe_record_contribution with (db, visitor, data, provider) when the flag is ON and wrote_graph is True", () => { throw new Error("NOT IMPLEMENTED — TDD stub: hook fires when flag ON and graph write happened") })
test("should NOT invoke maybe_record_contribution when wrote_graph is False", () => { throw new Error("NOT IMPLEMENTED — TDD stub: hook mirror case") })
test("should NOT invoke maybe_record_contribution when the global flag is OFF even if wrote_graph is True", () => { throw new Error("NOT IMPLEMENTED — TDD stub: hook flag-OFF case") })
```

SG-15:

```
test("should enter db.begin_nested, keep the ErasureRequest added, and still await db.commit() when the tombstone execute raises", () => { throw new Error("NOT IMPLEMENTED — TDD stub: tombstone failure never loses the erasure request") })
```

SG-1 is a lane gate (no scenario-level stub). Hybrid, Agent-Probe, and Known-Gap rows do not receive
stubs.

### Open gaps

- **SG-16 (optional item 5c): known-gap — accepted, named residual.** SG-15 proves the savepoint is
  *entered*; it cannot prove Postgres honours it, because the unit lane cannot abort a real
  transaction. Resolution D. Recorded in `## Test Infra Improvement Notes (Supplement)` as the
  candidate statement-level failure-injection helper.
- **Multi-process concurrency on the H2 window: known-gap — accepted, pre-declared.** SG-6 proves the
  sequential window, which is the actual reported defect; a true two-process race needs orchestration
  outside this supplement's scope.
- **N-A / N-B: open but instruction-closed** (E-S1, E-S2). Neither requires a plan edit.
- **N-E: doc-sync only** — the Resume/Handoff line still cites cycle 2's BLOCKED state; superseded by
  this contract. Outside this agent's write scope.
- **The high-risk evidence pack remains REJECTED and un-re-reviewed.** S6/S7 correct its bookkeeping;
  they do not and must not change the human verdict.

### What this coverage does NOT prove

- **SG-1 / SG-11 (lane gates)** prove no *collected* test regressed. They do not prove any new
  behavior exists — a lane can be green with zero new tests written.
- **SG-2 (unit, fake session)** proves the hook's *decision* logic. It does not prove any row is
  persisted, does not exercise the partial unique index, and does not prove `ON CONFLICT` semantics.
- **SG-3 / SG-4 / SG-5 / SG-6 / SG-6b / SG-7 / SG-8** prove single-process, sequential DB behavior on
  a local Postgres. They do not prove behavior under concurrency, under a different `search_path`, or
  on Supabase prod (where neither co-op migration is live).
- **SG-6b** proves the mint path is live in that fixture. It does not prove the mint path is live in
  *production* configuration — both flags are default OFF.
- **SG-9 / SG-10** prove the router contract through the integration client. They do not prove any UI
  or client behavior, and they do not prove the runbook reset (`UPDATE sites SET
  contribution_enabled=false` at a terms re-pin) is ever actually run — that is an operator action
  with no gate.
- **SG-15** proves the savepoint is *entered* against a fake session and that the request survives in
  that fake. It does **not** prove Postgres rolls back only the savepoint under a real deadlock,
  statement timeout, or connection loss — that is SG-16, a named residual.
- **SG-12 / SG-13 / SG-14** are Agent-Probe reads. They prove a human-or-agent looked and reported;
  they are not mechanically enforced and can be reported green in error.
- **No gate proves the diff budgets.** ≤12 `sites.py`, ≤18 `graph_erasure.py`, ≤8 `suppression.py`,
  ≤480 integration, ≤30 (likely ~45) `test_graph_erasure.py` are estimates; only the real diff proves
  them.
- **Nothing here proves prod behaviour.** Both co-op flags remain default OFF and neither co-op
  migration is live on prod. M2's fix makes the opt-in strictly harder, never easier. Enabling either
  flag stays a separate, explicit operator action gated on legal review and a terms-digest re-pin.

Gate: CONDITIONAL

Accepted by: **NOT YET ACCEPTED — pending orchestrator/user decision.** This validating agent does
not self-accept its own CONDITIONAL verdict. The concerns offered for acceptance, by name: **N-A**
(SG-15's unit test function is unnamed; closed by execute-agent instruction E-S1) and **N-B** (the
`test_graph_erasure.py` ≤30-line budget is optimistic; closed by E-S2). Both are execute-agent-
instruction class — **no further plan supplement cycle is required**, and no SUPPLEMENT REQUEST is
issued this cycle. The pre-declared known-gaps offered alongside them: **SG-16** (Postgres honours
the savepoint) and **multi-process concurrency on the H2 window**.
