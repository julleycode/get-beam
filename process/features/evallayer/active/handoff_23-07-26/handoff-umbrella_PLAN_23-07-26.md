---
name: plan:handoff-umbrella
description: "Handoff Detection — umbrella/orchestration plan for the 4-phase program (H1-H4)"
date: 23-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: umbrella
---

# Handoff Detection — Umbrella Plan

**Date:** 23-07-26
**Complexity:** COMPLEX
**Status:** ⏳ PLANNED

- Program type: PHASE PROGRAM (4 phases, H1 foundation → H2/H3 fan on H1 → H4 independent-gated)
- SPEC (governs all phases, INNER loop skips SPEC): `process/features/evallayer/active/handoff_23-07-26/handoff_SPEC_23-07-26.md`
- Feature folder: `process/features/evallayer/`
- Predecessor program (shipped, code-complete): `process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md`

---

## Program Goal Charter

```
Handoff Detection — Program Goal Charter

North star:
- Connect the two facts Beam already knows separately — "an AI agent fetched this page on
  someone's behalf" and "a human just clicked through from that same agent" — into one linked
  signal, and surface live intent the moment someone is actively asking an AI agent about the
  product, without ever weakening the outreach-exclusion guardrail that keeps agent records
  unemailable.

Definition of done (an unattended agent must be able to do all of these):
1. Record every AI-agent HTTP hit as an individually timestamped row (not just a rollup), tagged
   on-demand vs index, with zero new synchronous ingest-path calls (H1).
2. Correlate an on-demand fetch with a same-page human AI-referral click inside a bounded window
   into a new, structurally separate `agent_handoff_links` table, surfaced on the visitor detail
   view with a confidence-qualified badge — while proving in one regression test that the linked
   human stays fully emailable and the linked agent-fetch record never becomes emailable (H2).
3. Deliver near-real-time "someone is asking an AI agent about your pricing right now" alerts,
   rolling-window spike detection, and company-level (never person-level) AI-research-before-lead
   correlation metadata that never triggers outreach on its own (H3).
4. Produce a written, keyword-bearing VIABLE/NOT-VIABLE/INCONCLUSIVE feasibility VERDICT for
   citation-watermarking via one manual, double-opt-in live probe — with implementation gated
   strictly behind a VIABLE verdict plus explicit user sign-off (H4).

What "verified" means (program level):
- Every phase's own ACs are green per its validate-contract AND a regression check confirms no
  drift in the shipped EvalLayer (agent_visits rollup) or AI-Referral (`ai_source`) test suites.
- AC-H2-3 (both-directions emailability separation) is the single highest-priority gate in this
  program — H2 cannot be marked VERIFIED without it passing, mirroring EvalLayer's AC10 discipline.
- H4 is "done" once the VERDICT artifact exists with a recorded keyword — regardless of outcome;
  it is never blocked on delivering a shipped watermark feature.
- A phase without a validate-contract (or documented skip reason) cannot be marked VERIFIED.

Scope tiers → phase mapping:
- Tier 1 (foundation: per-hit events + tiering) → Phase 1 (H1)
- Tier 2 (correlation: handoff links + dashboard badge) → Phase 2 (H2)
- Tier 3 (live intent: alerts + spike + company correlation) → Phase 3 (H3)
- Tier 4 (gated feasibility probe, conditional implementation) → Phase 4 (H4)
- This program retires the "agent visit ↔ human click are two disconnected facts" gap and the
  "no live intent signal from AI-mediated research" gap.

Explicitly out of scope (deferred tier):
- Google-Extended / Applebot-Extended / Microsoft Copilot handoff or intent coverage (no
  documented on-demand token exists for these vendors).
- De-anonymizing a human purely from an index-crawl hit; index-tier hits are structurally
  ineligible for H2/H3, not a future toggle.
- Emailing/contacting any agent-fetch record at any confidence level (AC-H2-3 is the proof).
- Building the full "agent visits over time" daily-chart dashboard card (H1 unblocks it; shipping
  it is optional backlog — see `phase-06-daily-timeseries_NOTE_22-07-26.md`).
- Implementing citation-watermarking before H4 returns VIABLE + explicit user sign-off.
- Any cloaking/UA-sniffing content-variation technique, regardless of H4's outcome.
- Person-level claims from H3 signals; new identity-resolution providers; live (non-mocked)
  IP-range/rDNS re-verification (already covered, EvalLayer Phase 4).

Hard safety constraints (non-negotiable, per phase):
- Handoff links live on a NEW, structurally separate surface (`agent_handoff_links` table) —
  NEVER on `source_agent_visit_id` or any field the Phase 7 outreach-exclusion guardrail
  inspects. A handoff-linked human visitor is unconditionally fully emailable; the linked
  agent-fetch record is unconditionally never emailable. Both directions proven by ONE test
  (AC-H2-3) — this is the program's highest-priority gate.
- Every correlation link and every UI rendering of it carries `confidence` + `method`; never
  presented as certainty.
- Multi-tenancy unchanged: every new query filters by `site_id`; foreign/unknown ids return 404,
  never 403.
- H1's per-hit write is fail-open and cheap — no new synchronous external call added to the
  ingest hot path. H2 correlation and H3 intent detection run as periodic/async jobs
  (`apps/api/jobs/scheduler.py` pattern), never inline in ingest.
- No new PII; `do_not_resolve`/GPC behavior unchanged; H3 signals are account/site-level only,
  never person-level.
- Any new external call (only relevant if H4 ever reaches implementation) ships a
  `MOCK_EXTERNAL_APIS=true` deterministic path before being marked verified.
- H4's live-provider probe requires explicit double opt-in (billed/live 3rd-party call) —
  NEVER auto-run under `/goal`; this is a hard stop, not a routine PVL feasibility probe.
- Commit each phase's execution changes before starting the next phase. Keep process/plan/
  context commits separate from execution commits.
```

