---
name: plan:engage-learning-agent-umbrella
description: "Engage Learning Agent — umbrella/orchestration plan for the 3-phase program (signal acquisition → memory+privacy → learning+autonomy)"
date: 17-08-26
feature: campaigns-outreach
metadata:
  node_type: memory
  type: plan
  feature: campaigns-outreach
  phase: umbrella
---

# Engage Learning Agent — Umbrella Plan

**Date**: 17-08-26
**Complexity**: COMPLEX
**Status**: ⏳ PLANNED

- Program type: PHASE PROGRAM (**4 phases** — 1, 2, 3a, 3b — sequential with gated joins; restructured 17-08-26 at PVL cycle 4)
- Feature folder: `process/features/campaigns-outreach/`
- Task folder: `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/`
- Locked SPEC: `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/engage-learning-agent_SPEC_17-08-26.md` (AC-1..AC-20)
- Context routers this program reads: `process/context/all-context.md`, `process/context/tests/all-tests.md`

**TL;DR:** Close the Engage feedback loop in three disjoint workstreams — first capture what happens to a posted reply (Phase 1), then remember it privately and legally at three scopes (Phase 2), then let that memory pick better approaches and earn bounded autonomous sending behind hard rails (Phases 3a + 3b). Every flag defaults OFF; every flag-gated behavior needs a flag-ON gate.

---

## Overview

Beam's social Engage agent drafts, a human approves, Beam posts — and then discards the platform
`comment_id` (`apps/api/services/sender.py:212`). That single discarded value blocks nearly all
outcome measurement. This program persists it, measures what the reply achieved, stores those
measurements as memory at three scopes, and uses that measured history — never model
self-assessment — to (a) pick better approaches and (b) authorize autonomous sends above an
evidence-anchored threshold inside hard safety rails.

The program deliberately amends the repo's standing "never build auto-send" guardrail
(`process/context/all-context.md` §What Beam Is and §Business Guardrails item 1). The user approved
that change on 17-08-26; the doc edit is a Phase 3b gated deliverable (AC-20), not an afterthought.

---

## Program Goal Charter

```
Engage Learning Agent — Program Goal Charter

North star:
- The Engage agent measurably improves its own social replies from the observed outcomes of
  those replies, and earns bounded autonomy only where the measured evidence justifies it.

Definition of done (an unattended agent must be able to do all of these):
1. Persist the platform id of every posted reply, and record reply-back, public-metric, and
   attributed-site-visit outcomes against it without any frontend involvement.
2. Store what worked at three scopes — per-contact (erasable PII), per-site/playbook (computed
   from outcomes, not materialized), cross-tenant (own consent flag, k>=5, no deltas, no PII) —
   and surface the per-playbook track record to the site owner.
3. Select reply approaches from measured outcomes, and autonomously send ONLY when a pure
   function of outcome history clears N and R, inside dual kill switches, an hourly ceiling,
   a fail-closed crisis block, suppression enforcement, an audit row, and an undo path.

What "verified" means (program level):
- Every AC assigned to the phase has a named gate that RAN and passed, with flag-ON evidence for
  every flag-gated behavior (flag-OFF-only evidence is vacuous — icp_fit lesson, 17-08-26).
- The phase's migration was live round-tripped (up → down → up) against a LOCAL disposable
  Postgres, never prod.
- validate-contract gates are recorded alongside phase gates and regression evidence. A phase
  without a validate-contract (or a documented skip reason) cannot be marked VERIFIED.

Scope tiers → phase mapping:
- Tier 1 Signal acquisition (AC-1..AC-4) → Phase 1
- Tier 2 Memory + privacy + cross-tenant (AC-5..AC-10) → Phase 2
- Tier 3a Learning (AC-13) → Phase 3a; Tier 3b Autonomy + rails + guardrail text (AC-11, AC-12, AC-14..AC-20) → Phase 3b
- This program retires Tiers 1-3.

Explicitly out of scope (deferred tier):
- Reimplementing or approximating X's ranking algorithm.
- Impressions and profile-visit signals (paid tier / not exposed).
- Meta and TikTok (no sync path exists).
- LinkedIn autonomy — LinkedIn stays draft-approve-only in v1 (OQ-2 resolved: the phantommm
  sidecar exposes only job/campaign rollups, no per-contact outcomes). X is the sole learning
  platform.
- Storing third-party reply bodies (AC-6 forbids it; changing that needs its own SPEC).
- Email reply tracking; auto-adjusting live email campaigns; rebuilding voice_examples.

Hard safety constraints (non-negotiable, per phase):
- No autonomous send capability may become reachable before Phase 3b's rails land in the SAME
  phase: dual kill switch, hourly ceiling, fail-closed crisis block, suppression, audit, undo.
- Never run an alembic command or DB script without pinning DATABASE_URL to localhost:5433 or a
  disposable container DSN. The repo `.env` points at Supabase PRODUCTION and
  `apps/api/migrations/env.py` has NO local-host guard.
- Never hardcode `down_revision`. Re-derive the live head with
  `alembic -c apps/api/alembic.ini heads` at EXECUTE time — concurrent programs move it.
- No new flag ships ON. Every capability flag defaults False; enabling is an operator action.
- Per-contact memory writes flow through exactly one choke point and are registered in
  ERASURE_TARGETS in the same phase they are created.
- Commit each phase's execution changes before starting the next phase. Keep process/plan/context
  commits separate from execution commits.
```

---

## Stable Program Goal

