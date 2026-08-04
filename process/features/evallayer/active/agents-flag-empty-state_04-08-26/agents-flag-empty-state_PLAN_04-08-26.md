---
name: plan:agents-flag-empty-state
description: "Additive detection_enabled field on agent stats + branched empty-state copy on /dashboard/agents"
date: 04-08-26
feature: evallayer
---

# Agents Flag-Aware Empty State — Plan

**Date**: 04-08-26
**Complexity**: Simple
**Status**: ⏳ PLANNED

## Phase Completion Rules

A phase is NOT complete until:

1. **Integration Test** - Works with other system pieces
2. **Manual Test** - User can perform the action
3. **Data Verification** - Database/state changes confirmed
4. **Error Handling** - Failure cases handled gracefully
5. **User Confirmation** - User says "it works"

Status meanings:
- ⏳ PLANNED - Not started
- 🔨 CODE DONE - Written but not E2E tested
- 🧪 TESTING - Currently being tested
- ✅ VERIFIED - Tested AND confirmed working
- 🚧 BLOCKED - Has issues

After each phase, document:
- [ ] What was tested manually
- [ ] Data verified in DB (show query + result)
- [ ] Errors encountered and fixed
- [ ] User confirmation received

## Overview

`/dashboard/agents` always shows the same empty-state copy ("Agent detection must be enabled...")
regardless of whether `AGENT_DETECTION_ENABLED` is actually on or off. This is confusing once the
flag is flipped on but there are simply no agent visits yet. This plan adds an additive
`detection_enabled: bool` field to the existing `GET /{site_id}/stats` response, sourced from
`settings.agent_detection_enabled`, and branches the frontend empty-state message on it.

Fully mechanical — no design decisions, no INNOVATE needed.

## Goals

- Backend: `AgentStatsResponse` carries `detection_enabled: bool`, populated in `get_agent_stats`.
- Frontend: `AgentStatsResponse` type in `api-types.ts` gains the same field (optional, for
  back-compat with an old deployed backend).
- Frontend: the agents page empty-state description branches on `stats?.detection_enabled`.
- Backend unit test covers both flag states.

## Non-Goals

- No change to `AGENT_DETECTION_ENABLED` default (stays `False`).
- No new endpoint, no schema/DB migration, no auth change.
- No change to `/analytics` or any other agents route.

## Touchpoints

| File | Change |
|---|---|
| `apps/api/schemas/agents.py` | Add `detection_enabled: bool` field to `AgentStatsResponse` (line ~37-40) |
| `apps/api/routers/agents.py` | In `get_agent_stats` (line ~124-157), populate `detection_enabled=settings.agent_detection_enabled` in the returned `AgentStatsResponse(...)` |
| `apps/web/src/lib/api-types.ts` | Add `detection_enabled?: boolean` to the `AgentStatsResponse` interface (line ~404-407) |
| `apps/web/src/app/dashboard/agents/page.tsx` | Branch the `<EmptyState description=...>` (line ~318) on `stats?.detection_enabled` |
| `tests/unit/test_agent_stats_flag.py` (new) | Unit test: `detection_enabled` reflects both `True`/`False` settings states |

`settings` is already imported in `apps/api/routers/agents.py` (line 9: `from apps.api.config import
settings`) — no new import needed.

## Public Contracts

- `GET /api/v1/agents/{site_id}/stats` response gains one additive boolean field. This is a
  backward-compatible schema widening (existing consumers ignore unknown fields; Pydantic model
  additions are additive by default). No existing field changes shape or meaning.
- No new route, no new request parameter, no auth/permission change.

## Blast Radius

- 1 backend schema file (1 field added)
- 1 backend router file (1 line added inside an existing handler)
- 1 frontend type file (1 field added, optional)
- 1 frontend page file (1 conditional branch, ~4 lines)
- 1 new backend unit test file
- Risk class: none of the high-risk classes (no auth/billing/schema-migration/public-API-breaking-change/deploy/secrets surface touched) — this is a pure additive read-only field.

## Acceptance Criteria