---

## Stable Program Goal (copy-paste this to start autonomous execution)

```
SESSION GOAL: evallayer — Handoff Detection
Ref: process/features/evallayer/active/handoff_23-07-26/handoff-umbrella_PLAN_23-07-26.md
SPEC (governs all phases): process/features/evallayer/active/handoff_23-07-26/handoff_SPEC_23-07-26.md

TARGET: Complete ALL 4 phases until:
- H1: agent_fetch_events row per hit, correct on-demand/index tier, ingest hot path unaffected
- H2: agent_handoff_links created within window/vendor-family; AC-H2-3 emailability-separation
  regression GREEN (highest-priority gate); dashboard badge renders confidence-qualified copy
- H3: on-demand commercial-page alert fires; spike detector fires on synthetic rate increase;
  company-correlation signal is read-only metadata, never a new outreach trigger; no person-level
  claim; site-scoped
- H4: VERDICT artifact written with VIABLE/NOT-VIABLE/INCONCLUSIVE keyword (implementation only
  if VIABLE + explicit sign-off)
- Test tiers: automated (iterate-until-green) / hybrid (fix-if-in-blast-radius) / agent-probe
  (record-judgment) / H4 probe (needs-live-provider, double opt-in, hard stop)

AUTONOMY: Before ANY subagent spawn, read:
1. Umbrella ## Current Execution State → loop step + validate-contract status
2. Phase plan ## Phase Loop Progress → first unchecked box = next subagent to spawn

PER-PHASE LOOP (7-step inner loop `R → I → P → PVL → E → EVL → UP`, never skip, never reorder;
SKIPS SPEC — the SPEC above governs every phase, already locked):
  1. RESEARCH → 2. INNOVATE → 3. PLAN-SUPPLEMENT → 4. PVL → 5. EXECUTE → 6. EVL → 7. UPDATE-PROCESS
- PLAN-SUPPLEMENT: plan-agent writes research/innovate gaps into phase plan (or marks "n/a —
  research clean")
- PVL NEVER skipped; contract must follow example-validate-output.md full format; partial
  contract (missing Plan updates applied / Execute-agent instructions / Test gates) = blocked
  same as placeholder
- Every subagent FIRST ACTION: run vc-context-discovery (load context group files +
  process/context/tests/all-tests.md routing chain) AND vc-plan-discovery (same-feature full
  depth active/backlog/completed/reports/refs + other features active-only + general-plans active)
- Every phase-END: invoke vc-agent-strategy-compare for next step strategy recommendation

Report via phase reports. No approval between phases unless hard stop hit.

HARD STOPS (pause, wait for user):
- H4's live-provider probe (needs-live-provider, double opt-in) — ALWAYS pauses, never auto-run
- Any AC-H2-3 gate failure that cannot be resolved without touching source_agent_visit_id or the
  Phase 7 guardrail
- Net gate = BLOCKED with no backlog resolution path
- Plan file marks "pause required" or agent count > 100
- Validate-contract is placeholder and vc-validate-agent cannot run

SAFETY (never override):
- Handoff links never touch source_agent_visit_id / is_emailable_identity inputs; both
  directions of AC-H2-3 proven by one test before H2 is VERIFIED
- H1 write is fail-open, no new sync external call in ingest hot path
- H3 signals are site/company-scoped only, never person-level, never an auto-outreach trigger
- H4 implementation only on VIABLE verdict + explicit user sign-off; no silent implementation
- Commit each phase before advancing; process and execution commits separate

TEST GATES (every phase exit):
  cd /Users/apple/getbeam && python -m pytest tests/unit/test_agent_fetch_events.py -v
  cd /Users/apple/getbeam && python -m pytest tests/unit/test_handoff_correlation.py -v
  cd /Users/apple/getbeam && python -m pytest tests/unit/test_handoff_emailability_separation.py -v
  cd /Users/apple/getbeam && python -m pytest tests/unit/test_intent_alerts.py -v
  cd /Users/apple/getbeam && python -m pytest tests/unit/ tests/integration/ -q   # full regression, incl. EvalLayer + AI-Referral suites

VALIDATE CONTRACT: Per-phase contracts written by vc-validate-agent into each phase plan before EXECUTE.

START: Phase 1 (H1), loop step RESEARCH (pending). Spawn vc-research-agent for Phase 1.
```

