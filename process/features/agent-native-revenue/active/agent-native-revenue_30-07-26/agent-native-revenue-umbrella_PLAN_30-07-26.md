---
name: plan:agent-native-revenue-umbrella
description: "Agent-Native Revenue — umbrella/orchestration plan for the 4-workstream (WS0-WS3) program; WS4 parked"
date: 30-07-26
metadata:
  node_type: memory
  type: plan
  feature: agent-native-revenue
  phase: umbrella
---

# Agent-Native Revenue — Umbrella Plan

Date: 30-07-26
Status: PLANNED
**Date:** 30-07-26
**Complexity:** COMPLEX
**Status:** ⏳ PLANNED

- Program type: PHASE PROGRAM (4 active workstreams: WS0 → {WS1 ∥ WS2} → WS3; WS4 parked as design-note only)
- Feature folder: `process/features/agent-native-revenue/`
- Scaffold note: this is the umbrella charter + thin phase stubs only. Detailed per-phase checklists
  come from each phase's own RESEARCH step. Several stub fields are marked `OPEN — research-pending`
  per instruction — do not treat those as decided.

---

## Overview

This is a phase-program umbrella plan for **Agent-Native Revenue**: reposition Beam from
"detect the AI agent" to "greet the agent, identify the company behind it, and trade a
structured answer for qualification context." Four active workstreams (WS0 Ops gate, WS1 AI
Evaluation Timeline, WS2 Agent-driven session classifier, WS3 Agent Concierge kill test) plus
one parked design-note-only workstream (WS4 Network intel). See the Program Goal Charter below
for north star, definition of done, scope tiers, and hard safety constraints.

---

## Program Goal Charter

```
Agent-Native Revenue — Program Goal Charter

North star:
- Make Beam the reception desk for AI shopping/buying agents: greet the agent, identify the
  company behind it, and trade a structured qualified answer for qualification context — not
  just detect that an agent visited.

Definition of done (an unattended agent must be able to do all of these):
1. Resolve a real company from a handoff (agent fetch -> human click) on prod, at least once,
   with documented wild survival per identity vendor (WS0).
2. Render a sales-readable per-company "AI evaluation timeline" (fetch sequence: page, vendor,
   time) joined to the resolved company row in the dashboard (WS1).
3. Label human-shaped-but-agent-operated browser sessions (Atlas/Comet/Claude-in-Chrome/
   Playwright) without blocking or degrading UX, validated against a corpus with a
   research-set TPR/FPR threshold (WS2).
4. Stand up one live MCP concierge on a real site trading a structured answer (pricing,
   comparison, security questionnaire) for required qualification params, plus a zero-click
   lead tool, and report a signed GO/NO-GO from >=20 real wild AI-agent queries (WS3).

What "verified" means (program level):
- WILD DATA ONLY. Per guardrail 3: every survival/adoption/detection claim requires real
  prod or staging-tunnel evidence from a real external AI agent/vendor. A lab-only pass
  (mocked UA, synthetic corpus alone, local curl) NEVER closes a phase — it is necessary but
  not sufficient.
- validate-contract gates must be recorded alongside phase gates and regression evidence for
  a phase to reach VERIFIED. A phase without a validate-contract (or documented skip reason)
  cannot be marked VERIFIED.
- A workstream can be CODE DONE (implementation complete, lab-tested) without being VERIFIED
  (wild-tested). Keep this distinction honest in every phase report and status table.

Scope tiers → phase mapping:
- Tier 0 (prerequisite gate) — WS0 Ops gate: marker + resolution priority live on prod
- Tier 1 (company-level "who") — WS1 AI Evaluation Timeline (depends on WS0(b), not WS0(d))
- Tier 2 (session-level "who") — WS2 Agent-driven session classifier (independent of WS0/WS1,
  can run in parallel)
- Tier 3 (person-level "who," self-declared only) — WS3 Agent Concierge kill test (highest
  info/$, timeboxed 1 week)
- This program answers "who is behind the agent" at 3 levels: company (WS0+WS1), session/agent
  (WS2), self-declared qualification + lead (WS3). It does NOT retire any existing detection
  tier — it builds a revenue/product layer on top of the existing EvalLayer detection floor.

Explicitly out of scope (deferred tier):
- WS4 Network intel — PARKED. Design-note only (one privacy-scoped aggregate design-note page),
  no code, delivered inside the final phase's UPDATE PROCESS.
- No "cookie for AI agents" (server-side fetchers hold no per-user jar — dead end, do not
  attempt).
- No person-level identity from inference (only ever from consented self-declaration via WS3's
  ACP-pattern tool call).
- No anti-bot/blocking product — do not compete with Cloudflare/DataDome.
- No rebuild of the existing detection layer (agent_classifier.py / EvalLayer floor is
  sufficient); no F14 Web Bot Auth work until WS0-WS3 are done.

Hard safety constraints (non-negotiable, per phase) — the 6 locked guardrails:
1. Emailability separation is absolute: agent records never become emailable leads. Leads only
   ever originate from a tool/form submission with agent-provided contact info (WS3 path).
   This mirrors and must not weaken the existing `source_agent_visit_id` exclusion guardrail.
2. Never push commits to `dev_nhantc2` (another person's active branch). Fix CI issues on a new
   branch cut off it. After merge to main: commit directly on `main` per repo policy.
3. Wild-test discipline: every survival/adoption claim needs real prod/staging-tunnel data from
   a real external agent/vendor. A lab-only pass never ends a phase. No wild data = no claim,
   full stop.
4. WS2 must only ever LABEL suspected-agent sessions, never block or degrade UX for them.
5. Any schema, auth, API-contract, or billing change stops at the VALIDATE gate — no shortcut
   lane, no exception for "small" changes in this program.
6. tracker.js (WS2 surface): every change ships with e2e coverage AND a bundle-size check; no
   new pixel network call beyond the existing event call.

Additional standing constraint:
- Commit each phase's execution changes before starting the next phase. Keep process/plan/
  context commits separate from execution commits.
```

