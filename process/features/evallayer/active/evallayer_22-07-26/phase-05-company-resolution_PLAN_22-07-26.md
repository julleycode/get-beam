---
name: plan:evallayer-phase-05-company-resolution
description: "EvalLayer — Phase 05: Company-resolution -> human-outreach feed (agent IP -> existing company_resolver -> company enters existing enrichment/email pipeline)"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-05
---

# Phase 05 — Company Resolution → Outreach Feed

**Program:** evallayer
**Umbrella plan:** process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md
**Phase status:** ⏳ PLANNED — **RE-RESEARCH REQUIRED before PLAN (see note below)**
**Report destination:** process/features/evallayer/active/evallayer_22-07-26/phase-05-company-resolution_REPORT_22-07-26.md

---

## CRITICAL — Mandatory-Fresh RESEARCH (not resumable)

The prior 7-agent RESEARCH fan-out's `read:identity` sub-agent (agentId `acf7d043d1d675da7`)
returned **placeholder/test output** (`"summary":"test"`, `"key_files":["a"]`, all fields literally
`"a"` or `"test"`) instead of real findings. **Agent→company enrichment-waterfall mechanics for
this phase are under-researched.** Phase 5's Step 1 (RESEARCH) MUST be treated as mandatory-fresh —
not resumable from the existing research brief's Phase 5 summary, which is itself only a synthesis
of that placeholder output plus general context. Do not let PLAN begin for this phase until a real
RESEARCH pass has read `apps/api/services/company_resolver.py`, `apps/api/services/enricher.py` (or
equivalent), the identity-resolution budget/waterfall logic, and the existing lead/company creation
path in full.

---

## Purpose

When an agent visit's IP resolves via Beam's existing `company_resolver.py` to a real company,
create or update a normal company/lead record in the existing human enrichment + email-outreach
pipeline. The agent itself is never the contactable entity — only the resolved human/company
contact, reached through Beam's existing consent/suppression/approval gates (SPEC AC9). This phase
reuses the same provider waterfall as human visitor resolution and therefore consumes the existing
identity-resolution budget (SPEC Resolved Open Question 4).

---

## Entry Gate

- Phase 3 exit gate passed (agent visits are queryable via `/agents`).
- Phase 4 exit gate passed (verification/confidence field exists to gate which visits qualify for
  resolution, if the fresh RESEARCH pass confirms confidence-gating is part of the design).
- Phase 7's outreach-exclusion guardrail test exists or is actively scheduled alongside this phase
  (SPEC Resolved Open Question 10 — Phase 7 is a release gate for Phase 5, not merely a
  later-numbered nice-to-have).

---

## Blast Radius

- TBD — pending mandatory-fresh RESEARCH. Expected candidates based on the RESEARCH brief's
  reusable-assets list (not yet confirmed): `apps/api/services/company_resolver.py` (read/reuse),
  existing enrichment/lead-creation service (name unconfirmed), existing identity-resolution budget
  accounting logic.

---

## Implementation Checklist

### Step A — Mandatory-fresh research (must complete before any other step)

- [ ] A1. Read `company_resolver.py` in full — confirm exact function signatures for IP→company
      resolution reuse.
- [ ] A2. Read the existing enrichment/lead-creation pipeline in full — confirm how a resolved
      company enters the human pipeline as a normal lead (not a new, parallel code path).
- [ ] A3. Confirm identity-resolution budget accounting semantics for this reused waterfall path
      (SPEC Resolved Open Question 4 — this path DOES consume the existing budget).
- [ ] A4. Confirm the exact mechanism ensuring the created record's contactable identity is the
      resolved human/company contact — never the agent-visit record itself.

### Step B — Implementation (checklist items to be written at PLAN step, after Step A completes)

- [ ] B1. {pending fresh research — do not write speculative implementation steps for a
      security/outreach-adjacent surface}

---

## Exit Gate

```bash
# Company/lead record created from qualifying agent visit (AC9)
{command}
# Expected: Company/lead record created downstream; contactable identity is resolved human/company,
# never the agent-visit record

# Mock mode coverage (AC14, this phase's reused external call)
{command}
# Expected: unit tests run fully offline under MOCK_EXTERNAL_APIS=true
```

- AC9 and the mock-mode portion of AC14 pass.
- Phase 7's outreach-exclusion regression test passes (release-gate condition — see Entry Gate).
- Phase report written to report destination above.

---

## Blockers That Would Justify BLOCKED Status

- Mandatory-fresh RESEARCH (Step A) not yet complete — this phase cannot proceed past RESEARCH
  without real findings on the enrichment-waterfall mechanics.
- Phase 7's guardrail test does not exist or is not scheduled — per SPEC Resolved Open Question 10,
  this phase should not be considered PLAN-complete or EXECUTE-eligible without it.
- Phase 3 or Phase 4 exit gates not yet passed.

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [ ] 1. RESEARCH — research-agent: **MANDATORY FRESH** — prior findings are placeholder/test
      output and must not be treated as resumable; read company_resolver.py, enrichment pipeline,
      identity-resolution budget logic, and lead-creation path in full
- [ ] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: full checklist written (Step B above is a placeholder
      pending fresh research — do not skip to writing it speculatively)
- [ ] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md`
- [ ] 5. EXECUTE — all checklist items done; per-section test gates run and green
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** Highest-risk phase in the program (outreach-adjacent
surface) — VALIDATE may never be skipped, and PVL should apply extra scrutiny per
`vc-security`/STRIDE given the auth/outreach-adjacent surface.

---

## Touchpoints

- TBD — pending mandatory-fresh RESEARCH (Step A).

---

## Public Contracts

- No new externally-visible API surface expected — this phase feeds the existing lead/company
  creation pipeline. Existing campaign/segment/email API contracts must remain unchanged in shape;
  only new data enters via the existing pipeline, gated by Phase 7's guardrail.

---

## Verification Evidence

```bash
# {verification command — run after phase complete, exact command written at PLAN step, after fresh research}
{command}
# Expected: {expected output}
```

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/evallayer_22-07-26/phase-05-company-resolution_PLAN_22-07-26.md`
- Last completed step: not started
- Validate-contract status: pending
- Next step: Confirm Phase 3 + Phase 4 exit gates passed AND Phase 7 guardrail test exists/scheduled,
  then spawn vc-research-agent for a MANDATORY-FRESH RESEARCH pass (Step 1) — do not reuse the
  existing research brief's Phase 5 findings, which derive from placeholder sub-agent output.

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
