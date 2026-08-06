---
name: plan:identity-program-umbrella
description: "Identity honesty program — umbrella plan for Phase 0 (candidate-tier confidence gating) + Phase H (named-traffic factory via contact import)"
date: 03-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
  phase: umbrella
---

# Identity Honesty Program — Umbrella Plan

**Date:** 03-08-26
**Complexity:** COMPLEX
**Status:** ⏳ PLANNED

- Program type: PHASE PROGRAM (6 phases, mixed sequential/parallel-safe)
- SPEC: `process/features/visitors-identity/active/identity-program_03-08-26/identity-program_SPEC_03-08-26.md` (locked, 18 ACs)
- Feature folder: `process/features/visitors-identity/`

---

## Program Goal Charter

```
Identity Honesty Program — Program Goal Charter

North star:
- Beam never asserts a name it is not sure of, and gives customers a second, more reliable way
  to get named visitors by importing contacts they already own.

Definition of done (an unattended agent must be able to do all of these):
1. Every graph-sourced match (RB2B/Leadpipe/Capturify), at any confidence score, lands on
   identity_status="candidate" — never "identified" — and is visibly badged as unconfirmed with
   its confidence value, on both list and detail pages.
2. Candidate-tier identities are still emailable/exportable, but every send composed for a
   Candidate uses generic copy — no guessed name/title/company merge field anywhere in
   subject or body — enforced at send time, not just draft time.
3. A customer can reject a wrong Candidate (returns to anonymous, re-resolvable) or confirm a
   correct one (promotes to identified/verified; only sends after promotion are personalized).
4. Gmail-Connect sends decorate links and pass custom_args identically to SendGrid sends.
5. A customer can upload a CSV of up to 5,000 owned contacts/site; each becomes a phantom
   visitor with a working tokenized link; clicking that link makes the contact a named,
   verified visitor visible on the dashboard within 5 minutes, via a batch sweep — never
   synchronously inside /ingest.
6. A dashboard view shows "N of your M contacts active this week" without manual cross-referencing.
7. All 18 SPEC acceptance criteria have a named proving test at Fully-Automated, Hybrid, or
   Agent-Probe tier.

What "verified" means (program level):
- Every phase's validate-contract gates are recorded alongside phase test-gate + regression
  evidence before that phase is marked VERIFIED. A phase without a validate-contract (or a
  documented skip reason) cannot be VERIFIED.
- Program-level VERIFIED requires all 6 phases individually VERIFIED, the ~8 identity_status
  call-site reconciliation table fully resolved (SPEC AC8), and zero regressions in
  test_identity_classification.py / test_agent_origin_exclusion.py / test_outbound_identity_gate.py.

Scope tiers → phase mapping:
- Tier 1 (Candidate tier + reconciliation) → Phase 1
- Tier 2 (Send-time personalization gating) → Phase 2
- Tier 3 (Channel parity) → Phase 3
- Tier 4 (Named-traffic factory: import) → Phase 4
- Tier 5 (Click→verified promotion) → Phase 5
- Tier 6 (Hot-contacts dashboard) → Phase 6
- This program retires the "flat Identified, no confidence signal" tier entirely.

Explicitly out of scope (deferred tier):
- Phase F (AI-timed self-identification widget) and Phase E (agent-ready site config) — later phases.
- Third-party/purchased contact lists, LinkedIn-sourced enrichment, Meta Ads audience matching as
  an identity oracle, general-purpose CRM sync import, tiered/plan-based import quotas, changing
  SendGrid-vs-Gmail routing/selection logic.

Hard safety constraints (non-negotiable, per phase):
- No auto-send: outreach to any Candidate or imported contact still requires the existing
  human draft → approve → send gate.
- Every send (Candidate or imported-contact) MUST route through the existing guardrail chain
  (suppression list, do_not_email, 50/hour/site cap via email_rate_limiter, unsubscribe
  footer) — no bespoke/parallel sender may be built.
- is_emailable_identity() keeps exactly 3 parameters, unchanged, for the life of this program.
- No graph-sourced match may ever auto-promote to "identified" via a score threshold — only
  deterministic paths (form capture, _bid click, explicit human confirmation) verify.
- Contact import is capped at 5,000/site, hard-rejected (not truncated) above the cap.
- Click→verified resolution must complete within 5 minutes of click but MUST NOT run
  synchronously inside the /ingest request path.
- Every imported contact and every candidate-tier identity remains scoped to
  Site.user_id == user.id — no cross-tenant visibility.
- Commit each phase's execution changes before starting the next phase. Keep process/plan/
  context commits separate from execution commits.
```

