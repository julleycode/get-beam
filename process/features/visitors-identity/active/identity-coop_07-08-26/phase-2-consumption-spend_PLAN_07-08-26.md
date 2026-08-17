---
name: plan:identity-coop-phase-2a-consumption-expiry
description: "Identity Co-op — Phase 2a: read-only consumption aggregation + FIFO lot expiry sweep (spend wiring split out to Phase 2b; REVERSE dropped to K-1 backlog)"
date: 07-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
  phase: phase-2a
---

# Phase 2a — Consumption Aggregation + FIFO Expiry

**Program:** identity-coop
**Umbrella plan:** `process/features/visitors-identity/active/identity-coop_07-08-26/identity-coop-umbrella_PLAN_07-08-26.md`
Complexity: COMPLEX (phase of a 4-phase program — 1, 2a, 2b, 3)
Phase status: ⏳ PLANNED — entry gate PASSED 16-08-26; **PVL must re-run from V1 against this narrowed 2a scope**
Status: ⏳ PLANNED (SPLIT 17-08-26 from `phase-2-consumption-spend`)
Date: 07-08-26 (refresh supplement 16-08-26; **SPLIT rewrite 17-08-26**)
**Report destination:** `process/features/visitors-identity/active/identity-coop_07-08-26/phase-2a-consumption-expiry_REPORT_07-08-26.md`

**TL;DR** — Count consumption with ZERO new write surface (read-only aggregation over
`api_usage_logs`), implement FIFO lot accounting and an explicit idempotent `EXPIRE` sweep with
lot-symmetric stamping, and land the AC-8 exact-reconciliation property test. **No spend wiring and
no REVERSE vocabulary ship here** — those are Phase 2b and the K-1 backlog note respectively.

---

## Why This Phase Was Split (recorded 17-08-26 — do not re-merge)

Five PVL cycles plus three independent adversarial rounds produced a **stable design core**: the
savepoint posture, lock acyclicity, REVERSE idempotence, and the K-4 orphan premise all survived
repeated attack. But every fix cycle produced a NEW defect of one class: **a gate that passes on the
implementation it exists to forbid** (vacuous-green). Root cause is phase SIZE — one plan covering
ledger vocabulary + consumption aggregation + expiry sweep + spend wiring + locking + failure posture
cannot be gated coherently, because each fix widened the surface faster than the gate set could
follow.

**The user chose the split over more PVL cycles (explicit decision, 16-08-26).**

| Split | Contents | Status |
|---|---|---|
| **Phase 2a (this plan)** | P2-D2 (on-demand COUNT + EXPLAIN-gated conditional index E1 + per-live-site reconciliation invariant), P2-D5 (lot-symmetric stamping + explicit idempotent EXPIRE sweep), P2-D4 (unmarked `tests/unit -q` gate), the AC-8 oracle work | **Next executable phase** |
| **Phase 2b** (`phase-2b-spend-wiring_PLAN_16-08-26.md`) | P2-D3, P2-D6 + S-13b (failure posture / savepoint), S-14 (`pg_advisory_xact_lock`), the C-4/C-5 dashboard fix, G-6/G-7/G-9-spend-legs/G-10/G-16, K-4, the D-D user-pooling constraint | ⏳ PLANNED — not next |
| **K-1 backlog** (`backlog/coop-credit-reversal-semantics_NOTE_16-08-26.md`) | ALL REVERSE content: P2-D1, S-1, S-2/S-2b/S-2c, G-1/G-2, Constraint 12b, the clawback/debt algebra | Deferred, undecided |

**`LEDGER_ENTRY_TYPES` stays `("ACCRUE","SPEND","EXPIRE")` in 2a — no vocabulary change ships here.**

---

## Overview

See Purpose below for the narrative; this phase is one leg of the identity-coop phase program.
Ordering, gates, and program state live in the umbrella plan.

---

## Purpose

Phase 1 proved credits can be earned. Phase 2a proves they can be **counted against and expired**,
with the ledger reconciling exactly. Phase 2b then proves they can be **spent**. The core constraint
here is that consumption measurement adds **no new write surface**: the graph-served identification
is already logged, so consumption is purely a query.

---

## Entry Gate — **PASSED 16-08-26**

| Link | Status (16-08-26, source-verified) |
|---|---|
| Phase 1 exit gate | **PASSED.** Shipped in commit `d78b4f1` + supplement hunks; human-APPROVED 16-08-26. All 3 co-op tables live (`models/identity_coop.py:77,:127,:172`); `Site.contribution_enabled` wired (`models/site.py:38`, `schemas/sites.py:69,106`, flip endpoint `routers/sites.py:427-455`); resolver hook live (`identity_resolver.py:1308-1312`, gated on `wrote_graph`). |
| SPEC A `graph-erasure-compliance_07-08-26` LIVE | **CLEARED.** LIVE, EVL 14/14, migration `d1a6c4e93f27` applied in prod. |
| `identity-vocab-reconcile_07-08-26` | **CLEARED** (EXECUTED, user-accepted). |
| Consumption source unchanged | **CONFIRMED.** `_log_owned_resolution` (symbol at `identity_resolver.py:1515`, body `:1516-1540` — **locate by symbol, never by line**, S-25) → `log_api_call` (`usage_logger.py:22-56`) → `ApiUsageLog` in `api_usage_logs`, `provider='beam_identity_network'`, `category='identity'`. Call sites now `:1179` and `:1220`. |
| Alembic head | **Live head 16-08-26 = `a8c2f47e91b6`**, single head; the previously-untracked migrations are now tracked. **Re-derive LIVE at EXECUTE** (S-24); always pin `DATABASE_URL` to `localhost` first (`.env` → Supabase PROD; `migrations/env.py` has no guard). |

All entry-gate links are cleared. The remaining blocker is procedural only: **PVL must re-run from V1
against this narrowed 2a scope** (every prior `## Validate Contract` below is SUPERSEDED).

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
- `beam_identity_network ∈ OWNED_FREE_PROVIDERS` in `apps/api/services/identity_classification.py`.

**Therefore:** consumption = read-only aggregation over `api_usage_logs` WHERE
`provider = 'beam_identity_network' AND category = 'identity' AND success IS TRUE`, grouped by
`site_id`. Provider-purchased resolutions are structurally separate (non-zero `cost_usd`, different
providers) — AC-4's "does not increment the provider-spend counter" assertion falls out of the data
shape, not new plumbing.

**Do NOT add any write to the read path.** If the aggregation appears to need a new column, stop
and re-plan — that is the failure mode this decision exists to prevent.

**VALIDATE re-verification (07-08-26):** `_log_owned_resolution` (symbol at `identity_resolver.py:1515`, body `:1516-1540` — the former `:1415-1440` citation was STALE; **locate by symbol, never by line**, S-25)
confirmed verbatim. `OWNED_FREE_PROVIDERS` (`identity_classification.py:74-79`) = `{form_capture,
fingerprint_match, beam_identity_network, svid_reconcile}` — all four log to `api_usage_logs` with
`category="identity"`, so the `provider='beam_identity_network'` filter is load-bearing to isolate
graph-served consumption specifically. **Claim confirmed correct as stated.**

---

## Blast Radius

Risk class: **billing/credits + schema/migration**. Hybrid gate minimum.

**10 files** (was 8; +1 test-seeding helper and +1 mandatory migration added by the 17-08-26 supplement cycle — reconciled 17-08-26 at the split — this list and `## Touchpoints` are now ONE consistent
list; the cycle-5 F5-3 disagreement is closed below).

| File | Change | Budget |
|---|---|---|
| `apps/api/models/identity_coop.py` | **MODIFIED — S-10c prose + the E2 index mirror (F2b-2 fix, 17-08-26 cycle 2).** Two parts, BOTH mandatory: (i) the S-10c prose amendment — two "ACCRUE only" comments must state the stamping rule; (ii) **the E2 partial unique index mirrored into `CreditLedgerEntry.__table_args__`**: `Index("uq_coop_ledger_expire_per_lot", "lot_id", unique=True, postgresql_where=text("entry_type = 'EXPIRE'"))`. **The mirror is what makes G-21 runnable at all** — `tests/conftest.py:133` builds the integration schema with `Base.metadata.create_all`, **never alembic**, so without the mirror the index does not exist in the test DB and G-21 fails outright (no `IntegrityError` is ever raised). "Prose only" is **RETRACTED** as a description of this file. Still **no `LEDGER_ENTRY_TYPES` change** (REVERSE dropped to K-1) — no vocabulary edit. | **~12 lines (≈6 prose + ≈6 index mirror)** |
| `apps/api/services/identity_coop.py` | `consumption_count`, `contribution_count`, `spendable_lots`, `expire_lapsed_lots`, S-4 clamp | **~180 lines added** |
| `apps/api/services/coop_expiry_sweep.py` | **NEW (C-6)** — sweep body `run_coop_expiry_sweep(db)`, repo convention (`services/*_sweep.py`), NOT the Celery `tasks/` package | **~45 lines** |
| `apps/api/jobs/scheduler.py` | `_coop_expiry_sweep_job()` wrapper (flag check inside, session open, crash swallow — mirrors the `_cadence_bot_flag_sweep_job` **symbol**, defined at `jobs/scheduler.py:273-297`; the plan's former `:258-283` citation was STALE — that range is mostly `_intent_signal_sweep_job` at `:256`) + one `scheduler.add_job(...)` | **~25 lines** |
| `apps/api/config.py` | `coop_expiry_sweep_interval_minutes` | **1-2 lines** |
| `phase-blast-radius-registry.md` | Phase 2a claim amendment (S-3) — **verify-only unless missing or stale** | **0-4 lines** (0 when the existing dated claim is present and accurate; ~4 to amend it in place). **Reconciled with S-3 (L3-4, cycle 3) — the former "1-2 lines" here contradicted S-3's "0-4 lines"; 0-4 is authoritative in BOTH places.** |
| `tests/integration/test_identity_coop_ledger.py` | NEW — carries G-3, G-9, G-17, G-18, G-19, **G-20, G-21, G-22, G-23**. Declares `pytestmark = pytest.mark.integration` (S-26). | **~470 lines** |
| `tests/integration/conftest.py` **or** a module-local helper in `test_identity_coop_ledger.py` | **NEW (C2a-2 / Gap 7 fix)** — `seed_api_usage_logs(db, site_id, n, *, providers)` bulk-insert helper for G-4's EXPLAIN evidence. Bulk `INSERT … SELECT generate_series(...)` (single statement — a 100k-row ORM loop is not acceptable). **TWO bulk statements, not one (L2-5 fix, 17-08-26):** S-9/M-5 require ≥50% of rows on the probed site to have a **matching `identified_visitors` row**, which is a SECOND bulk insert into a different table — budget it explicitly. **Both inserts are raw SQL and therefore BYPASS the `_sync_identity_pii` mapper hook** (`services/pii_encryption_hooks.py:33-36`), so the seeded `identified_visitors.email_bidx` will be **NULL**. That is ACCEPTED and harmless: G-4 is an `EXPLAIN`-shape gate, not a correctness gate, and the A2 erased-row semantics are proven by G-19 against ORM-created rows. **Do not "fix" this by reaching for an ORM loop** — that is the 100k-row failure mode this helper exists to avoid. No such harness exists today (Test Infra note). | **~30 lines (two bulk statements)** |
| `apps/api/migrations/versions/{rev}_add_coop_expire_unique.py` | **NEW — MANDATORY (M-3 decision).** Partial unique index `uq_coop_ledger_expire_per_lot` on `identity_credit_ledger (lot_id) WHERE entry_type = 'EXPIRE'`. Rides E1's conditional-migration machinery but is **itself unconditional**. **Merge modality — DECIDED (L2-1, 17-08-26): if E1 fires, BOTH indexes go in this ONE migration file and the separate `{rev}_add_coop_ledger_indexes.py` file is NOT created.** "may be merged" is retracted everywhere; E2's checklist wording is authoritative. | **~35 lines (≈75 if E1 merges in)** |
| `apps/api/migrations/versions/{rev}_add_coop_ledger_indexes.py` | **CONDITIONAL and, per L2-1, NEVER a separate file in practice.** Only S-9 seq-scan evidence on `api_usage_logs` triggers E1 at all; when it does, the E1 index is added to the MANDATORY `{rev}_add_coop_expire_unique.py` file above. This row exists to name the E1 *content*, not a second file. Total file count therefore stays **10** whether or not E1 fires. | **~40 lines, folded into the file above** |

**F5-3 resolution (cycle 5 finding, closed at the split):** cycle 5 found `apps/api/models/identity_coop.py`
missing from the file list AND wrongly marked READ ONLY in `## Touchpoints`. With REVERSE dropped,
the vocabulary edit disappears — but the S-10c stamping-prose amendment REMAINS **and E2 adds the
index mirror**, so the file is **MODIFIED (~12 lines: S-10c prose + E2 index mirror)**, listed above,
and no longer appears under READ ONLY anywhere. **"Prose only" is RETRACTED (F2b-2, cycle-3 Gap 3 /
adversarial L3-1)** — an implementer honouring the retracted wording skips the `__table_args__`
mirror, the index never exists in the `create_all`-built test DB, and **G-21 fails outright**.

**Explicitly NOT touched in 2a:** `apps/api/services/billing.py`, `apps/api/routers/billing.py`
(both are Phase 2b), `apps/api/services/identity_resolver.py` (empty diff is an exit gate, G-13),
`Site.daily_resolution_budget`, `spendable_balance`'s QUERY at `identity_coop.py:242-247` (prose
only — S-10c), `apps/api/tasks/` (Celery package, out of scope by C-6), `visitor_aggregator`,
`tests/integration/test_identity_coop_spend.py` (created in Phase 2b).

---

## Credit Semantics Carried Into 2a (decided, do not re-open)

| Question | Decision |
|---|---|
| Exchange rate | **1 credit = 1 resolution unit of monthly allowance.** (Consumed in Phase 2b.) |
| Draw order | **FIFO by `expires_at` ascending** — oldest-expiring lot first, so credit is never wasted. `spendable_lots` (B1) implements the ordering here; the draw itself is 2b. |
| Expiry | Lot-based: each `ACCRUE` row carries `expires_at = created_at + coop_credit_expiry_days` (90). Excluded at read time; a sweep writes an explicit `EXPIRE` row (negative amount, `lot_id` set) so expiry is auditable, not silent. |
| Hold | A lot is not spendable until `now >= spendable_at` (`created_at + coop_credit_hold_hours`, 24h), giving the batch `cadence_bot_flag` sweep time to catch slow bot patterns. |
| What do credits buy? | Additional **monthly** identity-resolution allowance (`monthly_limit`), never `daily_resolution_budget`. **Wiring is Phase 2b** — 2a must not touch `billing.py`. |

The site-scoped-ledger vs. user-scoped-gate D-D constraint (`phase-blast-radius-registry.md:76-82`)
governs the SPEND path and therefore moves to **Phase 2b**. 2a writes only site-scoped EXPIRE rows
and needs no user join.

---

## Implementation Checklist

> **Numbering note.** Step/S-item/gate IDs are **STABLE IDENTIFIERS** cited across five PVL cycles,
> three adversarial rounds, both validate-contracts, and the K-1 backlog note. The split **drops**
> the items that moved to 2b/K-1 rather than renumbering the survivors — exactly the rationale that
> froze the Constraint numbering. Do NOT renumber. Step C (spend) and Step D's spend tests are gone
> because they are Phase 2b, not because they were renumbered.

### Step A — Consumption aggregation (read-only)

- [ ] A1. Add `async def consumption_count(db, site_id, *, since=None, until=None) -> int` to `apps/api/services/identity_coop.py` — a single SELECT COUNT over `api_usage_logs` filtered as stated in the Corrected Consumption Source section above. No writes, no new columns.
- [ ] A2. Exclude erased rows: filter out consumption events whose underlying identity `email_bidx` appears in `SuppressionEntry(scope="erased")`. **Join path (VALIDATE 07-08-26, confirmed feasible and specified exactly):** `api_usage_logs` has no PII/bidx column, but `api_usage_logs.visitor_id` + `.site_id` uniquely match `identified_visitors` via `uq_identified_site_visitor (site_id, visitor_id)`. `IdentifiedVisitor.email_bidx` (`models/visitor.py:227`) is auto-populated on every insert/update by the `before_insert`/`before_update` mapper hook `_sync_identity_pii` (`services/pii_encryption_hooks.py:33-36`), using the SAME `email_hash()` function `SuppressionEntry.email_hash` (`models/suppression.py`) is written with by the erasure sweep — so the two blind-index values are directly comparable. Join: `api_usage_logs JOIN identified_visitors ON (site_id, visitor_id) → WHERE identified_visitors.email_bidx NOT IN (SELECT email_hash FROM suppression_list WHERE scope='erased')`. **Join type is INNER — decided, do not re-open (L-2).** A consumption row whose `IdentifiedVisitor` no longer exists is **EXCLUDED by design**: per-visitor deletion (`routers/visitors.py:449-476`) removes the `identified_visitors` row but leaves the `api_usage_logs` row, so a LEFT JOIN would keep counting deleted identities. INNER means `consumption_count` measures *currently-attributable* graph-served resolutions, which is the number the co-op is entitled to charge against. State this in the docstring (S-7). **Backfill caveat largely CLOSED 16-08-26:** the 07-08-26 prod `backfill_pii_ciphertext` run completed 22/22 with 0 remaining across all 4 tables. Keep one defensive live check at EXECUTE (S-13a). New constraint (c): `SuppressionEntry(scope="erased")` now means "erasure REQUESTED or completed" (tombstone-at-enqueue), so this exclusion inherits the wider meaning and excludes MORE rows, SOONER. That is the intended direction — do not narrow it.
- [ ] A3. Add `async def contribution_count(db, site_id, *, since=None, until=None) -> int` over `identity_contribution_events`, excluding rows with a non-NULL `excluded_reason`. **Gated by G-22 (L-3):** an implementation that omits the `excluded_reason IS NULL` filter would otherwise ship green.
- [ ] A4. Assert with `EXPLAIN` (recorded in the phase report, per S-9) that both queries hit an index; add the conditional E1 covering-index migration ONLY if a seq scan appears **on `api_usage_logs`**. **E1 trigger rule — falsifiable, narrowed (M-5 fix):** the rule applies to the **`api_usage_logs` relation ONLY**. A seq scan on `identified_visitors` or `suppression_list` does **NOT** trigger E1 — S-9's seeding leaves those relations tiny and the planner is *correct* to seq-scan them, so a literal "a seq scan appears anywhere" rule would fire on **every** run regardless of index quality (predetermined by reading, not by evidence). Correspondingly, S-9's seed MUST make the join path genuinely exercised (see S-9).
- [ ] A5. Add a test proving A2's erased-row exclusion actually excludes: an `IdentifiedVisitor` row whose `email_bidx` is present in `SuppressionEntry(scope='erased')` must not be counted in `consumption_count`. Proves the SPEC A interface obligation that no other gate covers (G-19). Test function name: `test_coop_erased_row_excluded_from_consumption` (see D9).

### Step B — FIFO lot accounting and expiry

- [ ] B1. Add `async def spendable_lots(db, site_id) -> list[CreditLedgerEntry]` — `ACCRUE` rows where `now >= spendable_at` and `now < expires_at`, minus already-drawn amounts per `lot_id`, ordered by `expires_at` ASC. Per-lot remaining is clamped at `max(0, ...)` (S-4).
- [ ] B2. **Do NOT change `spendable_balance`'s query.** `spendable_balance(db, site_id)` (`identity_coop.py:227-249`) is FROZEN (Constraint 11) — it is covered by shipped green tests at `tests/integration/test_identity_coop_contribution.py:380` and `:417`. Phase 2a's F-1 fix lives entirely on the WRITE side: the EXPIRE writer stamps rows with the source lot's `spendable_at`/`expires_at` (S-10b), so non-ACCRUE rows no longer carry NULL and no longer "always count" — they enter and leave the window in lockstep with their lot. Prose/docstrings are corrected (S-10c/S-12); the query is not.
- [ ] B3. Add `async def expire_lapsed_lots(db) -> int` — for each `ACCRUE` lot past `expires_at`, write ONE `EXPIRE` row with **`amount = -max(0, remaining)`**, `lot_id`, `reason='lot_expired'`, stamped per S-10b. Skip the lot when `max(0, remaining) == 0`. Must be **idempotent**: re-running writes zero additional rows (**AC-7**).

  > **Loop + commit ownership — DECIDED (M-2 fix; B3 and B3b previously contradicted).**
  > **`expire_lapsed_lots(db)` owns BOTH the per-lot loop AND the per-lot `await db.commit()`.**
  > `run_coop_expiry_sweep(db)` owns ONLY: the advisory-lock acquire/release pair, the early return
  > when the lock is not acquired, and one call to `expire_lapsed_lots(db)`. It contains **no loop
  > and no commit of its own**. Crash semantics that follow: a mid-sweep crash leaves every
  > already-processed lot durably expired and every unprocessed lot untouched — the sweep resumes
  > correctly on the next tick with no partial-lot state. **What the direct-call tests (D3/D4/G-18)
  > may assume:** calling `expire_lapsed_lots(db)` directly COMMITS its own work — tests must not
  > wrap it in an outer transaction they expect to roll back, and must re-query (not rely on
  > identity-map caching) to observe the written rows.

  > **Orphan-EXPIRE guard + duplicate guard — MANDATORY, ONE STATEMENT, WRITTEN VERBATIM
  > (M-4 fix; `ON CONFLICT` promoted from "should" to MUST by C-4/M2-1, 17-08-26).** The EXPIRE row
  > MUST be written as exactly this single statement — the existence check, the insert, and the
  > conflict clause all in the SAME statement, never a read-then-insert pair and never an insert
  > without the conflict clause:
  >
  > ```sql
  > INSERT INTO identity_credit_ledger
  >     (id, site_id, entry_type, amount, lot_id, reason, spendable_at, expires_at, created_at)
  > SELECT :new_id, :site_id, 'EXPIRE', :amount, :lot_id, 'lot_expired',
  >        :lot_spendable_at, :lot_expires_at, now()
  > WHERE EXISTS (
  >     SELECT 1 FROM identity_credit_ledger
  >     WHERE id = :lot_id AND entry_type = 'ACCRUE' AND site_id = :site_id
  > )
  > ON CONFLICT (lot_id) WHERE entry_type = 'EXPIRE' DO NOTHING
  > ```
  >
  > The `ON CONFLICT (lot_id) WHERE entry_type = 'EXPIRE'` form is **partial-index inference** — it
  > targets `uq_coop_ledger_expire_per_lot` (E2) by predicate, so a losing racer is a silent no-op
  > rather than a 500. **This does NOT mask G-20:** G-20's correct outcome is exactly one EXPIRE row
  > per lot either way, so the conflict clause changes nothing G-20 observes. The only path it
  > covers is the multi-process race, which stays ungated by design (K-2, accepted).
  > **Why:** the sweep loads its lapsed-lot set, then `DELETE /sites/{id}` (`routers/sites.py:328,
  > :337-341`) cascades away that site's ledger rows and commits, and the sweep then inserts an
  > `EXPIRE(site_id=S, lot_id=L, −N)` for a site that no longer has a lot — an orphan negative row.
  > On same-`site_id` re-create (tombstone flow, `routers/sites.py:360-372`) the NEW site inherits
  > it, and Phase 3's dashboard — which reads EXPIRE rows **without** the balance window predicate —
  > reports credits the site never had. That is the H1 site_id-reuse class the delete tuple exists to
  > close; K-4 covers the 2b spend writer, **not** 2a's EXPIRE writer. The single-statement guard
  > shrinks the window to ~zero and removes the class rather than documenting it.

  > **Per-lot failure isolation — MANDATORY (C-1 fix, 17-08-26). Without it the lock leaks
  > SILENTLY on the exception path.** Each lot iteration inside `expire_lapsed_lots` MUST be wrapped:
  >
  > ```python
  > for lot in lapsed_lots:
  >     lot_id_str = str(lot.id)   # snapshot BEFORE the try — see the ordering note below
  >     try:
  >         ...  # the single INSERT statement above
  >         await db.commit()
  >     except Exception:
  >         await db.rollback()
  >         logger.exception("coop_expire_lot_failed", lot_id=lot_id_str)
  >         continue
  > ```
  >
  > **Ordering inside the block is load-bearing (L3-3 fix, cycle 3) — write it exactly as above.**
  > The earlier form evaluated `str(lot.id)` **inside** the `except`, **before** `await db.rollback()`.
  > If the failing statement was the `commit()` itself, that attribute access can trigger a lazy
  > refresh on an invalidated connection and **raise inside the except handler** — skipping both the
  > `rollback()` and the `continue`, aborting the whole loop, and leaving the session in exactly the
  > aborted state this block exists to prevent (which then defeats the `finally` unlock — see the
  > C-1 rationale below). Two independent fixes, and **both are applied above**: snapshot
  > `lot_id_str` before the `try`, and roll back before logging.
  >
  > **Why this is load-bearing, not defensive style:** all four cited lock precedents implement
  > `_release_lock` as `try: … except Exception: pass` (e.g. `services/reengagement.py:258-264`).
  > If any lot raises and is NOT rolled back, the session enters an aborted-transaction state, the
  > `finally`'s `SELECT pg_advisory_unlock(...)` then fails, the precedent's bare `except` swallows
  > that failure — **and the lock leaks anyway, silently, exactly as if the release had never been
  > written.** E2 itself is a new exception source. The precedent for per-row isolation is
  > `services/referral_activation.py:185-192`.
  >
  > **⚠ THE ISOLATION HAS A COST — MANDATORY REPORTING OBLIGATION (Gap 7, cycle 3).** `except … continue`
  > converts a **systemic** INSERT failure into a **silent zero-row sweep**. The realistic trigger is
  > concrete: if the E2 index is missing from the test DB (the F2b-2 `create_all`-not-alembic class),
  > the `ON CONFLICT (lot_id) WHERE entry_type = 'EXPIRE'` inference **errors on every single lot** —
  > every iteration logs, rolls back, and continues, the sweep returns 0, and the only visible symptom
  > is a red G-18 leg 5 / G-20 leg (b) **with no cause anywhere in the failure output**. **Therefore:
  > EXECUTE MUST capture and record in the phase report any `coop_expire_lot_failed` log lines emitted
  > during the integration gate run** (e.g. pytest `caplog`, or grepping the captured log output), and
  > MUST state explicitly in the report either the count of such lines or "zero `coop_expire_lot_failed`
  > lines observed". **A non-zero count with green gates is a finding to investigate, never noise.** **Additionally, `run_coop_expiry_sweep`'s `finally`
  > MUST call `await db.rollback()` immediately BEFORE `_release_lock(db)`** so the unlock always
  > runs on a usable transaction. The exception path itself remains ungated (see the gate table's
  > "lock release on the exception path" row, resolution D — a documented residual adjacent to K-2).
  >
  > **`remaining` is WINDOW-BLIND — mandatory definition, restated here verbatim (F5-2 fix, cycle 5 OPEN FAIL).**
  > `remaining` for a lot = the **raw arithmetic SUM of ALL ledger rows carrying that `lot_id`**,
  > computed **WITHOUT** the `spendable_at <= now AND expires_at > now` window predicate — i.e.
  > `SELECT SUM(amount) FROM identity_credit_ledger WHERE lot_id = :lot` with no time filter at all.
  > **Why this is load-bearing:** under a window-AWARE reading, a lapsed lot's ACCRUE is already
  > outside the window, so `remaining` reads as 0, `max(0, 0) == 0` fires the skip, and
  > `expire_lapsed_lots` writes **ZERO rows forever** — yet passes every legacy G-18 leg (legs 1-2
  > assert `balance == 0`, and a stamped EXPIRE row is balance-invisible BY CONSTRUCTION; leg 3
  > explicitly accepts "no EXPIRE row"; leg 4 quantifies only over rows that exist; D4 idempotence
  > is `0 + 0`). That is a textbook vacuous green: the sweep that never runs passes the gate that
  > exists to prove it ran. **G-18 leg 5 (positive leg) is the fix** and is mandatory.