1. `GET /api/v1/agents/{site_id}/stats` response includes `detection_enabled` matching
   `settings.agent_detection_enabled` exactly (both `True` and `False` cases).
2. `apps/web/src/lib/api-types.ts` `AgentStatsResponse` type includes `detection_enabled?: boolean`.
3. `apps/dashboard/agents` page empty-state description reads the flag-off copy when
   `stats.detection_enabled === false`, and the flag-on/no-visits copy otherwise (`true` or
   `undefined`).
4. `tests/unit/test_agent_stats_flag.py` passes for both flag states.
5. `cd apps/web && npx tsc --noEmit` passes with no new type errors.
6. No existing `/stats` or `/analytics` consumer breaks (additive-only field change).

## Implementation Checklist

1. **Backend schema** — in `apps/api/schemas/agents.py`, add `detection_enabled: bool` as a new
   field on `AgentStatsResponse` (after `by_vendor: dict[str, int]`).
2. **Backend handler** — in `apps/api/routers/agents.py`, `get_agent_stats` (~line 153), add
   `detection_enabled=settings.agent_detection_enabled` to the `AgentStatsResponse(...)` return
   call.
3. **Frontend type** — in `apps/web/src/lib/api-types.ts`, add `detection_enabled?: boolean;` to
   the `AgentStatsResponse` interface (optional — tolerates an old backend that hasn't deployed
   step 1-2 yet).
4. **Frontend branch** — in `apps/web/src/app/dashboard/agents/page.tsx`, replace the static
   `description="Agent detection must be enabled on the backend (AGENT_DETECTION_ENABLED)..."`
   string (line ~318, inside the `agents.length === 0` `<EmptyState>` block) with a conditional:
   - `stats?.detection_enabled === false` → `"Agent detection must be enabled on the backend (AGENT_DETECTION_ENABLED) before visits from GPTBot, ClaudeBot, PerplexityBot and others appear here."`
   - otherwise (`true` or `undefined` — old backend / stats not yet loaded) → `"No agent visits yet — once AI agents like GPTBot or ClaudeBot fetch your pages they'll appear here."`

   The page already fetches stats via the existing `useQuery({ queryKey: ["agent-stats", siteId],
   queryFn: () => api.getAgentStats(siteId) })` at line 253-257 — reuse `stats` directly, no new
   request.
5. **Backend test** — create `tests/unit/test_agent_stats_flag.py` following the mocked-DB router
   pattern in `tests/unit/test_agent_fetch_beacon.py` (FastAPI app + `ASGITransport` +
   `app.dependency_overrides[get_db]` + mocked `AsyncSession`/`db.execute` results). Two test
   cases:
   - `agent_detection_enabled=True` (monkeypatch `apps.api.routers.agents.settings.agent_detection_enabled`) → response `detection_enabled is True`
   - `agent_detection_enabled=False` → response `detection_enabled is False`
   Mock `db.execute` to return a scalar `0` for the total-visits query and an empty iterable for
   the by-vendor query (mirror the existing `AsyncMock` pattern) — auth mocked via
   `app.dependency_overrides[get_current_user]` and site-access via monkeypatching
   `agents_router._verify_site_access` to a no-op, same pattern as the beacon test file.

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `tests/unit/test_agent_stats_flag.py` — `detection_enabled=True` when settings flag on | Fully-Automated | Backend correctly reflects `agent_detection_enabled=True` in stats response |
| `tests/unit/test_agent_stats_flag.py` — `detection_enabled=False` when settings flag off | Fully-Automated | Backend correctly reflects `agent_detection_enabled=False` in stats response |
| `cd apps/web && npx tsc --noEmit` | Fully-Automated | Frontend type change + page.tsx branch compile with no type errors |
| Manual read of rendered branch logic (Agent-Probe, optional) | Agent-Probe | Empty-state copy differs correctly between flag-on/flag-off given `stats.detection_enabled` — no live UI/browser harness required for this trivial ternary |

## Test Infra Improvement Notes

(none identified yet)

## Rollback Note

