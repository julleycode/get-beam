---
phase: agents-flag-empty-state
date: 2026-08-04
status: COMPLETE
feature: evallayer
plan: process/features/evallayer/active/agents-flag-empty-state_04-08-26/agents-flag-empty-state_PLAN_04-08-26.md
---

# EXECUTE Exit Summary — Agents Flag-Aware Empty State

## What Was Done

1. `apps/api/schemas/agents.py:41` — added `detection_enabled: bool` to `AgentStatsResponse`.
2. `apps/api/routers/agents.py:157` — `get_agent_stats` now returns
   `detection_enabled=settings.agent_detection_enabled` (`settings` already imported at line 9).
3. `apps/web/src/lib/api-types.ts:408` — added optional `detection_enabled?: boolean`.
4. `apps/web/src/app/dashboard/agents/page.tsx:318` — empty-state `description` is now a ternary on
   `stats?.detection_enabled === false` (flag-off copy) vs otherwise (no-visits-yet copy).
5. `tests/unit/test_agent_stats_flag.py` (new) — 2 tests, both flag states, mocked DB + auth
   overrides per Execute-Agent Instruction E1 (`test_agent_profile.py` auth pattern) and E2
   (ordered `execute` responses: scalar total, then by-vendor rows).

## What Was Skipped or Deferred

Nothing. All 5 checklist items complete.

## Test Gate Outcomes

| Gate | Strategy | Result |
|---|---|---|
| `.venv/bin/python3.11 -m pytest tests/unit/test_agent_stats_flag.py -m unit -q` (AC1a/AC1b) | Fully-Automated | PASS — 2 passed in 1.16s |
| `cd apps/web && npx tsc --noEmit` (AC2/AC5/AC6) | Fully-Automated | PASS — no output, no errors |
| Empty-state ternary read (AC3) | Agent-Probe | PASS — both branches render the intended strings; `stats` is not gated by `stats &&` at the call site so optional chaining is correct |
| Additive back-compat (AC6) | grep | PASS — `AgentStatsResponse(...)` constructed in exactly one place (`routers/agents.py:153`) |

## Plan Deviations

None.

## Test Infra Gaps Found

None new. Known residuals carried from the validate-contract: no integration-tier coverage against
a real Postgres for this read-only aggregate; no browser-level render assertion (Agent-Probe only);
the old/undeployed-backend absent-field path is inferred from Pydantic/TS optional semantics, not
empirically probed.

## Closeout Packet

- Selected plan: `process/features/evallayer/active/agents-flag-empty-state_04-08-26/agents-flag-empty-state_PLAN_04-08-26.md`
- Finished: all 5 checklist items; all fully-automated gates green.
- Verified: backend field both flag states; frontend typecheck; single-construction-site back-compat.
- Unverified: live browser render; real-Postgres stats path.
- Remaining: EVL confirmation run + UPDATE PROCESS archival.
- Classification: **Ready for UPDATE PROCESS archival** (after EVL).

## Forward Preview

- **Test Infra Found:** `tests/unit/test_agent_profile.py` is the canonical mirror for
  `get_current_user` + `_verify_site_access` override tests; `.venv/bin/python3.11 -m pytest` is
  mandatory (broken `.venv/bin/pytest` shebang).
- **Blast Radius Changes:** none beyond the 5 planned files.
- **Commands to Stay Green:** `.venv/bin/python3.11 -m pytest tests/unit/test_agent_stats_flag.py -m unit -q`;
  `cd apps/web && npx tsc --noEmit`.
- **Dependency Changes:** none.
