---
name: plan:engage-learning-agent-phase-1-signal-acquisition
description: "Engage Learning Agent — Phase 1: signal acquisition (persist comment_id + site_id, engage_outcomes, reply-back sweep, metrics poller, server-side attribution mint, ingest attribution wiring)"
date: 17-08-26
feature: campaigns-outreach
metadata:
  node_type: memory
  type: plan
  feature: campaigns-outreach
  phase: phase-1
---

# Phase 1 — Signal Acquisition

**Date**: 17-08-26
**Complexity**: COMPLEX
**Status**: ⏳ PLANNED
**Program:** engage-learning-agent
**Umbrella plan:** `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/engage-learning-agent-umbrella_PLAN_17-08-26.md`
**Report destination:** `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/phase-1-signal-acquisition_REPORT_17-08-26.md`
**Covers SPEC ACs:** AC-1, AC-2, AC-3, AC-4
**Supplement revision:** PVL cycle 3 supplement applied 17-08-26 — closes P1/P3 (stale cross-refs) and Q1–Q7. Prior: cycle 2 supplement applied 17-08-26 — closes N1–N6 (FAIL) and K1–K8 (CONCERN). Cycle-1 closures (G1–G7, C1–C12, V3, V7) were independently re-derived and confirmed genuine by the cycle-2 validator.

**TL;DR:** Stop throwing away the platform id of every reply Beam posts, give each draft a resolvable
site key, then measure what that reply achieved — reply-backs, public metrics, and attributed site
visits — into one append-only, de-duplicated `engage_outcomes` table. Nothing here changes who can send.

---

## Inner Loop Refresh Note

**17-08-26 — PVL cycle 3 supplement (BLOCKED → supplement).** Sections amended: Step B3, Step C4,
Step D3, Step E6, Steps A3b/E4 (partial-index inference), Verification Evidence, Phase Loop Progress.
Drivers: validator FAILs **P1** (a `contact_bidx` orphan instruction survived in D3 after the column
was removed — an execute-agent would have written to a nonexistent column) and **P3** (E6 told the
execute-agent to set a boot offset, the exact thing the K1 fix forbids); CONCERNs Q1 (partial-index
`ON CONFLICT` needs `index_where`), Q2 (hardcoded scheduler arithmetic replaced by re-derive-only),
Q3 (config key list incomplete), Q4 (gate label), Q5 (audit-trail staleness), Q6 (slug rule invisible
downstream), Q7 (which side of the `_process_signal_events` convention the attribution loop belongs on).
Note: the umbrella-side FAIL **P2** (contradictory `routers/drafts.py` registry rows) is fixed in the
umbrella, not here.

**17-08-26 — PVL cycle 2 supplement (superseded above, retained for audit).** Sections amended: Overview, Touchpoints,
Public Contracts, Blast Radius, Implementation Checklist (Steps A, C, E, F), Verification Evidence,
Test Procedure, Test Infra Improvement Notes, Blockers, Exit Gate. Drivers: validator FAILs N1
(`site_id` type contradiction), N2 (second draft producer out of scope), N3 (ingest anchor
mechanically impossible), N4 (metrics key vs cadence contradiction), N5/N6 (`contact_bidx` circular
phase dependency + un-erasable PII), CONCERNs K1–K8, and orchestrator decisions N1/N2/N3/N4/N5/N6 +
K1/K3/K5/K8.

**17-08-26 — PVL cycle 1 supplement (superseded above, retained for audit).** Closed validator FAILs
G1–G7, CONCERNs C1–C12, and adversarial findings V3, V7 under orchestrator decisions D-O1, D-O2,
D-O3, D-O4, D-O8, D-O9, D-O10. The cycle-2 validator re-derived every one of those closures against
real source and confirmed them genuine.

---

## Overview / Context and Goals

Today `apps/api/services/sender.py:212` receives the platform `comment_id` from `post_comment()` and
uses it only in a log line. Nothing about a posted reply is measurable afterwards. There is no social
webhook anywhere in the repo (`routers/webhooks.py` is SendGrid + Leadpipe only), so all capture must
be poll/sweep-based.

Two facts discovered at PVL cycle 1 reshape this phase:

1. **There is no draft→site mapping anywhere in the repo.** `Draft` has `user_id`, `post_id`, and a
   nullable `visitor_id` string, but no site column; `Post` keys off `social_account_id`;
   `SocialAccount` keys off `user_id`; and one user may own many sites. Every site-keyed rail in this
   program (attribution, outcome aggregates, the Phase 3b per-site kill switch and hourly ceiling)
   therefore has no key. Orchestrator decision **D-O1** resolves this: Phase 1 adds a nullable
   `Draft.site_id` FK with a defined derivation and a FAIL-CLOSED posture on NULL.
1b. **`contact_bidx` moved to Phase 2 (N5/N6).** The cycle-1 supplement put a blind-index column
   on `engage_outcomes` while the `blind_index()` helper and the whole erasure machinery
   (`ERASURE_TARGETS`, `graph_erasure.py`) are Phase-2-owned — a circular phase dependency AND a
   PII-derived column with no erasure path, violating the umbrella's own hard constraint that
   per-contact data is registered for erasure in the phase that creates it. Phase 1 now ships
   `engage_outcomes` **without** `contact_bidx`; Phase 2 adds the helper, the column, its migration,
   and its `ERASURE_TARGETS` registration together.
2. **`EngagementAttribution` is dead in both directions.** `EngagementTracker.attribute_visitor`
   (`engagement_tracker.py:81`) has zero callers repo-wide, and `ai_reply.py:331-368` never passes
   `Site.url` into the prompt, so a generated reply essentially never contains a site-owned link.
   Minting a tag on content that has no link produces nothing. Orchestrator decision **D-O2** re-scopes
   AC-4 to the link-present path and adds the missing ingest-side producer.

Context loaded: `process/context/all-context.md` (§Business Guardrails, §Key Patterns, migration head
notes) and `process/context/tests/all-tests.md` (runner selection, Docker/port detection, alembic
offline gotcha).

### Goals

1. Persist the platform id of every posted reply, plus a resolvable `Draft.site_id` (AC-1, D-O1).
2. Detect reply-backs via a dedicated, de-duplicated correlation sweep (AC-2, D-O9).
3. Record public metrics on Beam's own replies via a batched, age-tiered poller (AC-3).
4. Mint the attribution tag server-side when — and only when — the approved content already contains
   a site-owned link, and wire the ingest-side producer that turns a tagged visit into an
   `attributed_visit` outcome row (AC-4, D-O2).

### Non-goals

Memory tables, cross-tenant sharing, strategy learning, and anything autonomous. This phase adds NO
new send-authorization path and NO auto-appending of links to human-approved content.

---

## Entry Gate

- Umbrella Phase 0 complete (all 4 plan artifacts validator-clean).
- Live alembic head re-derived at EXECUTE time with the DSN pinned local (D-O10):
  `DATABASE_URL='postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent' .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads`
- Integration lane infra reachable: `lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'` shows both.
- Baseline recorded: the current integration-lane pass count, and the scheduler inventory counts. **(Q2)** Re-derive the inventory counts from the live `tests/unit/test_scheduler_job_config.py` at EXECUTE time and update them to the re-derived values; never trust the numbers written in this plan. Never relax the assertion.

---

## Touchpoints

**Owned exclusively by Phase 1:**

- `apps/api/services/sender.py` — Phase 1 owns the send-path structure. **Licensed edits #1 and #2**
  of the registry's exhaustive four (comment_id persist; attribution mint).
- `apps/api/models/draft.py` — adds `platform_comment_id` AND `site_id` columns (D-O1 registry
  amendment). Does NOT touch `DraftStatus` (Phase 3b owns the enum value).
- `apps/api/models/engage_outcome.py` — NEW append-only outcome model.
- `apps/api/services/engage_outcome_sweep.py` — NEW reply-back correlation sweep.
- `apps/api/services/engage_metrics_poll.py` — NEW batched age-tiered metrics poller.
- `apps/api/services/engagement_tracker.py` — attribution row write + `attributed_visit` producer.
- `apps/api/services/auto_drafter.py` — sets `Draft.site_id` at draft creation (D-O1 derivation).
- `apps/api/routers/events.py` — ingest-side wiring AFTER the commit at `:474`: distinct `beam_`
  `utm_source` → `attribute_visitor` → `attributed_visit` outcome row (G3, G7, N3).
- `apps/api/migrations/versions/<new>_add_engage_outcomes.py` — NEW migration.
- `tests/unit/test_engage_outcome_model.py`, `tests/integration/test_engage_signal_acquisition.py` — NEW.

**Shared, with binding rules:**

- `apps/api/jobs/scheduler.py` — SHARED-append-only across all 3 phases (D-O3). Phase 1 appends its
  own two job ids only; it does not touch other phases' registrations.
- `tests/unit/test_scheduler_job_config.py` — SHARED. **(Q2)** Re-derive the inventory counts from the live `tests/unit/test_scheduler_job_config.py` at EXECUTE time and update them to the re-derived values; never trust the numbers written in this plan. Never relax the assertion.
- `apps/api/services/platforms/base.py` + `twitter.py` — SHARED (D-O4). Phase 1 ADDS the metrics /
  mentions / `referenced_tweets` reads as non-abstract `PlatformService` defaults overridden in
  `TwitterService`. Phase 1 does NOT modify `post_comment`; Phase 3b adds `delete_comment`.