```
SESSION GOAL: campaigns-outreach — Engage Learning Agent (3-phase program)
Ref: process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/engage-learning-agent-umbrella_PLAN_17-08-26.md

TARGET: Complete Phases 1 → 2 → 3a → 3b until:
- All 20 SPEC ACs have a gate that RAN and passed in its assigned phase
- Every flag-gated behavior has flag-ON evidence (flag-OFF-only = vacuous)
- Each phase's migration live round-tripped up→down→up on LOCAL Postgres
- Test tiers: automated (iterate-until-green) / hybrid (fix-if-in-blast-radius) / agent-probe (record-judgment)

AUTONOMY: Before ANY subagent spawn, read:
1. Umbrella ## Current Execution State → loop step + validate-contract status
2. Phase plan ## Phase Loop Progress → first unchecked box = next subagent to spawn

PER-PHASE LOOP (7-step, never skip/reorder; SKIPS SPEC — the umbrella SPEC governs all phases):
  1 RESEARCH → 2 INNOVATE → 3 PLAN-SUPPLEMENT → 4 PVL → 5 EXECUTE → 6 EVL → 7 UPDATE-PROCESS
- PLAN-SUPPLEMENT: plan-agent writes research/innovate gaps into the phase plan (or "n/a — clean")
- PVL NEVER skipped; a partial contract (missing Plan updates applied / Execute-agent
  instructions / Test gates) is blocked the same as a placeholder
- Every subagent FIRST ACTION: vc-context-discovery (context group + tests/all-tests.md routing
  chain) AND vc-plan-discovery (same-feature full depth + other-feature active + general active)
- Every phase-END: invoke vc-agent-strategy-compare for the next step's strategy
Report via phase reports. No approval between phases unless a hard stop is hit.

HARD STOPS (pause, wait for user):
- Any alembic/DB command whose DATABASE_URL is not pinned to localhost:5433 or a disposable DSN
- Any live/billed X API call (OQ-1 metrics tier probe is cost-class needs-live-provider: double opt-in)
- Flipping any engage_* flag ON in a real environment, or any deploy/push to remote
- Net gate = BLOCKED with no backlog resolution path; validate-contract cannot be written

SAFETY (never override):
- No autonomous send path reachable before Phase 3b rails land in the SAME phase
- Never hardcode down_revision; re-derive head at EXECUTE time
- All new flags default OFF; per-contact memory writes go through one choke point + ERASURE_TARGETS
- Commit each phase before advancing; process and execution commits separate

TEST GATES (run at every phase exit):
  node .claude/skills/vc-audit-vc/scripts/validate-agent-parity.mjs
  node .claude/skills/vc-audit-vc/scripts/validate-skills.mjs
  node .claude/skills/vc-audit-context/scripts/validate-context-discovery.mjs
  node .claude/skills/vc-audit-plans/scripts/validate-plan-inventory.mjs
  node .claude/skills/vc-audit-vc/scripts/validate-protocol-wiring.mjs
  Plus the phase plan's own pytest gates (runner: .venv/bin/python3.11 -m pytest)

VALIDATE CONTRACT: Per-phase contracts written by vc-validate-agent into each phase plan before EXECUTE.

START: 4 phases (1, 2, 3a, 3b). Phase 1, loop step PVL — re-run from V1 after the cycle-4 supplement.
Phases 3a/3b are NEW split files needing a first PVL. NEVER target phase-3-learning-autonomy (superseded).
```

---

## Phase Ordering (Phased Delivery Plan)

**Restructured 17-08-26 (PVL cycle 4).** The former Phase 3 was split into 3a and 3b; see
§Phase 3 Split Decision below for why the cycle-2 revisit condition fired.

| Phase | Plan file | Scope summary | Depends on |
|---|---|---|---|
| 0 (pre-program) | this file | Charter, phase split, blast-radius registry | — |
| 1 — Signal acquisition | `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/phase-1-signal-acquisition_PLAN_17-08-26.md` | Persist `comment_id` + `Draft.site_id`; `engage_outcomes` table; reply-back correlation sweep; metrics poller; server-side attribution mint; ingest-side `attributed_visit` producer (AC-1..AC-4) | Phase 0 |
| 2 — Memory + privacy | `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/phase-2-memory-privacy_PLAN_17-08-26.md` | `engage_contact_memory` + the absorbed `engage_outcomes.contact_bidx`; enqueue-time erasure keys + dual dispatch branches; choke-point write gates; computed track record + mounted endpoint; third consent flag + k≥5 aggregates (AC-5..AC-10) | Phase 1 |
| 3a — Learning | `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/phase-3a-learning_PLAN_17-08-26.md` | Pure `autonomy_gate()` + `select_strategy_from_outcomes` + `determine_draft_mode` consult. No schema, no migration, no send path, no web file (AC-13) | Phase 1 |
| 3b — Autonomy surface | `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/phase-3b-autonomy_PLAN_17-08-26.md` | `DraftStatus.auto_approved`, the autonomous-send driver, six rails + dwell floor + sibling handling, two-entry audit, prompt-safety fence, five-surface guardrail amendment (AC-11, AC-12, AC-14..AC-20) | 3a **and** Phase 2 |
| — | `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/phase-3-learning-autonomy_PLAN_17-08-26.md` | ⛔ SUPERSEDED pointer — never an execute or PVL target; retains cycle-1..3 contract history | — |

### Join Conditions

- Phase 1 MUST NOT start until Phase 0 exit gate passes (all plan artifacts validator-clean).
- Phase 2 MUST NOT start until Phase 1 exit gate passes — Phase 2 reads `engage_outcomes` rows that
  only Phase 1 can create, and appends `contact_bidx` to Phase 1's table.
- **3a MUST NOT start until Phase 1 exit gate passes.** It does NOT require Phase 2: it reads only the
  `engage_outcomes` shape and writes pure functions. Its DISTINCT-contact leg is written against the
  `contact_bidx` column contract and gated as Phase-2-dependent.
- **3b MUST NOT start until BOTH 3a and Phase 2 exit gates pass.** It imports `autonomy_gate` from 3a
  and `compute_track_record` + `contact_bidx` from Phase 2.
- **3a and Phase 2 are parallel-safe with each other** (disjoint file sets: 3a touches only
  `services/engage_autonomy.py`, `services/ai_reply.py`, `config.py`, 2 unit test files). Running them
  concurrently is permitted; running 3b concurrently with either is NOT.

### Independent shippability

Phases 1, 2 and 3a are each independently valuable and independently shippable. If 3b stalls, the
program still delivers measured outcomes, owner-visible track records, and outcome-driven strategy
selection — with **zero autonomy surface in the codebase at all**.

---

## Pre-PVL Conflict Resolution

**Resolved 17-08-26 by the orchestrator; amended after PVL cycle 2 (decisions D-O1 … D-O10, then
N1 … N6 / K1 … K8 / P2 F2-1,F2-2 / P3 Gaps 1-3,7,8).**

Cycle 2 forced three further re-classifications, all recorded in the table below: `routers/drafts.py`
became SHARED (Ph1 needs one line at `:199`; Ph3b owns the rest), `engage_outcomes.contact_bidx` moved
from Phase 1 to Phase 2 (its helper and erasure machinery live there — Phase 1 would have shipped
un-erasable PII behind a circular dependency), and two web AC-20 surfaces
(`llms.txt/route.ts`, `page-help.tsx`) were added to Phase 3b.


Cycle 1 proved the initial single-author disjointness claim incomplete: three shared files were
either unowned or wrongly claimed exclusive. Classification of every shared package/file:

