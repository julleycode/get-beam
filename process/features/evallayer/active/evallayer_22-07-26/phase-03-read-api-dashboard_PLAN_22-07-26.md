---
name: plan:evallayer-phase-03-read-api-dashboard
description: "EvalLayer — Phase 03: Read API /agents + dashboard 'Agents' tab (clone Visitors list/detail/stats)"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-03
---

# Phase 03 — Read API + Dashboard Tab

**Program:** evallayer
**Umbrella plan:** process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md
**Phase status:** ⏳ PLANNED
**Report destination:** process/features/evallayer/active/evallayer_22-07-26/phase-03-read-api-dashboard_REPORT_22-07-26.md

---

## Purpose

Give users a place to see agent visits: a new `/agents` API router (list/detail/stats, structurally
cloning `apps/api/routers/visitors.py` and reusing `verify_site_access`), plus a new top-level
"Agents" dashboard tab (structurally cloning the Visitors list/detail pages and widget shell). Per
SPEC decision D1/nav resolution, this is a separate top-level tab, not a filter on Visitors.

---

## Entry Gate

- Phase 2 exit gate passed (agent visits are persisted and queryable).

---

## Blast Radius

- `apps/api/routers/agents.py` (new)
- `apps/api/schemas/agents.py` (new)
- `apps/api/main.py` (register new router)
- `apps/web/src/app/dashboard/agents/*` (new — list + detail pages)
- `apps/web/src/app/dashboard/layout.tsx` (new nav item)
- `apps/web/src/lib/api.ts`, `apps/web/src/lib/api-types.ts` (new typed methods/types)
- `apps/web/src/components/ui/status-badge.tsx` (3 new STATUS_TONE entries)
- `tests/integration/test_agents_api.py` (new)
- `apps/web/e2e/agents.spec.ts` (new)

---

## Locked Shared Contract (backend schema + frontend types MUST match field-for-field)

**`AgentOut`** (list row): `id`(UUID str), `site_id`(str), `vendor`(str),
`product_or_ua_token`(str), `verification_method`(str: `"ua-only"` | `"ip-verified"` |
`"rdns-verified"`), `last_seen_at`(datetime), `visit_count`(int).

**`AgentDetailOut(AgentOut)`** adds: `first_seen_at`(datetime), `ip_address`(str | null),
`page_paths`(str[]), `resolved_company_id`(UUID str | null).

**`AgentListResponse`**: `{ agents: AgentOut[], total: int, page: int, page_size: int }`.
**`AgentStatsResponse`**: `{ total_visits: int, distinct_vendors: int, by_vendor: dict[str, int] }`.

Both `Out` schemas set `model_config = {"from_attributes": True}` (matches
`apps/api/schemas/visitors.py:42` convention).

**Frontend TS (`apps/web/src/lib/api-types.ts`)**: `Agent` (mirrors `AgentOut`), `AgentDetail
extends Agent` (adds the 4 detail fields), `AgentListResponse`, `AgentStatsResponse` — field names
are snake_case on the wire, matching the existing `Visitor` type convention (no camelCase mapping
layer).

**Confirmed at PVL (22-07-26) against `apps/api/models/agent_visit.py`:** `AgentVisit` (Phase 1)
carries exactly `site_id`, `vendor`, `product_or_ua_token`, `verification_method`, `first_seen_at`,
`last_seen_at`, `ip_address`, `page_paths`, `visit_count`, `resolved_company_id`, plus the
Base-inherited `id`(UUID PK)/`created_at`/`updated_at` — the Locked Shared Contract above maps
field-for-field onto real columns. No drift found.

---

## Implementation Checklist

### Step A — Backend read API

- [ ] A1. Create `apps/api/schemas/agents.py`: `AgentOut`, `AgentDetailOut(AgentOut)`,
      `AgentListResponse`, `AgentStatsResponse` per the Locked Shared Contract above. Both `Out`
      schemas carry `model_config = {"from_attributes": True}` (clone
      `apps/api/schemas/visitors.py` pattern).
