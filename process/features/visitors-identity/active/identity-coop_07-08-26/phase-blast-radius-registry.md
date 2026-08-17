# Identity Co-op — Phase Blast Radius Registry

Program: `identity-coop_07-08-26`
Feature: `visitors-identity`
Created: 07-08-26

Append-only. One `## Phase N` section per phase. Never overwrite a prior agent's claim.
Valid `status` values: `BLOCKED-skipped` | `DONE` | `SUPERSEDED` | (no field).
Step-0 dependency blocks use the `Dependency-BLOCKED` form (distinct from PVL `BLOCKED-skipped`).

---

## Phase 1 — Ledger + contribution substrate

Claimed files:
- `apps/api/models/identity_coop.py` (CREATE)
- `apps/api/services/identity_coop.py` (CREATE)
- `apps/api/models/site.py` (MODIFY — add `contribution_enabled`)
- `apps/api/config.py` (MODIFY — `## Identity co-op (Phase 1)` settings block)
- `apps/api/services/identity_resolver.py` (MODIFY — ~2-line hook immediately after the `_upsert_beam_identity` call inside `_save_identified`)
- `apps/api/schemas/sites.py` (MODIFY)
- `apps/api/routers/sites.py` (MODIFY — acceptance-guarded flag flip)
- `apps/api/migrations/versions/` (CREATE — 2 migrations) — **path CORRECTED 07-08-26 (PVL supplement): was `apps/api/alembic/versions/`, which does not exist and is not scanned by Alembic (`apps/api/alembic.ini` → `script_location = %(here)s/migrations`)**
- `tests/unit/test_identity_coop.py` (CREATE)
- `tests/integration/test_identity_coop_contribution.py` (CREATE)