| Shared surface | Classification | Resolution |
|---|---|---|
| `apps/api/jobs/scheduler.py` | **reassign → SHARED-append-only (all 3 phases)** | Was exclusive to Phase 1, which blocked Phase 2's aggregation job (F-E1) and Phase 3b's send driver. Each phase appends ONLY its own job ids, with literal `jitter` + `misfire_grace_time`. |
| `tests/unit/test_scheduler_job_config.py` | **reassign → SHARED (all 3 phases)** | AST-enforced literal kwargs + hardcoded inventory counts. Every phase adding a job re-derives the counts in the same change. |
| `apps/api/models/draft.py` | parallel-safe (disjoint edit regions) | Phase 1 = `platform_comment_id` + `site_id` (`String(50)` slug FK, N1) columns. Phase **3b** = the `auto_approved` enum value ONLY. Phase 3a touches this file NOT AT ALL. |
| `apps/api/routers/drafts.py` | **reassign → SHARED (Ph1 + Ph3b)** | Cycle-2 N2: it is the second draft producer (`:199`) and Phase 1 must set `site_id` there. **Ph1 = that one line; 3b = undo action, autonomy-audit read endpoint, pure sibling helper, retry fix.** |
| `engage_outcomes.contact_bidx` | **reassign → Phase 2** | Cycle-2 N5/N6: `blind_index()` and `ERASURE_TARGETS` are Phase-2-owned, so a Phase-1 column would be both circular and un-erasable. Column + migration + erasure registration land together in Ph2. |
| `apps/web/src/app/llms.txt/route.ts`, `apps/web/src/components/page-help.tsx` | parallel-safe (**Ph3b** only) | Cycle-2 Gap 3: a SERVED public route and in-product copy still assert "never auto-sends". Added to Ph3b's AC-20 scope and to the five-grep gate. |
| `apps/api/services/sender.py` | parallel-safe (exhaustive licensed-edit list) | Four licensed edits, enumerated below. Anything else is BLOCKED, not absorbed. |
| `apps/api/services/platforms/base.py` + `twitter.py` | **reassign → SHARED (Ph1 + Ph3b)** | Ph1 adds metrics/mentions/`referenced_tweets` reads; Ph3b adds `delete_comment`. Both as NON-abstract `PlatformService` defaults raising `NotImplementedError` — an `@abstractmethod` breaks all five subclasses. Neither touches `post_comment`. |
| `apps/web/src/**` | **reassign → SPLIT by surface (Ph2 + Ph3b)** | Ph2 owns the engage track-record surfaces + its `api.ts` additions. Ph3b owns `api-types.ts` (`DraftStatus` union), `status-badge.tsx`, `draft-card.tsx`, `dashboard/drafts/page.tsx`, and the undo UI. |
| `apps/api/models/site.py` | parallel-safe | One differently-named column per phase (Ph2 `engage_learning_contribution_enabled`, Ph3b `engage_autonomy_enabled`). |
| `apps/api/main.py` | **reassign → SHARED-append-only (all 3 phases)** | `# noqa: F401` model-registration imports only. This is the integration lane's ONLY table-registration mechanism (`tests/conftest.py:123`). |
| `apps/api/services/ai_reply.py` | **SHARED (Ph3a + Ph3b), SEQUENTIAL** | 3a edits `select_strategy_from_outcomes` + the `determine_draft_mode` consult (`:204`, `:261`); 3b edits `_sanitize_content` (`:111-119`, AC-19) only. 3a lands first by dependency order, so these are sequential edits to genuinely disjoint regions. **Each phase edits ONLY its named functions plus append-only import additions; neither phase reformats, reorders, or re-indents `ai_reply.py`** (cycle-4 3a-C2: the residual risk is whole-file operations near the shared import region, not region overlap). |
| `apps/api/config.py` | parallel-safe | One commented block per phase; no phase edits another's block. |
| `apps/api/routers/engagement.py` | parallel-safe (Ph2 only) | The track-record endpoint joins the ALREADY-MOUNTED router (`main.py:559`). Phase 2 does NOT create `routers/engage.py` — that would need a mount no checklist provided (F-D1). |
| `apps/api/routers/events.py` | parallel-safe (Ph1 only) | Ingest-side `beam_` utm attribution wiring — the `attributed_visit` producer (G3/G7). |
| `process/context/all-context.md` + `README.md` | parallel-safe (**Ph3b** only) | AC-20 guardrail amendment; all FIVE carrying surfaces (D-O6 + cycle-2 Gap 3), not three. |

**Conclusion: no phase is reassigned; five shared surfaces were re-classified from "exclusive" to
"shared with an ownership rule."** Phases remain sequential by dependency (Ph1 → Ph2 → Ph3a → Ph3b, with 3a ← Ph1 only); Phase 2's
cross-tenant half stays parallel-safe with Phase 3a.

## Phase Blast-Radius Registry

One registry, flat in this program task folder. **Amended 17-08-26 (PVL cycle 1, decisions D-O1/D-O3/D-O4).**
Each phase lists exact files. Shared files carry an explicit ownership rule; anything not listed is
outside that phase's blast radius.

### Phase 1 — Signal acquisition

Owns (exclusive):
- `apps/api/services/sender.py` — **owns the send-path structure**; licensed edits **#1** (comment_id
  persist) and **#2** (attribution mint before `post_comment`).
- `apps/api/models/draft.py` — **(D-O1 + N1 amendment)** adds `platform_comment_id` AND `site_id`
  columns. **`site_id` is `String(50)` FK → `sites.site_id` (the SLUG), not the UUID PK** — matching
  `visitors.site_id`, `Event.site_id`, and `EngagementAttribution.site_id`, all `String(50)`. Every
  downstream aggregate in Phases 2 and 3 joins on that slug, never on `sites.id`. Does NOT touch
  `DraftStatus`.
- `apps/api/models/engage_outcome.py` (new)
- `apps/api/services/engage_outcome_sweep.py` (new)
- `apps/api/services/engage_metrics_poll.py` (new)
- `apps/api/services/engagement_tracker.py` — attribution row write + `attributed_visit` producer.
- `apps/api/services/auto_drafter.py` — sets `Draft.site_id` at draft creation (D-O1 derivation).
- `apps/api/routers/events.py` — **(new touchpoint, N3-corrected)** ingest-side wiring anchored AFTER
  the commit at `events.py:474` (post-commit loop precedent `events.py:618`), deduped to the distinct
  `beam_` utm_sources per batch, fail-open.
- `apps/api/migrations/versions/<new>_add_engage_outcomes.py` (new)

Shared, with rule:
- `apps/api/routers/drafts.py` — **(N2 amendment) SHARED between Phase 1 and Phase 3b.** Phase 1 holds
  exactly ONE licensed edit: set `Draft.site_id` at the manual-draft construction (`drafts.py:199`).
  Phase 3b owns everything else in the file (undo action, autonomy-audit read endpoint, sibling helper, retry fix).