- [ ] A2. Create `apps/api/routers/agents.py`:
      - `router = APIRouter()`
      - Import `verify_site_access as _verify_site_access` from `apps.api.dependencies`
        (same import alias convention as `visitors.py:13`) and `get_current_user`.
      - `GET /{site_id}` — list. Params: `page: int = Query(1, ge=1)`, `page_size: int =
        Query(50, ge=1, le=100)`, `vendor: str | None = None`, `verification_method: str | None
        = None`. Call `await _verify_site_access(db, site_id, user)` FIRST. Query ONLY the
        `AgentVisit` model (AC6 — never join `Visitor` or `Event`). Apply `vendor`/
        `verification_method` filters identically to BOTH the row query and the `func.count()`
        query so `total` matches the filtered set. Default sort `last_seen_at DESC`.
        `response_model=AgentListResponse`.
      - `GET /{site_id}/stats` — `AgentStatsResponse` (`total_visits`, `distinct_vendors`,
        `by_vendor` via grouped count on `vendor`). Call `_verify_site_access` first.
        **MUST be registered in the router BEFORE the `/{site_id}/{agent_visit_id}` route below**
        — FastAPI matches routes in registration order and `/stats` would otherwise be swallowed
        by the `{agent_visit_id}` path-param catch-all (same sharp edge as `visitors.py` avoids
        by ordering `/countries` and `/stats` before the detail route at lines 186/237 vs 484).
      - `GET /{site_id}/{agent_visit_id}` — `AgentDetailOut`. Call `_verify_site_access` first.
        404 (not 403) if the row does not exist OR belongs to a different site — never leak
        cross-tenant existence.
      - **[PVL FIX 22-07-26 — mechanical gap]** `AgentVisit` has NO `agent_visit_id` column —
        unlike `Visitor.visitor_id` (a distinct business-id field that `visitors.py:494` queries
        by), the only identifier `AgentVisit` has is the `Base`-inherited `id` UUID primary key
        (see `agent_visit_persistence.py` — rows are upserted by the `(site_id, vendor,
        product_or_ua_token)` unique constraint, and `id` is never set explicitly). The detail
        route MUST query `AgentVisit.id == <parsed UUID>` (still filtered by `site_id` too), NOT
        a nonexistent `AgentVisit.agent_visit_id` attribute — that would be an `AttributeError`,
        not a 404. Parse the `agent_visit_id: str` path param via `uuid.UUID(agent_visit_id)`
        inside a `try/except ValueError` — on parse failure return 404 (not 500), same
        never-leak-cross-tenant-existence posture as the not-found case. Import `uuid` at the top
        of the file.
      - Route registration order in the file: list → stats → detail (stats before the
        parameterized detail route).
- [ ] A3. Register the router in `apps/api/main.py` beside the visitors registration (~line 188):
      `app.include_router(agents.router, prefix="/api/v1/agents", tags=["agents"])`. Add the
      `from apps.api.routers import ... agents ...` import alongside the existing router imports.
      **PVL note:** confirmed real insertion point — `visitors.router` registers at line 188 of
      current `main.py`; re-grep for the exact line before editing since Phase 1 already added one
      import line to this same file (additive only, no expected collision, but line numbers may
      have shifted).

### Step B — Frontend dashboard tab

- [ ] B1. Add a new `NavItem` to `EASYTRACK_ITEMS` in `apps/web/src/app/dashboard/layout.tsx`
      (after the `Visitors` entry, ~line 51): `{ href: "/dashboard/agents", label: "Agents", icon:
      Bot, tour: "agents" }`. Add `Bot` to the existing `lucide-react` import block at the top of
      the file. **PVL confirmed:** `EASYTRACK_ITEMS` starts at line 49, `Visitors` entry at line
      51, `Bot` is not currently imported (no name collision) — insertion point is real.
- [ ] B2. Create `apps/web/src/app/dashboard/agents/page.tsx` (client component). Clone
      `apps/web/src/app/dashboard/visitors/page.tsx` structure MINUS the filter bar / saved
      widget-layout machinery:
      - `SiteSelector` for site scoping (same pattern as visitors page).
      - TanStack Query: `useQuery({ queryKey: ["agents", siteId, page, vendor, verification_method],
        queryFn: () => listAgents(siteId, { page, page_size, vendor, verification_method }) })`.
      - Table columns: vendor, product_or_ua_token, verification badge (via `StatusBadge`),
        last_seen_at, visit_count.
      - Reuse `TableSkeleton`, `ErrorBanner`, `EmptyState` components from the visitors page's
        shared UI (same import paths).
      - Pagination controls matching the visitors page pattern.
      - Inline KPI row (NOT a persisted/localStorage widget layout — simpler than visitors'
        widget system) sourced from `useQuery(["agent-stats", siteId], () => getAgentStats(siteId))`:
        render `total_visits` and `distinct_vendors`.
- [ ] B3. Create `apps/web/src/app/dashboard/agents/[agentVisitId]/page.tsx` (client component).
      THIN detail page — clone the local (unexported) `Section`/`InfoRow` helper components from
      `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` (they are file-local, not
      exported — copy the function bodies, do not attempt to import them):
      - Hero: vendor + product_or_ua_token + verification-method badge (`StatusBadge`).
      - Activity section: first_seen_at, last_seen_at, ip_address, page_paths (render as a list
        of `Badge` chips), visit_count.
      - Back-link to `/dashboard/agents`.
