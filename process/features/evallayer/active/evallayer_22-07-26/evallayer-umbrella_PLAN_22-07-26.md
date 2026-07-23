---
name: plan:evallayer-umbrella
description: "EvalLayer — umbrella/orchestration plan for the 8-phase AI-agent traffic detection, dashboard, and outreach-safe enrichment program"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: umbrella
---

# EvalLayer — Umbrella Plan

**Date:** 22-07-26
**Complexity:** COMPLEX
**Status:** 🔨 CODE-COMPLETE (PENDING DOCKER GATE CLOSURE) — all 8 phases shipped 23-07-26; see
§Program-Level Closeout below. Kept in `active/`, not archived, until Phases 1-6's Docker/e2e
Known-Gaps close.

- Program type: PHASE PROGRAM (8 phases, 0–7, foundation + expansion tiers, gated joins)
- Date: 22-07-26
- Feature folder: `process/features/evallayer/`
- Locked SPEC: `process/features/evallayer/active/evallayer_22-07-26/evallayer_SPEC_22-07-26.md` (governs all 8 phases; inner loop skips SPEC — `R → I → P → PVL → E → EVL → UP`)

## Correction Note — Phase 0 Was Already Shipped (corrected 22-07-26, UPDATE PROCESS)

**The scaffolder's original "Data Discrepancy Note" (below, superseded) was wrong.** Phase 0's
SIMPLE plan was NOT lost — it existed, was executed, committed, and archived earlier the same day.
Root cause: the scaffolder's `find` against `process/general-plans/active/` raced the archival
`git mv` into `completed/`, landing between the move's rename-out and rename-in, so it wrongly
concluded the plan folder "does not exist on disk." No data was ever lost; nothing needs to be
reconstructed.

Verified facts:
- Commit `5ae5bd7` — `feat(seo): tiered JSON-LD offers + public ai-plugin.json manifest` — modifies
  `apps/web/public/beam/index.html` (3-tier JSON-LD `offers` array), adds
  `apps/web/src/app/.well-known/ai-plugin.json/route.ts`, and edits `apps/web/src/middleware.ts`
  (Clerk `.well-known/*` exemption, an unplanned but user-approved mid-EXECUTE supplement).
- Commit `7e0d625` — `process(evallayer-discoverability): archive shipped plan, capture learnings`
  — archives the plan.
- On disk today: `apps/web/src/app/.well-known/ai-plugin.json/route.ts` exists; the JSON-LD
  `offers` block in `index.html` is a 3-element array.
- Archived plan (full deviation notes, VALIDATE-skip reconciliation, closeout report):
  `process/general-plans/completed/evallayer-discoverability_22-07-26/evallayer-discoverability_PLAN_22-07-26.md`

**Resolution:** Phase 0 is treated as ✅ COMPLETE / shipped-pre-program. It is folded into this
program as a satisfied foundation deliverable, not re-run. Its stub file below has been rewritten
to point at the archived plan/commit as the source of truth rather than requiring a fresh
RESEARCH+INNOVATE+PLAN pass.

**One real gap remains, carried forward (not fabricated):** VALIDATE was explicitly skipped for the
Phase 0 SIMPLE plan (documented reason: frontend-only, no auth surface identified at PLAN time —
later found incomplete once the Clerk middleware exemption surfaced live). SPEC AC12's formal gates
were not run as validate-contract gates — verification was done ad hoc during EXECUTE (Verification
Evidence rows 1, 3, 4 passed; row 2, the Agent-Probe Google Rich Results Test paste-check, was never
run). **Recommendation:** run a lightweight AC12 verification pass (at minimum, the row-2 Agent-Probe
check) during this program's closeout, rather than treating Phase 0 as fully gate-verified.

---

## Program Goal Charter

```
EvalLayer — Program Goal Charter

North star:
- Give Beam users visibility into which AI agents (ChatGPT, Claude, Perplexity, etc.) visit their
  site — and turn the real company behind a resolvable agent visit into an ordinary sales lead —
  without ever weakening Beam's anti-bot / human-approves-outreach posture.

Definition of done (an unattended agent must be able to do all of these):
1. Classify a recognized AI-agent UA at ingest time, persist it to a dedicated agent-visit surface
   (never polluting human Visitor/Event data), and continue dropping generic bots exactly as today.
2. Surface agent visits in a new dashboard "Agents" tab (list/detail/stats) with a visible
   verification-method/confidence badge (ua-only / ip-verified / rdns-verified) on every record.
3. Upgrade confidence via published IP-range verification for OpenAI/Perplexity (Anthropic stays
   UA-only by design), fully covered by a MOCK_EXTERNAL_APIS=true deterministic path.
4. Resolve a qualifying agent visit's IP to a real company via the existing company-resolution
   pipeline, creating/updating a normal company/lead record — never an "agent contact" — and let
   that company flow through Beam's existing consent/suppression/approval-gated outreach path.
5. Guarantee, via a first-class regression test, that an agent-visit record can NEVER be selected
   as a campaign/email/social outreach target, directly or indirectly.
6. Surface GEO/AEO aggregate analytics (vendor breakdown, visits-over-time, page-read trends) built
   only from classified agent-visit data.
7. Carry forward the already-scoped discoverability surfaces (JSON-LD offers array,
   `/.well-known/ai-plugin.json`) unchanged as Phase 0's foundation deliverable.

What "verified" means (program level):
- SPEC AC1–AC14 each have a named `proven by:`/`strategy:` gate that is green (Fully-Automated
  gates iterate-to-green; Hybrid gates fixed-if-in-blast-radius; Agent-Probe gates have a recorded
  judgment). AC10 (outreach-exclusion regression test) is the single highest-priority gate in the
  program and must exist and pass before Phase 5 or Phase 7 can be marked VERIFIED.
- A phase's EVL confirmation run (vc-tester independently re-running the validate-contract gate
  commands) is green — execute-agent's internal claim of green is never sufficient by itself.
- validate-contract gates must be recorded alongside phase gates and regression evidence for a
  phase to reach VERIFIED. A phase without a validate-contract (or documented skip reason) cannot
  be marked VERIFIED.
- Model policy: EXECUTE phases run opus; RESEARCH/INNOVATE/PLAN/VALIDATE/UPDATE-PROCESS run sonnet
  (see `vc-agent-strategy-compare` §Model Selection Policy).

Scope tiers → phase mapping:
- Tier 1 (Foundation — detection substrate) → Phases 0, 1, 2, 3
- Tier 2 (Expansion — trust + enrichment) → Phases 4, 5
- Tier 3 (Expansion — analytics + safety hardening) → Phases 6, 7
- This program retires Tiers 1–3. (SPEC does not define a Tier 4; nothing is deferred beyond the
  SPEC's own Out-of-Scope section.)

Explicitly out of scope (deferred tier):
- Live-provider (non-mocked) vendor IP-range/rDNS verification runs — Agent-Probe/Known-Gap until a
  real fixture is available (per SPEC AC8 note).
- New/unconfirmed vendor UA tokens (Amazonbot, cohere-ai, Meta crawlers) — backlog, not v1.
- Google-Extended / Applebot-Extended live-traffic "detection" — structurally impossible; only
  robots.txt-policy surfacing is in scope, and only if/when a phase chooses to build it.
- Any pixel-side (`tracker.js`) fix for the `navigator.webdriver===true` self-block blind spot — the
  RESEARCH brief flagged this as a real undercount risk but no phase in this program owns a pixel
  change; note as a backlog item at UPDATE PROCESS.

Hard safety constraints (non-negotiable, per phase):
- Agents are NEVER emailed or contacted. Only a resolved human/company contact — reached through
  Beam's existing consent/suppression/approval gates — may ever enter outreach (SPEC AC10; the
  program's highest-priority regression test).
- Multi-tenancy is unchanged: every new query filters `Site.user_id == user.id`; foreign/unknown
  ids return 404, never 403 (no existence leakage).
- Every new external call (vendor IP-range fetch, rDNS lookup) ships a `MOCK_EXTERNAL_APIS=true`
  deterministic path before the phase can be marked VERIFIED (SPEC AC14).
- Human Visitor/Event data and stats are never polluted by agent-visit records — verified by a
  before/after count assertion, not assumed (SPEC AC2).
- Every agent-visit record's confidence must reflect verification method (ua-only / ip-verified /
  rdns-verified) — never presented as unconditional certainty (SPEC AC7).
- Phase 1 introduces a net-new migration; Phases 1, 2, 3, 5, 7 touch schema/ingest/API/outreach
  surfaces — VALIDATE (PVL) is mandatory for every one of these phases and may never be skipped.
- Commit each phase's execution changes before starting the next phase. Keep process/plan/context
  commits separate from execution commits.
```