- `apps/api/jobs/scheduler.py` — SHARED-append-only; Phase 1 appends `engage_outcome_sweep` +
  `engage_metrics_poll` only. **No `next_run_time` on either job** (K1: the `aggregation_sweep` 90s
  boot-offset ordering is AST-asserted); spread by distinct `jitter` literals only.
- `tests/unit/test_scheduler_job_config.py` — SHARED; Phase 1 re-derives the counts (26/22 → 28/24).
- `apps/api/services/platforms/base.py` + `twitter.py` — SHARED; Phase 1 ADDS the metrics/mentions/
  `referenced_tweets` reads as non-abstract defaults. Does not modify `post_comment`.
- `apps/api/main.py` — SHARED-append-only; `EngageOutcome` registration import.
- `apps/api/config.py` — appends its own `# ─── Engage outcome capture (Phase 1) ───` block only.

### Phase 2 — Memory + privacy

Owns (exclusive):
- `apps/api/models/engage_contact_memory.py` (new)
- `apps/api/models/engage_benchmark.py` (new)
- `apps/api/services/engage_memory.py` (new — the single write choke point)
- `apps/api/services/engage_benchmark.py` (new)
- `apps/api/services/engage_track_record.py` (new — computed, no materialized stats table)
- `apps/api/models/erasure_request.py` — adds to `ERASURE_TARGETS` **and** the new `author_bidx_list`
  ARRAY column.
- `apps/api/services/graph_erasure.py` — enqueue-time key collection, `_claim_next` extension,
  `_engage_memory_delete_stmt`, and the `elif` dispatch branch (D-O7).
- `apps/api/services/pii_crypto.py` — adds a generic `blind_index()`; `email_hash` untouched.
- `apps/api/models/engage_outcome.py` — **SHARED-with-rule (C3-1):** Phase 1 authors the table;
  Phase 2 appends EXACTLY ONE column (`contact_bidx`) and touches nothing else in the file.
- **(N5/N6 transfer)** `engage_outcomes.contact_bidx` — the column, its migration, and its
  `ERASURE_TARGETS` registration all land HERE, not in Phase 1. Phase 1 cannot own it: the helper is
  Phase-2-owned (circular dependency) and `engage_outcomes` would otherwise carry PII-derived data
  with no erasure path, violating this charter's own hard constraint.
- `apps/api/routers/engagement.py` — track-record endpoint on the ALREADY-MOUNTED router.
- `apps/api/schemas/engage.py` (new)
- `apps/web/**` engage **track-record** surfaces only (D-O4 split) + its `api.ts` additions.
- `apps/api/migrations/versions/<new>_add_engage_memory.py` (new)

Shared, with rule:
- `apps/api/models/site.py` — adds `engage_learning_contribution_enabled` ONLY.
- `apps/api/jobs/scheduler.py` — SHARED-append-only; Phase 2 appends `engage_benchmark_aggregate` only.
- `tests/unit/test_scheduler_job_config.py` — SHARED; re-derive counts in the same change.
- `apps/api/main.py` — SHARED-append-only; two model registration imports.
- `apps/api/config.py` — appends its own `# ─── Engage memory (Phase 2) ───` block only.

### Phase 3a — Learning (pure functions only)

Owns (exclusive):
- `apps/api/services/engage_autonomy.py` (new — pure `autonomy_gate()`, **no production caller in this phase**)
- `apps/api/services/ai_reply.py` — `select_strategy_from_outcomes` + the `determine_draft_mode` consult ONLY (3b separately edits `_sanitize_content` in the same file, AFTER 3a lands — sequential, not concurrent)
- `tests/unit/test_engage_autonomy.py`, `tests/unit/test_engage_strategy_selection.py` (new)

Shared, with rule:
- `apps/api/config.py` — appends the `# ─── Engage learning (Phase 3a) ───` block only (one key: `engage_outcome_learning_enabled`).

Touches NO schema, NO migration, NO `sender.py`, NO `routers/`, NO `jobs/scheduler.py`, NO `apps/web/`, NO doc surface.

### Phase 3b — Autonomy surface

Owns (exclusive):
- `apps/api/services/engage_autonomy.py` — **READ-ONLY in 3b** (created by 3a; 3b imports it)
- `apps/api/services/engage_autonomous_sender.py` — **(D-O3, new)** the autonomous-send driver: sweeps
  eligible pending drafts, runs the gate, flips `pending → auto_approved`, calls `send_draft`, and owns
  the kill-switch fallback. Without this the autonomous path is homeless (V1/F2).
- `apps/api/services/engage_crisis.py` (new — fail-closed lexicon)
- `apps/api/models/engage_autonomy_audit.py` (new) — **must carry `draft_id` (FK → `drafts.id`,
  indexed) and an `entry_type` discriminator (`decision` | `outcome` | `undo`) plus nullable
  `outcome_status`** (cycle-3 FAIL 1: without them the marker queries are unwritable). Outcome rows are
  written by the DRIVER after `send_draft` returns — **no fifth `sender.py` edit** (cycle-3 FAIL 2).
- `apps/api/schemas/engage_autonomy.py` (new)
- `apps/api/services/ai_reply.py` — **`_sanitize_content` composing `clean_text` (AC-19) ONLY**;
  `select_strategy_from_outcomes` and the `determine_draft_mode` wiring belong to 3a and land first.
- `apps/api/routers/drafts.py` — undo action, **autonomy-audit read endpoint (its assigned home)**,
  the extracted shared sibling-rejection helper (D-O5), and the retry fix. `approved` still written
  only at `:272`.
- `apps/web/src/lib/api-types.ts`, `apps/web/src/components/ui/status-badge.tsx`,
  `apps/web/src/components/**/draft-card.tsx`, `apps/web/src/app/dashboard/drafts/page.tsx`, plus the
  undo UI — **(D-O4 web split)** these are the real `auto_approved` hiding surfaces (V6).
- `process/context/all-context.md` + `README.md` + `apps/web/src/app/llms.txt/route.ts` +
  `apps/web/src/components/page-help.tsx` — AC-20 amendment across all FIVE carrying surfaces
  (D-O6 + cycle-2 Gap 3; the ONLY phase touching them). `docs/*` and `marketing/*` are DELIBERATE
  exclusions, covered by `backlog/marketing-copy-reconciliation_NOTE_17-08-26.md`.
- `apps/api/migrations/versions/<new>_add_engage_autonomy*.py` (TWO files: the enum `ALTER TYPE` alone,
  then the audit table + `Site` column).

