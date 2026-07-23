---
name: plan:handoff-phase-02-handoff-correlation
description: "Handoff Detection — Phase 02: fetch↔click handoff correlation + dashboard badge (H2)"
date: 23-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-02
---

# Phase 02 — Handoff Correlation + Dashboard (H2)

**Program:** handoff
**Umbrella plan:** process/features/evallayer/active/handoff_23-07-26/handoff-umbrella_PLAN_23-07-26.md
**SPEC:** process/features/evallayer/active/handoff_23-07-26/handoff_SPEC_23-07-26.md (AC-H2-1 through AC-H2-5)
**Phase status:** ⏳ PLANNED
**Report destination:** process/features/evallayer/active/handoff_23-07-26/phase-02-handoff-correlation_REPORT_23-07-26.md (flat in the program task folder)

---

## Purpose

Turn H1's per-hit `agent_fetch_events` stream into Beam's headline differentiator: when an
on-demand fetch of page X by vendor V happens at time T, and a human's AI-referral click (via the
already-shipped `ai_source`/`first_touch_referrer` fields) lands on the same page X from the same
vendor family within a bounded window after T, link them. Surface the link on the visitor-detail
dashboard as a confidence-qualified, never-certain badge. AC-H2-3 (both-directions emailability
separation) is the single highest-priority gate in this entire program — it must pass before this
phase can be marked VERIFIED, mirroring the discipline of EvalLayer's AC10.

---

## Entry Gate

- Phase 1 (H1) exit gate passed: `agent_fetch_events` table live, tiering correct, tests green
- Parallel-safe with Phase 3 per umbrella's Pre-PVL Conflict Resolution — Phase 2 registers its
  `apps/api/jobs/scheduler.py` job entry FIRST (before Phase 3); Phase 3 must additively append
  after re-reading this phase's changes

---

## Blast Radius

- `apps/api/models/agent_handoff_link.py` (new)
- `apps/api/migrations/versions/<hash>_add_agent_handoff_links_table.py` (new; additive-only)
- new correlation-sweep service (e.g. `apps/api/services/handoff_correlation.py`) — INNOVATE
  confirms exact module name/location
- `apps/api/jobs/scheduler.py` — ONE new periodic job registration (additive function + one new
  `add_job(...)` call); do not touch any existing job registration
- `apps/api/services/identity_classification.py` — READ-ONLY reference only, confirming
  `is_emailable_identity()`'s existing `source_agent_visit_id` mechanism is untouched; never
  modified by this phase
- `apps/api/routers/` — new or extended read endpoint surfacing handoff-link data for the visitor
  detail view (INNOVATE confirms whether this extends an existing visitor router or adds a new
  one)
- `apps/web/src/app/dashboard/visitors/` — visitor-detail badge/timeline entry
- `apps/web/src/app/dashboard/agents/page.tsx` — agents-side surfacing of linked visits
- `tests/unit/test_handoff_correlation.py` (new)
- `tests/unit/test_handoff_emailability_separation.py` (new — extends the Phase 7
  `test_agent_origin_exclusion.py` pattern; READ that existing test file during RESEARCH, do not
  reinvent its structure)

---

## Implementation Checklist

### Step A — Data model + migration

- [ ] A1. Define `AgentHandoffLink` model: `id` (UUID), `site_id` (FK), `agent_fetch_event_id`
      (FK to `agent_fetch_events`), `visitor_id` (FK, human side), `confidence` (`high`/`medium`/
      `low`), `method` (e.g. `exact-page-vendor-match`), `delta_seconds` (int), `matched_page`,
      `created_at`. This table NEVER references or writes `source_agent_visit_id` — it is a
      structurally separate surface per SPEC Constraint 1.
- [ ] A2. Generate additive-only migration for `agent_handoff_links`.

### Step B — Correlation sweep

