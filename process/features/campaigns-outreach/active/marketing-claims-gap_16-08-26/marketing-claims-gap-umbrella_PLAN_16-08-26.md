---
name: plan:marketing-claims-gap-umbrella
description: "Marketing Claims Gap — umbrella/orchestration plan for the 3-phase program closing the gap between Beam's marketing claims and shipped product"
date: 16-08-26
metadata:
  node_type: memory
  type: plan
  feature: campaigns-outreach
  phase: umbrella
---

# Marketing Claims Gap — Umbrella Plan

**Date**: 16-08-26
**Complexity**: COMPLEX
**Status**: 🧪 TESTING — code-complete, pending container-gate closure (WITH_GAPS)

- Program type: PHASE PROGRAM (3 phases + Phase 0 operator precondition)
- Feature folder: `process/features/campaigns-outreach/`
- Task folder: `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/`

---

## Overview

Beam's marketing copy makes three promises the shipped product does not yet keep:

| Claim | Reality today | Phase |
|---|---|---|
| "Book demos from your anonymous traffic" | No booking URL field, no `{{booking_link}}` token, third-party booking links get zero attribution (`link_decorator.py:88` is same-host only) | **Phase 1** |
| "Know which visitors fit your ICP" | `Site.site_profile` ICP JSONB exists (uncommitted) but nothing scores a visitor against it | **Phase 2** |
| "Campaigns learn and adjust automatically" | Sends/opens/clicks/conversions are recorded but nothing feeds them back into planning; no cross-tenant benchmark | **Phase 3** |

This program closes those three gaps in dependency order, smallest first. Every phase ships behind
a feature flag defaulting OFF.

Context read for this plan: `process/context/all-context.md`,
`process/context/planning/all-planning.md`, `process/context/tests/all-tests.md`,
`process/development-protocols/phase-programs.md`.

---

## Program Goal Charter

```
Marketing Claims Gap — Program Goal Charter

North star:
- Every capability Beam's marketing copy promises is either shipped and provable, or the copy is
  reworded to match reality — with zero weakening of the never-auto-send guarantee.

Definition of done (an unattended agent must be able to do all of these):
1. Configure a site's booking URL, have a campaign draft render {{booking_link}}, and see a
   "Demo booked" conversion attributed through the existing ConversionGoal/Conversion stack.
2. Score an identified visitor against that site's reviewed ICP (Site.site_profile) with a
   deterministic pure function, persist the 0-100 icp_fit, and surface it in conviction copy.
3. Read a weekly per-site campaign performance rollup, see a privacy-safe category benchmark line
   in the Monday outcome digest, and see those measured stats injected into the campaign planner
   and auto-drafter prompts.

What "verified" means (program level):
- Fully-Automated gates green (unit + integration under `.venv/bin/python3.11 -m pytest`).
- Hybrid gates run against the real local Postgres on :5433 (Docker IS available at
  /Applications/Docker.app/Contents/Resources/bin/docker — detect via `lsof -nP -iTCP -sTCP:LISTEN`
  on 5433/6379; NEVER classify a container gate as environment-blocked without running that lsof).
- Every gate names its flag-ON precondition explicitly. A gate that passes with the feature flag
  OFF proves nothing (ip-org errata G8/G10 precedent) and does not count.
- Any schema change has a live down/up round-trip on a disposable or local DB.
- validate-contract gates recorded alongside phase gates and regression evidence. A phase without
  a validate-contract (or documented skip reason), and User Confirmation (the user has user-confirmed the behavior) cannot be marked VERIFIED.

Scope tiers → phase mapping:
- Tier 1 "Book a demo" claim → Phase 1
- Tier 2 "ICP fit" claim → Phase 2 (entry-gated on Phase 0)
- Tier 3 "Learns and adjusts" claim → Phase 3
- This program retires Tiers 1-3.

Explicitly out of scope (deferred tier):
- AUTO-SEND of any outreach. Permanent, not a v1 deferral. Marketing copy that says outreach is
  "coordinated automatically" must be REWORDED (to draft-and-approve language), not implemented.
- Auto-adjustment of live/running campaigns. Learning feeds PROMPTS and reports only.
- Reply tracking (no reply model exists anywhere). Backlog note in Phase 3.
- Per-visitor LLM scoring for ICP fit (cost/latency — mirrors conviction.py philosophy).
- Calendly/Cal.com provider webhook ingestion as the primary booking-attribution route (documented
  as v2; the existing HMAC endpoint already supports it).

Hard safety constraints (non-negotiable, per phase):
- NEVER auto-send. campaign_sender.send_campaign_emails stays reachable only after human approval.
  No phase may add a code path that reaches it without that gate. Regression-test the gate.
- NEVER run a bare alembic command. Repo .env DATABASE_URL points at Supabase PRODUCTION and
  migrations/env.py has no local-host guard. Pin DATABASE_URL=postgresql+asyncpg://...@localhost:5433
  in the command environment for every alembic/DB-script invocation. Re-run `alembic heads` LIVE
  before chaining any new revision — concurrent programs move the head.
- Cross-tenant aggregates (Phase 3) store ZERO PII — counts and rates only, keyed by
  (category_normalized, period). If a design would store anything erasable, it must instead be
  reachable by graph_erasure.py's sweep; prefer the zero-PII shape so erasure is moot.
- Opt-in only for any cross-tenant contribution, via the existing Site.contribution_enabled flag.
- Every new capability ships behind a flag defaulting OFF.
- Commit each phase's execution changes before starting the next phase. Keep process/plan/context
  commits separate from execution commits. A concurrent-session rebase has destroyed uncommitted
  work in this repo before — do not leave a phase's output uncommitted.
```