Shared, with rule:
- `apps/api/models/draft.py` — adds the `auto_approved` value to `DraftStatus` ONLY.
- `apps/api/services/sender.py` — licensed edits **#3** (widen the status predicate at `:162`) and
  **#4** (pre-`post_comment` idempotency key + kill-switch/ceiling re-check **and** the
  same-transaction audit-row write alongside `draft.status = DraftStatus.sent` at `:215`).
- `apps/api/models/site.py` — adds `engage_autonomy_enabled` ONLY.
- `apps/api/services/platforms/base.py` + `twitter.py` — SHARED; Phase 3b adds `delete_comment` as a
  non-abstract default raising `NotImplementedError`, overridden in `TwitterService`.
- `apps/api/jobs/scheduler.py` — SHARED-append-only; Phase 3b appends `engage_autonomous_send` only.
- `tests/unit/test_scheduler_job_config.py` — SHARED; re-derive counts in the same change.
- `apps/api/main.py` — SHARED-append-only; audit-model registration import.
- `apps/api/config.py` — appends its own `# ─── Engage autonomy (Phase 3b) ───` block only.

### sender.py licensed-edit list (exhaustive — D-O4)

| # | Phase | Edit |
|---|---|---|
| 1 | Ph1 | Persist `draft.platform_comment_id = comment_id` before the success commit |
| 2 | Ph1 | Mint the attribution tag (link-present path only) immediately before `post_comment` |
| 3 | Ph3b | Widen the status predicate at `:162` to `{approved, auto_approved}` |
| 4 | Ph3b | Pre-`post_comment` idempotency key + kill-switch/ceiling re-check, AND the same-transaction audit-row write at `:215` |

Any fifth edit is a BLOCKED condition to surface, never to absorb.

### Non-overlap rules (binding)

1. `sender.py`: only the four licensed edits above. Phase 3b may not restructure Phase 1's send path.
2. `config.py`: each phase appends a NEW commented block; no phase edits another's.
3. `models/site.py`: one new column per phase, different names, different migrations.
4. `models/draft.py`: Phase 1 = two columns; Phase 3b = one enum value. Phase 3a does not touch this file. Never the same edit region.
5. `jobs/scheduler.py`, `tests/unit/test_scheduler_job_config.py`, `apps/api/main.py`: SHARED-append-only —
   each phase touches only its own job ids / registration imports, and re-derives the AST-enforced
   inventory counts in the same change.
6. `apps/web/src/**`: Phase 2 = track-record surfaces; Phase 3b = drafts page, badge, card, TS union,
   undo UI, plus the two AC-20 web surfaces (`llms.txt/route.ts`, `page-help.tsx`). No file is edited
   by both.
6b. `apps/api/routers/drafts.py`: Phase 1 = ONE licensed edit (set `site_id` at `:199`); Phase 3b =
   everything else. Never the same edit region.
7. Migrations: **4 total** (Ph1 ×1, Ph2 ×1, Ph3a ×0, Ph3b ×2 — the enum change is isolated in its own file),
   each chained off the live head re-derived at EXECUTE time.

## Phase 3 Split Decision (3a / 3b) — REVISIT CONDITION FIRED, SPLIT EXECUTED 17-08-26

At PVL cycle 2 this program considered the split and **rejected** it, recording an explicit revisit
condition: *"if Phase 3 stalls at EXECUTE or a third PVL cycle lands new FAILs in the rails, revisit
this decision — the seam the validator identified is real and clean."*

**That condition fired at cycle 3, and the split has now been executed.**

Evidence that triggered it (confirmed by the cycle-3 validator, not asserted):

| Cycle | Phase 3 verdict | Where the FAILs lived |
|---|---|---|
| 1 | 7 FAILs / 9 CONCERNs | Steps C–G |
| 2 | 3 FAILs / 8 CONCERNs — **none a restatement**; all newly derived from the cycle-1 fix text | Steps C–G |
| 3 | 2 FAILs / 4 CONCERNs — **both inside the cycle-2 supplement's own new text** | Steps C (FAIL 1) and D (FAIL 2) |

Steps A and B produced **zero findings across all three cycles**. The volatility was entirely in the
autonomy surface: a first-of-kind `ALTER TYPE … ADD VALUE`, a send driver, six rails, a two-entry
audit design, five doc surfaces and five web files — a set where each fix reliably created new
surface for the next cycle to find.

**What the split changes.** 3a carries the two pure functions (no schema, no migration, no send path,
no web file, ~5 files). 3b carries everything else. All cycle-3 FAILs live in 3b and are closed
there. The flag rollout order (capture → learning → autonomy) still provides the staging benefit the
cycle-2 rejection relied on — the split adds *structural* isolation on top of it, so a stalled 3b can
no longer block shipping learning.

**What the split does NOT change.** The umbrella's binding rule still holds: no autonomous-send
capability becomes reachable before its rails land in the SAME phase. 3a ships `autonomy_gate()` with
**no production caller**, gated by `test_autonomy_gate_has_no_production_caller`.

---

## Per-Phase Entry / Exit Gates

| Phase | Entry | Exit gate |
|---|---|---|
| 0 | Program start | All plan artifacts exist and pass their validators |
| 1 | Phase 0 complete | AC-1..AC-4 gates green (flag-ON legs + boundary gates included); migration round-tripped on a disposable container; sweep + poller registered, advisory-locked, idempotent |
| 2 | Phase 1 exit met | AC-5..AC-10 green; **all EIGHT erasure gates** green including the author-bidx-only path and the `engage_outcomes` unlink; five-object migration round-tripped |
| 3a | Phase 1 exit met | AC-13 green (flag-ON leg included); purity gate green; **no-production-caller gate green**; unit-lane regression clean |
| 3b | 3a **and** Phase 2 exits met | AC-11, AC-12, AC-14..AC-20 green; all six rails gated (none as known-gap); two-entry audit provably queryable; both migrations round-tripped; all FIVE AC-20 greps return no match |

---

## Per-Phase Loop

Each phase executes the canonical 7-step inner loop `R → I → P → PVL → E → EVL → UP`. This inner
loop SKIPS SPEC — the umbrella SPEC governs every phase.

1. **RESEARCH** — load context (`process/context/all-context.md` + `process/context/tests/all-tests.md`
   routing chain), read prior phase reports, check plan drift, re-derive the alembic head.
2. **INNOVATE** — decide approach; write a Decision Summary. Where this umbrella records a locked
   decision (D1–D10), INNOVATE confirms it rather than reopening it.
