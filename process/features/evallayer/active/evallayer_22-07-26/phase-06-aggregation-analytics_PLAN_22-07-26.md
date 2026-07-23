---
name: plan:evallayer-phase-06-aggregation-analytics
description: "EvalLayer — Phase 06: Aggregation + GEO/AEO analytics (vendor breakdown, page-read trends, verification-method split)"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-06
---

# Phase 06 — Aggregation + GEO/AEO Analytics

**Program:** evallayer
**Umbrella plan:** process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md
**Phase status:** ⏳ PLANNED (design locked — supplement 22-07-26)
**Report destination:** process/features/evallayer/active/evallayer_22-07-26/phase-06-aggregation-analytics_REPORT_22-07-26.md

---

## Purpose

Build a read-only aggregation service over `AgentVisit` rows (never touching Visitor/Event —
SPEC AC2) and three FIXED dashboard cards — vendor breakdown, page-read trends, and a
verification-method split — added below the existing Phase 3 `/stats` KPI row on the agents
dashboard page. This is deliberately simpler than the stub's original draggable-widget-system
Step B (see "KISS Simplification" below): fixed cards reuse existing Card/EmptyState/ErrorBanner
components and the `traffic-fit-card.tsx` stacked-bar pattern instead of a new draggable-widget
system with its own localStorage layout key.

True daily "agent visits over time" (a real time-series, requiring a new append-only rollup
table) is deferred to backlog — see `phase-06-daily-timeseries_NOTE_22-07-26.md`.

---

## KISS Simplification (supersedes original stub wording)

The original phase stub's Step B called for cloning `visitor-widgets.tsx`/`kpi-strip.tsx` with a
draggable widget system and a distinct `beam_agent_widgets_v1` localStorage key. That is dropped.
AC11 only requires vendor-breakdown + page-read-trends surfaced somewhere on the dashboard — it
does not require draggability or persisted layout. Fixed cards satisfy AC11 with far less surface
area and no new persistence/localStorage concern. If a future program wants draggable agent
widgets, that is a new backlog item, not part of this phase.

---

## Entry Gate

- Phase 3 exit gate passed (agent-visit read API/dashboard tab exists — confirmed:
  `apps/api/routers/agents.py` has `/{site_id}`, `/{site_id}/stats`, `/{site_id}/{agent_visit_id}`,
  and `apps/web/src/app/dashboard/agents/page.tsx` exists).
- Phase 4 exit gate passed (confidence/verification_method field exists — confirmed:
  `AgentVisit.verification_method` in `apps/api/models/agent_visit.py`).
- Parallel-safe with Phase 5 — disjoint blast radius (aggregation/analytics vs.
  company-resolution/outreach).

---

## Blast Radius

- `apps/api/services/agent_aggregator.py` (new)
- `apps/api/routers/agents.py` (add one new endpoint — no existing endpoint modified)
- `apps/api/schemas/agents.py` (add 2 new schemas — no existing schema modified)
- `apps/web/src/lib/api-types.ts` (add 2 new interfaces)
- `apps/web/src/lib/api.ts` (add 1 new client method)
- `apps/web/src/app/dashboard/agents/page.tsx` (append 3 fixed cards below existing KPI row)
- `tests/unit/test_agent_aggregator.py` (new)
- `process/features/evallayer/backlog/phase-06-daily-timeseries_NOTE_22-07-26.md` (new — backlog)

No new table, no migration, no Celery/scheduler task. Computed on-the-fly per request — cheap
because `agent_visits` is a small rollup table (one row per site/vendor/token tuple) and
`page_paths` is capped ~50 entries per row (Phase 2 ingest wiring cap).

---

## Implementation Checklist

### Step A — Aggregation service (pure + read-only split, mirrors `timeseries.py` precedent)