---

## Stable Program Goal (copy-paste this to start autonomous execution)

```
SESSION GOAL: visitors-identity — Identity Honesty Program (Phase 0 + Phase H)
Ref: process/features/visitors-identity/active/identity-program_03-08-26/identity-program-umbrella_PLAN_03-08-26.md

TARGET: Complete ALL 6 phases until:
- All 18 SPEC ACs have a green proving gate (Fully-Automated/Hybrid iterate-to-green; Agent-Probe recorded)
- No regression in test_identity_classification.py / test_agent_origin_exclusion.py / test_outbound_identity_gate.py
- Candidate never auto-promotes; is_emailable_identity keeps 3 params; no sync resolve in /ingest

AUTONOMY: Before ANY subagent spawn, read:
1. Umbrella ## Current Execution State → loop step + validate-contract status
2. Phase plan ## Phase Loop Progress → first unchecked box = next subagent to spawn

PER-PHASE LOOP (7-step inner loop R -> I -> P -> PVL -> E -> EVL -> UP, never skip, never
reorder; SKIPS SPEC — the outer program SPEC already governs every phase):
  1. RESEARCH -> 2. INNOVATE -> 3. PLAN-SUPPLEMENT -> 4. PVL -> 5. EXECUTE -> 6. EVL -> 7. UPDATE-PROCESS
- PLAN-SUPPLEMENT: plan-agent writes research/innovate gaps into phase plan (or "n/a — clean")
- PVL NEVER skipped; contract follows example-validate-output.md full format; partial contract
  (missing Plan updates applied / Execute-agent instructions / Test gates) = blocked as placeholder
- Every subagent FIRST ACTION: vc-context-discovery + vc-plan-discovery
- Every phase-END: invoke vc-agent-strategy-compare for next-step strategy

Report via phase reports. No approval between phases unless a hard stop is hit.

HARD STOPS (pause, wait for user):
- Irreversible/outward-facing action without explicit validate-contract instruction
- Net gate = BLOCKED with no backlog resolution path
- Cascade BLOCKED: two consecutive phases both BLOCKED-skipped
- Alembic migration touching production data (Phase 4's is_imported_contact column) — offline
  --sql validate only; live apply is a separate explicit operator action

SAFETY (never override):
- Never let a graph match auto-promote to identified via score
- Never build a parallel/bespoke email sender — reuse campaign_sender.py's guardrail chain
- Never run resolve synchronously inside /ingest
- Commit each phase before advancing; process and execution commits separate

TEST GATES (every phase exit):
  .venv/bin/python3.11 -m pytest tests/unit -k "identity or candidate or emailable or campaign_sender or import or promotion" -q
  .venv/bin/python3.11 -m pytest tests/integration -k "identity or import or promotion" -q
  node .claude/skills/vc-audit-vc/scripts/validate-agent-parity.mjs
  node .claude/skills/vc-generate-phase-program/scripts/validate-phase-stub.mjs <phase-plan.md>

VALIDATE CONTRACT: Per-phase contracts written by vc-validate-agent into each phase plan before EXECUTE.

START: Phase 1, loop step RESEARCH (pending). Spawn vc-research-agent for Phase 1.
```

---

## Phase Sequence

| Phase | Plan file | Scope summary | Depends on |
|---|---|---|---|
| 1 — Candidate tier | `phase-1-candidate-tier_PLAN_03-08-26.md` | New `identity_status="candidate"` for all graph matches; `is_verified_identity()` helper; 8-call-site reconciliation; reject/confirm paths; confidence surfacing to frontend; rb2b.py parsing unit tests | — (no deps) |
| 2 — Personalization gate | `phase-2-personalization-gate_PLAN_03-08-26.md` | Send-time hard guard in campaign_sender.py before `_personalize()`; fail-loud; draft-time generic wording; mid-campaign promotion cutover | Phase 1 |
| 3 — Gmail parity | `phase-3-gmail-parity_PLAN_03-08-26.md` | Shared compose step so `decorate_links`/`custom_args` run once upstream of the SendGrid/Gmail fork | — (parallel-safe with 1, 2) |
| 4 — Contact import | `phase-4-contact-import_PLAN_03-08-26.md` | CSV import endpoint + UI; phantom Visitor rows; 5,000/site cap; merge-on-click design | — (parallel-safe with 1, 2, 3) |
| 5 — Promotion sweep | `phase-5-promotion-sweep_PLAN_03-08-26.md` | APScheduler sweep (1-2 min) promoting fresh `utm`-source VisitorEmail rows to verified via existing resolver | Phase 4 |
| 6 — Hot-contacts dashboard | `phase-6-hot-contacts-dashboard_PLAN_03-08-26.md` | "N of your M contacts active this week" dashboard view powered by existing rollups | Phases 4 + 5 |