---

## Stable Program Goal (copy-paste this to start autonomous execution)

```
SESSION GOAL: agent-native-revenue — Agent-Native Revenue (reception desk for AI buying agents)
Ref: process/features/agent-native-revenue/active/agent-native-revenue_30-07-26/agent-native-revenue-umbrella_PLAN_30-07-26.md

TARGET: WS0 gate live on prod with >=1 wild identified_visitors row via handoff; WS1 renders
>=1 real sales-readable company timeline; WS2 corpus-validated label with research-set TPR/FPR
and zero pixel e2e regression; WS3 signed GO/NO-GO from >=20 real wild AI-agent MCP queries.
WS4 = design-note only, delivered at program close. Test tiers: automated (iterate-until-green)
/ hybrid (fix-if-in-blast-radius) / agent-probe (record-judgment). WILD DATA REQUIRED for any
survival/adoption claim — lab pass alone never closes a phase (guardrail 3).

AUTONOMY: Before ANY subagent spawn, read:
1. This file's ## Current Execution State -> loop step + validate-contract status
2. The active phase plan's ## Phase Loop Progress -> first unchecked box = next subagent to spawn

PER-PHASE LOOP (7-step inner loop R -> I -> P -> PVL -> E -> EVL -> UP, never skip, never
reorder; SKIPS SPEC -- SPEC runs once in the outer program loop):
  1. RESEARCH -> 2. INNOVATE -> 3. PLAN-SUPPLEMENT -> 4. PVL -> 5. EXECUTE -> 6. EVL -> 7. UPDATE-PROCESS
- PLAN-SUPPLEMENT: plan-agent writes research/innovate gaps into phase plan (or "n/a -- clean")
- PVL NEVER skipped; contract must follow example-validate-output.md full format; a partial
  contract (missing Plan updates applied / Execute-agent instructions / Test gates) = blocked
  same as a placeholder
- Every subagent FIRST ACTION: run vc-context-discovery (context group files + all-tests.md
  routing chain) AND vc-plan-discovery (same-feature full depth; other features active-only;
  general-plans active)
- Every phase-END: invoke vc-agent-strategy-compare for the next step's strategy recommendation

Report via phase reports. No approval between phases unless a hard stop is hit.

HARD STOPS (pause, wait for human):
- Merge PR dev_nhantc2 -> main
- Flip any prod flag/env (marker flag, ENCRYPTION_KEY rollout, WS2/WS3 feature flags)
- Any provider API spend beyond free tier
- Any schema/auth/API-contract/billing/emailability touch
- Any action on branch dev_nhantc2
- Publishing anything to a public site
- Net gate = BLOCKED with no backlog resolution path
- Validate-contract is placeholder and vc-validate-agent cannot run

SAFETY (never override -- the 6 locked guardrails):
1. Agent records never become emailable leads -- leads only via WS3 tool/form submission
2. Never commit to dev_nhantc2 -- new branch off it, PR, then main
3. Wild-data discipline -- lab pass never ends a phase
4. WS2 labels, never blocks, no UX degradation
5. Schema/auth/API/billing changes stop at VALIDATE, no shortcut
6. tracker.js changes ship with e2e + size check, no new pixel network calls
Commit each phase before advancing; process and execution commits stay separate.

TEST GATES (every phase exit):
  node .claude/skills/vc-audit-vc/scripts/validate-agent-parity.mjs
  node .claude/skills/vc-audit-vc/scripts/validate-skills.mjs
  node .claude/skills/vc-audit-context/scripts/validate-context-discovery.mjs
  node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs <phase-plan-path>
  Plus phase-specific gates recorded in that phase's Verification Evidence table.

VALIDATE CONTRACT: Per-phase contracts written by vc-validate-agent into each phase plan
before EXECUTE. None written yet.

START: WS0, loop step RESEARCH (in flight). Spawn/continue vc-research-agent for WS0's Ops
gate research: confirm dev_nhantc2 -> main PR status, prod env readiness (ENCRYPTION_KEY,
marker flag, PDL/Proxycurl keys), and design the wild marker-survival test per vendor.
```