---

## Phase Sequence

| Phase | Plan file | Scope summary | Depends on |
|---|---|---|---|
| 0 (pre-program) | this file | Confirm folder structure, baseline audit, create sub-phase plans | — |
| 1 — Per-hit fetch events + tiering (H1) | `process/features/evallayer/active/handoff_23-07-26/phase-01-fetch-events-tiering_PLAN_23-07-26.md` | New `agent_fetch_events` table + migration; on-demand-vs-index tier read off existing `_VENDOR_TOKENS`; fail-open write from ingest branch | Phase 0 |
| 2 — Handoff correlation + dashboard (H2) | `process/features/evallayer/active/handoff_23-07-26/phase-02-handoff-correlation_PLAN_23-07-26.md` | Periodic sweep joining on-demand fetches ↔ AI-referral clicks → `agent_handoff_links`; visitor-detail badge; AC-H2-3 emailability regression (program's highest-priority gate) | Phase 1 |
| 3 — Intent signals (H3) | `process/features/evallayer/active/handoff_23-07-26/phase-03-intent-signals_PLAN_23-07-26.md` | Live on-demand commercial-page alert (reuse `hot_alert.py`); rolling-window spike detector; company-correlation metadata (never a new outreach trigger) | Phase 1 (parallel-safe with Phase 2 — see Blast Radius note below) |
| 4 — Citation-watermark feasibility (H4) | `process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_PLAN_23-07-26.md` | Manual-first, double-opt-in live probe (VC-FEASIBILITY-PROBE-NEEDED, cost-class needs-live-provider); VERDICT artifact; conditional implementation only on VIABLE + sign-off | Phase 1 (serving infra only — probe itself has no phase dependency beyond H1's test-page infra if any is reused) |

### Join Conditions

- Phase 1 MUST NOT start until Phase 0 exit gate passes (this umbrella + phase stubs created and validated).
- Phase 2 MUST NOT start until Phase 1 exit gate passes (agent_fetch_events + tiering shipped, tests green).
- Phase 3 MAY start once Phase 1 exit gate passes — Phase 3's blast radius (`apps/api/services/`
  new intent-signal module + `apps/api/jobs/scheduler.py` wiring + `hot_alert.py` reuse) is
  currently assessed disjoint from Phase 2's blast radius (`agent_handoff_links` model/migration
  + dashboard visitor-detail component). Both phases depend only on Phase 1, not on each other.
  **Pre-PVL Conflict Resolution below reconciles this at outer PVL time before either executes.**
- Phase 4 (H4) has no hard phase dependency for the probe itself (it is a manual live-provider
  probe against a Beam-owned test page); it depends on Phase 1 only if the probe reuses H1's
  event-tagging infra for the test page. Phase 4 is a HARD STOP regardless of phase ordering —
  it always pauses for double opt-in before dispatch.

