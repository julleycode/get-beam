---
phase: phase-1-signal-acquisition
date: 2026-08-17
status: COMPLETE_WITH_GAPS
feature: campaigns-outreach
plan: process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/phase-1-signal-acquisition_PLAN_17-08-26.md
---

# Phase 1 — Signal Acquisition — EXECUTE report

**TL;DR:** All Steps A–F applied. Every Fully-Automated gate green, including the
mandatory flag-ON leg (16/16 against real PG+Redis) and the migration up→down→up
round-trip on a disposable container. Unit lane 1970 passed / 0 failed. No source
regressions. Status is COMPLETE_WITH_GAPS solely because the two pre-accepted
residuals (OQ-1 live X tier, AC-4 real-path ROI) remain open by design, and because
the full integration lane could not be measured uncontended (4 peer sessions share
one dev DB).

---

## What Was Done

Steps A→F in order, per-section gates green before advancing.

### Step A — schema and model
- `apps/api/models/engage_outcome.py` (NEW) — `EngageOutcome` + `record_outcome()`.
  Closed `outcome_type` vocabulary (CHECK constraint + `OUTCOME_TYPES` tuple), the
  four real X counter names, `strategy` denormalized, **no body/text column**, **no
  `contact_bidx`**. Module docstring carries the A1c fail-closed rule so Phases 2–3
  inherit it.
- `apps/api/models/draft.py` — `platform_comment_id` `String(64)` and `site_id`
  `String(50)` FK → **`sites.site_id`** (the SLUG, `ON DELETE SET NULL`). Both
  nullable, both internal — neither added to any response schema (E8).
- Migration `c5a91f3e07d4_add_engage_outcomes.py` (NEW), `down_revision =
  b7e4d21a9c58` — the head re-derived live with a pinned local DSN at EXECUTE time
  (E1). Single head confirmed before and after.
- `apps/api/main.py` — `EngageOutcome` registered for `create_all` (A7/E2).

### Step B — persist the platform id (AC-1)
- `sender.send_draft()` sets `draft.platform_comment_id` in the SAME transaction as
  `status=sent`. A falsy id leaves NULL and logs `draft_sent_without_comment_id` —
  telemetry never fails a post that succeeded.
- `apps/api/config.py` — all four keys in one `# ─── Engage outcome capture (Phase 1) ───`
  block, defaults OFF/conservative. B1's persistence is deliberately NOT flag-gated.

### Step C — server-side attribution mint (AC-4)
- `sender.mint_attribution_tag(content, site)` — host-equality ownership via
  `_host_of` (E3), first site-owned link only, **never appends a link**.
- Post-rewrite length re-validation against `CHAR_LIMITS[platform]`; over the cap →
  `skipped_length`, original content posted.
- `EngagementTracker.stage_engagement()` (NEW) — adds the attribution row WITHOUT
  committing, so it lands in the same transaction as `status=sent` (C3).
  `record_engagement` could not be reused: it commits internally.
- `engagement_tracker.make_utm_tag()` — public alias so the send path never touches
  the module-private minter.
- `routers/events.py` — the ingest-side `attributed_visit` producer (see E11 below).

### Step D — reply-back correlation sweep (AC-2)
- `apps/api/services/engage_outcome_sweep.py` (NEW). Advisory lock
  `engage_outcome_sweep` (grepped — no collision), flag short-circuit, exact linkage
  via `referenced_tweets[type=replied_to].id` → `Draft.platform_comment_id`,
  **own-account exclusion** on `platform_user_id`, per-row fail-open that logs
  `error_type`, acquire/release paired in `finally`.
- Token via `sync._get_fresh_token` (E2) — never raw `account.access_token`.

### Step E — metrics poller (AC-3)
- `apps/api/services/engage_metrics_poll.py` (NEW). Batched ≤100 ids, age tiering
  (<48h every sweep / 48h–7d daily / ≥7d one terminal snapshot), day-key
  `platform_ref`, latest-wins upsert, per-sweep call ceiling that stops and logs the
  backlog, distinct lock key.
- `platforms/base.py` — `read_retry` (429 + 5xx + timeouts; `post_retry` is
  write-only) plus `fetch_reply_mentions` / `get_tweets_metrics` as **non-abstract**
  defaults raising `NotImplementedError` (E6). `post_comment` untouched.