---

## Stable Program Goal (copy-paste this to start autonomous execution)

```
SESSION GOAL: campaigns-outreach — Marketing Claims Gap (3 phases)
Ref: process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/marketing-claims-gap-umbrella_PLAN_16-08-26.md

TARGET: Complete Phases 1-3 until:
- Every phase exit gate green with its flag-ON precondition named
- All schema changes live round-tripped against localhost:5433
- Test tiers: automated (iterate-until-green) / hybrid (fix-if-in-blast-radius) / agent-probe (record-judgment)

AUTONOMY: Before ANY subagent spawn, read:
1. Umbrella ## Current Execution State → loop step + validate-contract status
2. Phase plan ## Phase Loop Progress → first unchecked box = next subagent to spawn

PER-PHASE LOOP (7-step inner loop R -> I -> P -> PVL -> E -> EVL -> UP; never skip, never reorder; SKIPS SPEC — SPEC runs once in the outer program loop):
  1. RESEARCH -> 2. INNOVATE -> 3. PLAN-SUPPLEMENT -> 4. PVL -> 5. EXECUTE -> 6. EVL -> 7. UPDATE-PROCESS
- PLAN-SUPPLEMENT: plan-agent writes research/innovate gaps into the phase plan (or marks "n/a — clean")
- PVL NEVER skipped; contract must follow example-validate-output.md full format; a partial contract
  (missing Plan updates applied / Execute-agent instructions / Test gates) = blocked, same as placeholder
- Every subagent FIRST ACTION: vc-context-discovery (context group files + process/context/tests/all-tests.md
  routing chain) AND vc-plan-discovery (same-feature full depth + other features active + general-plans active)
- Every phase-END: invoke vc-agent-strategy-compare for the next step's strategy recommendation

Report via phase reports. No approval between phases unless a hard stop is hit.

HARD STOPS (pause, wait for user):
- Any alembic/DB command whose DATABASE_URL is not pinned to localhost:5433
- Phase 2 entry while Phase 0 (commit site-analysis working tree) is unmet
- Irreversible/outward-facing action without explicit validate-contract instruction
- Net gate = BLOCKED with no backlog resolution path
- Validate-contract is placeholder and vc-validate-agent cannot run

SAFETY (never override):
- NEVER auto-send. campaign_sender.send_campaign_emails stays behind the human approval gate.
  Auto-send is permanently out of scope; reword marketing copy instead.
- NEVER run bare alembic — repo .env points at Supabase PROD. Pin DATABASE_URL=localhost:5433 and
  re-run `alembic heads` live before chaining a revision.
- Cross-tenant aggregates store zero PII; opt-in via Site.contribution_enabled only.
- Every new capability flag defaults OFF; a gate passing with the flag OFF proves nothing.
- Commit each phase before advancing; process and execution commits separate.

TEST GATES (every phase exit):
  .venv/bin/python3.11 -m pytest tests/unit -q
  .venv/bin/python3.11 -m pytest tests/integration -q
  lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'
  DATABASE_URL=<localhost:5433> .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads
  node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs <phase plan>

VALIDATE CONTRACT: Per-phase contracts written by vc-validate-agent into each phase plan before EXECUTE.

START: Phase 1 (demo booking), loop step 1a-research (pending). Spawn vc-research-agent for Phase 1.
```

