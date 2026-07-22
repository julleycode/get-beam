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