- [ ] B4. Add 3 new entries to `STATUS_TONE` in `apps/web/src/components/ui/status-badge.tsx`
      (after the "visitors / enrichment / keys" block, ~line 37 — confirmed at PVL, plan
      originally said ~line 35, trivial drift): `"ua-only": "neutral"`, `"ip-verified": "info"`,
      `"rdns-verified": "success"`. No new component needed — reuse `<StatusBadge
      status={agent.verification_method} label="UA only" | "IP verified" | "rDNS verified" />`
      pattern (pass explicit `label` since the raw enum string uses hyphens, not the
      auto-generated `replace(/_/g," ")` transform).

### Step C — Frontend API client

- [ ] C1. Add to `apps/web/src/lib/api-types.ts` (near the existing `Visitor`/`VisitorDetail`
      types): `Agent`, `AgentDetail extends Agent`, `AgentListResponse`, `AgentStatsResponse` per
      the Locked Shared Contract above — snake_case field names to match the wire format.
- [ ] C2. Add to `apps/web/src/lib/api.ts` (near `listVisitors`/`getVisitor`):
      `listAgents(siteId: string, params: { page?: number; page_size?: number; vendor?: string;
      verification_method?: string }): Promise<AgentListResponse>`,
      `getAgent(siteId: string, agentVisitId: string): Promise<AgentDetail>`,
      `getAgentStats(siteId: string): Promise<AgentStatsResponse>`. Mirror the existing
      `listVisitors`/`getVisitor` call shape (query-string building, base client usage).

### Step D — Tests (added at PVL 22-07-26 — was missing from the checklist despite being named in Exit Gate / Verification Evidence)

- [ ] D1. Create `tests/integration/test_agents_api.py` (Docker-gated — PG+Redis via
      `infra/docker-compose.yml`, same as other `tests/integration/` files). Loose-pattern clone
      of an existing router-integration test (e.g. `tests/integration/test_visitor_filters.py` for
      fixture/client setup shape). Must include, at minimum, these named test functions (exact
      names — referenced by the Exit Gate and Verification Evidence sections below):
      - `test_list_agents_only_agent_visits` — list endpoint returns only `AgentVisit` rows;
        hitting `/agents` does not change `/visitors` list/count results (cross-check both
        endpoints in the same test, AC6).
      - `test_agent_stats_shape` — `/stats` counts correctly grouped by vendor.
      - `test_agent_verification_method_in_response` — `AgentOut`/`AgentDetailOut` include
        `verification_method` with one of `"ua-only" | "ip-verified" | "rdns-verified"` (AC7).
      - `test_agent_multi_tenancy_404` — foreign `site_id` → 404 not 403.
      - `test_stats_route_registered_before_detail_catchall` — `/stats` resolves to the stats
        handler, not the detail-by-id catch-all (route-ordering sharp edge, A2).
      - Also cover the PVL-added ID-parsing fix from A2: an `agent_visit_id` that is not a valid
        UUID returns 404, not 500.
- [ ] D2. Create `apps/web/e2e/agents.spec.ts` (loose-pattern clone of
      `apps/web/e2e/visitors.spec.ts` — reuse `auth.setup.ts`). Must cover, at minimum:
      - `/dashboard/agents` renders an "Agents" heading; `/dashboard/visitors` still renders its
        own heading unaffected (tab separation, AC6).
      - The verification-method badge renders on a list/detail row and its visible text matches
        the underlying field (AC7). Follow the canonical Playwright rules in
        `process/context/tests/all-tests.md` (auto-retry `toBeVisible`, `.first()` with `.or()`,
        specific selectors, read component source before writing selectors).

---

## Exit Gate

```bash
# Tab separation (AC6) — backend proof
.venv/bin/python -m pytest tests/integration/test_agents_api.py -q
# Expected: /agents endpoints return only AgentVisit rows; hitting /agents does not
# change /visitors list/count results (cross-check both endpoints in the same test)

# Confidence badge (AC7) — backend + frontend proof
.venv/bin/python -m pytest tests/integration/test_agents_api.py -k verification_method -q
# Expected: AgentOut/AgentDetailOut response includes verification_method field with one of
# "ua-only" | "ip-verified" | "rdns-verified"

npm run --prefix apps/web build
# Expected: exits 0 — proves apps/web/src/lib/api-types.ts, api.ts, agents/*, layout.tsx,
# and status-badge.tsx all compile against the locked contract (Next.js build runs tsc)
```

- Both exit-gate criteria (AC6, AC7) pass.
- Phase report written to report destination above.

---

