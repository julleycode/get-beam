---
phase: phase-6-hot-contacts-dashboard
date: 2026-08-05
status: COMPLETE_WITH_GAPS
feature: visitors-identity
plan: process/features/visitors-identity/active/identity-program_03-08-26/phase-6-hot-contacts-dashboard_PLAN_03-08-26.md
---

# Phase 6 — Hot-Contacts Dashboard — EXECUTE report

**TL;DR:** Shipped the "N of your M imported contacts active this week" query, endpoint, and
dashboard widget. All sandbox-runnable gates green (9 new unit tests, full unit lane 1638 passed /
0 failed vs 1629 baseline, frontend `tsc` clean). Both PVL-flagged mechanical bugs (multi-merged-child
double-count, route shadowing) are prevented by construction AND covered by tests. Remaining gaps are
the pre-named program-wide Docker/Agent-Probe class.

## What Was Done

| File | Change |
|---|---|
| `apps/api/services/hot_contacts.py` (new) | Query layer. Activity resolved via a **correlated scalar subquery** `MAX(merged_child.last_seen)` correlated on the outer `Visitor` — structurally incapable of JOIN fan-out, so a phantom with 2+ merged children counts exactly once. Reuses `agent_visitor_filters.has_merged_child`'s exact join predicate (`canonical_visitor_id` / `site_id` / `identity_status == "merged"`). Exposes `imported_contacts_total_query` (M, no join), `hot_contacts_count_query` (N), `hot_contacts_list_query` (drill-down), `hot_contacts_summary` (async orchestrator). |
| `apps/api/routers/hot_contacts.py` (new) | `GET /{site_id}/contacts/hot`, `verify_site_access` dependency (404-not-403), `days` (1-90, default 7) + `limit` query params. Deliberately a **separate router file** — see route-shadowing note below. |
| `apps/api/main.py` | Import + `include_router(hot_contacts.router, ...)` registered **before** `contacts.router`, with a load-bearing-order comment. |
| `apps/web/src/lib/api-types.ts` | `HotImportedContact`, `HotImportedContactsSummary`. |
| `apps/web/src/lib/api.ts` | `getHotImportedContacts(siteId, days=7)` + type import/re-export. |
| `apps/web/src/app/dashboard/contacts/page.tsx` | Summary card: "N of your M imported contacts active this week" + drill-down table (name / email / last activity). Copy says **imported contacts** throughout. Failure of the additive summary hides the widget, never breaks the import surface. |
| `tests/unit/test_hot_contacts_query.py` (new) | 9 structural tests (D1a). |
| `tests/integration/test_hot_contacts.py` (new) | 6 row-level tests (D1 + D3). |

### The two PVL-flagged bugs

1. **Multi-merged-child double-count** — avoided by construction (correlated `MAX()` subquery, never
   an ungrouped LEFT JOIN). Proven two ways: structurally
   (`test_count_query_is_counting_safe_against_multi_merged_children`) and row-level
   (`test_count_multi_merged_child_phantom_exactly_once`, asserts count==1 and that the reported
   timestamp is the *most recent* of the two children). The structural assertion was
   **mutation-checked**: a naive LEFT JOIN + COUNT form was compiled in a scratch run and confirmed to
   FAIL both assertions (no `max(`, single SELECT) — the gate is non-vacuous.
2. **Route shadowing** — avoided by using a new dedicated router registered before `contacts.router`.
   Two guards: a unit test asserting `paths.index("/…/contacts/hot") < paths.index("/…/contacts/{visitor_id}")`
   on the live `app.routes` (verified: index 32 vs 35), and a live integration test asserting the
   response body contains `active_count` rather than a 404 from `get_imported_contact`.

## What Was Skipped or Deferred

- **C2 / D2 Agent-Probe visual check** — no running API + Postgres in this sandbox. Same
  Agent-Probe/Docker-gated class carried by Phases 1/4/5. Widget code is `tsc`-clean and follows the
  page's existing Card/table idiom.
