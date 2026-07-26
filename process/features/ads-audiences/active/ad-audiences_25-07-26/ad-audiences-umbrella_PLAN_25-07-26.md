---
name: plan:ad-audiences-umbrella
description: "Ad Audiences — umbrella/orchestration plan for the 3-phase program (foundation + Meta live + Google live)"
date: 25-07-26
metadata:
  node_type: memory
  type: plan
  feature: ads-audiences
  phase: umbrella
---

# Ad Audiences — Umbrella Plan

**Date:** 25-07-26
**Complexity:** COMPLEX
**Status:** ⏳ PLANNED
Date: 25-07-26
Status: PLANNED

## Overview

Ad Audiences lets a Beam user connect Meta and Google ad accounts via OAuth (mirroring the
existing CrmConnectPanel pattern) and push an identified-visitor segment directly into a live
ad-platform audience, replacing the manual CSV download/upload step. This is a 3-phase
program (see Phased Delivery Plan / Phase Sequence below): Phase 1 builds the full CRM-mirror
foundation in mock mode; Phase 2 wires real Meta OAuth + Custom Audience push; Phase 3 wires
real Google OAuth + Data Manager API push with EEA-region exclusion. See the SPEC at
`process/features/ads-audiences/active/ad-audiences_25-07-26/ad-audiences_SPEC_25-07-26.md`
for the full 13 acceptance criteria this program proves.

- Program type: PHASE PROGRAM (3 phases; Phase 1 foundation, Phase 2 + Phase 3 both depend on Phase 1 but are otherwise independent of each other)
- SPEC: `process/features/ads-audiences/active/ad-audiences_25-07-26/ad-audiences_SPEC_25-07-26.md` (13 ACs, locked)
- Feature folder: `process/features/ads-audiences/`
- Locked INNOVATE decision: **"CRM-mirror, not CRM-extend"** — zero edits to `apps/api/models/crm_connection.py`, `apps/api/routers/crm.py`, `apps/api/services/crm.py`/`services/crm/`, `apps/api/services/crm_push.py`, `apps/api/services/crm_rate_limiter.py`, `apps/api/tasks/crm_tasks.py`, `apps/api/services/csv_exporter.py`. All ad-audience code is net-new, importing shared helpers (`_sha256`, `_get_segment_visitors`) rather than extracting or refactoring them.

---

## Program Goal Charter