### Join Conditions

- Phase 2 MUST NOT start until Phase 1 exit gate passes (needs `is_verified_identity()` + candidate status to exist).
- Phase 5 MUST NOT start until Phase 4 exit gate passes (needs phantom Visitor + import quota to exist).
- Phase 5 benefits from Phase 3 being live (Gmail-sent links also decorated) but is not blocked by it.
- Phase 6 MUST NOT start until Phases 4 AND 5 exit gates both pass (needs imported contacts + promotion data to summarize).
- Phase 3 is parallel-safe with Phases 1 and 2 (touches a disjoint region of `campaign_sender.py` — see Blast Radius below).

---

## Per-Phase Entry / Exit Gates

| Phase | Entry | Exit gate |
|---|---|---|
| 1 | Program start | `is_verified_identity()` exists and is used at all reconciled call sites; all 3 providers land on "candidate" at any score; rb2b.py has unit coverage; confidence_score reaches frontend type + badge renders |
| 2 | Phase 1 exit met | No Candidate-tier send ever contains a graph-sourced name/title/company merge field; guard fails loud if a candidate reaches the personalized branch; mid-campaign promotion cutover proven per-send |
| 3 | Program start (parallel with 1/2) | Gmail-Connect send decorates links and passes custom_args identically to SendGrid path |
| 4 | Program start (parallel with 1/2/3) | CSV import creates phantom Visitor rows up to 5,000/site hard cap; merge-on-click reconciles phantom + real visitor onto one visitor_id; cross-tenant isolation proven |
| 5 | Phase 4 exit met | Tokenized-link click promotes the contact to verified within ≤5 min via batch sweep, never synchronous in /ingest |
| 6 | Phases 4+5 exit met | Dashboard shows accurate "N of M active" count backed by a tested query |

---

## Per-Phase Loop

Each phase executes the canonical 7-step inner loop `R -> I -> P -> PVL -> E -> EVL -> UP`. This
inner loop SKIPS SPEC — the outer program SPEC (locked, 18 ACs) already governs every phase.

1. **RESEARCH** — spawn research-agent: load context, read prior phase reports, check plan drift, document findings
2. **INNOVATE** — spawn innovate-agent: decide approach; write Decision Summary (chosen approach + rejected alternatives) — most forks are already decided by the program-level INNOVATE Decision Summary; phase INNOVATE should mostly confirm/refine, not re-litigate
3. **PLAN-SUPPLEMENT** — spawn plan-agent: if research/innovate found gaps/pre-conditions not in checklist, add them; otherwise mark "n/a — research clean" and tick step 3
4. **PVL** — spawn vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md` format
5. **EXECUTE** — spawn vc-execute-agent per approved plan and validate-contract
6. **EVL** — spawn vc-tester: run phase test gates to green; register follow-up stubs; write EVL HANDOFF SUMMARY
7. **UPDATE-PROCESS** — write phase report to durable report path (flat in this task folder), rewrite this umbrella's `## Current Execution State` section (overwrite, not append)

**PVL is NEVER skipped.** A placeholder `## Validate Contract` = blocked. Do not spawn execute-agent while a phase's Validate Contract section reads "(placeholder — vc-validate-agent writes this section before EXECUTE)".

---

## Autonomous Execution Rules (During /goal)

- Agent self-decides at all V5 gates — no user approval needed between phases.
- CONDITIONAL net gate: proceed autonomously, fixes applied in-flight, gaps on record.
- BLOCKED net gate: document items in backlog, continue with remaining phase plans; backlog is always a valid resolution path.
- Hard stops (must pause for user approval): irreversible/outward-facing action without explicit contract instruction (production DB migration apply, deploy, push to remote); cascade BLOCKED (two consecutive phases BLOCKED-skipped).
- Agent writes phase reports, updates phase plans, creates new sub-plans as needed — all autonomously.
- The phase report is the communication channel for conflicts, errors, and learnings — not inline questions.

---

## Global Constraints