Cross-program overlap (outside this registry's scope, recorded):
- `identity_resolver.py` is also claimed by `identity-vocab-reconcile_07-08-26` (§3.2) and by
  `identity-program_03-08-26` Phase 1 (`_save_identified`, status PLANNED). Mitigation: hook is
  ~2 lines, described by call-graph position, never line number. Both upstream workstreams must
  clear before this phase's EXECUTE.

Depends on: vocab-reconcile PASS/descoped + SPEC A LIVE. **Both CLEARED 07-08-26** — vocab-reconcile
is `Gate: CONDITIONAL` user-accepted/executed/merged (intent satisfied, wording gap only), and SPEC A
is LIVE: EVL GREEN 14/14, migration `d1a6c4e93f27` round-tripped on a disposable Postgres, pushed to
`origin/main` + `origin/devjulley` at 0/0, deployed (prod `alembic_version = d1a6c4e93f27`).

status: DONE-entry-gate-cleared 07-08-26 — F1 conditions 1-4 verified; EXECUTE authorized

(Supersedes the prior `status: Dependency-BLOCKED — entry gate SPEC A not LIVE; files never
modified`, written when the entry gate was open and now factually stale. Files are still unmodified —
this status records routing authorization, not completed work. The Phase Program Pre-Routing Check
routes a `Dependency-BLOCKED` phase straight past EXECUTE to Phase N+1, which is why the stale line
had to be replaced before vc-execute-agent could be spawned.)

PVL supplement 07-08-26 (cycle 1): plan-fixable FAILs F2/F3 and CONCERNs C1/C2/C3/C5/C6/C8 are
settled in the phase plan (§PLAN Decisions D-A…D-E). Two of those decisions change this phase's
claim surface:
- **D-A** raises the `identity_resolver.py` diff budget from ≤ 6 to ≤ 12 lines and changes
  `_upsert_beam_identity`'s return type `None` → `bool`. Still the same file, same call-graph
  anchor, one production caller — the cross-program footprint stays confined to `_save_identified`
  and `_upsert_beam_identity`.
- **D-E** adds a partial unique index `uq_coop_accrued_site_email` to the Phase 1 migration. Schema
  addition only, inside already-claimed files.
Dependency + re-entry conditions: `process/features/visitors-identity/backlog/identity-coop-entry-gate-spec-a-live_NOTE_07-08-26.md`

---

## Phase 2 — Consumption aggregation + spend

Claimed files:
- `apps/api/services/identity_coop.py` (MODIFY — created in Phase 1; sequential, no concurrent edit)
- `apps/api/services/billing.py` (MODIFY — `monthly_limit` extension)
- `apps/api/tasks/` (MODIFY/CREATE — expiry sweep registration)
- `apps/api/config.py` (MODIFY — sweep cadence setting; same block as Phase 1, appended)
- `apps/api/migrations/versions/` (CREATE — conditional index migration only) — **path CORRECTED 07-08-26 (PVL supplement), same reason as Phase 1**
- `tests/unit/test_identity_coop_ledger.py` (CREATE)
- `tests/integration/test_identity_coop_spend.py` (CREATE)

Explicitly NOT claimed:
- `apps/api/services/identity_resolver.py` — empty diff is a Phase 2 exit gate
- `apps/api/models/identity_coop.py` — schema frozen after Phase 1

Depends on: Phase 1 exit gate.

Inherited constraint from Phase 1's D-D (recorded 07-08-26; schema freezes after Phase 1):
`identity_credit_ledger` is `site_id`-scoped with **no `user_id` column**. Phase 2's spend gate MUST
aggregate across a user's sites by joining `identity_credit_ledger.site_id → sites.site_id →
sites.user_id` before applying the balance at `billing.check_usage_allowed(db, user_id)`
(`services/billing.py:94`). Phase 2 MUST NOT add a `user_id` column and MUST NOT add a per-site
monthly gate.

---

## Phase 3 — Contributor surface + opt-in UX

Claimed files:
- `apps/api/routers/identity_coop.py` (CREATE)
- `apps/api/schemas/identity_coop.py` (CREATE)
- `apps/api/services/coop_terms.py` (CREATE)
- `apps/api/services/identity_coop.py` (MODIFY — read-only stats assembly)
- `apps/api/routers/sites.py` (MODIFY — terms-version exposure/validation; sequential after Phase 1)
- `apps/api/main.py` (MODIFY — router registration)
- `apps/web/src/app/dashboard/visitors/page.tsx` (MODIFY)
- `apps/web/src/lib/api-types.ts` (MODIFY)
- `apps/web/src/lib/api.ts` (MODIFY)
- `tests/integration/test_identity_coop_stats.py` (CREATE)
- `tests/unit/test_coop_terms.py` (CREATE)

Explicitly NOT claimed:
- `apps/api/services/identity_resolver.py` — empty diff is a Phase 3 exit gate
- `apps/api/services/billing.py` — frozen after Phase 2

Depends on: Phase 2 exit gate.

---

## Potential Blast Radius Conflicts

All three phases are STRICTLY SEQUENTIAL — no two phases run concurrently, so the shared files
below are handled by ordering, not by partitioning:

| Shared file | Phases | Resolution |
|---|---|---|
| `apps/api/services/identity_coop.py` | 1 (create), 2 (extend), 3 (extend) | Sequential — no concurrent edit possible |
| `apps/api/routers/sites.py` | 1 (flag guard), 3 (terms exposure) | Sequential — Phase 3 builds on Phase 1's guard |
| `apps/api/config.py` | 1 (settings block), 2 (sweep cadence) | Sequential — Phase 2 appends to the Phase 1 block |

Cross-PROGRAM conflict (the real risk): `apps/api/services/identity_resolver.py` is contested by
three programs. Only Phase 1 of this program touches it, with a ~2-line footprint. Hard gate: this
program's EXECUTE cannot begin until `identity-vocab-reconcile_07-08-26` reaches PASS/descope.

---

## Phase 1 — status update (16-08-26, append-only)

status: DONE — supplement S1–S7 shipped; evidence pack APPROVED by human reviewer 16-08-26.

Trail: EXECUTE + EVL green 07-08-26 → independent re-audit 16-08-26 (vc-tester 11/11 gates still
green; vc-code-reviewer adversarial found H1/H2/M2/M3/L1 outside the gate-fenced resolve path) →
human REJECT → `## Post-Audit Fix Supplement (16-08-26)` (PVL cycles 1-3, verdict CONDITIONAL
user-accepted) → EXECUTE 16-08-26 → independent EVL 16/16 green with 5 mutation-kill proofs →
human APPROVE.

Additional files touched by the supplement (beyond the original Phase 1 claim above):
- `apps/api/services/graph_erasure.py` (MODIFY — tombstone-at-enqueue inside `db.begin_nested()`)
- `apps/api/models/suppression.py` (MODIFY — docstring only, 2 falsified sentences replaced)
- `tests/unit/test_identity_coop_hook.py` (CREATE)
- `tests/unit/test_graph_erasure.py` (MODIFY — SG-15 savepoint gate)
- `tests/integration/test_identity_coop_contribution.py` (MODIFY — 9 new functions incl. SG-16)

Standing precondition carried into Phase 2 and beyond: `coop_terms_version` is a PLACEHOLDER
digest. Legal review + re-pin REQUIRED before `identity_coop_enabled` or any site's
`contribution_enabled` is flipped ON. Both flags remain OFF; production exposure is NONE.