3. **PLAN-SUPPLEMENT** — plan-agent adds research/innovate gaps to the phase plan, or marks
   "n/a — research clean"; writes an Inner Loop Refresh Note if sections changed.
4. **PVL** — vc-validate-agent runs V1–V7 and writes the full validate-contract.
5. **EXECUTE** — vc-execute-agent implements per the plan + contract; per-section test gates.
6. **EVL** — vc-tester independently re-runs the contract gates; follow-up stubs registered.
7. **UPDATE-PROCESS** — phase report written, `## Current Execution State` rewritten (overwrite,
   not append), commit.

**PVL is NEVER skipped.** A placeholder `## Validate Contract` = blocked.

---

## Locked Decision Record (from INNOVATE, 17-08-26 — do not reopen)

| ID | Decision |
|---|---|
| D1 | Nullable `Draft.platform_comment_id`; new append-only `engage_outcomes` table (type ∈ reply_received, metrics_snapshot, attributed_visit; counts + timestamps + draft_id FK; structurally NO body/text column). No `sent_replies` mirror. |
| D2 | Reply-back correlation = new APScheduler interval sweep modeled on `_handoff_correlation_sweep_job`; exact linkage via X `referenced_tweets[type=replied_to].id`. `engage_outcome_sweep_interval_minutes=30`, jitter, advisory-locked. No webhooks; do NOT piggyback the existing social sync job. |
| D3 | Metrics poller in the same job family; batched `GET /2/tweets?ids=…` (≤100 ids); age-tiered (<48h each sweep → daily → terminal at 7d). Mock branch under `mock_external_apis` matching `routers/demo.py:603` field shape. Live tier/cadence = OQ-1 known-gap (Hybrid), never a blocking gate. |
| D4 | Attribution tag minted server-side inside `send_draft()` immediately before `post_comment`; site-owned link rewritten with the utm tag + `EngagementAttribution` row inserted in the SAME transaction as `status=sent`. No site link → recorded `attribution: none`, not an error. |
| D5 | Three memory scopes: per-contact `engage_contact_memory` (HMAC blind index of platform+author_id, handle ciphertext-only, site-scoped, facts only, in ERASURE_TARGETS + sweep gains a social bidx match key); per-site/playbook track record COMPUTED at read/gate time from `engage_outcomes` (NO materialized stats table — icp_fit lesson); cross-tenant via new `services/engage_benchmark.py` replicating `campaign_benchmark.py` posture (k≥5, sub-floor writes no row, non-consenting never fetched, no deltas, reuse `normalize_category`). |
| D6 | Third consent flag `Site.engage_learning_contribution_enabled` (default False). Per-contact memory writes flow ONLY through `record_engage_outcome()` in `services/engage_memory.py`, mirroring `identity_signals` gates-then-silent-skip: suppression (via identified-visitor email join), `do_not_resolve` sticky, memory-flag ON. `engage_outcomes` (non-PII own-post facts) gated by flag only. |
| D7 | Learning = additive pure `select_strategy_from_outcomes(stats)` consulted by `determine_draft_mode` when `engage_outcome_learning_enabled` ON; falls back to `_get_preferred_strategy`. Outcome signal outranks approval signal once outcome N ≥ small floor. Deterministic/seedable. `voice_examples` NOT rebuilt. |
| D8 | Autonomy gate = pure `autonomy_gate()` in `services/engage_autonomy.py`; inputs ONLY the outcome-history aggregate + config; returns `{allowed, reason, sample_n, positive_rate}` flowing verbatim into the audit row. Model output structurally absent from the signature. Defaults `engage_autonomy_min_outcomes=20`, `engage_autonomy_min_positive_rate=0.4` (placeholder-conservative, tune-from-observed). Positive = reply_received OR attributed_visit (likes alone never unlock). Positive-rate aggregate uses DISTINCT-CONTACT counting (anti reply-spam gaming — mandatory). |
| D9 | Autonomous send fires via NEW `DraftStatus.auto_approved`; `sender.py` accepts `{approved, auto_approved}`; `routers/drafts.py` stays the sole writer of human `approved`. MUST audit every `DraftStatus` consumer so `auto_approved` rows don't vanish from UI. Kill-switch fallback = flip `auto_approved → pending`. Idempotency key on `draft_id` before `post_comment`. |
| D10 | Rails: dual kill switch (global `engage_autonomous_send_enabled=False` + per-site `Site.engage_autonomy_enabled=False`), checked in the gate AND re-checked at send time; hourly Redis ceiling per (site,hour) `engage_social_send_hourly_ceiling=20`, incremented BEFORE the platform call, fail-closed on Redis error → queue; `services/engage_crisis.py` deterministic conservative lexicon, FAIL-CLOSED (error/timeout → human queue; quality = Hybrid residual); suppression via `is_email_suppressed` through contact→identified-visitor join (unknown-email = documented limit); append-only `engage_autonomy_audit`, audit row committed in the SAME transaction as the send-status flip; undo = new platform `delete_comment()` (X `DELETE /2/tweets/:id`) + dashboard action + audit entry (live delete = Hybrid residual); AC-19 routes thread-derived text through `prompt_safety` and makes `_sanitize_content` compose `clean_text`; AC-20 amends `all-context.md`, grep-gated at EVL. |

---

## Risk Predictions (vc-predict CAUTIONs — each is a binding plan item)

| Risk | Encoded as |
|---|---|
| `DraftStatus` enum widening hides rows from dashboard filters | Phase 3b checklist item: audit EVERY `DraftStatus` consumer (dashboard filters, campaign surfaces) + a gate asserting `auto_approved` rows appear in the drafts list |
| AC-19 fence landing later than the autonomy surface | AC-19 is assigned to Phase 3b — the SAME phase as autonomy. It may not be deferred. |
| Track-record aggregate scans grow unbounded | Phase 1 migration creates `ix_engage_outcomes_site_strategy_created` on `(site_id, strategy, created_at)` |
| Owner cannot see the evidence that unlocked autonomy | AC-8 track-record UI is Phase 2 — ships BEFORE the Phase 3b gate |
| Erasure sweep silently misses social memory (email-bidx-only matching today) | Phase 2 explicit checklist item: extend the sweep with a social blind-index match key + a gate that fails if the row survives |
| Kill switch flipped while a send is in flight | Phase 3b: re-check BOTH switches at send time, not only at gate time; gate covers the in-flight race |
| Redis down silently disables the ceiling | Phase 3b: ceiling is fail-CLOSED — Redis error queues the draft; gate simulates a Redis failure |

---

## Autonomous Execution Rules (During /goal)

