---
name: report:private-beta-apply-form-pvl-iteration-003
description: "PVL supplement cycle 3 — closed 6 validate CONCERNs + 1 orchestrator-found gap; full gate-class audit"
date: 15-08-26
feature: onboarding-canary
metadata:
  node_type: report
  type: pvl-iteration
  cycle: 3
  domain: plan
---

# PVL Iteration 003 — private-beta-apply-form

## Input

Validate cycle 3: `Gate: CONDITIONAL` — 0 FAILs, 6 CONCERNs. Orchestrator added a
7th found while verifying the resume section after the validator self-reported a
truncated edit.

## Gaps closed

| Gap | Resolution |
|---|---|
| 1 | E4 pattern now includes the backtick — verified live: 3 hits → 4. Pre-fix confirmation made mandatory. |
| 2 | Section A now specifies **7** columns incl. `plan_interest` `String(32)`, 7× add/drop, self-sufficient without reading Section C. |
| 3 | Canary cross-plan backlog NOTE is now a Section E deliverable, gated by new E6. |
| 4 | F.3 default is the zero-touch verbatim literal; constant-extraction demoted to recorded-and-rejected. `dependencies.py` stays read-only. |
| 5 | F10 promoted Agent-Probe → Fully-Automated (`apps/web/e2e/invite-token-delivery.spec.ts`, no auth needed — both routes are public). |
| 6 | Ratified `invite_url` exception appended to the SPEC's Out of Scope (only edit outside the plan file). |
| 7 | Resume probe 5 replaced with E1's corrected pattern. |

## Gate-class audit — the real deliverable

Every probe in the resume ladder and every remaining grep/pytest gate command was
**executed** against the live tree, not read.

- **One more instance found (5th overall): resume probe 5.** Worse than the
  orchestrator flagged — `grep '/sign-up' apps/web/public/beam/*` returns **4**
  hits, because the bare `*` glob drags in `onboarding-app.js:11`, a file outside
  E1's declared scope, on top of the immortal prose lines at
  `onboarding-steps.js:9` and `:555`.
- Probes 1–4 satisfiable as written. Probe 6 tightened (a marker-less file reads
  green under `--collect-only` while the `-m unit` lane silently excludes it —
  the FAIL-C trap).
- A3, C1/C2, C4, D3, E1, E2, F1/F11, F8, F9 re-executed: satisfiable, correct
  failure direction. New E6 correctly fails now (file absent by design), passes
  once Section E writes the deliverable.
- **No further instances remain.**

### Why it recurred

Cycle 1 fixed this pattern *in the gate* (E1) and left it alive *in the probe*,
because only gates were re-audited. Standing rule now recorded in Test Infra
Improvement Notes: **any gate-pattern correction must be grepped plan-wide.**

Running count of the unsatisfiable-gate class: **4 gate instances + 1 probe
instance across 3 cycles.** It is the dominant defect class of this plan.

## Forced coherence edits

- **Blast radius 19 → 20** — gap 5's new Playwright spec. Recounted from the
  Touchpoints table (21 rows − 1 `waitlist.py` duplicate). `dependencies.py` is
  NOT in the count and must not enter it.
- Unsatisfiable-gate class count corrected 3 → 4 in the plan body.

## Tooling note

The `Edit` tool was unavailable to the supplement agent this session; it used
assertion-guarded Python replaces (`assert count==1` on a unique anchor, immediate
write, one gap per call). Stricter than hand anchor-matching — a non-unique or
absent anchor aborts before writing, making cycle 3's truncation failure mode
impossible.

## Validator state

`validate-plan-artifact.mjs` → 0 failures, 0 warnings. 16 `##` sections intact.

## Next step

Re-spawn vc-validate-agent from V1. Expectation: PASS.