- Never widen `is_emailable_identity()`'s parameter count — the tier gate lives in the send/draft composition layer, never in that function.
- Never let a `candidate`-tier row auto-promote based on score, ever — only deterministic paths.
- Never build a bespoke/parallel email sender for imported contacts — reuse `campaign_sender.py`'s guardrail chain exactly.
- Never run identity resolution synchronously inside the `/ingest` hot path.
- Migration for Phase 4's `is_imported_contact` column: re-verify current alembic head via `alembic -c apps/api/alembic.ini heads` at EXECUTE time (program docs note frequent concurrent-program head drift) before writing `down_revision`.
- After every phase that touches agent/skill/harness files, run the parity validator and confirm exit 0 before declaring the phase DONE.
- Commit each phase's execution changes before starting the next phase. Keep process/plan/context commits separate from execution commits.

---

## Durable Report Destinations

| Phase | Report path (inside this task folder) |
|---|---|
| 1 — Candidate tier | `process/features/visitors-identity/active/identity-program_03-08-26/phase-1-candidate-tier_REPORT_03-08-26.md` |
| 2 — Personalization gate | `process/features/visitors-identity/active/identity-program_03-08-26/phase-2-personalization-gate_REPORT_03-08-26.md` |
| 3 — Gmail parity | `process/features/visitors-identity/active/identity-program_03-08-26/phase-3-gmail-parity_REPORT_03-08-26.md` |
| 4 — Contact import | `process/features/visitors-identity/active/identity-program_03-08-26/phase-4-contact-import_REPORT_03-08-26.md` |
| 5 — Promotion sweep | `process/features/visitors-identity/active/identity-program_03-08-26/phase-5-promotion-sweep_REPORT_03-08-26.md` |
| 6 — Hot-contacts dashboard | `process/features/visitors-identity/active/identity-program_03-08-26/phase-6-hot-contacts-dashboard_REPORT_03-08-26.md` |

---

## Program Status Table

| Phase | Status | Outer-PVL gate (2026-08-03, generated-by: outer-pvl) |
|---|---|---|
| 1 — Candidate tier | ⏳ PLANNED | CONDITIONAL |
| 2 — Personalization gate | ⏳ PLANNED | PASS (inherits Phase 1's laundering-path fixes — no separate change needed; Phase 2's E5 instruction covers re-confirmation) |
| 3 — Gmail parity | ⏳ PLANNED | PASS |
| 4 — Contact import | ⏳ PLANNED | CONDITIONAL |
| 5 — Promotion sweep | ⏳ PLANNED | CONDITIONAL |
| 6 — Hot-contacts dashboard | ⏳ PLANNED | CONDITIONAL |

Status values: ⏳ PLANNED | 🔨 CODE DONE | 🧪 TESTING | ✅ VERIFIED | 🚧 BLOCKED | ✅ COMPLETE

**Live alembic head drift (Phase 4 validator finding, 2026-08-03):** the true current alembic head
is `a7d419e6c052`, NOT `e6b2d4a1c837` as recorded elsewhere in program docs — re-verify via
`.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` at every EXECUTE, since concurrent
programs have repeatedly advanced the head further.

---

## Touchpoints

- `apps/api/services/identity_providers/rb2b.py`, `leadpipe.py`, `capturify.py`
- `apps/api/services/identity_resolver.py` (`_save_identified`, `_resolve_identity_graphs_parallel`)
- `apps/api/services/identity_classification.py` (`identity_level`, `is_emailable_identity`, new `is_verified_identity`)
- `apps/api/models/visitor.py` (includes `IdentifiedVisitor` — there is no separate `identified_visitor.py` file)
- `apps/api/routers/visitors.py` (manual identify, residential-IP short-circuit, revive bulk SQL, reject/confirm endpoints)
- `apps/api/services/resolution_runner.py`, `apps/api/services/visitor_aggregator.py`
- `apps/api/routers/kpi.py`, `apps/api/routers/timeseries.py`, `apps/api/routers/dashboard.py`, `apps/api/services/visitors_helpers.py`
- `apps/api/services/campaign_sender.py`, `apps/api/services/email_sender.py`, `apps/api/services/email_providers/gmail_sender.py`
- `apps/api/schemas/visitors.py`, `apps/web/src/lib/api-types.ts`
- `apps/web/src/app/dashboard/visitors/page.tsx`, `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx`
- New: CSV import router/service, phantom-Visitor creation path, import-quota check, promotion sweep task, hot-contacts dashboard view
- `apps/api/migrations/versions/` — one new additive migration (Phase 4: `is_imported_contact` flag column)

---

## Public Contracts