---

## Phase Ordering

1. **Phase 0 — operator precondition** (not an agent phase): commit or explicitly freeze the
   uncommitted site-analysis working tree. Blocks Phase 2 only.
2. **Phase 1 — Demo booking.** Smallest, fully independent of Phases 0/2/3. Do first.
3. **Phase 2 — ICP-fit scoring.** Entry-gated on Phase 0.
4. **Phase 3 — Learning loop + benchmarks.** Consumes Phase 1's conversion signal; reads better
   with Phase 2's icp_fit but does not require it.

Phase 1 and Phase 2 are parallel-safe on paper (disjoint files) but are sequenced here because both
add an Alembic revision and the head must be re-derived live between them.

---

## Pre-PVL Conflict Resolution

**Resolved 16-08-26 (outer PVL, gap G-8).** One genuine shared file exists across phases:

| Shared file | Claimed by | Classification | Resolution |
|---|---|---|---|
| `apps/web/src/lib/api-types.ts` | Phase 1, Phase 2 | **reassign — winner: Phase 1** | Phase 1 lands FIRST and OWNS this file for the duration of its EXECUTE. Phase 2's edits to it are **additive-only** (adding `icp_fit?: number` to the visitor detail type — no edits to, or removal of, any Phase 1 field) and are written against Phase 1's landed state. Phase 2 EXECUTE must re-read the file after Phase 1 commits; it must not rebase a stale copy over Phase 1's changes. |
| `apps/api/config.py` | Phase 2 (`icp_fit_enabled`, Step C0), Phase 3 (`campaign_benchmark_enabled`, Step C0b) | **parallel-safe — no reassignment** | Both edits are ADDITIVE-ONLY flag declarations (`: bool = False`) in DISTINCT regions of a 1455-line `Settings` class, and the phases are already strictly sequenced. Neither can hard-fail startup — `model_config` carries `"extra": "ignore"` (`config.py:1455`). Rule: whichever phase lands SECOND must **re-read `config.py` immediately before editing** and append its own declaration; it must never rebase a stale copy over the other phase's declaration. Added 16-08-26 (PVL supplement cycle 4, gap H-8). |

