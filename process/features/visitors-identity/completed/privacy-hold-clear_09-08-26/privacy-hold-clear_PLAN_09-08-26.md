---
name: privacy-hold-clear_PLAN
description: "SIMPLE PLAN — Option D: privacy-hold UX + explicit site-owner Clear for sticky do_not_resolve. API endpoint + Visitors dashboard banner/button/confirm. No migration, no bypass, no un-suppress."
date: 09-08-26
metadata:
  node_type: plan
  type: plan
  complexity: SIMPLE
  feature: visitors-identity
  phase: UPDATE-PROCESS
  status: COMPLETE_WITH_GAPS
  approach: "D (privacy-hold UX + explicit confirmed owner Clear)"
  spec: process/features/visitors-identity/completed/privacy-hold-clear_09-08-26/privacy-hold-clear_SPEC_09-08-26.md
---

# PLAN — Privacy-Hold UX + Explicit Site-Owner Clear (SIMPLE)

**Date**: 09-08-26
**Status**: ✅ COMPLETE_WITH_GAPS — EXECUTE + EVL PASS; archived 10-08-26 (UPDATE PROCESS)
**Complexity**: SIMPLE
**Feature**: visitors-identity
**Context:** `process/context/all-context.md`, `process/context/tests/all-tests.md`, SPEC `privacy-hold-clear_SPEC_09-08-26.md`

## What's Functional Now

- `POST /api/v1/visitors/{site_id}/{visitor_id}/clear-privacy-hold` — site-scoped clear of sticky `do_not_resolve` (audited `privacy_hold_cleared`, no PII, no migration).
- `VisitorOut.do_not_resolve: bool = False` (additive; `VisitorDetailOut` inherits).
- Visitors dashboard: "Privacy hold" state + confirm "Clear privacy hold" (does-not-unsuppress copy).
- Web client: `api.clearPrivacyHold` + `Visitor.do_not_resolve?` in `api-types.ts`.
- Backend Fully-Automated gates green: `tests/integration/test_privacy_hold_clear.py` 8/8; sticky/pixel regressions green.

## Known Gaps (Resolved via Backlog)

- AC-1/2/3/6 Hybrid e2e (Clerk auth-harness): `process/features/visitors-identity/backlog/privacy-hold-clear-e2e-auth-harness_NOTE_09-08-26.md`
- AC-13 legal-adequacy (counsel): `process/features/visitors-identity/backlog/privacy-copy-counsel-review_NOTE_07-08-26.md`

## Phase Loop Progress

- [x] 1. RESEARCH
- [x] 2. SPEC
- [x] 3. INNOVATE
- [x] 4. PLAN
- [x] 5. VALIDATE (Gate: CONDITIONAL — Known-Gaps accepted)
- [x] 6. EXECUTE + EVL
- [x] 7. UPDATE PROCESS — archived; context updated; commit checkpoint deferred (dirty worktree; user did not request commit)

## Plan Deviations (EXECUTE)

1. Web `do_not_resolve?` type lives in `apps/web/src/lib/api-types.ts` (not `api.ts`); client method in `api.ts`.
2. Reused `StatusBadge status="vpn_filtered"` for Privacy-hold label styling.
3. Extra integration test `test_integration_clear_unknown_visitor_404`.
4. e2e legs `test.skip`-guarded on `E2E_PRIVACY_HOLD_VISITOR`.

## Lessons Learned

- Sticky `do_not_resolve` clear is a single-boolean write; never invent Identify bypass or un-suppress.
- Clerk Playwright auth-harness remains the recurring blocker for Visitors dashboard Hybrid e2e — register skip-guards + backlog stubs, do not mark terminal-green.

**TL;DR:** Add one site-scoped API endpoint that flips a single visitor's sticky
`do_not_resolve` back to `False` (audited via structlog, no PII, no migration), expose
`do_not_resolve` on the list-row schema, and add a "Privacy hold" state + confirmed "Clear
privacy hold" button to the Visitors dashboard. Identify still runs through the existing
`/resolve` gate — no bypass. Aggregator stickiness, suppression list, and the pixel are untouched.

## Overview

Today a visitor with a privacy signal (GPC/DNT/suppression cascade) gets a **sticky**
`Visitor.do_not_resolve = True` set by the aggregator (`BOOL_OR` + sticky `OR` upsert). There is no
in-product way to lift it — the only path is a manual SQL `UPDATE` (this happened to a real
Brave/GPC visitor). Option D gives the site owner a deliberate, confirmed, single-row Clear with an
audit trail, without auto-clearing, without an Identify bypass, and without touching suppression.

## Goals

- G1 — Site owner can clear one visitor's privacy hold for one site from the dashboard, confirmed.
- G2 — The hold reads as a **privacy/policy block** (not a usage limit) in the UI.
- G3 — Every clear is audited (actor/site/visitor/timestamp, no PII).
- G4 — Zero change to: aggregator stickiness, suppression enforcement, resolve gates, the pixel, DB schema.