- Agent self-decides at all V5 gates — no user approval between phases.
- CONDITIONAL net gate: proceed autonomously, gaps on record.
- BLOCKED net gate: write a backlog note, continue with remaining phases.
- Hard stops (must pause): unpinned `DATABASE_URL` on any alembic/DB command; any billed live X
  API call (OQ-1); flipping any `engage_*` flag ON in a real environment; any deploy or push.
- The phase report is the communication channel for conflicts, errors, and learnings.

---

## Global Constraints

- All 6 new flags default OFF. `Draft.platform_comment_id` persistence itself is unconditional and
  additive (it is data capture, not behavior change).
- **Mocking uses whichever of the repo's TWO mechanisms already applies (K8 reconciliation).**
  (a) Platform/social calls are mocked with a stub-`PlatformService` monkeypatch — the precedent is
  `tests/integration/test_sender_token_refresh.py` (`_FakeService` + `_patch_service`); there is NO
  `MOCK_EXTERNAL_APIS` branch in `services/platforms/` or `sender.py` and inventing one is a
  blast-radius expansion. (b) Service-layer `MOCK_EXTERNAL_APIS` branches are used only where that
  convention already exists in the touched module. Either way, fakes must match the REAL field shape.
- Multi-tenancy: every new user-facing query filters through `Site.user_id == user.id`; unknown ids
  return 404/not-found, never 403.
- No third-party-authored text is ever persisted (AC-6) or reaches a prompt unfenced (AC-19).
- 4 migrations total. Never hardcode `down_revision`. Read-only head derivation may use the shared dev
  DSN `retarget:retarget_dev@localhost:5433/retarget_agent`; every destructive up/down round-trip runs
  against a **disposable** `postgres:16-alpine` container, never the shared dev DB.
- Commit each phase before advancing; process/plan commits separate from execution commits.
- **3a ships `autonomy_gate()` unreachable.** No module under `apps/api` may import
  `services/engage_autonomy` until 3b's driver lands; gated by
  `test_autonomy_gate_has_no_production_caller`.

---

## Durable Report Destinations

| Phase | Report path (flat in this task folder) |
|---|---|
| 1 | `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/phase-1-signal-acquisition_REPORT_17-08-26.md` |
| 2 | `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/phase-2-memory-privacy_REPORT_17-08-26.md` |
| 3a | `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/phase-3a-learning_REPORT_17-08-26.md` |
| 3b | `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/phase-3b-autonomy_REPORT_17-08-26.md` |

---

## Program Status Table

Status promotion rule: a phase reaches ✅ VERIFIED only when its gates are green AND the user confirmed the phase works (user-confirmed; code-only completion is never VERIFIED).

| Phase | Status |
|---|---|
| 0 — Pre-program (plan creation) | ✅ COMPLETE |
| 1 — Signal acquisition | ⏳ PLANNED |
| 2 — Memory + privacy | ⏳ PLANNED |
| 3a — Learning (pure functions) | ⏳ PLANNED |
| 3b — Autonomy surface | ⏳ PLANNED |

Status values: ⏳ PLANNED | 🔨 CODE DONE | 🧪 TESTING | ✅ VERIFIED | 🚧 BLOCKED | ✅ COMPLETE

---

## SPEC AC → Phase Coverage Map

Every AC appears in exactly one phase. Restructured at cycle 4 (AC-13 → 3a; the rest of the former
Phase 3 → 3b).

| Phase | ACs | Count |
|---|---|---|
| 1 — Signal acquisition | AC-1, AC-2, AC-3, AC-4 | 4 |
| 2 — Memory + privacy | AC-5, AC-6, AC-7, AC-8, AC-9, AC-10 | 6 |
| 3a — Learning | AC-13 | 1 |
| 3b — Autonomy surface | AC-11, AC-12, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20 | 9 |

Total: **20/20 covered, zero duplication.**

**Deliberate placement note.** Step A (the pure `autonomy_gate` function) is BUILT in 3a but AC-11
and AC-12 are PROVEN in 3b. Their falsifiers require an end-to-end path — a fabricated model
confidence must be shown not to authorize a real send — and no send path exists until 3b. Asserting
them against the bare function would be a vacuous gate of exactly the class this charter bans.

---

## Touchpoints

- Phase 1: `sender.py`, `models/draft.py` (2 columns), `models/engage_outcome.py`, `services/engage_outcome_sweep.py`, `services/engage_metrics_poll.py`, `services/engagement_tracker.py`, `services/auto_drafter.py`, `routers/events.py`, `jobs/scheduler.py`, `tests/unit/test_scheduler_job_config.py`, `services/platforms/{base,twitter}.py`, `apps/api/main.py`, `config.py`, 1 migration
- Phase 2: `models/engage_contact_memory.py`, `models/engage_benchmark.py`, `services/engage_memory.py`, `services/engage_benchmark.py`, `services/engage_track_record.py`, `models/erasure_request.py`, `services/graph_erasure.py`, `services/pii_crypto.py`, `models/site.py`, `routers/engagement.py` (already mounted — NOT a new router), `schemas/engage.py`, web track-record surface, `jobs/scheduler.py`, `apps/api/main.py`, `config.py`, 1 migration
- Phase 3a: `services/engage_autonomy.py` (pure gate, no production caller), `services/ai_reply.py` (selector + `determine_draft_mode` consult), `config.py` (one key)
- Phase 3b: `services/engage_autonomous_sender.py` (the send driver, D-O3), `services/engage_crisis.py`, `models/engage_autonomy_audit.py`, `schemas/engage_autonomy.py`, `services/ai_reply.py`, `routers/drafts.py`, `sender.py` (licensed edits 3+4 only), `models/draft.py` (enum only), `models/site.py`, `services/platforms/{base,twitter}.py`, `jobs/scheduler.py`, 5 web files, `process/context/all-context.md`, `README.md`, `config.py`, 2 migrations

---

## Public Contracts

- `sender.send_draft(db, draft) -> bool` signature unchanged across all three phases.
- `routers/drafts.py` approve endpoint contract unchanged; `approved` remains human-only.
- `VisitorOut` / visitor API surfaces unchanged — this program adds no visitor-schema fields.
- `/engagement/roi` response shape unchanged; it simply stops returning zeros (Phase 1).
- New additive surfaces only: engage track-record read endpoint (Phase 2), undo action (Phase 3b).
- `is_emailable_identity()` semantics unchanged — social autonomy never widens email eligibility.

---

## Blast Radius