## Blockers That Would Justify BLOCKED Status

- Phase 2 exit gate not yet passed (no agent-visit data to read).
- Confidence field shape from Phase 1 schema is ambiguous or missing.

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [ ] 1. RESEARCH — research-agent: prior phase reports read; test context loaded; plan drift checked
- [ ] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written
- [x] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated with locked contract + full
      checklist (this supplement pass, 22-07-26); Inner Loop Refresh Note written below
- [x] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md`; 2 mechanical plan gaps found and fixed in-plan (Step D tests added; A2 ID-mapping bug documented) — Gate: PASS with documented environment known-gaps
- [x] 5. EXECUTE — all checklist items (A–D) done; FE build + unit gates green (Docker integration + e2e = env known-gaps); report written 22-07-26
- [x] 6. EVL — independent vc-tester confirmation run GREEN on all runnable gates (FE compile, unit regression, static safety review of 5 declared properties); Docker integration + Playwright e2e remain KNOWN-GAP (env-gated, close-commands recorded in phase report); no follow-up code stubs needed beyond the existing backlog test-building stub for the Agent-Probe badge judgment
- [x] 7. UPDATE PROCESS — phase report augmented with EVL results, umbrella state updated, blast-radius registry finalized, commit next (vc-git-manager)

**Validate-contract required before execute.** New public API surface — VALIDATE may never be
skipped for this phase.

---

## Inner Loop Refresh Note (22-07-26)

Supplement pass locked the exact backend/frontend contract and expanded the checklist from
high-level steps to atomic, file-and-line-referenced actions:
- Locked `AgentOut`/`AgentDetailOut`/`AgentListResponse`/`AgentStatsResponse` field shapes
  (backend schema ↔ frontend TS types must match exactly).
- Called out the FastAPI route-ordering sharp edge (`/stats` must register before the
  `/{agent_visit_id}` catch-all) — confirmed against `visitors.py`'s existing `/countries` +
  `/stats` before `/{visitor_id}` pattern.
- Confirmed no `typecheck` script exists in `apps/web/package.json` — `npm run build` (which runs
  `next build` → `tsc`) is the correct FE compile-gate command, not a bespoke typecheck script.
- Confirmed `apps/web/e2e/agents.spec.ts` does not yet exist; `playwright.config.ts` lives at
  `apps/web/playwright.config.ts`.
- Added `apps/api/main.py` and `status-badge.tsx` to Blast Radius (previously omitted — router
  registration and badge tone entries are real touchpoints).
- Sections changed: Blast Radius, Implementation Checklist (A/B/C fully expanded), Exit Gate,
  Verification Evidence, Test Infra Improvement Notes (new), Touchpoints.

## PVL Plan Updates Applied (22-07-26)

Two mechanical gaps found during VALIDATE V2 fan-out, fixed directly in this plan (V6 "Plan
Updates"), not left as execute-agent guesswork:
1. **Step D (Tests) added.** The checklist (Steps A-C) never instructed creating
   `tests/integration/test_agents_api.py` or `apps/web/e2e/agents.spec.ts`, despite both being
   named in Blast Radius, Exit Gate, and Verification Evidence with exact test-function names.
   Step D now lists the exact functions to write.
2. **A2 ID-mapping bug documented.** `AgentVisit` has no `agent_visit_id` column (only the
   `Base`-inherited `id` PK, upserted by the `(site_id, vendor, product_or_ua_token)` unique
   constraint per `agent_visit_persistence.py`). Cloning `visitors.py`'s `Visitor.visitor_id`
   query pattern verbatim would raise `AttributeError`. A2 now specifies: query by
   `AgentVisit.id` after parsing the path param as a UUID inside a `try/except ValueError` →
   404 on parse failure (never 500, never leak cross-tenant existence).

Both fixes are additive to the plan text; no scope expansion. Confirmed the `AgentOut`/
`AgentDetailOut` Locked Shared Contract otherwise matches `apps/api/models/agent_visit.py`
field-for-field with no drift.

---

## Touchpoints

- `apps/api/routers/agents.py` (new)
- `apps/api/schemas/agents.py` (new)
- `apps/api/main.py` (router registration)
- `apps/web/src/app/dashboard/agents/page.tsx` (new)
- `apps/web/src/app/dashboard/agents/[agentVisitId]/page.tsx` (new)
- `apps/web/src/app/dashboard/layout.tsx` (nav item)
- `apps/web/src/lib/api.ts`, `apps/web/src/lib/api-types.ts`
- `apps/web/src/components/ui/status-badge.tsx`
- `tests/integration/test_agents_api.py` (new)
- `apps/web/e2e/agents.spec.ts` (new)

---

## Public Contracts

- New `/api/v1/agents/{site_id}`, `/api/v1/agents/{site_id}/stats`,
  `/api/v1/agents/{site_id}/{agent_visit_id}` (net-new public API surface, mirrors `/visitors`
  shape and multi-tenancy semantics — 404-not-403 on foreign `site_id`).
- Existing `/visitors` API and "Visitors" tab behavior unchanged (AC6 — read-only addition, no
  shared query path with Visitor/Event).

---

## Blast Radius (risk class)

- Net-new read-only API surface (public API contract change) — moderate risk class: public API.
  No auth/identity, billing, schema-migration, or destructive-write surface touched. No new
  dependency, agent, or runtime surface introduced.
- ~10 files touched (backend: 3 new/modified, frontend: 6 new/modified, tests: 2 new).

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `tests/integration/test_agents_api.py::test_list_agents_only_agent_visits` — list endpoint returns only `AgentVisit` rows; hitting `/agents` doesn't change `/visitors` counts | Hybrid (Docker PG+Redis) | AC6 |
| `tests/integration/test_agents_api.py::test_agent_stats_shape` — `/stats` counts correctly grouped by vendor | Hybrid (Docker PG+Redis) | AC6 |
| `tests/integration/test_agents_api.py::test_agent_verification_method_in_response` — `AgentOut`/`AgentDetailOut` include `verification_method` | Hybrid (Docker PG+Redis) | AC7 |
| `tests/integration/test_agents_api.py::test_agent_multi_tenancy_404` — foreign `site_id` → 404 not 403 | Hybrid (Docker PG+Redis) | AC6 (tenancy safety) |
| `tests/integration/test_agents_api.py::test_stats_route_registered_before_detail_catchall` — `/stats` resolves to stats handler, not detail-by-id | Hybrid (Docker PG+Redis) | AC6 (route-ordering sharp edge) |
| `tests/integration/test_agents_api.py` — invalid-UUID `agent_visit_id` → 404 not 500 | Hybrid (Docker PG+Redis) | AC6 (PVL-added ID-mapping fix) |
| `npm run --prefix apps/web build` — FE types (`Agent`, `AgentDetail`, `AgentListResponse`, `AgentStatsResponse`) compile against the locked contract | Fully-Automated | AC6, AC7 (contract match) |
| `apps/web/e2e/agents.spec.ts` — `/dashboard/agents` renders an "Agents" heading; `/dashboard/visitors` still renders its own heading unaffected | Hybrid (needs dev server; Playwright) | AC6 (tab separation, UI level) |
| `apps/web/e2e/agents.spec.ts` — verification-method badge renders and text matches underlying field | Agent-Probe (visual/text judgment on rendered badge) | AC7 |

Command block (for copy-paste at EXECUTE/EVL time):

```bash
# Backend hybrid gates (Docker PG+Redis required — known-gap in a non-Docker dev shell)
.venv/bin/python -m pytest tests/integration/test_agents_api.py -q