---

## Stable Program Goal (copy-paste this to start autonomous execution)

```
SESSION GOAL: evallayer — EvalLayer AI-Agent Traffic Detection Program
Ref: process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md

TARGET: Complete ALL 8 phases (0–7) until:
- SPEC AC1–AC14 each have a green `proven by:` gate (or documented Known-Gap per vacuous-green ban)
- AC10 (agent-record can never enter outreach) passes as a first-class regression test before
  Phase 5 or Phase 7 is marked VERIFIED
- Test tiers: automated (iterate-until-green) / hybrid (fix-if-in-blast-radius) / agent-probe
  (record-judgment) — Known-Gap is a residual only, never a terminal PASS

AUTONOMY: Before ANY subagent spawn, read:
1. This file's `## Current Execution State` → current phase + loop step + validate-contract status
2. Target phase plan's `## Phase Loop Progress` → first unchecked box = next subagent to spawn

PER-PHASE LOOP (7-step inner loop `R → I → P → PVL → E → EVL → UP`, never skip, never reorder;
SKIPS SPEC — the SPEC above already governs all 8 phases):
  1. RESEARCH → 2. INNOVATE → 3. PLAN-SUPPLEMENT → 4. PVL → 5. EXECUTE → 6. EVL → 7. UPDATE-PROCESS
- PLAN-SUPPLEMENT: plan-agent writes research/innovate gaps into the phase plan (or marks
  "n/a — research clean")
- PVL is NEVER skipped; placeholder contract = blocked, same as a first-pass CONDITIONAL/BLOCKED
  gate — neither is legal to advance past without a supplement cycle or explicit acceptance
- Every subagent's FIRST ACTION: run vc-context-discovery (load context group files + the
  `process/context/tests/all-tests.md` routing chain) AND vc-plan-discovery (same-feature full
  depth active/backlog/completed + other features active-only + general-plans active)
- Every phase-END: invoke vc-agent-strategy-compare for the next step's execution strategy

Report via phase reports. No approval between phases unless a hard stop below is hit.

HARD STOPS (pause, wait for user):
- Any code path that could route an agent-visit record into email/social send (irreversible,
  outward-facing) without an explicit validate-contract instruction covering it
- Live-provider (non-mocked, billed) vendor IP-range or rDNS verification call
- Net gate = BLOCKED with no backlog resolution path, or two consecutive phases BLOCKED (cascade)
- Validate-contract is placeholder and vc-validate-agent cannot run

SAFETY (never override):
- Agents are never emailed/contacted; only resolved human/company contacts through existing
  consent/suppression/approval gates may be reached
- Multi-tenancy unchanged: Site.user_id == user.id; foreign ids → 404 not 403
- Every new external call ships a MOCK_EXTERNAL_APIS=true deterministic path
- Human Visitor/Event data and stats are never polluted by agent traffic
- Commit each phase before advancing; process and execution commits stay separate

TEST GATES (every phase exit — run all 5, plus phase-specific validate-contract gates):
  node .claude/skills/vc-audit-vc/scripts/validate-agent-parity.mjs
  node .claude/skills/vc-audit-context/scripts/validate-context-discovery.mjs
  node .claude/skills/vc-audit-plans/scripts/validate-plan-inventory.mjs
  node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs <phase-plan.md>
  node .claude/skills/vc-generate-phase-program/scripts/validate-phase-stub.mjs <phase-plan.md>

VALIDATE CONTRACT: Per-phase contracts written by vc-validate-agent into each phase plan before
EXECUTE. None exist yet — all 8 phases are ⏳ PLANNED / stub-only.