- [ ] B3b. **Commit granularity + sweep lock — DECIDED (M3-1, amended by F2a-1).** Commit is **per lot**, following the `cadence_bot_flag_sweep.py:158` precedent (which commits per site iteration); a bounded batch is explicitly rejected because a mid-batch failure would leave a partially-swept batch with no idempotence marker other than the rows themselves. **The per-lot loop and the per-lot commit both live in `expire_lapsed_lots` — see the ownership block under B3 (M-2).**

  > **LOCK — ACQUIRE **AND** RELEASE, mandatory pair (F2a-1 fix). Acquire-only is a defect.**
  > `run_coop_expiry_sweep(db)` takes ONE **global** instance-dedup try-lock at entry and **releases
  > it in a `finally`**. The two halves are non-separable:
  > 1. Acquire: `_try_acquire_lock(db)` → `SELECT pg_try_advisory_lock(hashtext(:key))` with a
  >    module-level `_LOCK_KEY = "coop_expiry_sweep"`.
  > 2. **Early return when not acquired — the predicate is `is False`, NOT falsy (C-2 fix,
  >    17-08-26).** Write `if got is False:` → log at info and **return 0 immediately**; do not call
  >    `expire_lapsed_lots`, do not attempt a release (the unlock would log a spurious warning).
  >    **`_try_acquire_lock` returns `bool | None`, where `None` means "unsupported / the lock query
  >    itself errored"** — all four precedents deliberately **PROCEED** on `None` (fail-OPEN), and
  >    2a follows them. A falsy check is fail-CLOSED: on a single `None` the sweep would silently
  >    never expire anything, forever, with **no gate in the set able to observe it** — a worse
  >    failure than a duplicate sweep run, which E2 now rejects at the DB tier anyway. Release
  >    symmetrically with `if got:` (never release on `None`).
  > 3. Release: `_release_lock(db)` → `SELECT pg_advisory_unlock(hashtext(:key))` in a `finally`
  >    that wraps the `expire_lapsed_lots` call.
  >
  > **Why release is load-bearing:** `pg_try_advisory_lock` is **SESSION-scoped, not
  > transaction-scoped** — the per-lot `await db.commit()` mandated above does **not** release it.
  > Without an explicit unlock the connection returns to the pool still holding the lock, so later
  > sweep ticks that draw that connection re-enter a session that already holds it (counter leak),
  > while ticks drawing any other connection skip forever. Both failure shapes are silent.
  >
  > **All four precedents pair acquire with release — verified against live source 17-08-26:**
  > `services/reengagement.py:246` / `:258`, `services/retention.py:64` / `:77`,
  > `services/daily_digest.py:462` / `:474`, `services/referral_activation.py:59` / `:71`
  > (call sites: `reengagement.py:546`/`:558`, `retention.py:121`/`:160`,
  > `daily_digest.py:496`/`:569`, `referral_activation.py:104`/`:192`).
  >
  > **S-21 contradiction — RESOLVED explicitly.** `_cadence_bot_flag_sweep_job` takes **no lock at
  > all**, so it is NOT a lock precedent. The decision: **the wrapper copies
  > `_cadence_bot_flag_sweep_job`'s SHAPE ONLY** (flag check inside the wrapper, session opened via
  > `async_session()`, top-level crash swallowed with `logger.exception`) **and the lock lives one
  > level down, inside `run_coop_expiry_sweep(db)`**, following the four `services/*` precedents
  > above. The wrapper itself never touches the lock. B3b and S-21 now agree.
  >
  > **Proven by G-20's leg (a) ONLY — corrected 17-08-26 (F2b-1). The former claim that the
  > double-call is "the only assertion that a leaked lock fails" was FALSE and is retracted.**
  > A double call made with the SAME `db` proves nothing about release, for two independent reasons:
  > (i) **PostgreSQL advisory locks are RE-ENTRANT within a session** — "if a session already holds
  > a given advisory lock, additional requests by it will always succeed" — and `tests/conftest.py:149`
  > builds a plain `async_sessionmaker` over a `pool_size=5` engine, so a single-tasked test
  > returning and re-checking out a connection gets the SAME connection back — **not because the pool is LIFO — SQLAlchemy's `QueuePool`/`AsyncAdaptedQueuePool` default is FIFO (`use_lifo=False`, `sqlalchemy/pool/impl.py:79`) and `tests/conftest.py` passes only `pool_size=5`, no `pool_use_lifo` — but because a SINGLE-TASKED test never populates the pool with more than ONE connection, so the only connection available on re-checkout is the one just returned** (M3-1 correction, cycle 3: the former "LIFO pool" mechanism claim was factually WRONG in four places and is retracted) — and
  > therefore the SAME PG session: call 2's `pg_try_advisory_lock` returns TRUE **even after a
  > leak**; (ii) even across two genuinely distinct sessions, a row-count assertion cannot separate
  > a CORRECT call 2 (`max(0, remaining) == 0` → skip → 0 new rows) from a LOCK-BLOCKED call 2
  > (early return → 0 new rows) — both leave one EXPIRE row and both return 0.
  > **What actually gates release is G-20 leg (a): a direct `SELECT pg_advisory_unlock(hashtext('coop_expiry_sweep'))`
  > probe asserted to return FALSE after call 1.** See the G-20 row in `## Verification Evidence`
  > for the two mandatory legs.
  >
  > **⚠ SCOPE OF LEG (a) — CORRECTED (C3-1, cycle 3). Leg (a) gates the POST-CONDITION, not the
  > acquire/release PAIR.** It asserts only that *no lock is held after the sweep returns*. An
  > implementation that takes **no lock at all** satisfies it (and satisfies leg (b) too, which
  > only counts rows). Earlier wording here describing leg (a) as gating the acquire/release pair
  > was overclaiming and is retracted. **The ACQUISITION itself is UNGATED — accepted, adjacent to
  > K-2**: the lock is efficiency-only (E2's partial unique index is the correctness boundary, per
  > the M-3 rationale under E2), so a missing acquire costs a redundant concurrent sweep that E2
  > rejects at the DB tier, never audit corruption. Leg (a) still fails the defect it was added
  > for — an acquire **without** a release (F2a-1) — which is the realistic implementation error. An implementer who "simplifies" G-20 back to a same-session
  > double call has re-introduced a vacuous gate.
  >
  > **Connection-swap residual — DECIDED, accepted as a documented efficiency gap (M2-2,
  > 17-08-26).** `expire_lapsed_lots`'s per-lot `await db.commit()` returns the AsyncSession's
  > connection to the pool, so the `finally`'s `pg_advisory_unlock` can run on a DIFFERENT
  > connection than the one that took the lock — the unlock then no-ops and the lock leaks anyway.
  > **This is repo-standard shape: all four cited precedents share it**, and 2a deliberately does
  > NOT deviate. Harm is bounded because **E2's partial unique index — not the advisory lock — is
  > the correctness boundary** (the lock is efficiency-only, per the M-3 rationale under E2); the
  > worst outcome is a wedged sweep, which is visible as a flat EXPIRE-row count, not as
  > audit corruption. **Rejected alternative:** pinning one connection for the lock's lifetime
  > (`engine.connect()` held across the loop) — it would deviate from every precedent, break the
  > per-lot commit boundary that gives crash-resumability, and buy no correctness that E2 does not
  > already provide. **Action taken instead:** record `coop_expiry_sweep` in the existing audit set at
  > `process/general-plans/active/capacity-hardening_25-07-26/transaction-pooler-advisory-lock-audit_NOTE_25-07-26.md`
  > as an EXECUTE-time obligation (S-27).

  **No per-lot or per-user lock in 2a**, because EXPIRE is the only balance-reducing writer that
  exists in this phase (and the M-3 partial unique index below is the durable backstop).
  **Phase 2b adds the per-user `pg_advisory_xact_lock` and MUST revisit this line** when
  `spend_credits` becomes a concurrent balance-reducing writer.
- [ ] B4. Register the sweep following the repo's APScheduler convention (S-21): the BODY lives in `apps/api/services/coop_expiry_sweep.py`; the `_coop_expiry_sweep_job()` wrapper and `scheduler.add_job(...)` registration live in `apps/api/jobs/scheduler.py` (verified against live source 17-08-26: sibling registrations at `:685-700`; canonical wrapper is the **`_cadence_bot_flag_sweep_job` symbol at `:273-297`** — the former `:258-283` citation was STALE, that range is mostly `_intent_signal_sweep_job` at `:256`. Per S-25, locate by symbol, never by line).

  > **Flag-gating placement — DECIDED (L-1 fix; B4 and S-21 previously disagreed).** **BOTH, and
  > that is deliberate.** (i) The `settings.identity_coop_enabled` check lives **inside**
  > `_coop_expiry_sweep_job()`, mirroring `_cadence_bot_flag_sweep_job`, so a runtime flag flip takes
  > effect without a process restart. (ii) The `scheduler.add_job(...)` call is **additionally**
  > gated on the same flag at startup, so a flag-OFF process registers no job at all. `_cadence_bot_flag_sweep_job`
  > is registered unconditionally by explicit design rationale (`jobs/scheduler.py:280-288`); 2a
  > deviates because `identity_coop_enabled` is a hard kill-switch on a billing surface where "no job
  > exists" is a stronger guarantee than "the job runs and returns early". Belt-and-braces is
  > intentional, not redundancy to remove. **G-23** asserts the registration call is present and
  > flag-gated.
- [ ] B5. Add `coop_expiry_sweep_interval_minutes: int = 60` to `apps/api/config.py`. Inert while the flag is OFF.

### Step D — Tests

> **Naming rule (M-1 fix — MANDATORY).** `-k` is a per-keyword **substring** match. Every Step-D
> test function name is prefixed **`test_coop_`** and every `-k` selector in `## Verification
> Evidence` is the substring of exactly one of these names. The former names
> `test_ledger_reconciles_exactly` and `test_erased_row_excluded_from_consumption_count` matched
> **NEITHER** their selectors (`coop_ledger_reconciles_exactly`,
> `coop_erased_row_excluded_from_consumption`) **NOR** the module name `test_identity_coop_ledger` —
> the `coop_` prefix broke the substring match and both gates would have exited **5**. Per S-25,
> re-grep every selector at EXECUTE: each must resolve to exactly ONE new test and select **0**
> today.

All tests below live in `tests/integration/test_identity_coop_ledger.py` (module declares
`pytestmark = pytest.mark.integration` — S-26).

- [ ] D1. `test_coop_consumption_count_per_live_site` — **the G-3 test** (was defined only in gate prose, outside the build list — M-1). Per-live-site reconciliation invariant with the **mandatory 5-row `api_usage_logs` fixture (a)-(e) PLUS the mandatory matching `identified_visitors` rows for (a) and (d)** — specified verbatim in the G-3 row and in `### G-3 / G-17 — mandatory identity-side seeding (F3a-1)` — asserting an **EXACT count of 1** (**AC-4 consumption half**). **The identity rows are not dressing:** A2's join is INNER, so an `api_usage_logs`-only fixture makes the expected count 0 and the gate passes on a `return 0` stub (F3a-1).
- [ ] D2. `test_coop_consumption_naive_tz_bounds` — **the G-17 test** (was gate-prose only — M-1). Naive/aware bound normalization per S-22, **plus leg (ii)'s exact in-window count**. Every seeded edge row carries a matching `identified_visitors` row and the expected in-window integer is NON-ZERO (F3a-1 — see `### G-3 / G-17 — mandatory identity-side seeding`).
- [ ] D3. `test_coop_expired_credit_excluded_and_expiry_row_written` — a lot past `expires_at` is excluded from spendable balance AND an `EXPIRE` ledger row explains why (**AC-7**).
- [ ] D4. `test_coop_expiry_sweep_is_idempotent` — running `expire_lapsed_lots` twice writes zero additional rows. **Not sufficient alone** — see G-18 leg 5.
- [ ] D5. `test_coop_ledger_reconciles_exactly` — **the AC-8 property test**: after ≥200 randomized accrue/expire operations, `sum(all ledger amounts for live lots) == spendable_balance(site)` exactly, zero drift (**AC-8**). The expected-value side MUST be computed independently of `spendable_balance()`'s own helper — a `SELECT SUM(amount)` oracle, **NOT "unconditional"** (see G-9 and Constraint 13), plus a harness-tracked running total for ≥50 of the ops.
- [ ] D6. `test_coop_hold_window_blocks_spend` — a lot inside its 24h `spendable_at` hold is not returned by `spendable_lots` and does not count toward `spendable_balance`. (The spend-side half of this assertion moves to Phase 2b.)
- [ ] D7. `test_coop_expiry_never_negative` — **the G-18 test** (was gate-prose only — M-1). It carries **all five mandatory legs specified verbatim in the `### G-18 — five mandatory legs` section** of `## Verification Evidence`: (1) fully-unspent lapsed lot, (2) partially-spent lapsed lot, (3) negative-raw-SUM lot, (4) row-stamp assertion + NULL-stamp negative control, (5) **the positive leg**. Legs 1-4 alone are satisfied by a sweep that never fires; leg 5 is not optional.
- [ ] D8. `test_coop_expiry_sweep_entrypoint_runs_twice` — **the G-20 test (F2a-2 fix; legs rewritten 17-08-26 by F2b-1).** Calls **`run_coop_expiry_sweep(db)`** — NOT `expire_lapsed_lots`. **TWO mandatory legs, both required (see the G-20 row in `## Verification Evidence` for the full rationale):**

  **(a) Lock-release probe — the ONLY assertion that fails on a leak.** Seed lapsed lot #1, call `run_coop_expiry_sweep(db)` once, then assert
  `(await db.execute(text("SELECT pg_advisory_unlock(hashtext('coop_expiry_sweep'))"))).scalar() is False`.
  PostgreSQL returns **false** (plus a warning) when the session holds nothing — so a correctly
  released lock gives `False`, and a **leaked** lock gives `True`. Deterministic, single-session, no
  new harness.

  **(b) Progress leg — separates "ran and skipped" from "wedged".** BEFORE the second call, seed a
  **SECOND** lapsed lot, then call the sweep again and assert the total is **exactly two** EXPIRE
  rows (one per lot). A live call 2 MUST write the additional row; a lock-blocked call 2 writes none.

  > **⚠ TRAP — do not "simplify" this test back to a same-`db` double call with a flat row count.**
  > PG advisory locks are **RE-ENTRANT within a session**, and `tests/conftest.py:149` is a plain
  > `async_sessionmaker` over a `pool_size=5` engine, so a single-tasked test gets the SAME
  > connection = the SAME PG session on call 2 — **not because the pool is LIFO — SQLAlchemy's `QueuePool`/`AsyncAdaptedQueuePool` default is FIFO (`use_lifo=False`, `sqlalchemy/pool/impl.py:79`) and `tests/conftest.py` passes only `pool_size=5`, no `pool_use_lifo` — but because a SINGLE-TASKED test never populates the pool with more than ONE connection, so the only connection available on re-checkout is the one just returned** (M3-1 correction, cycle 3: the former "LIFO pool" mechanism claim was factually WRONG in four places and is retracted) — and `pg_try_advisory_lock`
  > returns TRUE even after a leak. And a flat "exactly one row after each call" assertion is
  > satisfied *identically* by a correct skip and by a wedged early return. That version of this
  > test is vacuous — it was the cycle-2 FAIL (F2b-1).
  >
  > **⛔ SINGLE-SESSION PRECONDITION — MANDATORY, previously UNSTATED (M3-1, cycle 3).** Leg (a)'s
  > validity rests entirely on the probe running on the **same pooled connection** the sweep took the
  > lock on. Therefore **ALL database work in D8 — seeding both lapsed lots, calling
  > `run_coop_expiry_sweep`, the `pg_advisory_unlock` probe, and every row-count query — MUST go
  > through the SINGLE `db` session the test is given.** Opening a second `AsyncSession`, a second
  > engine, or a fresh-session read-back materializes a SECOND pooled connection and **voids leg (a)**
  > (the probe then runs on a connection that never held the lock and returns `False`
  > unconditionally — a permanently-passing assertion). **This trap is live:** the fresh-session
  > read-back pattern is explicitly endorsed elsewhere in this program for Phase 2b. Write the
  > precondition as an inline comment in the test body.
  >
  > **⛔ KEY-DRIFT FORCING FUNCTION — MANDATORY (M3-2, cycle 3).** The probe hardcodes
  > `hashtext('coop_expiry_sweep')` while the implementation locks on its own module-level
  > `_LOCK_KEY`. `pg_advisory_unlock` on a key **nobody holds** returns `False` — the **PASSING**
  > value — so ANY drift between the two makes leg (a) pass unconditionally forever, silently. The
  > test MUST therefore, before the probe:
  > `from apps.api.services.coop_expiry_sweep import _LOCK_KEY` and
  > `assert _LOCK_KEY == "coop_expiry_sweep"`. This is not style — without it leg (a) is one rename
  > away from being vacuous again.

  Leg (b) preserves the entrypoint-inertness coverage G-20 legitimately adds (an inert entrypoint
  writes 0 rows and fails both legs).
- [ ] D9. `test_coop_erased_row_excluded_from_consumption` — see A5 / G-19.
- [ ] D10. `test_coop_duplicate_expire_rejected_by_db` — **the G-21 test (M-3 decision).** Insert a second `EXPIRE` row for the same `lot_id` via **raw SQL, bypassing service code** (Phase 1 precedent for proving a DB-level constraint), and assert the DB raises `IntegrityError` on `uq_coop_ledger_expire_per_lot`.
- [ ] D11. `test_coop_contribution_count_excludes_excluded_reason` — **the G-22 test (L-3 fix).** Seed one `identity_contribution_events` row with `excluded_reason=NULL` and one with `excluded_reason='duplicate'`; assert `contribution_count` returns exactly 1. Without this, a `contribution_count` missing the filter ships green.
- [ ] D12. `test_coop_spendable_lots_fifo_order_and_drawn_subtraction` — **the G-23a test (L-3 fix).** Seed three live lots with **distinct** `expires_at` values (seeded deliberately out of insertion order) plus one partially-drawn lot; assert `spendable_lots` returns them ordered by `expires_at` ASC and that the drawn lot's remaining equals `ACCRUE − drawn` (clamped at 0 per S-4). D6 covers hold-exclusion only and proves nothing about ordering or subtraction.

### Step E — Migration (E2 MANDATORY, E1 conditional)

- [ ] E2. **MANDATORY — partial unique index on EXPIRE (M-3 decision, do not re-open).** Add
  `uq_coop_ledger_expire_per_lot` = a **partial unique index** on `identity_credit_ledger (lot_id)
  WHERE entry_type = 'EXPIRE'`. Ride E1's machinery (LIVE `alembic heads` per S-24, DSN pinned to
  `localhost`, chained onto the observed head, offline-validated with an explicit `<from>:<to>`
  range, round-tripped on a disposable Postgres). **If E1 also fires, put BOTH indexes in this ONE
  migration file — no second file is created (L2-1; Blast Radius and Touchpoints now say the same).**
  Precedent for the shape: `uq_coop_accrued_site_email` in `apps/api/models/identity_coop.py`
  (`postgresql_where=`).

  **Model mirror — MANDATORY, and it is what makes G-21 runnable (F2b-2 fix, 17-08-26).** Mirror the
  index in `CreditLedgerEntry.__table_args__`:
  `Index("uq_coop_ledger_expire_per_lot", "lot_id", unique=True, postgresql_where=text("entry_type = 'EXPIRE'"))`.
  **`tests/conftest.py:133` builds the integration schema with `Base.metadata.create_all`, never
  alembic** — so without the mirror the index does not exist in the test database at all, no
  `IntegrityError` is raised, and **G-21 fails outright**. The Blast Radius row for
  `models/identity_coop.py` is budgeted at ~12 lines to carry it; the former "prose only" wording is
  retracted. Proven by **G-21** (model tier) and **G-15b** (migration tier — the two are different
  proofs, see C-5).

  **The `ON CONFLICT (lot_id) WHERE entry_type = 'EXPIRE' DO NOTHING` clause is MANDATORY, not a
  "should" (C-4/M2-1).** The exact combined statement is written verbatim in the B3 orphan-guard
  block; implement that statement, not a paraphrase.

  > **Rationale — recorded so a future reader does not re-litigate it.** EXPIRE dedup was
  > previously **code-tier only**: a read-compute-skip plus the advisory lock that F2a-1 shows was
  > specified broken. Two sweep runners can therefore both insert `EXPIRE −N` for the same lot — and
  > because S-10b stamps both duplicates with the lot's `[S,E]`, the duplicates are
  > **BALANCE-INVISIBLE**, so **no gate at any tier can see them**. Yet Phase 3's dashboard reads
  > EXPIRE rows **WITHOUT** the balance window predicate and would report `2N` credits lost:
  > durable audit corruption on a billing surface, invisible to every balance assertion.
  > **The precedent is Phase 1's own stated principle** (`models/identity_coop.py:69-74`):
  > *"Enforced as a DB partial unique index, not only in service code, so a concurrent race cannot
  > mint a second credit."* Constraint 2's "no schema change" existed for the **REVERSE vocabulary
  > extension**, which is gone to K-1; Constraint 2 already carves out conditional DDL for E1, and
  > this is the same carve-out. **The advisory lock is hereby demoted to efficiency-only** — the
  > index, not the lock, is the correctness boundary. `expire_lapsed_lots` should use
  > `ON CONFLICT DO NOTHING` on that index so a losing racer is a no-op, not a 500.

