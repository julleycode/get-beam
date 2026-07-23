---
name: plan:handoff-phase-03-intent-signals
description: "Handoff Detection — Phase 03: live on-demand alerts, spike detection, company correlation (H3)"
date: 23-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-03
---

# Phase 03 — Intent Signals (H3)

**Program:** handoff
**Umbrella plan:** process/features/evallayer/active/handoff_23-07-26/handoff-umbrella_PLAN_23-07-26.md
**SPEC:** process/features/evallayer/active/handoff_23-07-26/handoff_SPEC_23-07-26.md (AC-H3-1 through AC-H3-4)
**Phase status:** ⏳ PLANNED
**Report destination:** process/features/evallayer/active/handoff_23-07-26/phase-03-intent-signals_REPORT_23-07-26.md (flat in the program task folder)

---

## Purpose

Turn H1's on-demand fetch stream into live founder-facing intent signals: near-real-time alerts
when someone is actively asking an AI agent about a commercial page, rolling-window spike
detection, and read-only company-correlation metadata linking prior AI-research activity to
resolved leads. None of these signals may ever independently trigger outreach or make a
person-level claim — they are context, not action.

---

## Entry Gate

- Phase 1 (H1) exit gate passed: `agent_fetch_events` table live, tiering correct
- Parallel-safe with Phase 2 per umbrella's Pre-PVL Conflict Resolution — this phase's
  `apps/api/jobs/scheduler.py` job registration MUST be additive and applied AFTER re-reading
  Phase 2's actual diff to that file (Phase 2 registers first in the phase sequence)

---

## Blast Radius

- new intent-signal service (e.g. `apps/api/services/agent_intent_signals.py`) — INNOVATE
  confirms exact module name; mirrors the pure-function aggregation precedent in
  `apps/api/services/agent_aggregator.py` (Phase 6 of the EvalLayer program)
- `apps/api/jobs/scheduler.py` — ONE new periodic job registration for the spike-detector sweep,
  additive, applied after Phase 2's registration (see Entry Gate note)
- `apps/api/services/hot_alert.py` — reused for delivery, not modified (pending INNOVATE
  confirmation of exact integration point per SPEC's `assumption-confirm` default)
- `apps/api/routers/` — new or extended endpoint(s) surfacing intent-alert/spike/company-
  correlation data
- `apps/web/src/app/dashboard/` — widget(s) surfacing live alerts, spike signal, and
  company-correlation metadata on the lead/company record
- `tests/unit/test_intent_alerts.py` (new)

---

## Implementation Checklist

### Step A — Commercial-page classification

- [ ] A1. Confirm during INNOVATE the exact mechanism for "commercial page" classification —
      SPEC default: per-site configurable list defaulting to `/pricing`, `/signup`, `/product*`
      path patterns, reusing whatever page-classification convention already exists in
      `traffic-fit-card.tsx`/segmenter if one exists (research step confirms or rejects reuse).

### Step B — Live on-demand alert

- [ ] B1. Implement alert-trigger logic: an on-demand fetch to a configured commercial page
      creates a near-real-time alert record, reusing the existing hot-alert delivery mechanism
      (`hot_alert.py`) rather than building a new notification channel (SPEC default — INNOVATE
      confirms exact integration point).
- [ ] B2. Confirm delivery latency tier during INNOVATE — SPEC leaves "same request-cycle vs next
      scheduled sweep tick" open for INNOVATE to decide (AC-H3-1 accepts either, as long as it is
      near-real-time per the existing hot-alert precedent).
- [ ] B3. Enforce `site_id` scoping — alerts are site-level, never cross-tenant.

### Step C — Spike detection

