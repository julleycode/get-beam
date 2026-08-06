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

Depends on: vocab-reconcile PASS/descoped + SPEC A LIVE.

status: Dependency-BLOCKED — entry gate SPEC A not LIVE; files never modified

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