## Scope

**In scope:** one new API endpoint in `apps/api/routers/visitors.py`; one additive field on
`VisitorOut`; Visitors dashboard banner/button/confirm-dialog in
`apps/web/src/app/dashboard/visitors/page.tsx`; one new API client method + web type field in
`apps/web/src/lib/api.ts`; backend integration tests; web e2e leg.

**Out of scope (locked, do NOT build):** auto-clear (Approach A), Identify bypass / force-resolve
(Approach B), dual GPC/manual fields (Approach C), removing suppression-list rows, bulk/site-wide
clear, cross-tenant clear, any pixel/tracker change, any change to `BOOL_OR`/sticky-`OR` aggregation,
any new audit table or DB migration.

## Acceptance Criteria

These are the SPEC's AC-1…AC-13 (testable outcomes), each bound to its proving gate in
§Verification Evidence. `proven by:` names the scenario; `strategy:` is one of
Fully-Automated / Hybrid / Agent-Probe (Known-Gap is a residual, never a strategy).

- **AC-1** Held visitor reads as a privacy hold, not a limit. proven by: `V-e2e-banner`. strategy: Hybrid.
- **AC-2** Clear control appears only for held rows. proven by: `V-e2e-button-visibility`. strategy: Hybrid.
- **AC-3** Clearing requires explicit confirmation (cancel = no-op). proven by: `V-e2e-confirm-dialog`. strategy: Hybrid.
- **AC-4** Confirm flips `do_not_resolve=false` for exactly one (site,visitor). proven by: `V-int-scoped-flip`. strategy: Fully-Automated.
- **AC-5** Only an authorized site member may clear; foreign → 404, no write. proven by: `V-int-cross-tenant-404`. strategy: Fully-Automated.
- **AC-6** After clear, UI returns to normal (Identify available). proven by: `V-e2e-post-clear-ui`. strategy: Hybrid.
- **AC-7** Identify after clear uses existing resolve path; no bypass. proven by: `V-int-no-bypass`. strategy: Fully-Automated.
- **AC-8** Aggregator stickiness unchanged; re-optout re-sticks. proven by: `V-agg-sticky` + `V-int-reoptout-resticks`. strategy: Fully-Automated.
- **AC-9** Clear is audited (actor/site/visitor/timestamp, no PII). proven by: `V-int-audit`. strategy: Fully-Automated.
- **AC-10** Clear never touches suppression list. proven by: `V-int-does-not-unsuppress`. strategy: Fully-Automated.
- **AC-11** Clear is safe/idempotent on a non-held row. proven by: `V-int-idempotent`. strategy: Fully-Automated.
- **AC-12** Pixel untouched. proven by: `V-pixel-regression`. strategy: Fully-Automated.
- **AC-13** Copy communicates deliberate/site-only/non-un-suppressing nature. proven by: `V-e2e-copy-presence` (presence) + counsel review. strategy: Agent-Probe (legal-adequacy half is a Known-Gap residual → AC-13 stays CONDITIONAL + backlog stub).

## Decision Record (locked upstream — do not re-open)