- `platforms/twitter.py` — both overrides. `fetch_reply_mentions` returns **raw
  dicts** carrying `author_id` + `referenced_tweets` (E15) — `_parse_tweets`/`FeedPost`
  drops both.
- `jobs/scheduler.py` — two interval jobs appended (`engage_outcome_sweep` jitter 45,
  `engage_metrics_poll` jitter 75), literal `misfire_grace_time`, **no
  `next_run_time`** (E9).
- `tests/unit/test_scheduler_job_config.py` — counts re-derived **26/22 → 28/24** from
  the live file in the same change (E5/E7), with a re-derivation note in the docstring.
  Assertion never relaxed.

### Step F — tests
`tests/unit/test_engage_outcome_model.py` (7 tests) and
`tests/integration/test_engage_signal_acquisition.py` (16 tests) — all F1–F10 gates.

---

## Per-Gate Results

| Gate | Command / scope | Result |
|---|---|---|
| AC-6 precursor (model, F1) | `pytest tests/unit/test_engage_outcome_model.py -m unit` | **7 passed** |
| Integration, flag-OFF (F9 + non-gated) | `pytest tests/integration/test_engage_signal_acquisition.py` | **11 passed, 5 skipped** (skips are by design — F8) |
| Integration, **flag-ON (F8, mandatory)** | `ENGAGE_OUTCOME_CAPTURE_ENABLED=true pytest …` | **16 passed, 0 skipped** |
| AC-1 (F2) | `test_engage_send_persists_platform_comment_id` | PASS |
| D-O1 site key (F2b, 5 cases, both producers) | `test_draft_site_id_derivation` | PASS |
| AC-2 (F3) | `test_reply_received_correlation_sweep` | PASS (flag-ON) |
| AC-2 idempotency (F3b) | `test_sweep_is_idempotent_across_two_runs` | PASS (flag-ON) |
| AC-2 self-inflation (F3c) | `test_own_account_reply_produces_no_outcome` + third-party control | PASS (flag-ON) |
| AC-3 (F4) | `test_reply_public_metrics_poll_records_outcomes` | PASS (flag-ON) |
| AC-3 anti-invention (F4b) | `test_metrics_field_mapping_uses_retweet_count` | PASS |
| AC-3 same-day re-poll (F4c) | `test_same_day_repoll_updates_row_without_error` | PASS (flag-ON) |
| AC-4 mint (F5) | `test_send_path_mints_attribution_tag_server_side` | PASS |
| AC-4 no-link (F5b) | `…_records_attribution_none_and_does_not_mutate` | PASS |
| AC-4 host safety (F5c) | `test_foreign_host_link_is_not_rewritten` | PASS |
| AC-4 char cap (F5d) | `test_at_cap_content_skips_rewrite_and_sends_original` | PASS |
| D-O1 fail-closed (F5e) | `test_null_site_id_skips_attribution_mint` | PASS |
| AC-4 ROI via ingest (F6) | `test_roi_nonzero_after_tagged_visit` | PASS |
| AC-6 precursor (sweep, F7) | `test_inbound_reply_body_not_persisted` | PASS |
| Scheduler inventory | `pytest tests/unit/test_scheduler_job_config.py -m unit` | **12 passed** at re-derived 28/24 |
| Unit regression (F10) | `pytest tests/unit -m unit` | **1970 passed, 2 skipped, 0 failed** |
| Schema safety (Hybrid) | disposable `postgres:16-alpine` :55433, full chain from EMPTY → head, then `downgrade -1` → `upgrade head` | **clean each direction**, final head `c5a91f3e07d4` |
| AC-4 no frontend dep (C5) | `grep -rn "trackEngagement" apps/web/src` | **1 hit** (`apps/web/src/lib/api.ts:1393`), zero component callers — unchanged |
| Integration lane regression | `pytest tests/ -m integration` | 663 passed / 1 failed / 9 errors — **all 10 pass on isolated re-run**; contention artifact, see below |
| Live X tier (OQ-1) | — | Known-gap, backlog stub written |
| Real-path ROI (D-O2) | — | Known-gap, backlog stub written |