- **Integration gates unrun** (Docker unavailable) — written and `--collect-only` clean (6 tests).

## Test Gate Outcomes

| Gate | Tier | Command | Result |
|---|---|---|---|
| Hot-contacts query structural shape (AC13) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_hot_contacts_query.py -q` | **9 passed** |
| N/M count incl. multi-merged-child dedup (AC13) | Hybrid (Docker) | `… tests/integration/test_hot_contacts.py -k count -q` | **KNOWN-GAP** — written, collects clean, unrun (no Docker) |
| Cross-tenant isolation (umbrella constraint) | Hybrid (Docker) | `… tests/integration/test_hot_contacts.py -k tenant -q` | **KNOWN-GAP** — written, collects clean, unrun (no Docker) |
| Widget renders (AC13) | Agent-Probe | manual visual check | **KNOWN-GAP** — deferred, no running stack |
| Full unfiltered unit lane | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -q` | **1638 passed, 2 skipped, 0 failed** (baseline 1629 → +9 new; no regression) |
| Frontend typecheck | Fully-Automated | `cd apps/web && npx tsc --noEmit` | **clean (0 errors)** |
| Alembic head (read-only) | — | `alembic -c apps/api/alembic.ini heads` | `e9d2a4c71f68` — single head, unchanged, no new migration |

## Plan Deviations

None material. One naming choice within blast radius: the plan left the service filename as
"e.g. `apps/api/services/hot_contacts.py`" — used exactly that, plus a matching
`apps/api/routers/hot_contacts.py` (the plan's required "new dedicated router file", name unspecified).

Hard constraints honored: no auto-send (read-only endpoint, sends nothing);
`is_emailable_identity` untouched (still 3 params); `dashboard.py:91` / `get_overview()` untouched;
Phase 2 guard, Phase 3 decoration, Phase 4 import write-path, Phase 5 sweep all untouched; no
migration; no git state-changing commands run; no "known contacts" wording anywhere in this phase's
copy or API naming.

## Test Infra Gaps Found

No new infra gaps. Existing pre-named gaps re-confirmed: no Docker → `tests/integration/*` unrunnable;
no running dashboard stack → Agent-Probe deferred.

## Closeout Packet

- **Selected plan:** `process/features/visitors-identity/active/identity-program_03-08-26/phase-6-hot-contacts-dashboard_PLAN_03-08-26.md`
- **Finished:** Steps A1/A2/A4, B1–B4, C1, D1, D1a, D3.
- **Verified:** unit structural gate (mutation-checked), full unit lane, frontend typecheck, route order, alembic head.
- **Unverified:** row-level N/M arithmetic and cross-tenant isolation against real Postgres; widget visual render.
- **Follow-up stubs created:** none new — the residuals fold into the program's existing Docker-gate
  known-gap class (see the umbrella + prior phases' backlog notes).
- **CONTEXT_PARTIAL items:** none.
- **Classification:** `Keep in active/testing` — code-complete, EVL pending, Docker-gated gates outstanding.

## Forward Preview

- **Test Infra Found:** `tests/unit/test_hot_contacts_query.py` is the sandbox-runnable proxy for the
  hot-contacts query; extend it rather than relying on Docker for shape regressions.
- **Blast Radius Changes:** two new backend files + `main.py` registration line; three frontend files.
  Nothing pre-existing was modified beyond additive lines.
- **Commands to Stay Green:** `.venv/bin/python3.11 -m pytest tests/unit -q` (expect ≥1638 passed, 0 failed);
  `cd apps/web && npx tsc --noEmit`.
- **Dependency Changes:** none.
- **Note for whoever gets Docker:** run
  `.venv/bin/python3.11 -m pytest tests/integration/test_hot_contacts.py -q` — it closes this phase's
  last two Hybrid gates and is self-contained (creates its own users/sites/fixtures).

This is the FINAL phase of the identity-honesty program.