---

## Phase Ordering

See "Workstream Sequence" table immediately below for the ordered workstream list, join
conditions, and dependencies (WS0 gate -> {WS1 (fka Phase 1) parallel with WS2 (fka Phase 2)} ->
WS3 (fka Phase 3); WS4 parked, no phase number).

## Workstream Sequence

| Workstream | Plan file | Scope summary | Depends on |
|---|---|---|---|
| WS0 — Ops gate (prerequisite) | `process/features/agent-native-revenue/active/agent-native-revenue_30-07-26/phase-ws0-ops-gate_PLAN_30-07-26.md` | Merge dev_nhantc2->main, prod env readiness, wild marker-survival test per vendor | GitHub billing fix (user action, HARD STOP — not code) |
| WS1 — AI Evaluation Timeline | `process/features/agent-native-revenue/active/agent-native-revenue_30-07-26/phase-ws1-eval-timeline_PLAN_30-07-26.md` | Per-company AI-fetch timeline joined to resolved company row, rendered in dashboard | WS0(b) merge only — NOT WS0(d) wild-survival test |
| WS2 — Agent-driven session classifier | `process/features/agent-native-revenue/active/agent-native-revenue_30-07-26/phase-ws2-session-classifier_PLAN_30-07-26.md` | Label human-shaped-but-agent-operated sessions in tracker.js; label-not-block | Independent of WS0/WS1 — can run in parallel with WS1 |
| WS3 — Agent Concierge kill test | `process/features/agent-native-revenue/active/agent-native-revenue_30-07-26/phase-ws3-concierge-kill-test_PLAN_30-07-26.md` | MCP gateway trades structured answer for qualification params; zero-click lead tool; 1-week wild kill test | WS0 gate live (identity resolution path proven); benefits from WS1 context but not blocked by it |
| WS4 — Network intel (PARKED) | design-note only, delivered inside final phase's UPDATE PROCESS report | Privacy-scoped aggregate design — NO CODE | N/A — explicitly parked |

### Join Conditions

