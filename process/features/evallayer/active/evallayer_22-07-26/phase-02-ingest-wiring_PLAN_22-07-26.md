---
name: plan:evallayer-phase-02-ingest-wiring
description: "EvalLayer — Phase 02: Ingest wiring (classify-then-branch in events.py, filter-ordering reconciliation, persist agent visits)"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-02
---

# Phase 02 — Ingest Wiring

**Program:** evallayer
**Umbrella plan:** process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md
**Phase status:** ⏳ PLANNED
**Report destination:** process/features/evallayer/active/evallayer_22-07-26/phase-02-ingest-wiring_REPORT_22-07-26.md

---

## Purpose

Wire Phase 1's classifier into the live `/events/ingest` hot path. Replace/extend the `is_bot()`
short-circuit (`events.py:74-78`) with classify-then-branch logic, resolve the ordering conflict
between the new agent-vendor allowlist and the existing datacenter/proxy-VPN drop checks
(`events.py:119-140` — per SPEC Resolved Open Question 3, the agent allowlist must run BEFORE these
drops), and persist agent visits to the Phase 1 data surface without touching human Visitor/Event
tables.

---

## Entry Gate

- Phase 1 exit gate passed (classifier + schema exist).

---

## Blast Radius

- `apps/api/routers/events.py` (ingest hot path)
- `apps/api/services/bot_filter.py` (integration point for classify-then-branch)
- `apps/api/config.py` (new `AGENT_DETECTION_ENABLED`-style flag)

---

## Implementation Checklist

### Step A — Classify-then-branch

- [ ] A1. Replace/extend the `is_bot()` short-circuit at `events.py:74-78` with a call into Phase
      1's `agent_classifier.py`; recognized agent tokens branch to persist, generic bot tokens
      still drop exactly as today (SPEC AC3).
- [ ] A2. Ensure the classify step is synchronous UA-match only (no added latency) per SPEC
      Resolved Open Question 2 — verification runs later in Phase 4, async/best-effort.

### Step B — Filter ordering reconciliation

- [ ] B1. Move or gate the datacenter/proxy-VPN drop checks (`events.py:119-140`) so a
      recognized-agent classification short-circuits past them (SPEC AC4, Resolved Open Question 3).
- [ ] B2. Confirm existing datacenter/proxy-VPN drop behavior for non-agent traffic is unchanged.

### Step C — Persistence

- [ ] C1. Persist classified agent visits to the Phase 1 data surface; confirm no row is written to
      `Visitor`/human `Event` aggregation tables (SPEC AC2).
- [ ] C2. Add `AGENT_DETECTION_ENABLED`-style flag to `config.py` following the
      `BLOCK_DATACENTER_TRAFFIC` convention.

---

## Exit Gate

```bash
# Recognized-agent UA persists (AC1)
{command}
# Expected: agent-visit row created, 204/existing response shape unchanged

# Human tables unaffected (AC2)
{command}
# Expected: Visitor/Event counts identical before/after agent-only batch

# Generic bots still dropped (AC3)
{command}
# Expected: no row written, existing 204 behavior unchanged

# Filter-ordering / datacenter IP not re-dropped (AC4)
{command}
# Expected: agent visit persists even when IP flagged datacenter/cloud

# Latency check (AC5, Hybrid)
{command}
# Expected: ingest response time comparable with/without agent classification
```

- All 5 exit-gate criteria (AC1–AC5) pass.
- Phase report written to report destination above.

---

## Blockers That Would Justify BLOCKED Status

- Phase 1 exit gate not yet passed (classifier/schema unavailable).
- Filter-ordering change risks regressing existing datacenter/proxy-VPN drop behavior for
  non-agent traffic — must be resolved with a regression test, not assumed safe.

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

**Validate-contract required before execute.** Ingest hot path + filter-ordering surface —
VALIDATE may never be skipped for this phase.

---

## Touchpoints

- `apps/api/routers/events.py`
- `apps/api/services/bot_filter.py`
- `apps/api/config.py`

---

## Public Contracts

- `/events/ingest` external request/response shape is unchanged for both human and agent traffic —
  only internal branching and persistence behavior change.

---

## Verification Evidence

```bash
# {verification command — run after phase complete, exact command written at PLAN step}
{command}
# Expected: {expected output}
```

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/evallayer_22-07-26/phase-02-ingest-wiring_PLAN_22-07-26.md`
- Last completed step: not started
- Validate-contract status: pending
- Next step: Confirm Phase 1 exit gate passed, then spawn vc-research-agent for RESEARCH (Step 1).

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