Accepted known-gap: multi-process concurrency on the H2 enqueue→sweep window is not gated
(SG-6/SG-6b cover the sequential window; SG-16 closed the savepoint half on real Postgres).

---

## Phase 2 SPLIT into 2a + 2b (17-08-26, append-only)

Explicit user decision. The `## Phase 2 — Consumption aggregation + spend` claim above is
**SUPERSEDED** by the two claims below; it is retained unedited for the chain. Program is now
**4 phases: 1, 2a, 2b, 3**.

Reason: five PVL cycles + three adversarial rounds produced a stable design core, but every fix cycle
produced a NEW defect of one class — a gate that passes on the implementation it exists to forbid.
Root cause was phase size; the split is the fix.

### Phase 2a — Consumption aggregation + FIFO expiry
Plan: `phase-2-consumption-spend_PLAN_07-08-26.md` (retitled in place to Phase 2a)
Claims (10 files — amended in place 17-08-26 at EXECUTE per S-3; the former 8-file list predated
the supplement cycles that added the seeding helper and the mandatory E2 migration):
- `apps/api/services/identity_coop.py` — `consumption_count`, `contribution_count`, `spendable_lots`, `expire_lapsed_lots`, S-4 clamp
- `apps/api/services/coop_expiry_sweep.py` (NEW) — sweep body
- `apps/api/jobs/scheduler.py` — wrapper + one `add_job`
- `apps/api/config.py` — `coop_expiry_sweep_interval_minutes`
- `apps/api/models/identity_coop.py` — S-10c stamping prose **+ the E2 `uq_coop_ledger_expire_per_lot` index mirror in `__table_args__`** (~12 lines). **"Prose only" is RETRACTED** — the integration schema is built by `create_all`, never alembic, so without the mirror G-21 fails outright. **No `LEDGER_ENTRY_TYPES` change** — REVERSE is dropped to K-1, so no vocabulary edit ships.
- `tests/integration/test_identity_coop_ledger.py` (NEW) — incl. the module-local `seed_api_usage_logs` bulk helper for G-4
- `apps/api/migrations/versions/b7e4d21a9c58_add_coop_expire_unique.py` (NEW, **MANDATORY** — E2). E1 was CONDITIONAL and **did not fire**: G-4's EXPLAIN showed a Bitmap Index Scan on `api_usage_logs`, no seq scan, so no covering index was added and no second migration file exists.
- this registry
- `process/general-plans/active/capacity-hardening_25-07-26/transaction-pooler-advisory-lock-audit_NOTE_25-07-26.md` (S-27, one row)

status: DONE (EXECUTE 17-08-26 — all gates green)
Explicitly NOT claimed by 2a: `apps/api/services/billing.py`, `apps/api/routers/billing.py` (empty
diff on both is a 2a exit gate), `apps/api/services/identity_resolver.py`.

**Freeze-scope reading (S-3, recorded):** the Phase 1 schema freeze covers D-D scoping (no `user_id`
column, no per-site gate). It does not cover the application-level `LEDGER_ENTRY_TYPES` tuple — but
**Phase 2a does not extend it anyway**, so the exception is moot until K-1 is picked up.

### Phase 2b — Spend wiring
Plan: `phase-2b-spend-wiring_PLAN_16-08-26.md` — ⏳ PLANNED, **entry-gated on Phase 2a LIVE**
Claims (5 files):
- `apps/api/services/identity_coop.py` — `spend_credits` only (**sequential after 2a**, same file, disjoint functions)
- `apps/api/services/billing.py` — read gate + SPEND write on a savepoint
- `apps/api/routers/billing.py` — `monthly_limit` extension + unlimited guard
- `tests/integration/test_identity_coop_spend.py` (NEW)
- this registry
Carries the D-D user-pooling constraint (registry lines 77-82) — the user-level view is a JOIN at
read/draw time, never a column.

**Overlap with 2a:** `apps/api/services/identity_coop.py` and this registry only. Resolution:
**sequential, not parallel** — 2b cannot start until 2a is LIVE, so no concurrent edit is possible.

### Dropped from Phase 2 entirely
All REVERSE artefacts (P2-D1, S-1, S-2/S-2b/S-2c, G-1/G-2, Constraint 12b's composition clause) moved
to `process/features/visitors-identity/backlog/coop-credit-reversal-semantics_NOTE_16-08-26.md` (K-1).
No phase in this program claims `LEDGER_ENTRY_TYPES` any more.