- WS1 and WS2 MUST NOT start implementation until WS0(b) (PR merge) is confirmed. WS1 additionally
  needs WS0(c) prod env readiness for its "resolved company row" join to have real data, but WS1's
  own research/innovate/plan-supplement steps may proceed once WS0(b) is confirmed even before
  WS0(d) wild-survival test completes.
- WS2 has NO dependency on WS0 or WS1 — it may start its own RESEARCH step immediately, in
  parallel with WS0, subject to the orchestrator's parallel fan-out judgment.
- WS3 MUST NOT begin its wild kill-test week until WS0's exit metric (>=1 identified_visitors
  row via handoff on prod) is met — WS3's MCP gateway needs a working identity-resolution path
  to produce a real lead, not just a tool-call log.
- WS4 never becomes an implementation phase in this program; it is written as a design note
  only, at program close.

---

## Per-Workstream Entry / Exit (Kill-Test) Criteria

| Workstream | Entry | Exit / kill-test gate |
|---|---|---|
| WS0 | User has resolved the GitHub Actions billing HARD STOP (not a code task) | dev_nhantc2->main PR merged; prod env (ENCRYPTION_KEY, marker flag, PDL/Proxycurl keys) confirmed live; wild marker-survival test run per vendor and journaled YES/NO (with path-token /r/<token> 302 fallback attempted before declaring a vendor dead); exit metric: >=1 `identified_visitors` row on prod tied to a handoff/ai_source visitor |
| WS1 | WS0(b) merge confirmed | >=1 real, sales-readable per-company AI-evaluation timeline rendered in the dashboard, reviewable without further explanation |
| WS2 | Can start independently | Self-built Playwright/CDP corpus + manual Comet/Atlas samples all correctly labeled; FPR on real-human sessions under the research-set threshold; zero pixel e2e regression; tracker.js stays within the research-set size budget |
| WS3 | WS0 exit metric met | Binary WILD kill test: >=20 real queries via ChatGPT + Claude against 1 real site's MCP concierge; measured tool-discovery rate, tool-call rate, param-fill rate, lead-event count; signed GO/NO-GO — no calls means STOP, journal, keep detection as floor, and promote WS2 to program priority 1 |
| WS4 | Program winding down | One privacy-scoped aggregate design-note page, written during the final phase's UPDATE PROCESS — no code, no exit gate beyond "note exists and is reviewed" |

---

## Per-Workstream Loop

Each workstream executes the canonical 7-step inner loop `R → I → P → PVL → E → EVL → UP`. This
inner loop SKIPS SPEC — SPEC runs once in the outer program loop, not per workstream.

1. **RESEARCH** — spawn research-agent: load context, read prior phase reports, check plan drift,
   resolve the workstream's `OPEN — research-pending` questions listed in its stub, document findings
2. **INNOVATE** — spawn innovate-agent: decide approach; write Decision Summary (chosen approach +
   rejected alternatives), informed by RESEARCH's resolved open questions
3. **PLAN-SUPPLEMENT** — spawn plan-agent: if research/innovate found gaps/pre-conditions not in the
   stub checklist, expand the stub into a full checklist; otherwise mark "n/a — research clean"
4. **PVL** — spawn vc-validate-agent: full V1–V7; validate-contract written per
   `.claude/skills/vc-validate-findings/references/example-validate-output.md` format
5. **EXECUTE** — spawn vc-execute-agent per approved plan and validate-contract; guardrails 1-6
   enforced throughout; hard stops honored, never auto-approved
6. **EVL** — spawn vc-tester: run workstream test gates to green (lab tier), then run the WILD gate
   per guardrail 3 before declaring VERIFIED; register follow-up stubs; write EVL HANDOFF SUMMARY
7. **UPDATE-PROCESS** — write phase report to durable report path, rewrite this umbrella's
   `## Current Execution State` section (overwrite, not append — git history is the audit log)

**PVL is NEVER skipped.** A placeholder `## Validate Contract` = blocked. Do not spawn
execute-agent while a workstream's Validate Contract section reads "(placeholder — vc-validate-agent
writes this section before EXECUTE)".

---

## Autonomous Execution Rules (During /goal)