- **Approach:** D (privacy-hold UX + explicit confirmed owner Clear). Per orchestrator Decision Summary.
- **Audit mechanism = structlog event, NOT a table.** Decided with codebase evidence:
  - `structlog` is the repo-wide audit pattern (Guardrail #3: log keys/ids only, never PII); other
    per-visitor writes already emit truncated-id structlog events (e.g. `osint_scan_job_done`).
  - `ApiUsageLog` (`api_usage_logs`) is a **billable external-API cost ledger** (`category ∈
    identity|enrichment|email|ai|osint`, `cost_usd`) — a clear is not a billable API call; writing
    there would pollute cost analytics. **Rejected.**
  - `RequestLog` (`request_logs`) is a middleware **debug artifact** for dropped/flagged requests,
    admin-gated, structurally not product/audit data. **Rejected.**
  - Net: emit `privacy_hold_cleared` structlog event; **no new table, no migration** — satisfies
    SPEC AC-9 "reuse existing pattern … avoid a bespoke table" and the schema-migration-averse
    constraint. Durable queryable audit, if ever needed, is a backlog item (see Test Infra / backlog note).
- **List-row visibility:** expose `do_not_resolve` on `VisitorOut` (additive Pydantic field,
  `from_attributes=True` reads the existing ORM column) so the list page can render the hold state
  and the Clear control. No migration — the `Visitor.do_not_resolve` column already exists.

## Touchpoints

| # | File | Change |
|---|---|---|
| T1 | `apps/api/routers/visitors.py` | NEW endpoint `POST /{site_id}/{visitor_id}/clear-privacy-hold` — mirrors `set_internal_override` shape: `_verify_site_access` → `human_only_visitor_filter()` fetch → 404 if missing → set `do_not_resolve=False` → `structlog` audit event → `db.commit()` → JSON response. |
| T2 | `apps/api/schemas/visitors.py` | Add `do_not_resolve: bool = False` to `VisitorOut` (additive; `VisitorDetailOut` inherits it). |
| T3 | `apps/web/src/lib/api.ts` | Add `clearPrivacyHold(siteId, visitorId)` client method (POST, typed response). Add `do_not_resolve?: boolean` to the web `Visitor`/`VisitorOut` TS type used by the list. |
| T4 | `apps/web/src/app/dashboard/visitors/page.tsx` | In `renderIdentity`: when `v.do_not_resolve` (anonymous + held), render a distinct "Privacy hold" state + "Clear privacy hold" button gated by a confirm dialog; add `clearMut` mutation that calls `api.clearPrivacyHold` and on success invalidates the `["visitors"]` query so the row re-renders with Identify. Add explanatory copy (US-1) + confirm-dialog copy (US-3/AC-13). |
| T5 | `tests/integration/test_privacy_hold_clear.py` | NEW — endpoint behavior + auth + no-bypass + scoped flip + idempotent + does-not-unsuppress + re-optout re-stick + audit event. |
| T6 | `apps/web/e2e/visitors.spec.ts` | EXTEND — held-row banner render, button visibility (held vs not-held), confirm/cancel, post-clear UI, copy-presence. (Hybrid legs; Playwright-Clerk auth-harness is a known residual — see Test Infra Notes.) |

**Untouched (assert-unchanged, never edit):** `apps/api/services/visitor_aggregator.py` (sticky
`BOOL_OR`/`OR`), `apps/api/services/suppression.py` + `IdentityResolver` suppression gate,
`resolve_one_visitor`/`resolve_site_visitors` gates, `apps/pixel/src/tracker.js`,
`tests/integration/test_optout_flow.py`.

## Public Contracts

**New endpoint**
```
POST /api/v1/visitors/{site_id}/{visitor_id}/clear-privacy-hold
Auth: Bearer (get_current_user) + _verify_site_access(db, site_id, user)  # same as /resolve
Body: none
200 → { "visitor_id": str, "do_not_resolve": false, "cleared": bool }   # cleared=false when already not held (idempotent no-op)
404 → visitor missing OR site not owned by caller (no 403 — multi-tenancy no-leak convention)
```
- The endpoint ONLY writes `Visitor.do_not_resolve = False` for the matched `(site_id, visitor_id)`
  row. It writes nothing else — no suppression edit, no identity write, no aggregate recompute.
- It provides **no** resolve/identify capability. Identify remains the existing `/resolve` endpoint,
  whose `if visitor.do_not_resolve:` short-circuit (visitors.py) is unchanged.

**Schema additive field:** `VisitorOut.do_not_resolve: bool = False` — read-only projection of the
ORM column; no consumer removes/renames existing fields.

**Web client:** `clearPrivacyHold(siteId, visitorId): Promise<{ visitor_id: string; do_not_resolve: false; cleared: boolean }>`.

## Blast Radius

- **DB:** none (no migration, no new column, no new table). Single-row `UPDATE visitors SET
  do_not_resolve=false` scoped by PK `(site_id, visitor_id)`.
- **API:** one additive route; one additive response field. No existing route signature changes.
- **Web:** one additive client method; one additive branch in `renderIdentity`; one additive TS
  field. No change to existing Identify/Enrich flows.
- **Cross-tenant:** none — `_verify_site_access` scopes to `Site.user_id == user.id`; the write is
  keyed by the caller's `site_id`. `beam_identity_graph` is never touched.
- **Aggregator/suppression/pixel:** none.

## Security (auth surface — STRIDE quick scan)

- **Spoofing/Elevation:** endpoint reuses `get_current_user` + `_verify_site_access` — identical
  gate to `/resolve` and `set_internal_override`. A caller without the site gets 404, not 403
  (no id-existence leak). No new auth surface invented.
- **Tampering:** write is bounded to a single boolean on a PK-matched row; no user-supplied field
  is written. No mass-assignment (no request body).
- **Repudiation:** mitigated by the `privacy_hold_cleared` structlog event (actor `user_id`, `site_id`,
  truncated `visitor_id`, timestamp) — no PII.
- **Info disclosure:** response echoes only `visitor_id` + booleans (no PII). 404 path leaks nothing.
- **DoS:** single indexed UPDATE; negligible. No new external call.
- **Compliance ("no silent reverse"):** clear is explicit + confirmed + audited; it does NOT
  un-suppress and does NOT auto-fire — consistent with `privacy.py::delete_suppression`'s stance.

## Data Flow

1. Owner opens Visitors dashboard → list rows now carry `do_not_resolve` (T2).
2. For a held anonymous row, `renderIdentity` shows "Privacy hold" + "Clear privacy hold" (T4).
3. Click → confirm dialog (deliberate / this-site-only / does-NOT-unsuppress copy). Cancel = no-op.
4. Confirm → `POST .../clear-privacy-hold` (T1) → `_verify_site_access` → fetch row (404 if
   missing/foreign) → `do_not_resolve=False` → structlog audit → commit.
5. Web `onSuccess` invalidates `["visitors"]` → row refetches → `do_not_resolve=false` → Identify
   control returns.
6. Owner clicks Identify → existing `/resolve` waterfall (no bypass). If the email is on the
   suppression list, `IdentityResolver` still refuses (gate unchanged).
7. Later opt-out event → aggregator may re-set `do_not_resolve=True` (expected; documented in copy).

## Failure Modes

- **Visitor already not held** → idempotent no-op, `cleared:false`, 200 (AC-11).
- **Foreign/unknown id** → 404, no write (AC-5).
- **Concurrent re-optout during clear** → last-writer-wins on a boolean; acceptable — a subsequent
  aggregator run re-sets sticky, which is the documented expected behavior (AC-8).
- **structlog sink failure** → audit is best-effort (matches existing logging posture); the DB write
  is the source of truth. (If durable audit is later required → backlog.)

## Implementation Checklist

1. ✅ `apps/api/schemas/visitors.py` — add `do_not_resolve: bool = False` to `VisitorOut` (place near
   `internal_override`; keep `model_config from_attributes=True`). [T2]
2. ✅ `apps/api/routers/visitors.py` — add `POST /{site_id}/{visitor_id}/clear-privacy-hold` endpoint
   modeled on `set_internal_override` (visitors.py:1013): `await _verify_site_access(...)`; select
   `Visitor` with `human_only_visitor_filter()`; `raise HTTPException(404, "Visitor not found")` if
   missing; capture `was_held = bool(visitor.do_not_resolve)`; set `visitor.do_not_resolve = False`;
   `await db.commit()`. [T1]
3. ✅ `apps/api/routers/visitors.py` — emit audit: `logger.info("privacy_hold_cleared",
   site_id=site_id, visitor_id=visitor_id[:8], user_id=str(user.id), was_held=was_held)` (no PII,
   truncated id per repo pattern). Return `{"visitor_id": visitor_id, "do_not_resolve": False,
   "cleared": was_held}`. [T1]
4. ✅ `apps/web/src/lib/api.ts` — add `clearPrivacyHold(siteId, visitorId)` method (POST, typed
   response); `do_not_resolve?: boolean` added on web `Visitor` in `api-types.ts` (deviation: type
   not in `api.ts`). [T3]
5. ✅ `apps/web/src/app/dashboard/visitors/page.tsx` — add `clearMut = useMutation` calling
   `api.clearPrivacyHold(siteId, id)`, `onSuccess` → `queryClient.invalidateQueries({ queryKey:
   ["visitors"] })` + clear notice; `onSettled` → `setActioningId(null)`. [T4]
6. ✅ `apps/web/src/app/dashboard/visitors/page.tsx` — in `renderIdentity`, BEFORE the default Identify
   button, add: `if (v.identity_status === "anonymous" && v.do_not_resolve) { return <PrivacyHold
   … /> }` rendering a distinct "Privacy hold" label + explanatory copy (US-1: policy block, not a
   usage cap) + a "Clear privacy hold" button that opens a confirm dialog. [T4]
7. ✅ Confirm dialog — reuse the existing shadcn dialog/AlertDialog primitive already used in the web
   app (scout `components/ui` for `alert-dialog`/`dialog`; if only `Dialog` exists, use it). Copy MUST
   state: deliberate action, this visitor + this site only, does NOT remove from any suppression
   list (AC-3, AC-13). Cancel closes with no write; Confirm fires `clearMut`. [T4]
8. ✅ `tests/integration/test_privacy_hold_clear.py` — NEW file, mirror the fixture pattern of
   `test_visitor_resolve_endpoint.py` (`_signup` → token, `_verify_site_access` via real Site owned
   by the user, `monkeypatch` IdentityResolver/Enricher where resolve is exercised). Implement the
   scenarios in Verification Evidence rows V-int-*. [T5]
9. ✅ `apps/web/e2e/visitors.spec.ts` — EXTEND with the held-row legs (V-e2e-*). Follow the canonical
   Playwright rules in `process/context/tests/all-tests.md` (auto-retry `toBeVisible`, `.first()`
   with `.or()`, specific selectors, read the component source first). [T6] — CONDITIONAL skip-guard.
10. ✅ Run gates (see Verification Evidence) and confirm `test_optout_flow.py` sticky suite + pixel
    size/capture suite are still GREEN unchanged (AC-8, AC-12). EVL independent PASS 10-08-26.

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `V-int-scoped-flip` (`integration_clear_hold_scoped_flip`): held row → POST clear → asserts that one row's `do_not_resolve` flips to False and a second held visitor is untouched | Fully-Automated | AC-4 |
| `V-int-cross-tenant-404` (`integration_clear_hold_cross_tenant_404`): second user/site calls clear on first site's visitor → 404, no write | Fully-Automated | AC-5 |
| `V-int-no-bypass` (`integration_no_hold_bypass`): still-held row → `/resolve` returns `privacy_opt_out`; after clear → `/resolve` reaches waterfall (`_FakeResolver` identifies) | Fully-Automated | AC-7 |
| `V-int-does-not-unsuppress` (`integration_clear_does_not_unsuppress`): visitor email on `do_not_process` suppression list; after clear, resolve still refuses (suppression gate) | Fully-Automated | AC-10 |
| `V-int-idempotent` (`integration_clear_idempotent_noop`): clear a not-held visitor → 200, `cleared:false`, no error | Fully-Automated | AC-11 |
| `V-int-reoptout-resticks` (`integration_clear_then_reoptout_resticks`): clear → add opt-out event → re-aggregate → `do_not_resolve` back to True | Fully-Automated | AC-8 |
| `V-int-audit` (`clear-hold-audit-record`): assert `privacy_hold_cleared` structlog event fields (site/visitor-truncated/user/was_held) via `structlog.testing.capture_logs`; assert NO PII (no email/raw) | Fully-Automated | AC-9 |
| `V-agg-sticky` (existing `test_optout_flow.py` `TestAggregatorSetsOptout`/sticky) stays GREEN unchanged | Fully-Automated | AC-8 |
| `V-e2e-banner` (`visitors-detail-privacy-hold-banner`): held row renders "Privacy hold" copy = policy block, not limit | Hybrid | AC-1 |
| `V-e2e-button-visibility` (`clear-hold-button-visibility`): Clear button shown for held rows, absent for not-held | Hybrid (e2e; automation blocked by Clerk auth-harness → CONDITIONAL, backlog stub) | AC-2 |
| `V-e2e-confirm-dialog` (`clear-hold-confirm-dialog`): confirm path writes; cancel path no-op | Hybrid | AC-3 |
| `V-e2e-post-clear-ui` (`clear-hold-post-clear-ui`): after clear, hold gone + Identify available | Hybrid | AC-6 |
| `V-e2e-copy-presence` (`clear-hold-copy-presence`): confirm copy asserts deliberate/this-site-only/does-not-unsuppress markers | Agent-Probe | AC-13 (presence half) |
| `V-pixel-regression` (existing `test_pixel*` size/capture) stays GREEN unchanged | Fully-Automated | AC-12 |
| Counsel legal-adequacy of copy | Known-Gap (residual, NOT a proving strategy) → keep AC-13 gate CONDITIONAL + backlog `privacy-copy-counsel-review_NOTE_07-08-26.md` | AC-13 (judgment half) |

**Vacuous-green control:** AC-13's legal-adequacy half is a Known-Gap residual (counsel review) — it
is recorded as a backlog dependency and AC-13 stays CONDITIONAL; the automatable presence half is
proven by `V-e2e-copy-presence`. No developed behavior is declared PASS on a Known-Gap alone. The
web e2e legs (AC-1/2/3/6) whose full automation is blocked by the known Clerk Playwright
auth-harness gap stay CONDITIONAL with a backlog stub rather than being marked terminal-green.

## Test Infra Improvement Notes

- The web app has **no React component-test runner** (only Playwright e2e). SPEC AC-2 ("web component
  test") therefore lands as a Playwright e2e leg; a true component test would need a vitest/RTL
  harness (not in scope here — note for future).
- **Playwright + Clerk auth-harness** is a recurring known gap across this repo (billing/exports,
  ads-audiences). The held-row e2e legs depend on an authenticated dashboard session; if the shared
  auth harness is unavailable at EXECUTE, these legs are CONDITIONAL residuals — register a backlog
  stub, do not mark them terminal-green.
- **Durable/queryable audit** deliberately deferred: this plan audits via structlog (no table). If a
  queryable clear-audit is later required, that is a new backlog item (would need a migration —
  intentionally out of scope for Option D phase 1).

## Dependencies

- Non-blocking: privacy-counsel copy review — existing backlog
  `process/features/visitors-identity/backlog/privacy-copy-counsel-review_NOTE_07-08-26.md`. Ship
  honest placeholder copy now (strictly better than the current dead end); does not block PLAN/EXECUTE.
- Integration tests require local Postgres+Redis (`docker compose -f infra/docker-compose.yml up -d
  postgres redis`), per `process/context/tests/all-tests.md`.
- ⚠️ Alembic/DB safety: this plan adds NO migration, so the "bare alembic hits Supabase prod" hazard
  is not triggered. If any DB command is run, pin `DATABASE_URL=localhost:5433` (see all-context).

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Owner clears, later GPC event re-sticks the flag (perceived as a bug) | Med | Documented as expected in UI copy (US-3/flow step 7); AC-8 test asserts re-stick is correct behavior. |
| Copy legally inadequate | Med | Counsel-review backlog dep; AC-13 CONDITIONAL until reviewed. |
| Accidentally treating clear as un-suppress | Low | AC-10 integration test; endpoint writes only the one boolean. |
| Web e2e flakiness / auth harness | Med | Follow canonical Playwright rules; CONDITIONAL + backlog stub if auth harness unavailable. |

## Rollback

- Pure-additive: revert the endpoint (T1), the schema field (T2), and the web changes (T3/T4). No
  migration to reverse, no data backfill. Existing behavior (dead-end privacy hold) returns exactly.

## Phase Completion Rules

SIMPLE single-phase plan. "Done" = ALL of:
1. Endpoint (T1) + schema field (T2) merged; `test_privacy_hold_clear.py` V-int-* gates GREEN.
2. Web client + UI + confirm dialog (T3/T4) merged; e2e legs GREEN or CONDITIONAL with a registered backlog stub (Playwright/Clerk auth-harness residual).
3. Regression suites unchanged-green: `test_optout_flow.py` sticky (AC-8) and `test_pixel*` size/capture (AC-12).
4. No developed behavior left terminal-green on a Known-Gap alone (AC-13 legal-adequacy half stays CONDITIONAL + backlog).
5. No migration introduced; aggregator/suppression/resolve-gates/pixel unchanged (diff-verified).

## Validate Contract

Status: CONDITIONAL
Date: 09-08-26
date: 2026-08-09
generated-by: outer-pvl

Parallel strategy: sequential
Rationale: Signal count 1/7 (single SIMPLE plan, one dominant signal — additive, one feature area, ~6 touchpoints). No independent-file fan-out warranted; VALIDATE fan-out ran as a single-agent synthesis.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-4 | Confirm flips `do_not_resolve=false` for exactly one (site,visitor) | Fully-Automated | `test_integration_clear_hold_scoped_flip` (`tests/integration/test_privacy_hold_clear.py`) | B |
| AC-5 | Only authorized site member may clear; foreign → 404, no write | Fully-Automated | `test_integration_clear_hold_cross_tenant_404` | B |
| AC-7 | Identify after clear uses existing resolve path; still-held row refuses | Fully-Automated | `test_integration_no_hold_bypass` | B |
| AC-8 | Aggregator stickiness unchanged; re-optout re-sticks | Fully-Automated | `test_integration_clear_then_reoptout_resticks` + existing `test_optout_flow.py` sticky suite | B (new) + A (regression) |
| AC-9 | Clear is audited (actor/site/visitor/timestamp, no PII) | Fully-Automated | `test_clear_hold_audit_record` via `structlog.testing.capture_logs` | B |
| AC-10 | Clear never touches suppression list | Fully-Automated | `test_integration_clear_does_not_unsuppress` | B |
| AC-11 | Clear is safe/idempotent on a non-held row | Fully-Automated | `test_integration_clear_idempotent_noop` | B |
| AC-12 | Pixel untouched | Fully-Automated | existing `test_pixel*` size/capture suite (regression) | A |
| AC-1 | Held visitor reads as privacy hold, not a limit | Hybrid | `visitors-detail-privacy-hold-banner` (Playwright e2e) | C (blocked on Clerk auth-harness → backlog stub) |
| AC-2 | Clear control appears only for held rows | Hybrid | `clear-hold-button-visibility` (Playwright e2e) | C (blocked on Clerk auth-harness → backlog stub) |
| AC-3 | Clearing requires explicit confirmation (cancel = no-op) | Hybrid | `clear-hold-confirm-dialog` (Playwright e2e) | C (blocked on Clerk auth-harness → backlog stub) |
| AC-6 | After clear, UI returns to normal (Identify available) | Hybrid | `clear-hold-post-clear-ui` (Playwright e2e) | C (blocked on Clerk auth-harness → backlog stub) |
| AC-13 (presence) | Confirm copy carries deliberate/site-only/no-un-suppress markers | Agent-Probe | `clear-hold-copy-presence` (Playwright e2e marker check) | C (presence automatable; legal half is D) |
| AC-13 (judgment) | Confirm copy is legally adequate | (residual, not a proving strategy) | counsel review | D — backlog `privacy-copy-counsel-review_NOTE_07-08-26.md` |

gap-resolution legend: A — proven now (existing regression) · B — gate added by this plan's checklist · C — deferred to named later phase/environment (Clerk auth-harness) · D — backlog test-building stub / residual.

C-4 reconciliation: `strategy` column carries only the 3 proving strategies (Fully-Automated / Hybrid / Agent-Probe). AC-13's legal-adequacy half is a named residual (gap-resolution D), never a strategy that proves a behavior.

Legacy line form (retained for existing consumers):
- Backend endpoint behavior (AC-4/5/7/9/10/11): Fully-automated: `.venv/bin/python -m pytest tests/integration/test_privacy_hold_clear.py -q` (needs local PG+Redis, `DATABASE_URL=localhost:5433`)
- Aggregator sticky (AC-8): Fully-automated: `.venv/bin/python -m pytest tests/integration/test_optout_flow.py -q`
- Pixel (AC-12): Fully-automated: `.venv/bin/python -m pytest tests/unit/test_pixel.py tests/unit/test_pixel_fingerprint.py -q`
- UI states (AC-1/2/3/6): hybrid: `cd apps/web && npm run test:e2e` — precondition: Clerk Playwright auth-harness available; if absent → known-gap: documented, backlog stub
- Copy presence (AC-13): agent-probe: `clear-hold-copy-presence` marker assertion
- Copy legal adequacy (AC-13): known-gap: documented (counsel review, backlog)

Failing stubs (Fully-Automated rows added by this plan — TDD stubs for EXECUTE):
```python
# tests/integration/test_privacy_hold_clear.py
async def test_integration_clear_hold_scoped_flip():
    raise NotImplementedError("TDD stub AC-4: POST clear on a held row flips exactly that (site,visitor) do_not_resolve→False; a second held visitor is untouched")

async def test_integration_clear_hold_cross_tenant_404():
    raise NotImplementedError("TDD stub AC-5: second user/site calls clear on first site's visitor → 404, no write")

async def test_integration_no_hold_bypass():
    raise NotImplementedError("TDD stub AC-7: still-held row → /resolve returns privacy_opt_out; after clear → /resolve reaches waterfall")

async def test_integration_clear_does_not_unsuppress():
    raise NotImplementedError("TDD stub AC-10: suppressed email still refused by resolve after clear")

async def test_integration_clear_idempotent_noop():
    raise NotImplementedError("TDD stub AC-11: clear a not-held visitor → 200, cleared:false, no error")

async def test_integration_clear_then_reoptout_resticks():
    raise NotImplementedError("TDD stub AC-8: clear → add opt-out event → re-aggregate → do_not_resolve back to True")

async def test_clear_hold_audit_record():
    raise NotImplementedError("TDD stub AC-9: assert privacy_hold_cleared structlog event fields (site/visitor-truncated/user/was_held); assert NO PII")
```

Dimension findings:
- Infra fit: PASS — new `POST /{site_id}/{visitor_id}/clear-privacy-hold` mirrors the confirmed precedent `set_internal_override` (`routers/visitors.py:1014`); `_verify_site_access` (dependencies), `human_only_visitor_filter` (services), and the `do_not_resolve` short-circuit (`visitors.py:932`) all exist; audit reuses the repo-wide `structlog` id-only pattern (no new table, no migration); integration lane needs local PG+Redis (documented).
- Test coverage: CONCERN — all 7 backend behaviors are non-vacuous Fully-Automated integration gates (plus 2 existing regression suites); the 4 UI behaviors (AC-1/2/3/6) are Hybrid e2e whose automation half depends on the recurring repo-wide **Clerk Playwright auth-harness** gap, and the web app has no React component-test runner; AC-13 legal-adequacy is a counsel Known-Gap. All pre-documented with backlog stubs.
- Breaking changes: PASS — pure additive: one route, one `VisitorOut.do_not_resolve: bool = False` field (populated safely via the proven `VisitorOut.model_validate(orm_row)` + `from_attributes=True` path at `visitors.py:155`), one web client method, one `renderIdentity` branch. No signature changes; rollback = revert. Note: the field follows the exact additive pattern of `confidence_score` (already on `VisitorOut:41`) and does not touch that assignment path — introduces no new `GET /visitors` 500 risk.
- Security surface: PASS — reuses `get_current_user` + `_verify_site_access` (identical gate to `/resolve`); 404-not-403 no-id-leak; bounded single-boolean write, no request body / no mass-assignment; structlog audit logs truncated id only (no PII); does NOT un-suppress and does NOT auto-fire (consistent with `privacy.py` "no silent reverse").
- Section feasibility (Touchpoints/Impl Checklist): PASS — all 6 touchpoint files exist on disk; web precedents `setInternalOverride` (`api.ts:383`) + `resolveVisitor` (`api.ts:1043`) and the `dialog.tsx` shadcn primitive confirmed (no `alert-dialog.tsx` — plan already accounts for this); highest-risk edit is the `renderIdentity` branch ordering, mechanically feasible.

Open gaps:
- AC-1/2/3/6 web e2e legs: known-gap: documented — blocked on shared Clerk Playwright auth-harness (recurring repo-wide gap); register backlog stub at EXECUTE if harness unavailable; do NOT mark terminal-green.
- AC-13 legal-adequacy: known-gap: documented — counsel review tracked in `process/features/visitors-identity/backlog/privacy-copy-counsel-review_NOTE_07-08-26.md`; AC-13 stays CONDITIONAL.

What this coverage does NOT prove:
- The integration gates (AC-4/5/7/9/10/11) prove endpoint auth, scoping, idempotency, no-bypass, no-un-suppress, and audit-event shape against a real DB — they do NOT prove the rendered dashboard banner/button/confirm-dialog wiring (that is the Hybrid e2e half).
- `test_integration_clear_then_reoptout_resticks` + the existing sticky suite prove aggregation semantics are unchanged — they do NOT prove behavior under real concurrent clear+re-optout races (last-writer-wins accepted per Failure Modes).
- `test_clear_hold_audit_record` proves the structlog event fields and PII-absence — it does NOT prove durable/queryable audit (deliberately deferred; structlog-only).
- The pixel regression suite proves size/capture budget unchanged — it does NOT re-prove tracker capture logic (untouched by this plan).
- The Agent-Probe copy-presence check proves marker strings are present — it does NOT prove the copy is legally adequate (counsel Known-Gap).

Gate: CONDITIONAL (concerns are pre-documented Known-Gaps; no FAILs; backend fully proven)
Accepted by: ACCEPTED — Known-Gaps (Clerk e2e AC-1/2/3/6; AC-13 counsel) accepted for EXECUTE; EVL independent PASS 10-08-26; UPDATE PROCESS archived WITH_GAPS.

## Autonomous Goal Block

SESSION GOAL: Privacy-hold UX + explicit site-owner Clear for sticky `do_not_resolve` (Option D)
Charter + umbrella plan: N/A — single SIMPLE plan (`privacy-hold-clear_PLAN_09-08-26.md`)
Autonomy: user-initiated VALIDATE (no active /goal); EXECUTE requires explicit user acceptance of the CONDITIONAL known-gaps + explicit "ENTER EXECUTE MODE".
Hard stop conditions / safety constraints:
- Never run any DB command (pytest integration included) without pinning `DATABASE_URL=localhost:5433` — repo `.env` `DATABASE_URL` points at Supabase PROD and `migrations/env.py` has no local-host guard.
- Do NOT add a migration; do NOT alter aggregator sticky `BOOL_OR`/`OR` semantics, suppression, resolve gates, or the pixel.
- Do NOT add an Identify bypass or auto-clear; clear writes only the single `do_not_resolve=False` boolean.
- Do NOT mark AC-1/2/3/6 or AC-13 terminal-green — they stay CONDITIONAL with backlog stubs.
Next phase: DONE — archived `process/features/visitors-identity/completed/privacy-hold-clear_09-08-26/`
Validate contract: inline in plan (this section), Gate: CONDITIONAL
Execute start: `.venv/bin/python -m pytest tests/integration/test_privacy_hold_clear.py -q` | regression `test_optout_flow.py` + `test_pixel*` | e2e `cd apps/web && npm run test:e2e` (conditional on Clerk auth-harness) | high-risk pack: no

## Resume and Execution Handoff

- **Selected plan (single execute anchor):**
  `process/features/visitors-identity/completed/privacy-hold-clear_09-08-26/privacy-hold-clear_PLAN_09-08-26.md`
- **SPEC:** `…/privacy-hold-clear_09-08-26/privacy-hold-clear_SPEC_09-08-26.md`
- **Start order:** T2 (schema) → T1 (endpoint + audit) → T5 (backend integration tests) → T3/T4
  (web client + UI + confirm) → T6 (e2e) → run gates + confirm AC-8/AC-12 suites unchanged.
- **Test runner:** pytest integration (`.venv/bin/python -m pytest tests/integration/test_privacy_hold_clear.py -q`) | pytest unit (regression) | Playwright e2e (`cd apps/web && npm run test:e2e`).
- **Validator commands for handoff:**
  `node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs <this-plan>` and, since a
  new API surface is added, `node .claude/skills/vc-audit-vc/scripts/validate-agent-parity.mjs --strict`
  is NOT required (no agent-surface change) — parity N/A.
- **Do not:** touch aggregator sticky semantics, suppression, resolve gates, or the pixel; add a
  migration; auto-clear; add an Identify bypass.

## Next Step

✅ Archived to `process/features/visitors-identity/completed/privacy-hold-clear_09-08-26/`.
Remaining: commit source (dirty worktree — invoke `vc-git-manager` when user asks) + close
Clerk e2e / counsel backlog notes when those residuals land.