Purely additive field + a UI copy branch. Revert = `git revert` the single implementation commit.
No migration, no data written, no default-flag change — reverting is safe at any time with zero
data-loss risk.

## Verification Commands

```bash
# Backend — scoped unit test for the new/touched file
.venv/bin/python3.11 -m pytest tests/unit/test_agent_stats_flag.py -m unit -q

# Frontend — typecheck touched files
cd apps/web && npx tsc --noEmit
```

Repo gotchas (from `process/context/tests/all-tests.md` and memory):
- `.venv/bin/pytest` shebang is broken (points at a moved path) — always invoke via
  `.venv/bin/python3.11 -m pytest`, run from repo root.
- Unit lane assumes no local Redis on port 6379 — a stray container can self-poison db15 cache;
  not expected to matter here (no Redis touched) but note if flaky.
- ORM-constructing tests need `import apps.api.main` first if any raw ORM object construction is
  used — the beacon test pattern being mirrored already avoids this by using
  `app.dependency_overrides` + mocks rather than constructing ORM rows directly, so this plan's
  new test should not need it; add the import if a `InvalidRequestError` surfaces.

## Validate Contract

Status: PASS
Date: 04-08-26
date: 2026-08-04
generated-by: outer-pvl

Parallel strategy: sequential
Rationale: Score 1/7 (S7 — exactly 5 blast-radius files; no multi-package/schema/auth/high-risk
signals present). Full multi-agent Layer 1+2 fan-out scaled down per orchestrator instruction —
this validate pass was run as a single sequential feasibility check (spot-checked citations +
mirror-test-run + structural validator), not a parallel agent-team dispatch.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC1a | `GET /{site_id}/stats` returns `detection_enabled=True` matching `settings.agent_detection_enabled=True` | Fully-Automated | `tests/unit/test_agent_stats_flag.py::test_detection_enabled_true_reflects_settings` | A |
| AC1b | `GET /{site_id}/stats` returns `detection_enabled=False` matching `settings.agent_detection_enabled=False` | Fully-Automated | `tests/unit/test_agent_stats_flag.py::test_detection_enabled_false_reflects_settings` | A |
| AC2, AC5 | Frontend `AgentStatsResponse` type + `page.tsx` conditional branch compile with no new type errors | Fully-Automated | `cd apps/web && npx tsc --noEmit` | A |
| AC3 | Empty-state description text differs correctly between `detection_enabled === false` vs `true`/`undefined` | Agent-Probe | Manual read of the rendered ternary in `apps/web/src/app/dashboard/agents/page.tsx` (no live browser harness required for a 2-branch string ternary) | A |
| AC6 | No existing `/stats`/`/analytics` consumer breaks (additive-only field) | Fully-Automated (partial) | `cd apps/web && npx tsc --noEmit` proves type-level back-compat; confirmed via grep that `apps/web/src/lib/api.ts` is the only other `AgentStatsResponse`-typed consumer and only reads `total_visits`/`distinct_vendors` | A |

gap-resolution legend: A — proven now (gate passes in this cycle).

Failing stub (AC1a — `tests/unit/test_agent_stats_flag.py`):
```python
@pytest.mark.unit
async def test_detection_enabled_true_reflects_settings(monkeypatch):
    raise NotImplementedError("NOT IMPLEMENTED — TDD stub: detection_enabled=True reflects settings.agent_detection_enabled")
```

Failing stub (AC1b — `tests/unit/test_agent_stats_flag.py`):
```python
@pytest.mark.unit
async def test_detection_enabled_false_reflects_settings(monkeypatch):
    raise NotImplementedError("NOT IMPLEMENTED — TDD stub: detection_enabled=False reflects settings.agent_detection_enabled")
```