- [ ] B1. Implement the periodic correlation sweep (confirm cadence during INNOVATE — SPEC
      default: mirrors `apps/api/jobs/scheduler.py`'s existing periodic-job pattern, e.g.
      `resolution_sweep_interval_minutes`-style config). Query: on-demand `agent_fetch_events`
      joined against human visitors whose `ai_source` matches the fetch's vendor family and whose
      visit timestamp falls within the configured window (SPEC default: 30 minutes) after the
      fetch.
- [ ] B2. Implement the 3-tier confidence model (SPEC default): `high` (exact page + vendor
      family + delta < 5 min), `medium` (exact page + vendor family + delta 5-30 min), `low`
      (same-domain-family match only, within window). Perplexity fetches capped at `medium`
      regardless of timing (undeclared-crawler trust discount per SPEC Constraint/Background).
- [ ] B3. Enforce `site_id` scoping on every query — no cross-site fetch/click pairs may link
      regardless of timing (AC-H2-5).
- [ ] B4. Register the sweep as a new periodic job in `apps/api/jobs/scheduler.py`, additive only.

### Step C — Emailability separation (hard gate)

- [ ] C1. Confirm via code read (not assumption) that `AgentHandoffLink` creation never calls,
      imports, or references `source_agent_visit_id` or `is_emailable_identity()`'s internals.
- [ ] C2. Confirm the human-side `Visitor`/identity record's `is_emailable_identity` output is
      computed identically whether or not a handoff link exists for that visitor — no new
      conditional branch is introduced into that function by this phase.
- [ ] C3. Confirm the agent-fetch-event side of the link has no code path into
      campaign/email/social targeting — grep for any new join from `agent_fetch_events` or
      `agent_handoff_links` into outreach/campaign tables and confirm none exists.

### Step D — API + dashboard surfacing

- [ ] D1. Extend the visitor-detail read endpoint to include handoff-link data (confidence,
      method, delta, matched page) when present — confirm exact endpoint during INNOVATE.
- [ ] D2. Add visitor-detail dashboard badge/timeline entry rendering qualifying language (e.g.
      "AI research detected: ChatGPT fetched this page at 14:32, 6 minutes before this visit") —
      never an unqualified assertion (AC-H2-4).
- [ ] D3. Add agents-page surfacing of the same link data from the agent-fetch side (INNOVATE
      confirms exact placement in `apps/web/src/app/dashboard/agents/page.tsx`).

### Step E — Tests

- [ ] E1. `tests/unit/test_handoff_correlation.py::test_link_created_within_window` — synthetic
      fixture, deterministic clock (proves AC-H2-1).
- [ ] E2. `tests/unit/test_handoff_correlation.py::test_no_link_outside_window` +
      `test_no_link_vendor_mismatch` (proves AC-H2-2).