- [ ] A1. Create `apps/api/services/agent_aggregator.py` with
      `async def fetch_agent_visit_rows(db: AsyncSession, site_id: str) -> list[dict]`:
      - SELECTs ONLY from `AgentVisit` filtered by `site_id` — NEVER joins or queries
        `Visitor`/`Event` (SPEC AC2 boundary; regression-critical, must be explicitly tested, not
        assumed).
      - Selects `vendor`, `visit_count`, `page_paths`, `verification_method` columns only.
      - Returns `list[dict]` (not ORM rows) so `aggregate_agent_analytics` (Step A2) stays pure
        and DB-independent, matching the `compute_timeseries` / `build_series` split in
        `services/timeseries.py`.
- [ ] A2. Add `def aggregate_agent_analytics(rows: list[dict], top_n: int = 10) -> dict` to the
      same file — PURE, no DB, unit-testable in isolation:
      - `by_vendor: dict[str, int]` — sum of `visit_count` grouped by `vendor`.
      - `top_pages: list[dict]` — for each distinct path appearing in any row's `page_paths`, sum
        `visit_count` of every row containing that path; sort descending by count; take the top
        `top_n` (default 10); each entry is `{"path": str, "count": int}`.
      - `by_verification: dict[str, int]` — sum of `visit_count` grouped by `verification_method`.
      - Edge cases the function must handle correctly (see Step C fixture): empty `rows` → all
        three fields empty/zero; tied `top_pages` counts → stable order (input order on ties);
        fewer distinct paths than `top_n` → return all of them, no padding.

### Step B — Endpoint + schemas

- [ ] B1. Add to `apps/api/schemas/agents.py` (append — do not modify existing classes):
      ```python
      class TopPageEntry(BaseModel):
          path: str
          count: int

      class AgentAnalyticsResponse(BaseModel):
          by_vendor: dict[str, int]
          top_pages: list[TopPageEntry]
          by_verification: dict[str, int]
      ```
      Plain `BaseModel` (not `from_attributes=True`) — built from the aggregation dict returned by
      `aggregate_agent_analytics`, not directly from an ORM row.
- [ ] B2. Add `GET /{site_id}/analytics` to `apps/api/routers/agents.py`:
      - **Route-ordering trap (mandatory):** register this route BEFORE the existing
        `/{site_id}/{agent_visit_id}` catch-all (i.e. insert it directly after the existing
        `/{site_id}/stats` handler, same file position class). FastAPI matches path routes in
        registration order — `/analytics` would otherwise be swallowed by the `{agent_visit_id}`
        path-param route, exactly the sharp edge the existing `/stats` docstring already calls
        out.
      - First line: `await _verify_site_access(db, site_id, user)` (same 404-not-403 pattern as
        every other agents.py endpoint — never leak cross-tenant existence).
      - Calls `fetch_agent_visit_rows` then `aggregate_agent_analytics`, returns
        `AgentAnalyticsResponse(**result)`.
      - Do NOT touch the existing `/{site_id}/stats` endpoint (Phase 3) — it stays as-is; this is
        an additive endpoint only.

### Step C — Correctness fixture (unit, no Docker)

- [ ] C1. `tests/unit/test_agent_aggregator.py` — synthetic `AgentVisit`-shaped dict rows across
      multiple vendors with overlapping `page_paths`:
      - Assert `by_vendor` sums correctly per vendor.
      - Assert `top_pages` ranking + counts are correct when paths overlap across rows.
      - Assert `by_verification` sums correctly per verification method.
      - Edge cases: empty rows list; tied counts; fewer than `top_n` distinct paths.