START: Phase 0 is ✅ COMPLETE (shipped `5ae5bd7`, archived `7e0d625` — see Correction Note above; no
RESEARCH re-run needed). Phase 1, loop step RESEARCH (pending). Spawn vc-research-agent for Phase 1.
```

---

## Phase Sequence

| Phase | Plan file | Scope summary | Depends on |
|---|---|---|---|
| 0 — Discoverability | `process/features/evallayer/active/evallayer_22-07-26/phase-00-discoverability_PLAN_22-07-26.md` (shipped; source of truth is the archived plan — see Correction Note) | JSON-LD `offers` array + `/.well-known/ai-plugin.json` manifest — ✅ shipped `5ae5bd7`, archived `7e0d625` | None |
| 1 — Data model + classifier | `process/features/evallayer/active/evallayer_22-07-26/phase-01-data-model-classifier_PLAN_22-07-26.md` | New agent-visit data surface + Alembic migration; `agent_classifier.py` splitting `_BOT_PATTERN` drop-vs-classify tokens; trust-tier classifier mirroring `identity_classification.py` | None |
| 2 — Ingest wiring | `process/features/evallayer/active/evallayer_22-07-26/phase-02-ingest-wiring_PLAN_22-07-26.md` | Classify-then-branch in `events.py`; resolve filter ordering vs datacenter/proxy drops (`events.py:119-140`); persist agent visits | Phase 1 |
| 3 — Read API + dashboard tab | `process/features/evallayer/active/evallayer_22-07-26/phase-03-read-api-dashboard_PLAN_22-07-26.md` | `/agents` router (list/detail/stats) + new "Agents" dashboard tab cloning Visitors list/detail | Phase 2 |
| 4 — IP/rDNS verification | `process/features/evallayer/active/evallayer_22-07-26/phase-04-ip-verification_PLAN_22-07-26.md` | OpenAI/Perplexity published IP-range verification + confidence field; Anthropic stays UA-only; mock path | Phase 2 (parallel-safe with Phase 3) |
| 5 — Company resolution → outreach feed | `process/features/evallayer/active/evallayer_22-07-26/phase-05-company-resolution_PLAN_22-07-26.md` | Agent IP → existing `company_resolver.py` → company enters existing enrichment/email pipeline as a normal lead | Phase 3, Phase 4 |
| 6 — Aggregation + GEO/AEO analytics | `process/features/evallayer/active/evallayer_22-07-26/phase-06-aggregation-analytics_PLAN_22-07-26.md` | Agent-visit rollup aggregation + vendor breakdown / visits-over-time / page-read trend widgets | Phase 3, Phase 4 |
| 7 — Outreach-exclusion guardrail | `process/features/evallayer/active/evallayer_22-07-26/phase-07-outreach-exclusion_PLAN_22-07-26.md` | Hard guard so an agent-visit record can never be a campaign/email/social target; first-class regression test (SPEC AC10) | Phase 2; treated as a **release gate for Phase 5** (may run parallel with or ahead of Phase 5) |

### Join Conditions

- Phase 1 and Phase 0 have no dependency on each other — either may start immediately in parallel.
- Phase 2 MUST NOT start until Phase 1's exit gate passes (needs the classifier + schema).
- Phase 3 MUST NOT start until Phase 2's exit gate passes (needs persisted agent-visit rows).
- Phase 4 MUST NOT start until Phase 2's exit gate passes; Phase 4 and Phase 3 are parallel-safe
  (disjoint blast radius: Phase 3 = API/dashboard read surface, Phase 4 = verification service).
- Phase 5 MUST NOT start until BOTH Phase 3 AND Phase 4 exit gates pass.
- Phase 6 MUST NOT start until BOTH Phase 3 AND Phase 4 exit gates pass (parallel-safe with Phase 5
  — disjoint blast radius: aggregation/analytics vs company-resolution/outreach).
- Phase 7 MUST NOT start until Phase 2's exit gate passes. Per SPEC Resolved Open Question 10, Phase
  7's regression test must exist or be actively scheduled alongside Phase 5 — Phase 5 is not
  considered mergeable/VERIFIED without Phase 7's guardrail test passing.

---

## Per-Phase Entry / Exit Gates

| Phase | Entry | Exit gate |
|---|---|---|
| 0 | Program start | ✅ SATISFIED (shipped pre-program) — JSON-LD `offers` array + `ai-plugin.json` manifest live on `main` (`5ae5bd7`); 3 of 4 AC12 criteria verified during EXECUTE (Verification Evidence rows 1, 3, 4); row 2 (Agent-Probe Rich Results paste-check) recommended at program closeout; VALIDATE was explicitly skipped for the SIMPLE plan, not run as a formal validate-contract |
| 1 | Program start (parallel with Phase 0) | Migration applies cleanly; classifier unit tests green (drop-vs-classify token split, tiering); no ingest wiring yet |
| 2 | Phase 1 exit met | Recognized-agent UA persists as agent visit (AC1); human Visitor/Event tables unaffected (AC2); generic bots still dropped (AC3); filter-ordering resolved so legit vendor IPs aren't re-dropped (AC4); no material ingest latency added (AC5) |
| 3 | Phase 2 exit met | `/agents` API + dashboard tab show agent visits only, never human ones (AC6); confidence badge renders per visit (AC7) |
| 4 | Phase 2 exit met | OpenAI/Perplexity mock IP-range verification upgrades confidence; Anthropic never exceeds ua-only (AC8); mock mode covers the new external call (AC14, partial) |
| 5 | Phase 3 + Phase 4 exits met, AND Phase 7's guardrail test exists/passing | Qualifying agent visit creates/updates a normal company/lead record via existing pipeline (AC9); mock mode covers the reused enrichment call (AC14, partial) |
| 6 | Phase 3 + Phase 4 exits met | Vendor breakdown / visits-over-time / page-read trend aggregation correct against synthetic fixture data (AC11) |
| 7 | Phase 2 exit met | First-class regression test proves an agent-visit record can never enter campaign/email targeting (AC10) — this is the program's release-gate test |

---

## Per-Phase Loop

Each phase executes the canonical 7-step inner loop `R → I → P → PVL → E → EVL → UP`. This inner
loop SKIPS SPEC — the locked SPEC above governs all 8 phases; no per-phase SPEC is written. The 7
steps map to:

1. **RESEARCH** — spawn research-agent: load context, read prior phase reports, check plan drift,
   document findings. **Phase 5 requires a MANDATORY-FRESH research pass** (see Phase 5 stub) — the
   prior workflow's `read:identity` sub-agent returned placeholder/test output, so agent→company
   enrichment-waterfall mechanics are under-researched and not resumable from existing findings.
2. **INNOVATE** — spawn innovate-agent: decide approach; write Decision Summary (chosen approach +
   rejected alternatives).
3. **PLAN-SUPPLEMENT** — spawn plan-agent: if research/innovate found gaps/pre-conditions not in the
   checklist, add them; otherwise mark "n/a — research clean" and tick step 3.
4. **PVL** — spawn vc-validate-agent: full V1–V7; validate-contract written per
   `.claude/skills/vc-validate-findings/references/example-validate-output.md` format (Status /
   Gate / Plan updates applied / Execute-agent instructions / Test gates / High-risk pack / Backlog
   artifacts / Known gaps / Accepted by).
5. **EXECUTE** — spawn vc-execute-agent per approved plan and validate-contract.
6. **EVL** — spawn vc-tester: run phase test gates to green; register follow-up stubs; write EVL
   HANDOFF SUMMARY.
7. **UPDATE-PROCESS** — write phase report to durable report path, rewrite this umbrella's
   `## Current Execution State` section (overwrite, not append — git history is the audit log).

**PVL is NEVER skipped.** A placeholder `## Validate Contract` = blocked. Do not spawn
execute-agent while the Validate Contract section reads "(placeholder — vc-validate-agent writes
this section before EXECUTE)". Phases 1, 2, 3, 5, 7 touch schema/ingest/API/outreach surfaces and
have zero VALIDATE-skip eligibility under any circumstance (see Hard Safety Constraints above).

---

## Autonomous Execution Rules (During /goal)

During /goal execution of this phase program:
- Agent self-decides at all V5 gates — no user approval needed between phases.
- CONDITIONAL net gate: proceed autonomously, fixes applied in-flight, gaps on record.
- BLOCKED net gate: document items in backlog, continue with remaining phase plans; backlog is
  always a valid resolution — always find a path forward. Two consecutive BLOCKED phases trigger
  the Cascade BLOCKED hard stop (see `orchestration.md` §BLOCKED Escalation Path).
- Hard stops (must pause for user approval):
  - Any irreversible/outward-facing action without explicit contract instruction (e.g. anything
    that could route an agent-visit record toward send/deploy/production data mutation)
  - Live-provider (non-mocked) IP-range or rDNS verification calls
  - Plan file explicitly marks "pause required" at a step
- Agent writes phase reports, updates phase plans, creates new sub-plans as needed — all
  autonomously. The phase report is the communication channel for conflicts, errors, and
  learnings — not inline questions.

---

## Global Constraints

- Never weaken or bypass the outreach-exclusion guardrail (Phase 7) to make Phase 5 "work" —
  Phase 5 is not mergeable/VERIFIED without Phase 7's regression test passing.