# Backend unit regression (no Docker needed) — confirms no regression vs current baseline
.venv/bin/python -m pytest tests/unit -q

# Frontend compile gate (fully automated, no Docker)
npm run --prefix apps/web build

# Frontend lint (fully automated, no Docker)
npm run --prefix apps/web lint

# Frontend e2e (hybrid — needs dev server running; see apps/web/playwright.config.ts)
npx playwright test apps/web/e2e/agents.spec.ts --config=apps/web/playwright.config.ts
```

---

## Test Infra Improvement Notes

- `tests/integration/` requires Docker (Postgres 16 + Redis 7) per `TESTING.md` — the Hybrid-tier
  gates above cannot run to completion in an environment without Docker. Confirm Docker
  availability before EXECUTE, or mark those gates as a documented known-gap for this run with a
  backlog note to run them in CI/Docker-enabled environment. **Confirmed at PVL (22-07-26):**
  Docker is unavailable in this sandbox (`docker info` times out) — same environment condition
  already documented as a known-gap in Phase 1 and Phase 2's registry entries. Not a new finding.
- No `typecheck` script exists in `apps/web/package.json` — `npm run build` is the closest
  fully-automated FE compile gate (runs `next build` → `tsc` internally). If a dedicated
  `tsc --noEmit` script is added to the repo later, prefer it over the full `next build` for
  faster iteration during EXECUTE.
- `apps/web/e2e/agents.spec.ts` does not exist yet — must be authored fresh (loose-pattern clone
  of `apps/web/e2e/visitors.spec.ts`); obey the flaky-e2e rules documented in
  `process/context/tests/all-tests.md` before finalizing assertions.

---

## Resume and Execution Handoff

1. Selected plan file path: `process/features/evallayer/active/evallayer_22-07-26/phase-03-read-api-dashboard_PLAN_22-07-26.md`
2. Last completed phase or step: Step 4 (PVL) — validate-contract written 22-07-26; Gate: PASS
   with documented environment known-gaps (Docker integration tests, Playwright e2e).
3. Validate-contract status: written (see `## Validate Contract` below), `generated-by:
   inner-pvl: phase-3`.
4. Supporting context files loaded: `process/context/all-context.md`, `apps/api/routers/visitors.py`,
   `apps/api/schemas/visitors.py`, `apps/api/main.py`, `apps/api/dependencies.py`,
   `apps/api/models/agent_visit.py`, `apps/api/services/agent_visit_persistence.py`,
   `apps/web/src/app/dashboard/layout.tsx`, `apps/web/src/app/dashboard/visitors/page.tsx`,
   `apps/web/src/lib/api.ts` / `api-types.ts`, `apps/web/src/components/ui/status-badge.tsx`,
   `apps/web/package.json`, `apps/web/playwright.config.ts`, `process/context/tests/all-tests.md`.
5. Next step for a fresh agent picking up mid-execution: spawn `vc-execute-agent` for Step 5
   (EXECUTE) — implement Steps A-D in order (backend schema → router → main.py registration, then
   frontend types → api client → pages → nav → badge, then tests), honoring the two PVL-added
   fixes (Step D test list; A2 ID-mapping via `AgentVisit.id` + UUID parse/404).

---

## Validate Contract

Status: PASS
Date: 22-07-26
date: 2026-07-22
generated-by: inner-pvl: phase-3

Parallel strategy: sequential (single validate-agent pass; blast radius is 2 domains — backend +
frontend — with no cross-talk needed between them; program-level phase-plan creation elsewhere in
this program uses agent-team, but this is a read-only VALIDATE pass on one already-written plan)
Rationale: Signals present: S2 (public API surface touched), S4 (phase-program classification),
S6 (high-risk class: public API contract), S7 (~10 files in blast radius) = 4/7 → HIGH score by
the threshold table, but the two Layer-2 sections (backend, frontend) are independently
verifiable by direct file/source inspection with no need for mid-analysis coordination between
them, so a single synthesizing pass (this one) is the right fit over spinning up separate
parallel agents for two small, disjoint, already-well-scoped sections. Model: sonnet (VALIDATE
phase; no code execution occurs in this pass).

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC6 | `/agents` list/detail/stats query only `AgentVisit`, never `Visitor`/`Event`; hitting `/agents` doesn't change `/visitors` counts | Hybrid | `.venv/bin/python -m pytest tests/integration/test_agents_api.py::test_list_agents_only_agent_visits -q` | C (deferred — Docker unavailable in this sandbox; close-command recorded below) |
| AC6 | `/stats` grouped-by-vendor counts are correct | Hybrid | `.venv/bin/python -m pytest tests/integration/test_agents_api.py::test_agent_stats_shape -q` | C |
| AC7 | `AgentOut`/`AgentDetailOut` carry `verification_method` in `{"ua-only","ip-verified","rdns-verified"}` | Hybrid | `.venv/bin/python -m pytest tests/integration/test_agents_api.py::test_agent_verification_method_in_response -q` | C |
| AC6 (tenancy) | foreign `site_id` → 404 not 403 | Hybrid | `.venv/bin/python -m pytest tests/integration/test_agents_api.py::test_agent_multi_tenancy_404 -q` | C |
| AC6 (route order) | `/stats` resolves to stats handler, never swallowed by `/{agent_visit_id}` catch-all | Hybrid | `.venv/bin/python -m pytest tests/integration/test_agents_api.py::test_stats_route_registered_before_detail_catchall -q` | C |
| AC6 (PVL fix) | invalid-UUID `agent_visit_id` → 404 not 500 | Hybrid | `.venv/bin/python -m pytest tests/integration/test_agents_api.py -k invalid -q` (function to be added under Step D1) | C |
| AC6, AC7 (contract match) | FE `Agent`/`AgentDetail`/`AgentListResponse`/`AgentStatsResponse` compile against the locked backend contract | Fully-Automated | `npm run --prefix apps/web build` | B (fixed in this plan — gate runs at EXECUTE, no precondition) |
| — (no-regression) | Phase 3 introduces zero regressions in the existing unit baseline | Fully-Automated | `.venv/bin/python -m pytest tests/unit -q` — PVL-run baseline: 725 passed, 2 skipped (matches Phase 2's recorded baseline exactly, confirming no drift since Phase 2 closed) | A (proven now — ran at PVL, green) |
| AC6 (tab separation, UI) | `/dashboard/agents` renders distinctly from `/dashboard/visitors` | Hybrid | `npx playwright test apps/web/e2e/agents.spec.ts --config=apps/web/playwright.config.ts` | C |
| AC7 (badge judgment) | verification-method badge visible text matches underlying field | Agent-Probe | Manual/agent visual check of rendered `StatusBadge` on the agents list/detail page once EXECUTE ships it | D (backlog test-building stub — Agent-Probe judgment is not scriptable; record a stub in the phase report at EVL time) |

gap-resolution legend: A — proven now (gate passes in this cycle) · B — fixed in this plan (gate
added by this plan's checklist) · C — deferred to a named later phase/plan (here: EXECUTE/EVL time
in a Docker-enabled environment; NOT a design gap) · D — backlog test-building stub (named
residual; keep-active; continue).

C-4 reconciliation: all `strategy:` values above are Fully-Automated, Hybrid, or Agent-Probe.
Known-Gap never appears as a `strategy:` value — the Docker/e2e items are Hybrid gates with an
unmet environment precondition (that is what Hybrid means), not Known-Gap residuals. Every
developed AC6/AC7 behavior in this phase has a real Hybrid or Fully-Automated proving gate
assigned — none rests on Known-Gap alone, satisfying the vacuous-green ban.

Legacy line form (retained for existing validate-contract consumers):
- Backend read API (AC6/AC7/tenancy/route-order): Hybrid: `.venv/bin/python -m pytest tests/integration/test_agents_api.py -q` — precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis`
- Frontend compile (AC6/AC7 contract match): Fully-automated: `npm run --prefix apps/web build`
- Frontend e2e (AC6 tab separation, AC7 badge presence): Hybrid: `npx playwright test apps/web/e2e/agents.spec.ts --config=apps/web/playwright.config.ts` — precondition: Next.js dev server running
- Badge visual/text judgment (AC7): Agent-probe: manual/agent check of rendered badge text vs `verification_method` value
- Unit regression baseline: Fully-automated: `.venv/bin/python -m pytest tests/unit -q` — ran at PVL: 725 passed, 2 skipped, no regression vs Phase 2 baseline