- [ ] E1. Only if A4/S-9 showed a seq scan: run `alembic heads` LIVE (S-24), **add the E1 index to the MANDATORY `{rev}_add_coop_expire_unique.py` file (L2-1 — never a second file; the separate `add_coop_ledger_indexes` migration is NOT created).** That file lives under `apps/api/migrations/versions/` (**NOT `apps/api/alembic/versions/`, which does not exist**) and is already chained onto the LIVE observed head per E2/S-24 — E1 adds an `op.create_index`/`op.drop_index` pair to it, it does not chain a second revision. **Literal execution of the retracted "chain a second migration" wording re-creates the two-heads collision class (cycle-3 Gap 5 / adversarial M3-3).** Offline-validate with an explicit `<from>:<to>` range, and round-trip on a disposable Postgres. If no index is needed, record "no E1 covering index required in Phase 2a" in the phase report — **note that E2 still ships regardless**, so "no migration in Phase 2a" is never a valid outcome.

---

## Supplement Checklist (S-items carried into 2a)

Ordering: **Step 1** S-6..S-9 (consumption, no deps) · **Step 2** S-10..S-12 + S-10b/S-10c/S-11 (FIFO
+ EXPIRE + the F-1 stamping fix) · **Step 3** S-4 · **Step 4** S-18..S-26 (test/EXECUTE obligations).