---

## E11 — ingest attribution placement decision + reasoning

**Placement:** `apps/api/routers/events.py`, AFTER the event-insert commit,
**OUTSIDE** `_process_signal_events`, as its own post-commit block (immediately
before the conversion-goal block).

Three reasons, recorded so the in-file convention stays legible:

1. `EngagementTracker.attribute_visitor` **commits internally**. Inside the batched
   insert it would commit mid-batch; inside `_process_signal_events` it would flush
   that function's still-pending fingerprint/svid updates — the exact hazard the
   existing `:530`-area convention comment calls out for the marker handoff.
2. The cycle-1 anchor was mechanically impossible: that line sits inside the
   `event_rows = [dict(...) for event in batch.events]` comprehension, where no
   `await` is legal.
3. This is attribution/analytics, not signal extraction. Same reasoning the in-file
   convention comment applies to the marker handoff — so it belongs on the same side
   of that boundary.

**Batch dedupe:** ONE `attribute_visitor` call per **DISTINCT** `beam_`-prefixed
`utm_source` in the batch, not one per event. N SELECTs per pageview on the hot path
is how this repo has repeatedly regressed (agent verification, handoff correlation,
promotion were all moved off ingest for this reason).

**Commit boundary:** the ingest transaction is already closed, so the internal commit
is safe. The whole block is wrapped fail-open with `error_type` logged — attribution
must never fail or delay ingest.

`attributed_visit.platform_ref` = `"{utm_tag}:{visitor_id}"` (per-visitor, not
per-event) so a returning visitor on the same tagged link is one outcome.

---

## E10 — CHAR_LIMITS cross-module contract note

`sender.py` now imports `CHAR_LIMITS` from `ai_reply.py` as the module-level
constant (not a copy). Import verified free of circular import: `ai_reply` pulls only
`config` and `models.social_account`.

**This makes `ai_reply.CHAR_LIMITS` a cross-module contract with two consumers.** It
may no longer be changed unilaterally: `ai_reply._truncate_draft` truncates to the cap
at GENERATION time using raw `len()`, and `sender` posts verbatim after a utm rewrite
that LENGTHENS the string. If the constant is raised in `ai_reply` alone, the send
path will post past a real platform cap. Both sides must agree on one number.

---

## X1 — ORM index mirror note (highest-value defect avoided)

The `metrics_snapshot` partial unique index (`uq_engage_outcomes_dedup`, `WHERE
platform_ref IS NOT NULL`) is declared **in BOTH** the model's `__table_args__` and
the migration, with a **textually identical** predicate.