- [ ] E3. `tests/unit/test_handoff_emailability_separation.py` — asserts BOTH directions in one
      test: (a) linked visitor's `is_emailable_identity` output unchanged, (b) linked
      agent-fetch-event/agent-visit side never gains an emailability/outreach path (proves
      AC-H2-3 — the program's highest-priority gate).
- [ ] E4. `tests/unit/test_agents_api.py::test_handoff_confidence_present` — API contract
      assertion that `confidence` field is always present on any handoff-link representation
      (proves AC-H2-4, Fully-Automated half); manual UI copy review for qualifying language
      (Agent-Probe half).
- [ ] E5. `tests/unit/test_handoff_correlation.py::test_no_cross_site_link` (proves AC-H2-5).

---

## Exit Gate

```bash
cd /Users/apple/getbeam && python -m pytest tests/unit/test_handoff_correlation.py -v
# Expected: all pass (link creation, window/vendor exclusion, cross-site exclusion)

cd /Users/apple/getbeam && python -m pytest tests/unit/test_handoff_emailability_separation.py -v
# Expected: pass — THIS IS THE PROGRAM'S HARD GATE. Phase cannot be VERIFIED without this green.

cd /Users/apple/getbeam && python -m pytest tests/unit/test_agents_api.py -k handoff_confidence -v
# Expected: pass
```

- All checklist items (A1-E5) checked
- AC-H2-3 regression green (both directions asserted in one test)
- Dashboard badge renders confidence-qualified copy (manual/Agent-Probe review recorded)
- Phase report written to report destination above

---

## Blockers That Would Justify BLOCKED Status

- Phase 1 (H1) exit gate not yet passed — this phase structurally cannot start without
  `agent_fetch_events`
- `apps/api/jobs/scheduler.py` conflict with Phase 3's in-flight edits — resolve per umbrella's
  Pre-PVL Conflict Resolution (Phase 2 registers first; re-verify no overlap before EXECUTE)
- Any code path found during Step C that would touch `source_agent_visit_id` or
  `is_emailable_identity()` internals — this is a hard stop requiring plan revision, not a
  fix-in-place

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [ ] 1. RESEARCH — research-agent: read Phase 1 report; read existing
      `test_agent_origin_exclusion.py` (Phase 7 pattern) in full; confirm exact visitor-detail
      endpoint/component to extend; test context loaded
- [ ] 2. INNOVATE — innovate-agent: confirm sweep cadence, confidence model, commercial-page/
      dashboard integration point; Decision Summary written
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated; Inner Loop Refresh Note if
      sections changed (or "n/a — research clean")
- [ ] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per
      `.claude/skills/vc-validate-findings/references/example-validate-output.md`. **Emailability
      separation is the highest-priority V2 dimension check for this phase.**
- [ ] 5. EXECUTE — all checklist items done; per-section test gates run and green (or gaps
      documented)
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate
Contract` reads "(placeholder — vc-validate-agent writes this section before EXECUTE)",
orchestrator must spawn vc-validate-agent first.

---

## Touchpoints

- `apps/api/models/agent_handoff_link.py` (new)
- `apps/api/migrations/versions/` (new migration file)
- new correlation-sweep service (location TBD by INNOVATE)
- `apps/api/jobs/scheduler.py` (one new job registration, additive)
- `apps/api/routers/` (extended or new visitor-detail read endpoint)
- `apps/web/src/app/dashboard/visitors/` (badge component)
- `apps/web/src/app/dashboard/agents/page.tsx` (surfacing addition)
- `tests/unit/test_handoff_correlation.py`, `tests/unit/test_handoff_emailability_separation.py` (new)

---

## Public Contracts

- `is_emailable_identity()`'s existing signature and `source_agent_visit_id` mechanism are
  unchanged — this phase never modifies `identity_classification.py`.
- Existing visitor-detail API response shape is extended additively (new optional handoff-link
  field), never breaking existing consumers.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `test_link_created_within_window` | Fully-Automated | AC-H2-1 |
| `test_no_link_outside_window` + `test_no_link_vendor_mismatch` | Fully-Automated | AC-H2-2 |
| `test_handoff_emailability_separation` (both directions, one test) | Fully-Automated | AC-H2-3 (program's hard gate) |
| `test_handoff_confidence_present` (API assertion) | Fully-Automated | AC-H2-4 (API half) |
| Manual UI copy review — badge never asserts certainty | Agent-Probe | AC-H2-4 (UI wording half) |
| `test_no_cross_site_link` | Fully-Automated | AC-H2-5 |

```bash
cd /Users/apple/getbeam && python -m pytest tests/unit/test_handoff_correlation.py tests/unit/test_handoff_emailability_separation.py -v
# Expected: all pass
```

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/handoff_23-07-26/phase-02-handoff-correlation_PLAN_23-07-26.md`
- Last completed step: not started
- Validate-contract status: pending
- Next step: Spawn vc-research-agent for RESEARCH (Step 1) — after Phase 1 exit gate confirmed

---

## Test Infra Improvement Notes

(none identified yet)

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