**No further shared files identified** (updated 16-08-26 — `apps/api/config.py` added above). The candidate overlaps listed below are not conflicts:
`apps/api/models/site.py` has a single writer (Phase 1) with Phases 2/3 read-only;
`apps/api/migrations/versions/` is serialized by the live-head re-derivation rule (each phase adds a
distinct new revision file, never edits another phase's); `apps/api/agents/campaign_planner.py` is
Phase 1 + Phase 3, which are already strictly sequenced by the Phase 3 dependency on Phase 1's exit
gate. `apps/api/routers/sites.py` is written by Phase 1 and read-only for Phase 2.

Original candidate-overlap list, retained for reference:
- `apps/api/models/site.py` — Phase 1 adds `booking_url`; Phase 2 reads `site_profile`; Phase 3 reads
  `category` + `contribution_enabled`. Only Phase 1 writes.
- `apps/api/migrations/versions/` — Phases 1, 2, 3 each add one revision. Serialize.
- `apps/api/agents/campaign_planner.py` — Phase 1 adds a token instruction; Phase 3 injects stats.

---

## Phase 0 — Operator Precondition (blocks Phase 2)

The entire site-analysis feature is UNCOMMITTED working-tree code:

- `apps/api/services/site_analysis.py` (new)
- `apps/api/schemas/site_analysis.py` (new)
- `apps/api/services/site_content.py` (new)
- `apps/api/models/site.py` (+5 `site_profile*` columns, modified)
- `apps/api/routers/sites.py` (modified)
- `apps/api/migrations/versions/c5e1a9b73d20_add_site_profile.py` (new)

Phase 2 reads `Site.site_profile` as its sole ICP source. Planning against an uncommitted tree is
unsafe here: a concurrent-session rebase has previously swept untracked files into an unrelated
commit and reverted tracked-file edits in this exact worktree.

**Exit condition (operator, human):** either (a) the six files above are committed on `main`, or
(b) the user explicitly states the tree is frozen for the duration of Phase 2 and accepts the risk.
Record the choice + the commit SHA (if any) in the Phase 2 report before Phase 2 RESEARCH starts.

**Verification:** `git status --short apps/api/services/site_analysis.py apps/api/models/site.py apps/api/migrations/versions/c5e1a9b73d20_add_site_profile.py` returns empty (all committed).

---

## Phase Sequence

| Phase | Plan file | Scope summary | Depends on |
|---|---|---|---|
| 0 (operator) | this file | Commit or freeze the site-analysis working tree | — |
| 1 — Demo booking | `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-1-demo-booking_PLAN_16-08-26.md` | `Site.booking_url`, `{{booking_link}}` token, "Demo booked" ConversionGoal preset, third-party-link attribution hole locked as documented behavior | — |
| 2 — ICP-fit scoring | `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-2-icp-fit-scoring_PLAN_16-08-26.md` | Pure deterministic `icp_fit` 0-100 scorer against `Site.site_profile`, persisted on `IdentifiedVisitor`, surfaced in conviction copy | Phase 0 |
| 3 — Learning loop + benchmarks | `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-3-learning-loop-benchmarks_PLAN_16-08-26.md` | Per-site campaign stats rollup, zero-PII cross-tenant category benchmark, stats injected into planner/auto-drafter prompts + Monday digest | Phase 1 |

### Join Conditions

- Phase 1 may start immediately (no dependency).
- Phase 2 MUST NOT start until Phase 0's exit condition is recorded.
- Phase 3 MUST NOT start until Phase 1's exit gate passes (it consumes the conversion signal).
- Each phase's Alembic revision MUST be chained off a LIVE-derived head, not a head recorded here.

---

## Per-Phase Entry / Exit Gates

| Phase | Entry | Exit gate |
|---|---|---|
| 0 | Program start | site-analysis files committed (or freeze explicitly accepted + recorded) |
| 1 | Program start | `booking_url` migration round-tripped on :5433; `{{booking_link}}` renders in a draft; third-party-host non-decoration test asserts the documented hole; goal-preset endpoint returns a "Demo booked" goal; unit+integration suites green |
| 2 | Phase 0 recorded | `icp_fit` scorer unit suite green incl. the null/flag-off cases; migration round-tripped; conviction clause renders only when `site_profile` is present; no new JSONB content-query added |
| 3 | Phase 1 exit met | Benchmark job produces rows for a category only at `site_count >= k`; benchmark row contains zero PII (asserted); planner/auto-drafter prompt injection covered by a test with the flag ON; digest line renders; send gate regression test green |

---

## Per-Phase Loop

Each phase executes the canonical 7-step inner loop `R → I → P → PVL → E → EVL → UP`. This inner
loop SKIPS SPEC — SPEC runs once in the outer program loop, not per phase.

1. **RESEARCH** — research-agent: load context, read prior phase reports, check plan drift, document findings
2. **INNOVATE** — innovate-agent: decide approach; write Decision Summary (chosen + rejected)
3. **PLAN-SUPPLEMENT** — plan-agent: add research/innovate gaps to this phase plan, or mark "n/a — research clean"
4. **PVL** — vc-validate-agent: full V1–V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md` format
5. **EXECUTE** — vc-execute-agent per the approved plan and validate-contract
6. **EVL** — vc-tester: re-run phase test gates independently to green; register follow-up stubs; write EVL HANDOFF SUMMARY
7. **UPDATE-PROCESS** — write the phase report to the durable path, rewrite this file's `## Current Execution State` (overwrite, not append — git history is the audit log)

**PVL is NEVER skipped.** A placeholder `## Validate Contract` = blocked.

---

## Autonomous Execution Rules (During /goal)

- Agent self-decides at all V5 gates — no user approval between phases.
- CONDITIONAL net gate: proceed autonomously, fixes applied in-flight, gaps on record.
- BLOCKED net gate: write a backlog note, continue with remaining phases; backlog is always a valid
  resolution.
- Hard stops (pause for user): any unpinned alembic/DB invocation; Phase 2 entry with Phase 0 unmet;
  irreversible/outward-facing action without explicit contract instruction; any change that would
  make outreach send without human approval.
- The phase report is the communication channel for conflicts, errors, and learnings.

---

## Global Constraints

- Never auto-send. `campaign_sender.send_campaign_emails` stays reachable only after the human
  approval gate; a regression test asserting this is required in every phase touching the send path.
- Never run bare alembic — `.env` `DATABASE_URL` points at Supabase PROD and `migrations/env.py`
  has no local-host guard. Pin `DATABASE_URL` to `localhost:5433` and re-run `alembic heads` live.
- Every new feature flag defaults OFF; every test gate names its flag-ON precondition.
- Cross-tenant aggregates store zero PII and are opt-in via `Site.contribution_enabled`.
- No per-visitor LLM calls on a hot path.
- Do not add JSONB content-queries against `Site.site_profile` (its migration assumed none). Score
  in Python, or plan a GIN index explicitly with rationale.
- Commit each phase's execution changes before starting the next phase. Keep process/plan/context
  commits separate from execution commits.

---

## Durable Report Destinations

| Phase | Report path (flat, inside the program task folder) |
|---|---|
| 1 — Demo booking | `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-1-demo-booking_REPORT_16-08-26.md` |
| 2 — ICP-fit scoring | `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-2-icp-fit-scoring_REPORT_16-08-26.md` |
| 3 — Learning loop | `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-3-learning-loop-benchmarks_REPORT_16-08-26.md` |

---

## Program Status Table

| Phase | Status |
|---|---|
| 0 — Operator precondition (commit site-analysis) | ✅ COMPLETE (decision recorded in Phase 2 report) |
| 1 — Demo booking | 🧪 TESTING (CODE DONE + EVL-green; WITH_GAPS — Hybrid gates blocked) |
| 2 — ICP-fit scoring | 🧪 TESTING (CODE DONE + EVL-green; WITH_GAPS — Hybrid gates blocked) |
| 3 — Learning loop + benchmarks | 🧪 TESTING (CODE DONE + EVL-green; WITH_GAPS — Hybrid gates blocked) |

Status values: ⏳ PLANNED | 🔨 CODE DONE | 🧪 TESTING | ✅ VERIFIED | 🚧 BLOCKED | ✅ COMPLETE

---

## Implementation Checklist (program level)

- [ ] P0. Operator commits or explicitly freezes the site-analysis working tree; record SHA/decision
- [ ] P1. Run Phase 1 inner loop to VERIFIED; commit; update this file's Current Execution State
- [ ] P2. Run Phase 2 inner loop to VERIFIED; commit; update Current Execution State
- [ ] P3. Run Phase 3 inner loop to VERIFIED; commit; update Current Execution State
- [ ] P4. Marketing copy reconciliation pass: reword any "coordinated automatically" / auto-send
      implication in `apps/web/public/beam/index.html`, `PRODUCT_ROADMAP.md`, and landing copy to
      draft-and-approve language. This is a copy edit, not a code change.
- [ ] P5. Archive the program task folder to `process/features/campaigns-outreach/completed/`

---

## Touchpoints

- `apps/api/models/site.py` — `booking_url` (P1), reads `site_profile` (P2), `category`/`contribution_enabled` (P3)
- `apps/api/services/campaign_sender.py` — `_personalize` token (P1); send gate untouched
- `apps/api/services/link_decorator.py` — read-only in P1; behavior deliberately unchanged
- `apps/api/services/conversion_tracker.py`, `apps/api/routers/outcomes.py` — goal preset (P1)
- new `apps/api/services/icp_fit.py`, `apps/api/services/conviction.py` (P2)
- `apps/api/services/visitor_aggregator.py`, `apps/api/models/visitor.py` (P2)
- new benchmark model/service, `apps/api/jobs/scheduler.py`, `apps/api/services/outcome_digest.py`,
  `apps/api/agents/campaign_planner.py`, `apps/api/services/auto_drafter.py` (P3)
- three new Alembic revisions under `apps/api/migrations/versions/`

---

## Public Contracts

- `POST /api/v1/campaigns/...` send path behavior unchanged — human approval still required.
- `link_decorator.decorate_links` behavior unchanged (same-host only) — the third-party gap is
  documented and test-locked, not fixed, in Phase 1.
- Existing `ConversionGoal` / `Conversion` / `CampaignClick` schemas unchanged; Phase 1 adds a
  preset creation convenience only.
- `VisitorOut` / `VisitorDetailOut`: Phase 2 adds `icp_fit` as an OPTIONAL field. Detail-only fields
  go on `VisitorDetailOut`, never on `VisitorOut` (the P0 `GET /visitors` 500 precedent).
- `/api/v1/outcomes/{site_id}/report` gains additive fields in Phase 3; no field removed.
- All new endpoints/fields are additive and flag-gated.

---

## Blast Radius

Risk class: **schema/migration** (3 revisions) + **public API contract** (additive fields) +
**cross-tenant data** (Phase 3 aggregate). No auth, no billing, no secrets.

Roughly 6-9 files per phase plus one migration each; approx 25 files across the program.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `.venv/bin/python3.11 -m pytest tests/unit -q` exits 0 | Fully-Automated | No regression across all three phases |
| `.venv/bin/python3.11 -m pytest tests/integration -q` exits 0 (Postgres on :5433 up) | Hybrid | Router/DB behavior of each phase's new surface |
| Migration live down/up round-trip per phase with `DATABASE_URL` pinned to localhost:5433 | Hybrid | Schema changes are reversible; no prod exposure |
| Send-gate regression test: no new call path reaches `send_campaign_emails` without approval | Fully-Automated | Hard safety constraint "never auto-send" |
| `lsof -nP -iTCP -sTCP:LISTEN \| grep -E '5433\|6379'` shows listeners before any Hybrid gate | Hybrid precondition | Container gates are actually runnable (Docker CLI is off PATH; never mark environment-blocked without this) |
| `node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs <each phase plan>` exits 0 | Fully-Automated | Plan artifacts stay structurally valid across supplements |

Per-phase evidence tables live in the phase plans. Testing context:
`process/context/tests/all-tests.md`.

---

## Test Infra Improvement Notes

- No `test_conviction*.py` exists anywhere in the repo despite `conviction.py` being consumed by the
  dashboard. Phase 2 should create it rather than extend an absent file.
- No test currently asserts that `link_decorator` skips third-party hosts. Phase 1 adds one so the
  known hole is documented behavior rather than an accident.
- Flag-off vacuity is a repeated failure mode here (ip-org errata G8/G10). Every phase's gates must
  name the flag-ON precondition inline.

---

## Resume and Execution Handoff

1. Selected plan file path: `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/marketing-claims-gap-umbrella_PLAN_16-08-26.md`
2. Last completed phase or step: Phase 0 planning (this umbrella + 3 phase plans written)
3. Validate-contract status: pending — vc-validate-agent writes one per phase before EXECUTE
4. Supporting context files loaded: `process/context/all-context.md`,
   `process/context/planning/all-planning.md`, `process/context/tests/all-tests.md`,
   `process/development-protocols/phase-programs.md`
5. Next step for a fresh agent: read this umbrella, then
   `phase-1-demo-booking_PLAN_16-08-26.md`, then spawn vc-research-agent for Phase 1 loop step 1
   (RESEARCH). Do NOT `ENTER EXECUTE MODE` for any phase until that phase's PVL has written a full
   validate-contract.

---

## Current Execution State

Last updated: 17-08-26
Current phase: 3 of 3 (all agent phases complete)
Phase 3 name: Learning loop + benchmarks
Phase 3 status: EXECUTED + EVL-green — classification WITH_GAPS (as are Phases 1 and 2)
Phase 3 EVL: PASS-WITH-GAPS / HALTED_SUCCESS (1 cycle; independent vc-tester)
Phase 3 report: process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-3-learning-loop-benchmarks_REPORT_16-08-26.md
Next phase: none — remaining work is operator-side container-gate closure (see
  process/features/campaigns-outreach/backlog/marketing-claims-gap-container-gates_NOTE_16-08-26.md),
  the execution commit (vc-git-manager), and umbrella checklist P4 (marketing copy pass)
Program status: code-complete, pending container-gate closure — all 3 phases EXECUTED +
  EVL-green, classification WITH_GAPS; every Hybrid/flag-ON gate unrun (Docker daemon down all
  session); no plan archived — task folder stays in active/ until flag-ON gates pass
  (vacuous-green ban / ip-org G8/G10 precedent). Program closeout:
  marketing-claims-gap_REPORT_16-08-26.md (this folder)

Loop step values: RESEARCH | INNOVATE | PLAN-SUPPLEMENT | PVL | EXECUTE | EVL | UPDATE-PROCESS
Orchestrator rule: read "Current loop step" and "validate-contract status" before spawning any
subagent. Never spawn execute-agent when the loop step is RESEARCH, INNOVATE, PLAN-SUPPLEMENT, or PVL.

Note: the Stable Program Goal above is fixed. This section is the only part that changes —
update-process-agent rewrites it after every phase closeout (overwrite, not append).

---

## Phase Loop Progress

Tracked per phase in each phase plan file. This umbrella tracks program-level progress only via
`## Program Status Table` and `## Current Execution State`.

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