- Agent self-decides at all V5 gates — no user approval needed between workstreams, EXCEPT the 6
  hard stops named in the Stable Program Goal block above (these always pause for a human,
  regardless of /goal autonomy).
- CONDITIONAL net gate: proceed autonomously, fixes applied in-flight, gaps on record.
- BLOCKED net gate: document items in backlog, continue with remaining workstreams; backlog is
  always a valid resolution — always find a path forward, except when the blocker IS one of the
  6 hard stops (those never auto-resolve).
- Agent writes phase reports, updates phase plans, creates new sub-plans as needed — all
  autonomously.
- The phase report is the communication channel for conflicts, errors, and learnings — not
  inline questions.
- Wild-test discipline (guardrail 3) is NOT waivable by autonomy: a workstream cannot be marked
  VERIFIED on lab evidence alone even under full /goal autonomy.

---

## Phased Delivery Plan (Workstream Stubs)

This umbrella plan's phased delivery plan is the workstream sequence above plus the stubs
below. Each workstream's own Implementation Checklist is written by its RESEARCH +
PLAN-SUPPLEMENT steps (per the 7-step inner loop) — not fabricated here.

## Workstream Stubs

Detailed checklists are intentionally deferred to each workstream's own RESEARCH step. These
stubs are the pre-research scaffold only — do not treat unresolved `OPEN` items as decided.

### WS0 — Ops Gate (prerequisite)

- **Goal:** Get the identity-resolution path (marker + resolution priority) live on prod so every
  downstream workstream has real data to work against.
- **Definition of done:** dev_nhantc2->main PR merged; prod env vars set (ENCRYPTION_KEY, marker
  flag, PDL/Proxycurl provider keys); wild marker-survival test run and journaled per vendor.
- **Kill test:** Wild survival YES/NO per vendor, recorded in the phase report/journal. If NO for
  a vendor, attempt the path-token `/r/<token>` 302 fallback before declaring that vendor dead. A
  temporal sweep is the safety net for delayed survival. Exit metric: at least 1
  `identified_visitors` row on prod for a handoff/`ai_source` visitor.
- **Key items:**
  - (a) **HARD STOP — user action, not code.** GitHub Actions billing failure on `main`
    ("payments failed / spending limit") must be fixed by the user before any CI-dependent step
    can run. This corrects the earlier misdiagnosis that CI was red on `be7fc6c` — CI never ran on
    `dev_nhantc2` because the workflow triggers only on `main`.
  - (b) PR `dev_nhantc2` -> `main`, merge after review (guardrail 2: never push to `dev_nhantc2`
    directly; branch off it for any CI fix, then PR to `main`).
  - (c) Prod env: `ENCRYPTION_KEY`, marker flag, provider keys (PDL/Proxycurl).
  - (d) Wild marker-survival test per vendor.
- **Key files:** TBD at RESEARCH (marker/resolution-priority surface — likely
  `apps/api/services/identity_resolver.py`, `apps/api/config.py`, deploy env docs).