- [ ] C2. AC2 isolation unit test (same file or a dedicated test): assert the compiled SQL
      `select()` statement built inside `fetch_agent_visit_rows` references only `agent_visits`
      and never `visitors` or `events` — inspect via `str(query)` substring check (mirrors the
      existing AC6 pattern in `list_agents`'s inline comment). This is the regression-critical
      isolation guarantee called out in the phase's Blockers section.
- [ ] C3. **(Added at VALIDATE — closes the route-ordering CONCERN)** Route-registration-order
      unit test, same file, Fully-Automated, zero Docker/DB dependency (route objects are built at
      import time): import `apps.api.routers.agents` and assert
      `[r.path for r in router.routes].index("/{site_id}/analytics") <
      [r.path for r in router.routes].index("/{site_id}/{agent_visit_id}")`. This mechanically
      proves the Step B2 route-ordering trap is closed instead of relying solely on the
      Docker-gated Hybrid `/analytics` endpoint e2e test (which cannot run in this sandbox).

### Step D — Frontend contract + fixed cards

- [ ] D1. `apps/web/src/lib/api-types.ts` — add, matching the backend schema field-for-field:
      ```typescript
      export interface TopPageEntry {
        path: string;
        count: number;
      }

      export interface AgentAnalytics {
        by_vendor: Record<string, number>;
        top_pages: TopPageEntry[];
        by_verification: Record<string, number>;
      }
      ```
- [ ] D2. `apps/web/src/lib/api.ts` — add `getAgentAnalytics(siteId: string)` mirroring the
      existing `getAgentStats` method exactly (same request pattern, same auth handling); export
      `AgentAnalytics`/`TopPageEntry` alongside the other Agent exports at the bottom of the file.
- [ ] D3. `apps/web/src/app/dashboard/agents/page.tsx` — append below the existing Phase 3 KPI
      row (do not modify the existing `stats` query or table):
      - `useQuery(["agent-analytics", siteId], () => api.getAgentAnalytics(siteId), { enabled: !!siteId })`.
      - **Vendor-breakdown card** — reuse `traffic-fit-card.tsx`'s hand-rolled stacked-bar pattern
        (no new Recharts dependency) keyed by vendor instead of country.
      - **Page-read-trends card** — ranked list/table of `top_pages` (`path` + `count`).
      - **Verification-method stat row** — small inline stat row from `by_verification` (cut
        first if scope needs to trim — optional, lowest priority of the three).
      - Reuse existing `Card`/`EmptyState`/`ErrorBanner` components (already imported patterns in
        this codebase) for loading/empty/error states — no new UI primitives.
      - Explicitly NOT: draggable widgets, a new localStorage key, `PeriodToggle` (no time-window
        selector — this is a snapshot, not a series).

---

## Exit Gate

```bash
.venv/bin/python -m pytest tests/unit/test_agent_aggregator.py -m unit -q
# Expected: all pass — by_vendor/top_pages/by_verification correctness + AC2 isolation +
# route-ordering assertion (C3) all green
```

- AC11 passes (vendor-breakdown + page-read-trends surfaced and correct against synthetic fixture).
- AC2 isolation assertion passes (aggregation query never touches Visitor/Event).
- Route-ordering assertion passes (Step C3 — added at VALIDATE).
- Phase report written to report destination above.

---

## Blockers That Would Justify BLOCKED Status

- Phase 3 or Phase 4 exit gates not yet passed. (Resolved this supplement — both confirmed passed.)
- Aggregation logic accidentally merges agent rollups into human-visitor tables (regression risk
  against SPEC AC2 — must be explicitly tested via Step C2, not assumed safe).

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [x] 1. RESEARCH — research-agent: prior phase reports read; test context loaded; plan drift checked
- [x] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written (fixed cards over
      draggable widgets — see "KISS Simplification")
- [x] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated with exact locked design
      (this supplement, 22-07-26)
- [x] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md` — Gate: PASS (2026-07-22)
- [ ] 5. EXECUTE — all checklist items done; per-section test gates run and green
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** Regression risk against human-data isolation
guardrail (AC2) — VALIDATE may never be skipped for this phase.

---

## Touchpoints

- `apps/api/services/agent_aggregator.py` (new)
- `apps/api/routers/agents.py` (add endpoint — additive only)
- `apps/api/schemas/agents.py` (add schemas — additive only)
- `apps/web/src/lib/api-types.ts` (add interfaces — additive only)
- `apps/web/src/lib/api.ts` (add client method — additive only)
- `apps/web/src/app/dashboard/agents/page.tsx` (append cards — additive only)
- `tests/unit/test_agent_aggregator.py` (new)

---

## Public Contracts

- New endpoint: `GET /api/v1/agents/{site_id}/analytics` → `AgentAnalyticsResponse`. Additive —
  no existing `/agents` contract (list, stats, detail) changes shape or behavior.
- No change to `/visitors` aggregation contract.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `by_vendor`/`top_pages`/`by_verification` correctness over synthetic multi-vendor, overlapping-page fixture — `.venv/bin/python -m pytest tests/unit/test_agent_aggregator.py -m unit -q` | Fully-Automated | AC11 |
| Edge cases (empty rows, tied counts, fewer than top_n paths) — same test file | Fully-Automated | AC11 |
| AC2 isolation — compiled query never references `visitors`/`events`, only `agent_visits` — same test file | Fully-Automated | AC2 |
| Full regression, no new failures vs 778-test baseline — `.venv/bin/python -m pytest tests/unit -q` | Fully-Automated | AC2 (no regression to existing human-data aggregation) |
| FE contract compiles — `cd apps/web && npm run build` | Fully-Automated | AC11 (analytics cards ship without build breakage) |
| `/analytics` endpoint end-to-end (real DB, multi-tenant 404 check) | Hybrid — requires Docker Postgres; precondition: `infra/docker-compose.yml` stack up | AC11, AC2 |
| Analytics cards render on dashboard (loose e2e, env-gated per flaky-e2e rules in `tests/all-tests.md`) | Hybrid — requires dev server + browser | AC11 |
| Route registration order — `/analytics` before `/{agent_visit_id}` catch-all (import-time route list check, no Docker/DB) — same test file (Step C3) | Fully-Automated | AC11, AC2 (route-ordering trap named in Step B2) |

---

## Test Infra Improvement Notes

(none identified yet)

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/evallayer_22-07-26/phase-06-aggregation-analytics_PLAN_22-07-26.md`
- Last completed step: Phase Loop Progress Step 4 (PVL) — Gate: PASS (2026-07-22)
- Validate-contract status: written (2026-07-22), `generated-by: inner-pvl: phase-6`, Gate: PASS
- Supporting context files loaded: `evallayer_SPEC_22-07-26.md` (AC2, AC11), umbrella plan Hard
  safety constraints, `apps/api/routers/agents.py`, `apps/api/schemas/agents.py`,
  `apps/api/models/agent_visit.py`, `apps/api/services/timeseries.py` (pure-split precedent),
  `apps/web/src/app/dashboard/agents/page.tsx`, `apps/web/src/components/traffic-fit-card.tsx`
  (stacked-bar precedent), `apps/web/src/lib/api.ts`, `apps/web/src/lib/api-types.ts`
- Next step: spawn `vc-execute-agent` for Phase Loop Progress Step 5 (EXECUTE) — this is the FINAL
  phase of the evallayer program; EXECUTE here also closes out the whole-program AC2/AC10
  regression posture end-to-end.

---

## Inner Loop Refresh Note (22-07-26)

Full supplement — Purpose, KISS Simplification (new), Entry Gate, Blast Radius, Implementation
Checklist (A/B/C/D fully rewritten with exact code-shape detail), Exit Gate, Touchpoints, Public
Contracts, Verification Evidence, Resume and Execution Handoff all updated. Locked design:
read-only pure-split aggregation service (no Celery task, no new table) + additive `/analytics`
endpoint (route-ordering trap noted) + 3 fixed dashboard cards (KISS simplification of original
draggable-widget stub). Backlog note written for true daily time-series
(`phase-06-daily-timeseries_NOTE_22-07-26.md`). Step 4 (PVL) must re-run against this updated plan.

---

## Validate Contract

Status: PASS
Date: 22-07-26
date: 2026-07-22
generated-by: inner-pvl: phase-6

Parallel strategy: parallel-subagents
Rationale: Signal score 2/7 (S4 phase-program classification present; S7 8-file blast radius
present) → MEDIUM. Fan-out ran as 4 Layer 1 dimension checks + 4 Layer 2 per-section feasibility
checks (Step A/B/C/D), no cross-agent coordination needed — all sections are read-only-analytics
with disjoint edit targets and no interdependency, so independent parallel review (not agent-team)
was correct.

Plan updates applied:
- P1: Added Step C3 — Fully-Automated, zero-Docker/DB route-registration-order unit test
  (`[r.path for r in router.routes]` index comparison at import time), closing the Step B2
  route-ordering trap with a real automated gate instead of relying solely on the Docker-gated
  Hybrid `/analytics` endpoint e2e test. Verification Evidence table and Exit Gate updated to
  match.

Execute-agent instructions:
- E1: Register `GET /{site_id}/analytics` directly after the existing `get_agent_stats` handler
  (currently ends at line 100 in `apps/api/routers/agents.py`) and before the
  `/{site_id}/{agent_visit_id}` catch-all (currently starts at line 102). Confirm final line
  numbers before insertion — do not assume they are unchanged if other edits shift them.
- E2: `fetch_agent_visit_rows` must SELECT only `AgentVisit.vendor`, `.visit_count`,
  `.page_paths`, `.verification_method` filtered by `site_id` — no join, no reference to
  `Visitor`/`Event` ORM classes anywhere in the function body. Step C2's compiled-SQL substring
  assertion is the mechanical proof; do not treat manual review as sufficient on its own.
- E3: `aggregate_agent_analytics` must remain a pure function (rows in, dict out) — no `db`
  parameter, no `await`, no I/O — so it stays independently unit-testable per the
  `timeseries.py` `build_series`/`compute_timeseries` split precedent.
- E4: Do not modify the existing `get_agent_stats` handler, `AgentOut`/`AgentDetailOut`/
  `AgentListResponse`/`AgentStatsResponse` schema classes, or the existing `stats` useQuery/table
  in `page.tsx` — this phase is additive-only in every touched file.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC11 | `by_vendor`/`top_pages`/`by_verification` correctness over synthetic multi-vendor, overlapping-page fixture, incl. edge cases (empty rows, tied counts, fewer than top_n paths) | Fully-Automated | `.venv/bin/python -m pytest tests/unit/test_agent_aggregator.py -m unit -q` | B |
| AC2 | Compiled `select()` in `fetch_agent_visit_rows` references only `agent_visits`, never `visitors`/`events` (`str(query)` substring check) | Fully-Automated | same test file (Step C2) | B |
| AC11, AC2 | Route registration order — `/analytics` before `/{agent_visit_id}` catch-all (import-time route list check) | Fully-Automated | same test file (Step C3 — added at VALIDATE) | B |
| AC2 (no regression) | Full unit regression, no new failures vs 778-test baseline | Fully-Automated | `.venv/bin/python -m pytest tests/unit -q` | A |
| AC11 (build) | FE contract compiles (TS types match Pydantic schema field-for-field) | Fully-Automated | `cd apps/web && npm run build` | A |
| AC11, AC2 | `/analytics` endpoint end-to-end — real DB, multi-tenant 404 check | Hybrid — precondition: `infra/docker-compose.yml` stack (Postgres) up | `.venv/bin/python -m pytest tests/integration/test_agents_api.py -k analytics -m integration -q` | D |
| AC11 | Analytics cards render on dashboard (loose e2e) | Hybrid — precondition: dev server + browser, env-gated per `tests/all-tests.md` flaky-e2e rules | `npm run --prefix apps/web dev & npx playwright test apps/web/e2e/agents.spec.ts --config=apps/web/playwright.config.ts` | D |

gap-resolution legend:
- A — proven now (gate passes in this cycle)
- B — fixed in this plan (gate added by this plan's checklist)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

C-4 reconciliation: strategy column carries only Fully-Automated/Hybrid — no Known-Gap strategy
value used; the 2 Hybrid rows' D-resolution is an environment residual (Docker/browser
unavailable in this sandbox), not an unproven behavior.

Legacy line form:
- Aggregation correctness + AC2 isolation + route ordering: Fully-automated:
  `.venv/bin/python -m pytest tests/unit/test_agent_aggregator.py -m unit -q`
- Full regression: Fully-automated: `.venv/bin/python -m pytest tests/unit -q`
- FE build: Fully-automated: `cd apps/web && npm run build`
- Endpoint e2e: hybrid: `pytest tests/integration/test_agents_api.py -k analytics -m integration -q` + precondition: Docker Postgres up
- Dashboard card render: hybrid: Playwright run + precondition: dev server up
- Live-provider anything: N/A — no new external call in this phase

Dimension findings:
- Infra fit: PASS — no container/infra/worker surface touched; standard FastAPI route +
  existing `get_db` dependency injection; no port/service changes.
- Test coverage: PASS — AC11 and AC2 both get Fully-Automated, Docker-free coverage (Step
  C1/C2/C3); the 2 remaining gates are Hybrid and env-gated only, consistent with every prior
  phase in this program.
- Breaking changes: PASS — new endpoint additive only; no existing endpoint, schema, or FE query
  modified; no schema/migration/Celery surface touched (confirmed by direct file/model reads).
- Security surface: PASS — `_verify_site_access` is the first line of the new handler (404-not-403
  tenancy pattern preserved); no new secrets, no new external call, no PII exposure beyond
  existing `/stats`/`/list` surfaces (aggregate vendor/page-path counts only).
- Section A (aggregation service): PASS — mechanically feasible against the real `AgentVisit`
  model and the `timeseries.py` pure-split precedent; no gaps; no conflicts.
- Section B (endpoint + schemas): PASS (after P1 plan update) — route-insertion point confirmed
  real (line 100/102 in current file); schema append confirmed collision-free against existing
  4 classes; route-ordering risk closed by Step C3.
- Section C (correctness fixture): PASS — `str(query)` compiled-SQL substring technique confirmed
  mechanically valid (SQLAlchemy Core compiles without a live connection); stronger than the
  existing AC6 precedent (which required Docker).
- Section D (frontend contract + fixed cards): PASS — `AgentAnalyticsResponse` Pydantic shape and
  `AgentAnalytics` TS interface confirmed field-for-field identical
  (`dict[str,int]`↔`Record<string,number>`, `list[TopPageEntry]`↔`TopPageEntry[]`); existing
  `stats` query/table confirmed untouched by the plan's additive-only design; `getAgentStats`
  mirror pattern confirmed real at `api.ts:476`.

Open gaps: none blocking. 2 environment known-gaps (Docker Postgres for the endpoint integration
test; dev server + browser for the Playwright e2e) — same pattern as Phases 1/2/3/4/5/7, does not
block PASS or (once closed) VERIFIED.

What this coverage does NOT prove:
- The Fully-Automated unit suite (C1/C2/C3) does not prove real end-to-end request/response
  behavior against a live Postgres connection, real multi-tenant HTTP round-trip, or FastAPI
  dependency-injection wiring at runtime — only the Hybrid integration test proves that, and it
  is env-gated in this sandbox.
- The FE build check proves the TS/Pydantic contract compiles; it does not prove the cards render
  correctly, handle loading/empty/error states visually, or that the stacked-bar reuse from
  `traffic-fit-card.tsx` looks right at runtime — only the Hybrid Playwright e2e (also env-gated)
  covers that, and even then only at the "loose e2e" tier, not full visual regression.
- No coverage proves behavior under concurrent requests or with a very large `page_paths`
  cardinality beyond the ~50-entry cap already enforced upstream in Phase 2's ingest wiring — out
  of scope for this phase's blast radius.

Gate: PASS (no FAILs; 0 CONCERNs after in-plan fix; 2 environment known-gaps carried, consistent
with program precedent, non-blocking)
Accepted by: session (autonomous, /goal execution) — environment known-gaps (Docker Postgres,
Playwright dev server) accepted per the same precedent already established across every prior
phase (1, 2, 3, 4, 5, 7) in this program; no user-facing CONCERN required acceptance since all
developed behavior has at least one Fully-Automated or Hybrid proving gate (vacuous-green ban
satisfied).
