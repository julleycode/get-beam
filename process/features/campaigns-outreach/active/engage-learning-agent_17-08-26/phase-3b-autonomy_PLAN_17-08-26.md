---
name: plan:engage-learning-agent-phase-3b-autonomy
description: "Engage Learning Agent — Phase 3b: the autonomy surface — DraftStatus enum, autonomous-send driver, six safety rails, prompt-safety fence, and the five-surface guardrail amendment"
date: 17-08-26
feature: campaigns-outreach
metadata:
  node_type: memory
  type: plan
  feature: campaigns-outreach
  phase: phase-3b
---

# Phase 3b — Autonomy Surface

**Date**: 17-08-26
**Complexity**: COMPLEX
**Status**: ⏳ PLANNED
**Program:** engage-learning-agent
**Umbrella plan:** `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/engage-learning-agent-umbrella_PLAN_17-08-26.md`
**Report destination:** `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/phase-3b-autonomy_REPORT_17-08-26.md`
**Covers SPEC ACs:** AC-11, AC-12, AC-14 … AC-20 (AC-13 belongs to Phase 3a)
**Origin:** split out of the former Phase 3 on 17-08-26 (PVL cycle 4). Steps A + B moved to
`phase-3a-learning_PLAN_17-08-26.md`; this plan keeps Steps C–G, where all cycle-2 and cycle-3 FAILs lived.
**Supplement revision:** PVL cycle 2 supplement applied 17-08-26 — closes cycle-2 Gaps 1–3 (FAIL) and C2-1…C2-8 (CONCERN). Cycle-1 closures (F1–F7, C1–C9, V1, V2, V5, V6) were independently re-derived against real source; 4 confirmed closed, 3 superseded by sharper cycle-2 findings.

**TL;DR:** Let a **dedicated autonomous-send driver** post on its own ONLY when Phase 3a's pure gate
function clears N and R — behind a dual kill switch, an hourly ceiling, a fail-closed crisis block,
suppression enforcement, a two-entry audit trail, sibling-collision handling, a dwell floor, and an
undo. Every rail ships in this phase with its gate. The "never auto-send" text is amended across all
five surfaces that carry it.

---

## Inner Loop Refresh Note

**17-08-26 — PVL cycle 4 / program restructure (split + supplement).** This file is the successor to
`phase-3-learning-autonomy_PLAN_17-08-26.md`, which is now a SUPERSEDED pointer. Steps A + B moved
out to Phase 3a; Steps C–G stay here. The split-revisit signal encoded in the umbrella at cycle 2
TRIGGERED — the cycle-3 validator confirmed two consecutive cycles of fix-introduced FAILs, **all in
Steps C–G**, while Steps A+B drew zero findings in three cycles.