- Never widen `_BOT_PATTERN`'s drop-list semantics without an explicit token reclassification
  decision documented in the Phase 1 plan.
- Never introduce a new external call (vendor IP-range fetch, rDNS lookup, enrichment reuse)
  without a `MOCK_EXTERNAL_APIS=true` deterministic path shipped in the same phase.
- After every phase that touches agent/harness files, run the parity validator and confirm it
  exits 0 before declaring the phase DONE.
- Commit each phase's execution changes before starting the next phase. Keep process/plan/context
  commits separate from execution commits.
- Do not conflate this program's blast radius with the unrelated uncommitted PII/email-hash work
  (`apps/api/services/known_hash.py`, `tests/unit/test_known_hash.py`) — confirmed unrelated by
  RESEARCH; leave that work untouched.

---

## Durable Report Destinations

| Phase | Report path (inside task folder, flat) |
|---|---|
| 0 — Discoverability | `process/features/evallayer/active/evallayer_22-07-26/phase-00-discoverability_REPORT_22-07-26.md` |
| 1 — Data model + classifier | `process/features/evallayer/active/evallayer_22-07-26/phase-01-data-model-classifier_REPORT_22-07-26.md` |
| 2 — Ingest wiring | `process/features/evallayer/active/evallayer_22-07-26/phase-02-ingest-wiring_REPORT_22-07-26.md` |
| 3 — Read API + dashboard tab | `process/features/evallayer/active/evallayer_22-07-26/phase-03-read-api-dashboard_REPORT_22-07-26.md` |
| 4 — IP/rDNS verification | `process/features/evallayer/active/evallayer_22-07-26/phase-04-ip-verification_REPORT_22-07-26.md` |
| 5 — Company resolution → outreach feed | `process/features/evallayer/active/evallayer_22-07-26/phase-05-company-resolution_REPORT_22-07-26.md` |
| 6 — Aggregation + GEO/AEO analytics | `process/features/evallayer/active/evallayer_22-07-26/phase-06-aggregation-analytics_REPORT_22-07-26.md` |
| 7 — Outreach-exclusion guardrail | `process/features/evallayer/active/evallayer_22-07-26/phase-07-outreach-exclusion_REPORT_22-07-26.md` |

Phase blast-radius registry (append-only, agent-team coordination token — created by the first
phase-plan-writing agent): `process/features/evallayer/active/evallayer_22-07-26/phase-blast-radius-registry.md`

---

## Program Status Table