- ~13 new Python modules/models across 3 phases; ~8 existing backend files edited additively.
- **4** alembic migrations (Ph1 x1, Ph2 x1 covering FIVE objects incl. the transferred `contact_bidx`, Ph3a x0, Ph3b x2 — the `ALTER TYPE ... ADD VALUE` is isolated in its
  own autocommit-safe file with a type-recreate downgrade); 4 new tables; 2 new `Site` columns; **2**
  new `Draft` columns (`platform_comment_id`, `site_id` — `String(50)` slug FK per N1); 1 new `erasure_requests` ARRAY column; 1 new
  `DraftStatus` enum value.
- Web: Phase 2 adds the track-record surface; Phase 3b edits `api-types.ts`, `status-badge.tsx`,
  `draft-card.tsx`, `dashboard/drafts/page.tsx` and adds the undo UI (D-O4 split).
- Guardrail amendment across FIVE surfaces (Phase 3b): `all-context.md:332`, `all-context.md:742`,
  and `README.md:3` (D-O6).
- Risk class: **HIGH** — public outward-facing action surface (autonomous posting), PII memory,
  cross-tenant data flow, and a schema migration. All three high-risk classes require at minimum a
  Hybrid gate; no known-gap is accepted for the autonomy rails.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Phase 1 exit gate suite (see phase-1 plan) | Fully-Automated | AC-1, AC-2, AC-3, AC-4 |
| Phase 2 exit gate suite (see phase-2 plan) | Fully-Automated | AC-5..AC-10 |
| Phase 3a exit gate suite (see phase-3a plan) | Fully-Automated | AC-13 |
| Phase 3b exit gate suite (see phase-3b plan) | Fully-Automated + Hybrid residuals | AC-11, AC-12, AC-14..AC-20 |
| `node .claude/skills/vc-audit-plans/scripts/validate-plan-inventory.mjs` exits 0 | Fully-Automated | Program artifact hygiene (not a SPEC AC) |
| `grep -n "Never build auto-send" process/context/all-context.md` returns no match | Fully-Automated | AC-20 |

```bash
# Program-level artifact gate (run now, and after any plan edit)
node .claude/skills/vc-generate-phase-program/scripts/validate-umbrella-artifact.mjs \
  process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/engage-learning-agent-umbrella_PLAN_17-08-26.md
# Expected: failures: []
```

---

## Test Infra Improvement Notes

- Mock X client needs a `get_tweets_metrics` fixture matching the `routers/demo.py:603` field shape
  (Phase 1 builds it; Phases 2-3 reuse it).
- No Playwright auth harness exists for authenticated dashboard flows (known repo-wide gap) — the
  Phase 2 track-record UI and Phase 3b undo action carry e2e legs as Hybrid residuals, with backend
  proof Fully-Automated.
- Integration lane requires PG:5433 + Redis:6379; detect with
  `lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`. Docker CLI is at
  `/Applications/Docker.app/Contents/Resources/bin/docker` — `which docker` lies.

---

## Resume and Execution Handoff

1. Selected plan file path: `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/engage-learning-agent-umbrella_PLAN_17-08-26.md`
2. Last completed phase or step: Phase 0 (plan creation) — this file plus the 3 phase plans.
3. Validate-contract status: pending — vc-validate-agent writes one per phase plan before EXECUTE.
4. Supporting context files loaded: `process/context/all-context.md`, `process/context/tests/all-tests.md`, the locked SPEC, `.claude/skills/vc-generate-phase-program/templates/*`.
5. Next step for a fresh agent: read this umbrella, then `phase-1-signal-acquisition_PLAN_17-08-26.md`, then spawn vc-research-agent for Phase 1 Step 1. Do NOT spawn vc-execute-agent — no validate-contract exists yet.

---

## Current Execution State

Last updated: 17-08-26 (PVL cycle 7 — **PVL CLOSED**)
Completed phases: Phase 0 (Planning) + full PVL loop across all 4 phase plans
Current phase: Phase 1 — Signal acquisition
Current loop step: EXECUTE (awaiting user gate)
Program Net Gate: **PVL CLOSED — cleared to EXECUTE**

Per-plan PVL verdicts (cycle 7, final):

| Plan | Verdict | Note |
|---|---|---|
| Phase 1 — Signal acquisition | CONDITIONAL, 0 FAIL | Accepted pending the user's known-gap acceptances (KG-1 handle-rename drift; OQ-1 live X tier; AC-4 real-path ROI residual) |
| Phase 2 — Memory + privacy | CONDITIONAL, 0 FAIL | Residuals: AC-8 dashboard e2e (Clerk harness), KG-1, LinkedIn social-key erasure v1 X-only |
| Phase 3a — Learning | **PASS** | No residuals |
| Phase 3b — Autonomy surface | CONDITIONAL, 0 FAIL | Residuals: crisis-lexicon quality (Agent-Probe), live X delete (needs-live-provider), rendered-web e2e (Clerk harness) |

**Next action: EXECUTE Phase 1 — awaiting the user gate.** No further PVL cycle is scheduled.
Route with `phase-1-signal-acquisition_PLAN_17-08-26.md` as the single execute anchor.
The orchestrator must emit the `/goal` block before spawning vc-execute-agent.

PVL cycle log (7 cycles, closed):
- cycle 1 — 19 FAILs + 8 adversarial defects → 47-gap supplement.
- cycle 2 — all cycle-1 closures re-derived genuine; 11 NEW FAILs, all in cycle-1's fix text → 34 gaps.
- cycle 3 — 8 FAILs across P1/P2/P3, again inside the prior supplement's text → 25 gaps.
- cycle 4 — **program restructured**: former Phase 3 split into 3a + 3b (revisit condition fired) → 25 gaps.
- cycle 5 — 4 FAILs from the config-key move's propagation → 20 gaps.
- cycle 6 — 4 FAILs, root cause a MOVED banner without deletion → 14 gaps (2 found by the new self-checks).
- cycle 7 — 0 FAILs. 4 doc/label one-liners → CLOSED.
- Trajectory: 19 → 11 → 8 → 4 → 4 → 0 FAILs. No cycle ever restated a prior FAIL.

Loop step values: RESEARCH | INNOVATE | PLAN-SUPPLEMENT | PVL | EXECUTE | EVL | UPDATE-PROCESS
Orchestrator rule: read "Current loop step" and the verdict table before spawning any subagent.
All four phase plans now carry a written validate-contract; none reads BLOCKED.

Note: the Stable Program Goal above is fixed. This section is the only part that changes —
update-process-agent rewrites it after every phase closeout (overwrite, not append).

## Next Step

Say **ENTER VALIDATE MODE** to run outer PVL across the 3 phase plans, or spawn vc-research-agent
for Phase 1 Step 1 under the standing /goal.

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