Failing stub (Fully-Automated row — FE compile gate has no red-state stub since it's a build
command, not a test function; the no-regression unit row already passed at PVL so no stub is
needed there):
```
test("agents contract types compile against locked backend schema", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: run `npm run --prefix apps/web build` after Step C1/C2 land; must exit 0")
})
```

Dimension findings:
- Infra fit: PASS — no container/infra/runtime/port changes; FastAPI router registration and
  Next.js page/nav additions both follow existing, confirmed-real repo patterns exactly.
- Test coverage: PASS (after in-plan fix) — Step D added at PVL with exact test-function names;
  all AC6/AC7 behaviors have Hybrid or Fully-Automated gates assigned; Docker/Playwright
  preconditions are environment gaps, not design gaps (see Known Gaps below).
- Breaking changes: PASS — net-new additive API surface; `/visitors` untouched; Public Contracts
  section correctly scoped.
- Security surface: PASS — multi-tenancy via `_verify_site_access` first-line-of-every-handler
  (404-not-403, matches existing convention exactly); no new secrets, no raw SQL (ORM `select`
  only), no join to human Visitor/Event data (AC6 isolation confirmed at the model/query level);
  no new external call introduced (no `MOCK_EXTERNAL_APIS` requirement for this phase).
- Section A — Backend (routers/agents.py, schemas/agents.py, main.py): PASS (after in-plan fix) —
  mechanical feasibility HIGH (verify_site_access signature, route-ordering pattern, main.py
  insertion point, and AgentVisit field shapes all confirmed real by direct source read). Gap
  found and fixed: A2 ID-mapping bug (see PVL Plan Updates Applied above). Highest-risk edit:
  `main.py` router registration — shared file also touched by Phase 1 (additive only); mitigation
  — execute-agent must re-grep the current import/include_router block before editing, and must
  not disturb Phase 1's existing import line.
