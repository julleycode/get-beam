---
name: plan:evallayer-phase-00-discoverability
description: "EvalLayer — Phase 00: Discoverability (JSON-LD offers array + /.well-known/ai-plugin.json) — SHIPPED pre-program"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-00
---

# Phase 00 — Discoverability

**Program:** evallayer
**Umbrella plan:** process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md
**Phase status:** ✅ COMPLETE — shipped, committed (`5ae5bd7`), pushed to `main`; plan archived (`7e0d625`)
**Report destination:** n/a — see the archived plan's own Closeout Report section (no separate phase report was written; the plan itself carries the closeout)

---

## IMPORTANT — Shipped Pre-Program, Not a Fresh Plan (corrected 22-07-26, UPDATE PROCESS)

This phase is **already done**. It was executed as a standalone SIMPLE plan earlier the same day,
before this 8-phase program was scaffolded, then archived once shipped. The scaffolder's original
note here (which claimed the prior plan "was not found anywhere on disk" and had to be re-planned
from scratch) was **wrong** — root cause: its `find` against `process/general-plans/active/` raced
the archival `git mv` into `completed/` and hit the folder mid-move. No content was ever lost.

**Source of truth for this phase:**
`process/general-plans/completed/evallayer-discoverability_22-07-26/evallayer-discoverability_PLAN_22-07-26.md`
— read that file for full scope, implementation checklist, deviations (including the unplanned
Clerk middleware exemption), Verification Evidence results, and the Closeout Report.

**Shipped commits:**
- `5ae5bd7` — `feat(seo): tiered JSON-LD offers + public ai-plugin.json manifest` (modifies
  `apps/web/public/beam/index.html`, adds `apps/web/src/app/.well-known/ai-plugin.json/route.ts`,
  edits `apps/web/src/middleware.ts` for the Clerk `.well-known/*` exemption)
- `7e0d625` — `process(evallayer-discoverability): archive shipped plan, capture learnings`

**Do not re-run RESEARCH, INNOVATE, PLAN, VALIDATE, or EXECUTE for this phase.** Nothing here needs
rebuilding.

**One real caveat carried forward (not fabricated):** VALIDATE was explicitly skipped for the
archived SIMPLE plan (documented reason: frontend-only, no auth surface identified at PLAN time —
later found incomplete once the Clerk middleware exemption surfaced live during EXECUTE). SPEC
AC12's 4 criteria were verified ad hoc during EXECUTE, not as a formal validate-contract: 3 of 4
passed (JSON-LD parse + 3-tier array; grep constraint for no `openapi`/`api.getbeam.fyi`; live GET
200 + content-type + manifest shape). The 4th (Agent-Probe: paste rendered HTML into Google Rich
Results Test / schema.org validator) was never run. **Recommendation:** run this lightweight AC12
Agent-Probe check during the program's overall closeout rather than treating Phase 0 as fully
gate-verified.

---

## Purpose (for reference — already achieved)

Make Beam's own site legible to AI agents/crawlers via two passive, outbound-facing surfaces: an
expanded JSON-LD `offers` array (3-tier pricing with availability) on the homepage, and a new
`/.well-known/ai-plugin.json` discovery manifest. Both shipped as described above.

---

## Entry Gate

- Program start — no dependency on any other phase.
- Already satisfied (shipped pre-program).

---

## Blast Radius (as shipped)