This is load-bearing, not belt-and-braces. The integration lane builds schema via
`Base.metadata.create_all` and **never runs alembic**, so a migration-only index is
invisible to every integration test — and every `ON CONFLICT` insert would raise
asyncpg `InvalidColumnReferenceError` ("no unique or exclusion constraint matching
the ON CONFLICT specification"). Combined with a per-row `except` that swallowed
silently, the sweep would complete "successfully" while writing **nothing**.

Two structural defenses against that class of failure now exist:
- `_DEDUP_PREDICATE` is a single shared constant in the model, used by both the index
  and the upsert's `index_where`, so they cannot drift.
- Every per-row fail-open handler logs `error_type=type(exc).__name__` (D5/E16), so a
  swallowed arbiter error is visible instead of silent.
- `test_both_required_indexes_are_declared_on_the_model` asserts the model-side
  declaration and predicate directly, and
  `test_same_day_repoll_updates_row_without_error` fails outright if the arbiter is
  missing.

---

## Plan Deviations

All within blast radius; no hard-stop class touched. No schema/auth/billing/API
surface change beyond what the plan authorizes.

| # | Deviation | Why |
|---|---|---|
| D1 | `derive_draft_site_id` (A1b precedence) placed in `services/engagement_tracker.py` rather than a new module | The plan names both producers but no home for the shared helper, and Blast Radius NEW(7) has no slot for another module. `engagement_tracker.py` is already an owned/edited file and owns site attribution. Avoids duplicating the precedence in two producers. |
| D2 | Added `EngagementTracker.stage_engagement()` instead of calling `record_engagement()` | C3 requires the attribution row in the SAME transaction as `status=sent`, but `record_engagement` commits internally. A committing call before `post_comment` would leave an orphan row on a failed post. |
| D3 | Added `engagement_tracker.make_utm_tag()` public alias | So `mint_attribution_tag` keeps the plan's exact `(content, site)` signature without reaching for the module-private `_make_utm_tag`. |
| D4 | Length re-validation performed at the C2 call site rather than inside `mint_attribution_tag` | Preserves the plan's mandated signature `mint_attribution_tag(content, site) -> tuple[str, str \| None, str]`, which carries no `platform` argument. Behaviour is exactly C1c. |
| D5 | Poller filters platform counters to the four recognized field names and records NOTHING when none match (`engage_metrics_unrecognized_fields`) | Found by the F4b anti-invention gate: without it a `repost_count`-only response wrote a row of all-NULL counters, so the "records nothing" half failed. Strengthens E5's intent — an X field rename now surfaces as a warning, not a silent skip or a fake row. |
| D6 | Added `read_retry` to `platforms/base.py` | D2c requires a 429/backoff policy for the NEW outward reads; `post_retry` is write-only and does not cover them. Named/scoped as a sibling policy, no existing behaviour changed. |

---

## Test Infra Gaps Found

1. **The shared dev DB on :5433 cannot support concurrent integration runs.** `tests/conftest.py`
   `test_engine` does a global `drop_all` + `DROP TYPE` + `create_all` per test, so two
   concurrent pytest processes collide on PG enum types
   (`duplicate key … pg_type_typname_nsp_index`, `typname=platform`). With 4 peer
   sessions active this contaminated **two** full-lane runs of mine:
   - contaminated run: 581 passed / 16 failed / 78 errors
   - uncontended-start run: 663 passed / 1 failed / 9 errors
   - **all 10 of those (1F+9E) pass on isolated re-run** — including the 4 of mine and
     unrelated `test_demo_identify`, `test_demo_security`, `test_feature_board`,
     `test_ip_org_pipeline::TestLockSerialization`.
   Consequence: **the full integration lane could not be measured uncontended**, so
   "no new failures vs baseline" is established per-file rather than lane-wide. EVL
   should re-run the lane when no peer session is testing. This is a harness
   limitation, not `harness-drift` and not a product defect.
2. **`tests/unit/test_coop_expiry_guard.py` breaks unit-lane collection** —
   `ImportError: cannot import name 'CoopExpirySystemicFailure' from
   apps.api.services.identity_coop`. The file is **untracked** and `identity_coop.py`
   is modified: a peer session's in-flight work, entirely outside this phase's blast
   radius. My unit-lane figure excludes it via `--ignore`. Not touched, not fixed.
   Classification: `test-breakage` (peer-owned, in flight).
3. Two `Draft`/`Visitor` fixture NOT-NULL traps cost a cycle each and are worth
   remembering: `posts.author_name` is NOT NULL, and **`visitors.first_seen` /
   `last_seen` are NOT NULL** (whereas `identified_visitors` has neither column — the
   same asymmetry recorded in a prior Docker-gate finding).
4. No disposable-Postgres migration round-trip harness exists; the A6 gate is manual
   (documented command sequence in the plan's Test Procedure step 5).

---

## Backlog Stubs Written

| File | Tracks |
|---|---|
| `process/features/campaigns-outreach/backlog/engage-live-x-metrics-tier_NOTE_17-08-26.md` | OQ-1 — live X tier/rate limits; `needs-live-provider`, **double opt-in required**. Names `referenced_tweets` presence as the highest-value first probe. |
| `process/features/campaigns-outreach/backlog/engage-reply-site-link-offer_NOTE_17-08-26.md` | AC-4 real-path residual (D-O2) — site link as human-approved candidate material at drafting time. **NEW PLAN REQUIRED, no home phase.** Includes the multi-site manual-draft NULL sub-case and the unverified `attributed_visit` dedupe path. |
| `process/features/campaigns-outreach/backlog/engage-playbook-accrual-rate-cap_NOTE_17-08-26.md` | E8b — per-playbook accrual-rate sanity cap (defense-in-depth). DEFERRED; right home is Phase 3b. |

---

## Accepted Residuals (recorded, not attempted)

- **OQ-1** live X tier/rate limits — `needs-live-provider`. **No live X call was made.**
  Every external call in every gate is stubbed via the `_FakeService` monkeypatch.
- **AC-4 real-path ROI** — proven for the link-present path only.
- **AC-4 multi-site manual-draft NULL sub-case** — fail-closed is intended.
- **R1–R4** (documentation-consistency CONCERNs) — unchanged; none altered an
  instruction executed here. E14 applied throughout: "Phase 3" read as 3a for
  learning/aggregate statements, 3b for autonomy/enum/kill-switch statements.

## CONTEXT_PARTIAL

`CONTEXT_PARTIAL: integration-lane baseline` — an uncontended full-lane baseline could
not be recorded (see Test Infra Gaps #1). Per-file and unit-lane evidence is complete.

---

## Closeout Packet

- **Selected plan:** `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/phase-1-signal-acquisition_PLAN_17-08-26.md`
- **Finished:** Steps A–F complete; 23 new tests (7 unit + 16 integration) all green;
  migration live round-tripped; scheduler counts re-derived 28/24; 3 backlog stubs written.
- **Verified:** every Fully-Automated gate + the mandatory flag-ON leg + the Hybrid
  migration gate.
- **Still unverified:** OQ-1 live provider behaviour; real-path ROI volume;
  `attributed_visit` run-twice dedupe; uncontended full integration lane.
- **Remaining cleanup:** EVL (independent vc-tester re-run of the contract gates),
  then UPDATE PROCESS. Nothing is committed — git was read-only this session.
- **Classification:** **Keep in active/testing** — code-complete and gate-green, but
  EVL has not run and the two residuals keep the AC gates CONDITIONAL.
- **Operator note:** all new flags default **OFF**
  (`engage_outcome_capture_enabled`). Schema-applied ≠ feature-enabled; flipping it
  requires the OQ-1 probe first.

---

## Forward Preview

### Test Infra Found
`_FakeService` + `_patch_service` monkeypatch is the ONLY platform-mocking mechanism
(no `MOCK_EXTERNAL_APIS` branch exists in `services/platforms/` or `sender.py`).
Phases 2–3 should extend `tests/integration/test_engage_signal_acquisition.py`'s
`_FakeService` (already carries `post_comment`, `fetch_reply_mentions`,
`get_tweets_metrics`) and its `_seed()` helper rather than rebuilding them. Run
integration tests only when no peer session is testing.

### Blast Radius Changes
NEW: `models/engage_outcome.py`, `services/engage_outcome_sweep.py`,
`services/engage_metrics_poll.py`, migration `c5a91f3e07d4`, 2 test files, 3 backlog notes.
EDITED: `services/sender.py`, `models/draft.py`, `services/engagement_tracker.py`,
`services/auto_drafter.py`, `routers/drafts.py` (the ONE licensed `site_id` edit),
`routers/events.py`, `jobs/scheduler.py`, `tests/unit/test_scheduler_job_config.py`,
`services/platforms/base.py`, `services/platforms/twitter.py`, `apps/api/main.py`,
`apps/api/config.py`.

### Commands to Stay Green
```bash
.venv/bin/python3.11 -m pytest tests/unit/test_engage_outcome_model.py -m unit -q
.venv/bin/python3.11 -m pytest tests/unit/test_scheduler_job_config.py -m unit -q
.venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py -q
ENGAGE_OUTCOME_CAPTURE_ENABLED=true \
  .venv/bin/python3.11 -m pytest tests/integration/test_engage_signal_acquisition.py -q
```

### Dependency Changes
No new packages. `sender.py` now depends on `ai_reply.CHAR_LIMITS`,
`detection_scanner._host_of`, and `engagement_tracker`. **Alembic head moved
`b7e4d21a9c58` → `c5a91f3e07d4`; re-derive live before chaining anything new.**
Phase 2 owes: `contact_bidx` + `blind_index()` + its `ERASURE_TARGETS` registration,
in one change. Phase 3a's DISTINCT-contact positive-rate depends on that.