- [ ] C1. Implement rolling-window rate-increase detection over on-demand hits to commercial
      pages (pure-function aggregation style, mirroring `agent_aggregator.py`'s precedent).
- [ ] C2. Register as a new periodic job in `apps/api/jobs/scheduler.py`, additive only, applied
      after re-reading Phase 2's actual scheduler.py diff.

### Step D — Company-correlation signal

- [ ] D1. Implement read-only correlation: when a company later resolves as a lead (existing
      company-resolution pipeline) and that company's IP/domain had prior on-demand AI-research
      activity, attach "AI-researched before first human visit" as contextual metadata on the
      already-existing lead record.
- [ ] D2. Confirm this signal NEVER independently creates, approves, or auto-sends any campaign —
      grep for any new write path from this signal into campaign/outreach tables and confirm
      none exists; it is read-only metadata attached to an already-existing record.
- [ ] D3. Confirm the signal is attached at company/site level only — never construct or surface
      a person-level claim from on-demand fetch data.
- [ ] D4. Enforce `site_id` scoping on the company-correlation query.

### Step E — Tests

- [ ] E1. `tests/unit/test_intent_alerts.py::test_commercial_page_triggers_alert` (proves
      AC-H3-1, Fully-Automated for alert creation; Agent-Probe for delivery-channel UX if new).
- [ ] E2. `tests/unit/test_intent_alerts.py::test_spike_detection_threshold` — synthetic fixture
      with rate increase triggers signal; flat/declining rate does not (proves AC-H3-2).
- [ ] E3. `tests/unit/test_intent_alerts.py::test_company_correlation_is_metadata_only` — asserts
      no campaign/outreach write path is triggered by this signal (proves AC-H3-3).
- [ ] E4. `tests/unit/test_intent_alerts.py::test_no_person_level_claim` +
      `test_site_scoped` (proves AC-H3-4).

---

## Exit Gate

```bash
cd /Users/apple/getbeam && python -m pytest tests/unit/test_intent_alerts.py -v
# Expected: all pass (alert trigger, spike detection, company-correlation metadata-only,
# no-person-level-claim, site-scoped)
```

- All checklist items (A1-E4) checked
- Company-correlation signal confirmed read-only (no new outreach-trigger code path)
- No person-level claim constructed anywhere in this phase's code
- Phase report written to report destination above

---

## Blockers That Would Justify BLOCKED Status

- Phase 1 (H1) exit gate not yet passed
- `apps/api/jobs/scheduler.py` overlap with Phase 2's registration not yet resolved — re-verify
  per umbrella's Pre-PVL Conflict Resolution before EXECUTE, do not proceed on a stale read
- Any discovered code path where the company-correlation signal could trigger outreach
  automatically — hard stop requiring plan revision, not a fix-in-place

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [ ] 1. RESEARCH — research-agent: read Phase 1 report; re-read Phase 2's actual
      `apps/api/jobs/scheduler.py` diff (if Phase 2 has executed) to confirm additive-only
      registration; confirm existing commercial-page classification conventions; test context
      loaded
- [ ] 2. INNOVATE — innovate-agent: confirm commercial-page mechanism, alert delivery
      integration point, delivery latency tier; Decision Summary written
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated; Inner Loop Refresh Note if
      sections changed (or "n/a — research clean")
- [ ] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per
      `.claude/skills/vc-validate-findings/references/example-validate-output.md`. **Person-level
      claim exclusion and outreach-trigger exclusion are the highest-priority V2 checks for this
      phase.**
- [ ] 5. EXECUTE — all checklist items done; per-section test gates run and green (or gaps
      documented)
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate
Contract` reads "(placeholder — vc-validate-agent writes this section before EXECUTE)",
orchestrator must spawn vc-validate-agent first.

---

## Touchpoints

- new intent-signal service (location TBD by INNOVATE)
- `apps/api/jobs/scheduler.py` (one new job registration, additive, after Phase 2's)
- `apps/api/services/hot_alert.py` (reused, not modified)
- `apps/api/routers/` (new or extended endpoint)
- `apps/web/src/app/dashboard/` (widget additions)
- `tests/unit/test_intent_alerts.py` (new)

---

## Public Contracts

- `hot_alert.py`'s existing delivery contract is reused, not altered.
- Existing company-resolution pipeline's output contract is extended additively (new read-only
  metadata field), never modified in its existing behavior.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `test_commercial_page_triggers_alert` | Fully-Automated (creation) / Agent-Probe (delivery UX if new) | AC-H3-1 |
| `test_spike_detection_threshold` | Fully-Automated | AC-H3-2 |
| `test_company_correlation_is_metadata_only` | Fully-Automated | AC-H3-3 |
| `test_no_person_level_claim` + `test_site_scoped` | Fully-Automated | AC-H3-4 |

```bash
cd /Users/apple/getbeam && python -m pytest tests/unit/test_intent_alerts.py -v
# Expected: all pass
```

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/handoff_23-07-26/phase-03-intent-signals_PLAN_23-07-26.md`
- Last completed step: not started
- Validate-contract status: pending
- Next step: Spawn vc-research-agent for RESEARCH (Step 1) — after Phase 1 exit gate confirmed;
  re-check Phase 2's scheduler.py state if Phase 2 has already executed

---

## Test Infra Improvement Notes

(none identified yet)

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
