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
