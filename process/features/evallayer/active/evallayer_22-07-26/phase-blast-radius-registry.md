---
name: plan:evallayer-blast-radius-registry
description: "EvalLayer program — single blast-radius coordination registry across all 8 phases"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: registry
---

# EvalLayer — Phase Blast-Radius Registry

One registry for the whole program. Each phase agent appends its own `## Phase N` section
before writing its full plan (or, if reconciled later, at VALIDATE time). Never overwrite —
append only. See `process/development-protocols/vc-system-behavior/11-phase-programs.md`
§Blast-radius registry for the write protocol and valid `status:` vocabulary.

---

## Phase 1

Plan: `process/features/evallayer/active/evallayer_22-07-26/phase-01-data-model-classifier_PLAN_22-07-26.md`

Blast radius (confirmed real, no collisions with any other phase at PVL time — verified
2026-07-22 against phase-00 (frontend-only, shipped) and phase-02 (events.py, bot_filter.py,
config.py) blast radii, which are disjoint from the files below):

- `apps/api/models/agent_visit.py` (new)
- `apps/api/migrations/versions/<hash>_add_agent_visits_table.py` (new; `down_revision = "b8f3c1d92a47"`, confirmed current head)
- `apps/api/services/agent_classifier.py` (new)
- `apps/api/main.py` (one new `# noqa: F401` import line — additive only)
- `tests/unit/test_agent_classifier.py` (new)
- `apps/api/services/bot_filter.py` — READ-ONLY reference, not modified this phase

status: DONE — EXECUTE + independent EVL both complete 2026-07-22; files created as claimed
(migration hash: d11b39a6c843); 3/4 gates GREEN (classifier 24/24, registration smoke, full
regression 716 passed/2 skipped/no regression); live-DB migration up/down/up cycle remains a
KNOWN-GAP (Docker unavailable in sandbox at both EXECUTE and EVL time) — close-the-gap command
recorded in the phase report. Phase classified 🔨 CODE DONE (not ✅ VERIFIED) in the umbrella
pending that gap.

---

## Phase 2

Plan: `process/features/evallayer/active/evallayer_22-07-26/phase-02-ingest-wiring_PLAN_22-07-26.md`

Blast radius (confirmed real, no collisions with any other phase — verified 2026-07-22 at PVL
against Phase 1's DONE entry above and Phase 3's planned blast radius, both disjoint from the
files below):

- `apps/api/routers/events.py` (modified — ingest hot path restructure)
- `apps/api/services/agent_visit_persistence.py` (new)
- `apps/api/config.py` (modified — new `agent_detection_enabled` flag)
- `tests/unit/test_agent_visit_persistence.py` (new)
- `tests/integration/test_events_ingest.py` (modified — extended)

No overlap with Phase 1 (`agent_visit.py`, migration, `agent_classifier.py`, `main.py`,
`test_agent_classifier.py` — all consumed read-only here) or Phase 3 (`agents.py`,
`schemas/agents.py`, `dashboard/agents/*`, `layout.tsx`, `api.ts`/`api-types.ts` — none touched
this phase).

status: DONE — EXECUTE + independent EVL both complete 2026-07-22. Gate: CONDITIONAL (accepted,
session/autonomous). EXECUTE shipped all 5 blast-radius files as claimed; EVL confirmed full unit
baseline GREEN (725 passed, 2 skipped — Phase 1 baseline was 716, +9, 0 regressions; classifier
24/24) and, in lieu of a live Docker run, a static safety review confirming all 3 declared safety
properties (agent branch hard-returns before the Event insert; flag-off is byte-identical to
pre-Phase-2 behavior; `persist_agent_visit` is fail-open — logs keys-only, rolls back, never
raises). Two Known-Gaps remain open and are NOT blockers to this DONE annotation (both
environment/tooling gaps, not design defects): (1) the 5 `TestAgentDetection` integration cases
(AC1-AC4 + flag-OFF) are collect-clean but unrun — no responsive Docker daemon in this sandbox at
either EXECUTE or EVL time; close command: `MOCK_EXTERNAL_APIS=true .venv/bin/python -m pytest
tests/integration/test_events_ingest.py -k "agent or datacenter" -m integration -q`; (2) AC5
(ingest latency benchmark) has no harness yet — backlog stub:
`process/features/evallayer/backlog/phase-02-latency-benchmark_NOTE_22-07-26.md`. Phase classified
🔨 CODE DONE (not ✅ VERIFIED) in the umbrella pending closure of both gaps. See phase plan's
Validate Contract and phase report for full findings.