- `apps/api/main.py` — SHARED-append-only. Phase 1 adds the `# noqa: F401` model-registration import
  for `EngageOutcome` (the integration lane's only table-registration mechanism, `tests/conftest.py:123`).
- `apps/api/routers/drafts.py` — **(N2) SHARED with Phase 3b.** Phase 1 holds exactly ONE licensed
  edit: set `Draft.site_id` at the manual-draft construction (`drafts.py:199`). Phase 1 touches
  nothing else in this file; Phase 3b owns the undo action, the autonomy-audit read endpoint, the sibling helper,
  and the retry fix.
- `apps/api/config.py` — appends the `# ─── Engage outcome capture (Phase 1) ───` block only.

---

## Public Contracts

- `sender.send_draft(db, draft) -> bool` — signature and return semantics UNCHANGED.
- `DraftStatus` — UNCHANGED in this phase.
- **CHANGED (declared, C7):** the posted text may differ from the human-approved text when a
  site-owned link is rewritten with a utm tag. This is a real contract change, is logged with an
  explicit `attribution_link_rewritten` event, and is bounded by the length rule in C5 below. Content
  is NEVER otherwise mutated and links are NEVER appended (D-O2).
- `Draft` API/response schemas — `platform_comment_id` and `site_id` are internal. Do NOT add either to
  a response schema in this phase (E8 / the `VisitorOut` P0 lesson).
- `PlatformService` — gains non-abstract default read methods that raise `NotImplementedError`.
  Existing subclasses keep working unmodified (E6).
- New internal contract: `record_outcome(db, draft_id, site_id, outcome_type, platform_ref, counts, observed_at)`
  in `engage_outcome` writes append-only rows and NEVER accepts a text/body argument.

---

## Blast Radius

Real file count (C9 correction — the earlier "5 existing files" undercount is retired):

- **NEW (7):** `models/engage_outcome.py`, `services/engage_outcome_sweep.py`,
  `services/engage_metrics_poll.py`, 1 migration, 2 test files, 1 backlog note.
- **EDITED (12):** `services/sender.py`, `models/draft.py`, `services/engagement_tracker.py`,
  `services/auto_drafter.py`, `routers/drafts.py` (N2 — ONE licensed edit: set `site_id`),
  `routers/events.py`, `jobs/scheduler.py`, `tests/unit/test_scheduler_job_config.py`,
  `services/platforms/base.py`, `services/platforms/twitter.py`, `apps/api/main.py`,
  `apps/api/config.py`. (K3: the header count now matches the enumerated list.)
- 1 new table (`engage_outcomes`, WITHOUT `contact_bidx` — deferred to Phase 2 per N5/N6);
  2 new nullable `drafts` columns; 2 new APScheduler interval jobs.
- Risk class: **schema/data migration** (Hybrid minimum) + **outward-facing read calls to the X API**
  (rate-limit surface) + **posted-content mutation** (C7). No new external write in this phase.

### Connection-pool note (C1)

The two new interval jobs join the existing interval-job fleet (count re-derived at EXECUTE time, never quoted here) on a shared 5-connection pool
(`pool_size=3 + max_overflow=2`); `scheduler.py:562` makes pool-awareness MANDATORY. Both jobs must:
open exactly one session, hold it only for the sweep body, and be spread by **`jitter` only**.
**(K1) Do NOT set `next_run_time` on either new job.** `jitter` and the boot offset are different
mechanisms: `test_the_boot_offset_is_larger_than_the_existing_offsets` asserts `aggregation_sweep`
(90s, `scheduler.py:785`) is strictly greater than every other job's offset — next highest is 60s
(`scheduler.py:695`). A new job with `next_run_time` ≥ 90s breaks that third AST gate, which E7's
count fix does not cover. If a boot offset is ever required, it must be strictly below 90s.
Superseded wording (retained so the error is not reintroduced): "carry a boot offset (distinct
`jitter` literals) so they never fire simultaneously with each other or with the handoff sweep." —
that sentence conflated the two mechanisms; use distinct `jitter` literals, no `next_run_time`.

---

## Implementation Checklist

### Step A — Schema and model

- [ ] A1. Add to `Draft` in `apps/api/models/draft.py`:
  `platform_comment_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)` and
  `site_id: Mapped[Optional[str]] = mapped_column(String(50), ForeignKey("sites.site_id", ondelete="SET NULL"), nullable=True, index=True)`.
  **(N1) The type is the `String(50)` site SLUG, not the UUID PK.** `Site` carries BOTH `id` (UUID PK)
  and `site_id` (`String(50)`, unique — so the FK is legal). Every site-keyed consumer in this repo
  uses the slug: `visitors.site_id` is `String(50)` (`models/visitor.py`), `Event.site_id` is the
  slug, and `EngagementAttribution.site_id` is `String(50)` NOT NULL. Choosing the slug makes A1b
  step 1 a direct assignment and C3 a direct write, with no `Site.id → Site.site_id` lookup anywhere.
  **Downstream join rule (binding on Phases 2 and 3):** `engage_outcomes.site_id`,
  `engage_contact_memory.site_id`, and the autonomy audit all carry the SAME `String(50)` slug and
  join to `sites.site_id` directly — never to `sites.id`. Both nullable and additive — historical
  rows stay NULL. Do NOT add either column to any response schema (E8).
- [ ] A1b. **(D-O1 + N2) Site derivation at draft creation.** `grep -rn "Draft(" apps/api` returns
  exactly TWO producers and Phase 1 must set `site_id` in BOTH:
  (i) `services/auto_drafter.py:119` — the auto path (Phase-1-exclusive);
  (ii) `routers/drafts.py:199` — the manual "Generate Reply" path. **(N2 registry amendment)**
  `routers/drafts.py` is now SHARED between Phase 1 and Phase 3b; Phase 1 holds exactly ONE licensed
  edit there — set `site_id` on the constructed `Draft`. Note `drafts.py:199` constructs the draft
  with NO `visitor_id`, so precedence step 1 can never apply on that path; it resolves via step 2 or
  falls to NULL.
  Precedence (both producers):
  1. `Draft.visitor_id` present → `SELECT site_id FROM visitors WHERE visitor_id = :vid` (note
     `uq_visitors_site_visitor` is `(site_id, visitor_id)`, so if this returns >1 row treat it as
     ambiguous → NULL).
  2. Else the owning user has exactly one `Site` → that site.
  3. Else → NULL.
  Record multi-site ambiguity as a **documented known limit**, not a silent guess.
  **AC-4 coverage consequence (stated, not discovered at EXECUTE):** a multi-site user's manual
  draft resolves to NULL → A1c fail-closed → no attribution mint on that path. This is the safe
  direction; it is recorded here and in the AC-4 residual rather than silently narrowing coverage.
- [ ] A1c. **(D-O1) FAIL-CLOSED on NULL `site_id`** — binding across the program: no attribution mint
  (Step C), no autonomy eligibility (Phase 3b), and site aggregates exclude NULL rows. Write this rule
  into the module docstring of `engage_outcome.py` so Phases 2–3 inherit it.
- [ ] A2. Create `apps/api/models/engage_outcome.py` with `EngageOutcome`:
  `id` UUID PK; `site_id` **nullable** FK (per A1c); `draft_id` FK → `drafts.id` ON DELETE CASCADE;
  `platform_comment_id` String(64); `outcome_type` String(32) constrained to
  `{reply_received, metrics_snapshot, attributed_visit}`; `platform_ref` String(128) **nullable**
  (**D-O9** dedupe key); `like_count` / `retweet_count` / `quote_count` / `reply_count` nullable
  Integers (**D-O10**: the X field is `retweet_count`, NOT `repost_count` — C4); `strategy` String(50)
  nullable (denormalized from `Draft.strategy`; `playbook == Draft.strategy`, pinned here);
  `observed_at` timestamptz; `created_at`/`updated_at`. **No body/text column may exist.**
  **(N5/N6) NO `contact_bidx` column in this phase.** The blind-index helper does not exist yet
  (`pii_crypto.py` exposes only `normalize_email` / `email_hash` / `encrypt_pii` / `decrypt_pii`) and
  is Phase-2-owned, and `engage_outcomes` is not in `ERASURE_TARGETS`. Adding a PII-derived column
  here would create a circular phase dependency AND ship un-erasable PII. Phase 2 adds the column,
  its own migration, and its erasure registration together; Phase 3a's DISTINCT-contact positive-rate
  is therefore a **Phase-2 dependency** (the dependency graph is unchanged — Phase 3a already
  requires Phase 2).
- [ ] A3. **(D-O9, replaces the broken `observed_at` key — G4)** Dedupe on a STABLE reference, mirroring
  `agent_fetch_event.py:49-52`: `platform_ref` carries the inbound reply's platform id
  (`reply_received`), the snapshot-day key `YYYY-MM-DD` (`metrics_snapshot`), or the visit reference
  (`attributed_visit`). Partial-unique index on `(draft_id, outcome_type, platform_ref)` WHERE
  `platform_ref IS NOT NULL`. An id is not a body — AC-6 safe.
- [ ] A3b. **(N4) Write semantics differ by outcome type — state it once, here.** Platform engagement
  counters are CUMULATIVE, so the correct semantics for a same-day re-poll is **latest-wins**, not a
  second row:
  - `metrics_snapshot` → `ON CONFLICT (draft_id, outcome_type, platform_ref) DO UPDATE` (latest-wins).
    **(Q1) The index is PARTIAL, so the inference clause MUST carry the predicate:**
    `index_where=text("platform_ref IS NOT NULL")`. Without it Postgres raises "there is no unique or
    exclusion constraint matching the ON CONFLICT specification". In-repo precedent:
    `apps/api/services/agent_visit_persistence.py:221`. Do **NOT** copy `routers/events.py:687` — that
    one infers against a FULL index and does not teach this.
    Day-granularity key and the E3 cadence both stay as written; polls 2..24 on the same day UPDATE
    the day's row rather than colliding.
  - `reply_received` and `attributed_visit` → strictly append-only, `ON CONFLICT DO NOTHING`. These
    are discrete events, not counters; an update would destroy history.
- [ ] A4. Add `Index("ix_engage_outcomes_site_strategy_created", "site_id", "strategy", "created_at")`
  — required by the Phase 3a aggregate. **(K6 note for Phase 3a)** the leading `site_id` may be NULL on
  the manual-draft path (N2), so re-check this index's selectivity once real data exists; a largely
  NULL leading column would weaken the Phase 3a aggregate.
- [ ] A5. Re-derive the live head and generate the migration `add_engage_outcomes` chained off it.
  **Never hardcode `down_revision`.** Pin the DSN per D-O10.
- [ ] A6. Live round-trip up → down → up against a **disposable** `postgres:16-alpine` container
  (C10 — NOT the shared dev DB on 5433). Record the exact revision range used; offline `--sql` needs an
  explicit `<from>:<to>` range in this repo.
