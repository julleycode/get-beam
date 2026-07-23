---
name: plan:handoff-phase-04-watermark-feasibility
description: "Handoff Detection — Phase 04: citation-watermark feasibility probe, gated implementation (H4)"
date: 23-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-04
---

# Phase 04 — Citation-Watermark Feasibility (H4)

**Program:** handoff
**Umbrella plan:** process/features/evallayer/active/handoff_23-07-26/handoff-umbrella_PLAN_23-07-26.md
**SPEC:** process/features/evallayer/active/handoff_23-07-26/handoff_SPEC_23-07-26.md (AC-H4-1, AC-H4-2)
**Phase status:** ⏳ PLANNED
**Report destination:** process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_REPORT_23-07-26.md (flat in the program task folder)

---

## Purpose

Answer, honestly and cheaply, whether a Beam-controlled query-string marker survives into an AI
agent's returned citation link — BEFORE committing to building any watermarking mechanism. This
phase is a manual-first, double-opt-in live probe (VC-FEASIBILITY-PROBE-NEEDED, cost-class
`needs-live-provider`), not a normal implementation phase. "Done" for H4 means the VERDICT is
recorded — regardless of outcome. Implementation is a strictly separate, gated sub-scope that only
activates on a VIABLE verdict plus explicit user sign-off.

---

## Entry Gate

- Loosely depends on Phase 1 (H1) only if the probe reuses H1's event-tagging infrastructure for
  the Beam-owned test page (confirm during RESEARCH — SPEC does not mandate this reuse).
- No hard phase dependency otherwise — this probe can, in principle, run independently of H2/H3.
- **HARD STOP regardless of ordering:** the live-provider probe dispatch always requires explicit
  double opt-in from the user before it runs (SPEC Constraint 7). This is never bypassed under
  `/goal` autonomous execution.

---

## Blast Radius

**Probe phase (always in scope):**
- `process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_FEASIBILITY_{date}.md`
  (new VERDICT artifact, written by vc-debugger per the `vc-feasibility-test` playbook)
- a Beam-owned, low-traffic test page (SPEC default: purpose-built, not a real customer page) —
  location TBD by INNOVATE (likely `apps/web/src/app/(some test route)/` or reuse of an existing
  internal test surface)

**Conditional implementation phase (ONLY if VERDICT = VIABLE + explicit user sign-off):**
- watermark-generation logic (location TBD — depends entirely on the probe's findings about what
  survives)
- citation-link parsing/attribution extension (location TBD)
- NOTE: this sub-scope has NO planned file list here because it cannot be planned before the
  probe's VERDICT exists — if VIABLE + sign-off occurs, a NEW plan must be written (either as a
  supplement to this phase plan or a follow-up phase, per the PLAN-SUPPLEMENT step) before any
  implementation checklist item is executed.

---

## Implementation Checklist

### Step A — Probe design (INNOVATE-owned, not assumed here)

- [ ] A1. Confirm test-page ownership and hosting location (SPEC default: Beam-owned, low-traffic,
      purpose-built page — never a real customer page).