---

## Phase 3

Plan: `process/features/evallayer/active/evallayer_22-07-26/phase-03-read-api-dashboard_PLAN_22-07-26.md`

Blast radius (confirmed real at PVL 2026-07-22, no collisions with Phase 1 or Phase 2's DONE
entries above — Phase 1 owns `agent_visit.py`/migration/`agent_classifier.py`/one `main.py`
import line; Phase 2 owns `events.py`/`agent_visit_persistence.py`/`config.py`; neither touches
any file below):

- `apps/api/routers/agents.py` (new)
- `apps/api/schemas/agents.py` (new)
- `apps/api/main.py` (one new router-registration line + one new import — additive only,
  confirmed disjoint from Phase 1's own additive import line in the same file)
- `apps/web/src/app/dashboard/agents/*` (new — list + detail pages)
- `apps/web/src/app/dashboard/layout.tsx` (new nav item)
- `apps/web/src/lib/api.ts`, `apps/web/src/lib/api-types.ts` (new typed methods/types)
- `apps/web/src/components/ui/status-badge.tsx` (3 new STATUS_TONE entries)
- `tests/integration/test_agents_api.py` (new)
- `apps/web/e2e/agents.spec.ts` (new)

status: DONE — EXECUTE + independent EVL both complete 2026-07-22. EVL confirmation run (vc-tester)
GREEN on all runnable gates: FE compile (`npm run build`), unit regression (725 passed/2 skipped,
== baseline, 0 regressions), and static safety review confirming all 5 declared properties
(`verify_site_access` first-line-of-every-handler; `AgentVisit`-only queries, no Visitor/Event join
= AC6; `/stats` registered before `/{agent_visit_id}` catch-all; UUID-parse-then-404 on the detail
route; 3 distinct `STATUS_TONE` badge entries = AC7). FE↔BE contract type-verified transitively by
the FE build. 2 KNOWN-GAPS remain open (env-gated, not design defects, not blockers): (1) Docker
integration run (10 cases in `tests/integration/test_agents_api.py`, collect-clean, unrun — no
responsive Docker in this sandbox at EXECUTE or EVL time; close command: `docker compose -f
infra/docker-compose.yml up -d postgres redis && .venv/bin/python -m pytest
tests/integration/test_agents_api.py -q`); (2) Playwright e2e (`apps/web/e2e/agents.spec.ts`) needs
a running dev server, not started this run; close command: `npm run --prefix apps/web dev & npx
playwright test apps/web/e2e/agents.spec.ts --config=apps/web/playwright.config.ts`. Badge
Agent-Probe judgment (AC7 visual/text check) is a backlog test-building stub, not scriptable, not
a blocker. Phase classified 🔨 CODE DONE (not ✅ VERIFIED) pending closure of both Docker/e2e gaps
— same environment-gap pattern as Phase 1/Phase 2. See phase report's `## EVL Confirmation` section
for full detail.

status (prior): PVL PASS (2026-07-22) — validate-contract written, `generated-by: inner-pvl: phase-3`.
Gate: PASS with documented environment known-gaps (Docker PG+Redis unavailable in this sandbox
for the Hybrid backend integration tests; Playwright e2e needs a dev server not started during
VALIDATE) — same environment condition already logged for Phase 1/Phase 2, not phase-3-specific.
2 mechanical plan gaps found and fixed in-plan during VALIDATE: (1) missing test-authoring
checklist step (Step D added with exact test-function names), (2) `AgentVisit` has no
`agent_visit_id` column — detail route must query by the inherited `id` PK with UUID
parse-then-404, not a nonexistent business-id field (A2 amended).