- [ ] A7. Add the `# noqa: F401 — register for create_all` import for `EngageOutcome` to `apps/api/main.py`
  (E2 — the integration lane's only table-registration mechanism).

### Step B — Persist the platform id (AC-1)

- [ ] B1. **(sender.py licensed edit #1)** In `send_draft()`, at the success branch that currently only
  logs `comment_id`, assign `draft.platform_comment_id = comment_id` BEFORE `await db.commit()` so it
  lands in the same transaction as `status=sent`.
- [ ] B2. Falsy/absent id → leave NULL, log `draft_sent_without_comment_id`, still commit the send.
  Never fail a successful post over telemetry.
- [ ] B3. **(Q3)** Config block — ALL FOUR keys: `engage_outcome_capture_enabled: bool = False`,
  `engage_outcome_sweep_interval_minutes: int = 30`, `engage_metrics_poll_interval_minutes: int = 60`,
  `engage_metrics_poll_max_calls_per_sweep: int = 10` (introduced in E2b; it belongs to this block).
  **B1's persistence is unconditional and additive** — data capture, not gated behavior. The sweeps and
  poller are flag-gated.

### Step C — Server-side attribution mint (AC-4, re-scoped per D-O2)

- [ ] C1. Add a pure helper `mint_attribution_tag(content: str, site) -> tuple[str, str | None, str]`
  returning `(content, tag_or_None, reason)`. It finds a **site-owned** link — **host equality against
  `Site.url`** using the `detection_scanner.py:169 _host_of` precedent, NEVER a substring match (E3) —
  and rewrites it with the utm tag. (K4 citation fix: `_host_of` is DEFINED at
  `detection_scanner.py:134`; `:169` is a call site.)
- [ ] C1b. **(D-O2) NEVER append a link to approved content.** If no site-owned link is present, return
  `(content, None, "none")` — no mutation, no error. Drafting MAY offer the site link as candidate
  material at generation time behind a separate flag with human approval; that is explicitly OUT of
  this phase's scope and is recorded as a Phase-3-or-later follow-up.
- [ ] C1c. **(D-O2 + V7 + C8 + K7) Post-rewrite length re-validation.** Importing `CHAR_LIMITS` from
  `ai_reply.py` into the send path is safe (no circular import: `ai_reply` imports only `config` and
  `models.social_account`), but it makes the constant a cross-module contract — record that in the
  phase report so `ai_reply` does not change it unilaterally. `ai_reply.py:27` sets
  `CHAR_LIMITS[twitter]=280` and `_truncate_draft` (`ai_reply.py:402-405`) truncates to exactly 280 at
  GENERATION time using raw `len()`; `sender.py` posts verbatim. A utm rewrite lengthens the raw
  string. Therefore: after rewriting, re-check `len(new_content) <= CHAR_LIMITS[platform]`. If it
  exceeds → **SKIP the rewrite, send the ORIGINAL content, record `attribution: skipped_length`.**
  Never mutate past the cap; never fail the send. (X counts URLs as 23 via t.co, so the real overflow
  risk is low — but that is an unverified assumption and this rule makes it moot.)
- [ ] C2. **(sender.py licensed edit #2)** Call C1 in `send_draft()` immediately BEFORE `post_comment`,
  and post the returned content. Log `attribution_link_rewritten` with the reason
  (`minted` | `none` | `skipped_length`) so the C7 contract change is never silent.
- [ ] C3. Insert the `EngagementAttribution` row via `engagement_tracker` in the SAME transaction as
  `status=sent`. `EngagementAttribution.site_id` is NOT NULL — so when `Draft.site_id` is NULL, **skip
  the mint entirely** (A1c fail-closed) and record `attribution: no_site`.
- [ ] C4. **(G3/G7/N3 — the missing producer, correctly anchored)** Wire the ingest side in
  `apps/api/routers/events.py`. **The cycle-1 anchor (`events.py:422`) was mechanically impossible** —
  line 422 sits inside the `event_rows = [dict(...) for event in batch.events]` comprehension (closing
  at `:461`), where no `await` is legal; and `EngagementTracker.attribute_visitor` commits internally
  (`engagement_tracker.py:107`), which around the batched insert would commit mid-batch. Correct wiring:
  - **Anchor AFTER the ingest commit at `events.py:474`**, in a post-commit loop following the
    existing precedent at `events.py:618` (`for event in batch.events:`). **(Q7) That precedent lives
    inside `_process_signal_events` (`events.py:591`), which is awaited at ~`:521` — after the `:474`
    commit, with `batch` in scope.** There is an in-file convention comment near `:530` ("Kept OUT of
    `_process_signal_events` deliberately…"). **Decision: put the attribution loop OUTSIDE
    `_process_signal_events`**, as its own post-commit block, because it is attribution/analytics rather
    than signal extraction — the same reasoning the `:530` comment applies. Record the placement and the
    reasoning in the phase report so the convention stays legible. The ingest transaction is
    already closed at that point, so an internal commit is safe.
  - **Dedupe per batch:** collect the DISTINCT `beam_`-prefixed `utm_source` values in the batch and
    make ONE `attribute_visitor` call per distinct value — not one per event. This keeps N SELECTs off
    the hot path, matching how agent verification, handoff correlation, and promotion were all moved
    off ingest in this repo.
  - **Commit boundary (stated):** the post-commit loop passes the same session and ACCEPTS that
    `attribute_visitor` commits internally. Nothing in the loop may hold uncommitted ingest state.
  - **Fail-open, always:** wrap the whole block in try/except and log; attribution must NEVER fail or
    delay ingest.
  - On a match, append an `attributed_visit` `EngageOutcome` row with `platform_ref` = the visit
    reference. This is the ONLY producer of the `attributed_visit` value; without it Phase 3a's
    positive-rate half is permanently empty.
- [ ] C5. Confirm zero frontend involvement: `grep -rn "trackEngagement" apps/web/src` shows no NEW callers.

### Step D — Reply-back correlation sweep (AC-2)

- [ ] D1. Create `apps/api/services/engage_outcome_sweep.py` with `run_engage_outcome_sweep(db)`,
  modeled structurally on `agent_handoff_correlation.py` + `_handoff_correlation_sweep_job`
  (`jobs/scheduler.py:237`).
- [ ] D2. **(C3)** Linkage is EXACT: read recent inbound mentions requesting `referenced_tweets` and
  match `referenced_tweets[type=replied_to].id` against stored `Draft.platform_comment_id`. This
  requires a NEW client read — `_parse_tweets` / `twitter.py:191` currently request only
  `created_at,author_id,text`. Per **D-O4**: add the read to `platforms/base.py` as a **non-abstract
  default raising `NotImplementedError`**, then override in `twitter.py`. Adding an `@abstractmethod`
  would break all five subclasses.
- [ ] D2b. **(C2)** Obtain the X token via `services/sync.py:53 _get_fresh_token(db, account)`. Do NOT
  read `account.access_token` raw (it is ciphertext → silent 401) and do NOT import the module-private
  `sender._refresh_if_expired`.
- [ ] D2c. **(C5)** Add a 429/backoff policy for the new outward READS. `post_retry`
  (`platforms/base.py:29`) is write-only and does not cover them.
- [ ] D2d. **(peer-session finding, orchestrator-adopted) Exclude the site's OWN posting account.**
  A reply authored by the site's own connected `SocialAccount` NEVER produces a `reply_received`
  outcome. Site owners routinely thread follow-ups onto their own replies; counting those as
  reply-backs would let a site inflate its own track record with no third-party engagement — and that
  track record is exactly what Phase 3b's autonomy gate reads. Match the inbound author against the
  connected account's platform user id and skip before any write.
- [ ] D3. On match, write ONE `reply_received` outcome row with `platform_ref` = the inbound reply's
  platform id. **(cycle-3 P1) The inbound author is deliberately NOT recorded in this phase** — Phase 2
  adds `contact_bidx` together with its `ERASURE_TARGETS` registration (Phase 2 item A2b), so writing it
  here would create the un-erasable-PII defect N6 exists to prevent. **Never persist the inbound reply's
  body** — do not even pass it into the write function.
- [ ] D4. **(C11)** Guard with a NEW, unique `_LOCK_KEY` string via `pg_try_advisory_lock(hashtext(:key))`
  (13 existing call sites use this pattern). Grep existing keys first and confirm no collision.
- [ ] D5. Per-row fail-open iteration; a top-level crash is swallowed and logged. Never touches the
  ingest hot path. **(cycle-6 DD-2, REQUIREMENT — not advisory) Every per-row fail-open handler MUST
  log the caught exception type; bare-swallow is forbidden.** Enforced by the run-the-sweep-twice
  gate (F3c's sibling F3b:
  `ENGAGE_OUTCOME_CAPTURE_ENABLED=true .venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py::test_sweep_is_idempotent_across_two_runs -q`),
  which fails if the second run neither updates nor no-ops correctly — the observable symptom of a
  swallowed write error. Recorded as execute-agent instruction E16.
- [ ] D6. **(G2/G1/D-O3)** Register the job in `scheduler.py` append-only:
  `add_job(..., "interval", minutes=settings.engage_outcome_sweep_interval_minutes, id="engage_outcome_sweep", replace_existing=True, jitter=<int literal>, misfire_grace_time=<int literal>)`.
  Both kwargs MUST be **positive int literals** —
  `tests/unit/test_scheduler_job_config.py::test_the_values_are_positive_literals` rejects a settings
  attribute, and `test_every_interval_job_sets_misfire_grace_time` requires both. Short-circuit the job
  body when `engage_outcome_capture_enabled` is False.

### Step E — Metrics poller (AC-3)

- [ ] E1. Create `apps/api/services/engage_metrics_poll.py` with `run_engage_metrics_poll(db)`.
- [ ] E2. Batch by id: `GET /2/tweets?ids=…&tweet.fields=public_metrics`, **≤100 ids per call**.
- [ ] E2b. **(K5) Per-sweep call ceiling.** Add `engage_metrics_poll_max_calls_per_sweep: int = 10`
  (≤1000 replies per sweep). D2c covers 429 handling but not call VOLUME; with a 60-minute cadence and
  a growing reply corpus this is the OQ-1 blast surface. When the ceiling is hit, stop the sweep and
  log the remaining backlog — never loop unbounded.
- [ ] E3. Age tiering: <48h polled every sweep; 48h–7d daily; at 7d one terminal snapshot, then stop
  forever. `platform_ref` = the snapshot-day key so a re-run on the same day does not double-write.
- [ ] E4. **(N4)** Write ONE `metrics_snapshot` row per (draft, day) with
  `ON CONFLICT (draft_id, outcome_type, platform_ref) DO UPDATE` — latest-wins, per A3b, and with
  `index_where=text("platform_ref IS NOT NULL")` per Q1 (partial-index inference is mandatory). A second poll
  on the same day UPDATES that day's row; it neither raises nor double-writes. The E3 cadence is
  unchanged. Only `reply_received` / `attributed_visit` are strictly append-only.
- [ ] E5. **(C4/D-O10)** Map the X response field **`retweet_count`** (NOT `repost_count`) onto the model
  column. The only live-shape evidence in this repo is `demo.py:614` reading `like_count`; every other
  field name is UNVERIFIED. Mock fixtures must use the real X names; regenerate from a real recorded
  response if one becomes available (E7). An invented snake_case field is the exact ip-org defect that
  produced a 100% silent skip.
- [ ] E6. Register the job per D6's rules (own id `engage_metrics_poll`, literal `jitter` +
  `misfire_grace_time`, **distinct `jitter` literal per C1 — no `next_run_time`**, flag-gated).
  **(cycle-3 P3)** The earlier "distinct boot offset per C1" wording cited C1 as authority for the very
  phrase C1 retired: `aggregation_sweep` holds `next_run_time` = 90s (`scheduler.py:785`, next highest
  60s at `:695`), and a new job at ≥90s breaks
  `test_the_boot_offset_is_larger_than_the_existing_offsets`.
- [ ] E7. **(G1/D-O3/Q2)** Re-derive the inventory counts from the live `tests/unit/test_scheduler_job_config.py` at EXECUTE time and update them to the re-derived values; never trust the numbers written in this plan. Never relax the assertion. Add a re-derivation note in the test docstring. The file's own docstring forbids relaxing the assertion.
- [ ] E8b. **(peer-session finding)** Record a backlog stub: **per-playbook outcome accrual-rate
  sanity cap** — a defense-in-depth ceiling on how fast one playbook may accrue positive outcomes, so
  an anomalous burst cannot fast-track the Phase 3b autonomy threshold. DEFERRED, not in this phase's
  scope; D2d's own-account exclusion plus DISTINCT-contact counting are the v1 defenses.
- [ ] E8. Record OQ-1 (live X API tier + rate limits at scale) as a Hybrid known-gap with a backlog stub.
  It is **never a blocking gate**; a live billed probe needs user double opt-in.

### Step F — Tests

- [ ] F1. `tests/unit/test_engage_outcome_model.py`: no Text/body column on `engage_outcomes`; closed
  `outcome_type` vocabulary; both indexes exist; `retweet_count` (not `repost_count`) is the column name.
- [ ] F2. `tests/integration/test_engage_signal_acquisition.py::test_engage_send_persists_platform_comment_id` (AC-1).
- [ ] F2b. `…::test_draft_site_id_derivation` (D-O1, N2/K2) — covers BOTH producers:
  `auto_drafter` (visitor-linked → that site; single-site user → that site; multi-site + no visitor →
  NULL) AND `routers/drafts.py:199` (single-site user → that site; multi-site user → NULL, since the
  manual path never carries `visitor_id`). A gate that exercises only the auto path leaves the
  dominant user flow unproven.
- [ ] F3. `…::test_reply_received_correlation_sweep` (AC-2).
- [ ] F3c. **(D2d)** `…::test_own_account_reply_produces_no_outcome` — an inbound reply authored by the
  site's OWN connected posting account yields ZERO outcome rows; a third-party-authored control reply in
  the SAME test yields exactly ONE. Non-vacuous by construction — without the control, a wholly broken
  sweep also passes.
- [ ] F3b. `…::test_sweep_is_idempotent_across_two_runs` (G4/D-O9) — run the sweep TWICE against the
  same mocked mention; assert exactly ONE outcome row. This is the gate the old `observed_at` key
  could never pass.
- [ ] F4. `…::test_reply_public_metrics_poll_records_outcomes` (AC-3).
- [ ] F4b. `…::test_metrics_field_mapping_uses_retweet_count` (C4) — fixture carries `retweet_count`;
  assert it lands; assert a fixture using `repost_count` records nothing (anti-invention gate).
- [ ] F4c. **(N4)** `…::test_same_day_repoll_updates_row_without_error` — poll the SAME reply twice on
  the same day; assert no `IntegrityError`, the row count is stable at 1, and the counts reflect the
  LATEST poll.
- [ ] F5. `…::test_send_path_mints_attribution_tag_server_side` (AC-4, link-present path) — content
  ALREADY contains a site-owned link; assert the tag is in the content passed to the mocked
  `post_comment` AND an `EngagementAttribution` row exists.
- [ ] F5b. `…::test_no_link_present_records_attribution_none_and_does_not_mutate` (D-O2) — content
  posted byte-identical to the approved content.
- [ ] F5c. `…::test_foreign_host_link_is_not_rewritten` (E3) — a non-site URL is left untouched.
- [ ] F5d. `…::test_at_cap_content_skips_rewrite_and_sends_original` (V7/C8/D-O2) — 280-char content
  with a site link; assert the ORIGINAL is posted and `attribution: skipped_length` recorded.
- [ ] F5e. `…::test_null_site_id_skips_attribution_mint` (A1c fail-closed).
- [ ] F6. `…::test_roi_nonzero_after_tagged_visit` (AC-4) — drives through the **ingest path**
  (`routers/events.py` with a `beam_` utm_source), NOT by calling `attribute_visitor` directly (G3).
  Asserts a non-zero `/engagement/roi` reading AND an `attributed_visit` outcome row (G7).
- [ ] F7. `…::test_inbound_reply_body_not_persisted` — distinctive body string appears in zero DB columns.
- [ ] F8. **Flag-ON gates (MANDATORY, anti-vacuity):** run F3, F3b, **F3c**, F4 with
  `engage_outcome_capture_enabled=True` against real PG+Redis. Flag-OFF-only evidence is vacuous.
  **(cycle-6 DD-1) Flag mechanism, stated so the two Test Procedure runs do not contradict each
  other:** the flag-gated sweep tests (F3, F3b, F3c, F4) set `engage_outcome_capture_enabled` via
  **test fixture / monkeypatch**, and each carries a **flag-OFF skip-guard**
  (`pytest.mark.skipif` on the setting). Consequence, and the command that enforces it: Test
  Procedure step 2 —
  `.venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py -q` — runs
  flag-OFF and **SKIPS** those four tests rather than failing them, so its "0 failed" expectation is
  honest; Test Procedure step 3 (the same command prefixed
  `ENGAGE_OUTCOME_CAPTURE_ENABLED=true`) is the run in which they actually execute.
- [ ] F9. Flag-OFF control: sweep and poller are no-ops when the flag is False.
- [ ] F10. Regression: `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` green **including the
  re-derived scheduler counts from E7**; touched integration files green; `sender.py` behavior for
  non-approved drafts unchanged.

---

## Acceptance Criteria

| AC | Criterion | proven by | strategy |
|---|---|---|---|
| AC-1 | Platform id of every posted reply is persisted and queryable | `test_engage_send_persists_platform_comment_id` (F2) | Fully-Automated |
| AC-2 | Reply-backs detected and recorded within one sweep interval, exactly once | `test_reply_received_correlation_sweep` + `test_sweep_is_idempotent_across_two_runs` (F3, F3b, flag-ON via F8) | Fully-Automated (mock); live X leg Hybrid residual (OQ-1) |
| AC-3 | Public metrics on our own replies captured as outcome facts | `test_reply_public_metrics_poll_records_outcomes` + `test_metrics_field_mapping_uses_retweet_count` (F4, F4b, flag-ON via F8) | Fully-Automated (mock); live tier Hybrid residual (OQ-1) |
| AC-4 | **(re-scoped per D-O2)** When approved content contains a site-owned link, the attribution tag is minted server-side before posting and a tagged visit produces a non-zero ROI reading | `test_send_path_mints_attribution_tag_server_side` + `test_roi_nonzero_after_tagged_visit` (F5, F6) + the F5b–F5e boundary gates | Fully-Automated for the link-present path; **real-path non-zero ROI is a named residual** (see below) |

**AC-4 named residual (D-O2):** generated replies essentially never contain a site-owned link today
(`ai_reply.py:331-368` never passes `Site.url` into the prompt), so in production the mint path will
rarely fire until a separate, human-approved "offer the site link as candidate material" change ships.
The SPEC's unqualified non-zero-ROI claim is therefore demoted to a residual with a backlog stub. This
is recorded, not silently absorbed — the gate stays CONDITIONAL on it.

---

## Phase Completion Rules

- 🔨 **CODE DONE** — all checklist items applied, no gates run yet.
- 🧪 **TESTING** — gates running; any red gate keeps the phase here.
- ✅ **VERIFIED** — all 4 AC gates green INCLUDING the flag-ON legs (F8) and the boundary gates
  (F3b, F4b, F5b–F5e), the migration live round-tripped on a **disposable** container, the scheduler
  inventory counts re-derived and green, the validate-contract recorded, regression green, and the
  user confirmed. Code-only completion is never VERIFIED.
- 🚧 **BLOCKED** — see blockers below.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `test_engage_send_persists_platform_comment_id` | Fully-Automated | AC-1 |
| `test_draft_site_id_derivation` (5 cases, both producers) | Fully-Automated | D-O1 site key (enables AC-4 + Phase 3b rails) |
| `test_reply_received_correlation_sweep` (flag-ON) | Fully-Automated | AC-2 |
| `test_sweep_is_idempotent_across_two_runs` | Fully-Automated | AC-2 (no double-count → Phase 3a aggregate integrity) |
| `test_own_account_reply_produces_no_outcome` (+ third-party control) | Fully-Automated | AC-2 (self-inflation guard — protects the Phase 3b autonomy gate's input) |
| `test_reply_public_metrics_poll_records_outcomes` (flag-ON) | Fully-Automated | AC-3 |
| `test_metrics_field_mapping_uses_retweet_count` | Fully-Automated | AC-3 (anti-invented-field) |
| `test_send_path_mints_attribution_tag_server_side` | Fully-Automated | AC-4 (link-present path) |
| `test_no_link_present_records_attribution_none_and_does_not_mutate` | Fully-Automated | AC-4 boundary (D-O2) |
| `test_foreign_host_link_is_not_rewritten` | Fully-Automated | AC-4 safety (host-equality, E3) |
| `test_at_cap_content_skips_rewrite_and_sends_original` | Fully-Automated | AC-4 boundary (V7 char cap) |
| `test_null_site_id_skips_attribution_mint` | Fully-Automated | D-O1 fail-closed |
| `test_roi_nonzero_after_tagged_visit` (through the ingest path) | Fully-Automated | AC-4 + `attributed_visit` producer |
| `test_inbound_reply_body_not_persisted` | Fully-Automated | AC-6 precursor (AC-6 formally gated in Phase 2) |
| `test_engage_outcome_model` structural assertions | Fully-Automated | AC-6 precursor + Phase 3a aggregate performance |
| `tests/unit/test_scheduler_job_config.py` green at the re-derived counts | Fully-Automated | Scheduler inventory integrity (G1) |
| Migration up→down→up on a **disposable** `postgres:16-alpine` | Hybrid (needs container) | Schema safety (high-risk class) |
| Live X polling tier + rate limits at scale | Known-Gap → Hybrid backlog stub (OQ-1) | AC-2/AC-3 live residual — gate stays CONDITIONAL |
| Real-path non-zero ROI (replies actually containing site links) | Known-Gap → backlog stub (D-O2) | AC-4 residual — gate stays CONDITIONAL |

### Test Procedure / Post-Phase Testing

```bash
# 0. Confirm integration infra is up (never trust `which docker`)
lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'

# 1. Unit lane (includes the re-derived scheduler inventory counts)
.venv/bin/python3.11 -m pytest tests/unit -m unit -q
# Expected: 0 failed

# 2. Phase integration file
.venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py -q
# Expected: 0 failed

# 3. Flag-ON leg (MANDATORY — flag-OFF-only evidence is vacuous)
ENGAGE_OUTCOME_CAPTURE_ENABLED=true \
  .venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py -q
# Expected: 0 failed, rows actually written

# 4. Full integration regression
.venv/bin/python3.11 -m pytest tests/ -m integration -q
# Expected: no NEW failures vs the pre-phase baseline recorded in the phase report

# 5. Migration live round-trip on a DISPOSABLE container (NOT the shared dev DB) — C10
DOCKER=/Applications/Docker.app/Contents/Resources/bin/docker
$DOCKER run -d --rm --name engage-mig-p1 -e POSTGRES_PASSWORD=pg -p 55433:5432 postgres:16-alpine
export DATABASE_URL='postgresql+asyncpg://postgres:pg@localhost:55433/postgres'
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini downgrade -1
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head
$DOCKER stop engage-mig-p1
# Expected: clean each direction
# NOTE: the shared dev DSN is retarget:retarget_dev@localhost:5433/retarget_agent (D-O10) —
# use it ONLY for read-only head derivation, never for the destructive round-trip.

# 6. No frontend attribution dependency reintroduced
grep -rn "trackEngagement" apps/web/src
# Expected: unchanged from baseline (no new callers)
```

---

## Test Infra Improvement Notes

- Needs a mock X client `get_tweets_metrics` fixture using the REAL field names (`like_count`,
  `retweet_count`, `quote_count`, `reply_count`); Phases 2-3 reuse it.
- Needs a mock inbound-mentions fixture carrying `referenced_tweets[type=replied_to]`.
- **(K8) Two mocking mechanisms coexist in this repo; use the right one.** Platform calls are mocked
  with a stub-`PlatformService` monkeypatch (`tests/integration/test_sender_token_refresh.py` defines
  `_FakeService` + `_patch_service`) — there is NO `MOCK_EXTERNAL_APIS` branch in
  `services/platforms/` or `sender.py`, and inventing one would be a blast-radius expansion.
  Service-layer `MOCK_EXTERNAL_APIS` branches are used only where that convention already exists.
  The umbrella's Global Constraints line has been amended to name BOTH mechanisms so the plan and the
  umbrella no longer disagree.
- No disposable-Postgres migration round-trip harness exists; step 5 above is manual.
- **Rationale for D5's log-the-exception-type requirement:** asyncpg raises
  `InvalidColumnReferenceError` when an `ON CONFLICT` arbiter index is absent, and a per-row `except`
  block can swallow it — the sweep would look healthy while writing nothing. The requirement itself
  lives in checklist item D5 (with its enforcing command); this note records only why it exists.
- `tests/unit/test_scheduler_job_config.py` AST-enforces literal kwargs and hardcoded inventory counts.
  Every phase adding a job must re-derive the counts in the same change.

---

## Blockers That Would Justify BLOCKED Status

- `DATABASE_URL` cannot be pinned away from Supabase PROD for a migration command (HARD STOP).
- The alembic chain has 2 heads from a concurrent program — re-chain deliberately, never force-merge.
- No draft producer can be made to set `site_id` without restructuring a surface outside this phase.
- The X client cannot expose a batched ids read or a `referenced_tweets` read without modifying
  `post_comment` (which Phase 3b depends on) — surface rather than restructure.
- Integration ports 5433/6379 genuinely absent AND the Docker daemon socket is missing (distinct from
  the CLI-off-PATH false alarm). "environment-blocked" is NOT a valid known-gap category — name the
  specific blocker.

---

## Phase Loop Progress

- [ ] 1. RESEARCH — prior context loaded; alembic head re-derived; plan drift checked
- [ ] 2. INNOVATE — approach confirmed against locked D1–D4 + D-O1/D-O2/D-O3; Decision Summary written
- [x] 3. PLAN-SUPPLEMENT — three supplements applied 17-08-26: cycle 1 (G1–G7, C1–C12, V3, V7), cycle 2 (N1–N6, K1–K8), cycle 3 (P1, P3, Q1–Q7); Inner Loop Refresh Note current
- [x] 4. PVL — satisfied by outer PVL, 7 cycles, accepted CONDITIONAL (0 FAILs; R1–R4 documentation-only; OQ-1 + AC-4 real-path residuals accepted by explicit user command 17-08-26)
- [x] 5. EXECUTE — all checklist items applied 17-08-26; per-section gates green (unit 1970 passed / 2 skipped; integration flag-OFF 11 passed / 5 skipped; integration flag-ON 16/16; scheduler 28/24 re-derived; migration up→down→up clean on a disposable container)
- [ ] 6. EVL — independent vc-tester re-run of contract gates; follow-up stubs registered
- [ ] 7. UPDATE PROCESS — phase report written; umbrella state updated; commit done

**Validate-contract required before execute.** A placeholder or partial contract blocks EXECUTE.

---

## Exit Gate

- All 4 AC gates green, INCLUDING the flag-ON legs and every boundary gate (F3b, F4b, F5b–F5e).
- `tests/unit/test_scheduler_job_config.py` green at the re-derived counts (re-derive from the live file at EXECUTE time; never trust a number written in this plan).
- Migration live round-tripped on a **disposable** container.
- Integration lane shows no new failures vs baseline.
- OQ-1 and the AC-4 real-path residual each recorded with a backlog stub (recorded residuals, never
  silent PASSes) — both keep their AC CONDITIONAL.
- Phase report written to the report destination.

---

## Execute Anchor

This file IS the primary execute anchor for its phase — pass this exact path to vc-execute-agent.
Supporting phase files (read-only context, never the execute target): the umbrella plan, the sibling
phase plans, and the locked SPEC in this task folder.

---

## Resume and Execution Handoff

1. Selected plan file path: `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/phase-1-signal-acquisition_PLAN_17-08-26.md`
2. Last completed phase or step: **EXECUTE complete 17-08-26** (Steps A–F all applied). PVL closed after 7 cycles; CONDITIONAL accepted by explicit user command.
3. Validate-contract status: written, **CONDITIONAL — ACCEPTED** (0 FAILs; CONCERNs R1–R4 documentation-only; residuals OQ-1 and the AC-4 real path accepted on record).
4. Supporting context files loaded: `process/context/all-context.md`, `process/context/tests/all-tests.md`, `engage-learning-agent_SPEC_17-08-26.md`, the umbrella plan.
5. Next step for a fresh agent: **EVL** — spawn an independent vc-tester to re-run the contract's Test Gates commands. Do NOT re-run EXECUTE and do NOT re-run PVL. Phase report:
   `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/phase-1-signal-acquisition_REPORT_17-08-26.md`.

**Migration note for the next agent:** this phase's migration is `c5a91f3e07d4`
(`add_engage_outcomes`), chained off the head derived live at EXECUTE time
(`b7e4d21a9c58`). Concurrent programs move the head repeatedly — always re-derive with
`alembic heads` and a DSN pinned to localhost before chaining anything new.

---

## Next Step

**EVL.** Spawn an independent vc-tester over the `### Test gates` commands in the contract
below. The flag-ON leg (`ENGAGE_OUTCOME_CAPTURE_ENABLED=true`) is mandatory — flag-OFF-only
evidence is vacuous and SKIPS five gates by design.

---

## Validate Contract

Status: CONDITIONAL
Date: 17-08-26
date: 2026-08-17
generated-by: outer-pvl
supersedes: 2026-08-17 (outer-pvl, PVL cycle 3) — re-run from V1 against the cycle-3 supplement; all three cycle-3 FAILs (P1, P2, P3) and 6 of 7 CONCERNs closed and re-derived against real source; 0 FAILs remain

PVL cycle: 4
Parallel strategy: sequential
Rationale: signal score 4/7 (S2 schema/migration, S4 phase program, S6 high-risk class, S7 5+ files
= HIGH band); fit rule overrides. Phase 1's steps are strictly dependent (schema → persist → mint →
sweep → poller → tests), so one vc-execute-agent (opus) is correct, followed by an independent
vc-tester (opus) EVL leg. Agent-team rejected: no mid-run coordination needed inside one phase.

### Cycle-3 closure audit (re-derived against real source — NOT rubber-stamped)

| Cycle-3 gap | Verdict | Evidence re-checked this cycle |
|---|---|---|
| **P1** `contact_bidx` orphan in D3 | **CLOSED** | D3 now reads "write ONE `reply_received` outcome row with `platform_ref` = the inbound reply's platform id. **(cycle-3 P1) The inbound author is deliberately NOT recorded in this phase** — Phase 2 adds `contact_bidx` together with its `ERASURE_TARGETS` registration (Phase 2 item A2b), so writing it here would create the un-erasable-PII defect N6 exists to prevent." The clause is gone AND the omission is marked deliberate with a forward pointer. Every remaining `contact_bidx` mention in the body (Overview 1b, Blast Radius, A2, D3's note) is explanatory, not instructional. |
| **P2** umbrella duplicate `routers/drafts.py` row | **CLOSED** | The shared-surface classification table now holds exactly ONE row: `\| apps/api/routers/drafts.py \| **reassign → SHARED (Ph1 + Ph3b)** \|`. The stale `parallel-safe (Ph3 only)` row is struck. |
| **P3** E6 boot-offset cross-reference | **CLOSED** | E6 now reads "**distinct `jitter` literal per C1 — no `next_run_time`**", plus an explicit note that the earlier "distinct boot offset per C1" wording cited C1 as authority for the phrase C1 retired, with the 90s/60s figures restated. Re-verified against source: `aggregation_sweep` `next_run_time` = 90s (`scheduler.py:785`), next highest 60s (`scheduler.py:695`). |
| **Q1** partial-index `ON CONFLICT` | **CLOSED** | A3b and E4 both specify `index_where=text("platform_ref IS NOT NULL")`, quote the Postgres error text that results without it, cite the in-repo precedent `apps/api/services/agent_visit_persistence.py:221`, and explicitly warn "do **NOT** copy `routers/events.py:687` — that one targets a FULL index". |
| **Q2** re-derive-only scheduler wording | **PARTIAL → R2** | Converted in the three *instructional* sites — Entry Gate, Touchpoints (`test_scheduler_job_config.py` row), and E7 — all now carry the exact requested sentence. Two *descriptive* sites still hardcode the arithmetic. See R2. |
| **Q3** B3 config block | **CLOSED** | B3 now reads "Config block — ALL FOUR keys" and lists `engage_metrics_poll_max_calls_per_sweep: int = 10` with "(introduced in E2b; it belongs to this block)". |
| **Q4** F2b case label | **CLOSED** | Verification Evidence now reads `test_draft_site_id_derivation` **(5 cases, both producers)**. |
| **Q5** Phase Loop Progress audit trail | **CLOSED** | Step 3 now reads "three supplements applied 17-08-26: cycle 1 (G1–G7, C1–C12, V3, V7), cycle 2 (N1–N6, K1–K8), cycle 3 (P1, P3, Q1–Q7)". |
| **Q6** slug rule propagation | **CLOSED — verified in all three downstream plans** | `phase-2-memory-privacy` (`:99`, `:101`), `phase-3a-learning` (`:77`, `:79`), `phase-3b-autonomy` (`:108-110`, `:142`) each carry one binding line: `Draft.site_id` is `String(50)` referencing `sites.site_id` — the slug, not the UUID PK — joining to `sites.site_id` directly, never `sites.id`. |
| **Q7** `_process_signal_events` convention | **CLOSED — with an actual decision, not a deferral** | C4 records that the `:618` precedent lives inside `_process_signal_events` (`:591`, awaited at ~`:521`, after the `:474` commit, `batch` in scope), names the `:530` convention comment, and **decides**: put the attribution loop OUTSIDE `_process_signal_events` as its own post-commit block, because it is attribution/analytics rather than signal extraction. Requires the placement and reasoning be recorded in the phase report. |

**Score: 3/3 cycle-3 FAILs closed, 6/7 CONCERNs closed, 1 partial. Zero FAILs remain.**

### Duplicate-block scan (plan-agent tooling risk — explicitly checked)

Mechanical scan of the plan body (everything above `## Validate Contract`):

- **Repeated `##`/`###` headings: none.**
- **Repeated checklist item ids (A1…F10): none.**
- **Repeated non-trivial lines (>60 chars): 2, both legitimate** — `alembic ... upgrade head` appears twice because the round-trip is up → down → **up**, and the phase integration pytest command appears twice because step 2 runs it flag-OFF and step 3 runs it flag-ON.

**Verdict: CLEAN.** Unlike 3 of the prior 4 supplements, this one left no partially-applied patch artifacts.

### Restructure check (Phase 3 → 3a + 3b)

The superseded plan is **properly retired**, not orphaned:
`phase-3-learning-autonomy_PLAN_17-08-26.md` carries `name: plan:engage-learning-agent-phase-3-superseded`,
`**Status**: ⛔ SUPERSEDED — do not execute, do not validate, do not supplement this file`, a
step→new-file split map, and the umbrella's Phase Ordering table lists it as
`⛔ SUPERSEDED pointer — never an execute or PVL target`. The `## Stable Program Goal` START line
also says "NEVER target phase-3-learning-autonomy (superseded)". Umbrella declares
`PHASE PROGRAM (**4 phases** — 1, 2, 3a, 3b)`. No action needed.

Residual naming drift from the split is recorded as R1/R3 below — documentation only, no Phase-1
instruction changes meaning under either reading.

### Net gate derivation

| Layer 1 dimension | Status |
|---|---|
| Infra fit | PASS |
| Test coverage | PASS |
| Breaking changes | CONCERN |
| Security surface | PASS |

| Layer 2 section | Status |
|---|---|
| A — Schema and model | PASS |
| B — Persist the platform id (AC-1) | PASS |
| C — Attribution mint + ingest producer (AC-4) | PASS |
| D — Reply-back correlation sweep (AC-2) | PASS |
| E — Metrics poller (AC-3) | CONCERN |
| F — Tests | PASS |
| Program artifact — umbrella registry | CONCERN |

**Totals: 0 FAILs / 4 CONCERNs / 9 PASSes → Net Gate: CONDITIONAL**

All four CONCERNs are documentation-consistency items. None changes what the execute-agent builds,
and none is a coverage hole. Two accepted residuals (OQ-1, AC-4 real path) are carried as named
known-gaps and did not contribute to the verdict.

### Dimension findings

- Infra fit: PASS — scheduler compliance is fully specified (literal `jitter` + `misfire_grace_time`,
  no `next_run_time`, re-derive-only counts), the pool note is explicit, and all cited line anchors
  re-verified against source this cycle.
- Test coverage: PASS — 17 named gates including both draft producers, sweep run-twice, metrics
  anti-invention, same-day re-poll, four AC-4 boundary cases, ROI through the real ingest path,
  mandatory flag-ON legs, and flag-OFF control. No vacuous gate remains.
- Breaking changes: CONCERN — R1/R3 only: post-split "Phase 3" references are ambiguous between 3a
  and 3b in prose. The declared contract changes themselves (posted-text mutation, `PlatformService`
  defaults, internal-only `Draft` columns) are correct and unchanged.
- Security surface: PASS — no PII column ships in this phase; no third-party body is persisted
  (structural, gated by F1 + F7); host-equality link matching prevents tagging a foreign URL;
  fail-closed on NULL `site_id`; all new flags default OFF; no new external write.
- Section A: PASS — slug FK verified legal (`site_id String(50) unique` on `models/site.py:15`);
  partial-index inference now correct with an in-repo precedent.
- Section B: PASS — unchanged and correct since cycle 1.
- Section C: PASS — ingest anchor, placement decision, batch dedupe, commit boundary and fail-open
  all specified; mechanically re-verified.
- Section D: PASS — the `contact_bidx` orphan is gone and the omission is deliberate and documented.
- Section E: CONCERN — R2, the two residual hardcoded counts.
- Section F: PASS.
- Umbrella registry: CONCERN — R3/R4, prose drift; the classification table itself is now correct.

### CONCERN gap list (cycle 4)

| # | Finding | Disposition |
|---|---|---|
| R1 | ~15 "Phase 3" references in the Phase-1 body are now ambiguous post-split. Learning-side refs belong to **3a** (`:250`, `:251`, `:272`, `:274`, `:346`, `:490`, `:500` — the outcome aggregate and DISTINCT-contact positive-rate); autonomy-side refs belong to **3b** (`:70` kill switch/ceiling, `:123` `DraftStatus` enum, `:141` `delete_comment`, `:144`/`:146`/`:221` `routers/drafts.py` sharing, `:236` autonomy eligibility, `:488` rails, `:573` `post_comment` dependency). **No Phase-1 instruction changes meaning under either reading** — Phase 1's blast radius and edits are identical — so this is documentation drift, not a blocker. It will, however, confuse the 3a/3b PVLs. | Plan addition |
| R2 | Q2 is 3/5 done. The instructional sites (Entry Gate, Touchpoints, E7) carry the requested re-derive-only sentence; two descriptive sites still hardcode the arithmetic — Verification Evidence ("`tests/unit/test_scheduler_job_config.py` green at 28/24") and Exit Gate ("green at the re-derived 28/24 counts"). The Blast Radius pool note likewise states "22 existing interval jobs". The numbers are correct against the live file today (still 26/22), so this is a staleness trap rather than an error. | Plan addition — restate both as "green at the re-derived counts" and drop the literals |
| R3 | Umbrella prose still says "Phase 3"/"Ph3" where the split now implies 3b: the `routers/drafts.py` owned-list line (`:259` "SHARED between Phase 1 and Phase 3"), the Phase 3 owned list (`:329`), non-overlap rule 6b (`:378`), and the Touchpoints roll-up (`:566`). The classification table row itself is correct. | Umbrella addition |
| R4 | Umbrella `:214` — within the single corrected row, the Classification cell says `SHARED (Ph1 + Ph3b)` but the Resolution cell still reads "Ph3 = undo action, audit endpoint, pure sibling helper, retry fix". Same row, two labels. | Umbrella addition (one word) |

### Known gaps (accepted postures — NOT counted toward the gate)

- **OQ-1 — live X API tier + rate limits for metrics/mentions polling at scale.**
  `known-gap: needs-live-provider`; double opt-in required before any billed call. AC-2 and AC-3 are
  proven in mock; the live legs stay Hybrid residuals. Orchestrator-accepted.
- **AC-4 real-path ROI residual (D-O2).** Generated replies essentially never contain a site-owned
  link today (`ai_reply.py:331-368` never passes `Site.url` into the prompt), so the mint path will
  rarely fire in production. AC-4 is re-scoped to the link-present path; the site-link-offer follow-up
  is a parked backlog stub with no home phase. `known-gap: documented as NEW PLAN REQUIRED`.
- **AC-4 multi-site manual-draft sub-case.** `routers/drafts.py:199` constructs drafts with no
  `visitor_id`, so a multi-site user's manual draft resolves to NULL `site_id` → A1c fail-closed → no
  mint on that path. Stated in A1b rather than discovered at EXECUTE. Accepted; this is the safe
  direction.
- **Playwright/Clerk auth harness** — repo-wide known gap; no e2e leg required by this phase.

### Test gates (C3 5-column form)

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 | `platform_comment_id` persists in the same transaction as `status=sent` | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py::test_engage_send_persists_platform_comment_id -q` | B |
| D-O1 site key | derivation across BOTH producers, 5 cases: auto (visitor-linked / single-site / multi-site→NULL) and manual (single-site / multi-site→NULL) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py::test_draft_site_id_derivation -q` | B |
| D-O1 fail-closed | NULL `site_id` skips the attribution mint entirely | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py::test_null_site_id_skips_attribution_mint -q` | B |
| AC-2 | reply-back correlated via `referenced_tweets[replied_to]` → one outcome row | Fully-Automated | `ENGAGE_OUTCOME_CAPTURE_ENABLED=true .venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py::test_reply_received_correlation_sweep -q` | B |
| AC-2 idempotency | running the sweep TWICE over the same mocked mention writes exactly ONE row | Fully-Automated | `ENGAGE_OUTCOME_CAPTURE_ENABLED=true .venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py::test_sweep_is_idempotent_across_two_runs -q` | B |
| AC-6 precursor (sweep) | the inbound reply body appears in ZERO DB columns; the inbound author is not recorded at all | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py::test_inbound_reply_body_not_persisted -q` | B |
| AC-3 | mocked nonzero metrics land as a `metrics_snapshot` row | Fully-Automated | `ENGAGE_OUTCOME_CAPTURE_ENABLED=true .venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py::test_reply_public_metrics_poll_records_outcomes -q` | B |
| AC-3 anti-invention | a `retweet_count` fixture lands; a `repost_count` fixture records NOTHING | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py::test_metrics_field_mapping_uses_retweet_count -q` | B |
| AC-3 same-day re-poll | second poll same day: no IntegrityError, row count stable at 1, counts reflect the LATEST poll | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py::test_same_day_repoll_updates_row_without_error -q` | B |
| AC-4 mint | tag is inside the content passed to `post_comment` AND an `EngagementAttribution` row exists | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py::test_send_path_mints_attribution_tag_server_side -q` | B |
| AC-4 no-link boundary | no site link → content posted byte-identical, `attribution: none` | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py::test_no_link_present_records_attribution_none_and_does_not_mutate -q` | B |
| AC-4 host safety | a foreign-host URL is never rewritten | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py::test_foreign_host_link_is_not_rewritten -q` | B |
| AC-4 char cap | 280-char content with a site link posts the ORIGINAL, records `attribution: skipped_length` | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py::test_at_cap_content_skips_rewrite_and_sends_original -q` | B |
| AC-4 ROI + `attributed_visit` | a tagged visit **through the ingest path** yields non-zero `/engagement/roi` AND an `attributed_visit` row | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py::test_roi_nonzero_after_tagged_visit -q` | B |
| AC-4 no frontend dep | no NEW `trackEngagement` caller | Fully-Automated | `grep -rn "trackEngagement" apps/web/src` → exactly 1 hit (`apps/web/src/lib/api.ts:1393`), zero component callers | A (verified 17-08-26) |
| AC-6 precursor (model) | no Text/body column; closed `outcome_type` vocabulary; both indexes exist; column is `retweet_count` not `repost_count` | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_engage_outcome_model.py -m unit -q` | B |
| Flag-ON non-vacuity | F3, F3b, F4 run with `engage_outcome_capture_enabled=True` against real PG+Redis, rows actually written | Fully-Automated | `ENGAGE_OUTCOME_CAPTURE_ENABLED=true .venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py -q` | B |
| Flag-OFF control | sweep and poller are no-ops when the flag is False | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py -q` (flag unset) | B |
| Scheduler inventory | both new interval jobs carry literal `jitter` + `misfire_grace_time`, NO `next_run_time`, and the counts are re-derived from the live file | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_scheduler_job_config.py -m unit -q` | B |
| Unit regression | no new unit-lane failures | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` | B |
| Integration regression | no new integration-lane failures vs the pre-phase baseline | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/ -m integration -q` | B |
| Schema safety | migration up→down→up on a DISPOSABLE container | Hybrid — precondition: `docker run -d --rm -e POSTGRES_PASSWORD=pg -p 55433:5432 postgres:16-alpine`; `DATABASE_URL` pinned to it, NEVER the shared dev DB, NEVER `.env` | `DATABASE_URL='postgresql+asyncpg://postgres:pg@localhost:55433/postgres' .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head` then `downgrade -1` then `upgrade head` | B |
| Live X metrics/mentions tier + rate limits at scale (OQ-1) | — | (no proving strategy — named residual) | — | D (backlog stub; `needs-live-provider`, double opt-in) |
| Real-path non-zero ROI (replies actually containing site links) | — | (no proving strategy — named residual) | — | D (backlog stub; NEW PLAN REQUIRED, no home phase) |

gap-resolution legend: A — proven now. B — gate added by this plan's checklist. C — deferred to a
named later phase. D — backlog test-building stub (named residual).

`strategy:` carries ONLY the three proving strategies (Fully-Automated / Hybrid / Agent-Probe).
Known-Gap is never a strategy — OQ-1 and the AC-4 real-path residual are carried as `D` rows.

Legacy line form (for existing contract consumers):
- engage send path: [Fully-automated: `.venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py -q`]
- engage model structure: [Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_engage_outcome_model.py -m unit -q`]
- scheduler registration: [Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_scheduler_job_config.py -m unit -q`]
- migration safety: [hybrid: disposable `postgres:16-alpine` on 55433 + `alembic upgrade head` / `downgrade -1` / `upgrade head`]
- live X polling tier: [known-gap: OQ-1 documented, `needs-live-provider`, double opt-in]
- real-path ROI: [known-gap: documented as NEW PLAN REQUIRED, no home phase]

### Failing stubs (Fully-automated rows only)

All Fully-automated gates in this contract are new tests this phase must author, so every one starts
red by construction. The four that encode a defect a prior cycle proved real — keep these exact
scenario names so the red-first order is auditable:

```
test("should write NO second outcome row when the sweep re-reads the same inbound reply", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: sweep idempotent across two runs (G4)")
})

test("should update the same-day metrics_snapshot row without an IntegrityError", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: latest-wins upsert via index_where (N4/Q1)")
})

test("should record nothing when the metrics fixture uses repost_count instead of retweet_count", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: anti-invented-field gate (C4)")
})

test("should yield non-zero engagement ROI after a tagged visit arrives through the ingest path", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: ROI via ingest, not a direct attribute_visitor call (G3/N3)")
})
```

### Plan updates applied

**None by this agent.** Per the outer-PVL scope fence this agent writes only this contract section.
The four CONCERNs (R1–R4) are documentation-consistency fixes proposed for the orchestrator: R1/R2 in
the phase plan, R3/R4 in the umbrella. **They do not gate EXECUTE** — no execute-agent instruction
changes meaning under either reading. They should be applied before the 3a/3b PVLs, which will
otherwise inherit the ambiguity.

### Execute-agent instructions

| # | Instruction | Trigger condition |
|---|---|---|
| E1 | Re-derive the live alembic head with `DATABASE_URL` pinned to `retarget:retarget_dev@localhost:5433/retarget_agent` (read-only) before generating the migration. NEVER hardcode `down_revision`. The repo `.env` points at Supabase PRODUCTION and `apps/api/migrations/env.py` has no local-host guard — an unpinned alembic command applies DDL to prod. | Step A5 entry |
| E2 | Obtain X tokens via `services/sync.py:53 _get_fresh_token(db, account)`. Never read `account.access_token` raw (ciphertext → silent 401); never import `sender._refresh_if_expired` (module-private). | Steps D, E entry |
| E3 | "Site-owned link" MUST be host equality via `_host_of` (defined `detection_scanner.py:134`, called at `:169`), never a substring match. | Step C1 entry |
| E4 | Use a NEW, unique `_LOCK_KEY` string with `pg_try_advisory_lock(hashtext(:key))` (13 existing call sites). Grep the existing keys first and confirm no collision. | Step D4 entry |
| E5 | Pass `jitter=<int literal>` AND `misfire_grace_time=<int literal>` on both new `add_job` calls. Then re-derive the inventory counts from the live `tests/unit/test_scheduler_job_config.py` and update them in the SAME change. Never relax the assertion. Ignore any residual literal counts in this plan's descriptive tables (R2) — the live file is the source of truth. | Steps D6 / E6 / E7 entry |
| E6 | Add the new X reads to `PlatformService` (`platforms/base.py`) as NON-abstract defaults raising `NotImplementedError` before overriding in `twitter.py`. An `@abstractmethod` breaks all five subclasses. Do NOT touch `post_comment`. | Step D2 entry |
| E7 | Regenerate metrics fixtures from a real recorded response if one becomes available. Only `like_count` has live-shape evidence in this repo (`demo.py:614`). | Step E5 entry |
| E8 | `Draft.platform_comment_id` and `Draft.site_id` are internal — do NOT add either to any response schema (the `VisitorOut` P0 lesson). | Step A1 entry |
| E9 | Do NOT set `next_run_time` on either new job — `jitter` literals only. If a boot offset ever becomes unavoidable it MUST be strictly below 90s (`aggregation_sweep` holds 90s at `scheduler.py:785`; next highest 60s at `:695`). | Steps D6 / E6 entry |
| E10 | Import `CHAR_LIMITS` from `ai_reply.py` as the module-level constant, not a copy. Verified safe from circular import. Record the cross-module contract in the phase report. | Step C1c entry |
| E11 | Attribution work on the ingest path runs AFTER the event insert commits (`events.py:474`), **outside** `_process_signal_events`, as its own post-commit block. One `attribute_visitor` call per DISTINCT `beam_` utm_source in the batch, not one per event. Wrap fail-open. Record the placement and reasoning in the phase report. | Step C4 entry |
| E12 | The `metrics_snapshot` upsert targets a **PARTIAL** unique index, so the ON CONFLICT inference MUST carry the predicate: `index_where=text("platform_ref IS NOT NULL")`. Copy `apps/api/services/agent_visit_persistence.py:221`. Do NOT copy `routers/events.py:687` — that targets a FULL index. `reply_received` and `attributed_visit` use `DO NOTHING`; only `metrics_snapshot` uses `DO UPDATE`. | Steps A3b / E4 entry |
| E13 | Do NOT write a `contact_bidx` value anywhere in Phase 1 — the column does not exist in this phase's model. Phase 2 adds it with `blind_index()` and its `ERASURE_TARGETS` registration (Phase 2 item A2b). Do not record the inbound author in any form. | Step D3 entry |
| E14 | This plan predates the Phase 3 → 3a/3b split in places (R1). Where the text says "Phase 3", read it as **3a** for outcome-aggregate / positive-rate / learning statements and **3b** for `DraftStatus` enum, undo/`delete_comment`, kill-switch, ceiling, and autonomy statements. No Phase-1 edit changes under either reading — do not let the ambiguity expand scope. | Any "Phase 3" reference |

### Backlog artifacts

| Artifact | Location | What it tracks |
|---|---|---|
| `engage-live-x-metrics-tier_NOTE_17-08-26.md` | `process/features/campaigns-outreach/backlog/` | OQ-1: live X API tier + rate limits for metrics/mentions polling at scale; `needs-live-provider`, double opt-in before any billed call |
| `engage-reply-site-link-offer_NOTE_17-08-26.md` | `process/features/campaigns-outreach/backlog/` | AC-4 real-path residual (D-O2): offering the site link as human-approved candidate material at drafting time. **NEW PLAN REQUIRED — no home phase.** Includes the multi-site manual-draft NULL sub-case. |

### What this coverage does NOT prove

- **`test_engage_send_persists_platform_comment_id`** does not prove a REAL X post returns an id in
  the expected shape — `post_comment` is stubbed via the `_FakeService` monkeypatch precedent
  (`tests/integration/test_sender_token_refresh.py`); the live `resp.json()["data"]["id"]` path is
  never exercised.
- **`test_draft_site_id_derivation`** covers both producers but proves nothing about a user who
  acquires a second site AFTER drafts exist — historical rows stay NULL by design.
- **`test_reply_received_correlation_sweep`** does not prove X's mentions endpoint actually returns
  `referenced_tweets` on this account's tier — nothing in this repo has ever requested that field.
- **`test_sweep_is_idempotent_across_two_runs`** proves dedupe for `reply_received`;
  `test_same_day_repoll_updates_row_without_error` covers `metrics_snapshot`. **Neither proves the
  `attributed_visit` dedupe path** — it has no run-twice gate, so a duplicate visit reference is
  unverified.
- **`test_metrics_field_mapping_uses_retweet_count`** proves the mapping against a fixture we wrote.
  It does NOT prove the live field names — only `like_count` has live evidence (`demo.py:614`).
- **`test_send_path_mints_attribution_tag_server_side`** does not prove any real generated reply ever
  contains a site-owned link — the test seeds one (accepted AC-4 residual).
- **`test_roi_nonzero_after_tagged_visit`** proves the wiring, not production volume: the mint rarely
  fires on the real path, and a multi-site user's manual draft never mints at all.
- **`test_inbound_reply_body_not_persisted`** proves no body reaches a DB column. It does NOT prove no
  body reaches a log line or a structlog event field.
- **No gate proves** the connection pool tolerates 2 more jobs on a 5-connection pool, that per-sweep
  X call volume stays within limits (E2b's ceiling is a cap, not a measurement), or 429 behavior under
  real rate limits.
- **The migration round-trip** proves the chain applies cleanly on an empty disposable container. It
  does NOT prove behavior at production data volume and is not a production apply.
- **Flag-ON gates** prove the code path executes against real PG+Redis. They do NOT prove behavior
  against the real X API — every external call is stubbed.

### Cycle-6 Delta Addendum

Scoped delta-check only (not a re-run of V1–V7). Three cycle-6 body items reviewed: D2d, F3c, and
the E8b backlog stub + asyncpg Test Infra note. **Verdict: DELTA-DEFECT (2 items, both CONCERN
level). The cycle-4 CONDITIONAL gate STANDS** — neither defect makes an addition unimplementable,
and no FAIL is introduced.

**(a) D2d is implementable — concrete join verified against source.**
`Draft.post_id` → `Post.social_account_id` (`models/post.py:34`) → `SocialAccount.platform_user_id`
(`models/social_account.py:37`, `String(255)`). Population proof: `TwitterService.exchange_code`
sets `platform_user_id=user_info["id"]` from `_get_me()` → `GET /2/users/me` →
`resp.json()["data"]["id"]` — X's numeric user id. That is the SAME id space as the `author_id`
field the client already requests (`tweet.fields=author_id`, `twitter.py:150/169/282`) and reads
(`:199`). The comparison is a plain string equality; no normalization, no new column, no new query.
The sweep already holds the `SocialAccount` because D2b requires `_get_fresh_token(db, account)`, so
`account.platform_user_id` is in scope at the exclusion point. Choosing the platform **id** over the
handle is correct — handles are mutable, ids are not.

*Implementation note (not a defect):* `_parse_tweets` returns `FeedPost`, which carries
`author_username` but **drops `author_id`** — and has no `referenced_tweets` either. D2 already
mandates a NEW client read rather than reusing `_parse_tweets` precisely because of
`referenced_tweets`; D2d rides on that same requirement. The new read MUST surface the raw
`author_id`, not a `FeedPost`.

**(b) F3c is non-vacuous as specified** — the same-test third-party control means a wholly broken
sweep (writing nothing) fails the control leg rather than passing the exclusion leg. Correct
construction. Conditional on DD-1 below.

**(c) Contradiction check — 1 defect, 1 cosmetic.**

| # | Severity | Finding |
|---|---|---|
| DD-1 | CONCERN | **F3c is flag-gated but missing from F8's mandatory flag-ON list.** F8 names only F3, F3b, F4. D6 short-circuits the sweep body when `engage_outcome_capture_enabled` is False, so under flag-OFF F3c's control leg ("exactly ONE row") cannot pass — while Test Procedure step 2 runs the whole integration file flag-OFF expecting "0 failed". Fix: add F3c to F8's list and give it the same flag-OFF skip-guard treatment F3/F4 need. (The underlying flag-OFF/flag-ON ambiguity for F3/F4 pre-dates cycle 6; the F8 omission for F3c is addition-scoped.) |
| — | cosmetic | F3c is placed between F3 and F3b, so Step F reads F3, F3c, F3b, F4. Distinct test names, no functional impact. |

**(d) Stub/note inertness — 1 defect.**

| # | Severity | Finding |
|---|---|---|
| DD-2 | CONCERN | **The asyncpg Test Infra note is NOT inert.** Its closing sentence — "When adding per-row fail-open handlers, log the exception type rather than swallowing silently" — is an execute-time behavioral requirement on D5, parked in a notes section an execute-agent working the checklist may never read. D5 currently says only "Per-row fail-open iteration; a top-level crash is swallowed and logged." Fix: move that requirement into D5 as an explicit clause; leave the diagnostic rationale in the note. |
| — | inert ✅ | **E8b** is clean: "Record a backlog stub… **DEFERRED, not in this phase's scope**", with the v1 defenses named (D2d + DISTINCT-contact counting). Record-only, no execute-time behavior. |
| — | cosmetic | Blast Radius still says "NEW (7) … 1 backlog note" while the plan now names three stubs (OQ-1, AC-4 site-link-offer, accrual-rate). Pre-existing undercount, widened by one. |

**Contract impact.** No test-gate row is invalidated. Two rows should be added to the Test Gates
table when the delta is folded in: `AC-2 self-inflation guard` — `test_own_account_reply_produces_no_outcome`
(+ third-party control), Fully-Automated, gap-resolution B — and F3c added to the flag-ON gate row.
D2d also strengthens a previously unguarded input to Phase 3b's autonomy gate, which the cycle-4
contract flagged only indirectly. Two execute-agent instructions follow:

| # | Instruction | Trigger |
|---|---|---|
| E15 | The new mentions read must return the raw tweet dict (or a shape carrying BOTH `author_id` and `referenced_tweets`) — never a `FeedPost`, which drops both. Compare `inbound["author_id"] == account.platform_user_id` as strings and skip before any write. | Steps D2 / D2d entry |
| E16 | Per-row fail-open handlers in the sweep and poller MUST log the caught exception type, never bare-swallow. asyncpg raises `InvalidColumnReferenceError` when an `ON CONFLICT` arbiter index is absent; a silent except makes the sweep look healthy while writing nothing. | Step D5 entry |

**Gate impact: CONDITIONAL stands.** DD-1 and DD-2 join R1–R4 as documentation/wiring CONCERNs to be
accepted or fixed before EXECUTE. Neither is a FAIL; no re-run of V1–V7 is warranted.

Gate: CONDITIONAL (0 FAILs; 4 documentation-consistency CONCERNs R1–R4; 2 accepted residuals on record)
Accepted by: NOT self-accepted — this agent does not accept its own CONDITIONAL. The orchestrator or
user must accept the four CONCERNs and the two named residuals (OQ-1; AC-4 real-path + multi-site
manual-draft sub-case) before EXECUTE. Per the PVL gate rule, CONDITIONAL after ≥1 recorded fix cycle
is EXECUTE-eligible once accepted — `results.tsv` records cycles 1–3.