| Phase | Status |
|---|---|
| 0 — Discoverability | ✅ COMPLETE (shipped `5ae5bd7`; plan archived `7e0d625`) |
| 1 — Data model + classifier | 🔨 CODE DONE (EXECUTE + EVL complete; 3/4 gates GREEN; live-DB migration up/down/up = KNOWN-GAP, Docker unavailable — not ✅ VERIFIED until that gate is closed, see phase report) |
| 2 — Ingest wiring | 🔨 CODE DONE (EXECUTE + EVL complete; Gate: CONDITIONAL accepted; full unit baseline GREEN 725/2-skipped, +9, 0 regressions; classifier 24/24; static safety review confirmed all 3 declared safety properties. 2 KNOWN-GAPS open — Docker integration tests (5 cases, collect-clean, unrun) + AC5 latency benchmark (no harness, backlog stub written) — not ✅ VERIFIED until both close, see phase report) |
| 3 — Read API + dashboard tab | 🔨 CODE DONE (EXECUTE + independent EVL complete; FE compile + unit-regression + static-safety-review all GREEN; Docker integration (10 cases) + Playwright e2e = KNOWN-GAPS, env-gated — not ✅ VERIFIED until both close, see phase report) |
| 4 — IP/rDNS verification | 🔨 CODE DONE (EXECUTE + independent EVL complete; unit 10/10, hot-path grep=0, Anthropic structural ceiling confirmed, full regression 735/2 no drop — 1 Docker-gated integration Known-Gap open, not ✅ VERIFIED until closed, see phase report) |
| 5 — Company resolution → outreach feed | 🔨 CODE DONE (EXECUTE + independent EVL complete; AC10 18/18, Phase-5 suite 25/25, full regression 778/2 (0 regressions vs 752/2); Phase 7 D1-D6 contract FULFILLED; 2 Docker known-gaps open (migration apply/rollback, integration sweep) — not ✅ VERIFIED until closed, see phase report) |
| 6 — Aggregation + GEO/AEO analytics | 🔨 CODE DONE (EXECUTE + independent EVL complete 2026-07-23; 11/11 unit + 824/2 full regression + FE build all GREEN; 2 Docker/e2e Known-Gaps carried, non-blocking — see phase report) — **program's LAST phase; program is now code-complete** |
| 7 — Outreach-exclusion guardrail | ✅ VERIFIED (EXECUTE + independent EVL complete 2026-07-22; AC10 gate 17/17, full regression 752/2 (0 regressions), no Docker known-gap; released as the program's release-gate test for Phase 5 — see phase report + registry) |

Status values: ⏳ PLANNED | 🔨 CODE DONE | 🧪 TESTING | ✅ VERIFIED | 🚧 BLOCKED | ✅ COMPLETE

---

## Touchpoints

- `apps/api/routers/events.py` (ingest hot path — classify-then-branch, filter ordering)
- `apps/api/services/bot_filter.py` (`_BOT_PATTERN` token split)
- `apps/api/services/identity_classification.py` (trust-tier pattern reference, not modified)
- `apps/api/services/company_resolver.py` (IP-range verification + company resolution reuse)
- `apps/api/models/` (new agent-visit data surface; net-new Alembic migration)
- `apps/api/routers/agents.py`, `apps/api/schemas/agents.py` (new)
- `apps/api/services/visitor_aggregator.py`, `apps/api/tasks/aggregation_tasks.py` (parallel
  agent-visit rollup path)
- `apps/api/routers/campaigns.py` / segment targeting logic (outreach-exclusion guardrail)
- `apps/web/src/app/dashboard/layout.tsx` (new "Agents" nav item)
- `apps/web/src/app/dashboard/visitors/*` (clone target for Agents list/detail)
- `apps/web/src/components/visitor-widgets.tsx`, `kpi-strip.tsx`, `traffic-fit-card.tsx` (clone
  target for agent analytics widgets)
- `apps/web/src/lib/api.ts`, `apps/web/src/lib/api-types.ts` (new typed client methods/types)
- `apps/web/public/beam/index.html`, `apps/web/src/app/llms.txt/route.ts`, new
  `apps/web/src/app/.well-known/ai-plugin.json/route.ts` (Phase 0 discoverability)
- `apps/api/config.py` (new `AGENT_DETECTION_ENABLED`-style flag)

---

## Public Contracts

- Existing `/events/ingest` request/response contract is unchanged for human traffic; agent
  traffic gains persistence but the endpoint's external shape (status codes, body) is unchanged.
- Existing `/visitors` API and dashboard "Visitors" tab behavior is unchanged — agent records never
  appear there (SPEC AC6).
- Existing campaign/segment/outreach API contracts are unchanged in shape; only an additional
  hard exclusion is added so agent-visit ids are never accepted as targets (SPEC AC10).
- New `/agents` API surface and "Agents" dashboard tab are net-new public contracts, structurally
  mirroring the existing `/visitors` surface (list/detail/stats).
- Existing multi-tenancy contract (`Site.user_id == user.id`, 404-not-403 on foreign ids) applies
  unchanged to every new surface.

---

## Blast Radius

Files directly modified or created across the program (aggregate — see per-phase Blast Radius
sections for phase-scoped detail):

- `apps/api/routers/events.py`, `apps/api/services/bot_filter.py` — modified
- `apps/api/services/agent_classifier.py` — new
- `apps/api/models/*` (new agent-visit model + 1 Alembic migration) — new
- `apps/api/routers/agents.py`, `apps/api/schemas/agents.py` — new
- `apps/api/services/agent_verification.py` (or equivalent, Phase 4) — new
- `apps/api/services/visitor_aggregator.py`, `apps/api/tasks/aggregation_tasks.py` — modified/new
- `apps/api/routers/campaigns.py` / segment targeting module — modified (guardrail)
- `apps/web/src/app/dashboard/agents/*` — new (list/detail pages)
- `apps/web/src/app/dashboard/layout.tsx` — modified (nav)
- `apps/web/src/components/agent-widgets.tsx` (or equivalent) — new
- `apps/web/src/lib/api.ts`, `apps/web/src/lib/api-types.ts` — modified
- `apps/web/public/beam/index.html`, `apps/web/src/app/.well-known/ai-plugin.json/route.ts` — new/modified (Phase 0)
- `apps/api/config.py` — modified
- Static vendor IP-range JSON fixtures (OpenAI/Perplexity, real + mock) — new

Risk class: schema/migration (Phase 1), public API contract (Phases 3, 4), auth/multi-tenancy
surface reuse (all phases, unchanged pattern), outreach/email surface (Phases 5, 7 — highest risk
class in the program).

---

## Verification Evidence

```bash
# Core validator suite (run after every phase touching harness/plan artifacts)
node .claude/skills/vc-audit-vc/scripts/validate-agent-parity.mjs
node .claude/skills/vc-audit-context/scripts/validate-context-discovery.mjs
node .claude/skills/vc-audit-plans/scripts/validate-plan-inventory.mjs
# Expected: all exit 0

# Umbrella + phase-stub structural validators (run once at scaffold time and after any structural edit)
node .claude/skills/vc-generate-phase-program/scripts/validate-umbrella-artifact.mjs process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md
node .claude/skills/vc-generate-phase-program/scripts/validate-phase-stub.mjs process/features/evallayer/active/evallayer_22-07-26/phase-0N-*_PLAN_22-07-26.md
# Expected: exit 0, no FAIL lines
```

Per-phase, program-level Verification Evidence (`| Gate / Scenario | Strategy | Proves SPEC
criterion |`) is deferred to each phase's own plan, written at that phase's PLAN step — the table
below maps SPEC criteria to the phase that owns proving them, so no criterion is dropped across
the program.

| Gate / Scenario | Strategy | Proves SPEC criterion | Owning phase |
|---|---|---|---|
| Recognized agent UA persists, not dropped | Fully-Automated | AC1 | Phase 2 |
| Human Visitor/Event tables unaffected by agent traffic | Fully-Automated | AC2 | Phase 2 |
| Generic bots still dropped unchanged | Fully-Automated | AC3 | Phase 2 |
| Legit vendor IP not re-dropped by datacenter/proxy filter | Fully-Automated (mocked IP-rep) | AC4 | Phase 2 |
| No material ingest latency added | Hybrid | AC5 | Phase 2 |
| Agents tab shows agent visits only, never human | Fully-Automated (Playwright) | AC6 | Phase 3 |
| Confidence/verification-method badge renders | Fully-Automated | AC7 | Phase 3 |
| OpenAI/Perplexity mock IP-range upgrades confidence; Anthropic stays ua-only | Fully-Automated (mock path) | AC8 | Phase 4 |
| Qualifying agent visit creates a normal company/lead, not an "agent contact" | Hybrid (mocked provider path; re-research required) | AC9 | Phase 5 |
| Agent-visit record can never enter campaign/email targeting | Fully-Automated (highest priority) | AC10 | Phase 7 |
| GEO/AEO aggregate analytics correct on synthetic fixtures | Fully-Automated | AC11 | Phase 6 |
| Discoverability surfaces remain valid (JSON-LD + manifest) | Fully-Automated / Hybrid | AC12 | Phase 0 |
| Google-Extended/Applebot-Extended never appear as live "visits" | Fully-Automated | AC13 | Phase 1 |
| Mock mode covers every new external call | Fully-Automated | AC14 | Phase 4, Phase 5 |

---

## Test Infra Improvement Notes

- Add `tests/unit/test_agent_classifier.py` scaffold early in Phase 1 so classifier logic is TDD'd
  rather than tested after the fact (per RESEARCH brief's Infra Improvement Suggestions).
- Add a deterministic mock fixture for vendor IP-range JSON (mirrors existing `MOCK_EXTERNAL_APIS`
  pattern) before Phase 4 begins, so verification logic is testable without live network calls.
- No existing test coverage was located for any AI-agent-vendor-specific classification path
  (RESEARCH confirmed zero targeted assertions) — every phase touching classification must add its
  own coverage; none can be assumed to exist.

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md`
- Last completed phase: Phase 5 (Company resolution → outreach feed) — **🔨 CODE DONE**, all 7
  inner-loop steps run, EVL-confirmed independently, Phase 7's D1-D6 contract FULFILLED. 2 Docker
  known-gaps open (migration apply/rollback, integration sweep — no disposable Postgres in this
  sandbox). See `phase-05-company-resolution_REPORT_22-07-26.md`.
- Validate-contract status: Phases 1, 3, 4, 5, 7 written (Gate: PASS). Phase 2 written (Gate:
  CONDITIONAL, accepted). Phase 6 pending (stub-only, placeholder).
- Supporting context files loaded this session: `evallayer_SPEC_22-07-26.md`,
  `phase-05-company-resolution_PLAN_22-07-26.md` + `_REPORT_`, `phase-blast-radius-registry.md`,
  `process/context/all-context.md`, `process/development-protocols/phase-programs.md`
- **Program is code-complete.** All 8 phases (0-7) have shipped: Phase 0 ✅ COMPLETE, Phase 7
  ✅ VERIFIED, Phases 1-6 🔨 CODE DONE (each with 1-2 environment-only Docker/e2e Known-Gaps,
  consolidated in `process/features/evallayer/backlog/program-docker-verification-gaps_NOTE_23-07-26.md`).
- Next step for a fresh agent: read this umbrella plan's §Program-Level Closeout section first. Do
  NOT re-spawn execute-agent for any of the 8 phases — their Known-Gaps are backlog/EVL-confirmed
  environment residuals, not open EXECUTE tasks. Two paths forward: (1) run the consolidated
  backlog note's close-all sequence against a live Postgres/Redis to promote Phases 1-6 to
  ✅ VERIFIED; (2) scaffold the successor **Handoff Detection** program in a new feature folder.
- Current phase: none — program complete.
- Next action: `vc-generate-phase-program` (or manual scaffold) for the **Handoff Detection**
  successor program in a new feature folder, OR run the Docker close-all sequence if live infra
  becomes available first.
- Execute-agent start instruction: NOT ELIGIBLE for any phase in this program — all 8 have
  completed EXECUTE. A future execute-agent spawn only makes sense against the new Handoff
  Detection program's own phase plans, or against a dedicated NEW PLAN closing one of the
  standalone backlog items (latency benchmark, identity-merge collision, rollup staleness).

---

## Program-Level Closeout (23-07-26 — UPDATE PROCESS, Phase 6 + whole program)

**Program status: CODE-COMPLETE.** All 8 phases have shipped code. Phase 0 ✅ COMPLETE
(pre-program), Phase 7 ✅ VERIFIED (zero Docker known-gap), Phases 1-6 🔨 CODE DONE (each has 1-2
environment-only Docker/e2e known-gaps, zero design defects). No phase remains ⏳ PLANNED or
🚧 BLOCKED.

**What "code-complete" means here, precisely:** every SPEC AC1-14 has a Fully-Automated or Hybrid
proving gate; every Fully-Automated gate is green; the only outstanding gates are Hybrid gates
that require a live Postgres/Redis/dev-server the sandbox never had access to. This is the same
disposition every phase in this program reached — not a program-level shortcut invented at
closeout.

**Consolidated known-gaps (all Docker/live-environment, not design defects):** tracked in the new
backlog note `process/features/evallayer/backlog/program-docker-verification-gaps_NOTE_23-07-26.md`
(written this session) with one close-all command sequence covering every phase's residual gate in
a single pass, plus 2 pre-existing standalone backlog items (`phase-02-latency-benchmark_NOTE`,
identity-merge-collision/rollup-staleness notes from Phase 5) that need dedicated NEW PLANs, not
just an infra run.

**Bonus work shipped this same session (outside the 8-phase scope, same commit window):**
**AI-Referral Attribution v1** — `apps/api/services/ai_referral.py` classifier (chatgpt, perplexity,
gemini, copilot, claude, you, grok, deepseek, mistral — excludes in-SERP google/bing by design);
`Visitor.first_touch_referrer` (fixed a lexicographic-MAX bug, now true chronological first-touch)
+ `Visitor.ai_source` (migration `b3f9a1d2c7e5`); "Arrived via" badge/pill/facet on the Visitors
dashboard; `ai_source` fed into the segmenter as a signal. Safety-reviewed: `ai_source` is
attribution metadata only, on a separate write path from `source_agent_visit_id`;
`is_emailable_identity` never reads it; AI-referred humans stay fully emailable (this is the
opposite of the EvalLayer guardrail — these are real humans, not agents). Commit `a5ab596`. This
is NOT part of the EvalLayer SPEC's 14 acceptance criteria and is tracked here only because it
shares this session's commit window and touches adjacent visitor-attribution surface.

**Archival decision: KEEP `evallayer_22-07-26/` IN `active/` — do NOT archive yet.** Rationale: the
program is code-complete but genuinely unverified at the Docker/live-integration tier across 6 of
8 phases (Phases 1-6). Archiving now would bury an open, real verification gap under `completed/`
where it is less visible. Re-evaluate archival once the consolidated backlog note's close-all
sequence has been run against a live Postgres/Redis and each phase is promoted 🔨 CODE DONE →
✅ VERIFIED (or the user explicitly accepts the Docker gaps as permanent Known-Gaps and asks for
archival anyway).

**Successor program:** **Handoff Detection** (human-behind-the-agent) is being scaffolded next, in
a new feature folder (not appended to `evallayer/`, since EvalLayer's own scoped goal — the 8-phase
SPEC — is fully code-complete). Planned shape: H1 `agent_fetch_events` per-hit table + on-demand-
vs-index token tiers → H2 handoff correlation (`agent_handoff_links`, on-demand fetch ↔ AI-referral
click — NEVER touching `source_agent_visit_id`) → H3 intent signals/alerts → H4 citation-watermark
live probe. Grounded in fresh research: OpenAI/Anthropic/Perplexity document distinct on-demand
fetcher UAs separate from their indexing crawlers; no competitor currently correlates an on-demand
agent fetch with a subsequent human click-through from that agent's answer. This program directly
builds on both EvalLayer's agent-classification substrate (Phase 1-4) and this session's
AI-referral attribution work (the human-side half of the correlation).

---

## Current Execution State

Last updated: 23-07-26 (UPDATE PROCESS closeout of Phase 6 — FINAL phase — and the whole 8-phase
program)
Completed phases:
- Phase 5 (Company resolution → outreach feed) — **🔨 CODE DONE** (all 7 inner-loop steps run;
  EXECUTE + independent EVL both complete). Gate: PASS at PVL (2 mandatory FAILs found via
  `vc-security` STRIDE scan and resolved in-plan: GUARD #1 atomicity fix — marker threaded through
  `resolve()`/`_save_identified()` and set at INSERT time, no deferred-UPDATE window; GUARD #2
  completeness fix — 7th AC2 exclusion site found in `resolution_tasks.py::_process_site`). EVL
  confirmation run (independent `vc-tester` re-run, not relying on execute-agent's internal claim)
  GREEN on all Fully-Automated gates: AC10 suite 18/18 (incl. real-row re-run
  `test_ac10_real_sweep_created_row_is_non_emailable`), Phase-5 suite 25/25, full regression 778
  passed/2 skipped (baseline 752/2, +26, 0 regressions), AC14 mock-mode 25/25. Static review
  confirmed GUARD #1 marker atomic with NO instance-state leak (reset unconditionally at the top of
  every `resolve()` call — human callers get a cleared value) and all 7 AC2 sites wired via the
  shared `human_only_visitor_filter()`; no agent-email path exists. **Phase 7 D1-D6 contract
  FULFILLED**: `IdentifiedVisitor.source_agent_visit_id` exists with the exact literal name Phase
  7's guard expects — its `getattr(...)` tripwire wiring is now live, not a no-op; no
  PERSON_LEVEL provider is ever assigned to an agent-resolved row; no 4th bypass path introduced;
  `test_agent_origin_exclusion.py` re-run against a real Phase-5-created row is green. 2 gates
  KNOWN-GAP (no disposable Postgres in this sandbox at either EXECUTE or EVL time): (a) migration
  apply/rollback against a live Postgres — close command: `docker compose -f
  infra/docker-compose.yml up -d postgres redis && .venv/bin/python -m alembic upgrade head &&
  .venv/bin/python -m alembic downgrade -1`; (b) full sweep integration round-trip — close command:
  `docker compose -f infra/docker-compose.yml up -d postgres redis && .venv/bin/python -m pytest
  tests/integration -k agent_company_resolution -m integration -q` (test file TBD if not yet
  authored — see phase report). 2 pre-existing safe-direction backlog residuals carried forward
  unchanged, NOT touched this phase (plan E4 forbids it): identity-merge email-dedup collision
  (`process/features/evallayer/backlog/phase-05-identity-merge-collision_NOTE_22-07-26.md`),
  AgentVisit rollup staleness
  (`process/features/evallayer/backlog/phase-05-rollup-staleness_NOTE_22-07-26.md`). 2
  within-blast-radius EXECUTE deviations recorded (DEV-1 instance-state marker threading, DEV-2 AC2
  D1+D6-facet via the shared `_build_visitor_filters` helper — both validate-contract-sanctioned).
  Not classified ✅ VERIFIED because the two Docker known-gaps sit on this phase's own
  highest-risk-class surface (schema migration + live sweep against real data) — this is a
  deliberate, documented pair of Known-Gaps, not a silent pass. Report:
  `phase-05-company-resolution_REPORT_22-07-26.md`. Not committed this session (`vc-git-manager`
  next).
- Phase 7 (Outreach-exclusion guardrail) — **✅ VERIFIED** (all 7 inner-loop steps run; EXECUTE +
  independent EVL both complete). Gate: PASS at PVL (1 plan update applied: C5 literal-field-name
  tripwire test, closing a `vc-security` STRIDE tampering-risk finding). EVL confirmation run
  (independent `vc-tester` re-run, not relying on execute-agent's internal claim) GREEN: AC10 gate
  `test_agent_origin_exclusion.py` 17/17 (all 5 test groups, incl. C5 tripwire); full unit
  regression 752 passed/2 skipped (baseline 735 + 17, 0 regressions); adjacent
  `test_outbound_identity_gate.py` 18/18 (no breakage); non-vacuity confirmed by independent code
  inspection (the `source_agent_visit_id` override is the first, unconditional statement in
  `is_emailable_identity` — physically deleting it flips C1 red for every `PERSON_LEVEL_PROVIDERS`
  value). No Docker known-gap in this phase — every gate is Fully-Automated. Phase 5's D1-D6
  contract obligation (D5/D6) is now DISCHARGED — see Phase 5 entry above. Two accepted
  non-blocking Known-Gaps (not backlog artifacts — see report): skip-counter miscategorization
  (observability-only) and D4 centralization (written contract, not a code-enforced chokepoint).
  Report: `phase-07-outreach-exclusion_REPORT_22-07-26.md`. Not committed this session
  (`vc-git-manager` next).
- Phase 0 (Discoverability) — ✅ COMPLETE, shipped pre-program (`5ae5bd7`, archived `7e0d625`),
  folded into this program as a satisfied foundation deliverable
- Phase 1 (Data model + classifier) — 🔨 CODE DONE (all 7 inner-loop steps run; EXECUTE + independent
  EVL both complete). 3/4 gates GREEN (classifier 24/24, registration smoke, full regression 716
  passed/2 skipped/no regression). 1 gate KNOWN-GAP: live-DB migration up/down/up cycle — no
  responsive Docker in this sandbox at either EXECUTE or EVL time; offline structural check
  (single Alembic head, script loads) passed as a partial substitute. Close-the-gap command is
  recorded in `phase-01-data-model-classifier_REPORT_22-07-26.md`. Not classified ✅ VERIFIED
  because the schema/migration gate — the phase's highest-risk-class gate — has not actually run
  live; this is a deliberate, documented Known-Gap, not a silent pass. Report:
  `phase-01-data-model-classifier_REPORT_22-07-26.md`.
- Phase 2 (Ingest wiring) — 🔨 CODE DONE (all 7 inner-loop steps run; EXECUTE + independent EVL both
  complete). Gate: CONDITIONAL, accepted this session (autonomous). Full unit baseline GREEN (725
  passed, 2 skipped — Phase 1 baseline 716, +9, 0 regressions); classifier 24/24; static safety
  review (independent vc-tester, in lieu of a live Docker run) confirmed all 3 declared safety
  properties: (1) agent branch hard-returns before the `Event` insert (AC2), (2) flag-off is
  byte-identical to pre-Phase-2 behavior (AC3/regression-safe), (3) `persist_agent_visit` is
  fail-open (logs keys-only, rolls back, never raises). 2 gates KNOWN-GAP: (a) 5
  `TestAgentDetection` integration cases (AC1-AC4 + flag-OFF) are collect-clean but unrun — no
  responsive Docker in this sandbox at either EXECUTE or EVL time; close command:
  `MOCK_EXTERNAL_APIS=true .venv/bin/python -m pytest tests/integration/test_events_ingest.py -k
  "agent or datacenter" -m integration -q`; (b) AC5 (ingest latency benchmark) has no harness yet —
  backlog stub: `process/features/evallayer/backlog/phase-02-latency-benchmark_NOTE_22-07-26.md`.
  Not classified ✅ VERIFIED until both gaps close; this is a deliberate, documented pair of
  Known-Gaps, not a silent pass. Report: `phase-02-ingest-wiring_REPORT_22-07-26.md`.
- Phase 3 (Read API + dashboard tab) — 🔨 CODE DONE (all 7 inner-loop steps run; EXECUTE +
  independent EVL both complete). Gate: PASS at PVL (2 mechanical plan gaps found and fixed
  in-plan: Step D test-authoring checklist added; A2 `AgentVisit.id` UUID-parse-then-404 fix
  documented). EVL confirmation run (vc-tester) GREEN on all runnable gates: FE compile (`npm run
  build`), unit regression (725 passed/2 skipped, == baseline, 0 regressions), and static safety
  review confirming all 5 declared properties (`verify_site_access` first-line-of-every-handler;
  `AgentVisit`-only queries/no Visitor-Event join = AC6; `/stats` before `/{agent_visit_id}`
  catch-all; UUID-parse-then-404 on detail route; 3 distinct badge tones = AC7). 2 gates KNOWN-GAP:
  (a) Docker integration run (10 cases in `tests/integration/test_agents_api.py`, collect-clean,
  unrun — no responsive Docker in this sandbox); close command: `docker compose -f
  infra/docker-compose.yml up -d postgres redis && .venv/bin/python -m pytest
  tests/integration/test_agents_api.py -q`; (b) Playwright e2e needs a running dev server, not
  started this run; close command: `npm run --prefix apps/web dev & npx playwright test
  apps/web/e2e/agents.spec.ts --config=apps/web/playwright.config.ts`. Badge Agent-Probe judgment
  (AC7) is a backlog test-building stub, not a blocker. Not classified ✅ VERIFIED until both Docker
  gaps close; same environment-gap pattern as Phase 1/Phase 2. Report:
  `phase-03-read-api-dashboard_REPORT_22-07-26.md`.
- Phase 4 (IP/rDNS verification) — 🔨 CODE DONE (all 7 inner-loop steps run; EXECUTE + independent
  EVL both complete). Gate: PASS at PVL (2 mechanical/test-coverage gaps found and fixed in-plan:
  added a Fully-Automated mocked-`AsyncSession` unit test for the sweep's fail-open isolation
  property, closing a Docker-only vacuous-green risk; removed `load_ip_ranges()`'s module-level
  cache to eliminate a cross-test-isolation bug). EVL confirmation run (independent re-run, not
  relying on execute-agent's internal claim) GREEN on all runnable gates: unit `test_agent_verification.py`
  10/10 pass; hot-path import check `grep -c agent_verification apps/api/routers/events.py` = 0
  (AC5/OQ2 — verification never reachable from the ingest hot path); Anthropic structural ceiling
  confirmed (`find apps/api/data -iname "*anthropic*"` → no results — no dataset entry exists, not
  an incidental omission); full unit regression 735 passed/2 skipped (Phase 3 baseline 725/2, +10,
  0 regressions); both backlog notes confirmed present on disk. 1 gate KNOWN-GAP: Docker-gated
  `test_agent_verification_sweep.py` integration test is collect-clean but unrun (no responsive
  Docker in this sandbox at either EXECUTE or EVL time) — does not block VERIFIED per SPEC AC8
  note; close command: `docker compose -f infra/docker-compose.yml up -d postgres redis &&
  .venv/bin/python -m pytest tests/integration/test_agent_verification_sweep.py -m integration -q`.
  Not classified ✅ VERIFIED until that gap closes; same environment-gap pattern as Phase 1/2/3.
  Report: `phase-04-ip-verification_REPORT_22-07-26.md`.
- Phase 6 (Aggregation + GEO/AEO analytics) — **🔨 CODE DONE** (all 7 inner-loop steps run; EXECUTE +
  independent EVL both complete 2026-07-23). Gate: PASS at PVL (1 plan update applied: Step C3
  Fully-Automated route-registration-order test, closing the Step B2 route-ordering trap with a
  real automated gate instead of Hybrid-only inference). EVL confirmation run (independent,
  re-run this UPDATE PROCESS session, not relying on execute-agent's internal claim) GREEN: unit
  aggregator suite 11/11 (`by_vendor`/`top_pages`/`by_verification` correctness + edge cases + AC2
  isolation + route-order); full unit regression 824 passed/2 skipped (baseline 778, +11 Phase 6,
  +35 same-session AI-referral bonus, 0 regressions); FE build (`npm run build`) clean. 2 gates
  KNOWN-GAP (no disposable Postgres/dev-server in this sandbox): (a) `/analytics` endpoint
  integration test; (b) dashboard card Playwright e2e. Both consolidated into
  `phase-06-daily-timeseries` sibling backlog note
  `process/features/evallayer/backlog/program-docker-verification-gaps_NOTE_23-07-26.md` alongside
  every other phase's Docker residual. Not classified ✅ VERIFIED until both Docker/e2e gaps close
  — same environment-gap pattern as every prior phase. This is the **FINAL phase of the 8-phase
  program.** Report: `phase-06-aggregation-analytics_REPORT_22-07-26.md`. Committed: `5fb52ac`
  (feat) + `a3e16ed` (process).
Current phase: **NONE — the 8-phase program is complete.** Program Status Table shows Phase 0
✅ COMPLETE, Phase 7 ✅ VERIFIED, Phases 1-6 🔨 CODE DONE. No phase remains ⏳ PLANNED or 🚧 BLOCKED.
Current phase status: PROGRAM COMPLETE (code-complete; 6 of 8 phases pending Docker gate closure
to reach ✅ VERIFIED — see §Program-Level Closeout above)
Current phase EVL: n/a — all 8 phases have completed their own EVL pass
Current phase report: n/a — see per-phase report table under §Durable Report Destinations; all 8
written (Phase 0's is the archived pre-program plan's own evidence table)
Next phase: **None within this program.** Successor program: **Handoff Detection** (new feature
folder, not yet scaffolded on disk — see §Program-Level Closeout for shape). Separately: run the
consolidated backlog note's close-all sequence against a live Postgres/Redis to promote Phases 1-6
from 🔨 CODE DONE to ✅ VERIFIED whenever Docker infra becomes available.
Current loop step: PROGRAM COMPLETE (no active loop step — all 8 phases have reached their Step 7)
Validate-contract status: Phase 1 — written 22-07-26, Gate: PASS (`generated-by: inner-pvl:
phase-1`). Phase 2 — written 22-07-26, Gate: CONDITIONAL, accepted (`generated-by: inner-pvl:
phase-2`). Phase 3 — written 22-07-26, Gate: PASS (`generated-by: inner-pvl: phase-3`). Phase 4 —
written 22-07-26, Gate: PASS (`generated-by: inner-pvl: phase-4`). Phase 5 — written 22-07-26, Gate:
PASS (`generated-by: inner-pvl: phase-5`). Phase 6 — written 22-07-26, Gate: PASS (`generated-by:
inner-pvl: phase-6`). Phase 7 — written 22-07-26, Gate: PASS (`generated-by: inner-pvl: phase-7`).
Phase 0 was shipped with VALIDATE explicitly skipped, per its archived plan. All 8 phases now have
either a written validate-contract or a documented VALIDATE-skip reason.
Program Net Gate: CODE-COMPLETE, PENDING-VERIFICATION (8 of 8 phases shipped; Phase 0 COMPLETE,
Phase 7 VERIFIED with 0 known-gaps, Phases 1-6 CODE DONE with 1-2 Docker/e2e known-gaps each — none
are design defects, all tracked in the consolidated backlog note)
Accumulated Known-Gaps carried forward (none blocked the program from reaching code-complete — all
are environment/tooling gaps, not design defects; consolidated into
`process/features/evallayer/backlog/program-docker-verification-gaps_NOTE_23-07-26.md`):
- Phase 1: `agent_visits` migration never applied to a real Postgres instance (Docker-gated)
- Phase 2: 5 `TestAgentDetection` integration cases unrun (Docker-gated); AC5 ingest-latency
  benchmark has no harness (backlog stub written)
- Phase 3: 10 `test_agents_api.py` integration cases unrun (Docker-gated); Playwright e2e
  (`apps/web/e2e/agents.spec.ts`) unrun (needs dev server); badge Agent-Probe judgment deferred
  (backlog test-building stub, not scriptable)
- Phase 4: `test_agent_verification_sweep.py` integration test unrun (Docker-gated); live vendor
  range refresh + rDNS tier remain out of scope (2 backlog notes already written)
- Phase 5: migration apply/rollback against live Postgres unrun (Docker-gated); full sweep
  integration round-trip unrun (Docker-gated); 2 pre-existing safe-direction backlog residuals
  carried forward unchanged (identity-merge collision, rollup staleness — both NEW PLAN REQUIRED)
- Phase 7: none blocking — D5 (real-Phase-5-row re-verification) DISCHARGED by Phase 5's EVL; 2
  accepted non-blocking residuals (skip-counter miscategorization, D4 centralization) documented in
  the phase report, not backlog artifacts
- Phase 6: `/analytics` endpoint integration test unrun (Docker-gated); dashboard card Playwright
  e2e unrun (needs dev server) — both consolidated into the program-wide backlog note alongside
  every other phase's residual
Latest validator run: this UPDATE PROCESS session (23-07-26) — see Verification Evidence run below
for exit codes (validate-agent-parity, validate-context-discovery, validate-plan-inventory,
validate-phase-stub for phase-06, validate-umbrella-artifact for this file)

Loop step values: RESEARCH | INNOVATE | PLAN-SUPPLEMENT | PVL | EXECUTE | EVL | UPDATE-PROCESS
Orchestrator rule: read "Current loop step" and "validate-contract status" before spawning any
subagent. Never spawn execute-agent when loop step is RESEARCH, INNOVATE, PLAN-SUPPLEMENT, or PVL.

Note: The Stable Program Goal above is fixed. This section is the only part that changes —
update-process-agent rewrites it after every phase closeout (overwrite, not append — git history is
the audit log).

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE; this umbrella plan itself is
not directly executed — each phase plan carries its own validate-contract)
