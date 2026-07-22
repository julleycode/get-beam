---
name: plan:evallayer-phase-07-outreach-exclusion
description: "EvalLayer — Phase 07: Outreach-exclusion guardrail + regression test (agent record can NEVER be an outreach target — SPEC AC10, highest-priority test in the program)"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-07
---

# Phase 07 — Outreach-Exclusion Guardrail

**Program:** evallayer
**Umbrella plan:** process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md
**Phase status:** ⏳ PLANNED — **ELEVATED PRIORITY: release gate for Phase 5**
**Report destination:** process/features/evallayer/active/evallayer_22-07-26/phase-07-outreach-exclusion_REPORT_22-07-26.md

---

## Priority Note

Per SPEC Resolved Open Question 10, this phase's numbering (7) reflects dependency order, not
priority order. This is treated as a **hard release gate for Phase 5** — Phase 5 (company
resolution → outreach feed) is not considered mergeable/VERIFIED until this phase's regression test
exists and passes. This phase's dependency (Phase 2 only) means it CAN and SHOULD start in parallel
with, or ahead of, Phase 3/4/5 — do not sequence it strictly after Phase 5 just because its number
is higher.

---

## Purpose

Build a hard, explicit guard ensuring an agent-classified record — resolved to a company or not —
can never be selected as an email/social outreach target, directly or indirectly. This is the single
highest-priority test in the entire program (SPEC AC10) and the program's core business-guardrail
safety constraint: agents are never emailed; only human/company contacts through existing
consent/suppression/approval gates may be reached.

---

## Entry Gate

- Phase 2 exit gate passed (agent-visit records exist and are queryable/referenceable by id).
- No dependency on Phase 3, 4, 5, or 6 — this phase's guardrail must exist independent of and
  before Phase 5 is considered complete.

---

## Blast Radius

- `apps/api/routers/campaigns.py` (or equivalent campaign-targeting entry point)
- segment/audience targeting logic (exact file TBD at RESEARCH/PLAN step — must be confirmed, not
  assumed, given this is the highest-risk surface in the program)
- new regression test file(s) asserting the guardrail

---

## Implementation Checklist

### Step A — Guardrail audit

- [ ] A1. Enumerate every code path that can select a targetable record for campaign/email/social
      send (segment targeting, manual add-to-campaign, any bulk-import path).
- [ ] A2. Confirm the existing `is_emailable_identity()`-style logic (or equivalent) as the
      enforcement point, and extend it (or add an explicit adjacent guard) so an agent-visit
      record id is structurally rejected at every enumerated path — not just the primary one.

### Step B — Regression test (release-gate deliverable)

- [ ] B1. Write a first-class regression test explicitly asserting an agent-visit record ID is
      rejected/excluded if passed into campaign targeting or send-eligibility logic, covering every
      path enumerated in A1.
- [ ] B2. Confirm the test fails (red) against a codebase WITHOUT the guard, and passes (green)
      with it — proving the test actually exercises the guard, not a no-op.

---

## Exit Gate

```bash
# Outreach-exclusion regression test (AC10 — highest priority in the program)
{command}
# Expected: agent-visit record id is rejected/excluded at every campaign/email/social targeting
# entry point; test is proven non-vacuous (fails without the guard, passes with it)
```

- AC10 passes; test is proven non-vacuous.
- Phase report written to report destination above.
- This phase's status must be explicitly cross-referenced in Phase 5's Entry Gate before Phase 5 is
  marked VERIFIED.

---

## Blockers That Would Justify BLOCKED Status

- Phase 2 exit gate not yet passed (no agent-visit records exist to test exclusion against).
- Guardrail audit (Step A1) surfaces a targeting path that cannot be closed within this phase's
  blast radius — must be escalated, never silently left open given this is the program's
  highest-priority safety constraint.

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [ ] 1. RESEARCH — research-agent: prior phase reports read; enumerate every campaign/segment/
      email-targeting code path in full (this is a safety-critical enumeration, not a sample)
- [ ] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated; Inner Loop Refresh Note if sections changed (or "n/a — research clean")
- [ ] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md`; run `vc-security` STRIDE scan given this is an outreach/trust-boundary surface
- [ ] 5. EXECUTE — all checklist items done; per-section test gates run and green
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** This is the highest-risk phase's release-gate
partner — VALIDATE may never be skipped, and a CONDITIONAL/BLOCKED gate must never be silently
accepted as "good enough" given the business-guardrail stakes (agents must never be emailed).

---

## Touchpoints

- `apps/api/routers/campaigns.py` (or equivalent)
- segment/audience targeting logic (file TBD at RESEARCH)
- new regression test file(s)

---

## Public Contracts

- No externally-visible API shape change — this phase adds an internal hard exclusion; existing
  campaign/segment/email API contracts remain unchanged in shape.

---

## Verification Evidence

```bash
# {verification command — run after phase complete, exact command written at PLAN step}
{command}
# Expected: {expected output}
```

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/evallayer_22-07-26/phase-07-outreach-exclusion_PLAN_22-07-26.md`
- Last completed step: not started
- Validate-contract status: pending
- Next step: Confirm Phase 2 exit gate passed, then spawn vc-research-agent for RESEARCH (Step 1).
  Recommend prioritizing this phase's kickoff alongside or ahead of Phase 5, not strictly after it.

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