- **Dependencies:** none upstream (this is the program's prerequisite gate); WS1 depends on (b),
  WS3 depends on the full exit metric.
- **Open — research-pending:** (5) whether the new resolution priority needs backfill for
  pre-merge handoff visitors.

### WS1 — AI Evaluation Timeline

- **Goal:** Turn "traffic from ChatGPT" into a per-company, sales-readable timeline of AI-agent
  fetch activity (page, vendor, time, on-demand/index) joined to the resolved company row.
- **Definition of done:** Dashboard renders at least 1 real company timeline that a salesperson
  can read without further explanation.
- **Kill test:** >=1 real company timeline, sales-readable without explanation.
- **Key files:** `apps/api/services/agent_aggregator.py`, models `agent_fetch_events` /
  `agent_handoff_links`, `apps/web/src/components/*` (exact dashboard component TBD at RESEARCH).
- **Dependencies:** WS0(b) merge only — explicitly NOT gated on WS0(d) wild-survival test, so WS1
  research/innovate/plan-supplement can proceed in parallel with WS0(d).
- **Open — research-pending:** (4) where the eval timeline lives in the current dashboard IA and
  which company row is the anchor.

### WS2 — Agent-driven Session Classifier

- **Goal:** Label human-shaped-but-agent-operated browser sessions (Atlas, Comet,
  Claude-in-Chrome, Playwright/CDP) in `apps/pixel/src/tracker.js` — carry the principal's
  company IP+cookie through, label then resolve normally. Label-not-block, always.
- **Definition of done:** Classifier implemented behind a flag (default OFF, matching program
  precedent), corpus-validated, zero pixel e2e regression.
- **Kill test:** Self-built Playwright/CDP corpus + manual Comet/Atlas samples all labeled
  correctly; FPR on real-human sessions under a research-set threshold.
- **Signals (research finalizes the exact set/weights):** `navigator.webdriver`, CDP/Playwright
  window artifacts, UA-CH `HeadlessChrome`, near-zero pointer entropy pre-click, dead-center
  clicks, robotic form-fill cadence, no scroll momentum, agentic-browser self-declared UA/brand.
- **Key files:** `apps/pixel/src/tracker.js` (+ `apps/pixel/e2e/`), `apps/api/routers/events.py`,
  `apps/api/services/agent_classifier.py`, Visitor model (new agent-operated label),
  `apps/api/services/agent_company_resolution.py` (reuse pattern per program precedent).
- **Dependencies:** none — independent of WS0/WS1, may run in parallel.
- **Open — research-pending:** (1) Atlas/Comet/Claude-in-Chrome UA self-declaration state as of
  7/2026; (3) WS2 TPR/FPR threshold, corpus design, and tracker.js size budget.

### WS3 — Agent Concierge Kill Test (timebox 1 week)

- **Goal:** Flip the MCP gateway from FREE content to a TRADE — a structured answer (configured
  pricing, comparisons, security questionnaire) gated behind required params (`use_case`,
  `company_size`, `evaluating_against`), plus a zero-click conversion tool
  (`request_quote`/`book_demo`) that fires a lead with full context to the site owner's inbox.
- **Definition of done:** Live on 1 real site for 1 week; signed GO/NO-GO report from real wild
  queries.
- **Kill test (binary, WILD):** >=20 real queries via ChatGPT + Claude; measure tool-discovery
  rate, tool-call rate, param-fill rate, lead-event count. No calls -> STOP, journal, keep
  detection as floor, and promote WS2 to program priority 1. Calls -> this becomes the main
  product axis. Lab testing does NOT count toward this kill test.
- **Key files:** `apps/api/services/agent_gateway.py`, existing MCP surface (`agent_mcp.py`),
  agent profile CRUD (`agent_profile.py`), offers feed (TBD — likely new module, confirm at
  RESEARCH).
- **Dependencies:** WS0 exit metric (identity resolution must work for a lead to resolve to a
  real company); benefits from, but is not blocked by, WS1's timeline UI.
- **Open — research-pending:** (2) the real discovery path for a buyer's agent to find an SMB's
  MCP concierge in ChatGPT consumer; (6) whether the path-token `/r/<token>` redirect (from WS0's
  fallback) has any SEO/canonical impact worth guarding against here.

### WS4 — Network Intel (PARKED)

- **Status:** Explicitly parked. Design-note only — no code, no phase plan file, no exit gate.
- **Deliverable:** One privacy-scoped aggregate design-note page, written inside the FINAL
  workstream's UPDATE PROCESS step (i.e., at program close, once WS0-WS3 have concluded).
- **Dependencies:** None — does not block or get blocked by WS0-WS3.

---

## Global Constraints (the 6 locked guardrails, restated for execute-agent visibility)

1. Emailability separation is absolute — agent records never become emailable leads; leads only
   from WS3 tool/form submission with agent-provided contact.
2. Never push commits to `dev_nhantc2` — branch off it for CI fixes, PR to `main`; post-merge,
   commit directly on `main` per repo policy.
3. Wild-test discipline — every survival/adoption claim needs real prod/staging-tunnel data; lab
   pass never ends a phase; no data = no claim.
4. WS2 = label, not block — zero UX degradation for suspected-agent sessions.
5. Schema/auth/API-contract/billing changes stop at VALIDATE — no shortcut lane.
6. tracker.js — every change ships with e2e + size check; no new pixel network call beyond the
   existing event call.
7. After every phase that touches agent files, run the parity validator and confirm exit 0 before
   declaring the phase DONE.
8. Commit each phase's execution changes before starting the next phase; keep process/plan/context
   commits separate from execution commits.

---

## Durable Report Destinations

| Workstream | Report path (inside task folder) |
|---|---|
| WS0 — Ops Gate | `process/features/agent-native-revenue/active/agent-native-revenue_30-07-26/phase-ws0-ops-gate_REPORT_30-07-26.md` |
| WS1 — AI Evaluation Timeline | `process/features/agent-native-revenue/active/agent-native-revenue_30-07-26/phase-ws1-eval-timeline_REPORT_30-07-26.md` |
| WS2 — Agent-driven Session Classifier | `process/features/agent-native-revenue/active/agent-native-revenue_30-07-26/phase-ws2-session-classifier_REPORT_30-07-26.md` |
| WS3 — Agent Concierge Kill Test | `process/features/agent-native-revenue/active/agent-native-revenue_30-07-26/phase-ws3-concierge-kill-test_REPORT_30-07-26.md` |
| WS4 — Network Intel (design note) | Written inline in the final workstream's UPDATE PROCESS report (no dedicated file until that point) |

---

## Program Status Table

| Workstream | Status |
|---|---|
| WS0 — Ops Gate | ⏳ PLANNED (HARD STOP: GitHub billing fix pending — user action) |
| WS1 — AI Evaluation Timeline | ⏳ PLANNED |
| WS2 — Agent-driven Session Classifier | ⏳ PLANNED |
| WS3 — Agent Concierge Kill Test | ⏳ PLANNED |
| WS4 — Network Intel | ⏸️ PARKED (design-note only) |

Status values: ⏳ PLANNED | 🔨 CODE DONE | 🧪 TESTING | ✅ VERIFIED | 🚧 BLOCKED | ✅ COMPLETE | ⏸️ PARKED

---

## Touchpoints

- `apps/api/services/identity_resolver.py`, `apps/api/config.py` — WS0 marker/resolution priority
- `apps/api/services/agent_aggregator.py`, `apps/web/src/components/*` — WS1 timeline
- `apps/pixel/src/tracker.js`, `apps/pixel/e2e/`, `apps/api/services/agent_classifier.py` — WS2
- `apps/api/services/agent_gateway.py`, `agent_mcp.py`, `agent_profile.py` — WS3
- No WS4 touchpoints (design note only)

---

## Public Contracts

- Existing pixel event contract unchanged (WS2 adds a label, no new network call — guardrail 6).
- Existing MCP gateway surface extended (not replaced) by WS3's structured-trade tools; existing
  free-content behavior stays intact unless a phase explicitly documents a breaking change and
  routes it through VALIDATE per guardrail 5.
- `is_emailable_identity()` guard contract unchanged — WS3 leads must flow through the existing
  tool/form-submission path, never bypass the agent-origin exclusion (guardrail 1).

---

## Blast Radius

Exact file list TBD per-workstream at RESEARCH. Known likely areas from the locked brief:

- `apps/api/services/identity_resolver.py`, `apps/api/config.py`, deploy/env docs (WS0)
- `apps/api/services/agent_aggregator.py`, dashboard components under `apps/web/src/components/`
  (WS1)
- `apps/pixel/src/tracker.js`, `apps/pixel/e2e/`, `apps/api/routers/events.py`,
  `apps/api/services/agent_classifier.py`, Visitor model, `agent_company_resolution.py` (WS2)
- `apps/api/services/agent_gateway.py`, `agent_mcp.py`, `agent_profile.py`, offers-feed module
  (WS3)
- Multi-package, schema-adjacent risk present (WS2's new Visitor label, WS3's lead-tool path) —
  guardrail 5 applies; VALIDATE gate is mandatory, no shortcut.

---

## Verification Evidence

```bash
# Program-level parity/skill/context validators — run after every workstream
node .claude/skills/vc-audit-vc/scripts/validate-agent-parity.mjs
node .claude/skills/vc-audit-vc/scripts/validate-skills.mjs
node .claude/skills/vc-audit-context/scripts/validate-context-discovery.mjs
# Expected: all exit 0

# Umbrella/phase-stub structure validators — run once phase plans exist
node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs <phase-plan-path>
# Expected: no FAIL lines

# WS0 exit metric (illustrative — exact query TBD at WS0 RESEARCH)
# SELECT count(*) FROM identified_visitors WHERE source_agent_visit_id IS NULL AND ... (handoff/ai_source join)
# Expected: >= 1 on prod
```

Per-workstream Verification Evidence tables (with `| Gate / Scenario | Strategy | Proves SPEC
criterion |`) will be added by each workstream's own PLAN-SUPPLEMENT step once RESEARCH resolves
the `OPEN — research-pending` items above — writing them now would fabricate detail not yet known.

---

## Test Infra Improvement Notes

(none identified yet)

---

## Resume and Execution Handoff

- Selected plan file path:
  `process/features/agent-native-revenue/active/agent-native-revenue_30-07-26/agent-native-revenue-umbrella_PLAN_30-07-26.md`
- Last completed step: umbrella charter + workstream stubs written (this file)
- Validate-contract status: not written (placeholder — no PVL run yet for any workstream)
- Supporting context files loaded: `process/context/all-context.md`,
  `process/development-protocols/phase-programs.md`,
  `.claude/skills/vc-generate-phase-program/references/program-goal-charter-template.md`
- Next step for a fresh agent: Read this umbrella plan in full, then spawn vc-research-agent for
  WS0 — first confirm with the user whether the GitHub Actions billing HARD STOP has been
  resolved (WS0(a) is a user action, not something research/execute can do), then proceed with
  WS0(b)/(c)/(d) research. WS2's research may be spawned in parallel per the orchestrator's
  fan-out judgment since WS2 has no WS0 dependency.

---

## Current Execution State

Last updated: 30-07-26
Completed phases: none (program just chartered)
Current phase: WS0 — Ops Gate
Current loop step: RESEARCH (in flight — awaiting user confirmation that the GitHub billing HARD
STOP is resolved before WS0(b)/(c)/(d) research can produce actionable findings)
Validate-contract status: pending — none written yet
Program Net Gate: PENDING
Latest validator run: not yet run against this program's artifacts

Loop step values: RESEARCH | INNOVATE | PLAN-SUPPLEMENT | PVL | EXECUTE | EVL | UPDATE-PROCESS
Orchestrator rule: read "Current loop step" and "validate-contract status" before spawning any
subagent. Never spawn execute-agent when loop step is RESEARCH, INNOVATE, PLAN-SUPPLEMENT, or PVL.

Note: The Stable Program Goal above is fixed. This section is the only part that changes —
update-process-agent rewrites it after every workstream closeout (overwrite, not append — git
history is the audit log).

---

## Pre-PVL Conflict Resolution

Not yet applicable — no phase plans have entered PVL. When WS1 and WS2 (or any two workstreams)
run PVL/EXECUTE concurrently, the orchestrator must classify each shared package here as
`parallel-safe` or `reassign` (naming the winning workstream) before outer PVL begins. Current
assessment from the stubs above: WS1 (`apps/api/services/agent_aggregator.py`,
`apps/web/src/components/*`) and WS2 (`apps/pixel/src/tracker.js`, `apps/api/routers/events.py`,
`apps/api/services/agent_classifier.py`) touch disjoint file sets — **parallel-safe**, pending
confirmation once each workstream's RESEARCH step produces its real Touchpoints list. WS3
(`apps/api/services/agent_gateway.py`, `agent_mcp.py`, `agent_profile.py`) is also disjoint from
WS1/WS2's known areas — **parallel-safe**, same caveat. Re-run this check with real file lists
before any outer PVL fan-out.

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
