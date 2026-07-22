---
name: plan:evallayer-phase-06-aggregation-analytics
description: "EvalLayer — Phase 06: Aggregation + GEO/AEO analytics widgets (vendor breakdown, visits-over-time, page-read trends)"
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
**Phase status:** ⏳ PLANNED
**Report destination:** process/features/evallayer/active/evallayer_22-07-26/phase-06-aggregation-analytics_REPORT_22-07-26.md

---

## Purpose

Build the aggregation and analytics layer on top of classified, verified agent visits: a rollup path
parallel to `visitor_aggregator.py`/`aggregation_tasks.py` (not merged into human-visitor
aggregation, per SPEC AC2), and dashboard widgets (vendor breakdown, visits-over-time, page-read
trends) cloning `visitor-widgets.tsx`/`kpi-strip.tsx`/`traffic-fit-card.tsx` conventions with a
distinct storage key (e.g. `beam_agent_widgets_v1`) to avoid localStorage collision with existing
Visitor widgets.

---

## Entry Gate

- Phase 3 exit gate passed (agent-visit read API/dashboard tab exists).
- Phase 4 exit gate passed (confidence field exists for accurate vendor breakdown).
- Parallel-safe with Phase 5 — disjoint blast radius (aggregation/analytics vs.
  company-resolution/outreach).

---

## Blast Radius

- `apps/api/services/agent_aggregator.py` (or equivalent — new, parallel to
  `visitor_aggregator.py`)
- `apps/api/tasks/aggregation_tasks.py` (new agent-visit rollup task, sync-wrapper + async impl
  pattern)
- `apps/web/src/components/agent-widgets.tsx` (or equivalent — new)

---

## Implementation Checklist

### Step A — Aggregation service

- [ ] A1. Build agent-visit rollup logic parallel to `visitor_aggregator.py` (never merges into
      human-visitor aggregation tables — SPEC AC2 boundary applies here too).
- [ ] A2. Add Celery task following the existing sync-wrapper + async-impl pattern in
      `aggregation_tasks.py`.

### Step B — Analytics widgets

- [ ] B1. Clone `visitor-widgets.tsx`/`kpi-strip.tsx`/`traffic-fit-card.tsx` conventions for "Agent
      vendor breakdown" and "Agent visits over time" widgets.
- [ ] B2. Use a distinct localStorage key (e.g. `beam_agent_widgets_v1`) to avoid collision with
      existing Visitor widget layout storage.

### Step C — Correctness fixture

- [ ] C1. Build a synthetic fixture set of agent visits across multiple vendors/pages for
      aggregation correctness testing (SPEC AC11).

---

## Exit Gate

```bash
# Aggregation correctness (AC11)
{command}
# Expected: vendor-breakdown and page-read trend counts correct against synthetic fixture data
```

- AC11 passes.
- Phase report written to report destination above.

---

## Blockers That Would Justify BLOCKED Status

- Phase 3 or Phase 4 exit gates not yet passed.
- Aggregation logic accidentally merges agent rollups into human-visitor tables (regression risk
  against SPEC AC2 — must be explicitly tested, not assumed safe).

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [ ] 1. RESEARCH — research-agent: prior phase reports read; test context loaded; plan drift checked
- [ ] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated; Inner Loop Refresh Note if sections changed (or "n/a — research clean")
- [ ] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md`
- [ ] 5. EXECUTE — all checklist items done; per-section test gates run and green
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** Regression risk against human-data isolation
guardrail (AC2) — VALIDATE may never be skipped for this phase.

---

## Touchpoints

- `apps/api/services/agent_aggregator.py` (new)
- `apps/api/tasks/aggregation_tasks.py`
- `apps/web/src/components/agent-widgets.tsx` (new)

---

## Public Contracts

- No externally-visible API contract change — extends the `/agents` stats surface (from Phase 3)
  with aggregated data; existing `/visitors` aggregation contract unchanged.

---

## Verification Evidence

```bash
# {verification command — run after phase complete, exact command written at PLAN step}
{command}
# Expected: {expected output}
```

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/evallayer_22-07-26/phase-06-aggregation-analytics_PLAN_22-07-26.md`
- Last completed step: not started
- Validate-contract status: pending
- Next step: Confirm Phase 3 + Phase 4 exit gates passed, then spawn vc-research-agent for RESEARCH
  (Step 1); may run in parallel with Phase 5.

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