- [ ] S-4. `spendable_lots` clamps per-lot remaining at `max(0, ...)`. Diff budget: **~3 lines**. **Note: this clamp is on `spendable_lots` ONLY — it does not protect the sweep. See S-11.**
- [ ] S-6. Implement `consumption_count` per A1 as a pure on-demand `COUNT` — **no rollup table, no `visitor_aggregator` reuse, no speculative index**.
- [ ] S-7. Write the **per-live-site** reconciliation invariant verbatim into the docstring and the phase report (never a global/historical claim). **Invariant text, amended (L-2 fix):** *"for every site that currently exists, `consumption_count(site)` equals the count of graph-served resolutions recorded for that site, **excluding erased/deleted identities**."* The exclusion clause is not decoration — the unqualified form is **falsified in production** by per-visitor deletion (`routers/visitors.py:449-476` removes the `identified_visitors` row but NOT the `api_usage_logs` row) and by the A2 erasure exclusion. State in the same docstring that the A2 join is **INNER** and that a missing `IdentifiedVisitor` ⇒ the consumption row is excluded, **by design**.
- [ ] S-8. Record the site-delete corollary in the phase report: a deleted site's ledger history vanishes while `User.monthly_identified_count` does not — accepted (counter = enforcement, ledger = attribution).
- [ ] S-9. A4 EXPLAIN evidence: seed a **disposable** Postgres with **≥100k `api_usage_logs` rows of mixed providers** via the new `seed_api_usage_logs` helper (Blast Radius; bulk `INSERT … SELECT generate_series`, not an ORM loop), run `EXPLAIN` on both queries, paste output into the phase report. **Seeding shape is load-bearing (M-5 fix):** **≥50% of the rows must belong to the single probed `site_id`**, and each such row must have a **matching `identified_visitors` row** (same `site_id` + `visitor_id`) so the A2 join path is genuinely exercised rather than joining against an empty relation. Create the E1 index migration **only if** a seq scan appears **on the `api_usage_logs` relation specifically** — a seq scan on the small `identified_visitors`/`suppression_list` relations is the correct plan and does **not** trigger E1 (see A4).
- [ ] S-10. Keep the read-time `expires_at` filter as the correctness backstop **in addition to** the explicit EXPIRE sweep — both, never one. **`spendable_balance`'s query shape (`identity_coop.py:242-247`) MUST NOT change** (Constraint 11).
- [ ] S-10b. **F-1 fix — lot-symmetric stamping.** Every non-ACCRUE row is written with the **source lot's** `spendable_at` AND `expires_at` copied verbatim, in addition to the lot's `site_id` and `lot_id`. In 2a this applies to `expire_lapsed_lots`. **Phase 2b inherits the identical obligation for `spend_credits`.** Without it, every normal expiry drives the site's balance to `−N` on the billing surface. Diff budget: **~3 lines**.
- [ ] S-10c. **Correct the prose, never the query.** `apps/api/models/identity_coop.py` contains **THREE** `# ACCRUE only —` comments; **exactly two are amended** (Gap 5 fix — the former "two comments / three line numbers" text was internally inconsistent). **Locate by column name, never by line** (S-25):
  - **`spendable_at`** — `# ACCRUE only — created_at + coop_credit_hold_hours (provisional hold).` → **AMEND** to state the P2-D5 stamping rule (non-ACCRUE rows copy the source lot's value; NULL on a non-ACCRUE row is a defect, per Constraint 12).
  - **`expires_at`** — `# ACCRUE only — created_at + coop_credit_expiry_days.` → **AMEND** identically.
  - **`contribution_event_id`** — `# ACCRUE only — provenance back to the contribution event.` → **CORRECT AS-IS. DO NOT TOUCH.** Only an ACCRUE row has a contribution event; EXPIRE and SPEND genuinely have none.
- [ ] S-11. `expire_lapsed_lots` writes one `EXPIRE` row per lapsed lot with a positive **window-blind** remainder, `amount = -max(0, remaining)` (definition restated verbatim in B3), **stamped per S-10b**; idempotent (AC-7 / D4). **`max(0, …)` is load-bearing:** for a lot whose raw SUM has gone negative, a literal `amount = -remaining` would write a **positive** EXPIRE, violating the `amount` column contract (locate by the `# Positive for ACCRUE; negative for SPEND and EXPIRE.` comment). The S-4 clamp does **not** cover this path. Skip the row entirely when `max(0, remaining) == 0` (keeps idempotence).
- [ ] S-12. Docstring `spendable_balance`: **held lots EXCLUDED** (unchanged Phase 1 behavior); "pending (in hold)" is Phase 3. Merge this edit with S-10c so the docstring is rewritten once, and state the AC-8 oracle precondition (clock past every lot's `spendable_at`) in the same docstring so a future reader cannot re-derive the invalid unconditional oracle.
- [ ] S-13a. **Defensive live check (the surviving half of S-13; the rest is Phase 2b).** Confirm at EXECUTE that `IdentifiedVisitor.email_bidx` is non-NULL for the rows the A2 exclusion touches (07-08-26 prod backfill was 22/22, 0 remaining — this is confirmation, not discovery).
- [ ] S-18. Every test that flips a site's `contribution_enabled` ON MUST use the pytest `monkeypatch` fixture to set `identity_coop_enabled=True` for the **whole test function** (Constraint 10 / inherited constraint b) — never bare `setattr`.
- [ ] S-19. **"Control the effective hold/expiry TIMESTAMPS", never "control the clock".** The D5/G-9 property test must guarantee that, before EVERY reconciliation assert, effective `now` is past **every** lot's `spendable_at` and every lot's position relative to its `expires_at` is deterministic. **"Control the clock" is RETRACTED as unimplementable:** `grep -rn "freezegun\|freeze_time\|time_machine"` over `requirements.txt`, `tests/`, `apps/` returns **zero hits**; `requirements.txt` is not in the Blast Radius, so adding one would trip the S-25 budget sweep. **The two SANCTIONED mechanisms, either or both:** (i) `monkeypatch.setattr(settings, "coop_credit_hold_hours", 0)` — read at call time (`identity_coop.py:194`), so the monkeypatch takes effect; (ii) explicitly seeded past `spendable_at` values (precedent `tests/integration/test_identity_coop_contribution.py:384-412`).
- [ ] S-20. Conditional E1 migration: re-derive `alembic heads` LIVE with `DATABASE_URL` pinned to `localhost`. Round-trip on a disposable Postgres.
- [ ] S-21. **C-6 — sweep placement follows repo convention, not the Celery package.** Body in **`apps/api/services/coop_expiry_sweep.py`** as `async def run_coop_expiry_sweep(db)`; `_coop_expiry_sweep_job()` wrapper in `apps/api/jobs/scheduler.py` doing the `settings.identity_coop_enabled` check INSIDE the wrapper, opening the session via `async_session()`, and swallowing top-level crashes with `logger.exception(...)` — copying the **`_cadence_bot_flag_sweep_job` symbol** (defined at `jobs/scheduler.py:273-297`; the former `:258-283` citation was **STALE** — that range is mostly `_intent_signal_sweep_job` at `:256`. Gap 3 fix; per S-25, locate by symbol, never by line), registered via `scheduler.add_job(..., "interval", minutes=settings.coop_expiry_sweep_interval_minutes, id="coop_expiry_sweep", replace_existing=True, jitter=..., misfire_grace_time=300)` alongside the sibling registrations at `:685-700`. **Pattern verified against live source 17-08-26.**

  > **S-21 ⇄ B3b contradiction — RESOLVED (F2a-1 fix). Read both halves; they are now one design.**
  > `_cadence_bot_flag_sweep_job` takes **NO advisory lock** — it is a shape precedent, **not** a
  > lock precedent. **The wrapper copies the SHAPE ONLY** (flag check inside, `async_session()`,
  > `logger.exception` crash swallow) and takes no lock. **The lock lives one level down, inside
  > `run_coop_expiry_sweep(db)`**, as the mandatory `_try_acquire_lock` / `_release_lock`
  > (`pg_try_advisory_lock` / `pg_advisory_unlock`) **pair in a `try/finally`**, with an explicit
  > early return when the lock is not acquired — following `services/reengagement.py:246`/`:258`,
  > `services/retention.py:64`/`:77`, `services/daily_digest.py:462`/`:474`,
  > `services/referral_activation.py:59`/`:71`. **Acquire without release is a defect** —
  > `pg_try_advisory_lock` is session-scoped and survives the per-lot commit. Full rationale and
  > the four precedent call sites: the LOCK block under **B3b**. Proven by **G-20**.
- [ ] S-22. **C-7 — naive/aware datetime mismatch.** `api_usage_logs.created_at` is a **naive** `DateTime` (`models/api_usage.py:48`, `server_default=func.now()`), while the coop ledger is `DateTime(timezone=True)`. Normalize BOTH range bounds of every `api_usage_logs` comparison to **naive UTC** via `.replace(tzinfo=None)` on a `datetime.now(timezone.utc)`-derived value (precedent: `apps/api/routers/visitors_helpers.py:272,276-277` — package path is `routers/`, not `services/`). Never pass a tz-aware bound into that filter. Proven by **G-17**.
- [ ] S-23. **Unit-lane baseline is an EXECUTE-time obligation, not an assumption.** Before adding any test, run `.venv/bin/python3.11 -m pytest tests/unit -q` and record the ACTUAL pass/skip counts in the phase report. Any remembered baseline is stale — treat a delta as a finding to investigate, never as noise, and re-baseline G-11's expected figure from the observed run.
- [ ] S-24. **Live alembic head re-derivation (EXECUTE-time, pinned DSN).** Before any migration work, re-derive the head LIVE with `DATABASE_URL` pinned to `localhost` — do not chain off a remembered value. Live head 16-08-26 was `a8c2f47e91b6` (single head; previously-untracked migrations are now tracked), but re-derive anyway. **CONFIRMED MANDATORY at cycle 3 (C3-7): the live head was NOT re-derived during this PVL cycle and any value written in this plan is therefore presumed STALE. S-24's pinned-DSN LIVE re-derivation at EXECUTE is the control that closes this — it is not optional, not skippable on a remembered value, and E2/E1 chain off its OUTPUT, never off a head recorded here.**
- [ ] S-25. **Budget / cross-reference sweep, EXECUTE-time.** After implementation, diff each touched file against its Blast Radius budget and record actual-vs-budget in the phase report; flag any file exceeding budget as a scope finding before proceeding to the gates. **Re-anchor every S-*/G-* citation by unique symbol or string before editing** — line numbers in this plan drift by up to ~6 lines and one package path was wrong; locate by string, never by line. Then re-grep every `-k` selector and confirm each resolves to the intended new test (pytest exits **5**, not 0, on a zero-match `-k` — that is the gate set's non-vacuity property).
- [ ] S-27. **(NEW, 17-08-26 cycle 2 — M2-2)** Record `coop_expiry_sweep` in the existing advisory-lock audit set at `process/general-plans/active/capacity-hardening_25-07-26/transaction-pooler-advisory-lock-audit_NOTE_25-07-26.md` (append one row: sweep name, lock key `coop_expiry_sweep`, session-scoped, per-lot commit → connection-swap residual ACCEPTED, correctness boundary is `uq_coop_ledger_expire_per_lot`). Diff budget: **~3 lines in that note**. This is bookkeeping in an already-active general plan, not a new artifact.
- [ ] S-26. **The `integration` marker is NOT applied by directory in this repo.** `pyproject.toml:7` only *registers* the marker; there is **no `collection_modifyitems` hook** in `tests/conftest.py`. Every integration file declares it by hand (precedent: `tests/integration/test_identity_coop_contribution.py:45`). **`tests/integration/test_identity_coop_ledger.py` MUST declare `pytestmark = pytest.mark.integration` at module level.** Without it every `-m integration` gate deselects the new tests and the gates exit 5. Diff budget: **1 line**.
- [ ] S-3. `phase-blast-radius-registry.md` — **VERIFY-ONLY unless missing (Gap 6 fix).** The dated 17-08-26 `### Phase 2a — Consumption aggregation + FIFO expiry` claim **already exists** at `phase-blast-radius-registry.md:151-194` (confirmed 17-08-26). At EXECUTE: **verify it is present and accurate** against this plan's final Blast Radius, and **append only if missing**. If present but stale (e.g. missing the two files added by this supplement cycle — the `seed_api_usage_logs` helper and the mandatory `{rev}_add_coop_expire_unique.py` migration), **amend the existing block in place; do NOT append a duplicate claim**. Diff budget: **0-4 lines** — 0 when present-and-accurate, ~4 to amend in place. **This figure is authoritative and now matches the Blast Radius row verbatim (L3-4, cycle 3).**

---

## Phase 2a Decisions (carried verbatim)

### P2-D2 — Consumption is a pure on-demand COUNT

Read-only `COUNT` over `api_usage_logs` by site + provider + date range, computed at read time.

- **No rollup table** — that would be a new write surface (violates the phase guardrail) and a
  second reconciliation target.
- **No reuse of `visitor_aggregator`** (different domain). **No speculative index.**
- **A4 tightened:** EXECUTE MUST produce `EXPLAIN` evidence against a **disposable** Postgres seeded
  with **≥100k `api_usage_logs` rows of mixed providers**. The conditional E1 index migration is
  created **only if** that EXPLAIN shows a seq scan. Existing indexes:
  `idx_api_usage_site_created (site_id, created_at)`, `idx_api_usage_category_created`,
  `idx_api_usage_provider` (`models/api_usage.py:24-60`).
- **No retention horizon.** `retention.py` purges only `events` / `agent_fetch_events` /
  `request_logs` — it never touches `api_usage_logs`. But **site delete removes it**
  (`routers/sites.py:328`) in the SAME tuple as the two spendable co-op tables (`:337-341`).
- **Reconciliation invariant is per-live-site, never global:** *"for every site that currently
  exists, `consumption_count(site)` equals the count of graph-served resolutions recorded for that
  site"* — quantified over existing sites **at assertion time**. A global historical claim is
  falsified by site delete.
- **Corollary to record:** a deleted site's ledger history vanishes while `User.monthly_identified_count`
  does not. Acceptable — the counter is the enforcement record; the ledger is attribution.

### P2-D4 — Exit gate uses the UNMARKED unit lane

`.venv/bin/python3.11 -m pytest tests/unit -q`, matching Phase 1's actual gate. `-m unit` selects
only a subset and deselects ~963 — false confidence on a billing surface. Integration stays
`-m integration`, run **serialized** (shared `retarget_agent_test` DB), with **no stray local Redis
on 6379**. Re-baseline the expected counts at EXECUTE per S-23.

### P2-D5 — Explicit idempotent EXPIRE sweep, with LOT-SYMMETRIC STAMPING

**The defect this closes (F-1).** Phase 1's SHIPPED `spendable_balance`
(`apps/api/services/identity_coop.py:242-247`) is a **flat row-filtered SUM**, not a per-lot
computation:

```
(spendable_at IS NULL OR spendable_at <= now) AND (expires_at IS NULL OR expires_at > now)
```

Under the old "non-ACCRUE rows carry NULL hold/expiry and therefore ALWAYS count" contract, a lapsed
lot's ACCRUE (+N) is **already filtered out** by `expires_at > now`, while the new EXPIRE row
(−N, NULL `expires_at`) **always counts** → balance = `0 + (−N) = −N`. Every normal expiry would
silently drive the site's balance negative on the billing surface.

**The fix: stamp every non-ACCRUE row with the SOURCE LOT's `spendable_at` AND `expires_at`.**
`spendable_balance`'s filter shape is **NOT changed** (Constraint 11 — covered by shipped green tests
at `test_identity_coop_contribution.py:380` and `:417`); instead the offsetting rows enter and leave
the filtered window **in lockstep with the lot they offset**.

**The stamping rule (entry kinds live in 2a; SPEND is Phase 2b's identical obligation):**

| Entry kind | `lot_id` | `spendable_at` | `expires_at` | Rationale |
|---|---|---|---|---|
| `ACCRUE` | own id | `created_at + coop_credit_hold_hours` | `created_at + coop_credit_expiry_days` | unchanged Phase 1 behavior |
| `EXPIRE` | the lapsed ACCRUE lot | **copied from that lot** | **copied from that lot** | the zeroing row must vanish together with the +N it zeroes — this is the F-1 fix |
| `SPEND` *(Phase 2b)* | the drawn ACCRUE lot | **copied from that lot** | **copied from that lot** | a spend must be visible exactly while the lot it drew from is visible; if the lot leaves the window, its −k must leave too |

**The stamping algebra — three-interval walk (verbatim, do not re-derive).** For a lot with ACCRUE
+N, hold `S`, expiry `E`, and a spend of `k`:

- before `S` — ACCRUE filtered out (held); SPEND cannot exist (a held lot is unspendable);
  contribution **0** ✓
- between `S` and `E` — ACCRUE `+N` counted, SPEND `−k` counted (same stamps); contribution
  **`N − k`** ✓
- after `E` — ACCRUE, SPEND and the EXPIRE `−(N−k)` are **all** filtered out together;
  contribution **0** ✓ (under the old rule this was `−(N−k)`)

Any other choice breaks a leg: leaving SPEND unstamped makes the post-expiry contribution `−k`;
leaving EXPIRE unstamped is F-1 itself. A stamped SPEND does **not** "un-spend" credits at expiry —
the `+N` it offsets disappears in the same instant, so the net stays 0.

**Why keep the explicit EXPIRE row at all.** Under stamping the EXPIRE row is stamped `[S,E]` and is
written only once `now ≥ E`, so it is invisible to `spendable_balance` in **every** interval — the
oracle returns 0 for a lapsed lot with or without it. The row is kept for **audit / reporting only**:
it is the durable record of *how many credits a site lost, and on what date*, which Phase 3's
dashboard reads directly by querying EXPIRE rows **without** the balance window predicate. The
read-time `expires_at` filter **STAYS** as the correctness backstop — a lapsed lot is unspendable
immediately, before its EXPIRE row lands. Both, never one. **Consequence for G-18:** its
`balance == 0` half would also pass with no sweep at all, so the gate's non-vacuity rests entirely on
the per-row stamp assertion, the NULL-stamp negative control, **and the leg-5 positive proof (F5-2)**
— all three are mandatory.

**The AC-8 oracle is NOT unconditional.** `coop_credit_hold_hours = 24` (`config.py:483`) and
`spendable_balance` **EXCLUDES held lots**. A fresh ACCRUE is therefore in an unconditional SUM but
out of the balance, so an unconditional oracle is algebraically invalid and a **correct**
implementation would fail G-9 — pressuring EXECUTE to damage source or gut the test. The word
"unconditional" is **retracted**. The precondition is mandatory and stated in the gate text itself:

> **G-9 oracle precondition (mandatory, not optional):** before **every** reconciliation assert, the
> effective hold/expiry TIMESTAMPS must be controlled so `now` is past **every** lot's
> `spendable_at` and each lot's position relative to its `expires_at` is deterministic. Only then
> does `SUM(amount)` over the lot-window predicate equal `spendable_balance`. The former alternative
> *"OR run `expire_lapsed_lots` before each assert"* is **DELETED**: running the sweep does nothing
> about the 24h hold.

---

## Inherited Constraints From the Phase 1 Supplement (must be absorbed)

| # | Constraint |
|---|---|
| a | **Site-delete cascade** deletes `identity_contribution_events` + `identity_credit_ledger` (`routers/sites.py:337-341`); consent acceptances are RETAINED **by design** — do not "fix". `api_usage_logs` is deleted in the same tuple (`:328`). |
| b | **422 gate:** `contribution_enabled=True` raises 422 when `settings.identity_coop_enabled` is False, **before** the digest check (`routers/sites.py:429-433`). Any test flipping a site ON MUST monkeypatch the global flag True for the **whole test function** via the pytest `monkeypatch` fixture — **never bare `setattr`**. |
| c | **Tombstone-at-enqueue:** `SuppressionEntry(scope="erased")` now means "erasure REQUESTED or completed". Any erased-row exclusion inherits the wider meaning (excludes more, sooner). |
| d | **`coop_terms_version` is a PLACEHOLDER digest.** Legal review + re-pin required before ANY flag flip (`phase-blast-radius-registry.md:142-144`, `coop-terms-repin_RUNBOOK_16-08-26.md`). **Phase 2a must not assume a flag can be flipped for a live gate.** |
| e | Inherited accepted known-gap: multi-process concurrency on the H2 enqueue→sweep window is ungated. |

---

## Constraints (hard, non-negotiable)

> **Numbering note.** The numbers are STABLE IDENTIFIERS cited elsewhere in this plan, in Phase 2b,
> in the K-1 backlog note, and in the validate-contracts. Items that moved to Phase 2b (9, 12b, 16,
> 17) or to K-1 (12's REVERSE clause) are **removed here rather than renumbered**. Do NOT renumber.

1. **All flags stay OFF.** `identity_coop_enabled` and every site's `contribution_enabled` remain OFF; production exposure is NONE. Constraint (d) means a live flag-on gate is not even available.
2. **No VOCABULARY change in Phase 2a; DDL is limited to two named indexes (amended by M-3).** `LEDGER_ENTRY_TYPES` stays `("ACCRUE","SPEND","EXPIRE")` — the REVERSE vocabulary extension is dropped to K-1, and **that dropped extension was the entire original rationale for this constraint**. Permitted DDL, exhaustively: (i) the **MANDATORY** `uq_coop_ledger_expire_per_lot` partial unique index (E2 — see the M-3 rationale block there); (ii) the **CONDITIONAL** E1 covering index, created only on S-9 seq-scan evidence against `api_usage_logs`. This constraint already carved out (ii); (i) is the same carve-out for the same reason, and it directly implements Phase 1's stated principle (`models/identity_coop.py:69-74`) that a uniqueness rule is *"enforced as a DB partial unique index, not only in service code, so a concurrent race cannot mint a second credit."* **No table, no column, and no enum value may be added or altered.**
3. **`DATABASE_URL` pinning is mandatory** for every alembic or DB-script invocation (`.env` points at Supabase PROD; `migrations/env.py` has no guard).
4. **Integration runs are SERIALIZED** (shared `retarget_agent_test`); **no stray local Redis on 6379**.
5. **`git diff HEAD -- apps/api/services/identity_resolver.py` must stay EMPTY** — exit gate G-13.
6. **`Site.daily_resolution_budget` (`models/site.py:23`) is untouched.**
7. **No new write surface on the consumption read path.** If aggregation appears to need a column, STOP and re-plan.
8. **No `user_id` column on the ledger; no per-site monthly gate** (Phase 1 D-D freeze). The D-D user-pooling *application* is Phase 2b.
10. **Every flag-flipping test uses the `monkeypatch` fixture for the whole function**, never bare `setattr`.
11. **`spendable_balance`'s query shape is frozen** (`identity_coop.py:242-247`, covered by shipped green tests at `test_identity_coop_contribution.py:380,417`). The F-1 fix is WRITE-side stamping only. Prose/docstrings are corrected; the query is not.
12. **Every non-ACCRUE ledger row carries its source lot's `spendable_at`/`expires_at`.** In 2a that means EXPIRE; Phase 2b inherits it for SPEND. NULL on a non-ACCRUE row is a defect, not a default.
13. **The AC-8 oracle is never "unconditional."** Any reconciliation assert made without first controlling the **effective hold/expiry timestamps** past every lot's `spendable_at` is invalid and must not be written. **"Control the clock" is retracted** — no freezegun/time-machine exists in this repo; the only sanctioned mechanisms are `monkeypatch.setattr(settings, "coop_credit_hold_hours", 0)` and explicitly seeded past `spendable_at` values.
14. **No gate may require a real deployment flag flip** (K-3 — `coop_terms_version` placeholder pending legal re-pin). `monkeypatch` for the whole test function is the only legitimate substitute.
15. **The expiry sweep follows repo convention** — body in `services/coop_expiry_sweep.py`, wrapper + registration in `jobs/scheduler.py`. The Celery `apps/api/tasks/` package is out of scope.
18. **The ledger test file lives in `tests/integration/`.** No unit-lane ledger test file may be created — `tests/unit/` has no real database session.

---

## Exit Gate

```bash
# Unit lane — UNMARKED (P2-D4). Re-baseline counts at EXECUTE per S-23.
.venv/bin/python3.11 -m pytest tests/unit -q
# Precondition: no stray local Redis on 6379 (documented self-poisoning hazard).
#
# ⚠ OPS FACT + PRECONDITION CONFLICT — RESOLVED (recorded 17-08-26). Docker/PG/Redis are UP on this
# machine: :5433 and :6379 are LISTENING and ~/.docker/run/docker.sock exists, so the Hybrid tier is
# runnable TODAY (Docker CLI is off PATH — detect with `lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`,
# never `which docker`). But a LISTENING :6379 VIOLATES this unit lane's own "no stray local Redis"
# precondition (memory note `unit-tests-assume-no-local-redis`: some unit tests self-poison db15).
# RESOLUTION — the precondition is SCOPED TO THE RUN THAT NEEDS IT, not to the session:
#   1. Run the INTEGRATION lane first, WITH Redis up (it requires :6379).
#   2. Then STOP the Redis container — it is `infra-redis-1` (Postgres is `infra-postgres-1`), and the
#      Docker CLI is OFF PATH at /Applications/Docker.app/Contents/Resources/bin/docker:
#        /Applications/Docker.app/Contents/Resources/bin/docker stop infra-redis-1
#      Run the UNIT lane with :6379 closed. Verify closed via the lsof check above BEFORE running;
#      record the verification in the phase report.
#   3. Restart afterwards (leave-as-found):
#        /Applications/Docker.app/Contents/Resources/bin/docker start infra-redis-1
# A unit-lane run performed with :6379 listening is NOT a valid G-11 green — re-run it, do not
# rationalize the deltas as noise (S-23).

# Integration lane — run SERIALIZED (conftest shares `retarget_agent_test`). Needs PG :5433 + Redis 6379.
# Docker CLI: /Applications/Docker.app/Contents/Resources/bin/docker
.venv/bin/python3.11 -m pytest tests/ -m integration -q
# Expected: exit 0

# Read-path purity guard — no new write surface added to the consumption path
git diff HEAD --quiet --exit-code -- apps/api/services/identity_resolver.py
# Expected: exit 0

# Billing purity guard (NEW at the split) — Phase 2a must not touch the spend surface
git diff HEAD --quiet --exit-code -- apps/api/services/billing.py apps/api/routers/billing.py
# Expected: exit 0

# Migration validation — E2 is MANDATORY (always runs); E1 is conditional and may share the file.
# MANDATORY: pin DATABASE_URL to localhost first — bare alembic hits Supabase PROD via .env.
DATABASE_URL='postgresql+asyncpg://...@localhost:5433/...' alembic -c apps/api/alembic.ini heads
DATABASE_URL='postgresql+asyncpg://...@localhost:5433/...' alembic -c apps/api/alembic.ini upgrade <recorded_head>:head --sql
# Expected: single head; exit 0
# Plus a live down/up round-trip on a DISPOSABLE Postgres proving `uq_coop_ledger_expire_per_lot`
# drops and recreates cleanly (partial unique index — `postgresql_where`). This round-trip is
# **gate G-15b** in `## Verification Evidence` (mandatory, always runs) — it is no longer prose-only.
```

- All checklist items checked.
- AC-8 property test passes with ≥200 randomized operations, zero drift.
- **G-18 leg 5 (positive expiry proof) is green** — a normal lapsed lot yields exactly one EXPIRE row.
- **G-20 is green on BOTH legs** — (a) `SELECT pg_advisory_unlock(hashtext('coop_expiry_sweep'))` returns **`False`** after call 1 (**this**, and only this, fails on a LEAKED lock — but note the corrected scope: leg (a) gates the POST-CONDITION only, so a no-lock-at-all implementation also passes it; acquisition is ungated and accepted, adjacent to K-2 — C3-1); (b) with a SECOND lapsed lot seeded before call 2, the sweep yields **exactly two** EXPIRE rows total (proves the entrypoint actually fires rather than being wedged or inert). The former claim that a same-session double call proved lock release was **FALSE** and is retracted (F2b-1).
- **G-15b is green** — the E2 migration offline-validates over an explicit `<from>:<to>` range AND round-trips down/up on a disposable Postgres. E2 is unconditional, so "no migration was run in 2a" is never a valid outcome.
- **G-21 is green** — a raw-SQL duplicate `EXPIRE` for the same `lot_id` is rejected by `uq_coop_ledger_expire_per_lot`.
- **G-22 / G-23 are green** — `contribution_count` honours `excluded_reason`; `spendable_lots` orders FIFO and subtracts drawn (a); the `add_job(id="coop_expiry_sweep")` registration exists per grep (b); and the **Agent-Probe** read confirming that `add_job` call sits inside the `identity_coop_enabled` guard is recorded in the phase report (c — split out from (b) by L2-3, because lexical scope is not grep-decidable).
- The unit lane was run with **:6379 closed**, verified by `lsof` and recorded in the phase report.
- `Site.daily_resolution_budget` provably untouched.
- Both billing files show an empty diff.
- Phase report written to the report destination above.

---

## Acceptance Criteria

- **AC-4 (partial — consumption half)** — a graph-served resolve is counted by `consumption_count`; a provider-purchased resolve is not. *(The "does not increment provider spend" symmetric half is proven in Phase 2b's spend gates.)*
- **AC-7** — a credit past its 90-day expiry is excluded from spendable balance AND an `EXPIRE` ledger row explains why; the sweep is idempotent AND **non-vacuous** (writes exactly one row for a normal lapsed lot).
- **AC-8** — after ≥200 randomized accrue/expire operations, `sum(ledger) == spendable balance` exactly, zero drift.
- SPEC A interface obligation: erased rows are excluded from `consumption_count`.
- `apps/api/services/identity_resolver.py` diff is EMPTY for this phase.
- `apps/api/services/billing.py` and `apps/api/routers/billing.py` diffs are EMPTY for this phase.
- **AC-7 entrypoint half** — `run_coop_expiry_sweep(db)` itself provably fires and is re-entrant within one process (G-20); a duplicate `EXPIRE` for a lot is rejected by the DB, not merely skipped by service code (G-21).
- `contribution_count` excludes `excluded_reason` rows (G-22); `spendable_lots` is FIFO-ordered with drawn amounts subtracted (G-23a).
- **AC-6 (spend ledger row) is NOT in 2a's scope** — it is Phase 2b's exit criterion.

---

## Phase Completion Rules

- 🔨 **CODE DONE** — all checklist items checked, no test evidence yet.
- 🧪 **TESTING** — both pytest lanes running; failures fixed inline.
- ✅ **VERIFIED** — both lanes exit 0 including the AC-8 property test at zero drift and G-18 leg 5, the resolver and billing diffs are empty, and the validate-contract is written (non-placeholder).
- 🚧 **BLOCKED** — the erased-row exclusion would require a new write surface on the read path.
- AC-8 drift is a correctness blocker, never a known-gap.
- **A green G-18 without leg 5 does NOT satisfy AC-7** (F5-2).
- **A green G-18 without G-20 does NOT satisfy AC-7 either** (F2a-2) — G-18 proves `expire_lapsed_lots`; only G-20 proves the sweep entrypoint (leg b) and the lock post-condition (leg a — it fails an acquire-without-release, but does NOT prove the acquire happened at all; C3-1, accepted adjacent to K-2). **A G-20 run that omits leg (a), or that uses a same-`db` double call with a flat row count, does NOT prove lock release at all** (F2b-1) and does not satisfy AC-7's entrypoint half.
- **G-15b is mandatory for ✅ VERIFIED.** E2 ships unconditionally, so "no migration round-trip was run" is never a valid 2a outcome.

---

## Blockers That Would Justify BLOCKED Status

- The erased-row exclusion join (A2) turns out to require a new column on `api_usage_logs` — that would be a new write surface on the read path. Stop, record, and re-plan rather than adding it. (VALIDATE 07-08-26: not the case — a join through `identified_visitors` is feasible without any new column.)
- Docker unavailable ⇒ the migration round-trip and every Hybrid gate cannot run. Known-Gap + backlog stub; keep the gate **CONDITIONAL**. **Verify the premise before claiming it (17-08-26): Docker IS up on this machine** — `:5433` and `:6379` are listening and `~/.docker/run/docker.sock` exists; the CLI is merely off `PATH` at `/Applications/Docker.app/Contents/Resources/bin/docker`. Detect with `lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`, **never** `which docker`. A Docker-unavailable BLOCKED claim not backed by a fresh `lsof` check is not acceptable.
- The AC-8 property test cannot reach zero drift — this is a correctness blocker, not a known-gap.

---

## Phase Loop Progress

- [ ] 1. RESEARCH — research-agent: Phase 1 report read; `api_usage_logs` write path re-confirmed; test context loaded
- [ ] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: this plan updated; Inner Loop Refresh Note if sections changed
- [ ] 4. PVL — vc-validate-agent: full V1-V7 **from V1 against the narrowed 2a scope**; validate-contract written
- [ ] 5. EXECUTE — all checklist items done; per-section test gates run and green
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** A placeholder `## Validate Contract` = blocked. Every
contract below this line is **SUPERSEDED by the 17-08-26 split**.

---

## Touchpoints

Identical to the Blast Radius table above — this is a derived view and must never disagree with it
(the cycle-5 F5-3 disagreement is what forced this reconciliation).

**MODIFIED / NEW (10 files):** `apps/api/models/identity_coop.py` (**S-10c prose + the E2 index mirror in `__table_args__`, ~12 lines — NOT prose-only; F2b-2**),
`apps/api/services/identity_coop.py`, `apps/api/services/coop_expiry_sweep.py` (NEW),
`apps/api/jobs/scheduler.py`, `apps/api/config.py`, `phase-blast-radius-registry.md`
(**verify-only unless missing** — S-3), `tests/integration/test_identity_coop_ledger.py` (NEW),
the `seed_api_usage_logs` helper (NEW — G-4),
`apps/api/migrations/versions/{rev}_add_coop_expire_unique.py` (**NEW, MANDATORY**),
`apps/api/migrations/versions/{rev}_add_coop_ledger_indexes.py` (**CONDITIONAL content, never a
separate file — per L2-1 the E1 index is folded into the mandatory migration above when it fires**).

**READ ONLY:** `apps/api/models/api_usage.py`, `apps/api/services/usage_logger.py`,
`apps/api/models/visitor.py` (`IdentifiedVisitor.email_bidx` join key for A2),
`apps/api/models/suppression.py` (`SuppressionEntry.email_hash` join key for A2),
`apps/api/services/identity_resolver.py` (empty-diff exit gate).

---

## Public Contracts

- `api_usage_logs` write path UNCHANGED — consumption is read-only.
- `apps/api/services/identity_resolver.py` UNCHANGED (empty diff is an exit gate).
- `apps/api/services/billing.py` / `apps/api/routers/billing.py` UNCHANGED in 2a (empty diff is an exit gate) — all billing wiring is Phase 2b.
- `Site.daily_resolution_budget` semantics UNCHANGED.
- `LEDGER_ENTRY_TYPES` UNCHANGED — no vocabulary change ships in 2a.
- `spendable_balance`'s query shape UNCHANGED (Constraint 11); its **write-side inputs** change (stamped EXPIRE rows).
- New internal service functions only; no new HTTP surface in this phase.
- New scheduled job `coop_expiry_sweep`, inert while `identity_coop_enabled` is OFF.

---

## Verification Evidence

Gate IDs are **stable identifiers** preserved across the split (see the Numbering note). Gates that
moved to Phase 2b — **G-5, G-6, G-7, G-8, G-10, G-14, G-16** — and to K-1 — **G-1, G-2** — are
deliberately absent here.

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| **G-3** `-k "coop_consumption_count_per_live_site"` (test `test_coop_consumption_count_per_live_site`, D1) — per-live-site invariant holds. **MANDATORY 3-row provider fixture + EXACT-count assertion (H-1 fix — the former "non-zero count" wording did NOT force the `provider` filter).** For the probed site the fixture MUST seed: (a) **≥1 `provider='beam_identity_network'`, `category='identity'`, `success=True` row — COUNTED**; (b) **≥1 paid-provider row with `cost_usd > 0`** (e.g. `people_data_labs`) — **NOT counted**; (c) **≥1 OTHER `OWNED_FREE_PROVIDERS` row, e.g. `provider='form_capture'`, `category='identity'`, `cost_usd=0.0`** — **NOT counted**. Assert the **EXACT** expected integer, never `> 0`. **Why (c) is the load-bearing row:** `OWNED_FREE_PROVIDERS` = `{form_capture, fingerprint_match, beam_identity_network, svid_reconcile}` and **all four write `category='identity'` with `cost_usd=0.0`** — so an implementation filtering on `category` alone (or on `cost_usd = 0`) counts the other three plus every paid-provider `api_usage_logs` mirror, and **the paid row (b) alone does NOT catch it**. The nearest confusables are the other owned-free providers, not the paid ones. The consequence of missing this lands in Phase 2b as a co-op credit **overcharge**. **TWO MORE ROWS ARE MANDATORY (F3 fix, 17-08-26) — the `site_id` predicate is otherwise unforced:** rows (a)-(c) all sit on the probed site and conftest gives each test a fresh `drop_all`/`create_all` database, so the DB contains ONLY what the test seeds — an implementation with **no `site_id` filter at all** still hits the exact count. Add: **(d) ≥1 `provider='beam_identity_network'`, `category='identity'`, `success=True` row on a SECOND site — NOT counted**; **(e) ≥1 otherwise-identical row with `site_id = NULL` — NOT counted** (`api_usage_logs.site_id` is **NULLABLE** — `apps/api/models/api_usage.py:35`, "account-wide calls without a site can still log"). Keep the EXACT-count assertion. **⛔ MANDATORY: the `identified_visitors` side of the A2 INNER join must also be seeded, and the expected EXACT count is 1 (NON-ZERO) — see `### G-3 / G-17 — mandatory identity-side seeding (F3a-1)` below. Without it this whole fixture is vacuous: every row is dropped by the INNER join, the assertion resolves to 0, and a `return 0` stub passes.** **Why this is the same class as H-1, one predicate over:** unscoped counting inflates every site with other tenants' rows AND account-wide rows — a cross-tenant billing **overcharge** in Phase 2b. **`success`/`category` axes are deliberately NOT varied on the beam provider and need no rows:** `_log_owned_resolution` (symbol at `identity_resolver.py:1515`) hardcodes `category="identity", success=True` for every owned write, so those two predicates are **production-vacuous given the `provider` predicate** — a synthetic row varying them would gate a shape that cannot occur. Recorded so a later reviewer does not re-raise it. | Hybrid (PG :5433, serialized) | AC-4 (consumption half) / P2-D2 — **the `provider='beam_identity_network'` filter AND the `site_id` scoping predicate** |
| **G-4** `EXPLAIN` output for both aggregation queries against a disposable PG seeded ≥100k mixed-provider rows via the **new budgeted `seed_api_usage_logs` helper** (Blast Radius, ~30 lines, bulk `INSERT … SELECT generate_series` — C2a-2/Gap 7 fix: the helper is now budgeted rather than assumed), **≥50% of rows on the probed site each with a matching `identified_visitors` row** (M-5), pasted into the phase report | Hybrid (disposable PG) | P2-D2 / A4 — index scan, OR **a seq scan on `api_usage_logs` specifically** that triggers E1 (a seq scan on the small join relations does NOT trigger it) |
| **G-9** `-k "coop_ledger_reconciles_exactly"` — ≥200 randomized accrue/expire ops; oracle = `SUM(amount)` computed independently of `spendable_balance`'s helper. **Mandatory precondition (Constraint 13):** before EVERY assert, the effective hold/expiry TIMESTAMPS must be controlled so `now` is past EVERY lot's `spendable_at` and each lot's position relative to `expires_at` is deterministic — via `monkeypatch.setattr(settings, "coop_credit_hold_hours", 0)` and/or seeded past `spendable_at` (precedent `test_identity_coop_contribution.py:384-412`). **Independent-oracle hardening:** a `SUM(amount)` oracle sharing the lot-window predicate with the implementation is skewed identically by a wrong-window stamp and stays green — therefore **≥50 of the ≥200 ops MUST compare against a HARNESS-TRACKED expected balance**, a running total maintained in Python from the test's own intent, never from any repo query. | Hybrid (PG :5433, serialized) | AC-8 / P2-D5 |
| **G-11** `.venv/bin/python3.11 -m pytest tests/unit -q` | Fully-Automated | P2-D4 (re-baseline per S-23) |
| **G-12** `.venv/bin/python3.11 -m pytest tests/ -m integration -q` (SERIALIZED) | Hybrid (PG + Redis) | P2-D4 |
| **G-13** `git diff HEAD --quiet --exit-code -- apps/api/services/identity_resolver.py` (`HEAD` is load-bearing — it catches staged changes; the bare `git diff <path>` form exits 0 unconditionally) | Fully-Automated | zero-new-write-surface |
| **G-13b (NEW at split)** `git diff HEAD --quiet --exit-code -- apps/api/services/billing.py apps/api/routers/billing.py` | Fully-Automated | 2a/2b boundary — spend wiring must not leak into 2a |
| **G-15** conditional E1 only; `DATABASE_URL`-pinned up/down/up on a disposable PG. **Per L2-1 E1 never has its own file** — when E1 fires, G-15's subject IS the G-15b file. | Hybrid (Docker at `/Applications/Docker.app/Contents/Resources/bin/docker`) | schema/migration high-risk class (conditional) |
| **G-15b (NEW — C-3 fix, 17-08-26; MANDATORY, always runs)** the E2 migration `{rev}_add_coop_expire_unique.py`: (i) `DATABASE_URL`-pinned **offline** validation with an explicit `<from>:<to>` range (never bare `upgrade head --sql` — `b7d3e9f1a4c2` calls `sa.inspect(bind)` and breaks offline mid-chain); (ii) a **live down/up round-trip on a DISPOSABLE Postgres** proving `uq_coop_ledger_expire_per_lot` **drops and recreates cleanly** (partial unique index — `postgresql_where`). Docker CLI at `/Applications/Docker.app/Contents/Resources/bin/docker`. **Why this row exists:** E2 is MANDATORY but its proof lived ONLY in Exit Gate prose while G-15 read "conditional E1 only" — and the validate-contract's Test Gates derive from THIS table, so the mandatory migration was one edit away from having no gate at all. **This is the only proof of the migration file; G-21 proves the MODEL index only** (`create_all`, never alembic — C-5). | Hybrid (disposable PG + Docker) | E2 / schema-migration high-risk class — **mandatory, not conditional** |
| **G-17** `-k "coop_consumption_naive_tz_bounds"` — seed `api_usage_logs` rows whose naive `created_at` sits within a few hours of both window edges, then assert **(i)** the count is identical whether the caller passes a tz-aware or naive bound **AND (ii) that the count equals the EXACT expected integer** given deliberately seeded in-window and out-of-window edge rows (M2-3 fix, 17-08-26). **Leg (ii) is not optional:** identical-counts alone is satisfied trivially by an implementation that ignores `since`/`until` **entirely** — equally wrong on both sides — and Phase 2b's monthly-allowance math consumes exactly those windows. Seed at minimum one row just INSIDE each bound and one just OUTSIDE each bound, and assert the exact in-window integer under both bound flavours. **Mechanism:** asyncpg **raises** when a tz-aware value is bound to a `TIMESTAMP WITHOUT TIME ZONE` column — the un-normalized case most likely errors rather than silently shifting the window. The assertion must tolerate *both* failure shapes (raise OR wrong count) as a FAIL. **⛔ MANDATORY: every seeded edge row needs a matching `identified_visitors` row and the expected in-window integer must be NON-ZERO — same F3a-1 treatment as G-3; see `### G-3 / G-17 — mandatory identity-side seeding (F3a-1)` below. Leg (ii)'s exact-count assertion is otherwise vacuous for the identical reason.** | Hybrid (PG) | C-7 / S-22 |
| **G-18** `-k "coop_expiry_never_negative"` — **five legs, all mandatory** (see below) | Hybrid (PG :5433, serialized) | F-1 / S-10b / S-11 / **AC-7 non-vacuity** |
| **G-19 (renumbered from D9)** `-k "coop_erased_row_excluded_from_consumption"` — an `IdentifiedVisitor` whose `email_bidx` is in `SuppressionEntry(scope='erased')` is not counted; asserts a non-zero pre-exclusion count so the leg cannot pass on an empty fixture | Hybrid (PG :5433, serialized) | SPEC A interface obligation (erased-row exclusion) |
| **K-1** REVERSE / clawback-debt semantics | — | **INFORMATIONAL POINTER — NOT a 2a known-gap and NOT CONDITIONAL-forcing (C2a-4/Gap 4 fix).** All REVERSE content left 2a's scope to `backlog/coop-credit-reversal-semantics_NOTE_16-08-26.md`; the backlog note owns it. Retained here only so a reader of 2a's gate table can find where it went. **2a's gate verdict MUST NOT be held CONDITIONAL on this row** — doing so made 2a unable to reach PASS for a reason entirely outside its blast radius. |
| **G-20 (NEW — F2a-2 fix; LEGS REWRITTEN 17-08-26 by F2b-1)** `-k "coop_expiry_sweep_entrypoint_runs_twice"` (test D8) — calls **`run_coop_expiry_sweep(db)`**, NOT `expire_lapsed_lots`. **TWO mandatory legs.** **(a) LOCK-RELEASE PROBE:** after call 1 returns, assert `SELECT pg_advisory_unlock(hashtext('coop_expiry_sweep'))` returns **`False`** from the sweep's own session — PG returns false (plus a warning) when nothing is held, so a leak returns `True`. This is the assertion that actually gates the B3b acquire/release pair. **(b) PROGRESS LEG:** seed a **SECOND** lapsed lot before call 2, then assert **exactly two** EXPIRE rows total after call 2 (one per lot). **⚠ Both legs exist because the previous single "double call with the same `db`, exactly one row after each call" form was VACUOUS (F2b-1), on two independent grounds: (i) PG advisory locks are RE-ENTRANT within a session and `tests/conftest.py:149` is a plain `async_sessionmaker` over a `pool_size=5` engine, so a single-tasked test re-checks-out the SAME connection = the SAME PG session and call 2's `pg_try_advisory_lock` returns TRUE even after a leak — **note the mechanism is NOT LIFO ordering (SQLAlchemy `QueuePool`/`AsyncAdaptedQueuePool` defaults to FIFO, `use_lifo=False`; `tests/conftest.py` passes only `pool_size=5`) but single-connection pool population in a single-tasked test — M3-1 correction, cycle 3**; (ii) a flat row count cannot separate a CORRECT call 2 (`max(0, remaining) == 0` → skip → 0 rows) from a LOCK-BLOCKED call 2 (early return → 0 rows) — both leave one row. Do not "simplify" back to that form.** Entrypoint-inertness coverage is preserved by leg (b): an inert entrypoint writes 0 rows and fails both legs. **NOT covered by either leg (explicit "does NOT prove" list — C3-1/C3-2, cycle 3):** (i) **leg (a) gates the POST-CONDITION only — that no lock is held after the sweep returns — NOT the acquire/release pair; an implementation that takes NO lock at all passes both legs. The acquisition itself is UNGATED — accepted, adjacent to K-2** (the lock is efficiency-only; E2's partial unique index is the correctness boundary); (ii) **leg (a) proves release in the TEST TOPOLOGY only** — one single-tasked session on one pooled connection — **not under the pooled production shape**, where M2-2's accepted connection-swap means the unlock may execute on a different connection and no-op (routed to the capacity-hardening advisory-lock audit note by S-27); (iii) the exception path (C-1 — an aborted transaction makes the unlock fail and the precedent's bare `except` swallows it); (iv) the wrapper `_coop_expiry_sweep_job()`'s own RUNTIME flag check (see G-23(c) and K-5). **Leg (a) is mandatory regardless: it fails the exact defect it was added for — an acquire WITHOUT a release (F2a-1).** | Hybrid (PG :5433, serialized) | F2a-2 / **B3b lock RELEASE (leg a)** / AC-7 non-vacuity at the entrypoint level (leg b) |
| **G-21 (NEW — M-3 decision)** `-k "coop_duplicate_expire_rejected_by_db"` (test D10) — insert a second `EXPIRE` row for the same `lot_id` via **raw SQL, bypassing service code** (Phase 1 precedent for proving a DB-level constraint), assert the DB raises `IntegrityError` on `uq_coop_ledger_expire_per_lot`. Proves the duplicate-EXPIRE class is closed at the **DB tier**, not merely by the read-compute-skip and the advisory lock — duplicates are balance-INVISIBLE under S-10b stamping, so no balance assertion at any tier can see them, while Phase 3's dashboard (which omits the window predicate) would report `2N` credits lost. | Hybrid (PG :5433, serialized) | E2 / durable-audit integrity on a billing surface |
| **G-22 (NEW — L-3 fix)** `-k "coop_contribution_count_excludes_excluded_reason"` (test D11) — one `excluded_reason=NULL` row + one `excluded_reason='duplicate'` row; assert `contribution_count` returns exactly 1. Without it, an A3 implementation missing the filter ships green. | Hybrid (PG :5433, serialized) | A3 |
| **G-23 (NEW — L-3 + L-1 fix)** two legs. **(a)** `-k "coop_spendable_lots_fifo_order_and_drawn_subtraction"` (test D12) — three live lots with distinct `expires_at` seeded out of insertion order plus one partially-drawn lot; assert `expires_at` ASC ordering and `remaining == ACCRUE − drawn` clamped at 0 (S-4). D6 covers hold-exclusion ONLY and proves nothing about ordering or subtraction — a FIFO bug would otherwise surface first in Phase 2b's draw. **(b)** Fully-Automated: `grep -n 'id="coop_expiry_sweep"' apps/api/jobs/scheduler.py` returns **≥1 hit** — presence of the registration only. **(c) SPLIT OUT 17-08-26 (L2-3):** that the surrounding `add_job` call sits **inside** an `identity_coop_enabled` guard is **NOT grep-decidable** (it is a lexical-scope property, not a string match) — it is therefore an **Agent-Probe**: read `apps/api/jobs/scheduler.py` around the registration and judge that the `add_job` call is within the `if settings.identity_coop_enabled:` block, recording the judgment verbatim in the phase report. The old combined "grep returns a hit AND the call is inside a guard" wording claimed Fully-Automated for a leg no grep can decide. | (a) Hybrid (PG :5433, serialized); (b) Fully-Automated; (c) Agent-Probe | (a) B1 / FIFO draw order; (b) B4 registration presence; (c) B4/L-1 startup flag-gating |
| **K-5 (NEW — 17-08-26 cycle 2, F2b-1 item iii)** The `_coop_expiry_sweep_job()` wrapper's **RUNTIME** `settings.identity_coop_enabled` check | — | **Known-Gap — DECLARED, not silently absent.** No gate executes the wrapper: G-20 calls `run_coop_expiry_sweep(db)` **directly**, and G-23(b)/(c) only inspect the `add_job` **registration**. So the wrapper's own early-return-when-flag-OFF branch is unexecuted by any tier. **Accepted, and cheap to accept — but the unreachability claim is SCOPED (Gap 6 fix, cycle 3).** The belt-and-braces design (B4/L-1) means a process that starts with the flag **OFF** registers no job at all, so the wrapper is unreachable **in the startup-flag-OFF case ONLY**. It is emphatically **REACHABLE in the runtime-flag-flip case** — a process that starts flag-ON registers the job, and a later flip to OFF is caught by nothing except this in-wrapper check. **That case is the entire reason L-1 mandates the in-wrapper check exists (i), and it is why the check MUST NOT be deleted as dead code.** The earlier unqualified wording ("unreachable in exactly the case it guards") was FALSE as stated and is retracted. What is accepted is only that no *gate* executes the wrapper; every 2a service function is flag-independent, so the residual risk is bounded. **Resolution D — backlog residual**, adjacent to K-3 (no live flag-on gate is available at all under constraint d). Revisit in Phase 2b when the flag becomes live-flippable. |
| **K-2** Multi-process concurrency on the H2 enqueue→sweep window | — | **Known-Gap — APPLIES to 2a** (inherited accepted, constraint e). Note it does **NOT** cover F2a-1's lock-release defect (fixed in-plan) nor the duplicate-EXPIRE class (now closed at the DB tier by E2/G-21). |
| **K-3** Any live flag-on gate | — | **Known-Gap — APPLIES to 2a.** Blocked by constraint d (`coop_terms_version` placeholder pending legal re-pin). **No gate in this table requires a REAL deployment flag flip** — every 2a service function is called directly by its test, and the flag checks live entirely in the scheduler layer — **TWO of them, per L-1: (i) the runtime check INSIDE `_coop_expiry_sweep_job()` and (ii) the startup gate around the `add_job(...)` registration** (the former single-check wording was stale — L3-2, cycle 3). Static coverage is **G-23(b)** (Fully-Automated grep: the registration exists) plus **G-23(c)** (**Agent-Probe**: the `add_job` call sits inside the `identity_coop_enabled` guard — lexical scope is not grep-decidable, L2-3); the runtime check (i) is executed by no tier and is declared as **K-5**. `monkeypatch` for the whole test function (S-18 / Constraint 10 / 14) is the only sanctioned substitute. |
| **K-4** Orphan-lot / site_id-reuse class | — | **MOVED OUT of 2a to Phase 2b** for the SPEND writer. **2a's own EXPIRE writer is NOT covered by that move** — its delete-vs-sweep window is closed in-plan by the mandatory single-statement `INSERT … SELECT … WHERE EXISTS` guard under B3 (M-4), not deferred. |

### G-3 / G-17 — mandatory identity-side seeding (F3a-1, cycle-3 FAIL)

A2's join is **INNER** (decided, L-2). A fixture that seeds `api_usage_logs` rows ONLY has **every one
of them dropped** by that join, so the EXACT-count assertion resolves to **0** — and an implementation
with **no `provider` predicate, no `site_id` predicate, even a literal `return 0` stub, passes**. The
H2-2/F3 repair that added G-3 rows (d)-(e) therefore created **zero** real coverage. Mandatory for both
gates:

1. **G-3 row (a) MUST have a matching `identified_visitors` row** — same `site_id` **and** same
   `visitor_id`, created **through the ORM** so the `_sync_identity_pii` `before_insert` hook
   (`services/pii_encryption_hooks.py:33-36`) populates a **non-NULL `email_bidx`**, and with that
   `email_bidx` **absent** from `SuppressionEntry(scope='erased')`. Without it row (a) — the one row
   that must be COUNTED — is itself dropped.
2. **G-3 row (d) MUST have its own matching `identified_visitors` row on the SECOND site.** Without it
   row (d) is structurally inert and forces nothing: an implementation missing the `site_id` predicate
   still cannot see it, so the tenant-scoping proof H2-2 intended never happens. **Row (d) + its
   identity row is the `site_id`-predicate forcing pair.**
3. **G-3 row (e) (`site_id = NULL`) can NEVER equi-join** — `IdentifiedVisitor.site_id` and
   `.visitor_id` are both `nullable=False` (`apps/api/models/visitor.py:204-205`), so no identity row
   can ever match a NULL `site_id`. **DECIDED: keep row (e) with its purpose RESTATED** — it is
   retained solely as a guard that the implementation does not join on **`visitor_id` ALONE** (a
   `visitor_id`-only join would match row (e) against site-1's identity row and inflate the count).
   It is **not** tenant-scoping proof. Recorded so a later reader neither deletes it as dead weight
   nor re-cites it as the `site_id` forcing row.
3b. **⛔ ROWS (b) AND (c) MUST ALSO BE JOINABLE (C4-1, cycle-4).** As written above, rows (b) and (c)
   had **no mandated `identified_visitors` row** — but they are the ONLY two rows that can force the
   `provider='beam_identity_network'` predicate, and (c) is named in this plan as **"the load-bearing
   row"**. Under the INNER join an unjoinable row is **dropped before any predicate is evaluated**, so
   an implementation with **no `provider` filter at all** never sees (b) or (c) and still hits the
   exact count — the predicate stops being forced. The proof only survives if the test author
   *happens* to reuse row (a)'s `visitor_id`; that must not be left to chance.
   **MANDATORY:** seed rows (b) and (c) on **row (a)'s `site_id` AND row (a)'s `visitor_id`**, **or**
   give each its own matching ORM-created `identified_visitors` row on the probed site. Either shape
   is acceptable; having neither is a FAIL.

4. **G-3's expected EXACT count = 1** (row (a) only) — a **NON-ZERO** integer. An expected value of 0
   is by definition unable to fail on a `return 0` implementation and is not an acceptable outcome.
   **Arithmetic with rows (b) and (c) now joinable (recomputed, C4-1) — the number does NOT move:**

   | Row | Provider / shape | Joins? | Counted? | Why |
   |---|---|---|---|---|
   | (a) | `beam_identity_network`, probed site | YES (own identity row) | **1** | passes provider + site_id |
   | (b) | paid provider, `cost_usd > 0`, probed site | **YES (newly mandated)** | 0 | dropped by the `provider` predicate — the whole point |
   | (c) | `form_capture` (other `OWNED_FREE_PROVIDERS`), probed site | **YES (newly mandated)** | 0 | dropped by the `provider` predicate — the load-bearing confusable |
   | (d) | `beam_identity_network`, SECOND site | YES (own identity row on site 2) | 0 | dropped by the `site_id` predicate |
   | (e) | `beam_identity_network`, `site_id = NULL` | NEVER (see item 3) | 0 | cannot equi-join; `visitor_id`-only-join guard |

   **Expected EXACT count = 1 + 0 + 0 + 0 + 0 = 1.** Unchanged from before this fix, because (b) and
   (c) are *supposed* to be excluded by `provider` — making them joinable is precisely what turns that
   exclusion from vacuous into proved. EXECUTE asserts `== 1`, never `> 0`.

4b. **⛔ EVERY seeded `identified_visitors` row MUST be created with a real `email=` value (C4-2,
   cycle-4).** `_sync_identity_pii` writes `email_bidx = email_hash(target.email) if target.email
   else None` — an identity row created without a real `email=` gets **`email_bidx = NULL`**, and A2's
   erased-suppression `NOT IN` filter then **silently drops that row** under SQL three-valued logic
   (`NULL NOT IN (...)` is `NULL`, never `TRUE`). That re-vacuums the fixture through a second, subtler
   door than F3a-1. Applies to **every** identity row seeded for **G-3, G-17, and G-19**, and each MUST
   be created **through the ORM** so the `before_insert` hook fires (a raw `INSERT` bypasses it and
   produces the same NULL).

4c. **DECIDED — emailless identities are EXCLUDED from `consumption_count` (C4-2, previously
   UNDECIDED).** A2's behaviour for an `identified_visitors` row with `email_bidx IS NULL` was never
   written down; it is now an explicit decision, not an accident of three-valued logic:
   **an identity with no email is NOT counted**, because the erasure-exclusion filter cannot evaluate
   it safely — there is no blind index to compare against `SuppressionEntry(scope='erased')`, so
   counting it would risk billing for a visitor who may already have been erased. **Direction of error
   is deliberately conservative: this UNDERCOUNTS consumption** (the co-op is never overcharged), which
   is the same safe direction every other predicate in this phase errs toward. EXECUTE implements the
   `NOT IN` filter as-is — no `COALESCE`, no `OR email_bidx IS NULL` rescue — and does not "fix" the
   drop.
5. **G-17: every seeded edge row** (in-window and out-of-window, both bound flavours) needs its own
   matching ORM-created `identified_visitors` row, and the expected in-window integer **MUST be
   NON-ZERO** — mirror G-19's non-zero pre-exclusion guard (assert `> 0` before asserting the exact
   value) so the leg cannot pass on an empty effective fixture.

**Generalizable rule (also recorded in `## Test Infra Improvement Notes`): every consumption gate in
this phase and in Phase 2b MUST seed the `identified_visitors` side of the A2 join and MUST assert a
non-zero count.**

---

### G-18 — five mandatory legs

`.venv/bin/python3.11 -m pytest tests/ -m integration -q -k "coop_expiry_never_negative"`
(test function `test_coop_expiry_never_negative` — checklist item **D7**; the five legs below are the
build spec D7 cites, so they are no longer gate-prose living outside the build list — M-1 fix.)

**Scope boundary:** all five legs call `expire_lapsed_lots` **directly**. They prove nothing about
`run_coop_expiry_sweep`, the advisory lock, or the scheduler registration — that is **G-20/G-23(b)**
(F2a-2). Do not treat a green G-18 as covering the sweep entrypoint.

1. **Fully-unspent lapsed lot** → `spendable_balance(site)` exactly 0 (never `−N`).
2. **Partially-spent lapsed lot** → exactly 0. *(Seed the SPEND row directly — `spend_credits` does not exist until Phase 2b.)*
3. **Negative-raw-SUM lot** → a lot whose window-blind raw SUM has gone negative must produce **either no EXPIRE row or a NEGATIVE one — never a positive and never a ZERO EXPIRE**; assert **`amount < 0`** (tightened from `amount <= 0` by L2-4, 17-08-26) on every EXPIRE row, and balance still exactly 0. **PLUS a row-ABSENCE assertion:** seed a fully-drawn lot whose `max(0, remaining) == 0` and assert **zero** EXPIRE rows exist for that `lot_id`. **Why both:** a broken skip that writes `amount = -max(0, 0) = 0` rows for fully-drawn lots passes the old `amount <= 0` form and is balance-invisible under S-10b stamping — the skip in B3 would be silently dead. `amount < 0` alone would fail such a row only if it is written for THIS leg's lot; the absence assertion covers the fully-drawn case directly. Without this leg the literal `amount = -remaining` sign bug also ships green (legs 1-2 cannot see it).
4. **Row-stamp assertion + NULL-stamp negative control (load-bearing):** assert every EXPIRE row's `spendable_at`/`expires_at` equal its source lot's, AND — as an explicit negative control — that seeding the same rows with **NULL** stamps yields `−(N−k)`. Under the new stamping, `balance == 0` alone would pass with **no sweep at all**.
5. **POSITIVE LEG — MANDATORY (F5-2 fix, cycle-5 OPEN FAIL).** A **normal lapsed lot** (ACCRUE `+N`, no offsets, `now` past `expires_at`) must yield **exactly ONE `EXPIRE` row with `amount == -N`**, carrying the lot's `lot_id`, `site_id`, and `[S,E]` stamps — and re-running `expire_lapsed_lots` must yield **exactly one row still** (idempotent at N=1, not at N=0). **Why:** legs 1-4 and D4 are ALL satisfied by an `expire_lapsed_lots` that writes zero rows forever under a window-aware reading of `remaining` (legs 1-2 assert `balance == 0` and a stamped EXPIRE is balance-invisible by construction; leg 3 explicitly accepts "no EXPIRE row"; leg 4 quantifies over existing rows only; D4's idempotence is `0 + 0`). Leg 5 is the only assertion in the set that a never-firing sweep fails.

---

## Test Infra Improvement Notes

- (16-08-26, F2-2) **`tests/unit/` has no real database session at all** — `grep -rn "create_async_engine\|aiosqlite" tests/unit/` returns nothing, and the existing coop unit test uses a hand-written fake `AsyncSession`. Any assertion whose value is computed by Postgres (`spendable_balance`, `spendable_lots`) **cannot** live in that lane, and SQLite is not a fallback (`postgresql.UUID`, `postgresql_where`). Recorded so future phases do not re-pin DB-dependent gates to the unit lane.
- (16-08-26, C2-1) **No clock-control mechanism exists in this repo** — zero hits for `freezegun` / `freeze_time` / `time_machine` across `requirements.txt`, `tests/`, `apps/`. Any hold/expiry-window test must monkeypatch `settings.coop_credit_hold_hours` (read at call time, `identity_coop.py:194`) or seed explicit past timestamps. Adding a time-freezing dependency would be a genuine infra improvement but is out of this phase's blast radius.
- (16-08-26; **RESOLVED IN-PLAN 17-08-26**) No existing harness seeds `api_usage_logs` at ≥100k rows. G-4's EXPLAIN evidence needs a new disposable-PG seeding helper — **now budgeted** as `seed_api_usage_logs` in the Blast Radius (~30 lines, bulk `INSERT … SELECT generate_series`, ≥50% of rows on the probed site each with a matching `identified_visitors` row). It is no longer an unbudgeted assumption (C2a-2/Gap 7).
- (17-08-26, this supplement cycle) **Sweep-entrypoint coverage was structurally absent.** Every expiry gate called the service function (`expire_lapsed_lots`) rather than the entrypoint (`run_coop_expiry_sweep`), so an inert entrypoint would have shipped with a fully green gate set — the vacuous-green class displaced one level up. Closed by G-20. Worth generalizing: **when a plan adds both a service function and a scheduled caller, the caller needs its own gate.**
- (17-08-26, **CORRECTED same day by F2b-1**) **Session-scoped advisory locks are not released by `commit()`.** Any future sweep in this repo must pair `pg_try_advisory_lock` with `pg_advisory_unlock` in a `finally`; four existing sweeps do, and copying only the acquire half is a silent defect. **The original wording of this note — "…unless a double-call-in-one-process test exists" — was WRONG and is retracted.** A double call **cannot** detect a leak: PG advisory locks are re-entrant within a session, and `tests/conftest.py:149` is a plain `async_sessionmaker` over a `pool_size=5` engine, so a single-tasked test gets the SAME connection = the SAME session on the second call. **Mechanism corrected (M3-1, cycle 3): this is NOT LIFO pool ordering** — SQLAlchemy's `QueuePool`/`AsyncAdaptedQueuePool` defaults to **FIFO** (`use_lifo=False`, `sqlalchemy/pool/impl.py:79`) and `tests/conftest.py` passes only `pool_size=5` — **it is single-connection pool population in a single-tasked test.** The practical consequence is the generalizable one: any lock-release probe of this shape is valid ONLY while every statement in the test runs on that one session; a second session or engine voids it. **The generalizable harness lesson: to gate lock release, assert `SELECT pg_advisory_unlock(<key>)` returns `False` after the sweep** — that is a direct state probe, needs no new harness, and is the only cheap assertion that fails on a leak.
- (17-08-26, cycle 2 — C-1) **An aborted transaction defeats a `finally`-based unlock.** All four lock precedents swallow the unlock exception (`except Exception: pass`), so a raising row leaves the session aborted, the unlock SELECT fails, and the lock leaks silently *despite* correct-looking `try/finally` code. Any repo sweep with per-row work needs per-row `try/except → rollback → continue` (precedent `services/referral_activation.py:185-192`) plus a `rollback()` before the unlock. **This exception path is not gated by any tier in 2a** — a documented residual, adjacent to K-2.
- (17-08-26, cycle 2 — M2-2) **Per-row `commit()` can move the connection out from under a session-scoped lock.** Committing returns the AsyncSession's connection to the pool, so a later `pg_advisory_unlock` may execute on a different connection and no-op. Repo-standard shape (all four precedents share it); accepted here because the E2 partial unique index, not the lock, is 2a's correctness boundary. Recorded in `process/general-plans/active/capacity-hardening_25-07-26/transaction-pooler-advisory-lock-audit_NOTE_25-07-26.md` (S-27).
- (17-08-26, cycle 2 — F3) **A fresh `drop_all`/`create_all` DB per test makes `site_id` scoping predicates unforceable by construction.** With only the test's own rows present, a query missing its tenant filter still returns the exact expected count. Any per-tenant count gate in this repo must seed a second-site row **and** a `site_id = NULL` row (`api_usage_logs.site_id` is nullable) to force the predicate. Generalizable to every future tenant-scoped aggregation gate.
- (17-08-26, cycle 2 — F2b-2) **`tests/conftest.py:133` builds the integration schema from `Base.metadata.create_all`, not alembic.** Any DDL that a test must observe (indexes, constraints, CHECKs) MUST be mirrored into the model's `__table_args__` or it simply does not exist in the test database — and the migration file gets no test coverage at all. The two tiers need two separate gates (here: G-21 model, G-15b migration).
- (17-08-26, cycle 3 — F3a-1) **A consumption gate that seeds only `api_usage_logs` proves nothing, because the A2 join is INNER.** Rows with no matching `identified_visitors` row are dropped, the exact-count assertion collapses to 0, and a `return 0` stub passes every predicate the fixture was built to force. **Generalizable rule for this repo: every consumption gate MUST seed the `identified_visitors` side of the A2 join (same `site_id` + `visitor_id`, ORM-created so `_sync_identity_pii` populates `email_bidx`) and MUST assert a NON-ZERO expected count.** Note also that `IdentifiedVisitor.site_id`/`.visitor_id` are `nullable=False` (`models/visitor.py:204-205`), so an `api_usage_logs` row with a NULL `site_id` is structurally unjoinable and can only ever serve as a `visitor_id`-only-join guard — never as tenant-scoping proof. Applies to G-3, G-17 and G-19 here, and to every Phase 2b consumption/allowance gate.
- (17-08-26, at the split) The **multi-site-per-user fixture infra** noted by prior cycles is no longer a 2a need — it moves to Phase 2b with P2-D3's user-pooled draw.
- (17-08-26, at the split) The **fresh-session read-back helper** and the **concurrency harness** (`asyncio.gather` + one session per coroutine, precedent `tests/integration/test_campaign_double_send.py:113-122`, `tests/conftest.py:92-96` `pool_size=5`) are Phase 2b needs, not 2a's — 2a has a single serialized writer.

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/visitors-identity/active/identity-coop_07-08-26/phase-2-consumption-spend_PLAN_07-08-26.md` (**this file — now Phase 2a**)
- Last completed step: **Step 3 PLAN-SUPPLEMENT — PVL-supplement cycle 3 against the 2a scope, 17-08-26** (merged gap set: PVL `Gate: BLOCKED` cycle 3 — **1 FAIL (F3a-1) + 7 CONCERNs, SUPPLEMENT REQUEST Gaps 1-7** — plus an independent adversarial round-3 verifier's **NO HIGH / 3 MEDIUM / 4 LOW**; the two reviewers CONVERGED on the E1-wording and "prose only" items and each caught items the other missed). Previously: **PVL-supplement cycle 2 against the 2a scope, 17-08-26** (merged gap set: PVL `Gate: BLOCKED` cycle 2 — F2b-1, F2b-2, Gaps 3-8 — plus an independent adversarial round-2 verifier's 2 HIGH / 3 MEDIUM / 5 LOW; the two reviewers CONVERGED on F2b-1/H2-1 and each caught one the other missed). Previously: **PVL-supplement cycle 1, 17-08-26** (merged gap set: PVL `Gate: BLOCKED` F2a-1/F2a-2 + Gaps 3-7, plus an independent adversarial verifier's 1 HIGH / 5 MEDIUM / 3 LOW). The SPLIT rewrite preceded it on 17-08-26; Steps 1-2 completed 16-08-26.
- Validate-contract status: **ALL prior contracts SUPERSEDED by the 17-08-26 split.** The cycle-5 inner-pvl contract (`Gate: CONDITIONAL`, three FAILs) is retained verbatim below for the chain but is no longer authoritative: F5-2 is FIXED in this plan (B3 window-blind definition + G-18 leg 5), F5-3 is FIXED (Blast Radius/Touchpoints reconciled), and F5-1 moved to Phase 2b with the G-6 concurrency surface. **PVL must re-run from V1 against the narrowed 2a scope.**
- Supporting context files loaded: umbrella plan, Phase 1 plan + report + `phase-1-supplement-execute_REPORT_16-08-26.md`, `phase-blast-radius-registry.md`, `coop-terms-repin_RUNBOOK_16-08-26.md`, `backlog/coop-credit-reversal-semantics_NOTE_16-08-26.md`, `process/context/tests/all-tests.md`, `process/context/all-context.md`
- **Supplement cycle 1 change summary (17-08-26)** — F2a-1 closed (B3b/S-21 now mandate the acquire **and** release pair in `try/finally` + early return; the S-21/B3b lock contradiction is resolved explicitly); F2a-2 closed (**NEW G-20** exercises `run_coop_expiry_sweep` twice in-process, **G-23(b)** asserts the `add_job` registration); H-1 closed (G-3 now mandates a 3-row provider fixture with an EXACT count, naming the other `OWNED_FREE_PROVIDERS` as the load-bearing confusables); **M-3 DECIDED — the mandatory partial unique index `uq_coop_ledger_expire_per_lot` (new checklist item E2, new migration file, new gate G-21)**, with Constraint 2 reworded to carve it out and the advisory lock demoted to efficiency-only; M-1 closed (all Step-D tests renamed `test_coop_…` so every `-k` selector matches, and D1/D2/D7/D8/D10/D11/D12 added so no gate lives only in prose); M-2 closed (loop **and** per-lot commit assigned to `expire_lapsed_lots`; the sweep owns only lock+call); M-4 closed (single-statement `INSERT … SELECT … WHERE EXISTS` orphan guard under B3); M-5 closed (E1 trigger narrowed to a seq scan on `api_usage_logs` only + seeding shape mandated); Gaps 3-7 and L-1/L-2/L-3 all applied. Blast Radius 8 → **10 files**.
- **Supplement cycle 2 change summary (17-08-26)** — **F2b-1 closed**: G-20/D8 rewritten to two mandatory legs — (a) a `pg_advisory_unlock(...) is False` state probe (the only assertion that fails on a leak) and (b) a second seeded lapsed lot forcing call 2 to write an additional row; the same-session LIFO re-entrancy trap is written inline in D8, the G-20 row, B3b, the Exit Gate, the Phase Completion Rules, and Test Infra note 5 so it cannot be re-introduced. **F2b-2 closed**: `models/identity_coop.py` re-budgeted to ~12 lines "S-10c prose + E2 index mirror", with the `create_all`-not-alembic reason stated in both Blast Radius and E2. **F3 (adversarial H2-2) closed**: G-3 gains a second-site row (d) and a `site_id = NULL` row (e) to force the tenant predicate. **C-1** per-lot `try/except → rollback → continue` + pre-unlock `rollback()` mandated in B3. **C-2** early return changed to `if got is False` (fail-open on `None`, matching all four precedents). **C-3** new **G-15b** mandatory migration gate. **C-4/M2-1** the combined `INSERT … SELECT … WHERE EXISTS … ON CONFLICT (lot_id) WHERE entry_type='EXPIRE' DO NOTHING` statement promoted to MUST and written verbatim in B3. **C-6** `_log_owned_resolution` re-anchored to symbol in both places. **C-7** `infra-redis-1` + the off-PATH Docker CLI named inline in the Exit Gate. **M2-2** connection-swap leak ACCEPTED as a documented efficiency gap (E2 index is the correctness boundary; pinning a connection REJECTED with rationale) + new **S-27** records the sweep in the capacity-hardening advisory-lock audit note. **M2-3** G-17 gains an EXACT-count leg with in/out-of-window edge rows. **L2-1** merge modality decided — when E1 fires it is folded into the ONE mandatory migration file (no second file); Blast Radius, Touchpoints and E2 now agree. **L2-2** `success`/`category` axes documented as production-vacuous (hardcoded at `identity_resolver.py:1515`), no rows added, reason recorded. **L2-3** G-23(b) split — grep stays Fully-Automated, the guard-scope half becomes **(c) Agent-Probe**. **L2-4** G-18 leg 3 tightened to `amount < 0` plus a row-ABSENCE assertion for a `remaining == 0` lot. **L2-5** the seeding helper documented as TWO bulk statements with NULL `email_bidx` accepted. **New K-5** declares the wrapper's runtime flag check as an explicit known-gap. **No `-k` selector was added or changed this cycle** — all 9 were re-grepped 17-08-26 and still return **0 files** in `tests/`, and each remains a substring of exactly one mandated `test_coop_*` name (both directions).
- **Supplement cycle 3 change summary (17-08-26)** — **F3a-1 (the FAIL) closed**: G-3's and G-17's fixtures were seeding `api_usage_logs` ONLY while A2's join is INNER, so every fixture row was dropped, the EXACT-count assertions resolved to **0**, and a `return 0` stub passed both gates — the H2-2/F3 repair had created ZERO real coverage. New mandatory subsection `### G-3 / G-17 — mandatory identity-side seeding (F3a-1)` requires matching ORM-created `identified_visitors` rows for G-3 rows (a) and (d) and for every G-17 edge row, mandates a **NON-ZERO** expected count (G-3 = exactly **1**), and restates row (e)'s purpose as a `visitor_id`-only-join guard (it can never equi-join — `IdentifiedVisitor.site_id`/`.visitor_id` are `nullable=False`). D1/D2 and a new Test Infra note carry the generalizable rule. **Gap 5 / M3-3 closed**: E1's checklist wording no longer says "chain an `add_coop_ledger_indexes` migration" — it now folds the E1 index into the ONE mandatory `{rev}_add_coop_expire_unique.py` file per L2-1, removing the two-heads collision class. **Gap 3 / L3-1 closed**: the F5-3 paragraph's "MODIFIED (prose only)" is rewritten to "~12 lines: S-10c prose + E2 index mirror" with "prose only" explicitly RETRACTED. **Gap 4 / C3-1+C3-2 closed**: G-20 leg (a) rescoped to the POST-CONDITION (a no-lock implementation passes; acquisition ungated, accepted adjacent to K-2) with an explicit four-item "does NOT prove" list incl. the test-topology-only caveat; the Exit Gate and Phase Completion Rules overclaims corrected too. **Gap 6 closed**: K-5's unreachability rationale scoped to the startup-flag-OFF case only — the runtime-flag-flip case IS reachable and is why L-1 mandates the in-wrapper check; resolution D retained. **Gap 7 closed**: EXECUTE must capture and report any `coop_expire_lot_failed` log lines during the integration gate run (a systemic INSERT failure otherwise reads as a silent zero-row sweep). **C3-7 confirmed**: S-24's pinned-DSN LIVE head re-derivation restated as mandatory and as the control; no head recorded in this plan may be chained off. **M3-1 closed**: the "LIFO pool" mechanism claim was factually WRONG (SQLAlchemy `QueuePool` defaults to **FIFO**, `use_lifo=False`; `tests/conftest.py` passes only `pool_size=5`) and is corrected in all FOUR places (B3b, D8 trap, G-20 row, Test Infra note 5) to single-connection pool population in a single-tasked test — plus D8's previously-unstated **single-session precondition** (all D8 DB work through the one `db` session; a second session voids leg (a)). **M3-2 closed**: D8 must `from apps.api.services.coop_expiry_sweep import _LOCK_KEY` and assert `_LOCK_KEY == "coop_expiry_sweep"` before the probe — `pg_advisory_unlock` on an unheld key returns the PASSING value, so key drift made leg (a) pass forever. **L3-2 closed**: the K-3 row now names BOTH L-1 flag checks and cites G-23(b) **and** G-23(c). **L3-3 closed**: the per-lot except block snapshots `lot_id_str` before the `try` and rolls back before logging. **L3-4 closed**: S-3's budget reconciled to **0-4 lines** in both the Blast Radius row and S-3. **No `-k` selector was added or changed this cycle** — the 9 existing selectors are untouched, so their re-grep evidence from cycle 2 stands; S-25 still requires a fresh re-grep at EXECUTE.
- Next step: **spawn vc-validate-agent for inner PVL from V1** on this plan. Do NOT spawn EXECUTE until a non-placeholder, non-BLOCKED contract exists for the 2a scope. Per prior contract instruction **E-7**, also spawn one independent adversarial verifier instructed to REFUTE (default verdict REFUTED) — external verifiers found the top defect in every prior cycle on this program.
- Sibling plan: `process/features/visitors-identity/active/identity-coop_07-08-26/phase-2b-spend-wiring_PLAN_16-08-26.md` (⏳ PLANNED, entry-gated on 2a LIVE).

---

## Inner Loop Refresh Note

- **Date:** 17-08-26
- **Trigger:** Explicit user decision to SPLIT Phase 2 into 2a + 2b (mid-program restructure, NOT a supplement cycle).
- **Sections changed:** frontmatter (name/description/phase → `phase-2a`); title; header block; NEW `## Why This Phase Was Split`; Purpose; Blast Radius (rewritten as the single authoritative 8-file table; F5-3 closed — `models/identity_coop.py` is MODIFIED (~12 lines: S-10c prose + E2 index mirror), no longer READ ONLY; "prose only" is RETRACTED — E-12); Spend Semantics → Credit Semantics Carried Into 2a; Implementation Checklist (Step C deleted; Step D reduced; B3 restated with the window-blind `remaining` definition per F5-2; NEW B3b commit-granularity + sweep-lock decision per M3-1); Supplement Checklist (spend/REVERSE items removed, S-13 narrowed to S-13a); Decisions (P2-D1/D3/D6 removed; P2-D2/D4/D5 kept); Constraints (9, 12b, 16, 17 removed to 2b; 12's REVERSE clause to K-1); Exit Gate (NEW billing purity guard); Acceptance Criteria; Touchpoints (reconciled with Blast Radius); Public Contracts; Verification Evidence (rewritten; G-18 leg 5 added; G-13b added; G-19 renumbered from D9); Test Infra Improvement Notes; Resume and Execution Handoff.
- **Effect on PVL:** every prior `## Validate Contract` is SUPERSEDED. **PVL must re-run from V1.**

---
## Validate Contract

Status: CONDITIONAL
Date: 17-08-26
date: 2026-08-16
generated-by: inner-pvl: phase-2a
supersedes: 2026-08-16 (inner-pvl: phase-2a, cycle 3) — cycle 4 is the CONFIRMATION pass over the
merged 12-item fix set (PVL cycle-3 FAIL F3a-1 + 7 CONCERNs, plus adversarial round-3's 3 MEDIUM /
4 LOW). Cycle 3's single FAIL is verified CLOSED against live source.

PVL cycle: 4 (inner, Phase 2a scope)
Parallel strategy: sequential (single validator; no Agent tool available in this environment — the
orchestrator-spawned adversarial verifier is a separate leg, see E-7 carried forward)
Rationale: 1 plan file, 1 blast radius, no independent investigation directions. Signal score 3/7
(S2 schema/API surface, S6 high-risk class billing+migration, S7 10 files) → MEDIUM. The adversarial
leg found the top defect in cycles 1-3 and converged to NO HIGH in round 3.

---

### Headline — F3a-1 is CLOSED. Zero FAILs. The gate set can now catch a broken implementation.

The cycle-3 FAIL (G-3/G-17 fixtures vacuous under the A2 INNER join) is genuinely closed: the new
`### G-3 / G-17 — mandatory identity-side seeding (F3a-1)` subsection makes both fixtures able to
fail a `return 0` stub and a missing-`site_id` implementation, and the generalizable rule is recorded
where a future gate author will find it.

**One residual of the same family survives, one row over, and is the reason this is CONDITIONAL
rather than PASS:** G-3's rows **(b)** and **(c)** — the rows whose entire job is to force the
`provider='beam_identity_network'` predicate — were NOT given mandated matching `identified_visitors`
rows. Under the INNER join, whether they force anything depends on a `visitor_id` the plan never
specifies. This is carried as **C4-1** with a binding EXECUTE instruction (E-10), not as a FAIL,
because G-3 still deterministically fails `return 0` and still deterministically fails a missing
`site_id` predicate — the gate is no longer vacuous, only incompletely forcing on one of its two
target predicates. A reviewer could reasonably grade C4-1 a FAIL; see the note under it.

---

### Priority verification results (W-1 … W-4, all against live source, 17-08-26)

| ID | Question | Result |
|---|---|---|
| **W-1a** | With the mandated identity rows present, does G-3 fail a `return 0` stub? | **YES — CLOSED.** Expected EXACT count is **1**, explicitly non-zero (seeding item 4). `return 0` ≠ 1. |
| **W-1a** | …fail an implementation missing the **`site_id`** predicate? | **YES — CLOSED.** Row (d) now carries its own identity row on site 2 (seeding item 2), so it joins and is visible: an unscoped count returns **2 ≠ 1**. This was structurally impossible before the fix. |
| **W-1a** | …fail an implementation missing the **`provider`** predicate? | **NOT DETERMINISTICALLY → C4-1.** Rows (b) (paid) and (c) (`form_capture`, the named load-bearing confusable) have **no mandated identity row**. If the author gives them fresh `visitor_id`s they are INNER-join-dropped, force nothing, and a `provider`-less (or `cost_usd`-based) implementation returns 1 and passes. If the author reuses row (a)'s `site_id`+`visitor_id` — the natural shape, since `api_usage_logs` legitimately carries several provider rows per visitor — the predicate IS forced. Author-dependent; one-sentence fix. |
| **W-1b** | Is row (e) coherently restated as a `visitor_id`-only-join guard? | **YES — COHERENT.** Verified live: `IdentifiedVisitor.site_id` and `.visitor_id` are both `nullable=False` (`apps/api/models/visitor.py:204-205`), and `api_usage_logs.site_id` IS nullable (`apps/api/models/api_usage.py:35`, comment verbatim). So row (e) can never equi-join — correct. Retained purpose is exact: "otherwise-identical" means it shares row (a)'s `visitor_id`, so a `visitor_id`-only join matches it against site-1's identity row and inflates the count to 2 ≠ 1. Seeding item 3 explicitly warns against both deleting it and re-citing it as the `site_id` forcing row. |
| **W-1c** | Is the generalizable rule where a future gate author will see it? | **YES — TWO places.** In the seeding subsection (`:883-885`) and as a standalone Test Infra Improvement Note (`:918`), the latter being exactly where a 2b gate author looks. The note also carries the `nullable=False` mechanism so the reasoning transfers, not just the rule. |
| **W-2i** | Is the G-20 acquisition-ungated acceptance coherent + clearly documented? | **YES — ACCEPT AS STATED. Not re-raised.** The G-20 row states verbatim that leg (a) "gates the POST-CONDITION only … an implementation that takes NO lock at all passes both legs. The acquisition itself is UNGATED — accepted, adjacent to K-2". The justification is load-bearing and TRUE: E2 (the partial unique index) is MANDATORY and unconditional (Step E verified), so the correctness boundary genuinely exists independent of the lock, and the lock is genuinely demoted to efficiency-only in the same breath. A future reader is told precisely what is and is not proven. |
| **W-2ii** | Is the "test-topology-only release proof" acceptance coherent + routed? | **YES — ACCEPT AS STATED. Not re-raised.** G-20 item (ii) states the caveat inline; Test Infra note M2-2 (`:915`) records the mechanism (per-row `commit()` returns the connection, so the unlock may no-op on a different connection under the pooled production shape) and routes it via **S-27** to `process/general-plans/active/capacity-hardening_25-07-26/transaction-pooler-advisory-lock-audit_NOTE_25-07-26.md` — **file confirmed to exist on disk**. The acceptance names both the scope of the proof and the owner of the residual. |
| **W-3** | Are the four "LIFO pool" corrections accurate? | **YES — CLOSED, and the correction is factually right.** All four live locations (B3b `:331`, D8 trap `:421`, G-20 row `:843`, Test Infra note 5 `:913`) now attribute same-session re-entrancy to **single-connection pool population in a single-tasked test**, explicitly NOT LIFO. Verified live: `use_lifo: bool = False` at `.venv/…/sqlalchemy/pool/impl.py:79` — the cited line is exact. `tests/conftest.py` passes only `pool_size=5`, no `pool_use_lifo`. |
| **W-3** | Is D8's single-session precondition stated? | **YES — CLOSED (`:426-435`).** Mandatory, names every operation that must go through the one `db` session, states the failure mode (probe runs on a connection that never held the lock → returns `False` unconditionally → permanently-passing assertion), and flags that the trap is LIVE because the fresh-session read-back pattern is endorsed for Phase 2b. Coherent with the harness: `tests/conftest.py`'s `test_db` fixture yields exactly one session. |
| **W-3** | Is the `_LOCK_KEY` import-assert mandated? | **YES — CLOSED (`:437-444`).** `from apps.api.services.coop_expiry_sweep import _LOCK_KEY` + `assert _LOCK_KEY == "coop_expiry_sweep"` before the probe, with the reason stated (unlock on an unheld key returns the PASSING value, so key drift makes leg (a) pass forever). Matches the service's declared module-level `_LOCK_KEY` at `:293`. |
| **W-3** | Does E1 fold into the one mandatory migration file? | **YES — CLOSED, four locations agree.** E1 checklist (`:493`), E2 (`:459-460`), and both Blast Radius migration rows (`:129-130`) all state the E1 index is added to `{rev}_add_coop_expire_unique.py` and that `add_coop_ledger_indexes.py` is never created as a second file. The retracted "chain a second migration" wording is gone and its two-heads collision class is named explicitly. |
| **W-3** | Is the "prose only" retraction consistent everywhere? | **ALMOST — one surviving instance → C4-3.** All build-spec locations are correct and explicit (Blast Radius `:121`, F5-3 paragraph `:132-138`, E2 `:470`, Touchpoints `:793`). **One survivor at `:942`** inside `## Inner Loop Refresh Note`: "`models/identity_coop.py` is MODIFIED-prose-only, no longer READ ONLY". It is a dated changelog of the split (which predates the cycle-2 F2b-2 fix), not a build spec — so it does not re-open F2b-2 for an implementer reading either authoritative location, both of which retract it in bold. Graded LOW. |
| **W-4** | All 9 `-k` selectors 0-hit in `tests/`? | **YES — re-grepped live 17-08-26, all 9 return 0 files.** |
| **W-4** | Each selector a substring of exactly one mandated `test_coop_*` name, both directions? | **YES — verified mechanically both ways.** 9 selectors → 9 distinct mandated names, 1:1. No selector is a substring of a second mandated name (checked the two near-collisions: `coop_expiry_never_negative` vs `coop_expiry_sweep_*`, and `coop_expiry_sweep_entrypoint_runs_twice` vs `coop_expiry_sweep_is_idempotent` — neither is a substring of the other). The three mandated names with no selector (`…expired_credit_excluded…`, `…expiry_sweep_is_idempotent`, `…hold_window_blocks_spend`) are D3-D6 items covered by the lane gates G-11/G-12, not gate selectors — correct by design. |
| **W-4** | Blast Radius ⇄ Touchpoints consistent? | **YES.** Both list the same **10 files**, both mark `models/identity_coop.py` as MODIFIED ~12 lines / NOT prose-only, both state the E1-folding rule. Touchpoints declares itself a derived view that must never disagree. |
| **W-4** | Contradictions introduced by this round? | **NONE FOUND** beyond C4-3 (a changelog line the round did not touch). |
| **SECONDARY** | Live alembic head re-derivation, pinned DSN | **RUN — single head `a8c2f47e91b6`, no branching.** `DATABASE_URL` pinned to `localhost:5433`; `.env` was never read. This is a control observation only — per S-24/C3-7 the head MUST be re-derived LIVE at EXECUTE and **no head recorded in this plan may be chained off**, including this one. |

---

### Net gate derivation

#### Layer 1 dimensions

| Layer 1 dimensions | Status |
|---|---|
| Infra fit | PASS |
| Test coverage | CONCERN |
| Breaking changes | PASS |
| Security surface | PASS |

#### Layer 2 sections

| Layer 2 sections | Status |
|---|---|
| Step A — consumption aggregation (A1-A5) | CONCERN — C4-1, C4-2 |
| Step B — FIFO lots + expiry + sweep (B1-B4) | PASS |
| Step D — tests (D1-D12) | CONCERN — C4-1 lands in D1's fixture |
| Step E — migrations (E1/E2 + model mirror) | PASS |
| Verification Evidence gate table (G-3…G-23, K-2/K-3/K-5) | PASS |
| Scope hygiene post-split | CONCERN — C4-3 |

**Totals: 0 FAILs / 3 CONCERNs / 3 PASSes (Layer 2) + 3 PASSes / 1 CONCERN (Layer 1)**

**→ Net Gate: CONDITIONAL**

Rationale: zero FAILs. All three CONCERNs have deterministic one-line fixes carried as binding
EXECUTE instructions (E-10, E-11, E-12). Per the vacuous-green ban: no developed behavior in 2a rests
on Known-Gap alone — consumption is gated by G-3/G-17/G-19/G-22, FIFO by G-23a, expiry by G-18's five
legs + G-20 + G-21, the migration by G-15b, the scheduler registration by G-23(b)/(c). K-5 (the
wrapper's runtime flag check) is the one behavior with no executing tier and it is a **named residual
with written justification and resolution D**, which is exactly why this gate is CONDITIONAL and not
a terminal PASS.

---

### Verified CLOSED this cycle (source-checked — do not re-litigate)

| Item | Evidence |
|---|---|
| **F3a-1** (the cycle-3 FAIL) | G-3 expected count is a non-zero EXACT **1**; row (a) and row (d) both carry mandated ORM-created identity rows; G-17 mandates one per edge row plus a non-zero pre-assert mirroring G-19. `return 0` and missing-`site_id` both now fail. |
| **A2 join mechanism** | `_sync_identity_pii` confirmed live at `services/pii_encryption_hooks.py:33-36` writing `email_bidx = email_hash(target.email)`; `IdentifiedVisitor` composite key `uq_identified_site_visitor (site_id, visitor_id)` confirmed at `models/visitor.py:199-205`. Join path is implementable exactly as specified. |
| **Consumption source** | `_log_owned_resolution` confirmed by symbol in `identity_resolver.py` hardcoding `category="identity", success=True, cost_usd=0.0` — so the plan's "those two axes are production-vacuous given the `provider` predicate" claim is TRUE and correctly reasoned. `OWNED_FREE_PROVIDERS` confirmed = `{form_capture, fingerprint_match, beam_identity_network, svid_reconcile}` at `identity_classification.py:74-79`. |
| **M3-1 / LIFO** | SQLAlchemy `use_lifo=False` default confirmed at the cited line. Four-place correction complete and accurate. |
| **M3-2 / key drift** | D8's `_LOCK_KEY` import-assert mandated with correct rationale. |
| **Gap 5 / L2-1** | E1 folds into the one mandatory migration file in all four locations. Two-heads collision class closed. Live head today is single (`a8c2f47e91b6`). |
| **C3-3 / F2b-2** | The F5-3 paragraph now reads "MODIFIED (~12 lines: S-10c prose + E2 index mirror)" with "Prose only" **RETRACTED** in bold, and states the consequence (skipping the `__table_args__` mirror → index absent from the `create_all`-built test DB → G-21 fails outright). |
| **G-15b** | Mandatory-always-runs migration gate present in the gate table, so the mandatory E2 migration is no longer proven only in Exit Gate prose. Model tier (G-21) and migration tier (G-15b) are correctly separated per C-5. |

---

### FAILs

**None.**

---

### CONCERNs

| ID | Finding | Severity | Fix |
|---|---|---|---|
| **C4-1** | **G-3's `provider` predicate is not deterministically forced.** Rows (b) (paid, `cost_usd > 0`) and (c) (`form_capture` — named in the plan as "the load-bearing row" precisely because it is the nearest confusable) are the only rows that can force `provider='beam_identity_network'`. The F3a-1 seeding subsection mandates matching `identified_visitors` rows for rows **(a)** and **(d)** only. Under the INNER join, rows (b)/(c) with unmatched `visitor_id`s are dropped and force nothing — a `provider`-less or `cost_usd`-based implementation then returns exactly 1 and passes G-3. The plan's own stated consequence of a missing `provider` predicate is a co-op credit **overcharge** in Phase 2b. Same family as F3a-1, one row over. | CONCERN (high) | Add to the seeding subsection: **"Rows (b) and (c) MUST also be joinable — seed them on row (a)'s `site_id` AND `visitor_id` (one identity row serves all three), or give each its own matching ORM-created `identified_visitors` row. An unjoinable row (b)/(c) forces no predicate at all."** Carried as **E-10** (binding at EXECUTE). |
| **C4-2** | **NULL `email_bidx` silently drops rows on both sides.** `_sync_identity_pii` writes `email_bidx = email_hash(target.email) **if target.email else None**` (live source). (i) *Fixture:* an `IdentifiedVisitor` created without an `email=` value gets `email_bidx = NULL`; under A2's `email_bidx NOT IN (SELECT …)` that row evaluates to NULL → filtered → the "mandatory identity row" silently fails to rescue its `api_usage_logs` row and G-3 collapses to 0 again. The subsection says "non-NULL `email_bidx`" but never says *how* (set a real `email`). (ii) *Implementation:* the same three-valued-logic behavior means any real identified visitor with no email is silently excluded from `consumption_count` — plausibly vacuous for `beam_identity_network` (graph hits are email-keyed) but currently undecided rather than decided. | CONCERN (medium) | Fixture: state explicitly that every mandated identity row is constructed with a real `email=` value, since the hook writes NULL otherwise. Implementation: A2 must make the NULL case a written decision — either `(email_bidx IS NULL OR email_bidx NOT IN (…))` or an explicit docstring statement that emailless identities are out of scope. Carried as **E-11**. |
| **C4-3** | **Surviving "prose-only" instance.** `## Inner Loop Refresh Note` (`:942`) still says "`models/identity_coop.py` is MODIFIED-prose-only, no longer READ ONLY". It is a dated changelog of the 17-08-26 split, not a build spec, and both authoritative locations retract the wording in bold — so it does not re-open F2b-2 in practice, but it is the one place a skimmer could still read the retracted claim. | CONCERN (low) | Amend `:942` to "…`models/identity_coop.py` is MODIFIED (~12 lines: S-10c prose + E2 index mirror), no longer READ ONLY". Carried as **E-12**. |

**Note on C4-1's grading.** A reviewer could defensibly call C4-1 a FAIL, since it leaves G-3's
primary advertised predicate unforced in one branch of author choice. It is graded CONCERN because
(i) the row exists and its purpose is stated verbatim — the defect is an unspecified `visitor_id`,
not a missing row; (ii) G-3 is no longer vacuous: `return 0` and missing-`site_id` both fail
deterministically; (iii) the plan's own generalizable rule and Test Infra note both already push the
author toward joinable identity rows; and (iv) the fix is a single sentence that a binding EXECUTE
instruction carries reliably. **If the user prefers zero author-dependence on a billing surface, run
one more supplement cycle applying E-10 and re-validate — that is a legitimate override of this
grading, and cheap.**

---

### Known gaps carried (this CONDITIONAL rests on exactly these — user acceptance required)

| ID | Gap | Why accepted |
|---|---|---|
| **K-2** | Multi-process concurrency on the H2 enqueue→sweep window | Inherited accepted (constraint e). Does NOT cover F2a-1's lock-release defect (fixed in-plan) nor the duplicate-EXPIRE class (closed at the DB tier by E2/G-21). |
| **K-3** | Any live flag-on gate | Blocked by constraint d (`coop_terms_version` placeholder pending legal re-pin). No 2a gate needs a real deployment flag flip; static coverage is G-23(b) + G-23(c); `monkeypatch` is the sanctioned substitute. |
| **K-5** | `_coop_expiry_sweep_job()`'s **runtime** `identity_coop_enabled` check | Executed by no tier. Unreachability is correctly SCOPED to the startup-flag-OFF case only; the runtime-flag-flip case IS reachable and is why L-1 mandates the check exist. Resolution D — backlog residual, revisit in 2b when the flag is live-flippable. |
| **G-20 residual (i)** | Lock **acquisition** is ungated — a no-lock implementation passes both legs | Accepted adjacent to K-2. Justification verified sound: E2's partial unique index is MANDATORY and is 2a's correctness boundary; the lock is efficiency-only. |
| **G-20 residual (ii)** | Leg (a) proves release in the **test topology only**, not under the pooled production shape | Accepted; routed via S-27 to `capacity-hardening_25-07-26/transaction-pooler-advisory-lock-audit_NOTE_25-07-26.md` (file confirmed present). |
| **G-20 residual (iii)** | The exception path (C-1: aborted transaction defeats the `finally` unlock) | Documented residual, adjacent to K-2; mitigated in-plan by mandated per-lot `try/except → rollback → continue` + pre-unlock `rollback()`. |
| **K-1 / K-4** | REVERSE-clawback semantics; orphan-lot / site_id-reuse for the SPEND writer | **Out of 2a scope by design — NOT CONDITIONAL-forcing.** K-1 is owned by `backlog/coop-credit-reversal-semantics_NOTE_16-08-26.md`; K-4 moved to Phase 2b. 2a's own EXPIRE-writer window is closed in-plan by the M-4 orphan guard. |

---

### Test gates

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| G-3 | per-live-site consumption count; `provider` + `site_id` predicates | Hybrid | `-k "coop_consumption_count_per_live_site"` (PG :5433, serialized) | B (E-10 closes the `provider` half) |
| G-4 | aggregation query plan / E1 trigger | Hybrid | `EXPLAIN` on disposable PG, ≥100k rows via `seed_api_usage_logs` | A |
| G-9 | ledger reconciliation, ≥200 randomized ops, ≥50 harness-tracked | Hybrid | `-k "coop_ledger_reconciles_exactly"` | A |
| G-11 | unit-lane regression | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -q` (:6379 CLOSED) | A |
| G-12 | integration-lane regression | Hybrid | `.venv/bin/python3.11 -m pytest tests/ -m integration -q` (SERIALIZED) | A |
| G-13 | zero new write surface on the resolver | Fully-Automated | `git diff HEAD --quiet --exit-code -- apps/api/services/identity_resolver.py` | A |
| G-13b | 2a/2b boundary — no spend wiring leak | Fully-Automated | `git diff HEAD --quiet --exit-code -- apps/api/services/billing.py apps/api/routers/billing.py` | A |
| G-15 | conditional E1 migration (subject IS the G-15b file) | Hybrid | DSN-pinned up/down/up on disposable PG | C (fires only on a seq scan) |
| G-15b | **mandatory** E2 migration; partial unique index drops+recreates | Hybrid | offline `<from>:<to>` validation + live round-trip on disposable PG | A |
| G-17 | naive/aware tz bound normalization + exact in-window count | Hybrid | `-k "coop_consumption_naive_tz_bounds"` | A |
| G-18 | expiry never negative — **five mandatory legs** | Hybrid | `-k "coop_expiry_never_negative"` | A |
| G-19 | erased-row exclusion, non-zero pre-exclusion guard | Hybrid | `-k "coop_erased_row_excluded_from_consumption"` | A |
| G-20 | sweep entrypoint: lock **release** post-condition (a) + progress (b) | Hybrid | `-k "coop_expiry_sweep_entrypoint_runs_twice"` | A (acquisition + prod topology = named residuals) |
| G-21 | duplicate EXPIRE rejected at the **DB tier** | Hybrid | `-k "coop_duplicate_expire_rejected_by_db"` | A |
| G-22 | `contribution_count` excludes `excluded_reason` rows | Hybrid | `-k "coop_contribution_count_excludes_excluded_reason"` | A |
| G-23a | FIFO ordering + drawn subtraction, clamped | Hybrid | `-k "coop_spendable_lots_fifo_order_and_drawn_subtraction"` | A |
| G-23b | scheduler registration present | Fully-Automated | `grep -n 'id="coop_expiry_sweep"' apps/api/jobs/scheduler.py` ≥1 hit | A |
| G-23c | `add_job` sits inside the `identity_coop_enabled` guard | Agent-Probe | read `apps/api/jobs/scheduler.py`, judge lexical scope, record verbatim | A |
| K-5 | wrapper runtime flag check | — | *(no proving test — named residual)* | D |

gap-resolution legend: A — proven now · B — fixed in this plan · C — deferred to a named later
phase/plan · D — backlog test-building stub (named residual).

Legacy line form:
- consumption (`consumption_count`/`contribution_count`): Hybrid — `pytest tests/ -m integration -q -k "coop_consumption_count_per_live_site"` etc.; precondition PG :5433 + Redis, SERIALIZED
- FIFO/expiry: Hybrid — `-k "coop_expiry_never_negative"`, `-k "coop_expiry_sweep_entrypoint_runs_twice"`, `-k "coop_duplicate_expire_rejected_by_db"`, `-k "coop_spendable_lots_fifo_order_and_drawn_subtraction"`
- migration: Hybrid — G-15b offline `<from>:<to>` + live round-trip on a disposable Postgres, `DATABASE_URL` pinned to localhost
- purity guards: Fully-automated — `git diff HEAD --quiet --exit-code -- <path>` (G-13, G-13b)
- scheduler flag-gating: agent-probe — G-23(c) lexical-scope judgment
- wrapper runtime flag check: known-gap: documented as K-5

No TDD failing stubs are emitted for Hybrid / Agent-Probe / Known-Gap rows. The only
Fully-Automated rows (G-11, G-12 lanes, G-13, G-13b, G-23b) are command/diff gates, not
behavior tests, so no `test(...)` stub applies.

---

### Dimension findings

- Infra fit: PASS — Docker/PG :5433/Redis :6379 confirmed UP; the unit-lane-vs-Redis precondition
  conflict is resolved by run-scoped ordering (integration with Redis up, then stop `infra-redis-1`,
  then unit) with the off-PATH Docker CLI named inline. Migration path is single-head today.
- Test coverage: CONCERN — C4-1 (G-3's `provider` predicate is author-dependent), C4-2 (NULL
  `email_bidx` can silently re-vacuum the fixture). Everything else is tiered with exact commands and
  a stated non-vacuity guard.
- Breaking changes: PASS — read-only consumption path, `api_usage_logs` write path unchanged,
  `spendable_balance` FROZEN, `identity_resolver.py` empty-diff enforced as a gate, billing surface
  fenced by G-13b.
- Security surface: PASS — no auth/PII surface added; A2 reads `email_bidx` blind indexes only, never
  plaintext; the erased-row exclusion inherits the wider tombstone-at-enqueue meaning (excludes more,
  sooner — the safe direction).
- Step A feasibility: CONCERN — join path verified implementable exactly as specified; C4-1/C4-2 above.
- Step B feasibility: PASS — window-blind `remaining`, S-10b stamping, the single-statement
  `INSERT … SELECT … WHERE EXISTS … ON CONFLICT DO NOTHING` orphan guard, and B3b's lock+commit
  granularity are all specified verbatim with correct precedents.
- Step D feasibility: CONCERN — 12 test items, all named, all 9 selectors 0-hit and 1:1; C4-1 lands
  in D1's fixture.
- Step E feasibility: PASS — E2 mandatory + model mirror + one-file E1 folding; both proof tiers
  separated (G-21 model / G-15b migration).
- Scope hygiene: CONCERN — C4-3 only.

---

### Open gaps

- **C4-1** — G-3 rows (b)/(c) unjoinable ⇒ `provider` predicate author-dependent. Fix via E-10.
- **C4-2** — NULL `email_bidx` drops rows silently on both fixture and implementation sides. Fix via E-11.
- **C4-3** — one surviving "prose-only" changelog line. Fix via E-12.
- **K-2 / K-3 / K-5** — accepted known-gaps (see the table above); K-5 is `known-gap: documented`,
  resolution D, revisit in Phase 2b.
- **G-20 residuals (i)(ii)(iii)** — accepted, documented, and routed (S-27). Re-confirmed coherent
  this cycle; **do not re-raise**.
- K-1 / K-4 — out of 2a scope; not CONDITIONAL-forcing.

---

### What this coverage does NOT prove

- **G-3** does not prove the `provider` predicate unless rows (b)/(c) are made joinable (C4-1/E-10).
  It never proves `success`/`category` filtering — those axes are production-vacuous given the
  `provider` predicate (hardcoded in `_log_owned_resolution`), deliberately ungated.
- **G-17** proves window bounds and exact in-window counts; it does not prove behavior across a DST
  transition or a non-UTC server timezone.
- **G-18** proves five expiry legs against `expire_lapsed_lots` **called directly**; it proves
  nothing about `run_coop_expiry_sweep`, the advisory lock, or scheduler registration.
- **G-20** proves the lock-release POST-CONDITION and forward progress. It does NOT prove: lock
  acquisition (a no-lock implementation passes), release under the pooled production shape, the
  aborted-transaction exception path, or the wrapper's runtime flag check (K-5).
- **G-21** proves the index at the **model/`create_all`** tier only. **G-15b** proves the migration
  file. Neither proves the other; a green G-21 with a broken migration is possible and vice versa.
- **G-23b/c** prove the registration exists and is lexically flag-guarded. Neither executes the job.
- **G-11/G-12** are lane regressions; a green lane proves no regression, not that new behavior works.
- **No gate** runs with `identity_coop_enabled` genuinely ON in a deployed process (K-3), and no gate
  covers multi-process concurrency on the enqueue→sweep window (K-2).
- The live alembic head recorded here (`a8c2f47e91b6`) proves only that the chain is single-headed
  **today**; it is not a chaining target — S-24 mandates LIVE re-derivation at EXECUTE.

---

### Execute-agent instructions

| # | Instruction | Trigger |
|---|---|---|
| **E-10 (NEW, binding)** | Before writing D1: make G-3 rows **(b)** and **(c)** joinable — seed them on row (a)'s `site_id` AND `visitor_id` (one identity row serves all three), or give each its own matching ORM-created `identified_visitors` row. An unjoinable (b)/(c) forces no predicate. Then confirm by inspection that removing the `provider` filter from `consumption_count` would make G-3 red; record that reasoning in the phase report. | Step D, item D1 |
| **E-11 (NEW, binding)** | Construct every mandated `identified_visitors` row with a real `email=` value — `_sync_identity_pii` writes `email_bidx = NULL` when `email` is falsy, and a NULL `email_bidx` is filtered out by `NOT IN` (three-valued logic), silently re-vacuuming the fixture. Separately, A2 must make the NULL case a **written** decision (either `(email_bidx IS NULL OR email_bidx NOT IN (…))` or an explicit docstring exclusion), recorded in the phase report. | Steps A2 / D1 / D2 |
| **E-12 (NEW)** | Amend `## Inner Loop Refresh Note` line 942 to drop "MODIFIED-prose-only" in favour of "MODIFIED (~12 lines: S-10c prose + E2 index mirror)". Documentation-only. | Any time before closeout |
| **E-7 (carried)** | Spawn one independent adversarial verifier instructed to REFUTE (default verdict REFUTED) on any further supplement cycle. External verifiers found the top defect in cycles 1-3. | Any re-validation |
| **S-24 / C3-7 (carried, mandatory)** | Re-derive the alembic head LIVE with `DATABASE_URL` pinned to `localhost:5433` immediately before writing the E2 migration. **No head recorded in this plan may be chained off**, including `a8c2f47e91b6`. Bare alembic hits Supabase PROD via `.env`. | Step E |
| **S-25 (carried)** | Re-grep all 9 `-k` selectors at EXECUTE; locate every code anchor by **symbol**, never by line number. | Step D |
| **S-23 (carried)** | Re-baseline the unit lane at EXECUTE. A unit-lane run performed with :6379 LISTENING is not a valid G-11 green — stop `infra-redis-1` first and record the `lsof` verification. | G-11 |
| **Gap 7 (carried)** | Capture and report any `coop_expire_lot_failed` log lines during the integration gate run; a systemic INSERT failure otherwise reads as a silent zero-row sweep. | G-12 / G-18 |
| **E-8 (carried)** | Do NOT re-open: the A2 INNER-join decision (L-2), the sweep design, the S-10b stamping rule, the M-4 orphan guard, the G-20 two-leg design, or the E2 index decision. All re-verified sound this cycle. | Throughout |

---

Gate: CONDITIONAL
Accepted by: **PENDING USER ACCEPTANCE** — this CONDITIONAL rests on exactly these named gaps:
**K-2** (multi-process concurrency), **K-3** (no live flag-on gate), **K-5** (sweep-wrapper runtime
flag check, resolution D), and the three **G-20 residuals** (ungated lock acquisition; release proven
in test topology only, routed via S-27; the aborted-transaction exception path) — plus the three
CONCERNs **C4-1 / C4-2 / C4-3**, each carried as a binding EXECUTE instruction (E-10 / E-11 / E-12).
Accept these to unblock EXECUTE, or override C4-1 to FAIL and run one more supplement cycle applying
E-10 first.

---

## ARCHIVED VALIDATE CONTRACTS — ALL SUPERSEDED BY THE 17-08-26 SPLIT

Every contract below was written against the pre-split Phase 2 scope (consumption + expiry + spend +
REVERSE in one phase). None is authoritative. They are retained verbatim for the PVL chain and for
the finding archaeology their FAILs/CONCERNs carry. **PVL must re-run from V1 against the Phase 2a
scope defined above.**

## [SUPERSEDED 17-08-26 — SPLIT] Validate Contract

> **⚠️ SUPERSEDED 16-08-26 — DO NOT ACT ON THIS CONTRACT.** This is the 07-08-26 outer-pvl artifact.
> Both of its FAILs are resolved: **F0** (dependency chain) — Phase 1 shipped `d78b4f1`, SPEC A is
> LIVE; **F1** (spend-target wiring) — closed by decision **P2-D3** per the Phase 1 D-D constraint.
> Its Entry-Gate table, `Totals: 3 FAILs`, and `Gate: BLOCKED` verdict are all stale, as are
> findings F2-F7 (all applied or answered). See `## Refresh Supplement (16-08-26)` above for
> current reality. **PVL must re-run from V1**; vc-validate-agent owns writing the replacement
> contract. Retained for audit only.

Status: BLOCKED (**SUPERSEDED — see note above**)
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

---

## [SUPERSEDED 17-08-26 — SPLIT] Validate Contract (inner-pvl, cycle 5, 16-08-26) — AUTHORITATIVE

> Supersedes the cycle-3 inner-pvl contract (BLOCKED) and, transitively, the 07-08-26 outer-pvl
> contract (banner-marked SUPERSEDED above). Validates the FOUR-times-repaired
> `## Refresh Supplement (16-08-26)`: P2-D1..P2-D6, M-1..M-3, S-1..S-26, 18 gates + K-1..K-4.
> Scope of this pass: verify closure of cycle-3's F3-1/F3-2 + the adversarial H-A/M-A/M-B/M-C/L-1/L-2,
> then hunt defects the four repair rounds introduced.

Status: BLOCKED
Date: 16-08-26
date: 2026-08-16
generated-by: inner-pvl: phase-2
supersedes: 2026-08-16 (inner-pvl: phase-2, cycle 3) — cycle 5 re-verified the cycle-4 repairs against live source

Parallel strategy: sequential
Rationale: single-pass source verification prioritized on W-1..W-5. The Agent tool is unavailable to
this agent in this environment (memory note `validate-agent-no-agent-tool-needs-external-fanout`), so
Layer 1 / Layer 2 fan-out ran as one sequential source-read pass. Signal count 5/7 (S1 multi-package,
S2 billing surface, S4 phase program, S6 high-risk class billing/credits, S7 ≥5 files) — HIGH would
normally warrant an agent team. E-7 (external adversarial verifier) remains the compensating control
and has found the top defect in 6 of 6 prior cycles on this program. **This cycle a single sequential
pass found 3 FAILs unaided; E-7 is still mandatory before EXECUTE.**

### Headline — cycle-3's two FAILs are CLOSED; three NEW FAILs replace them

The cycle-4 repairs to F3-1 (savepoint), F3-2 (G-7 leg (v)), H-A (G-6 negative leg), M-A
(`remaining` definition), M-B (S-2c lock) and M-C (distinct sessions) all landed and were verified
against live source. Three defects the repairs introduced or left uncovered now block:

| New FAIL | One-line |
|---|---|
| **F5-1** | G-6 cannot discriminate try-and-skip — the counter `UPDATE`'s users-row lock already serializes every same-user `increment_usage`, so the advisory lock never contends. Constraint 16 / S-14 has no proving gate. |
| **F5-2** | `remaining` is defined only for `reverse_credit`. Under the window-AWARE reading `expire_lapsed_lots` writes **zero rows forever** — and passes all four G-18 legs. No gate asserts the sweep writes anything. |
| **F5-3** | The C3-2 "single source of truth" reconciliation is incomplete: `## Blast Radius` lists 10 files while claiming 11, and `## Touchpoints` marks `models/identity_coop.py` **READ ONLY** — the file S-1 and S-10c both mandate editing. |

### Net gate derivation

#### Layer 1 dimensions

| Layer 1 dimension | Status |
|---|---|
| Infra fit | CONCERN — sweep placement/scheduler pattern verified; advisory-lock accumulation across the sweep transaction unspecified (C5-2) |
| Test coverage | **FAIL** — F5-1 (no gate discriminates the forbidden lock shape), F5-2 (no gate proves the sweep writes a row), C5-1 (leg (v) names an impossible injection) |
| Breaking changes | PASS — signatures frozen; the 5-caller census re-confirmed against live source |
| Security surface | PASS — flags OFF, no new external surface, no PII in the new log events |

#### Layer 2 sections

| Layer 2 section | Status |
|---|---|
| P2-D6 / S-13b savepoint posture | PASS |
| P2-D1 / S-2 / S-2b / S-2c REVERSE | CONCERN (C5-3) |
| P2-D5 / S-10b / S-11 stamping + sweep | **FAIL** (F5-2) |
| P2-D3 / S-13 / S-15 / S-15b spend wiring | CONCERN (C5-4, C5-6, C5-7) |
| S-14 / G-6 concurrency | **FAIL** (F5-1) |
| Blast Radius / Touchpoints / B4 reconciliation | **FAIL** (F5-3) |
| Gate set non-vacuity (`-k` selectors) | PASS — all 13 selectors re-grepped, 0 hits each |

**Totals: 3 FAILs / 11 CONCERNs / 5 PASSes**

**→ Net Gate: BLOCKED**

### Verified CLOSED this pass (source-checked — do not re-litigate)

| Cycle-3 item | Closure evidence |
|---|---|
| **F3-1 savepoint** | The mandated shape is the live shipped precedent at `apps/api/services/graph_erasure.py:218-231`: `try:` → `async with db.begin_nested():` → `except Exception:` → **one** `await db.commit()` after. (a) Savepoint rollback releases only to the savepoint, leaving the enclosing transaction committable — proven by that shipped, tested call site and by `services/identity_coop.py:175`. (b) Ordering is correct: the counter `UPDATE` is emitted FIRST and OUTSIDE the try (`billing.py:142-146`), so `.returning()` yields the post-increment count and no savepoint rollback can undo it; the single `commit()` at the end commits the counter regardless. (c) Budget fits: the graph_erasure precedent is ~13 lines incl. its comment, so S-13b's ~12 is tight-but-plausible; billing.py totals ≈56-58 against the ≤70 SSOT budget. |
| **F3-2 leg (vi)** | Confirmed against source: `resolution_runner.py` `check_usage_allowed` at **:161** is OUTSIDE the per-visitor `try:` (**:172**, `except` at **:182**) while `increment_usage` is at **:178** inside — the batch-kill shape is real. `resolution_tasks.py` `:120`/`:135` confirmed (see C5-9). |
| **F3-2 leg (v) constructibility** | Constructible — but only via the SECOND stated mechanism (`SELECT 1/0`); the first is impossible (C5-1). |
| **H-A — G-6 negative leg passable** | Yes. A correct implementation with 1 credit and 2 concurrent over-limit calls yields exactly 1 SPEND, counter delta 2, balance 0 — precisely what the rewritten leg asserts. The old unpassable wording is gone. |
| **H-A — S-17 reconciliation clause** | Genuinely removes the contradiction (does not restate it). The regime split is sound: *credits remaining* ⇒ a lost spend is a defect; *credits exhausted* ⇒ an un-backed increment is bounded accepted noise. G-6 no longer forbids what S-17/G-10 accept. |
| **M-A skip-when-zero vs G-1 idempotence** | Does not break it — skip-when-zero **is** the idempotence mechanism. Walked: ACCRUE +5 → SPEND −2 → late REVERSE −3 (raw SUM 3) → re-run computes 0 → writes nothing. G-1 legs 3-4 assert exactly this. |
| **M-B key derivation + deadlock** | Derivation IS specified (`key = str(user_id)` via lot `site_id → sites.user_id`). No deadlock cycle exists: `spend_credits`, `reverse_credit` and each sweep iteration take exactly ONE lock, all on the same key space — a cycle requires two locks in differing orders and no path takes two. |
| **Caller census** | Re-verified live: `routers/visitors.py:959` check / **:969** `increment_usage`, and :969 is genuinely UNWRAPPED (the `try` below covers only the Enricher). |
| **Gate-set non-vacuity** | All 13 `-k` selectors re-grepped over `tests/` → **0 hits each**. Neither target file exists. The exit-5 property holds. |
| **Structural validator** | `validate-plan-artifact.mjs` → **0 failures**, 2 advisory legacy-shape warnings (no execute-anchor note / no supporting-phase-file notes). Not blocking. |

### FAILs (must be closed before EXECUTE)

**F5-1 — G-6 cannot discriminate the forbidden try-and-skip shape; Constraint 16 / S-14 is ungated.**
Constraint 17 / P2-D6 step 5 / S-13b place the counter `UPDATE` **outside and before** the try. That
statement is `UPDATE users SET monthly_identified_count = monthly_identified_count + 1 WHERE id = :uid`
(`apps/api/services/billing.py:142-146`) — a row-level exclusive lock on the user tuple, held until
COMMIT. Two concurrent `increment_usage` calls **for one user** therefore serialize on that row lock
*before either reaches* `pg_advisory_xact_lock`. Consequences:
- `pg_try_advisory_lock` would **always return True** at this call site, so the forbidden try-and-skip
  shape conserves exactly like the mandated blocking shape: N credits / N concurrent calls ⇒ N SPEND
  rows on **both**. G-6's conservation legs (N=2, N=3) pass on the defect.
- The plan's stated non-vacuity rationale — *"The property that actually kills try-and-skip is
  CONSERVATION, not denial"* (G-6 row) — is **false as written**, and it is the only justification
  offered for S-14 / Constraint 16.
- The rewritten negative leg (1 credit, 2 calls ⇒ 1 SPEND / counter +2 / balance 0) is likewise
  satisfied by try-and-skip. So **no leg of G-6 discriminates**, and no other gate proves S-14.
The lock is still *required* — it is what makes S-2c/Constraint 12b compose with `reverse_credit` and
the sweep, neither of which touches the users row. It is the GATE that must change, not S-14.
**Fix (both, cheap):**
1. Add a G-6 leg that drives `spend_credits(db, user_id, 1)` **directly** from N distinct sessions via
   `asyncio.gather` (bypassing `increment_usage`, hence no users-row lock), asserting **exactly N SPEND
   rows** for N spendable credits. This is the leg try-and-skip fails.
2. Add a Fully-Automated mechanical gate: `grep -n "pg_try_advisory_lock" apps/api/services/identity_coop.py`
   must not match the FIFO-draw path (and `pg_advisory_xact_lock` must). Exit-code asserted.
3. Record the row-lock interaction in S-14 so a future reader does not "simplify away" the advisory
   lock as redundant — it is redundant on the `increment_usage` path only.

**F5-2 — `remaining` is undefined for the expiry sweep; the window-aware reading makes the sweep
silently inert and still green.**
S-2 defines `remaining_at_write_time` as the **window-BLIND raw lot SUM**, explicitly and only for
`reverse_credit`. B3 and S-11 use the bare word `remaining` with **no definition** and no cross-reference
to S-2's. But `expire_lapsed_lots` operates *by construction* on lots already past `expires_at`, where
every row for that lot is out of window — so the window-AWARE lot sum is **always 0**, `max(0, 0) == 0`,
and S-11's own skip-when-zero rule then skips **every lot, forever**. Zero EXPIRE rows are ever written.
That inert implementation passes the entire gate set:
- G-18 legs 1-2 assert `spendable_balance == 0`, which the plan itself concedes *"would pass with no
  sweep at all"* under the new stamping;
- G-18 leg 3 explicitly permits *"either no EXPIRE row or a NEGATIVE one"*;
- G-18 leg 4's per-row stamp assertion is **vacuously true** when no EXPIRE rows exist (its NULL-stamp
  negative control uses seeded rows, not sweep-written ones);
- AC-7 idempotence ("re-running writes zero additional rows") is trivially satisfied by writing none;
- G-9's harness-tracked oracle is unaffected — the sweep does not move the balance either way.
**No gate anywhere asserts that the sweep writes a row.** This is the same vacuity class as F3-2.
**Fix:** (i) restate the window-blind definition verbatim in B3 and S-11 (or replace both bare uses with
`remaining_at_write_time` and cross-reference S-2), stating explicitly that the window-aware reading is
always 0 for a lapsed lot and is therefore forbidden; (ii) add a **G-18 positive leg**: a normal lapsed,
unspent lot ACCRUE `+N` must produce **exactly one** EXPIRE row with `amount == -N`, stamped `[S,E]` from
the lot, and a second sweep run must add **zero** rows — making AC-7's idempotence claim non-vacuous.

**F5-3 — Blast Radius single-source reconciliation is incomplete; Touchpoints contradicts a mandated edit.**
C3-2 declared the `### Supplement Blast Radius` table the single source of truth (11 rows) and claimed
the derived views were reconciled. They were not:
- `## Blast Radius` (`:98-113`) contains **10** bullets while asserting "**11 files**" (`:115`).
  The missing entry is **`apps/api/models/identity_coop.py`** — SSOT row 1, budget ~10 lines,
  mandated by **S-1** (add `"REVERSE"` at three vocabulary sites) and **S-10c** (amend two of the three
  "ACCRUE only" comments).
- `## Touchpoints` (`:288`) lists that same file as "**READ ONLY — schema fixed in Phase 1**" — a direct
  contradiction of S-1 and S-10c. An EXECUTE agent honoring the Touchpoints annotation skips both items,
  and S-25's budget sweep would then report a file edited that scope says must not be.
**Fix:** add `apps/api/models/identity_coop.py (MODIFIED — S-1 REVERSE vocabulary + S-10c comment
amendment)` to `## Blast Radius` (restoring the count to a genuine 11) and change the `## Touchpoints`
entry from READ ONLY to MODIFIED with the same annotation.

### CONCERNs

| # | Concern | Fix |
|---|---|---|
| C5-1 | **G-7 leg (v) names an impossible injection mechanism first.** *"force an `IntegrityError` by inserting a duplicate ledger row (violating the partial-unique dedup index)"* — `identity_credit_ledger` has **no unique index**: `models/identity_coop.py:129-131` declares three plain indexes (`site_id`, `lot_id`, `expires_at`). The partial-unique `postgresql_where=text("accrued IS TRUE")` index at `:85-90` is on **`identity_contribution_events`**, a different table. A duplicate ledger insert succeeds silently ⇒ no transaction abort ⇒ leg (v) passes on the defective bare-try shape, re-opening F3-2. | Delete the IntegrityError wording; mandate `await db.execute(text("SELECT 1/0"))` inside the draw (or a NOT-NULL violation on `identity_credit_ledger.reason`) as THE mechanism. |
| C5-2 | **Sweep advisory-lock accumulation (introduced by S-2c).** `pg_advisory_xact_lock` is not released until the transaction commits — the plan states this itself. S-2c takes one per **lot iteration** of `expire_lapsed_lots`; the commit boundary is unspecified in S-11 and S-21. A single sweep transaction over many users therefore holds one lock per distinct user for the whole sweep, blocking every affected user's request-path draw, and risks `max_locks_per_transaction` exhaustion at scale. Flags OFF ⇒ Phase-2 exposure NONE (pre-flag-flip, same class as K-4). | Specify per-user (or bounded-batch) commit in S-11/S-21, or acquire the lock once per distinct user. Record alongside K-4 in the enable runbook. |
| C5-3 | **`reverse_credit` lock-key derivation has no defined behavior when the lot's site row is gone** (the K-4 orphan class): `lot.site_id → sites.user_id` can return no row, leaving `hashtext(None)` or a `scalar_one()` raise. | State the fallback in S-2c: skip + `logger.warning`, write no row, return 0. |
| C5-4 | **Stale budget cross-reference.** S-13 and finding C3-4 both say *"the ≤60-line budget absorbs both"*, while the SSOT table says **≤70 lines** (raised cycle 4). | Update both to ≤70. |
| C5-5 | **Stale line citations the cycle-4 fix missed.** The Supplement Blast Radius `models/identity_coop.py` row and P2-D5's "Docstring/comment debt" paragraph both cite `:146`/`:150`; S-10c already corrected these to the live `:144`/`:148`/`:152` (verified live this pass). | Re-anchor both to the comment strings (S-25 already mandates this at EXECUTE). |
| C5-6 | **The user-level spendable-credit helper is never named or given a home.** S-13/S-15/S-15b all reference "the D-D join" / "the SAME helper the read gate uses", but no S-item creates it and no blast-radius row budgets it. It presumably belongs in `identity_coop.py` (~320-line budget). | Name it (e.g. `user_spendable_credit(db, user_id)`) in S-13 and attribute its lines to the `identity_coop.py` row. |
| C5-7 | **Two User reads, unstated.** S-13(i) puts `.returning(User.monthly_identified_count)` on the counter UPDATE (outside the savepoint) while P2-D6 step 1 puts the plan/`current_period_end`/`bonus_monthly_quota` read inside it. Harmless, but an implementer folding those columns into the `.returning()` clause is equally valid and moves the read outside. | One clarifying sentence in S-13 permitting either. |
| C5-8 | **The "REVERSE OR EXPIRE" Phase-3 reporting rule is unreachable for its audience.** It lives only inside S-2's ordering-consequence bullet in the Phase 2 checklist. No S-item propagates it to the `reverse_credit`/`expire_lapsed_lots` docstrings, the phase report, or `phase-3-contributor-surface_PLAN_07-08-26.md`. S-10c mandates a docstring hazard line for the balance-vs-reporting predicate but not this one. | Add it to the S-12/S-10c docstring mandate AND append one line to the Phase 3 plan. |
| C5-9 | **`resolution_tasks.py` is worse than the plan states.** Verified `:117-140`: that loop has **no per-visitor `try/except` at all**, so a poisoned session kills the whole Celery task, not just the batch. The plan's "same shape at `tasks/resolution_tasks.py:120`/`:135`" understates it (conservatively). | One clause in G-7 leg (vi). |
| C5-10 | **S-20/S-24 environment facts have already drifted again** (informational — S-24's live re-derivation design is correct and validated by exactly this): live `alembic heads` with `DATABASE_URL` pinned to `localhost:5433` now returns **`a8c2f47e91b6` (single head)**, not the remembered `e4b1d78c3a05`; and `git status --short apps/api/migrations/versions/` is now **EMPTY** — the "three untracked migrations" are tracked. | No plan change needed; E-1 already mandates live re-derivation. Update the parenthetical example so it is not read as current. |
| C5-11 | **S-23 / S-25 remain unverified EXECUTE-time obligations** (unchanged from cycle 3 / C2-11): the unit-lane baseline (2801 passed / 2 skipped) was not re-run this pass, and the budget/citation sweep is not runnable before implementation. | Carried as EXECUTE obligations E-1/E-6; no plan change. |

### Test gates

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| G-1 | REVERSE writes one stamped audit row; window-blind `-max(0, remaining)`; ordering + zero-skip legs | Hybrid | `.venv/bin/python3.11 -m pytest tests/ -m integration -q -k "coop_reverse_credit"` | A |
| G-2 | REVERSE never increases balance (`0 <= after <= before`); expired leg exactly 0; concurrency leg | Hybrid | `... -k "coop_reverse_no_balance_increase"` | A |
| G-3 | Per-live-site consumption count | Hybrid | `... -k "coop_consumption_count_per_live_site"` | A |
| G-4 | Aggregation query plan on ≥100k rows | Hybrid | `EXPLAIN` on a disposable PG, pasted in the phase report | A |
| G-5 | FIFO user-pooled draw; SPEND carries the drawn lot's `site_id` | Hybrid | `... -k "coop_fifo_user_pooled_draw"` | A |
| G-6 | Concurrent draw conserves spends; blocking lock, not try-and-skip | Hybrid | `... -k "coop_concurrent_increment_no_double_draw"` | **B — F5-1: current legs cannot discriminate try-and-skip; needs the direct-`spend_credits` leg + the grep gate** |
| G-7 | Co-op failure is swallowed; counter committed; no 500; DB-level + batch legs | Hybrid | `... -k "coop_spend_failure_swallowed"` | **B — C5-1: leg (v)'s first injection mechanism is impossible; mandate `SELECT 1/0`** |
| G-8 | Flag-off billing byte-identical, zero coop queries | Hybrid | `... -k "coop_flag_off_billing_unchanged"` | A |
| G-9 | ≥200-op reconciliation with harness-tracked oracle + hold precondition | Hybrid | `... -k "coop_ledger_reconciles_exactly"` | A |
| G-10 | Seven S-17 edge cases incl. bounded L-3 noise | Hybrid | `... -k "coop_edge"` | A |
| G-11 | Unit lane green | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -q` | A |
| G-12 | Integration lane green (serialized) | Hybrid | `.venv/bin/python3.11 -m pytest tests/ -m integration -q` | A |
| G-13 | Resolver untouched | Fully-Automated | `git diff HEAD --quiet --exit-code -- apps/api/services/identity_resolver.py` | A |
| G-14 | Daily budget untouched | Hybrid | `... -k "coop_daily_budget_untouched"` | A |
| G-15 | Conditional migration round-trip | Hybrid | `DATABASE_URL`-pinned up/down/up on a disposable PG | A |
| G-16 | Dashboard/gate limit parity, 4 legs incl. unlimited | Hybrid | `... -k "coop_status_limit_matches_gate"` | A |
| G-17 | Naive-UTC range bounds | Hybrid | `... -k "coop_consumption_naive_tz_bounds"` | A |
| G-18 | Expiry never negative; stamping; reversed-lapsed leg; NULL-stamp control | Hybrid | `... -k "coop_expiry_never_negative"` | **B — F5-2: add a positive leg proving the sweep writes exactly one `-N` EXPIRE row and is idempotent** |
| NEW-1 | The FIFO draw uses the blocking lock, not try-and-skip | Fully-Automated | `grep -n "pg_try_advisory_lock" apps/api/services/identity_coop.py` must not match the draw path | B |
| K-1 | Clawback/debt semantics under lot-symmetric stamping | — | — | D (backlog note, `coop-credit-reversal-semantics_NOTE_16-08-26.md`) |
| K-2 | Multi-process concurrency on the H2 enqueue→sweep window | — | — | D (inherited, constraint e) |
| K-3 | Any live flag-on gate | — | — | D (blocked by constraint d — `coop_terms_version` legal re-pin) |
| K-4 | Orphan SPEND surviving a concurrent site delete | — | — | D — **PRE-FLAG-FLIP BLOCKER** (S-17b / C3-7) |

Legacy line form:
- REVERSE primitive: [Hybrid: `pytest tests/ -m integration -k "coop_reverse_credit"` + PG :5433 serialized]
- Concurrency/lock shape: [Hybrid: `-k "coop_concurrent_increment_no_double_draw"`] — **currently non-discriminating (F5-1)**
- Failure posture: [Hybrid: `-k "coop_spend_failure_swallowed"`] — leg (v) injection mechanism must change (C5-1)
- Expiry/stamping: [Hybrid: `-k "coop_expiry_never_negative"`] — **no leg proves the sweep writes a row (F5-2)**
- Lanes: [Fully-automated: `pytest tests/unit -q`] / [Hybrid: `pytest tests/ -m integration -q`]
- Resolver purity: [Fully-automated: `git diff HEAD --quiet --exit-code -- apps/api/services/identity_resolver.py`]
- Clawback semantics: [known-gap: documented — K-1]
- H2 concurrency: [known-gap: documented — K-2]
- Live flag-on: [known-gap: documented — K-3]
- Orphan SPEND: [known-gap: documented — K-4, pre-flag-flip blocker]

### Dimension findings

- Infra fit: CONCERN — sweep body/wrapper placement and the APScheduler pattern verified; advisory-lock accumulation across the sweep transaction is unspecified (C5-2).
- Test coverage: FAIL — two gates cannot fail the implementation they exist to forbid (F5-1, F5-2) and one leg names an impossible injection (C5-1).
- Breaking changes: PASS — the three billing signatures stay frozen; the 5-caller census re-verified live at `visitors.py:959/:969`, `resolution_tasks.py:120/:135`, `resolution_runner.py:161/:178`.
- Security surface: PASS — flags OFF, no new external surface, `logger.exception("coop_spend_failed", ...)` carries no PII.
- Section — savepoint posture (P2-D6/S-13b): PASS — shape, ordering and budget all verified against the shipped `graph_erasure.py:218-231` precedent.
- Section — stamping + sweep (P2-D5/S-10b/S-11): FAIL — F5-2.
- Section — concurrency (S-14/G-6): FAIL — F5-1.
- Section — scope reconciliation (Blast Radius/Touchpoints/B4): FAIL — F5-3.

### Open gaps

- K-1: known-gap: documented — clawback/debt semantics open by design; `backlog/coop-credit-reversal-semantics_NOTE_16-08-26.md`.
- K-2: known-gap: documented — multi-process concurrency on the H2 enqueue→sweep window (inherited, constraint e).
- K-3: known-gap: documented — no gate may require a live flag flip; `coop_terms_version` legal re-pin pending (`coop-terms-repin_RUNBOOK_16-08-26.md`).
- K-4: known-gap: documented — orphan SPEND on concurrent site delete; **pre-flag-flip blocker**, detectable by dangling `lot_id`.
- C5-2 (sweep lock accumulation) joins K-4 as a pre-flag-flip item.
- S-23 (unit-lane baseline) and S-25 (budget + citation sweep) remain EXECUTE-time obligations, unverifiable at PVL.

### What this coverage does NOT prove

- G-6 does **not** prove the FIFO draw uses a blocking lock rather than try-and-skip — the users-row lock from the counter `UPDATE` serializes same-user calls first, so both shapes conserve (F5-1). Until the direct-`spend_credits` leg lands, S-14 and Constraint 16 rest on code review alone.
- G-18 does **not** prove the expiry sweep ever writes a row; every leg passes on a sweep that writes nothing (F5-2). It proves only that the balance never goes negative.
- G-7 leg (v) as written does **not** guarantee a genuine transaction abort — a duplicate ledger insert cannot raise (C5-1); only the `SELECT 1/0` variant does.
- No gate exercises a real deployment flag flip (K-3), so flag-on behavior is unproven end to end.
- No gate covers the site-delete-vs-draw race (K-4) or multi-process sweep concurrency (K-2).
- The unit-lane baseline figure (2801 / 2) is remembered, not re-measured this pass (C5-11); G-11's expected count must be re-baselined at EXECUTE per S-23.
- `EXPLAIN` behavior at ≥100k rows (G-4) and the conditional migration round-trip (G-15) are unrun — both are EXECUTE-time.
- Nothing here proves behavior against production data; all flags are OFF and the phase is pre-flag-flip.

Gate: BLOCKED (3 unresolved FAILs: F5-1, F5-2, F5-3)
Accepted by: — (BLOCKED; no CONDITIONAL acceptance. Cycle 5 does not self-accept its own verdict.)

### Execute-agent instructions (carry forward after the next supplement cycle)

| # | Instruction | Trigger |
|---|---|---|
| E-1 | Re-derive `alembic heads` LIVE with `DATABASE_URL` pinned to `localhost:5433`; re-derive the untracked-file COUNT live, never hard-code it. **Cycle 5 observed head `a8c2f47e91b6` (single) and an EMPTY `git status --short apps/api/migrations/versions/` — already different from cycle 3's three-untracked reading. Treat this observation as stale too.** Record the live head, the live count and the `git status` output in the phase report. | S-20 / S-24 entry |
| E-2 | Every flag-flipping test uses the pytest `monkeypatch` fixture for the **whole function** — never bare `setattr` (inherited constraint b). | S-18 entry |
| E-3 | Use `.returning(User.monthly_identified_count)` with `.scalar_one_or_none()`; derive the threshold via `get_effective_plan` → `get_effective_limit`, identical to the read path. | S-13 entry |
| E-4 | **SAVEPOINT is mandatory, not optional.** Wrap the coop-draw block in `async with db.begin_nested():` inside the `try` — precedents `services/identity_coop.py:175`, `routers/sites.py:206`, and the anti-simplification comment at `services/graph_erasure.py:218-231`. Exactly ONE `commit()`, after the try. A bare `try/except` loses the counter and 500s the unwrapped caller at `routers/visitors.py:969`. | S-13b entry |
| E-5 | Normalize both `api_usage_logs` range bounds to naive UTC (`created_at` is a naive `DateTime`). | S-6 entry |
| E-6 | **Locate every edit target by unique symbol or string, never by the line numbers in this plan.** Do not rewrite the third "ACCRUE only" comment (contribution-event provenance — genuinely ACCRUE-only). | Any S-* entry |
| E-7 | **Compensating control for the sequential strategy:** before EXECUTE, the orchestrator spawns one independent adversarial verifier instructed to REFUTE this contract (default verdict REFUTED). External verifiers have found the top defect in 6 of 6 prior cycles; cycle 5 found 3 FAILs sequentially, which raises rather than lowers the prior that more remain. | Post-supplement, pre-EXECUTE |
| E-8 | Guard the `/billing/status` extension with `monthly_limit is not None` — unlimited plans return `None` and would raise. | S-15b entry |
| E-9 | Declare `pytestmark = pytest.mark.integration` at module level in BOTH new test files — the marker is not applied by directory. Without it, 13 gates exit 5. | Either new test file |
| E-10 | Add the `settings` import (and the coop-service import) to `apps/api/services/billing.py` — neither exists today — and confirm no circular import with `services/identity_coop.py`. | S-13 / S-15 entry |
| E-11 | **NEW (F5-1).** The advisory lock is redundant on the `increment_usage` path (the counter UPDATE's users-row lock already serializes same-user calls) but is REQUIRED for composition with `reverse_credit` and the sweep. Do not "simplify" it away, and do not use `pg_try_advisory_lock`. | S-14 entry |
| E-12 | **NEW (F5-2).** `remaining` in `expire_lapsed_lots` is the **window-BLIND** raw lot SUM, identical to S-2's `remaining_at_write_time`. The window-aware reading is always 0 for a lapsed lot and would make the sweep write nothing. | S-11 / B3 entry |
| E-13 | **NEW (F5-3).** `apps/api/models/identity_coop.py` IS in scope (S-1 + S-10c) despite the stale "READ ONLY" annotation in `## Touchpoints`. The `### Supplement Blast Radius` table is the single source of truth. | S-1 entry |