Legacy line form (retained for existing validate-contract consumers):
- Backend flag-response: Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_agent_stats_flag.py -m unit -q` | known-precondition: run from repo root, `.venv/bin/pytest` shebang is broken — always invoke via `.venv/bin/python3.11 -m pytest` (confirmed live against the mirror file `tests/unit/test_agent_fetch_beacon.py`, 19 passed in 0.68s, keyless, no Redis/PG).
- Frontend typecheck: Fully-automated: `cd apps/web && npx tsc --noEmit`
- Empty-state copy branch: agent-probe: read `page.tsx` conditional after EXECUTE and confirm both branches render the intended string.

Dimension findings:
- Infra fit: PASS — no container/runtime/deploy surface touched; pure additive field + one JSX conditional.
- Test coverage: PASS — `tests/unit/test_agent_fetch_beacon.py` confirmed live-green (19/19, keyless, 0.68s) as the general FastAPI-app-with-mocked-DB pattern. One correction to the plan's citation: for the specific "mock `get_current_user` + mock/no-op `_verify_site_access`" combination, the closer proven mirror is `tests/unit/test_agent_profile.py` (uses `app.dependency_overrides[get_current_user]` against the real `apps.api.main.app`, and drives `verify_site_access` via a `FakeSession` rather than monkeypatching it directly) — `test_agent_fetch_beacon.py`'s endpoint uses shared-secret auth, not `get_current_user`/`_verify_site_access`, so it never demonstrates that combination. See Execute-Agent Instruction E1 below; this does not block feasibility since `monkeypatch.setattr(agents_router, "_verify_site_access", AsyncMock())` is a mechanically valid technique regardless of citation.
- Breaking changes: PASS — confirmed via grep that `apps/web/src/lib/api.ts` (the API client) is the only other file referencing the `AgentStatsResponse` TS type; `page.tsx` only reads `total_visits`/`distinct_vendors`, both unchanged. Pydantic model field addition is additive-only server-side. No existing field changes shape or meaning.
- Security surface: PASS — no auth/billing/schema/secrets/trust-boundary surface touched; `detection_enabled` mirrors an existing non-secret boolean settings flag already readable via `/dashboard/agent-gateway` and other agent-detection UI surfaces.
- Section — Implementation Checklist (single Layer 2 section, SIMPLE plan): PASS
  - Mechanical feasibility: confirmed by direct file read — `AgentStatsResponse` at `apps/api/schemas/agents.py:37-40` (matches plan citation exactly), `get_agent_stats` handler + return call at `apps/api/routers/agents.py:124-157` (matches "~124-157"; return statement at 153-157), `settings` imported at `apps/api/routers/agents.py:9` (exact match, no new import needed), frontend `AgentStatsResponse` interface at `apps/web/src/lib/api-types.ts:404-407` (matches "~404-407" exactly), target `description=` string at `apps/web/src/app/dashboard/agents/page.tsx:318` inside the `agents.length === 0` `<EmptyState>` block (matches "~318" exactly), `stats` query already fetched at `page.tsx:253-257` and is NOT gated by `stats &&` at the empty-state call site (line 314) — so the plan's `stats?.detection_enabled` optional-chaining is correct (unlike the stats-cards block at line 277 which IS gated).
  - Gaps found: none beyond the test-mirror citation noted above (resolved via E1).
  - Conflicts found: none — `tests/unit/test_agent_stats_flag.py` does not already exist (confirmed via `ls`); no naming collision.
  - Highest-risk edit + mitigation: none of this plan's edits carry material risk (additive field, additive UI branch). If any risk exists it is the new test file's `db.execute` mock needing two distinct return shapes in one handler call sequence (`.scalar_one()` for the total-visits query, then a sync-iterable for the by-vendor query) — mitigate with `db.execute = AsyncMock(side_effect=[result_scalar, result_rows])`, ordered to match the two `await db.execute(...)` calls in `get_agent_stats`.

Execute-Agent Instructions:
- E1: When writing `tests/unit/test_agent_stats_flag.py`, use `tests/unit/test_agent_profile.py`'s auth pattern as the canonical reference for `app.dependency_overrides[get_current_user]` (not `test_agent_fetch_beacon.py`, which uses shared-secret auth and never touches `get_current_user`/`_verify_site_access`). The plan's proposed technique — `monkeypatch.setattr(agents_router, "_verify_site_access", AsyncMock(return_value=<Site-like stub or None>))` — remains valid and is the simpler of the two approaches for this trivial test; `test_agent_fetch_beacon.py` is still the correct reference for the FastAPI-app-with-mocked-`db.execute` scaffolding (its `_beacon_client`-style app/dependency_overrides/ASGITransport setup).
- E2: Order `db.execute` mock responses to match call order in `get_agent_stats` (total-visits query first, by-vendor query second) — a single `AsyncMock(return_value=...)` will return the same object to both calls and break the by-vendor iteration; use `side_effect=[...]`.

Open gaps: none

What this coverage does NOT prove:
- `tests/unit/test_agent_stats_flag.py` (AC1a/AC1b) proves the backend field reflects the settings flag with a mocked DB/session — it does NOT prove behavior against a real Postgres row set (no integration/hybrid tier exists for this trivial read-only aggregate; acceptable given zero migration/schema surface).
- `npx tsc --noEmit` (AC2/AC5/AC6) proves type-level compilation only — it does NOT prove the JSX renders the correct string at runtime in a browser; that residual is covered by the Agent-Probe row (AC3), which is a code-read judgment call, not a live-browser assertion (no Playwright leg is warranted for a 2-branch string ternary on an already-tested-elsewhere `<EmptyState>` component).
- No test proves the OLD/undeployed-backend back-compat path (`detection_enabled` absent from response JSON entirely) end-to-end against a real stale-backend response — this is inferred from Pydantic/TS optional-field semantics, not empirically probed. Low risk (single-service monorepo deploy, not independently versioned front/back).

Gate: PASS (no FAILs, no unresolved CONCERNs — one minor test-mirror-citation correction resolved via Execute-Agent Instruction E1)

## Autonomous Goal Block

SESSION GOAL: Add flag-aware empty-state copy to /dashboard/agents (additive detection_enabled field on GET /{site_id}/stats)
Charter + umbrella plan: N/A — single standalone plan (not a phase of process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md)
Autonomy: Standard /goal autonomous execution rules apply once EXECUTE begins — self-decide at V5-equivalent gates, hard-stop only on irreversible/outward-facing actions not covered by this contract.
Hard stop conditions / safety constraints:
- Do not change AGENT_DETECTION_ENABLED default (must stay False).
- Do not add a new endpoint, DB migration, or auth change — this plan is additive-field-only.
- Do not touch /analytics or any other agents route.
Next phase: EXECUTE: process/features/evallayer/active/agents-flag-empty-state_04-08-26/agents-flag-empty-state_PLAN_04-08-26.md
Validate contract: inline in plan (## Validate Contract section above)
Execute start: `.venv/bin/python3.11 -m pytest tests/unit/test_agent_stats_flag.py -m unit -q` (fully-auto) | `cd apps/web && npx tsc --noEmit` (fully-auto) | Agent-Probe: read page.tsx empty-state ternary post-edit | high-risk pack: no

## Resume and Execution Handoff

1. **Selected plan file path**: `process/features/evallayer/active/agents-flag-empty-state_04-08-26/agents-flag-empty-state_PLAN_04-08-26.md`
2. **Last completed phase or step**: PLAN written, not yet validated or executed.
3. **Validate-contract status**: pending (placeholder above).
4. **Supporting context files loaded**: `process/context/all-context.md`, `process/context/tests/all-tests.md`, `apps/api/schemas/agents.py`, `apps/api/routers/agents.py` (lines 1-180), `apps/api/config.py` (agent_detection_enabled), `apps/web/src/lib/api-types.ts` (AgentStatsResponse), `apps/web/src/app/dashboard/agents/page.tsx` (lines 245-330), `tests/unit/test_agent_fetch_beacon.py` (mocked-router test pattern reference).
5. **Next step for a fresh agent picking up mid-execution**: if EXECUTE has not started, run
   `ENTER VALIDATE MODE` first. If EXECUTE is in progress, resume at the first unchecked item in
   Implementation Checklist above and run the Verification Commands after each backend/frontend
   change.

---

Next: review this plan, then say **ENTER VALIDATE MODE** to proceed to plan validation (required before implementation).