- `is_emailable_identity(provider, source_agent_visit_id, is_abuse_flagged)` — exactly 3 parameters, unchanged.
- Existing "Identified" dashboard counts/KPIs/filters keep their current meaning; Candidate is additive, never silently folded in or dropped.
- `_bid` tokenized-link mechanism (generate/decode) is reused as-is for imported contacts — no new token scheme.
- Campaign send guardrail chain (suppression, do_not_email, hourly cap, unsubscribe) is the ONLY send path for any new contact source.

---

## Blast Radius

Estimated ~25-30 files across 6 phases; shared-file regions are explicitly partitioned below to keep phase blast radii disjoint:

- **`campaign_sender.py`** shared by Phases 2, 3, 5(adjacent):
  - Phase 2 owns: the tier-check guard immediately before the `_personalize()` calls at ~line 248/250 (send-time personalization gate).
  - Phase 3 owns: the shared compose step upstream of the channel fork (where `decorate_links()`/`custom_args` are currently built once for SendGrid) — extends it to also feed `send_via_gmail()`.
  - Phase 5 does not modify `campaign_sender.py` directly; it only depends on Phase 3's decoration parity being live for imported-contact sends to attribute correctly.
- **`identity_resolver.py`** shared by Phases 1, 4, 5:
  - Phase 1 owns: `_save_identified` (candidate-vs-identified branch), `_resolve_identity_graphs_parallel` (no scoring change, only branch target).
  - Phase 4 owns: the phantom-Visitor lookup/merge-on-click logic invoked from ingest/resolution entry points — a new function, not an edit to Phase 1's owned functions.
  - Phase 5 owns: the promotion-sweep's call into the existing email-based resolution path (read-only reuse, no edits to Phase 1's or Phase 4's owned functions).
- All other touchpoints are single-phase-owned (see each phase plan's own Blast Radius section).

---

## Verification Evidence

```bash
# Full identity/candidate/emailable/import/promotion unit suite
.venv/bin/python3.11 -m pytest tests/unit -k "identity or candidate or emailable or campaign_sender or import or promotion" -q
# Expected: 0 failures

# Integration suite for identity + import + promotion
.venv/bin/python3.11 -m pytest tests/integration -k "identity or import or promotion" -q
# Expected: 0 failures (Docker/Postgres+Redis required — see TESTING.md)

# No regression in the 3 named guardrail test files
.venv/bin/python3.11 -m pytest tests/unit/test_identity_classification.py tests/unit/test_agent_origin_exclusion.py tests/unit/test_outbound_identity_gate.py -q
# Expected: 0 failures

# Harness parity after any agent/skill touch
node .claude/skills/vc-audit-vc/scripts/validate-agent-parity.mjs
# Expected: exit 0
```

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/visitors-identity/active/identity-program_03-08-26/identity-program-umbrella_PLAN_03-08-26.md`
- Last completed phase: none — program not yet started
- Validate-contract status: pending (vc-validate-agent writes per-phase)
- Supporting context files loaded: `process/context/all-context.md`, `process/context/planning/all-planning.md`, `process/features/visitors-identity/active/identity-program_03-08-26/identity-program_SPEC_03-08-26.md`, INNOVATE Decision Summary (scratchpad), research-phase0.md, research-phaseH.md (scratchpad)
- Next step for a fresh agent: Read this umbrella plan, read `phase-1-candidate-tier_PLAN_03-08-26.md`, then run Phase 1's RESEARCH subagent before any EXECUTE work.
- Current phase: Phase 1 (Candidate tier)
- Next action: Spawn vc-research-agent for Phase 1
- Execute-agent start instruction: Do NOT spawn execute-agent for any phase until that phase's `## Validate Contract` section is filled in (not the placeholder).

---

## Current Execution State

Last updated: 03-08-26
Current phase: 1 of 6 (Candidate tier)
Phase 1 status: ⏳ PLANNED
Phase 1 EVL: not started
Phase 1 report: not written
Next phase: Phase 1 RESEARCH (pending)
Current loop step: RESEARCH (pending, not yet spawned)
Validate-contract status: pending (no phase has a written contract yet)

Loop step values: RESEARCH | INNOVATE | PLAN-SUPPLEMENT | PVL | EXECUTE | EVL | UPDATE-PROCESS
Orchestrator rule: read "Current loop step" and "validate-contract status" before spawning any subagent. Never spawn execute-agent when loop step is RESEARCH, INNOVATE, PLAN-SUPPLEMENT, or PVL.

Note: The Stable Program Goal above is fixed. This section is the only part that changes — update-process-agent rewrites it after every phase closeout (overwrite, not append — git history is the audit log).

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