```
Ad Audiences — Program Goal Charter

North star:
- Let a Beam user connect an ad platform (Meta or Google) once and push a segment straight
  into a live ad audience with one click, replacing the manual CSV download/upload step,
  without ever touching or risking the existing CRM connector code path.

Definition of done (an unattended agent must be able to do all of these):
1. Connect Meta and Google ad accounts via OAuth (mirroring the CrmConnectPanel UX exactly),
   see connected/error/not-connected status, and disconnect cleanly.
2. Push a segment to a connected platform: only safety-cleared visitors
   (do_not_email / agent-origin-excluded / do_not_sell all filtered via `_get_segment_visitors`
   verbatim) are ever included, every identifier is SHA256-hashed before leaving Beam
   (`_sha256` reused verbatim), and re-pushing the same segment updates rather than
   duplicates the platform-side audience.
3. LinkedIn shows a disabled "coming soon" card (CSV export unaffected); the whole feature is
   gated behind `ad_audiences_enabled` (default OFF) and works fully deterministically under
   `MOCK_EXTERNAL_APIS=true` before any live-provider work begins.
4. EEA-region visitors are excluded from Google pushes specifically (Meta has no equivalent
   consent-field requirement in this SPEC) — this is the locked v1 answer to SPEC Open
   Question 4.

What "verified" means (program level):
- Every phase's validate-contract (V1-V7, full example-validate-output.md format) is written
  and its Gate is PASS or explicitly-accepted CONDITIONAL before that phase is marked VERIFIED.
- Phase 1 exit = all 13 ACs provable in mock mode (flag on, MOCK_EXTERNAL_APIS=true); Phase 2 /
  Phase 3 exit = the respective live-provider ACs (2/6/7/13 for Meta, 3 for Google) additionally
  hold against a Hybrid-tier sandbox smoke per the SPEC's declared strategy per AC.
- A phase without a validate-contract (or a documented skip reason) cannot be marked VERIFIED.

Scope tiers → phase mapping:
- Tier 1 (Foundation: models, services/ads skeleton, router, UI panel, mock-mode parity) → Phase 1
- Tier 2 (Meta live: real OAuth + Custom Audience create/upload) → Phase 2
- Tier 3 (Google live: real OAuth + Data Manager API + EEA exclusion) → Phase 3
- This program retires Tiers 1-3. LinkedIn live push, auto-sync/scheduled re-push, ads
  performance reporting, and audience-deletion-propagation guarantees are NOT retired by this
  program — they are explicitly out of scope per SPEC.

Explicitly out of scope (deferred tier):
- LinkedIn Matched Audiences API push (CSV-export-only stays; SPEC-confirmed, two-approval
  path not viable this scope).
- Automatic/scheduled re-push (auto_push) — CRM has this precedent, ads pushes stay manual v1.
- Ads performance reporting (spend/reach/conversion read-back).
- Audience deletion propagation guarantees on disconnect.
- PII-at-rest encryption of IdentifiedVisitor.email — tracked in the separate active
  `pii-at-rest_22-07-26` general plan; noted here as a cross-plan dependency RISK (see
  "Global Constraints" below), not something this program blocks on.
- Meta "Full Access" tier (managing other users' ad accounts).
- Google production dev-token approval as a blocking gate for the whole feature (sandbox path
  ships first; wider production rollout per site is a separate later operator action).
- EEA-consent sourcing options (a) pixel-consent mapping and (b) manual site-level attestation
  — v1 uses option (c), blanket EEA-region exclusion from Google pushes; (a)/(b) are future
  enhancements, noted in Phase 3's backlog section.

Hard safety constraints (non-negotiable, per phase):
- ZERO edits to any existing CRM file (`crm_connection.py`, `routers/crm.py`, `services/crm.py`,
  `services/crm/*`, `crm_push.py`, `crm_rate_limiter.py`, `tasks/crm_tasks.py`). Import only.
- ZERO edits to `csv_exporter.py` — `_sha256` and `_get_segment_visitors` are imported, never
  copy-modified or monkeypatched.
- `ad_audiences_enabled` feature flag defaults OFF in every commit; flipping it in a real
  environment is a deliberate, separate, out-of-program operator action (matches
  `agent_detection_enabled` precedent).
- No push may ever leave Beam with plaintext PII — SHA256-hash-only egress is enforced at the
  payload-builder level, not just by convention (AC5 is a hard automated gate, not advisory).
- No live Meta/Google network call is permitted in Phase 1 — Phase 1 must be fully mock-mode
  provable per `MOCK_EXTERNAL_APIS=true` before Phase 2/3 begin any live-provider wiring.
- No auto-send/auto-sync: every push remains a human-initiated click (SPEC out-of-scope item).
- Commit each phase's execution changes before starting the next phase. Keep process/plan/
  context commits separate from execution commits.
```

---

## Stable Program Goal (copy-paste this to start autonomous execution)

```
SESSION GOAL: ads-audiences — Ad Audiences Program
Ref: process/features/ads-audiences/active/ad-audiences_25-07-26/ad-audiences-umbrella_PLAN_25-07-26.md

TARGET: Complete ALL phases until:
- All 13 SPEC ACs are provable at their declared strategy (Fully-Automated / Hybrid / Agent-Probe)
- All 5 core validator commands exit 0 after each phase touching harness artifacts
- Test tiers: automated (iterate-until-green) / hybrid (fix-if-in-blast-radius, else Hybrid
  smoke recorded) / agent-probe (record-judgment, e.g. AC13 error-shape probe)

AUTONOMY: Before ANY subagent spawn, read:
1. Umbrella ## Current Execution State → loop step + validate-contract status
2. Phase plan ## Phase Loop Progress → first unchecked box = next subagent to spawn

PER-PHASE LOOP (7-step inner loop `R → I → P → PVL → E → EVL → UP`, never skip, never reorder; SKIPS SPEC — SPEC already locked at program level):
  1. RESEARCH → 2. INNOVATE → 3. PLAN-SUPPLEMENT → 4. PVL → 5. EXECUTE → 6. EVL → 7. UPDATE-PROCESS
- PLAN-SUPPLEMENT: plan-agent writes research/innovate gaps into phase plan (or marks "n/a — clean")
- PVL NEVER skipped; contract must follow example-validate-output.md full format;
  partial contract (missing Plan updates applied / Execute-agent instructions / Test gates) =
  blocked same as placeholder
- Every subagent FIRST ACTION: run vc-context-discovery (load context group files +
  process/context/tests/all-tests.md routing chain) AND vc-plan-discovery (same-feature full
  depth active/backlog/completed/reports/refs + other features active-only + general-plans active)
- Every phase-END: invoke vc-agent-strategy-compare for next step strategy recommendation

Report via phase reports. No approval between phases unless hard stop hit.

HARD STOPS (pause, wait for user):
- Any edit inside a CRM/csv_exporter file (see Hard safety constraints) — refuse and report
- `ad_audiences_enabled` being flipped to True in any non-test config
- Net gate = BLOCKED with no backlog resolution path
- Meta ToS-acceptance error shape / Google Data Manager API contract remains ambiguous after
  docs-fetch AND requires a live-provider billed call to resolve (needs-live-provider gate —
  double opt-in required, never auto-granted)
- Validate-contract is placeholder and vc-validate-agent cannot run

SAFETY (never override):
- Every outbound push payload must be hash-only (AC5) — verify with the automated unit test
  before any live Phase 2/3 call is made
- EEA-region visitors excluded from Google pushes (decision c) — implemented + tested before
  Phase 3 can reach VERIFIED
- Commit each phase before advancing; process and execution commits separate

TEST GATES (every phase exit):
  node .claude/skills/vc-audit-vc/scripts/validate-agent-parity.mjs
  node .claude/skills/vc-audit-vc/scripts/validate-skills.mjs
  node .claude/skills/vc-audit-context/scripts/validate-context-discovery.mjs
  node .claude/skills/vc-audit-plans/scripts/validate-plan-inventory.mjs
  node .claude/skills/vc-audit-vc/scripts/validate-guide-sync.mjs

VALIDATE CONTRACT: Per-phase contracts written by vc-validate-agent into each phase plan before EXECUTE.

START: Phase 1 (Foundation), loop step RESEARCH (pending). Spawn vc-research-agent for Phase 1.
```

---

## Phase Sequence (Phased Delivery Plan)

| Phase | Plan file | Scope summary | Depends on |
|---|---|---|---|
| 0 (pre-program) | this file | Confirm folder structure, baseline audit, create sub-phase plans | — |
| 1 — Foundation | `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-1-foundation_PLAN_25-07-26.md` | `AdConnection` + `ad_audience_links` models, migrations, `services/ads/` skeleton (all 3 providers registered, meta/google stubbed-mock, linkedin `ready:false`), `ads_push.py`, `ads_rate_limiter.py`, `tasks/ads_tasks.py`, `routers/ads.py`, config env trios + flag, schemas, frontend `AdConnectPanel` + CSV-block move, `api.ts` client. Covers ACs 1,4,5,9,10,11,12 in mock mode. | Phase 0 |
| 2 — Meta live | `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-2-meta-live_PLAN_25-07-26.md` | Real Meta OAuth (Limited Access tier), Custom Audience create + member upload, Celery async leg, ToS-precondition error surfacing, min-size warning wiring. Covers ACs 2,6,7,13. | Phase 1 |
| 3 — Google live | `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-3-google-live_PLAN_25-07-26.md` | Real Google OAuth (datamanager+adwords scopes), Data Manager API docs-fetch + audience create/upload, EEA-region exclusion + test, sandbox test-account dev path. Covers AC3. | Phase 1 |

### Join Conditions

- Phase 1 MUST NOT start until Phase 0 exit gate passes (this umbrella + all 3 phase plans + registry created and validators clean).
- Phase 2 MUST NOT start until Phase 1 exit gate passes (all Phase 1 ACs provable in mock mode, `services/ads/` registry + factory pattern stable).
- Phase 3 MUST NOT start until Phase 1 exit gate passes. Phase 3 does NOT depend on Phase 2 — Meta and Google live work are independent once the Phase 1 foundation is stable, and may run in either order or in parallel (see Blast-Radius Registry for disjointness proof).

---

## Per-Phase Entry / Exit Gates

| Phase | Entry | Exit gate |
|---|---|---|
| 0 | Program start | Phase plan files + registry created; validators exit 0 |
| 1 | Phase 0 complete | ACs 1,4,5,9,10,11,12 pass at Fully-Automated tier with `ad_audiences_enabled=true`, `MOCK_EXTERNAL_APIS=true`; AC10 flag-OFF baseline also passes; zero diffs in any CRM/csv_exporter file |
| 2 | Phase 1 exit met | ACs 2,6,7 pass at Fully-Automated (mocked callback) tier + Hybrid sandbox smoke recorded; AC13 Agent-Probe judgment recorded with real-or-best-effort error shape |
| 3 | Phase 1 exit met | AC3 passes at Fully-Automated (mocked callback) tier + Hybrid sandbox-account smoke recorded; EEA-exclusion test passes; Data Manager API contract confirmed via docs-fetch (or feasibility-probe escalation resolved) |

---

## Per-Phase Loop

Each phase executes the canonical 7-step inner loop `R → I → P → PVL → E → EVL → UP`. This inner
loop SKIPS SPEC — SPEC is already locked at the program level (`ad-audiences_SPEC_25-07-26.md`).
The 7 steps map to:

1. **RESEARCH** — spawn research-agent: load context, read prior phase reports, check plan drift (especially: has `alembic heads` moved since this plan was written; has the pii-at-rest plan touched `IdentifiedVisitor.email` read path), document findings
2. **INNOVATE** — spawn innovate-agent: decide approach for any remaining open sub-question (e.g. Phase 3's Data Manager API docs-fetch outcome); write Decision Summary
3. **PLAN-SUPPLEMENT** — spawn plan-agent: if research/innovate found gaps not in the checklist, add them; otherwise mark "n/a — research clean" and tick step 3
4. **PVL** — spawn vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md` format
5. **EXECUTE** — spawn vc-execute-agent per approved plan and validate-contract
6. **EVL** — spawn vc-tester: run phase test gates to green; register follow-up stubs; write EVL HANDOFF SUMMARY
7. **UPDATE-PROCESS** — write phase report to durable report path (flat in this task folder), rewrite this umbrella's `## Current Execution State` section (overwrite, not append)

**PVL is NEVER skipped.** A placeholder `## Validate Contract` = blocked. Do not spawn execute-agent while the Validate Contract section reads "(placeholder — vc-validate-agent writes this section before EXECUTE)".

**Phase 3 research-step special case:** Phase 3's Step 1 RESEARCH must include the Data Manager API docs-fetch named in SPEC Open Question 1/3. If docs are ambiguous after a genuine fetch attempt, escalate via `VC-FEASIBILITY-PROBE-NEEDED: [Data Manager API endpoint contract] — cost-class: docs-fetch` (escalating to `needs-live-provider` only if docs-fetch is truly inconclusive, per orchestration.md §VC-FEASIBILITY-PROBE-NEEDED Signal Routing).

---

## Autonomous Execution Rules (During /goal)

During /goal execution of this phase program:
- Agent self-decides at all V5 gates — no user approval needed between phases, EXCEPT the hard
  stops listed in the Stable Program Goal block above (any CRM/csv_exporter file edit; flag
  flip to True outside test config; needs-live-provider gate).
- CONDITIONAL net gate: proceed autonomously, fixes applied in-flight, gaps on record.
- BLOCKED net gate: document items in backlog, continue with remaining phase plans; backlog is
  always a valid resolution — always find a path forward. Exception: a BLOCKED caused by an
  attempted CRM/csv_exporter edit is a hard stop, not an auto-continue.
- Agent writes phase reports, updates phase plans, creates new sub-plans as needed — all
  autonomously.
- The phase report is the communication channel for conflicts, errors, and learnings — not
  inline questions.

---

## Global Constraints

- ZERO edits to any CRM file or `csv_exporter.py` — import only, verbatim reuse (see Hard
  safety constraints above). This is the single most load-bearing constraint of the program;
  every phase's Verification Evidence includes a `git diff --stat` check proving these files
  are untouched.
- `ad_audiences_enabled` flag defaults OFF in every commit across all 3 phases.
- Every new external call (Meta, Google) has a deterministic mock path gated by
  `MOCK_EXTERNAL_APIS=true`, matching every other external integration in the codebase — no
  phase may introduce a live-only code path.
- Cross-plan risk (non-blocking, monitor only): the active `pii-at-rest_22-07-26` general plan
  (`process/general-plans/active/`) may change how `IdentifiedVisitor.email` is read.
  `ads_push.py` reads plaintext email for hashing exactly like `csv_exporter._get_segment_visitors`
  does today — if pii-at-rest lands first, re-verify the read path still returns a hashable
  string before Phase 1 EVL closes. Each phase's RESEARCH step must check this plan's status.
- After every phase that touches agent/harness files, run the 5 core validators and confirm
  they exit 0 before declaring the phase DONE.
- Commit each phase's execution changes before starting the next phase. Keep process/plan/
  context commits separate from execution commits.

---

## Durable Report Destinations

| Phase | Report path (flat inside this task folder) |
|---|---|
| 0 (pre-program) | `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-0-planning_REPORT_25-07-26.md` |
| 1 — Foundation | `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-1-foundation_REPORT_{dd-mm-yy}.md` |
| 2 — Meta live | `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-2-meta-live_REPORT_{dd-mm-yy}.md` |
| 3 — Google live | `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-3-google-live_REPORT_{dd-mm-yy}.md` |

---

## Program Status Table

| Phase | Status |
|---|---|
| 0 — Pre-program (plan creation) | 🔨 CODE DONE (this write) |
| 1 — Foundation | ✅ VERIFIED (2 env-only known-gaps: G1 migration round-trip, G2 Playwright auth harness — see backlog) |
| 2 — Meta live | 🧪 TESTING (code-complete, EVL-green; 3 env-only known-gaps: E3 sandbox smoke, AC7 Playwright legs, AC13 error shape — see backlog) |
| 3 — Google live | ⏳ PLANNED |

Status values: ⏳ PLANNED | 🔨 CODE DONE | 🧪 TESTING | ✅ VERIFIED | 🚧 BLOCKED | ✅ COMPLETE

---

## Touchpoints

- `apps/api/models/ad_connection.py` (new), `apps/api/models/ad_audience_link.py` (new)
- `apps/api/migrations/versions/*_add_ad_connections.py`, `*_add_ad_audience_links.py` (new)
- `apps/api/services/ads/` (new: `base.py`, `factory.py`/registry, `meta.py`, `google.py`, `linkedin.py`)
- `apps/api/services/ads_push.py`, `apps/api/services/ads_rate_limiter.py` (new)
- `apps/api/tasks/ads_tasks.py` (new)
- `apps/api/routers/ads.py` (new)
- `apps/api/schemas/ads.py` (new)
- `apps/api/config.py` (append-only: new settings fields, never edit existing CRM fields)
- `apps/web/src/components/ad-connect-panel.tsx` (new)
- `apps/web/src/app/dashboard/connectors/page.tsx` (edit: mount `AdConnectPanel` inside the
  already-renamed "Ad Audiences" tab below the CSV block; tab labels are already correct —
  pre-program rename shipped separately today)
- `apps/web/src/lib/api.ts` (append-only: new ad-connection client methods)

Read-only imports (never edited): `apps/api/services/csv_exporter.py` (`_sha256`,
`_get_segment_visitors`), `apps/api/services/encryption.py`, `apps/api/services/oauth_state.py`.

---

## Public Contracts

- Existing CRM API surface (`/api/v1/crm/*`) unchanged — zero new routes added there, zero
  existing routes modified.
- Existing CSV export routes/behavior for Meta/Google/LinkedIn unchanged regardless of ad-audience
  connection state (SPEC constraint).
- New public surface: `/api/v1/ads/{site_id}/connections` (list), `/api/v1/ads/{site_id}/connections/{provider}/connect` (POST), `/api/v1/ads/callback/{provider}` (GET), `/api/v1/ads/{site_id}/connections/{provider}/test` (POST), `/api/v1/ads/{site_id}/connections/{provider}/push` (POST), `/api/v1/ads/{site_id}/connections/{provider}` (DELETE) — mirrors the shape of `apps/api/routers/crm.py` 1:1, new file, new prefix.
- New feature flag `ad_audiences_enabled: bool = False` in `apps/api/config.py`.

---

## Blast Radius

Files directly modified or created across all 3 phases (see each phase plan + the blast-radius
registry for the exact per-phase split):

- ~14 new backend files (models, migrations, services/ads/*, router, schemas, tasks, rate limiter)
- 1 new frontend component + 2 edited frontend files (connectors page mount point, api.ts client)
- 1 edited config file (append-only)
- Zero edits to any CRM or csv_exporter file (hard constraint, verified every phase)
- Risk class: **auth/identity** (OAuth token storage) + **external API contract** (new outbound
  Meta/Google integrations) — both High-Risk Classes per `orchestration.md`; every phase's
  validate-contract must include at least a Hybrid-tier gate for its live-provider surface.

---

## Verification Evidence

```bash
# Prove zero CRM/csv_exporter file drift across the whole program
git diff --stat main -- apps/api/models/crm_connection.py apps/api/routers/crm.py \
  apps/api/services/crm.py apps/api/services/crm/ apps/api/services/crm_push.py \
  apps/api/services/crm_rate_limiter.py apps/api/tasks/crm_tasks.py apps/api/services/csv_exporter.py
# Expected: empty output (no changes) at every phase boundary

# Core validator suite (run after every phase touching harness artifacts)
node .claude/skills/vc-audit-vc/scripts/validate-agent-parity.mjs
node .claude/skills/vc-audit-vc/scripts/validate-skills.mjs
node .claude/skills/vc-audit-context/scripts/validate-context-discovery.mjs
node .claude/skills/vc-audit-plans/scripts/validate-plan-inventory.mjs
node .claude/skills/vc-audit-vc/scripts/validate-guide-sync.mjs
# Expected: all exit 0
```

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/ads-audiences/active/ad-audiences_25-07-26/ad-audiences-umbrella_PLAN_25-07-26.md`
- Last completed phase: Phase 0 (this umbrella plan file + 3 phase plans + registry = Phase 0 artifact)
- Validate-contract status: pending (vc-validate-agent writes per-phase)
- Supporting context files loaded: `process/context/all-context.md`, `process/context/planning/all-planning.md`, `process/features/ads-audiences/active/ad-audiences_25-07-26/ad-audiences_SPEC_25-07-26.md`, `process/context/tests/all-tests.md`
- Next step for a fresh agent: Read this umbrella plan, read the Phase 1 plan, then run Phase 1 RESEARCH subagent before any EXECUTE work.
- Current phase: Phase 1 — Foundation
- Next action: Spawn vc-research-agent for Phase 1 (Step 1 of the 7-step inner loop)
- Execute-agent start instruction: Read this file. Read Phase 1 plan. Run research subagent first.

---

## Current Execution State

Last updated: 26-07-26
Current phase: 3 of 3 (Phase 3 — Google Live)
Phase 3 name: Google Live
Phase 2 status: 🧪 TESTING (code-complete, EVL-green) — NOT ✅ VERIFIED. Inner-PVL Gate: PASS
  (cycle 4, `generated-by: inner-pvl: phase-2`). 3 env-only known-gaps: E3 Hybrid Meta sandbox
  smoke (no real Meta developer app/Business Manager in this environment), AC7 Playwright UI legs
  (Clerk auth harness gap G2, pre-existing), AC13 exact error code/subcode (Agent-Probe residual,
  fails safe). All 3 have resolution paths; none block Phase 3 start. (Note: the Phase 2 EVL
  handoff also flagged T1 conftest fix as "not yet landed on main" — independently re-verified
  26-07-26 as STALE: T1 is already fixed and committed, `c88444a`. See backlog note's correction.)
  See backlog
  note `process/features/ads-audiences/backlog/phase-1-docker-and-auth-known-gaps_NOTE_25-07-26.md`
  (extended with a Phase 2 section).
Phase 2 EVL: green — 14 gates: unit 539 full regression + 48 ads-scope, guardrail agent-origin
  18/18, 5/5 integration files (fresh-schema), frontend typecheck clean, frozen-ads-file drift
  clean, no-raw-token-logging grep clean, no-live-Meta-calls grep clean, alembic single head
  `d5b1f7c3a908` (`results.tsv` iteration 5, HALTED_SUCCESS). No regression against Phase 1 surfaces.
Phase 2 report: `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-2-meta-live_REPORT_26-07-26.md`
Phase 1 status: ✅ VERIFIED — Gate: PASS (cycle 2); 2 named env-only known-gaps (G1 migration
  round-trip, G2 Playwright auth harness), unchanged this phase.
Note: alembic head has moved twice since Phase 1 closeout, both by concurrent programs, not this
  program — currently `d5b1f7c3a908` (single head, re-verified live 26-07-26 via `alembic heads`).
  Phase 3's RESEARCH step must re-confirm the head again before any migration work, per the
  umbrella's Global Constraints check.
Next phase: Phase 3 — Google Live, inner-loop Step 1 RESEARCH (pending — not yet spawned). Read
  Phase 3 plan (`phase-3-google-live_PLAN_25-07-26.md`) and this umbrella before spawning
  vc-research-agent. Phase 3 does not depend on Phase 2 (see Join Conditions) — its Phase 1
  dependency is already satisfied.

Program Net Gate: IN PROGRESS (1 of 3 phases VERIFIED; Phase 2 code-complete/EVL-green pending
  Hybrid+UI evidence; Phase 3 not started)
Latest validator run: 26-07-26 — see this UPDATE PROCESS session's Tier-1 audit results

Loop step values: RESEARCH | INNOVATE | PLAN-SUPPLEMENT | PVL | EXECUTE | EVL | UPDATE-PROCESS
Orchestrator rule: read this section plus the current phase plan's "## Phase Loop Progress"
checkboxes before spawning any subagent. Never spawn execute-agent when the phase's PVL step is
unchecked or its Validate Contract section is a placeholder.

Note: The Stable Program Goal above is fixed. This section is the only part that changes —
update-process-agent rewrites it after every phase closeout (overwrite, not append — git
history is the audit log).

---

## Test Infra Improvement Notes

(none identified yet)

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