- `apps/web/public/beam/index.html` (JSON-LD `offers` array expansion) — modified
- `apps/web/src/app/.well-known/ai-plugin.json/route.ts` (new route) — new
- `apps/web/src/middleware.ts` (Clerk `.well-known/*` exemption) — modified, unplanned supplement,
  user-approved (see archived plan's Deviations section)

---

## Implementation Checklist (all done — see archived plan for full detail)

### Step A — Research + confirm current state

- [x] A1. Confirmed `apps/web/public/beam/index.html` JSON-LD block and `apps/web/src/app/llms.txt/route.ts` shape during EXECUTE.
- [x] A2. Confirmed 3 of 4 SPEC AC12 criteria (valid JSON-LD; valid manifest with `auth.type: none`, no `api`/`openapi` reference; prices in sync). 4th criterion (Agent-Probe Rich Results check) not run — see caveat above.

### Step B — JSON-LD offers array

- [x] B1. Expanded single `Offer` to a 3-tier array (Free/Pro/Max) with `availability`.
- [x] B2. Prices confirmed in sync with `pricing/page.tsx` at ship time; sync-note HTML comment added.

### Step C — ai-plugin.json manifest

- [x] C1. Created `apps/web/src/app/.well-known/ai-plugin.json/route.ts` mirroring `llms.txt/route.ts` conventions.
- [x] C2. Manifest sets `auth.type: none`, omits any `api`/`openapi` reference.

---

## Exit Gate

Satisfied for 3 of 4 SPEC AC12 criteria (Fully-Automated + Hybrid gates, verified during EXECUTE —
see archived plan's Verification Evidence table rows 1, 3, 4). Row 2 (Agent-Probe Rich Results
paste-check) recommended at program closeout, not blocking for Phase 0 completion.

- Phase report: not a separate file — see the archived plan's own `## Closeout Report (UPDATE
  PROCESS, 22-07-26)` section, which serves as this phase's report.

---

## Blockers That Would Justify BLOCKED Status

None — phase is complete. (Historical: none arose during the original EXECUTE pass; the middleware
gap was caught live and resolved within the same pass, no BLOCKED state occurred.)

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. All steps below are complete
— this phase requires NO further subagent spawns.

- [x] 1. RESEARCH — done during the original standalone SIMPLE-plan session (pre-program)
- [x] 2. INNOVATE — explicitly skipped per the archived plan ("SPEC and INNOVATE were intentionally skipped — decisions are locked, the how is mechanical")
- [x] 3. PLAN-SUPPLEMENT — n/a, full checklist was written directly in the original SIMPLE plan
- [x] 4. PVL — VALIDATE explicitly skipped (documented reason in archived plan's `## Validate Contract` section); gates verified directly during EXECUTE instead
- [x] 5. EXECUTE — all checklist items done; gates green (see archived plan Verification Evidence)
- [x] 6. EVL — n/a as a separate step; verification folded into EXECUTE per the archived plan's Gate: PASS note
- [x] 7. UPDATE PROCESS — plan archived (`7e0d625`); this stub corrected in a later UPDATE PROCESS session (22-07-26) to reflect the true shipped state

---

## Touchpoints

- `apps/web/public/beam/index.html`
- `apps/web/src/app/.well-known/ai-plugin.json/route.ts`
- `apps/web/src/middleware.ts`

---

## Public Contracts

- New public discoverability surfaces only (JSON-LD, manifest route) — no existing contract changed. Shipped.

---

## Verification Evidence

See the archived plan's full Verification Evidence table:
`process/general-plans/completed/evallayer-discoverability_22-07-26/evallayer-discoverability_PLAN_22-07-26.md`

Summary: JSON-LD parse assertion (Fully-Automated) — PASS. Grep constraint check (Fully-Automated)
— PASS. Manifest GET check (Hybrid, live-verified) — PASS. Google Rich Results Test paste-check
(Agent-Probe) — not run; recommended at program closeout.

---

## Resume and Execution Handoff

- Selected plan file path (source of truth): `process/general-plans/completed/evallayer-discoverability_22-07-26/evallayer-discoverability_PLAN_22-07-26.md`
- This stub's path: `process/features/evallayer/active/evallayer_22-07-26/phase-00-discoverability_PLAN_22-07-26.md`
- Last completed step: shipped and archived — phase complete.
- Validate-contract status: VALIDATE explicitly skipped (documented reason in archived plan); no formal validate-contract exists for this phase.
- Next step: none. Program should proceed to Phase 1. If program closeout wants tighter AC12 coverage, schedule the Agent-Probe Rich Results check as a small follow-up task, not a phase re-run.

---

## Validate Contract

**VALIDATE explicitly skipped** for the original SIMPLE plan (documented reason: frontend-only
change, no auth surface identified at PLAN time). Post-hoc correction: this skip reason was
incomplete — a new public `.json` route pulled in a Clerk middleware config change, caught by live
verification and user-approved before applying. No FAIL/BLOCKED state occurred. See the archived
plan's own `## Validate Contract` section for full detail, including the exact gate outcomes.

**Gate: PASS** (with one documented post-hoc supplement — the middleware exemption — applied and
verified within the same EXECUTE pass; no separate PVL cycle was needed).