Cycle-3 gaps closed in the same pass: **FAIL 1** (audit schema had no `draft_id` and no entry-kind
discriminator, so Gap 1's two marker queries were unwritable) and **FAIL 2** (`failed`/`undone`
outcome entries had no legal write site under the registry's `sender.py` edit licence), plus
CONCERNs N1–N4 (re-eligibility after a kill-switch revert; human-retry target status; G7b coverage;
failed-send audit assertion). Sections amended: Overview, Entry Gate, Touchpoints, Public Contracts,
Blast Radius, Steps C/D/G, Acceptance Criteria, Verification Evidence, Test Procedure, Exit Gate.

**17-08-26 — PVL cycle 2 supplement (superseded above, retained for audit).** Sections amended: Overview, Touchpoints,
Blast Radius, Implementation Checklist (Steps C, D, F, G), Acceptance Criteria, Verification Evidence,
Test Procedure, Blockers, Exit Gate. Drivers: cycle-2 FAILs — Gap 1 (no durable autonomy marker, so
the retry fix and the eligibility predicate were both unimplementable), Gap 2 (the sibling helper
commits internally, so "same transaction as the flip" was unsatisfiable), Gap 3 (AC-20's surface set
missed a SERVED public route and in-product copy) — plus CONCERNs C2-1…C2-8 and orchestrator
decisions on the audit-as-marker design, the pure sibling helper, the dwell floor, and the 3a/3b
split rejection.

**17-08-26 — PVL cycle 1 supplement (superseded above, retained for audit).** Sections amended: Overview, Entry Gate,
Touchpoints, Public Contracts, Blast Radius, Implementation Checklist (Steps A–G, all rewritten),
Acceptance Criteria, Verification Evidence, Test Procedure, Test Infra Improvement Notes, Blockers,
Exit Gate. Drivers: validator FAILs F1–F7, CONCERNs C1–C9, adversarial findings V1 (homeless send
driver), V2 (unowned surfaces), V5 (sibling double-post), V6 (consumer gate cannot fail), and
orchestrator decisions D-O1, D-O3, D-O4, D-O5, D-O6, D-O10.

---

## Overview / Context and Goals

This is the phase where Beam's outward-facing behavior actually changes, so it carries the whole safety
surface. The design constraint that makes it defensible: the autonomy decision is a **pure function of
stored outcome history** — `autonomy_gate()` takes an outcome aggregate plus config and returns
`{allowed, reason, sample_n, positive_rate}`. Model output is structurally absent from the signature,
so a fabricated "0.99 confident" model response has no path to authorize a send.

Four facts discovered at PVL cycle 1 reshape this phase:

1. **The autonomous send had no driver (F2 / V1).** The prior checklist built the gate, the enum value,
   the widened predicate and the rails — but nothing called `autonomy_gate()`, wrote `auto_approved`, or
   invoked `send_draft`. The only draft producer (`auto_drafter.py:124`) writes `pending`. Orchestrator
   decision **D-O3** creates `services/engage_autonomous_sender.py` plus its scheduler job as the named
   owner.
2. **Sibling drafts double-post (V5).** Each post gets 1–3 drafts, and `_auto_reject_siblings`
   (`drafts.py:386`) runs ONLY inside the human approve endpoint (`drafts.py:276`). Per-`draft_id`
   idempotency cannot stop two siblings of the same post from both being auto-approved. **D-O5** requires
   the autonomous path to reuse the same semantics via an extracted shared helper.
3. **The consumer gate could not fail (F6 / V6).** The prescribed
   `grep -rn "DraftStatus\." apps/api apps/web` returns **zero hits in `apps/web`** — every web consumer
   is a type or string-literal position. The real hiding surfaces are `drafts/page.tsx:14-20` TABS,
   `draft-card.tsx:108` pending-only actions, and the closed TS union at `api-types.ts:995`.
4. **AC-20's grep was a half-gate (V4 / D-O6).** Editing `all-context.md:332` alone passes the old gate
   while `all-context.md:742` (different string and case) and `README.md:3` keep the stale rule.

Everything below threshold keeps today's behavior exactly: `routers/drafts.py:272` remains the sole
writer of human `approved`, and `sender.py` still refuses anything outside `{approved, auto_approved}`.

**Cycle-3's two FAILs, and how they are resolved here.** Both lived inside the cycle-2 fix text, not
in the original design:
- **FAIL 1 — the audit table could not do the job assigned to it.** Cycle 2 made
  `engage_autonomy_audit` the durable autonomy marker, then never gave it a `draft_id` column or an
  entry-kind discriminator — so neither the retry-laundering check nor the "already auto-processed"
  predicate could actually be written. Resolved in C1c: `draft_id` (FK, indexed) + `entry_type`
  (`decision` | `outcome` | `undo`).
- **FAIL 2 — `failed` and `undone` outcome rows had no legal write site.** The two-entry split put
  the outcome row at `sender.py:215`, but that line is only reached on success, and the registry's
  `sender.py` licence is exhaustive at four edits. Resolved in C5: **the DRIVER writes the outcome
  entry after `send_draft` returns** — no fifth `sender.py` edit, no registry change.

**Binding join rule inherited from Phase 1 (Q6).** `Draft.site_id` is `String(50)` referencing
`sites.site_id` — the **slug**, not the UUID PK. The per-site kill switch, the hourly Redis counter
key, and the audit row all carry that slug and join to `sites.site_id` directly, never to `sites.id`.

Context loaded: `process/context/all-context.md` (§Business Guardrails, brand stance),
`process/context/tests/all-tests.md`.

### Goals

1. A real caller for Phase 3a's pure gate — `autonomy_gate(stats, min_outcomes, min_positive_rate)` —
   so AC-11 and AC-12 can be falsified end-to-end.
2. Six rails plus sibling-collision handling and a dwell floor (AC-14 … AC-18, AC-17).
3. The prompt-safety fence on the engage path (AC-19).
4. The guardrail-text amendment across all five carrying surfaces, grep-gated (AC-20).

### Non-goals

Writing `autonomy_gate()` or `select_strategy_from_outcomes()` — **both are Phase 3a deliverables**;
this phase only calls them. Rebuilding `voice_examples`. LinkedIn autonomy (draft-approve-only in
v1). Restructuring the Phase 1 send path — this phase may only widen it additively, within the
registry's licensed edit list.

---

## Entry Gate

**(C9) Mechanical, not prose** — both upstream deliverables must import:

```bash
.venv/bin/python3.11 -c "from apps.api.models.engage_outcome import EngageOutcome; from apps.api.services.engage_track_record import compute_track_record; from apps.api.services.engage_autonomy import autonomy_gate; from apps.api.services.ai_reply import select_strategy_from_outcomes; print('phase 1+2+3a present')"
```

- Phase 1, Phase 2, AND Phase 3a exit gates all met; the command above exits 0.
- **(cycle-5 Gap 4) The Entry Gate command above is the mechanical import-assert for BOTH 3a
  deliverables** — `autonomy_gate` and `select_strategy_from_outcomes`. If either import raises,
  3a has not landed and 3b must not start; do not stub either function locally.
- `engage_outcomes.contact_bidx` exists (added by **Phase 2** item A2b, not Phase 1) — the
  DISTINCT-contact positive-rate depends on it.
- `Draft.site_id` exists as `String(50)` → `sites.site_id` (Phase 1 A1, N1) — every site-keyed rail
  in this phase depends on it.
- Live alembic head re-derived at EXECUTE time, DSN pinned per D-O10.
- Integration infra reachable.

---

## Touchpoints

**Owned exclusively by Phase 3b:**

- `apps/api/services/engage_autonomy.py` — **READ-ONLY here.** Created by Phase 3a; 3b imports
  `autonomy_gate(stats, min_outcomes, min_positive_rate)` and must not modify the module (its
  AST-purity gate is 3a's). 3b is the config reader; 3a reads no config.
- `apps/api/services/engage_autonomous_sender.py` — **NEW (D-O3 / F2 / V1)**, the send driver.
- `apps/api/services/engage_crisis.py` — NEW, deterministic conservative lexicon, fail-closed.
- `apps/api/models/engage_autonomy_audit.py` — NEW append-only audit model.
- `apps/api/services/ai_reply.py` — **`_sanitize_content` composing `clean_text` (AC-19) ONLY.**
  `select_strategy_from_outcomes` and the `determine_draft_mode` wiring are Phase 3a's edits to this
  same file; 3b must not re-touch them. Phase 3a lands first, so this is a sequential edit, not a
  conflict.
- `apps/api/routers/drafts.py` — undo action; the extracted shared sibling-rejection helper; the retry
  fix. `approved` still written ONLY at `:272`.
- `apps/api/schemas/engage_autonomy.py` — NEW response models for the audit read endpoint.
- `process/context/all-context.md` + `README.md` + `apps/web/src/app/llms.txt/route.ts` +
  `apps/web/src/components/page-help.tsx` — AC-20 amendments across all FIVE carrying surfaces
  (D-O6 + cycle-2 Gap 3; the ONLY phase touching them). `docs/*` and `marketing/*` are deliberate
  exclusions covered by the marketing-copy-reconciliation backlog note.
- `apps/api/migrations/versions/<new>_add_engage_autonomy.py` — NEW migration.
- `tests/unit/test_engage_autonomy.py`, `tests/unit/test_engage_prompt_safety.py`,
  `tests/integration/test_engage_autonomous_send.py` — NEW.

**Web surfaces owned by Phase 3b (D-O4 split — Phase 2 owns the track-record surfaces):**

- `apps/web/src/lib/api-types.ts` — widen the closed `DraftStatus` TS union at `:995` (F6/V6).
- `apps/web/src/lib/api.ts` — undo action client method.
- `apps/web/src/components/ui/status-badge.tsx` — add the `auto_approved` key to `STATUS_TONE` (`:15-47`).
- `apps/web/src/components/draft-card.tsx` — `:108` pending-only actions must also render for
  `auto_approved`. (Literal path — no `**/` glob; the earlier glob form made the grep gate unverifiable.)
- `apps/web/src/app/dashboard/drafts/page.tsx` — the hardcoded `TABS` at `:14-20` must surface
  `auto_approved` (this is the real hiding surface, not a Python grep).

**Shared, with binding rules:**

- `apps/api/services/sender.py` — **licensed edits #3 and #4 ONLY** (registry-amended, F7):
  (3) widen the status predicate at `:162` to `{approved, auto_approved}`;
  (4) add the pre-`post_comment` idempotency key + kill-switch/ceiling re-check **and** the
  same-transaction audit-row write alongside `draft.status = DraftStatus.sent` at `:215` before the
  commit at `:216`. May NOT restructure Phase 1's send path.
- `apps/api/models/draft.py` — adds the `auto_approved` value to `DraftStatus` ONLY (Phase 1 owns the
  two columns).
- `apps/api/models/site.py` — adds `engage_autonomy_enabled` ONLY.
- `apps/api/services/platforms/base.py` + `twitter.py` — SHARED (D-O4). Phase 3b adds `delete_comment` as a
  **non-abstract `PlatformService` default raising `NotImplementedError`**, overridden in `TwitterService`
  (C3). An `@abstractmethod` would break all five subclasses.
- `apps/api/jobs/scheduler.py` — SHARED-append-only (D-O3): Phase 3b appends ONLY the
  `engage_autonomous_send` job id, with literal `jitter` + `misfire_grace_time`.
- `tests/unit/test_scheduler_job_config.py` — SHARED: re-derive the inventory counts in the same change.
- `apps/api/main.py` — SHARED-append-only: `# noqa: F401` registration import for the audit model.
- `apps/api/config.py` — appends the `# ─── Engage autonomy (Phase 3b) ───` block only.

---

## Public Contracts

- `DraftStatus` gains `auto_approved` — **a public enum widening across two languages.** Every consumer
  must be audited (C4/F6) so `auto_approved` rows do not vanish from any surface.
- `sender.send_draft(db, draft) -> bool` — signature unchanged; accepted-status set widened.
- `routers/drafts.py` approve endpoint unchanged; human `approved` stays written only at `:272`.
  **(C1)** The retry path at `:361` is corrected: it must restore the draft's PRIOR status class and
  must never convert `auto_approved → approved` (D-O10).
- New additive endpoints: undo a posted reply; read the autonomy audit for a site — both added to
  `routers/drafts.py` (tenant-scoped, named here so no endpoint is homeless — F7/V2).
- `Site` gains ONE new boolean column, default False.
- `PlatformService` gains a non-abstract `delete_comment` default; existing subclasses unmodified.
- `is_emailable_identity()` unchanged — social autonomy never widens email eligibility.
- Guardrail text changes on FIVE surfaces (documented, AC-20): `process/context/all-context.md` (×2 lines),
  `README.md`, `apps/web/src/app/llms.txt/route.ts` (a SERVED public route), and
  `apps/web/src/components/page-help.tsx` (in-product copy).

---

## Blast Radius

- **NEW (9):** 3 services, 1 model, 1 schemas module, 1 migration, 3 test files.
- **EDITED (14):** `services/sender.py`, `services/ai_reply.py`, `routers/drafts.py`,
  `models/draft.py`, `models/site.py`, `services/platforms/base.py`, `services/platforms/twitter.py`,
  `jobs/scheduler.py`, `tests/unit/test_scheduler_job_config.py`, `apps/api/main.py`,
  `apps/api/config.py`, `process/context/all-context.md`, `README.md`, plus 5 web files.
- 1 new table (`engage_autonomy_audit`), 1 new `Site` column, **1 new native-PG enum value**.
- Risk class: **HIGHEST in the program** — outward-facing autonomous public posting, schema migration
  including a first-of-kind `ALTER TYPE … ADD VALUE`, and a cross-language public enum widening. Every
  rail requires a Fully-Automated or Hybrid gate; **no rail may be accepted as a known-gap.**
  **(C2-8) Rail-vs-quality tier split, stated once so it is not re-litigated at EVL:** a rail's
  ROUTING behavior is always Fully-Automated (a crisis-flagged thread routing to the human queue is a
  deterministic assertion); only the crisis DETECTOR's lexicon QUALITY is an Agent-Probe residual. The
  residual is about how well the lexicon classifies, never about whether the rail routes. These two
  statements are consistent, not contradictory.

---

## Implementation Checklist

### Steps A and B — MOVED to Phase 3a

The pure `autonomy_gate()` function and the outcome-driven strategy selector now live in
`phase-3a-learning_PLAN_17-08-26.md`. This phase CONSUMES them and does not reimplement them:
`autonomy_gate(stats, min_outcomes, min_positive_rate)` is imported by the driver (C5);
`select_strategy_from_outcomes` is already wired into `determine_draft_mode` by 3a. If either import
fails, the Entry Gate has not been met — stop, do not re-create the function here.

**(cycle-5 FAIL / cycle-6 Gap 1) The live Step A and Step B checkbox blocks that used to sit directly
below this banner have been DELETED.** They were a split artifact: they still carried the
pre-cycle-5 `autonomy_gate(stats, config)` signature and the two `engage_autonomy_min_*` config keys,
so an execute-agent working 3b would have re-created the function with a signature 3a no longer uses.
A MOVED banner is only true if the moved block is actually gone.


### Step C — The enum, the driver, and the consumer audit

- [ ] C1. Add `auto_approved = "auto_approved"` to `DraftStatus` in `apps/api/models/draft.py`.
- [ ] C1c. **(cycle-3 FAIL 1) `engage_autonomy_audit` schema — queryable by design.** Cycle 2 made this
  table the durable autonomy marker but never gave it the columns the marker role requires. It MUST carry:
  - `draft_id` — FK → `drafts.id`, **indexed** (both marker queries filter on it; without it neither
    C3b's retry check nor C5.1's eligibility predicate is writable at all);
  - `entry_type` — String discriminator constrained to `{decision, outcome, undo}`;
  - `outcome_status` — nullable String `{sent, failed, undone}`, populated on `outcome`/`undo` rows only;
  - plus the decision payload already specified in D5 (`site_id` slug, contact blind index/ciphertext,
    strategy, `sample_n`, `positive_rate`, gate reason, timestamp, posted-reply platform id).
  Append-only: no row is ever updated or deleted.
- [ ] C1b. **(F4/D-O10) Native-PG enum migration — fully specified.** `drafts.status` is a native enum
  (`cd811a8b1f32_baseline_schema.py:459`) and the repo has **zero** prior `ALTER TYPE … ADD VALUE`
  migrations. Therefore:
  - **Its own migration file**, containing ONLY the enum change (no data steps), because on PG12+ a
    newly added value cannot be used in the same transaction that added it.
  - `upgrade()`: `op.execute("ALTER TYPE draftstatus ADD VALUE IF NOT EXISTS 'auto_approved'")` run with
    an autocommit-safe connection (`op.get_bind().execution_options(isolation_level="AUTOCOMMIT")`).
  - `downgrade()`: PostgreSQL has **no `ALTER TYPE … DROP VALUE`**. Strategy = **type-recreate**:
    (1) precondition guard — `SELECT count(*) FROM drafts WHERE status = 'auto_approved'`; if > 0, raise
    with an explicit message (downgrading would destroy live state); (2) if 0, create
    `draftstatus_old` with the five original values, `ALTER TABLE drafts ALTER COLUMN status TYPE
    draftstatus_old USING status::text::draftstatus_old`, drop `draftstatus`, rename. This satisfies the
    up→down→up round-trip on a disposable PG with no `auto_approved` rows present.
  - The other Phase 3b schema objects (audit table, `Site` column) go in a SEPARATE migration chained
    after it.
- [ ] C2. **(sender.py licensed edit #3)** Widen the status check at `sender.py:162` to accept
  `{DraftStatus.approved, DraftStatus.auto_approved}`.
- [ ] C3. `routers/drafts.py:272` remains the SOLE writer of human `approved`. The autonomy path writes
  ONLY `auto_approved`. Structural gate asserts no third writer appears.
- [ ] C3b. **(C1/D-O10 + cycle-2 Gap 1) Fix the retry second-writer — with a real data source.**
  `drafts.py:357-361` writes `DraftStatus.approved` on a failed draft, laundering a failed autonomous
  send into the human lane. The cycle-1 fix said "restore the PRIOR status class" but named no column
  that survives the `sent → failed` transition. **Resolution (orchestrator decision): NO new `Draft`
  column. The `engage_autonomy_audit` table IS the durable marker.** The retry path queries it:
  `EXISTS (SELECT 1 FROM engage_autonomy_audit WHERE draft_id = :id AND entry_type = 'decision')` ⇒ the
  draft was autonomous. **(cycle-3 N2) The retry target status is `pending` — never `approved`, never
  `auto_approved`.** A human clicking retry on a failed autonomous send puts the draft back in the human
  queue for normal re-approval; it does not silently re-authorize an autonomous send (the draft already
  carries an `outcome` row, so C5.1 permanently excludes it from the driver anyway). Gate it (G18).
- [ ] C4. **(F6/V6) The consumer audit — corrected command and real surfaces.** The old
  `grep -rn "DraftStatus\." apps/api apps/web` returns ZERO web hits and cannot fail. Use:
  ```bash
  grep -rn "DraftStatus\|\"approved\"\|'approved'\|\"pending\"\|'pending'" apps/api apps/web/src
  ```
  Then explicitly reconcile these four named web surfaces (each is a checklist item, not a scan result):
  - [ ] C4a. `apps/web/src/lib/api-types.ts:995` — widen the closed union to include `"auto_approved"`.
    Left unwidened, strict mode breaks at `:1043` `status: DraftStatus`.
  - [ ] C4b. `apps/web/src/components/ui/status-badge.tsx:15-47` — add an `auto_approved` key to the
    `STATUS_TONE` map (a missing key silently renders an untoned badge).
  - [ ] C4c. `apps/web/src/components/draft-card.tsx:108` — actions are gated to `pending`;
    `auto_approved` drafts must also render their (undo) action.
  - [ ] C4d. `apps/web/src/app/dashboard/drafts/page.tsx:14-20` — the hardcoded `TABS`
    (Pending/Sent/Failed/Rejected/All) hide `auto_approved` under "All" only. Surface it explicitly.
  - [ ] C4e. Also reconcile the unnamed Python consumers found by the corrected grep: `routers/ai.py:110`,
    `routers/ai.py:145`, `agents/workspace_tools.py:270`, `services/daily_digest.py:317`,
    `services/kpi.py:92`. Record the full consumer list verbatim in the phase report.
- [ ] C5. **(D-O3 / F2 / V1) Create the autonomous-send driver** —
  `apps/api/services/engage_autonomous_sender.py` with `run_engage_autonomous_send(db)`:
  1. Select eligible drafts: `status == pending`, `site_id IS NOT NULL` (Phase 1 A1c fail-closed),
     `platform == twitter`, **older than `engage_autonomy_min_draft_age_minutes`** (C2-5/Gap 8), and
     **not already auto-processed** — the predicate is
     `NOT EXISTS (SELECT 1 FROM engage_autonomy_audit WHERE draft_id = drafts.id AND entry_type = 'outcome')`.
     **(cycle-3 N1) It keys on OUTCOME entries, not any entry** — that distinction is the whole
     re-eligibility rule:
     - A draft reverted by the kill switch (`auto_approved → pending`) has a `decision` row but NO
       `outcome` row, so it **RE-ENTERS** autonomy when the switch is re-enabled. That is intended:
       the switch pauses autonomy, it does not permanently disqualify drafts.
     - A draft with ANY `outcome` entry (`sent`, `failed`, or `undone`) is **permanently excluded**
       from autonomy. A failed autonomous send goes to the human queue, never to an auto-retry loop.
  1b. **(C2-6)** Re-read each draft's status INSIDE the loop before acting on it. A sibling rejected
     earlier in the same pass must not then be processed — SQLAlchemy's identity map makes this work
     within one session, but it must be stated, not assumed. G19 depends on it.
  2. Compute stats via Phase 2's `compute_track_record`, then call the gate with the thresholds passed
     **explicitly from config** (3a holds no config — the driver is the config reader):
     `autonomy_gate(stats, settings.engage_autonomy_min_outcomes, settings.engage_autonomy_min_positive_rate)`.
     **No numeric threshold literal may appear at this call site** — gated by G28.
  3. Evaluate ALL rails (Step D) — any NO leaves the draft `pending` (the human queue) with a logged reason.
  4. All YES → flip `pending → auto_approved`, then call `sender.send_draft(db, draft)`.
  5. Writes the `outcome` audit entry after `send_draft` returns (D5 item 2).
  6. Owns the kill-switch fallback (C6c).
- [ ] C5b. **(cycle-3 FAIL 2) Driver commit boundary — explicit.** Per draft the driver runs TWO
  transactions, in this order: (i) flip `pending → auto_approved` + apply sibling rejections + write the
  `decision` audit row, committed together; then (ii) call `send_draft` (which commits its own
  outcome), then append the `outcome` audit row and commit. The decision row is therefore durable
  before any platform call happens, which is what makes it a marker rather than a receipt.
- [ ] C5b. Register `engage_autonomous_send` in `apps/api/jobs/scheduler.py` append-only, own job id
  only, literal `jitter` + `misfire_grace_time`, advisory-locked with a NEW unique `_LOCK_KEY`,
  short-circuited when either kill switch is OFF. Re-derive
  `tests/unit/test_scheduler_job_config.py` inventory counts in the same change.
- [ ] C6. **(C5/D-O10) Idempotency:** before `post_comment`, take a Redis `SETNX` key on `draft_id` with a
  TTL. A retry must never double-post.
- [ ] C6b. **(D-O5 / V5 / cycle-2 Gap 2) Sibling collision — the defect per-draft idempotency cannot
  catch.** Each post carries 1–3 drafts and `_auto_reject_siblings` (`drafts.py:386`) runs ONLY in the
  human approve endpoint (`drafts.py:276`). The cycle-1 wording ("call it inside the same transaction
  as the flip") is unsatisfiable against the real body: it mutates siblings, calls
  `_save_voice_example` per sibling, and `await db.commit()`s internally (`drafts.py:410`).
  **Resolution: extract a PURE selection helper.**
  - New helper returns the sibling draft IDs only — **no mutation, no `_save_voice_example`, no
    commit, no side effects.**
  - The human approve endpoint keeps its existing behavior **byte-compatible**: it calls the pure
    helper, then applies the same mutations + `_save_voice_example` + commit it does today.
  - The autonomous driver calls the pure helper and applies the rejections in **its OWN transaction**,
    together with the `pending → auto_approved` flip.
- [ ] C6b2. **(cycle-2 Gap 7 / C2-4) Machine-rejected siblings NEVER feed `voice_examples`.**
  `_save_voice_example` (`drafts.py:403`) exists to learn from HUMAN decisions. Routing it from the
  autonomous driver would silently change the signal source `_get_preferred_strategy` reads —
  a learning-loop corruption. The driver's rejection path therefore does NOT call
  `_save_voice_example`. Gate it (G21).
- [ ] C6c. **(C8) Kill-switch fallback — named owner and trigger.** Owner: the driver
  (`engage_autonomous_sender`). Trigger: at the TOP of each job run, if either switch is OFF, flip any
  `auto_approved`-but-not-yet-`sent` drafts back to `pending`. Note `approve_draft` rejects non-`pending`
  drafts (`drafts.py:269`), so this fallback is load-bearing for AC-14. Gated by G7b.

### Step D — The six rails (AC-14 … AC-18)

- [ ] D1. **Dual kill switch** — global `engage_autonomous_send_enabled: bool = False` AND per-site
  `Site.engage_autonomy_enabled` default False. BOTH checked inside the driver's gate call AND
  **re-checked at send time** immediately before `post_comment` (sender.py licensed edit #4) — this
  closes the in-flight race.
- [ ] D2. **Hourly ceiling** — Redis counter keyed `(site_id, hour)`,
  `engage_social_send_hourly_ceiling: int = 20` (stricter than the 50/hr email precedent). Incremented
  BEFORE the platform call. **Fail-CLOSED on any Redis error → queue the draft.**
  **(C2) Flag the inversion explicitly in code comments:** `services/email_rate_limiter.py` fails
  **OPEN** by documented design; this rail deliberately inverts that because the action is public and
  autonomous. An execute-agent copying the precedent would otherwise silently ship fail-open.
- [ ] D3. **Crisis block** — `apps/api/services/engage_crisis.py`, a deterministic conservative lexicon
  over thread text. FAIL-CLOSED: any error or timeout routes to the human queue with a reason. Detector
  *quality* is an Agent-Probe residual; the *routing behavior* is Fully-Automated.
- [ ] D4. **(F3) Suppression — mechanically specified, fail-CLOSED.**
  - Call: `is_email_suppressed_any(db, email, ("do_not_email", "erased"))` (`suppression.py:28`).
  - Join key: `Post.author_username` → `EnrichmentProfile.twitter_handle` (`models/enrichment.py:31`,
    **non-unique**) → the linked visitor's email; decrypt via the parallel `twitter_handle_ciphertext`
    (`:40`) path where needed.
  - Multi-row handle match ⇒ unresolvable ⇒ **fail CLOSED** (no autonomous send).
  - **No email link at all (the majority social case) ⇒ fail CLOSED** — no autonomous send. This reverses
    the prior fail-OPEN wording, which made AC-18 vacuous for most targets.
  - AC-18 is therefore proven for the linked path and **explicitly scoped**: unlinkable contacts are never
    auto-sent to at all, which is a stronger guarantee than the SPEC asked for.
- [ ] D5. **Audit — TWO entries per autonomous draft (cycle-2 Gap 1).** `engage_autonomy_audit` is
  append-only and doubles as the program's durable autonomy marker:
  1. **Decision entry, written at FLIP time** (`pending → auto_approved`) inside the DRIVER's
     transaction: site, contact reference (blind index / ciphertext only), playbook/strategy,
     `sample_n`, `positive_rate`, gate reason, timestamp. This is what makes the marker survive a
     later `sent → failed` transition, which is why C3b and C5.1 can both query it.
  2. **Outcome entry, written by the DRIVER after `send_draft` returns** (cycle-3 FAIL 2):
     `entry_type='outcome'` with `outcome_status` ∈ `{sent, failed}`, plus the posted-reply platform id
     on success. **This is NOT written inside `sender.py`.** `sender.py:215` is reached only on the
     success path, so a `failed` outcome could never be recorded there — and the registry's `sender.py`
     licence is exhaustive at four edits, so a fifth was not available. Writing it in the driver needs
     **no registry change and no fifth `sender.py` edit**: `send_draft` returns a bool and commits on
     every one of its five failure paths (`:175`, `:191`, `:205`, `:236`, `:244`), so the driver can
     always observe the result and append the matching row.
     **Undo entries** (`entry_type='undo'`, `outcome_status='undone'`) are written by the undo endpoint
     in `routers/drafts.py`, exactly as D6 already designs — that path is Phase-3b-owned and needs no
     driver involvement.
- [ ] D5b. **(C2-7) Plaintext email handling — explicit.** D4's suppression check decrypts a contact
  email to compute `email_hash(email)`. That plaintext is **never logged, never persisted, and never
  entered into the audit row**; it exists only as a local for the hash computation and is discarded.
- [ ] D6. **Undo** — **(C3)** add `delete_comment()` to `platforms/base.py` as a **non-abstract default
  raising `NotImplementedError`**, overridden in `TwitterService` (X `DELETE /2/tweets/:id`). The undo
  call site performs a runtime capability check. Add the dashboard undo action and an undo audit entry.
  Live platform-delete is a Hybrid residual (mock-asserted here).
- [ ] D7. Config block — **(cycle-4 3a-C1 transfer) it now carries the two gate thresholds too**:
  `engage_autonomy_min_outcomes: int = 20` and `engage_autonomy_min_positive_rate: float = 0.4`
  (placeholder-conservative, tune-from-observed; 3a deliberately holds no config, and the driver passes
  these into `autonomy_gate()` as explicit arguments). Plus both kill-switch flags,
  `engage_social_send_hourly_ceiling`, and
  **`engage_autonomy_min_draft_age_minutes: int = 30`** (C2-5/Gap 8 — the dwell floor). Without it the
  driver's eligible set is the same queue the human reviews, so a draft could be auto-sent before the
  owner ever sees it. 30 minutes is a placeholder-conservative, tune-from-observed operator value.

### Step E — Prompt-safety fence (AC-19)

- [ ] E1. Route ALL thread-derived / third-party text on the engage path through
  `apps/api/agents/prompt_safety.py` (`clean_text` + `wrap_untrusted`) before it reaches any prompt.
- [ ] E2. Make `ai_reply._sanitize_content` (`:111`) **COMPOSE** `clean_text` — it currently strips
  control chars and role-prefix patterns but NOT `<`/`>` (verified `:111-119`), while
  `prompt_safety.clean_text` does (`prompt_safety.py:51`). Do not delete the existing sanitization.
- [ ] E3. Gate with an injection-shaped fixture asserting the fence is unforgeable.

### Step F — Guardrail text (AC-20, **five** surfaces: D-O6's three + cycle-2 Gap 3's two)

- [ ] F1. `process/context/all-context.md:332` (§What Beam Is) — replace "AI drafts, the human approves
  and sends. Never build auto-send." with the new rule: autonomous sending is permitted ONLY above the
  evidence-anchored threshold of this SPEC, inside its safety rails; everything else remains
  human-approved.
- [ ] F2. `process/context/all-context.md:742` (§Business Guardrails item 1) — amend the unconditional
  "never auto-send" identically. **This is a DIFFERENT string in different case from F1** — editing F1
  alone leaves the rulebook self-contradictory.
- [ ] F3. **(D-O6/V4)** `README.md:3` — "**you approve and send** (never auto-send)" is public-facing and
  also stale. Amend it in the same change.
- [ ] F3b. **(cycle-2 Gap 3) `apps/web/src/app/llms.txt/route.ts:30`** — a SERVED public route that
  currently emits "the AI drafts, the human approves and sends. Beam never auto-sends." After ship this
  route would keep telling every crawler and agent that Beam never auto-sends, while all three cycle-1
  greps passed. Amend it.
- [ ] F3c. **(cycle-2 Gap 3) `apps/web/src/components/page-help.tsx:93`** — in-product copy: "Flow:
  draft → approved → active. Nothing sends without your approval." Amend it.
- [ ] F3d. **Copy direction for all five surfaces** (exact wording chosen at EXECUTE): approval-first
  remains the DEFAULT and the described behavior; autonomous sending is available only after a measured
  track record clears the threshold, inside the safety rails, and the site owner can disable it at any
  time. Do not write copy that implies autonomy is the norm.
- [ ] F3e. **Deliberate exclusions, named.** `docs/*` (e.g. `docs/project-overview-pdr.md`,
  `docs/project-roadmap.md`) and `marketing/*` also carry the stale stance and are **intentionally out
  of scope** for this phase — they are covered by
  `process/features/campaigns-outreach/backlog/marketing-copy-reconciliation_NOTE_17-08-26.md`.
  This is a recorded exclusion, not an oversight.
- [ ] F4. All three edits cite this program's task folder so future agents can find the authorization.
- [ ] F5. **FIVE grep gates at EVL** (three was still a half-gate — cycle-2 Gap 3):
  ```bash
  grep -n  "Never build auto-send" process/context/all-context.md          # expect: no match
  grep -in "never auto-send" process/context/all-context.md                # expect: no match
  grep -in "never auto-send" README.md                                     # expect: no match
  grep -in "never auto-sends" apps/web/src/app/llms.txt/route.ts           # expect: no match
  grep -in "nothing sends without your approval" apps/web/src/components/page-help.tsx  # expect: no match
  ```

### Step G — Tests

**(cycle-6 cross-plan duplicate scan) G1, G4 and G17 were DELETED from this phase.** They test
Phase 3a's pure functions (`autonomy_gate` arithmetic, strategy-selection shift, module purity) and
already live in `phase-3a-learning_PLAN_17-08-26.md`. They were split artifacts of the same class as
the Steps A/B blocks — this plan's own AC table already assigns AC-13 to 3a and states that the
function-boundary purity gates live there. Gate numbering is intentionally non-contiguous as a result;
do not renumber (the contracts reference these ids).

- [ ] G2. `…::test_model_confidence_field_cannot_unlock_autonomy` (AC-11 adversarial) — a fabricated
  "0.99 confident" model output with zero history must queue for approval. **Driven through the C5 driver**,
  not the bare function, so it is a real end-to-end falsifier.
- [ ] G3. `…::test_engage_autonomy_flags_default_off` (AC-14 config defaults).
- [ ] G5. `tests/unit/test_engage_prompt_safety.py::test_engage_prompt_inputs_pass_prompt_safety_fence` (AC-19).
- [ ] G6. `tests/integration/test_engage_autonomous_send.py::test_fresh_site_never_autosends` (AC-12) —
  run the C5 driver against empty history.
- [ ] G7. `…::test_kill_switch_halts_autonomous_sends_immediately` (AC-14) — including the in-flight race:
  flip the switch between the gate call and the send; assert no post.
- [ ] G7b. `…::test_kill_switch_fallback_returns_auto_approved_to_pending` (C8/C6c).
- [ ] G8. `…::test_social_send_ceiling_queues_excess` (AC-15) + a Redis-failure case asserting
  fail-CLOSED queueing.
- [ ] G9. `…::test_crisis_thread_routes_to_human_queue` (AC-16) — non-vacuous neutral-thread control in
  the SAME test + a detector-timeout case asserting fail-closed.
- [ ] G10. `…::test_autonomous_send_audit_record_completeness` + `…::test_undo_deletes_platform_post_and_audits`
  (AC-17) — mock platform delete asserted; audit rows present.
- [ ] G10b. **(cycle-3 N4)** `…::test_failed_send_writes_failed_outcome_audit_entry` — force a
  `send_draft` failure; assert an `entry_type='outcome'`, `outcome_status='failed'` row exists. Without
  this, a success-only audit assertion would never catch the missing failed-send trail.
- [ ] G11. `…::test_suppressed_contact_blocks_autonomous_social_send` (AC-18) — non-vacuous unsuppressed
  control.
- [ ] G11b. `…::test_unlinkable_contact_never_autosends` (F3 fail-closed) — no email link ⇒ no send.
- [ ] G12. `…::test_auto_approved_drafts_visible_in_dashboard_surfaces` — asserts the API response shape.
  **Explicitly marked in-file as NOT proving the rendered surface** (V6): the TS union, `STATUS_TONE`
  map, `draft-card` actions, and drafts-page TABS are covered by G12b instead.
- [ ] G12b. **(F6/V6 + C2-1/C2-2/C2-3) Web-surface gates that CAN fail:**
  (a) `cd apps/web && npm run lint && npm run build`. **(C2-2)** Use `npm run build`, NOT
  `npx tsc --noEmit`: `apps/web/package.json` has no `typecheck` script, a standalone `tsc` run needs
  `.next/types` present, and there is no captured red/green baseline — `build` typechecks in-context
  and would break on the unwidened `DraftStatus` union.
  **(C2-3)** The package manager for this gate is **npm** (`package-lock.json` is the tracked
  lockfile). The `pnpm-lock.yaml` / `pnpm-workspace.yaml` currently in the worktree are ambient and
  NOT program-owned — do not reference them and do not migrate as part of this phase.
  (b) a grep gate asserting `"auto_approved"` appears in ALL FOUR named web files — including
  **`draft-card.tsx`** (C2-1: the cycle-1 grep listed only three, leaving C4c ungated).
  A true rendered assertion is blocked on the Clerk auth harness — that leg is a Hybrid residual with
  a backlog stub.
- [ ] G13. `…::test_idempotency_key_prevents_double_post` (C6).
- [ ] G14. **Flag-ON gates (MANDATORY):** run G6–G13 with `ENGAGE_AUTONOMOUS_SEND_ENABLED=true`,
  `ENGAGE_OUTCOME_LEARNING_ENABLED=true`, and `ENGAGE_SOCIAL_SEND_HOURLY_CEILING` set explicitly, against
  real PG+Redis. **(C5) `Site.engage_autonomy_enabled` is a DB column and CANNOT be set by env — it is
  fixture-set.** Flag-OFF-only evidence is vacuous.
- [ ] G15. Flag-OFF control: with either switch OFF, zero autonomous sends occur and every draft queues.
- [ ] G16. Regression: full unit lane (including re-derived scheduler counts); `voice_examples` behavior
  unchanged; `is_emailable_identity` unchanged; **Phase 1 + Phase 2 + Phase 3a gate suites re-run
  green** — 3a's suites are `tests/unit/test_engage_autonomy.py` and
  `tests/unit/test_engage_strategy_selection.py` (cycle-6 Gap 2: 3a is an upstream dependency of this
  phase, so its gates belong in this regression sweep).
- [ ] G18. **(C1/C3b)** `…::test_retry_of_auto_approved_draft_never_becomes_approved`.
- [ ] G19. **(D-O5/V5)** `…::test_two_sibling_drafts_only_one_posts` — two drafts on one post both pass the
  gate; assert exactly ONE posts and the other is rejected.
- [ ] G20. **(D-O5/V5)** `…::test_pending_sibling_of_auto_sent_draft_is_auto_rejected`.
- [ ] G21. **(cycle-2 Gap 7)** `…::test_machine_rejected_siblings_do_not_feed_voice_examples` — after
  the driver rejects a sibling, assert ZERO new `voice_examples` rows; the human approve path in the
  same test still writes one (non-vacuous control).
- [ ] G22. **(Gap 8/C2-5)** `…::test_draft_younger_than_dwell_floor_is_not_autosent`.
- [ ] G23. **(Gap 1 + cycle-3 FAIL 1)** `…::test_audit_decision_row_written_at_flip_time` — keyed on
  `(draft_id, entry_type='decision')`: the decision entry exists BEFORE `send_draft` is called and
  survives a subsequent `sent → failed` transition.
- [ ] G26. **(cycle-3 N1/G7b)** `…::test_kill_switch_reverted_draft_re_enters_autonomy_when_reenabled`
  — a draft reverted to `pending` by the kill switch (decision row, no outcome row) IS picked up again
  after the switch is re-enabled.
- [ ] G28. **(cycle-5 Gap 2)** `…::test_driver_passes_configured_thresholds_to_gate` — override BOTH
  `engage_autonomy_min_outcomes` and `engage_autonomy_min_positive_rate` to values that flip the
  decision for a fixed outcome history, run the driver, and assert the autonomy outcome flips
  accordingly. Also assert **no numeric threshold literal appears at the driver's `autonomy_gate(...)`
  call site** — otherwise a hardcoded default would satisfy the behavioral half while silently ignoring
  operator config.
- [ ] G27. **(cycle-3 N1)** `…::test_draft_with_outcome_entry_never_re_autosends` — a draft carrying a
  `failed` outcome row is permanently excluded from the driver's eligible set.

---

## Acceptance Criteria

| AC | Criterion | proven by | strategy |
|---|---|---|---|
| AC-11 | Confidence is observed history, never model self-assessment | **G2 + G28 together**: G2 (`test_model_confidence_field_cannot_unlock_autonomy`) drives a fabricated model confidence END-TO-END through the C5 driver and asserts it cannot authorize; G28 proves the decision actually tracks the OPERATOR-configured thresholds rather than a hardcoded literal. Neither alone is sufficient — G2 without G28 leaves "history-driven" unproven against a constant. Function-boundary purity gates (G1, G17) live in Phase 3a. | Fully-Automated |
| AC-12 | Cold start is always human-approved | `test_fresh_site_never_autosends` (G6, flag-ON via G14) | Fully-Automated |
| AC-14 | OFF by default; dual kill switch halts immediately | G3 + G7 + G7b | Fully-Automated |
| AC-15 | Social send-rate ceiling queues excess | G8 incl. Redis-failure fail-closed case | Fully-Automated |
| AC-16 | Never auto-send into negative/crisis threads | G9 (non-vacuous control + timeout case) | Fully-Automated for routing; detector quality Agent-Probe residual |
| AC-17 | Full audit + undo | G10 | Fully-Automated (mock); live platform-delete Hybrid residual |
| AC-18 | Suppression extends to social — **explicitly scoped** to the email-linked path, with unlinkable contacts failing CLOSED (never auto-sent to) | G11 + G11b | Fully-Automated |
| AC-19 | Untrusted text entering prompts is fenced | G5 | Fully-Automated |
| AC-20 | Guardrail text updated in the same change, on **all FIVE** carrying surfaces | the five grep gates in F5 (`all-context.md` ×2, `README.md`, `llms.txt/route.ts`, `page-help.tsx`) | Fully-Automated |

---

## Phase Completion Rules

- 🔨 **CODE DONE** — checklist applied, gates unrun.
- 🧪 **TESTING** — gates running; any red gate keeps the phase here.
- ✅ **VERIFIED** — all 10 AC gates green INCLUDING the flag-ON legs (G14), the sibling gates (G19/G20),
  the retry gate (G18), the purity gate (G17), and the web-surface gates (G12b); both migrations live
  round-tripped on a disposable container (including the enum type-recreate downgrade); the full
  `DraftStatus` consumer list recorded in the phase report; validate-contract recorded; Phase 1+2
  regression green; user confirmed. **No rail may be marked PASS on a known-gap.**
- 🚧 **BLOCKED** — see blockers below.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `test_autonomy_gate_pure_function_of_outcome_history` | Fully-Automated | AC-11 |
| `test_model_confidence_field_cannot_unlock_autonomy` (end-to-end through the driver) | Fully-Automated | AC-11 (with G28) |
| `test_driver_passes_configured_thresholds_to_gate` (both values overridden, decision flips; no literal at the call site) | Fully-Automated | AC-11 (with G2) |
| `test_autonomy_gate_module_is_pure` (AST) | Fully-Automated | AC-11 (C7) |
| `test_fresh_site_never_autosends` (flag-ON) | Fully-Automated | AC-12 |
| `test_approach_selection_shifts_with_outcome_history` | Fully-Automated | AC-13 |
| `test_engage_autonomy_flags_default_off` | Fully-Automated | AC-14 |
| `test_kill_switch_halts_autonomous_sends_immediately` (in-flight race) | Fully-Automated | AC-14 |
| `test_kill_switch_fallback_returns_auto_approved_to_pending` | Fully-Automated | AC-14 (C8) |
| `test_social_send_ceiling_queues_excess` (+ Redis-down fail-closed) | Fully-Automated | AC-15 |
| `test_crisis_thread_routes_to_human_queue` (control + timeout) | Fully-Automated | AC-16 |
| Crisis lexicon quality on a human-reviewed sample set | Agent-Probe | AC-16 residual — backlog stub required |
| `test_autonomous_send_audit_record_completeness` | Fully-Automated | AC-17 |
| `test_undo_deletes_platform_post_and_audits` (mock delete asserted) | Fully-Automated | AC-17 |
| Live X `DELETE /2/tweets/:id` undo | Hybrid (needs-live-provider, double opt-in) | AC-17 residual — backlog stub required |
| `test_suppressed_contact_blocks_autonomous_social_send` | Fully-Automated | AC-18 |
| `test_unlinkable_contact_never_autosends` | Fully-Automated | AC-18 (fail-closed scope) |
| `test_engage_prompt_inputs_pass_prompt_safety_fence` | Fully-Automated | AC-19 |
| FIVE grep gates (all-context :332, all-context :742 case-insensitive, README.md, `apps/web/src/app/llms.txt/route.ts`, `apps/web/src/components/page-help.tsx`) | Fully-Automated | AC-20 |
| `test_two_sibling_drafts_only_one_posts` | Fully-Automated | D-O5/V5 double-post (not a SPEC AC) |
| `test_pending_sibling_of_auto_sent_draft_is_auto_rejected` | Fully-Automated | D-O5/V5 |
| `test_retry_of_auto_approved_draft_never_becomes_approved` | Fully-Automated | C1 second-writer |
| `test_auto_approved_drafts_visible_in_dashboard_surfaces` (API shape only) | Fully-Automated | Enum-consumer risk (partial) |
| `npm run lint` + typecheck + 4-file `auto_approved` grep | Fully-Automated | Enum-consumer risk (web surfaces, V6) |
| Rendered drafts-page/badge/card verification | Hybrid (Clerk auth harness) | Enum-consumer residual — backlog stub required |
| `test_idempotency_key_prevents_double_post` | Fully-Automated | Retry double-post risk |
| Enum migration up→down→up on a **disposable** container (type-recreate downgrade) | Hybrid (needs container) | Schema safety (first-of-kind, high-risk) |
| Second migration (audit table + Site column) up→down→up | Hybrid (needs container) | Schema safety |

### Test Procedure / Post-Phase Testing

**REGENERATED 17-08-26 from the current checklist (cycle-5).** Do not hand-patch this block — if the
checklist changes, regenerate it wholesale. The cycle-4 validator found it had stale-reverted to
`npx tsc --noEmit` and three AC-20 greps, and had dropped `draft-card.tsx`.

```bash
lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'

# Entry gate (mechanical) — Phase 1 + Phase 2 + Phase 3a must all be present
.venv/bin/python3.11 -c "from apps.api.models.engage_outcome import EngageOutcome; from apps.api.services.engage_track_record import compute_track_record; from apps.api.services.engage_autonomy import autonomy_gate; from apps.api.services.ai_reply import select_strategy_from_outcomes; print('phase 1+2+3a present')"

.venv/bin/python3.11 -m pytest tests/unit -m unit -q
# Expected: 0 failed (scheduler inventory counts re-derived from the live file at EXECUTE time)

.venv/bin/python3.11 -m pytest tests/integration/test_engage_autonomous_send.py -q
# Expected: 0 failed

# Flag-ON leg (MANDATORY — the whole phase is vacuous without it).
# NOTE: Site.engage_autonomy_enabled is a DB column and is FIXTURE-set, not env-set (C5).
ENGAGE_AUTONOMOUS_SEND_ENABLED=true \
ENGAGE_OUTCOME_LEARNING_ENABLED=true \
ENGAGE_SOCIAL_SEND_HOURLY_CEILING=20 \
ENGAGE_AUTONOMY_MIN_DRAFT_AGE_MINUTES=30 \
  .venv/bin/python3.11 -m pytest tests/integration/test_engage_autonomous_send.py -q
# Expected: 0 failed AND autonomous sends actually execute against the stub PlatformService

# Program regression: Phase 1 + Phase 2 + Phase 3a suites
.venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py \
  tests/integration/test_engage_memory_privacy.py tests/integration/test_engage_benchmark.py \
  tests/unit/test_engage_autonomy.py tests/unit/test_engage_strategy_selection.py -q
# Expected: 0 failed

.venv/bin/python3.11 -m pytest tests/ -m integration -q
# Expected: no new failures vs baseline

# AC-20 doc gates — ALL FIVE must return no match (D-O6 + cycle-2 Gap 3, Step F5)
grep -n  "Never build auto-send" process/context/all-context.md
grep -in "never auto-send" process/context/all-context.md
grep -in "never auto-send" README.md
grep -in "never auto-sends" apps/web/src/app/llms.txt/route.ts
grep -in "nothing sends without your approval" apps/web/src/components/page-help.tsx

# DraftStatus consumer audit — corrected command (the old `DraftStatus\.` grep returns 0 web hits)
grep -rn "DraftStatus\|\"approved\"\|'approved'\|\"pending\"\|'pending'" apps/api apps/web/src
# Record the full list verbatim in the phase report (E5)

# Web surface gates (V6 + cycle-2 C2-1/C2-2/C2-3)
# npm (package-lock.json is the tracked lockfile). `npm run build` typechecks in-context —
# `npx tsc --noEmit` has no baseline and needs .next/types, so it is NOT the gate.
cd apps/web && npm run lint && npm run build; cd -
grep -rn "auto_approved" \
  apps/web/src/lib/api-types.ts \
  apps/web/src/components/ui/status-badge.tsx \
  apps/web/src/components/draft-card.tsx \
  apps/web/src/app/dashboard/drafts/page.tsx
# Expected: a hit in EACH of the four named files

# Migration round-trip on a DISPOSABLE container (BOTH migrations; enum downgrade is type-recreate)
DOCKER=/Applications/Docker.app/Contents/Resources/bin/docker
$DOCKER run -d --rm --name engage-mig-p3b -e POSTGRES_PASSWORD=pg -p 55435:5432 postgres:16-alpine
export DATABASE_URL='postgresql+asyncpg://postgres:pg@localhost:55435/postgres'
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini downgrade -2
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head
$DOCKER stop engage-mig-p3b
# Expected: clean each direction, with ZERO auto_approved rows present during downgrade
# Read-only head derivation may use the shared dev DSN:
#   postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent
```

---

## Test Infra Improvement Notes

- Platform mocking precedent is a **stub-`PlatformService` monkeypatch**
  (`tests/integration/test_sender_token_refresh.py:86`). There is NO `MOCK_EXTERNAL_APIS` branch in
  `services/platforms/` or `sender.py` (verified: zero hits) — do not invent one (C6).
- Needs a mock X `delete_comment` fixture (new call shape, no precedent).
- Needs a Redis-failure injection helper for the fail-closed ceiling gate; none exists today.
- Crisis-lexicon quality needs a human-reviewed sample set — no crisis-thread fixture corpus exists.
- No Clerk Playwright auth harness — rendered drafts-page/badge/card verification and the undo UI carry
  Hybrid residuals with Fully-Automated backend + lint/typecheck proof.
- `tests/unit/test_scheduler_job_config.py` AST-enforces literal kwargs and hardcoded counts.

---

## Blockers That Would Justify BLOCKED Status

- `sender.py` cannot accept `auto_approved` or host the same-transaction audit write within licensed
  edits #3/#4 without restructuring Phase 1's send path — surface to the orchestrator, do not restructure.
- A `DraftStatus` consumer is found that cannot tolerate a new value without a breaking UI change.
- The enum `downgrade()` type-recreate cannot satisfy up→down→up on a disposable PG.
- Redis is unavailable such that the ceiling cannot be implemented fail-closed.
- `_auto_reject_siblings` cannot be extracted without changing the human approve endpoint's behavior.
- `DATABASE_URL` cannot be pinned away from Supabase PROD (HARD STOP).
- Any rail cannot be gated at Fully-Automated or Hybrid — that is BLOCKED, not CONDITIONAL.

---

## Phase Loop Progress

- [ ] 1. RESEARCH — Phase 1+2 reports read; alembic head re-derived; `DraftStatus` consumers enumerated
- [ ] 2. INNOVATE — approach confirmed against locked D7–D10 + D-O3/D-O5/D-O6/D-O10; Decision Summary written
- [x] 3. PLAN-SUPPLEMENT — PVL cycle 1 supplement applied 17-08-26 (F1–F7, C1–C9, V1, V2, V5, V6); Inner Loop Refresh Note written
- [ ] 4. PVL — vc-validate-agent: full V1–V7; re-run from V1 after this supplement
- [ ] 5. EXECUTE — all checklist items done; per-section gates green
- [ ] 6. EVL — independent vc-tester re-run; follow-up stubs registered
- [ ] 7. UPDATE PROCESS — phase report written; umbrella state updated; commit done

**Validate-contract required before execute.**

---

## Exit Gate

- All 10 AC gates green including the flag-ON legs.
- All six rails gated; none accepted as a known-gap. Sibling, retry, purity, and web-surface gates green.
- `DraftStatus` consumer list (corrected grep) recorded verbatim in the phase report.
- Both migrations live round-tripped on a disposable container, including the enum type-recreate downgrade.
- All **FIVE** AC-20 grep gates return no match.
- Phase 1 + Phase 2 suites re-run green (program regression).
- Phase report written. **Flipping any `engage_*` flag ON in a real environment remains a separate
  operator action outside this phase.**

---

## Execute Anchor

This file IS the primary execute anchor for its phase — pass this exact path to vc-execute-agent.
Supporting phase files (read-only context, never the execute target): the umbrella plan, the sibling
phase plans, and the locked SPEC in this task folder.

---

## Resume and Execution Handoff

1. Selected plan file path: `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/phase-3-learning-autonomy_PLAN_17-08-26.md`
2. Last completed phase or step: PVL cycle 1 supplement applied 17-08-26; awaiting PVL re-run from V1. Depends on Phase 1 + Phase 2 exits.
3. Validate-contract status: written (BLOCKED, cycle 1) — must be re-run from V1 after this supplement.
4. Supporting context files loaded: `process/context/all-context.md`, `process/context/tests/all-tests.md`, the SPEC, the umbrella plan, Phase 1 and Phase 2 plans.
5. Next step for a fresh agent: re-spawn vc-validate-agent from V1 against this amended plan.

---

## Next Step

Re-run PVL from V1 (`ENTER VALIDATE MODE`). Never ENTER EXECUTE MODE while the contract verdict below
reads BLOCKED.

---

## Validate Contract

Status: CONDITIONAL
Date: 17-08-26
date: 2026-08-17
generated-by: outer-pvl
supersedes: 2026-08-17 (outer-pvl, PVL cycle 5) — cycle-5 FAILs 3b-2/3b-3 and CONCERNs 3b-C3…3b-C5 re-derived against the files and real source; ALL FIVE CLOSED. Two new minor CONCERNs, no FAILs.

Parallel strategy: sequential (no Agent tool in this environment — Layer 1 dimensions and Layer 2 sections executed sequentially in-agent against real source)
Rationale: signal score 6/7 (S1, S2, S4, S5, S6, S7). Dominant signal: S6 — outward-facing autonomous public posting plus a first-of-kind native-PG-enum migration.

### Net Gate Derivation

| Layer 1 dimension | Status |
|---|---|
| Infra fit | PASS |
| Test coverage | CONCERN |
| Breaking changes | PASS |
| Security surface | PASS |

| Layer 2 section | Status |
|---|---|
| Steps A/B — MOVED to 3a | PASS |
| Step C — enum, driver, consumer audit | PASS |
| Step D — the six rails | PASS |
| Step E — prompt-safety fence | PASS |
| Step F — guardrail text | PASS |
| Step G — tests | CONCERN |

**Totals: 0 FAILs / 2 CONCERNs / 8 PASSes → Net Gate: CONDITIONAL**

Trajectory across the lineage: 7 FAILs → 3 → 2 → 1 → 2 → **0**. Both remaining CONCERNs are one-line additions to existing commands; neither leaves a developed behavior ungated.

---

### Cycle-5 closures — RE-DERIVED

| Cycle-5 finding | Verdict | Evidence re-checked this cycle |
|---|---|---|
| **FAIL 3b-2** — duplicated Steps A/B survived under the MOVED banner | **CLOSED** | A mechanical scan of the plan body for live `- [ ] A#` / `- [ ] B#` checkboxes returns an **empty list**. The banner is followed only by a why-note recording the deletion: "The live Step A and Step B checkbox blocks that used to sit directly below this banner have been DELETED … A MOVED banner is only true if the moved block is actually gone." The banner itself now quotes the NEW signature. The single `autonomy_gate(stats, config)` string left in the file is inside that why-note — descriptive, not prescriptive. |
| **FAIL 3b-3** — driver never passed config; no gate | **CLOSED, both halves** | C5 `:340` now reads `autonomy_gate(stats, settings.engage_autonomy_min_outcomes, settings.engage_autonomy_min_positive_rate)`, with `:341` adding "**No numeric threshold literal may appear at this call site** — gated by G28". G28 `:550` (`test_driver_passes_configured_thresholds_to_gate`) overrides BOTH values and asserts the decision flips. This is the cheapest falsifier for the hardcode failure mode and it now exists. |
| **3b-C3** — no mechanical entry check for the 3a dependency | **CLOSED (partially — see 3b-C6)** | Entry Gate `:137` and Test Procedure `:633` both run `.venv/bin/python3.11 -c "from apps.api.models.engage_outcome import EngageOutcome; from apps.api.services.engage_track_record import compute_track_record; from apps.api.services.engage_autonomy import autonomy_gate; print('phase 1+2+3a present')"`. The load-bearing import (`autonomy_gate`) is asserted. |
| **3b-C4** — umbrella listed `engage_autonomy.py` under 3b | **CLOSED** | Umbrella `:305` lists it under 3a; `:317` records "**READ-ONLY in 3b** (created by 3a; 3b imports it)". |
| **3b-C5** — AC-11 chain had a hole | **CLOSED, and well-argued** | AC-11 row `:565`: "**G2 + G28 together**: G2 drives a fabricated model confidence END-TO-END through the C5 driver and asserts it cannot authorize; G28 proves the decision actually tracks the OPERATOR-configured thresholds rather than a hardcoded literal. **Neither alone is sufficient — G2 without G28 leaves 'history-driven' unproven against a constant.** Function-boundary purity gates (G1, G17) live in Phase 3a." That is the correct reading of SPEC AC-11's "operator-configurable N and R". |

**Deliberate, not flagged (per orchestrator instruction, verified as stated):** 3b's gate numbering is non-contiguous — `G1`, `G4` and `G17` are absent because they are 3a's function-boundary gates, and the AC table has always located them there. The do-not-renumber note is present at `:488-489` ("Gate numbering is intentionally non-contiguous as a result; do not renumber (the contracts reference these ids)"). Confirmed correct; not a finding.

---

### CONCERNs (cycle 6 — both newly derived, both one-line fixes)

| # | Finding | Severity | Proposed fix |
|---|---|---|---|
| 3b-C6 | **The Entry Gate import-assert covers one of the two symbols its own banner names.** The MOVED banner says "If **either** import fails, the Entry Gate has not been met — stop." The command asserts `EngageOutcome`, `compute_track_record` and `autonomy_gate`, but **not `select_strategy_from_outcomes`**. That second symbol is 3a's `ai_reply.py` edit, and the umbrella's SHARED-SEQUENTIAL rule makes "3a lands first" load-bearing for that exact file — 3b's Step E then edits `_sanitize_content` in it. As written, 3b could begin editing `ai_reply.py` before 3a has, and nothing would detect the ordering violation. This is the same prose-vs-command shape as cycle 5's stale Test Procedure, inverted: the prose is broader than the check. | CONCERN | Append `from apps.api.services.ai_reply import select_strategy_from_outcomes;` to the Entry Gate and Test Procedure commands. |
| 3b-C7 | **G16's regression sweep omits 3a.** G16 `:534-535` reads "full unit lane (including re-derived scheduler counts); `voice_examples` behavior unchanged; `is_emailable_identity` unchanged; **Phase 1 + Phase 2** gate suites re-run green." 3b now depends on 3a and edits `ai_reply.py` *after* 3a does, so a 3b `_sanitize_content` change could break 3a's selector tests with no named gate catching it. (Checked as instructed: the `voice_examples` and scheduler-count items are **correctly** scoped to 3b — 3b touches `jobs/scheduler.py` via C5b, and C6b2/G21 make `voice_examples` behaviourally in-scope through the sibling helper. No trim needed; the omission is 3a.) | CONCERN | Change to "Phase 1 + Phase 2 + Phase 3a gate suites re-run green" and name 3a's two unit files. |

---

### PASSes (verified against real source)

- **Step C — enum, driver, consumer audit: PASS.** `C1c` specifies the audit table as `draft_id` (FK → `drafts.id`, **indexed**), `entry_type` ∈ `{decision, outcome, undo}`, `outcome_status` nullable ∈ `{sent, failed, undone}`, plus the decision payload, append-only. Every query that references the table is specifiable: C3b's retry check, C5.1's eligibility predicate, G23's `(draft_id, entry_type='decision')`, G10b's `(entry_type='outcome', outcome_status='failed')`.
- **Config keys land only where they belong.** `engage_autonomy_min_*` appears exactly twice in the plan body outside explanatory text: `:340` (the driver call site, `settings.`-prefixed) and `:429` (3b's own config block). 3a adds neither.
- **Step D — the six rails: PASS.** Dual kill switch with send-time re-check; fail-CLOSED Redis ceiling with the `email_rate_limiter.py` fail-OPEN inversion called out; fail-CLOSED crisis routing; fail-CLOSED suppression on both the multi-row and no-link branches; two-entry audit with the driver writing the outcome row after `send_draft` returns (premise re-verified: all five failure paths `:175/:191/:205/:236/:244` commit and the function returns a bool); undo via a non-abstract `PlatformService.delete_comment` default; 30-minute dwell floor in both the C5.1 predicate and the D7 config block.
- **Step E — prompt fence: PASS.** `_sanitize_content` (`ai_reply.py:111-119`) still does not strip `<`/`>`; `prompt_safety.clean_text` (`:51`) does. Compose-don't-delete intact, with the umbrella's no-reformat clause protecting the shared file.
- **Step F — guardrail text: PASS.** Five surfaces, five greps, consistent across Overview, Goals, F3d, the AC row, the Test Procedure and the Exit Gate. All five were verified in cycle 4 to match today, so all five can fail.
- **Re-eligibility still correct in both directions.** C5.1 keys on `entry_type='outcome'`: rails-NO → no decision row → still eligible; flip-then-kill-switch-revert → decision row but no outcome row → **RE-ENTERS**; `sent`/`failed`/`undone` → excluded. Undo does not reopen eligibility because the original send's outcome row persists. Gated by G26/G27.
- **Cross-plan duplicate scan (new dimension) clean.** Only `G16` is shared between the plans (deliberate per-phase regression sweep). Shared source files `config.py`, `ai_reply.py`, `engage_autonomy.py` are each governed by an explicit umbrella rule.
- **Structural validator:** 0 failures, 0 warnings. **No duplicate headings. No stale "Phase 3" references.**
- **Infra available now:** PG:5433 and Redis:6379 LISTENing; `.venv/bin/python3.11` resolves.

---

### Test gates (C3 5-column) — deltas from cycle 5 only

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-11 | Fabricated model confidence cannot unlock autonomy, AND the decision tracks operator-configured thresholds | Fully-Automated | **G2 + G28 jointly**: `…::test_model_confidence_field_cannot_unlock_autonomy` (end-to-end through the C5 driver) and `…::test_driver_passes_configured_thresholds_to_gate` (override both config values → decision flips; no numeric literal at the call site) | B — cycle-5 FAIL closed |
| Ordering | 3a deliverables exist before Step C begins | Fully-Automated | `.venv/bin/python3.11 -c "from apps.api.models.engage_outcome import EngageOutcome; from apps.api.services.engage_track_record import compute_track_record; from apps.api.services.engage_autonomy import autonomy_gate; print('phase 1+2+3a present')"` | B — covers `autonomy_gate`; misses `select_strategy_from_outcomes` (3b-C6) |
| Regression | Unit lane + Phase 1/2 suites + full integration lane | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -m unit -q`; `.venv/bin/python3.11 -m pytest tests/ -m integration -q` | A — 3a's suite not yet named (3b-C7) |
| — | All other gates (AC-12, AC-14 incl. re-eligibility G26/G27, AC-15, AC-16, AC-17 incl. G10b failed-send audit and G23 decision-row, AC-18 incl. unlinkable, AC-19, AC-20 five greps, V5 sibling pair G19/G20, G21 voice-example isolation, G22 dwell floor, G13 idempotency, G12b web surfaces via `npm run build` + 4-file grep, both migrations on a disposable container) | as recorded in the cycle-4/5 contracts | unchanged and verified present | B |

gap-resolution legend: A — proven now; B — fixed in this plan; C — deferred to a named later phase; D — backlog stub.

**Recorded deviation — AC-18 is deliberately stricter than the SPEC.** D4 fails CLOSED for both the multi-row-handle case and the no-email-link case, so unlinkable contacts are never auto-sent to at all. Intentional; must not be "corrected" back at EXECUTE.

---

### Dimension findings

- Infra fit: PASS — driver, scheduler job, advisory lock, slug site key, both migrations, disposable-container path and the audit schema all check out against real files.
- Test coverage: CONCERN — every AC now has a real, passable, non-vacuous gate, and AC-11's joint G2+G28 framing closes the last logical hole. The two residual issues are scope omissions in the entry check and the regression sweep, not missing coverage of any behavior.
- Breaking changes: PASS — enum widening, all four web surfaces and the five Python consumers are owned, line-anchored and gated; the retry second-writer is closed; `sender.py` stays within its four licensed edits (the outcome row is driver-written, so no fifth edit).
- Security surface: PASS — the audit trail is queryable and complete in both directions; the five-surface guardrail amendment leaves no public claim contradicting the shipped behavior; suppression, crisis and ceiling all fail closed; plaintext email is never logged, persisted or audited (D5b).
- Steps A/B (MOVED), C, D, E, F: PASS. Step G: CONCERN.

---

### Proposed plan updates (NOT applied — this agent's write scope is this section only)

| # | What changes | Where in plan | Why |
|---|---|---|---|
| P1 | Append `from apps.api.services.ai_reply import select_strategy_from_outcomes;` to the Entry Gate and Test Procedure import-assert | Entry Gate `:137`, Test Procedure `:633` | 3b-C6 |
| P2 | Change G16's sweep to "Phase 1 + Phase 2 + Phase 3a gate suites re-run green" and name 3a's two unit files | G16 `:534` | 3b-C7 |

### Execute-agent instructions

| # | Instruction | Trigger condition |
|---|---|---|
| E1 | Do NOT create `engage_autonomy.py` or edit the `ai_reply.py` selector region — both are 3a deliverables. If the entry import fails, STOP; 3a has not landed. | Checklist entry |
| E2 | The driver passes operator config into `autonomy_gate` as explicit arguments. Never hardcode threshold literals at the call site (G28 asserts this). | C5 entry |
| E3 | Re-derive the live alembic head with `DATABASE_URL` pinned to a local/disposable DSN before writing either migration. Never run alembic with repo `.env` loaded — it points at Supabase PROD. | Migration entry |
| E4 | The enum migration file contains ONLY the `ALTER TYPE`. No data step, no other DDL, no use of the new value in the same transaction. | C1b entry |
| E5 | `sender.py` gets licensed edits #3 and #4 only. Do NOT write the outcome audit row inside `sender.py` — the driver owns it. A fifth edit is a BLOCKED condition to surface. | Step C/D entry |
| E6 | `routers/drafts.py:272` stays the only writer of human `approved`. | C3b entry |
| E7 | The extracted sibling helper returns IDs only — no mutation, no `_save_voice_example`, no commit. | C6b entry |
| E8 | In `ai_reply.py`, edit ONLY `_sanitize_content` (`:111-119`). Do not reformat, reorder or re-indent; import additions are append-only. | Step E entry |
| E9 | Record the full corrected-grep `DraftStatus` consumer list verbatim in the phase report, including all five Python consumers in C4e. | Before marking Step C done |
| E10 | Re-derive `tests/unit/test_scheduler_job_config.py` inventory counts in the same commit as the scheduler append. | C5b entry |
| E11 | Every rail lands with its gate in the same change. No rail may be marked done on a known-gap. | Step D entry |
| E12 | Do not renumber gates. The non-contiguous ids (`G1`/`G4`/`G17` absent) are deliberate and are referenced by these contracts. | Step G entry |

### Backlog artifacts required

| Artifact | Location | What it tracks |
|---|---|---|
| `engage-crisis-lexicon-sample-set_NOTE_17-08-26.md` | `process/features/campaigns-outreach/backlog/` | AC-16 Agent-Probe residual — human-reviewed crisis-thread corpus |
| `engage-undo-live-platform-delete_NOTE_17-08-26.md` | `process/features/campaigns-outreach/backlog/` | AC-17 Hybrid residual — live X `DELETE /2/tweets/:id`, double opt-in |
| `engage-autonomy-web-render-harness_NOTE_17-08-26.md` | `process/features/campaigns-outreach/backlog/` | Rendered drafts-page / badge / card / undo verification, blocked on the Clerk Playwright auth harness |

---

Open gaps: CONCERNs 3b-C6 and 3b-C7 only. No FAILs.

Known gaps (accepted postures — named residuals with written justification, excluded from the FAIL/CONCERN count):
- Live X platform-delete undo — Hybrid, needs-live-provider, double opt-in required. Mock-asserted here.
- Crisis-detector lexicon quality — Agent-Probe; no crisis-thread fixture corpus exists in-repo. The rail's *routing* is Fully-Automated; only detector quality is the residual.
- `N=20` / `R=0.4` / `ceiling=20` / `dwell=30` — placeholder-conservative, tune-from-observed operator values, not gates. G28 proves the configured values are the ones applied, whatever they are set to.
- DISTINCT-contact positive-rate counting — Phase-2-dependent (`engage_outcomes.contact_bidx`, Phase 2 item A2b).
- Rendered web-surface verification — Hybrid residual, blocked on the Clerk Playwright auth harness; backend + `npm run build` + 4-file grep cover the rest.
- Phases 1, 2 and 3a deliverables are not on disk yet; entry-gate commands are expected to fail until they land.

Every developed behavior in this phase carries a Fully-Automated or Hybrid gate, so this CONDITIONAL is not vacuously green — the residuals above are named, justified and backed by backlog stubs.

What this coverage does NOT prove:
- The Python lanes prove backend behavior only. `npm run lint` + `npm run build` prove the TS union compiles and the literals are present; no gate proves a rendered `auto_approved` badge, tab or card action.
- The flag-ON integration legs run against a stub `PlatformService`. They prove nothing about real X API semantics, rate limits, error codes, or whether a real post was created or deleted.
- The disposable-container round-trip proves both migrations apply and reverse on an empty PG **with zero `auto_approved` rows present**. Production downgrade after any autonomous send is effectively one-way by design.
- The five AC-20 greps prove exact strings are absent from five named files. They do not prove the replacement copy is coherent, and they deliberately exclude `docs/*` and `marketing/*`.
- AC-18 is proven only for the email-linked path; unlinkable contacts are proven excluded from autonomy entirely — a stronger, different guarantee than "suppression was checked".
- G23 and G10b together prove the audit trail survives one failure; they do not exhaustively cover all five `send_draft` failure paths.
- G28 proves the driver passes the configured values at the call site it tests. It does not prove every future call site will.
- The re-eligibility gates prove the revert-and-re-enter cycle once; they do not prove behavior under repeated toggling or concurrent job runs.
- The entry import-assert proves 3a's service module landed; it does not currently prove 3a's `ai_reply.py` edit landed (3b-C6).
- PG:5433 and Redis:6379 were confirmed LISTENing at validate time (17-08-26). That is not a CI-runnability guarantee.

Gate: CONDITIONAL (0 FAILs; 2 CONCERNs — Entry Gate import-assert incomplete, G16 regression sweep omits 3a)
Accepted by: not accepted by this agent — vc-validate-agent does not self-accept its own CONDITIONAL. Routing note for the orchestrator: five recorded PVL fix cycles precede this verdict, so a CONDITIONAL acceptance here is a legal EXECUTE gate under the ≥1-cycle rule; the two CONCERNs are one-line additions that could equally be folded into a cycle-7 supplement first.