---

## Pre-PVL Conflict Resolution

Phase 2 and Phase 3 both depend only on Phase 1 and were initially assessed as parallel-safe
(disjoint blast radii: Phase 2 touches `agent_handoff_links` model/migration + visitor-detail
dashboard component + a new correlation-sweep service; Phase 3 touches a new intent-signal
service + `apps/api/jobs/scheduler.py` wiring + `hot_alert.py` reuse + agents-dashboard widgets).

Both phases DO share one file: `apps/api/jobs/scheduler.py` (Phase 2's correlation sweep and
Phase 3's spike-detector sweep are each registered as new periodic jobs in this same file).

- **Classification: `reassign`.** Phase 2 registers its sweep job in `scheduler.py` first (Phase
  2 executes before Phase 3 in the phase sequence below); Phase 3's INNOVATE/PLAN-SUPPLEMENT step
  must re-read `scheduler.py` post-Phase-2 and add its own job registration additively (new
  function + new `add_job(...)` call), never editing Phase 2's registration block.
- All other files across Phase 2 and Phase 3 blast radii are classified `parallel-safe` (no
  further overlap found this session).
- This resolution is written here by the plan-agent as a placeholder; the orchestrator (or the
  Phase 2/3 research-agents at their respective RESEARCH steps) MUST re-verify `scheduler.py`'s
  actual line-level diff state before Phase 3 EXECUTE, since Phase 2 may add helper functions
  Phase 3 also needs to reference.

No other package conflicts identified across all 4 phases at this planning pass.

---

## Per-Phase Entry / Exit Gates

| Phase | Entry | Exit gate |
|---|---|---|
| 0 | Program start | Umbrella + 4 phase stub plans created; template validators pass |
| 1 (H1) | Phase 0 complete | AC-H1-1/2/3 green; `agent_fetch_events` row per hit; correct tier; ingest hot-path latency unaffected; rollup (`agent_visits`) upsert unchanged; EvalLayer regression suite green |
| 2 (H2) | Phase 1 exit met | AC-H2-1/2/3/4/5 green; AC-H2-3 (both-directions emailability separation) is the hard gate — cannot be VERIFIED without it; visitor-detail badge renders confidence-qualified copy |
| 3 (H3) | Phase 1 exit met (parallel-safe with Phase 2 per Pre-PVL resolution) | AC-H3-1/2/3/4 green; alert/spike/company-correlation signals never trigger outreach; site-scoped; no person-level claim |
| 4 (H4) | Phase 1 exit met (loosely; probe itself is independent) | VERDICT artifact written with recorded keyword; if VIABLE + user sign-off, conditional implementation checklist executes; otherwise phase is complete once VERDICT is recorded |

---

## Per-Phase Loop

Each phase executes the canonical 7-step inner loop `R → I → P → PVL → E → EVL → UP`. This inner
loop SKIPS SPEC — the SPEC (`handoff_SPEC_23-07-26.md`) governs every phase and is already
locked; it runs once at the program level, not per phase. The 7 steps map to:

1. **RESEARCH** — spawn research-agent: load context, read prior phase reports, check plan drift, document findings
2. **INNOVATE** — spawn innovate-agent: decide approach (resolve the SPEC's `assumption-confirm` defaults for that phase); write Decision Summary (chosen approach + rejected alternatives)
3. **PLAN-SUPPLEMENT** — spawn plan-agent: if research/innovate found gaps/pre-conditions not in checklist, add them; otherwise mark "n/a — research clean"
4. **PVL** — spawn vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md` format (Status / Gate / Plan updates applied / Execute-agent instructions / Test gates / High-risk pack / Backlog artifacts / Known gaps / Accepted by). **Phase 4's V2 fan-out will very likely emit `VC-FEASIBILITY-PROBE-NEEDED` for the watermark hypothesis itself — this is expected and routes per `orchestration.md` §VC-FEASIBILITY-PROBE-NEEDED Signal Routing, resolving the `needs-live-provider` cost-class gate (double opt-in) before vc-debugger dispatches.**
5. **EXECUTE** — spawn vc-execute-agent per approved plan and validate-contract
6. **EVL** — spawn vc-tester: run phase test gates to green; register follow-up stubs; write EVL HANDOFF SUMMARY
7. **UPDATE-PROCESS** — write phase report to durable report path, rewrite umbrella `## Current Execution State` section (overwrite, not append — git history is the audit log)

**PVL is NEVER skipped.** A placeholder `## Validate Contract` = blocked. Do not spawn
execute-agent while the Validate Contract section reads "(placeholder — vc-validate-agent
writes this section before EXECUTE)".

**Phase 4 special note:** H4's probe is distinct from a routine feasibility signal — it is
declared a HARD STOP in the Stable Program Goal above regardless of the VC-FEASIBILITY-PROBE-NEEDED
routing outcome. Even if the routing mechanism would otherwise auto-resolve under `/goal`, the
`needs-live-provider` cost-class always requires explicit double opt-in per SPEC Constraint 7.

---

## Autonomous Execution Rules (During /goal)

During /goal execution of a phase program:
- Agent self-decides at all V5 gates — no user approval needed between phases
- CONDITIONAL net gate: proceed autonomously, fixes applied in-flight, gaps on record
- BLOCKED net gate: document items in backlog, continue with remaining phase plans; backlog is always a valid resolution — always find a path forward
- Hard stops (must pause for user approval):
  - Irreversible/outward-facing action without explicit contract instruction (push to remote, deploy to production, schema migration on live DB)
  - H4's live-provider probe (needs-live-provider cost-class) — always pauses, per SPEC Constraint 7
  - Plan file explicitly marks "pause required" at a step
- Agent writes phase reports, updates phase plans, creates new sub-plans as needed — all autonomously
- The phase report is the communication channel for conflicts, errors, and learnings — not inline questions

---

## Global Constraints

- Never touch `source_agent_visit_id` or the `is_emailable_identity` decision logic in
  `apps/api/services/identity_classification.py` from any phase in this program — AC-H2-3 proves
  this via regression, extending the shipped `test_agent_origin_exclusion.py` pattern.
- Never widen H1's ingest hot path with a new synchronous external call — H1's write must remain
  fail-open per Constraint 4.
- H3 signals never independently create, approve, or auto-send a campaign — read-only metadata
  only.
- H4 implementation code path must not exist unless a VIABLE verdict + explicit user sign-off is
  on record — verified at program closeout (AC-H4-2).
- After every phase that touches agent files, run the parity validator suite and confirm it exits
  0 before declaring phase DONE.
- Commit each phase's execution changes before starting the next phase. Keep process/plan/context
  commits separate from execution commits.
- Zero regressions in existing EvalLayer (agent-visit rollup) and AI-Referral (`ai_source`) test
  suites — both are read-only dependencies for this program, never modified.

---

## Durable Report Destinations

| Phase | Report path (inside task folder) |
|---|---|
| 0 (pre-program) | `process/features/evallayer/active/handoff_23-07-26/phase-00-umbrella-scaffold_REPORT_23-07-26.md` |
| 1 — Fetch events + tiering (H1) | `process/features/evallayer/active/handoff_23-07-26/phase-01-fetch-events-tiering_REPORT_23-07-26.md` |
| 2 — Handoff correlation (H2) | `process/features/evallayer/active/handoff_23-07-26/phase-02-handoff-correlation_REPORT_23-07-26.md` |
| 3 — Intent signals (H3) | `process/features/evallayer/active/handoff_23-07-26/phase-03-intent-signals_REPORT_23-07-26.md` |
| 4 — Watermark feasibility (H4) | `process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_REPORT_23-07-26.md` |

---

## Program Status Table

| Phase | Status |
|---|---|
| 0 — Pre-program (plan creation) | ✅ COMPLETE |
| 01 — Fetch events + tiering (H1) | 🔨 CODE DONE (Docker gaps) |
| 02 — Handoff correlation (H2) | 🔨 CODE DONE (Docker gaps) |
| 03 — Intent signals (H3) | ⏳ PLANNED |
| 04 — Watermark feasibility (H4) | ⏳ PLANNED |

Status values: ⏳ PLANNED | 🔨 CODE DONE | 🧪 TESTING | ✅ VERIFIED | 🚧 BLOCKED | ✅ COMPLETE

---

## Touchpoints

- `apps/api/models/` — new `agent_fetch_event.py` (H1), new `agent_handoff_link.py` (H2)
- `apps/api/migrations/versions/` — new migrations for `agent_fetch_events` (H1) and
  `agent_handoff_links` (H2)
- `apps/api/services/agent_classifier.py` — read-only tier lookup extension (H1); no rewrite of
  `_VENDOR_TOKENS`
- `apps/api/services/agent_visit_persistence.py` — additive per-hit write alongside existing
  rollup upsert (H1)
- `apps/api/routers/events.py` — additive call into new per-hit persistence (H1)
- `apps/api/jobs/scheduler.py` — two new periodic job registrations (H2 correlation sweep, H3
  spike-detector sweep) — see Pre-PVL Conflict Resolution
- `apps/api/services/` — new handoff-correlation service (H2), new intent-signal service (H3)
- `apps/api/services/hot_alert.py` — reused (not modified) for H3 alert delivery, pending
  INNOVATE confirmation
- `apps/api/services/identity_classification.py` — READ-ONLY reference only; never modified
- `apps/web/src/app/dashboard/visitors/` — visitor-detail badge (H2)
- `apps/web/src/app/dashboard/agents/page.tsx` — agents-side surfacing (H2/H3)
- `apps/web/src/app/(public or internal test)/` — H4's controlled test page (if net-new)
- `tests/unit/test_agent_fetch_events.py` (H1, new), `tests/unit/test_handoff_correlation.py`
  (H2, new), `tests/unit/test_handoff_emailability_separation.py` (H2, new),
  `tests/unit/test_intent_alerts.py` (H3, new)

---

## Public Contracts

- Existing `agent_visits` rollup table, `agent_classifier.py::classify_agent()` signature, and
  `is_emailable_identity()` contract are unchanged — H1/H2/H3 read from or extend adjacent to
  them, never modify their existing behavior.
- Existing `ai_source` / `first_touch_referrer` fields on `Visitor` are unchanged (read-only
  dependency for H2's correlation sweep).
- New `agent_fetch_events` (H1) and `agent_handoff_links` (H2) tables are additive; no existing
  API response shape changes unless a phase's INNOVATE explicitly adds new optional fields
  (documented in that phase's plan).
- `hot_alert.py`'s existing delivery contract is reused, not altered, by H3 (pending INNOVATE
  confirmation of exact integration point).

---

## Blast Radius

Files directly modified or created (aggregate across all 4 phases — see per-phase plans for
exact per-phase splits):

- H1: `apps/api/models/agent_fetch_event.py` (new), 1 new migration, `agent_classifier.py`
  (tier-lookup addition), `agent_visit_persistence.py` (additive write), `routers/events.py`
  (additive call), `tests/unit/test_agent_fetch_events.py` (new)
- H2: `apps/api/models/agent_handoff_link.py` (new), 1 new migration, new correlation-sweep
  service, `apps/api/jobs/scheduler.py` (new job registration), visitor-detail dashboard
  component, agents-page surfacing, `tests/unit/test_handoff_correlation.py` (new),
  `tests/unit/test_handoff_emailability_separation.py` (new)
- H3: new intent-signal service, `apps/api/jobs/scheduler.py` (new job registration, additive
  after H2's), `hot_alert.py` (reused), dashboard widget(s),
  `tests/unit/test_intent_alerts.py` (new)
- H4: no code blast radius unless VIABLE + sign-off; probe artifact only:
  `process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_FEASIBILITY_{date}.md`

Risk class: H2 and H3 touch no auth/billing/schema-migration-of-existing-data surfaces (both are
purely additive new tables/services); H1's migration is additive-only (new table, no column
changes to existing tables). H4 is the program's only "needs-live-provider" risk class item.

---

## Verification Evidence

```bash
# H1
cd /Users/apple/getbeam && python -m pytest tests/unit/test_agent_fetch_events.py -v
# Expected: all pass, includes tier-classification + fail-open isolation cases

# H2
cd /Users/apple/getbeam && python -m pytest tests/unit/test_handoff_correlation.py tests/unit/test_handoff_emailability_separation.py -v
# Expected: all pass; emailability-separation test is the hard gate (both directions asserted)

# H3
cd /Users/apple/getbeam && python -m pytest tests/unit/test_intent_alerts.py -v
# Expected: all pass, includes company-correlation-is-metadata-only + no-person-level-claim cases

# H4
grep -E "VIABLE|NOT-VIABLE|INCONCLUSIVE" process/features/evallayer/active/handoff_23-07-26/*_FEASIBILITY_*.md
# Expected: exactly one recorded keyword

# Program-wide regression
cd /Users/apple/getbeam && python -m pytest tests/unit/ tests/integration/ -q
# Expected: zero regressions in EvalLayer + AI-Referral suites
```

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/handoff_23-07-26/handoff-umbrella_PLAN_23-07-26.md`
- Last completed phase: Phase 0 (this umbrella plan file = Phase 0 artifact)
- Validate-contract status: pending (vc-validate-agent writes per-phase)
- Next step for a fresh agent: Read this umbrella plan and the locked SPEC, read the Phase 1
  (`phase-01-fetch-events-tiering`) plan, then run Phase 1 research subagent before any EXECUTE
  work.
- Current phase: Phase 1 — Fetch events + tiering (H1)
- Next action: Spawn vc-research-agent for Phase 1
- Execute-agent start instruction: Read this file. Read the SPEC. Read Phase 1 plan. Run research
  subagent first.

---

## Current Execution State

Last updated: 24-07-26
Completed phases: Phase 0 (Planning), Phase 1 — Fetch events + tiering (H1) — CODE DONE, EVL-confirmed
  green on all fully-automated gates; 2 Hybrid gates (Alembic upgrade/downgrade cycle, E7 live
  retention purge) remain Docker-gated known-gaps, tracked in
  `backlog/handoff-program-docker-verification-gaps_NOTE_23-07-26.md`.
  Phase 2 — Handoff correlation + dashboard (H2) — CODE DONE, EVL-confirmed green (21/21 target,
  899/0 full regression, FE build, registration+indexes, single migration head `e2a4c7f81b93`,
  AC-H2-3 confirmed via zero-diff + zero-reference tripwire + zero outreach joins, probabilistic
  badge copy confirmed). Core capability now code-complete: on-demand AI fetch links to the human's
  click-through — "human behind the agent" resolved at high/medium confidence, emailable status
  untouched in both directions. 1 Docker-gated Hybrid gap (live sweep + migration cycle) remains as
  known-gap, tracked in the same backlog note (H2 rows).
Current phase: Phase 3 — Intent signals (H3)
Current loop step: RESEARCH (pending)
Validate-contract status: Phase 1 written (Gate: CONDITIONAL, pre-accepted Docker-gated residuals);
  Phase 2 written (Gate: CONDITIONAL, pre-accepted Docker-gated residual); Phase 3 not yet written
Program Net Gate: PENDING (2 of 4 phases code-done)
Latest validator run: 24-07-26 — see this UPDATE PROCESS closeout
Cross-program note: Phase 1's migration (`c4e8f1a9d2b7`) has three foreign/downstream migrations
  chained onto it (`f8a2c1d9b3e7`, `a3e9f1c7d2b5` — visitors-identity "owned-data-layer" program;
  `e2a4c7f81b93` — this program's own H2 migration). Chain confirmed linear single head, no fork —
  but the visitors-identity program's live-apply remains blocked on this program's migrations being
  committed. Prioritize the H1+H2 execution commit.
Scheduler coordination note: H2's correlation-sweep job is registered in `apps/api/jobs/scheduler.py`
  (own `add_job(...)` call, additive). Per the umbrella's Pre-PVL Conflict Resolution (`reassign`
  classification), H3's Phase 3 INNOVATE/PLAN-SUPPLEMENT step MUST re-read the live diff to
  `scheduler.py` before adding its own spike-detector job registration — append additively, never
  edit H2's registration block.

Loop step values: RESEARCH | INNOVATE | PLAN-SUPPLEMENT | PVL | EXECUTE | EVL | UPDATE-PROCESS
Orchestrator rule: read "Current loop step" and "validate-contract status" before spawning any
subagent. Never spawn execute-agent when loop step is RESEARCH, INNOVATE, PLAN-SUPPLEMENT, or PVL.

Note: The Stable Program Goal above is fixed. This section is the only part that changes —
update-process-agent rewrites it after every phase closeout (overwrite, not append — git history
is the audit log).

---

## Test Infra Improvement Notes

(none identified yet)

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