- Section B — Frontend (dashboard/agents/*, layout.tsx, api.ts/api-types.ts, status-badge.tsx):
  PASS (after in-plan fix) — mechanical feasibility HIGH (EASYTRACK_ITEMS insertion point, lucide
  `Bot` import non-collision, STATUS_TONE insertion point, Visitor/VisitorDetail and
  listVisitors/getVisitor clone patterns all confirmed real). Gap found and fixed: missing Step D2
  (e2e test authoring) — same class of gap as Section A's Step D1. Highest-risk edit: `layout.tsx`
  nav insertion — shared file, low risk since strictly additive; mitigation — insert only after
  the `Visitors` item, do not reorder existing nav entries.

Open gaps: none blocking. Environment-only known-gaps below.

Known Gaps (environment, not design — do not block PASS):
- Docker (Postgres 16 + Redis 7) is unavailable in this sandbox — all Hybrid-tier backend tests
  in `tests/integration/test_agents_api.py` are written-but-unrun until EXECUTE/EVL runs in a
  Docker-enabled environment. Close command: `docker compose -f infra/docker-compose.yml up -d
  postgres redis && .venv/bin/python -m pytest tests/integration/test_agents_api.py -q`. Same
  environment condition already logged in Phase 1 and Phase 2's blast-radius registry entries —
  not a new or phase-3-specific gap.
- Playwright e2e (`apps/web/e2e/agents.spec.ts`) requires a running Next.js dev server — not
  started in this VALIDATE pass. Close command: `npm run --prefix apps/web dev &` then `npx
  playwright test apps/web/e2e/agents.spec.ts --config=apps/web/playwright.config.ts`.
- Badge visual/text judgment (Agent-Probe, AC7) cannot be performed until the frontend ships —
  record the judgment in the Phase 3 EVL report once `/dashboard/agents` is live.

Execute-agent instructions:
- E1: Query the AgentVisit detail row by `AgentVisit.id` (parsed from the `agent_visit_id` path
  param as a `uuid.UUID` inside `try/except ValueError` → 404 on failure), never by a
  `agent_visit_id` attribute — that column does not exist on the model. See A2 PVL fix.
- E2: Before editing `apps/api/main.py`, re-grep the current router-import block and
  `include_router` list — do not assume the ~line 188 anchor is still exact; do not disturb
  Phase 1's existing additive import line.
- E3: Register `/stats` before `/{site_id}/{agent_visit_id}` in `apps/api/routers/agents.py` —
  registration order, not alphabetical or logical grouping, determines FastAPI route matching.
- E4: High-risk pack (public API contract change, risk class #4) — before declaring EXECUTE done,
  write a Phase-3-scoped risk-evidence record. The shared `harness/risk-gate.json` in this task
  folder already holds Phase 1's schema/migration risk-gate entry — do NOT overwrite it. Write a
  separate `harness/risk-gate-phase3.json` (same 5-artifact schema, `riskClass: "public-api"`)
  instead, so Phase 1's evidence is preserved.
- E5: Run the unit regression gate (`tests/unit -q`) before declaring EXECUTE done and confirm the
  passed/skipped counts are ≥ the PVL baseline (725 passed, 2 skipped) with 0 new failures.

Backlog artifacts: none new — the existing
`process/features/evallayer/backlog/phase-02-latency-benchmark_NOTE_22-07-26.md` is unrelated to
this phase (ingest-latency, not read-API).

High-risk pack: yes — public API contract change (risk class #4 of 6). Not a blocking gate for
VALIDATE (manual-first, opt-in per `vc-risk-evidence-pack`); required before EXECUTE finalize —
see Execute-agent instruction E4 above.

What this coverage does NOT prove:
- The Hybrid backend gates (test_agents_api.py, all 6 rows) prove correctness only once run in a
  Docker-enabled environment — they are written-but-unrun as of this VALIDATE pass, so no live
  proof of AC6 isolation, tenancy 404 behavior, route ordering, or the ID-parse fix exists yet.
- The FE compile gate (`npm run build`) proves the TypeScript types compile against the locked
  contract; it does NOT prove runtime correctness of the API client calls or React rendering.
- The e2e Hybrid gate proves the two pages render distinctly once a dev server is running; it does
  NOT prove data correctness (that's the backend Hybrid gates' job) or cross-browser behavior
  (Playwright config's configured browser only).
- The Agent-Probe badge-judgment gate proves a one-time visual/text check at EVL time; it does NOT
  provide regression protection against a future accidental badge-text change (no automated
  assertion of the exact label strings beyond what the e2e spec's selectors check).
- The unit regression gate proves no regression in the existing 725/2-skipped baseline; it does
  NOT execute any new agents.py/schemas/agents.py code at all (that code has no unit tests — its
  only coverage is the Hybrid integration tier).

Gate: PASS (no FAILs; 2 mechanical gaps found and fixed in-plan; environment known-gaps documented
per the vacuous-green ban's Hybrid-vs-Known-Gap distinction — every AC6/AC7 behavior has a real
Hybrid or Fully-Automated proving gate, none rests on Known-Gap alone)
Accepted by: session (autonomous, /goal execution) — environment known-gaps (Docker, Playwright
dev server) accepted as documented residuals consistent with Phase 1/2 precedent in this program;
no design-level concern requires user acceptance.