- [ ] A2. Design the unique query-string marker scheme for the test page (e.g.
      `?beam_probe_id=<uuid>` or similar) — kept intentionally simple, no cloaking or UA-sniffing
      involved (SPEC's absolute Out-of-Scope boundary applies even to the probe itself).
- [ ] A3. Confirm which live AI agent(s) the founder will manually query (e.g. ChatGPT) and the
      exact prompt/browsing request to issue.

### Step B — Dispatch (hard stop — requires explicit double opt-in)

- [ ] B1. Orchestrator surfaces `VC-FEASIBILITY-PROBE-NEEDED: citation-watermark survival —
      cost-class: needs-live-provider` per `orchestration.md`
      §VC-FEASIBILITY-PROBE-NEEDED Signal Routing. This ALWAYS pauses for explicit double opt-in
      — never auto-granted under `/goal`.
- [ ] B2. On opt-in: founder manually asks the live AI agent to browse the tokenized test page,
      then requests (or asks a follow-up question that would surface) a citation link back to the
      page.
- [ ] B3. Inspect the returned citation link for marker survival (present verbatim, stripped,
      transformed, or absent).

### Step C — Verdict

- [ ] C1. `vc-debugger` writes the VERDICT artifact to
      `process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_FEASIBILITY_{date}.md`
      with an explicit `VIABLE` / `NOT-VIABLE` / `INCONCLUSIVE` keyword and the 3-part design
      constraint (what this licenses / what this forbids / what remains uncertain).
- [ ] C2. Record the actual resolved `## Probe Cost Class` in the VERDICT (confirming
      `needs-live-provider` was the correct classification, per `orchestration.md`'s cost-class
      gate resolution step).

### Step D — Conditional implementation gate

- [ ] D1. If VERDICT = `NOT-VIABLE` or `INCONCLUSIVE`: phase is COMPLETE. No implementation code
      is written. Program closeout confirms no watermark-write code path exists (AC-H4-2).
- [ ] D2. If VERDICT = `VIABLE`: STOP. Do not implement automatically. Surface the VERDICT to the
      user and request explicit sign-off for production rollout, per SPEC's US7/AC-H4-2 gating
      language ("even then requires explicit user sign-off before any production rollout, never
      automatic").
- [ ] D3. If sign-off is granted: a NEW implementation checklist must be written (via
      PLAN-SUPPLEMENT to this phase or a new follow-up phase plan) before any code is written —
      this checklist does not exist yet and is intentionally not pre-authored here, since it
      depends entirely on what the VERDICT's design constraint licenses/forbids.

---

## Exit Gate

```bash
grep -E "VIABLE|NOT-VIABLE|INCONCLUSIVE" process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_FEASIBILITY_*.md
# Expected: exactly one recorded keyword

grep -rn "watermark" apps/api/ apps/web/src/ 2>/dev/null | grep -v test
# Expected (unless VIABLE + sign-off + follow-up implementation has occurred): no production
# watermark-write code path found
```

- Step A-C complete: VERDICT artifact exists with a recorded keyword and the 3-part design
  constraint
- If VERDICT != VIABLE: phase is complete, no implementation attempted (Step D1)
- If VERDICT == VIABLE: explicit user sign-off recorded before any implementation checklist is
  authored (Step D2/D3)
- Phase report written to report destination above, regardless of verdict outcome

---

## Blockers That Would Justify BLOCKED Status

- User does not grant double opt-in for the live-provider probe — this is NOT a blocker in the
  traditional sense; the phase remains PENDING/paused (not BLOCKED) until the user opts in or
  explicitly defers the probe to backlog
- The Beam-owned test page cannot be provisioned (e.g. no available low-traffic hosting slot) —
  genuine blocker, escalate to user for an alternative hosting decision
- VERDICT = VIABLE but user declines sign-off for production rollout — phase is still COMPLETE
  per AC-H4-2 ("done" means VERDICT recorded, not that watermarking ships); this is NOT a blocker,
  it is an accepted terminal state for this phase

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop). **This
phase's PVL step is expected to itself trigger `VC-FEASIBILITY-PROBE-NEEDED` — this is normal for
H4, not an error.**

- [ ] 1. RESEARCH — research-agent: confirm test-page hosting options; confirm exact live-agent
      probe mechanics (what "asking ChatGPT to browse a page" looks like in practice); test
      context loaded
- [ ] 2. INNOVATE — innovate-agent: design the marker scheme and probe prompt; Decision Summary
      written; **INNOVATE itself may emit `VC-FEASIBILITY-PROBE-NEEDED` — this is the expected
      and correct signal for this phase, not a deviation**
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated with the confirmed probe
      design (or "n/a — research clean")
- [ ] 4. PVL — vc-validate-agent: full V1-V7. **This phase's validate-contract records the probe
      dispatch instructions, NOT a normal code-change gate — Test Gates section should reference
      the VERDICT-keyword grep command above rather than a pytest command, since there is no code
      change to test until/unless VIABLE + sign-off occurs.**
- [ ] 5. EXECUTE — Step B (dispatch, requires opt-in) + Step C (VERDICT written) executed; Step D
      gate resolved
- [ ] 6. EVL — confirm VERDICT artifact exists with a valid keyword; confirm no premature
      implementation code was written
- [ ] 7. UPDATE PROCESS — phase report written (recording the verdict outcome regardless of
      VIABLE/NOT-VIABLE/INCONCLUSIVE), umbrella state updated, commit done

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate
Contract` reads "(placeholder — vc-validate-agent writes this section before EXECUTE)",
orchestrator must spawn vc-validate-agent first. **The double-opt-in hard stop at Step B is
independent of and additional to the normal PVL gate — even a PASS validate-contract does not
authorize skipping the opt-in pause.**

---

## Touchpoints

- `process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_FEASIBILITY_{date}.md` (new VERDICT artifact)
- a Beam-owned test page (location TBD by INNOVATE)
- (conditional, only if VIABLE + sign-off) watermark-generation + citation-parsing code — not
  planned here, requires a follow-up plan

---

## Public Contracts

- None in the probe-only path — no code changes, no API/schema surface touched.
- (Conditional) any future implementation would need its own Public Contracts section in a
  follow-up plan.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| VERDICT artifact exists with recorded keyword | Agent-Probe (cost-class: needs-live-provider) | AC-H4-1 |
| Program closeout manual review confirms no watermark-write code path exists unless VIABLE + sign-off on record | Agent-Probe | AC-H4-2 |

```bash
grep -E "VIABLE|NOT-VIABLE|INCONCLUSIVE" process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_FEASIBILITY_*.md
# Expected: exactly one recorded keyword
```

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_PLAN_23-07-26.md`
- Last completed step: not started
- Validate-contract status: pending
- Next step: Spawn vc-research-agent for RESEARCH (Step 1); expect PVL to route through
  `VC-FEASIBILITY-PROBE-NEEDED` and the double-opt-in hard stop before any dispatch

---

## Test Infra Improvement Notes

(none identified yet)

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
