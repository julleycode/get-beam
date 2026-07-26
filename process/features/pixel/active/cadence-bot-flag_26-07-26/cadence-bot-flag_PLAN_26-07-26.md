---
name: plan:cadence-bot-flag
description: "Behavioral (non-UA) stealth-crawler detection: cadence-variance + engagement-mix dual signal, independent APScheduler batch sweep, visibility-only bot-suspect flag on Visitor/IdentifiedVisitor, structurally isolated from is_abuse_flagged/agent_visits/is_emailable_identity"
date: 26-07-26
feature: pixel
---

# Cadence Bot Flag — PLAN (COMPLEX-lite)

**Date**: 26-07-26
**Status**: PLAN — VALIDATE run (PVL pass 2, re-validation from V1). Gate: CONDITIONAL,
execute-eligible (1 completed supplement cycle resolved G1).
**Complexity**: COMPLEX-lite (migration + new service + scheduler job + API + web; single cohesive
design, no independent phase split needed — see INNOVATE strategy note in SPEC)

SPEC: `process/features/pixel/active/cadence-bot-flag_26-07-26/cadence-bot-flag_SPEC_26-07-26.md`
(14 ACs, all `proven by:`/`strategy:` tagged — locked, not re-opened here)

INNOVATE decision (chosen approach, verbatim from the approved Decision Summary):
- Independent APScheduler sweep job (own module, own interval setting), structural clone of the
  `_intent_signal_sweep_job` registration pattern (`apps/api/jobs/scheduler.py:415-462` block
  precedent) and the `agent_intent_signals.py` module shape (pure functions + thin DB-loop
  wrapper, fail-open per site/visitor).
- Dual signal: (a) cadence = coefficient of variation (stddev/mean) of inter-visit gaps from
  `events.created_at`; (b) engagement ratio = engagement-event-count / total-event-count. Both
  dual-precondition-gated (sample-size floor evaluated BEFORE ratio — mirrors
  `ingest_velocity.evaluate_velocity` shape). Binary conjunction fires the flag (AC-3).
- Storage: sticky boolean pair `visitors.is_bot_suspect` + `identified_visitors.is_bot_suspect`,
  mirroring the existing `is_abuse_flagged` two-table shape, OR-merge sticky semantics.
- Surfacing: new field on visitor API response + badge on detail page + list page badge/facet,
  following the `ai_source` "Arrived via" pill precedent exactly.
- Config: new `## ─── Cadence bot flag ───` settings block, default OFF, operator-tunable
  thresholds, bounded-read lookback cap (non-negotiable per vc-predict).
- Rejected: piggyback in `visitor_aggregator.py`'s incremental pass; Celery task; read-time
  computation; score/JSONB storage; separate verdict table; datacenter-ASN v1 signal.

## Phase Completion Rules

This plan is a single COMPLEX-lite unit (no phase split). It is `CODE DONE` when every checklist
item below is implemented and its own section's test gates pass locally. It is `VERIFIED` only
after: (a) all Fully-Automated unit gates are green, (b) the Hybrid integration gates are green on
a disposable Postgres+Redis (Docker-gated), (c) the migration is offline `--sql`-validated both
directions, and (d) AC-5/AC-6/AC-7 structural-isolation regression tests pass with zero changes to
existing `is_emailable_identity()` / `visitor_aggregator.py` FILTER / `agent_visits` behavior. Live
migration round-trip and AC-14 live-crawler validation are Known-Gaps carried to closeout — a
plan cannot be marked VERIFIED against those two items; they are explicitly deferred, not silently
dropped (see Known-Gaps section).

## Acceptance Criteria

This plan implements SPEC AC-1 through AC-14 verbatim (see SPEC file for full text and the
"SPEC AC → Step → Test Gate Traceability" table below for the authoritative per-criterion mapping).
Summary pass/fail bar: every `proven by:` test named in SPEC is green (AC-1–AC-13 as automated
Fully-Automated/Hybrid gates), AC-14 is tracked as an explicit Known-Gap requiring a post-deploy
operator verification step (not an automated gate), and zero regressions in
`is_emailable_identity()`, `visitor_aggregator.py`'s existing FILTER exclusions, or `agent_visits`
behavior (AC-5/AC-6/AC-7).

## Overview

Beam's four existing bot layers (`tracker.js` webdriver check, `bot_filter.py` UA regex,
`agent_classifier.py` self-declaring vendor list, `ingest_velocity.py` flood detector) all reason
about identity strings or short-window traffic shape — none look at *behavior over time*. A polite,
low-volume daily crawl with a convincing UA sails past all four and shows up in the dashboard as a
real "Returning" identified visitor. This plan adds a fifth, orthogonal signal computed in a batch
sweep over existing `events` rows: cadence-variance (is the visit schedule cron-like?) AND
engagement-mix (does the visitor ever do anything a script wouldn't bother faking?). Only the
conjunction of both trips the flag (AC-3), matching the existing dual-condition philosophy in
`ingest_velocity.evaluate_velocity`.

The single most important constraint in this plan (repeated from SPEC because it drives every
touchpoint below): the new `is_bot_suspect` flag is **visibility-only**. It must never set
`is_abuse_flagged` or `do_not_resolve`, never be read by `is_emailable_identity()`, never join the
`agent_visits` table, and never be added to any `FILTER (WHERE NOT is_flagged_abuse)` aggregate
exclusion. A real, wanted contact who also runs a bot against the site stays exactly as emailable
and exactly as counted as before — the only new thing is a badge.

## SPEC AC → Step → Test Gate Traceability

| AC | Requirement (summary) | Implementation step(s) | Test gate |
|---|---|---|---|
| AC-1 | Cadence-variance pure function | Step 3 (`cadence_bot_flag.py::compute_cadence_variance`) | `tests/unit/test_cadence_bot_flag.py::test_compute_cadence_variance_*` |
| AC-2 | Engagement-mix pure function | Step 3 (`compute_engagement_ratio`) | `tests/unit/test_cadence_bot_flag.py::test_compute_engagement_ratio_*` |
| AC-3 | Conjunction-only flag decision | Step 3 (`evaluate_cadence_bot_flag`), Step 4 (4-quadrant matrix) | `tests/unit/test_cadence_bot_flag.py::test_evaluate_quadrant_matrix` |
| AC-4 | Batch-only, zero ingest-path change | Step 5 (sweep module), Step 6 (scheduler registration — no `routers/events.py` edit) | `tests/integration/test_cadence_bot_flag.py::test_ingest_unaffected_by_new_module` |
| AC-5 | Structurally distinct from `is_abuse_flagged`/`agent_visits` | Step 3–7 (zero imports of `agent_visit.py`, zero writes to `is_abuse_flagged`) | `tests/unit/test_cadence_bot_flag.py::test_no_agent_visit_import`, grep-based code-level check in Step 11 |
| AC-6 | Does not change outreach eligibility | Step 9 (no 4th guard param added), regression proof | `tests/integration/test_cadence_bot_flag.py::test_is_emailable_identity_unaffected` |
| AC-7 | Does not distort existing aggregates | Step 8 (no `visitor_aggregator.py` FILTER edit) | `tests/integration/test_cadence_bot_flag.py::test_aggregation_output_unchanged` |
| AC-8 | Detail-page badge | Step 12 | Agent-Probe manual render check (reclassified from Hybrid, PVL supplement cycle 1 — see Known-Gaps #4; `apps/web` has no component-test infra) |
| AC-9 | List-page badge | Step 13 | Agent-Probe manual render check (reclassified from Fully-Automated, PVL supplement cycle 1 — see Known-Gaps #4; `apps/web` has no component-test infra) |
| AC-10 | New API field | Step 10 | `tests/integration/test_cadence_bot_flag.py::test_visitor_detail_serializes_is_bot_suspect` |
| AC-11 | Config default OFF, tunable thresholds | Step 1 | `tests/unit/test_cadence_bot_flag.py::test_flag_disabled_is_noop`, `test_thresholds_read_from_settings` |
| AC-12 | No PII in logs | Step 5 (structlog call sites) | `tests/unit/test_cadence_bot_flag.py::test_no_pii_in_log_calls` (mirrors `test_ingest_abuse_no_pii_logging.py` pattern) |
| AC-13 | False-positive: rigid+engaged never flags | Step 4 (quadrant matrix, "power user" case) | `tests/unit/test_cadence_bot_flag.py::test_rigid_engaged_power_user_not_flagged` |
| AC-14 | Known-gap: live-crawler validation | Step 15 (operator verification runbook) | Agent-Probe/Known-Gap — documented operator step, not an automated gate; carried to closeout |

Non-negotiable constraints (vc-predict, both apply across every step touching the sweep):
bounded-read lookback cap (`cadence_bot_flag_lookback_days`) and an explicit minimum-event/
minimum-visit-count floor evaluated BEFORE any ratio math — never an unbounded full-`events`-table
scan per sweep tick.

## Touchpoints

| File | Change |
|---|---|
| `apps/api/services/cadence_bot_flag.py` (NEW) | Pure functions: `compute_cadence_variance`, `compute_engagement_ratio`, `evaluate_cadence_bot_flag` (conjunction decision) — no I/O, DB-free, mirrors `ingest_velocity.evaluate_velocity` shape |
| `apps/api/services/cadence_bot_flag_sweep.py` (NEW) | Thin per-site/per-visitor DB-loop wrapper: bounded-window query over `events`, calls the pure functions, fail-open per visitor/site, sticky OR-merge write to `Visitor.is_bot_suspect` / `IdentifiedVisitor.is_bot_suspect`. Mirrors `agent_intent_signals.py` module shape (pure functions + thin wrapper) |
| `apps/api/jobs/scheduler.py` | New `_cadence_bot_flag_sweep_job()` async wrapper (structural clone of `_intent_signal_sweep_job`, lines ~190-199) + new `scheduler.add_job(...)` registration block (structural clone of the `_intent_signal_sweep_job` registration at lines 434-441), gated by `settings.cadence_bot_flag_enabled` |
| `apps/api/config.py` | New `## ─── Cadence bot flag ───` settings block (Step 1) — default OFF + tunable thresholds + lookback cap + sweep interval |
| `apps/api/models/visitor.py` | New column `Visitor.is_bot_suspect: bool` (default False, server_default "false", nullable False) — added near `is_abuse_flagged` (~line 76) with an explicit comment distinguishing it; new column `IdentifiedVisitor.is_bot_suspect: bool` (same shape, near ~line 113) |
| `apps/api/migrations/versions/<new>_add_cadence_bot_flag.py` (NEW) | Additive: 2 new boolean columns, default false, server_default "false", not nullable. Chains onto the LIVE-RECONFIRMED head (re-run `alembic heads` before writing — see Step 2) |
| `apps/api/schemas/visitors.py` | New field `is_bot_suspect: bool = False` on `VisitorOut` (inherited by `VisitorDetailOut`, `VisitorListResponse` row schema) |
| `apps/api/routers/visitors.py` | No new endpoint — `VisitorOut.model_validate(visitor)` already serializes new ORM columns automatically since `model_config = {"from_attributes": True}"`; verify no manual dict-construction path drops the field (checked at `get_visitor_detail` ~line 588 and the list endpoint) |
| `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` | New badge/pill near the `ai_source` pill block (~lines 472-477, 830), following identical visual pattern, distinct copy ("Bot-suspect" / tooltip explaining cadence+engagement basis) |
| `apps/web/src/app/dashboard/visitors/page.tsx` | New per-row badge in the list (structural clone of `ai_source` list-facet pattern at lines 81, 139, 183-185, 562-563, 670-675) — badge only in v1 (no new filter facet required by SPEC; facet is a stretch, not an AC) |
| `tests/unit/test_cadence_bot_flag.py` (NEW) | AC-1, AC-2, AC-3, AC-11, AC-12, AC-13 |
| `tests/integration/test_cadence_bot_flag.py` (NEW) | AC-4, AC-5, AC-6, AC-7, AC-10 |
| `apps/web` component test file (co-located with existing visitor list/detail test precedent, if any — else new `apps/web/src/app/dashboard/visitors/__tests__/cadence-badge.test.tsx`) | AC-8, AC-9 |

## Public Contracts

- `GET /api/v1/visitors/{site_id}/{visitor_id}` (`VisitorDetailOut`) — new field `is_bot_suspect: bool`
  added, default `False`. Additive, backward-compatible — no existing field renamed/removed.
- `GET /api/v1/visitors/{site_id}` (`VisitorListResponse` row schema, `VisitorOut`) — same new field,
  same default. Additive.
- No new route. No change to `POST /api/v1/events/ingest` request/response shape (AC-4 hard
  requirement — verified by an integration test asserting ingest behavior is byte-identical with
  the new module present but its sweep never invoked).
- New APScheduler job `cadence_bot_flag_sweep`, gated behind `settings.cadence_bot_flag_enabled`
  (default `False`) — dormant unless explicitly enabled by an operator post-migration-live-apply,
  matching the `agent_detection_enabled` rollout posture exactly.
- New DB columns: `visitors.is_bot_suspect`, `identified_visitors.is_bot_suspect` — both
  `bool NOT NULL DEFAULT false`. No FK, no index required for v1 (read pattern is per-visitor
  point lookups already covered by existing PK/unique indexes — no new query pattern introduced
  that needs a dedicated index).

## Blast Radius

- **Risk class:** none of auth/billing/schema-destructive/public-API-breaking/deploy — this is an
  additive analytics signal. The one high-risk-adjacent surface is a **schema migration**
  (additive-only, nullable-false-with-default, non-destructive) — Hybrid tier minimum applies per
  `vc-test-coverage-plan` High-Risk Classes table.
- **Files touched:** 2 new backend service modules, 1 new migration, 1 model file edit (2 columns),
  1 scheduler registration edit, 1 config edit, 1 schema edit, 2 web page edits, 3 new test files
  (1 unit, 1 integration, 1 web component) = ~11 touchpoint files. Below the 5+-file HIGH-fan-out
  threshold on its own dimension but the schema/migration signal is present — see Strategy
  Recommendation below for the VALIDATE fan-out call.
- **Packages:** `apps/api` (backend, majority of the work), `apps/web` (2 dashboard page edits).
  No `apps/pixel`, `apps/extension` changes — confirmed zero client-side surface per SPEC Out of
  Scope ("No new client-side detection probes").
- **Structural non-overlap guarantee (AC-5/AC-6/AC-7):** this plan's blast radius deliberately
  EXCLUDES `apps/api/services/identity_classification.py` (no 4th guard param added),
  `apps/api/services/visitor_aggregator.py` (no FILTER clause edit), `apps/api/models/agent_visit.py`
  (zero import), `apps/api/services/ingest_velocity.py` (zero import/dependency — parallel sibling,
  not a caller), and `apps/api/routers/events.py` (zero edit — AC-4).

## Implementation Checklist

### Step 0 — Re-verify migration head (mandatory pre-flight, run every session before Step 2)

0. Run `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` from repo root. Confirm a
   single head (expected `d5b1f7c3a908` as of 26-07-26, per concurrent-migration-collision
   precedent — other work may have advanced it further). Record the actual current head in the
   migration file's docstring exactly as the `d5b1f7c3a908` precedent does. **Verification:** command
   exits 0, output shows exactly one head.

### Step 1 — Config settings (AC-11)

1. In `apps/api/config.py`, add a new `## ─── Cadence bot flag ───` block (place after the
   `## ─── Ingest abuse hardening (P1–P5) ───` block or after the most recent feature-flag block —
   confirm exact insertion point at implementation time via `grep -n "## ───" apps/api/config.py`).
   Add:
   - `cadence_bot_flag_enabled: bool = False` — default OFF, operator-gated (matches
     `agent_detection_enabled` precedent). Inline comment: enabling requires the migration below to
     be live-applied first.
   - `cadence_bot_flag_sweep_interval_minutes: int = 60` — sweep cadence, mirrors
     `aggregation_sweep_interval_minutes` default.
   - `cadence_bot_flag_lookback_days: int = 90` — **non-negotiable bounded-read cap** (vc-predict
     constraint). Inline comment explaining why this exists: without a cap, a visitor with years of
     history would force an unbounded `events` scan per sweep tick.
   - `cadence_bot_flag_min_visits: int = 5` — minimum distinct-visit-day floor, evaluated BEFORE
     variance math (mirrors `ingest_velocity_visitor_threshold` precondition-before-ratio shape).
     Below this floor, `evaluate_cadence_bot_flag` returns `False` unconditionally — not enough data
     to judge cadence.
   - `cadence_bot_flag_max_variance_threshold: float = 0.15` — coefficient-of-variation ceiling
     below which a visit schedule is considered "cron-like" (operator-tunable, no hardcoded magic
     number in the detection module itself).
   - `cadence_bot_flag_max_engagement_ratio: float = 0.05` — engagement-ratio ceiling below which
     a visitor's sessions are considered "pageview-only" (operator-tunable).
   - Inline rollout-order comment (matching the `ingest_velocity_enabled` / `site_ingest_limit_enabled`
     precedent style): enable only after the migration (Step 2) is live-applied; tune thresholds
     against real event-history samples before flipping `cadence_bot_flag_enabled` in a real
     environment.
   **Verification:** `grep -n "cadence_bot_flag_enabled" apps/api/config.py` returns the new field;
   `python3.11 -c "from apps.api.config import settings; assert settings.cadence_bot_flag_enabled is False"`
   passes.

### Step 2 — Migration (AC-11 dependency, Constraints)

2. Author `apps/api/migrations/versions/<hash>_add_cadence_bot_flag.py` per `vc-docs-seeker`-confirmed
   Alembic `op.add_column` syntax (same signature as the `d5b1f7c3a908` precedent read above — no
   new API surface to confirm, this is a stable, already-used pattern in this repo):
   - `revision` = new short hash (8 lowercase hex chars, matching repo convention)
   - `down_revision` = the ACTUAL head confirmed in Step 0 (not a guessed/hardcoded value)
   - `upgrade()`: `op.add_column("visitors", sa.Column("is_bot_suspect", sa.Boolean(), nullable=False, server_default=sa.false()))`
     + same for `"identified_visitors"`
   - `downgrade()`: `op.drop_column("visitors", "is_bot_suspect")` + same for `"identified_visitors"`
   - Docstring: state additive-only, non-destructive, OFFLINE-VALIDATED ONLY at this stage (never
     live-apply as part of this plan), matching the `d5b1f7c3a908` docstring convention exactly.
   **Verification (offline, no live DB required):**
   ```bash
   .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head --sql > /tmp/cadence_up.sql
   .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini downgrade -1 --sql > /tmp/cadence_down.sql
   ```
   Both commands exit 0; `/tmp/cadence_up.sql` contains two `ALTER TABLE ... ADD COLUMN ... is_bot_suspect BOOLEAN NOT NULL DEFAULT false` statements; `/tmp/cadence_down.sql` contains two matching `DROP COLUMN` statements. Live round-trip on a disposable Postgres is a Known-Gap (see Known-Gaps section) — do NOT attempt a live `alembic upgrade` against any real or shared DB as part of this plan.

### Step 3 — Pure detection functions (AC-1, AC-2, AC-3, AC-13)

3. Create `apps/api/services/cadence_bot_flag.py`:
   - `compute_cadence_variance(visit_timestamps: list[datetime]) -> float | None` — pure, no I/O.
     Computes inter-visit gaps (consecutive timestamp deltas in seconds), returns coefficient of
     variation (`stddev(gaps) / mean(gaps)`). Returns `None` if fewer than 2 gaps are computable
     (mirrors the `min_visits` floor — the sweep wrapper checks this before calling, per Step 5).
   - `compute_engagement_ratio(event_types: list[str]) -> float` — pure, no I/O. Ratio of
     engagement-event-count (`{"click", "scroll", "time_on_page", "conversion"}`, matching
     `tracker.js:243,263,283,374,538,552,557` emitted types) to `len(event_types)`. Returns `0.0`
     for an empty list (never divides by zero).
   - `evaluate_cadence_bot_flag(variance: float | None, engagement_ratio: float, min_visits_met: bool, max_variance_threshold: float, max_engagement_ratio: float) -> bool` —
     pure decision function, structural sibling of `ingest_velocity.evaluate_velocity`. Returns
     `False` immediately if `not min_visits_met` or `variance is None` (precondition-before-ratio,
     matching AC-3/AC-13's dual-gate design). Otherwise returns
     `variance <= max_variance_threshold and engagement_ratio <= max_engagement_ratio` (conjunction
     — AC-3).
   **Verification:** module has zero imports from `apps.api.models.agent_visit` or any DB session
   type (AC-5 structural check, run at Step 11).

### Step 4 — Unit test matrix (AC-1, AC-2, AC-3, AC-11, AC-12, AC-13)

4. Create `tests/unit/test_cadence_bot_flag.py` (`pytestmark = pytest.mark.unit`, mirrors
   `tests/unit/test_ingest_velocity.py` structure):
   - `test_compute_cadence_variance_cron_like` — synthetic near-identical-gap series → low CV
   - `test_compute_cadence_variance_organic` — synthetic human-jitter series → high CV
   - `test_compute_cadence_variance_insufficient_data` — 0 or 1 timestamp → `None`
   - `test_compute_engagement_ratio_pageview_only` — all-pageview series → `0.0`
   - `test_compute_engagement_ratio_mixed` — mixed series → expected ratio
   - `test_evaluate_quadrant_matrix` — parametrized over the 4 quadrants (rigid+engaged,
     rigid+low-engagement, irregular+engaged, irregular+low-engagement); asserts ONLY
     rigid+low-engagement returns `True` (AC-3)
   - `test_rigid_engaged_power_user_not_flagged` — explicit named "power user" fixture: rigid daily
     schedule (low CV) but high engagement ratio → `False` (AC-13, restated as its own named test
     per SPEC's explicit false-positive framing, not merely a quadrant-matrix row)
   - `test_min_visits_floor_unmet` — fewer than `cadence_bot_flag_min_visits` distinct visit days →
     `False` regardless of variance/engagement values
   - `test_flag_disabled_is_noop` — with `cadence_bot_flag_enabled=False`, the sweep wrapper
     (Step 5) never calls the pure functions / never writes (mocked/spied call-count assertion)
   - `test_thresholds_read_from_settings` — asserts `evaluate_cadence_bot_flag` callers pass
     `settings.cadence_bot_flag_max_variance_threshold` / `..._max_engagement_ratio`, not literals
   - `test_no_pii_in_log_calls` — asserts every `structlog` call site in `cadence_bot_flag_sweep.py`
     passes only `site_id`, `visitor_id`, counts, and computed signal values as kwargs (mirrors
     `test_ingest_abuse_no_pii_logging.py` pattern — reflect over the module's log call sites)
   **Verification:**
   ```bash
   .venv/bin/python3.11 -m pytest tests/unit/test_cadence_bot_flag.py -m unit -v
   ```
   All tests pass (0 failures).

### Step 5 — Sweep wrapper (AC-4, AC-5, AC-12, bounded-read constraint)

5. Create `apps/api/services/cadence_bot_flag_sweep.py`:
   - `async def run_cadence_bot_flag_sweep(db: AsyncSession) -> dict` — top-level entrypoint, mirrors
     `agent_intent_signals.py` module shape (fail-open per site/visitor — one visitor's failure never
     blocks the rest of the sweep, matching `agent_handoff_correlation.run_handoff_correlation_sweep`
     precedent).
   - Query pattern: per site, per visitor with `events.created_at >= now() - cadence_bot_flag_lookback_days`
     (the bounded-read cap — **never** an unbounded full-history scan). Group by `visitor_id`,
     collect `created_at` timestamps + `event_type` list per visitor within the lookback window.
   - Evaluate `min_visits_met = distinct_visit_days >= settings.cadence_bot_flag_min_visits` BEFORE
     calling `compute_cadence_variance` (precondition-before-ratio, matches Step 3 design).
   - On a positive flag decision: sticky OR-merge write — `UPDATE visitors SET is_bot_suspect = true WHERE ... AND NOT is_bot_suspect` (never un-flag on a later clean window, matching `is_abuse_flagged`
     sticky semantics) + same pattern on `identified_visitors` when a matching row exists (LEFT JOIN
     by `(site_id, visitor_id)`, matching the existing `is_abuse_flagged` copy-at-write pattern).
   - Log line on flag-set: `logger.info("cadence_bot_flag_set", site_id=..., visitor_id=..., variance=..., engagement_ratio=..., distinct_visit_days=...)` — counts/ids/computed-values only, zero
     PII (AC-12).
   - **Zero imports** of `apps.api.models.agent_visit` (AC-5) — this module never touches
     `agent_visits`.
   **Verification:** module-level `grep -c "agent_visit" apps/api/services/cadence_bot_flag_sweep.py`
   returns 0 (excluding this comment text itself, checked manually).

### Step 6 — Scheduler registration (AC-4)

6. In `apps/api/jobs/scheduler.py`:
   - Add `async def _cadence_bot_flag_sweep_job() -> None:` (structural clone of
     `_intent_signal_sweep_job`, ~lines 190-199) — guarded by `if not settings.cadence_bot_flag_enabled: return` at the top (no-op path when the flag is off), then opens an `async_session()` and calls
     `run_cadence_bot_flag_sweep(db)`.
   - Add the `scheduler.add_job(...)` registration block (structural clone of the
     `_intent_signal_sweep_job` registration, ~lines 434-441): `id="cadence_bot_flag_sweep"`,
     `minutes=settings.cadence_bot_flag_sweep_interval_minutes`, `replace_existing=True`,
     `jitter=90` (consistent with the other ~60min-class jobs), `misfire_grace_time=300`.
   - **No edit to `routers/events.py` or any ingest write path** — this is the AC-4 hard constraint;
     confirm via `git diff --stat` at Step 11 that `routers/events.py` has zero lines changed by this
     plan.
   **Verification:** `python3.11 -c "import apps.api.jobs.scheduler"` imports cleanly (no syntax
   error); manual review confirms the new job is gated behind the settings flag exactly like every
   other conditional job in the file (e.g. `agent_verification_sweep`, `changelog_sync`).

### Step 7 — Model columns (dependency for Steps 2, 5, 9, 10)

7. In `apps/api/models/visitor.py`: add `is_bot_suspect: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)` to `Visitor` (near `is_abuse_flagged`, ~line 76)
   and to `IdentifiedVisitor` (near ~line 113). Comment on both: "Cadence bot flag (visibility-only,
   see cadence_bot_flag.py) — structurally independent of is_abuse_flagged; never read by
   is_emailable_identity(); never excluded from any aggregate FILTER clause." This inline comment is
   itself part of the AC-5 evidence trail (matches the existing self-documenting comment style at
   `is_abuse_flagged`'s own definition).
   **Verification:** `python3.11 -c "from apps.api.models.visitor import Visitor, IdentifiedVisitor; assert hasattr(Visitor, 'is_bot_suspect'); assert hasattr(IdentifiedVisitor, 'is_bot_suspect')"`
   passes.

### Step 8 — Regression proof: aggregator untouched (AC-7)

8. **No code change** to `apps/api/services/visitor_aggregator.py` — this step is a verification-only
   checklist item, not an implementation item. Confirm via `git diff --stat apps/api/services/visitor_aggregator.py` shows zero lines changed by this plan's branch/commits.
   **Verification:** `tests/integration/test_cadence_bot_flag.py::test_aggregation_output_unchanged`
   constructs a visitor with `is_bot_suspect=True`, runs `aggregate_visitors_for_site`, and asserts
   the output is bit-for-bit identical to the same visitor's aggregation output with the flag unset
   (mirrors SPEC AC-7's exact `proven by:` language).

### Step 9 — Regression proof: outreach eligibility untouched (AC-6)

9. **No code change** to `apps/api/services/identity_classification.py`,
   `apps/api/services/campaign_sender.py`, `apps/api/services/csv_exporter.py`, or
   `apps/api/routers/campaigns.py` — verification-only item. `is_emailable_identity()`'s signature
   stays exactly `(provider, source_agent_visit_id=None, is_abuse_flagged=False)` — no 4th
   parameter added.
   **Verification:**
   ```bash
   .venv/bin/python3.11 -m pytest tests/integration/test_cadence_bot_flag.py::test_is_emailable_identity_unaffected -m integration -v
   ```
   Constructs an `IdentifiedVisitor` with `is_bot_suspect=True`, a person-level provider, and no
   agent/abuse markers; asserts `is_emailable_identity(provider, None, False)` still returns `True`
   (unaffected by the new column's presence). Also asserts `inspect.signature(is_emailable_identity).parameters` has exactly 3 parameters (structural guard against silent signature drift).

### Step 10 — API schema + serialization (AC-10)

10. In `apps/api/schemas/visitors.py`: add `is_bot_suspect: bool = False` to `VisitorOut` (inherited
    automatically by `VisitorDetailOut` and the `VisitorListResponse` row type, matching how
    `ai_source` is defined once on the base class). No router code change needed — confirm
    `VisitorOut.model_validate(visitor)` (used at `routers/visitors.py` ~line 588) picks up the new
    ORM column automatically via `model_config = {"from_attributes": True}`.
    **Verification:**
    ```bash
    .venv/bin/python3.11 -m pytest tests/integration/test_cadence_bot_flag.py::test_visitor_detail_serializes_is_bot_suspect -m integration -v
    ```
    Asserts a `GET /api/v1/visitors/{site_id}/{visitor_id}` response includes `is_bot_suspect: true`
    for a flagged fixture and `is_bot_suspect: false` for an unflagged one.

### Step 11 — AC-5 structural-isolation code-level check

11. Run and record:
    ```bash
    grep -rn "agent_visit" apps/api/services/cadence_bot_flag.py apps/api/services/cadence_bot_flag_sweep.py
    grep -rn "is_abuse_flagged" apps/api/services/cadence_bot_flag.py apps/api/services/cadence_bot_flag_sweep.py
    git diff --stat apps/api/routers/events.py apps/api/services/visitor_aggregator.py apps/api/services/identity_classification.py
    ```
    **Verification:** first two greps return zero matches (no accidental cross-reference); third
    command shows zero changed lines in all three files. This is the AC-5/AC-6/AC-7 evidence bundle
    referenced by `tests/unit/test_cadence_bot_flag.py::test_no_agent_visit_import`.

### Step 12 — Detail page badge (AC-8)

12. In `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx`, add a badge/pill adjacent to the
    existing `ai_source` pill block (~lines 472-477 for the header pill, ~830 for the sidebar
    `InfoRow`), conditionally rendered on `visitor.is_bot_suspect`. Copy: "Bot-suspect" pill with a
    `title` tooltip explaining the cadence+engagement basis (mirrors the `ai_source` tooltip pattern
    exactly — `title={...explains the signal...}`). Use a distinct tone (e.g. `bg-warning-muted` /
    `text-warning`, NOT the same `bg-info-muted` used for `ai_source`, to visually distinguish an
    attribution pill from a caution pill).
    **Verification (reclassified — PVL supplement cycle 1, 26-07-26, see Known-Gaps #4):** Agent-Probe
    manual check — a reviewing agent loads the detail page against `is_bot_suspect: true` and
    `is_bot_suspect: false` fixtures/data and visually confirms the badge is present/absent
    respectively. No automated component-render test infrastructure exists in `apps/web` (see Test
    Infra Improvement Notes), so this gate is Agent-Probe, not the Fully-Automated/Hybrid tier
    originally stated in this step's prose.

### Step 13 — List page badge (AC-9)

13. In `apps/web/src/app/dashboard/visitors/page.tsx`, add the same badge inline per row (structural
    clone of the `ai_source` list-facet pill block at ~lines 562-563), conditionally rendered on
    `v.is_bot_suspect`. No new filter facet added in v1 (SPEC does not require a facet — badge only).
    **Verification (reclassified — PVL supplement cycle 1, 26-07-26, see Known-Gaps #4):** Agent-Probe
    manual check — a reviewing agent loads the list page against a mix of flagged/unflagged visitor
    fixtures and visually confirms the per-row badge is present only for `is_bot_suspect: true` rows.
    No automated component-render test infrastructure exists in `apps/web` (same gap as Step 12), so
    this gate is Agent-Probe, not Fully-Automated as originally stated in this step's prose.

### Step 14 — Integration test suite (AC-4, AC-5, AC-6, AC-7, AC-10)

14. Create `tests/integration/test_cadence_bot_flag.py` (Docker-gated, `pytestmark = pytest.mark.integration`, mirrors `tests/integration/test_ingest_abuse_hardening.py` structure):
    - `test_ingest_unaffected_by_new_module` — `POST /ingest` latency/behavior unchanged with the
      new module present but its sweep not yet run (AC-4)
    - `test_aggregation_output_unchanged` — AC-7 (see Step 8)
    - `test_is_emailable_identity_unaffected` — AC-6 (see Step 9)
    - `test_visitor_detail_serializes_is_bot_suspect` — AC-10 (see Step 10)
    - `test_sweep_flags_cron_like_low_engagement_visitor` — end-to-end: seed `events` rows matching
      the cron-like+pageview-only shape, run `run_cadence_bot_flag_sweep`, assert
      `Visitor.is_bot_suspect` and `IdentifiedVisitor.is_bot_suspect` (when identified) both become
      `True`
    - `test_sweep_does_not_flag_organic_visitor` — same seed pattern with organic/engaged shape,
      assert flag stays `False`
    - `test_sweep_respects_lookback_cap` — seed events both inside and outside
      `cadence_bot_flag_lookback_days`; assert the query only reads the bounded window (proof of
      the non-negotiable bounded-read constraint)
    **Verification:**
    ```bash
    .venv/bin/python3.11 -m pytest tests/integration/test_cadence_bot_flag.py -m integration -v
    ```
    Requires local Postgres+Redis per `TESTING.md` docker-compose setup. All tests pass.

### Step 15 — AC-14 Known-Gap operator runbook (documentation only, not a code gate)

15. Write a short operator-verification runbook (inline in this plan's Known-Gaps section, not a
    separate file) describing the one-time post-deploy check: run the sweep against the motivating
    case's real `site_id`/`visitor_id` once the feature is live-applied and enabled, compare the
    flag's verdict to the operator's own confirmation that this specific visitor is a bot. This is
    Agent-Probe/Known-Gap by SPEC design (AC-14) — not an automated test, and not blocking VERIFIED
    status for the rest of this plan.

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `tests/unit/test_cadence_bot_flag.py::test_compute_cadence_variance_cron_like` + `_organic` | Fully-Automated | AC-1 |
| `tests/unit/test_cadence_bot_flag.py::test_compute_engagement_ratio_pageview_only` + `_mixed` | Fully-Automated | AC-2 |
| `tests/unit/test_cadence_bot_flag.py::test_evaluate_quadrant_matrix` | Fully-Automated | AC-3 |
| `tests/integration/test_cadence_bot_flag.py::test_ingest_unaffected_by_new_module` | Fully-Automated (Docker-gated Hybrid precondition) | AC-4 |
| `tests/unit/test_cadence_bot_flag.py::test_no_agent_visit_import` + Step 11 grep bundle | Fully-Automated | AC-5 |
| `tests/integration/test_cadence_bot_flag.py::test_is_emailable_identity_unaffected` | Hybrid | AC-6 |
| `tests/integration/test_cadence_bot_flag.py::test_aggregation_output_unchanged` | Hybrid | AC-7 |
| Agent-Probe manual detail-page badge render check (reclassified, PVL supplement cycle 1 — see Known-Gaps #4) | Agent-Probe | AC-8 |
| Agent-Probe manual list-page badge render check (reclassified, PVL supplement cycle 1 — see Known-Gaps #4) | Agent-Probe | AC-9 |
| `tests/integration/test_cadence_bot_flag.py::test_visitor_detail_serializes_is_bot_suspect` | Hybrid | AC-10 |
| `tests/unit/test_cadence_bot_flag.py::test_flag_disabled_is_noop` + `test_thresholds_read_from_settings` | Fully-Automated | AC-11 |
| `tests/unit/test_cadence_bot_flag.py::test_no_pii_in_log_calls` | Fully-Automated | AC-12 |
| `tests/unit/test_cadence_bot_flag.py::test_rigid_engaged_power_user_not_flagged` | Fully-Automated | AC-13 |
| Operator runbook (Step 15) — one-time post-deploy verification against motivating-case data | Agent-Probe / Known-Gap | AC-14 |
| Migration offline `--sql` upgrade+downgrade dry run (Step 2) | Hybrid | Constraints §migration-additive |
| Live migration round-trip on disposable Postgres | Known-Gap (deferred, see Known-Gaps) | Constraints §migration-live-apply |

## High-Risk Class Table

| Area | High-risk class | Minimum tier | Gap rationale if known-gap accepted |
|---|---|---|---|
| Migration (2 additive boolean columns) | schema/migration | Hybrid (offline `--sql` validated both directions) | Live round-trip deferred as Known-Gap — rationale: no disposable Postgres available in this EXECUTE environment at plan-write time, matching the `c7d3b8e1f624` precedent; offline validation covers syntax correctness, not runtime constraint enforcement |

## Test Infra Improvement Notes

**VALIDATE finding (G1, 26-07-26):** `apps/web` has ZERO React component-render test
infrastructure today. `vitest.config.ts` is scoped `environment: "node"`,
`include: ["src/**/*.test.ts"]` only (its own header comment: "First JS unit runner in apps/web —
scoped to pure `src/lib` logic ... not the DOM"); no `@testing-library/react` or `jsdom` appears in
`apps/web/package.json` devDependencies; zero `.test.tsx` files exist anywhere in the repo. Steps
12–13's "component test" verification for AC-8/AC-9 assumes this infrastructure exists — it does
not. See `## Validate Contract` → Open gaps → G1 for the resolution options and the routed PVL
supplement. (This line replaces the prior "(none identified yet)" placeholder, which was
inaccurate.) **PVL pass 2 re-confirmation (26-07-26):** re-checked `vitest.config.ts` (still
`environment: "node"`, `include: ["src/**/*.test.ts"]` only), `apps/web/package.json`
devDependencies (still no `@testing-library/react`/`jsdom`), and a repo-wide `.test.tsx` search
(still 0 files) — the underlying fact this finding rests on is unchanged, so the Agent-Probe
reclassification below remains correctly grounded, not stale.

**Backlog candidate (recorded 26-07-26, not scheduled in this plan):** add
`@testing-library/react` + `jsdom` as new `apps/web` devDependencies plus a jsdom-scoped vitest
project/config (or a per-file `// @vitest-environment jsdom` pragma), extending
`vitest.config.ts`'s `include` glob to also match `src/**/*.test.tsx`. This would give `apps/web`
its first React component-render test capability, unblocking AC-8/AC-9-style component checks
project-wide — but building it here is out of scope for this plan (PVL-supplement mode forbids
introducing new test infrastructure as a side effect of an unrelated feature; see Known-Gaps #4).
Candidate for a dedicated future plan or backlog artifact.

## Known-Gaps (carried to closeout, never silently dropped)

1. **AC-14 — Live stealth-crawler validation.** The detection logic is proven against synthetic
   fixtures only (AC-1–AC-13). Whether the motivating-case crawler's real historical event data
   actually trips the flag in production is Agent-Probe/Known-Gap per SPEC design — requires a
   post-deploy operator step (Step 15 runbook) run once `cadence_bot_flag_enabled` is live and the
   migration is applied. This gate stays CONDITIONAL until that operator step runs; it is not a
   PASS-able automated gate.
2. **Migration live round-trip.** Offline `--sql` validation (Step 2) proves syntax correctness in
   both directions; a live `upgrade → downgrade -1 → upgrade` round-trip on a disposable Postgres
   has not been run as part of this plan (matches the `c7d3b8e1f624` / `b7d3e9f1a4c2` /
   `c8e4f2a6b1d9` / `d5b1f7c3a908` precedent — none of those 4 most-recent migrations are live-
   round-tripped either). Backlog note to be written at UPDATE PROCESS if this plan closes before a
   Docker-available session can run it.
3. **Playwright auth-harness leg for AC-8.** Full end-to-end detail-page rendering under a real
   Clerk-authenticated session is blocked on the same auth-harness gap noted for other pixel/
   ads-audiences UI ACs (Phase 1/2 precedent in `process/context/all-context.md`). Component-level
   render test (fixture-based, no auth) is Fully-Automated and covers the badge presence/absence
   logic; the full-session leg is Agent-Probe.
4. **AC-8/AC-9 — component-render test tier reclassified to Agent-Probe (PVL supplement cycle 1,
   26-07-26).** `apps/web` has zero React component-render test infrastructure today:
   `vitest.config.ts` is explicitly `environment: "node"`, `include: ["src/**/*.test.ts"]` only (its
   own header comment: "First JS unit runner in apps/web — scoped to pure `src/lib` logic ... not
   the DOM"); no `@testing-library/react` or `jsdom` appears in `apps/web/package.json`
   devDependencies; zero `.test.tsx` files exist anywhere in the repo. Per repo precedent — the
   `ai_source` badge (this feature's direct clone) shipped with no component tests, and the
   Playwright/Clerk auth-harness gap already blocks UI test legs on two prior programs
   (ads-audiences Phase 1 + Phase 2 AC7), both carried forward as env-only known-gaps — introducing
   new DOM-test infrastructure as a side effect of this unrelated feature would be scope expansion,
   which PVL-supplement mode forbids. Steps 12/13's badge-presence/absence logic is therefore proven
   only by Agent-Probe manual verification (see Steps 12/13 Verification and the C3 test-gate table),
   not by an automated Fully-Automated/Hybrid gate as originally stated. This gate stays CONDITIONAL
   until an agent performs the manual check — it is not silently accepted as PASS (vacuous-green
   ban). Building `@testing-library/react` + `jsdom` + a jsdom-scoped vitest project for `apps/web`
   is recorded as a backlog candidate in Test Infra Improvement Notes for a future, dedicated plan —
   not as a step of this plan. **PVL pass 2 re-confirmation (26-07-26):** this reclassification was
   spot-re-checked against the live repo (see Test Infra Improvement Notes re-confirmation above) and
   found still accurate — no regression, no stale claim. This known-gap does not block EXECUTE; the
   Agent-Probe manual check itself runs once Steps 12/13 are implemented (EXECUTE/EVL time), not
   during VALIDATE.

## AC-14 Operator Verification Runbook (Step 15 — post-deploy, one-time)

Run ONCE after the migration is live-applied and `cadence_bot_flag_enabled` is turned on. This is
the Agent-Probe/Known-Gap check that no synthetic fixture can substitute for.

1. **Preconditions.** `alembic heads` shows `e6b2d4a1c837` applied; `cadence_bot_flag_enabled=true`;
   thresholds reviewed against real event history (do NOT ship the `0.15` / `0.05` defaults blind —
   same "never ship the placeholder default live" posture as `site_ingest_limit_per_minute`).
2. **Pick the motivating case.** Record the real `site_id` + `visitor_id` of the crawler the
   operator has independently confirmed is a bot (out-of-band evidence: server logs, ASN, robots
   behavior).
3. **Run the sweep once** (or wait one `cadence_bot_flag_sweep_interval_minutes` tick) and read the
   structlog stream for `cadence_bot_flag_set` events. The log line carries
   `site_id / visitor_id / variance / engagement_ratio / distinct_visit_days` — no PII.
4. **Compare.** Did the known-bot visitor get `is_bot_suspect = true`?
   - Yes → AC-14 satisfied; record the observed `variance` / `engagement_ratio` as the first real
     calibration data point.
   - No → read its logged signal values. If `variance` is just above
     `cadence_bot_flag_max_variance_threshold`, tune the threshold up (never hardcode); if
     `engagement_ratio` is high, the crawler fakes engagement and the signal genuinely does not
     cover this case — record that as a real coverage limit, do not force-fit the thresholds.
5. **False-positive sweep.** List the flagged set for the site and eyeball it for known-human
   power users (the AC-13 case). Any human in the set means the thresholds are too loose.
6. **Safety re-confirm.** Spot-check that a flagged identity is still emailable and still counted
   in the dashboard totals — the flag is visibility-only by design, and a regression here is the
   single most important thing this runbook can catch.

## Execution Notes (EXECUTE, 26-07-26)

All 15 steps implemented. Migration head re-verified LIVE at Step 0 (`d5b1f7c3a908`, single head,
unchanged) and chained onto as `e6b2d4a1c837`; offline `--sql` validated both directions; NOT
live-applied. Gates: unit 25/25 green (mutation-kill verified — flipping the AC-3 conjunction to
`or` fails 3 tests), integration 7/7 green against a reachable local Postgres, full unit lane
602 passed / 2 skipped, web `tsc --noEmit` clean.

Deviations from the plan (all within blast radius, none touching a hard-stop surface):

1. **`tests/unit/test_scheduler_job_config.py` edited (file not listed in Touchpoints).** The
   pre-existing AC-13 tripwire asserts an exact `add_job` call count (12 total / 11 interval).
   Registering the new sweep job made it 13/12 and the test failed. The test's own failure message
   instructs re-deriving the arithmetic when a job is added ("do not relax this gate"), so the two
   counts were updated with a comment recording why. No assertion was weakened or removed.
2. **Offline `--sql` upgrade run as a scoped range (`upgrade d5b1f7c3a908:head --sql`) rather than
   `upgrade head --sql`.** The unscoped form fails inside the UNRELATED concurrent migration
   `b7d3e9f1a4c2_add_ad_connections.py`, which calls `sa.inspect(bind)` — unsupported against
   alembic's offline `MockConnection`. Pre-existing defect in another program's migration, not
   caused by or fixable within this plan. The scoped range validates exactly this plan's revision
   and produced the two expected `ADD COLUMN ... BOOLEAN DEFAULT false NOT NULL` statements;
   `downgrade -1 --sql` ran unscoped and clean.
3. **Sweep uses naive-UTC `datetime.utcnow()` for the lookback cutoff**, not the aware
   `datetime.now(timezone.utc)` the plan's prose implied. `events.created_at` is a naive `DateTime`
   column and asyncpg raises `DataError` on an aware bound parameter against it. Matches the
   existing naive-branch handling in `visitor_aggregator._decay_multiplier`. Caught by the
   integration gate, not by review.
4. **`apps/web/src/lib/api-types.ts` edited (file not listed in Touchpoints).** The `Visitor` TS
   interface needed `is_bot_suspect?: boolean` for the two badge sites to typecheck. Type-only,
   additive, optional.

Known-gaps confirmed still open at EXECUTE exit (4 carried, none resolved, none silently dropped):
AC-14 live-crawler validation; migration live round-trip; Playwright/Clerk auth-harness leg;
AC-8/AC-9 Agent-Probe manual render check — the badges now exist and are statically verified
(conditional render on `is_bot_suspect`, `bg-warning-muted`/`text-warning` tone tokens confirmed in
use elsewhere in the same files, `tsc` clean), but no agent has loaded the rendered pages, so the
AC-8/AC-9 gates remain CONDITIONAL and those two sections are NOT-ARCHIVABLE.

## Resume and Execution Handoff

1. **Selected plan file path:** `process/features/pixel/active/cadence-bot-flag_26-07-26/cadence-bot-flag_PLAN_26-07-26.md`
2. **Last completed phase or step:** VALIDATE PVL pass 2 complete 26-07-26 — Gate: CONDITIONAL,
   execute-eligible (1 completed supplement cycle resolved G1; see `## Validate Contract` below).
3. **Validate-contract status:** written 26-07-26 (pass 1), re-validated and updated 26-07-26
   (pass 2). Gate: CONDITIONAL, execute-eligible.
4. **Supporting context files loaded during PLAN:** `process/context/all-context.md`,
   `process/context/tests/all-tests.md` (routing chain followed — unit lane precedent
   `tests/unit/test_ingest_velocity.py`, integration lane precedent
   `tests/integration/test_ingest_abuse_hardening.py`), SPEC file (full read), plus direct reads of
   `apps/api/jobs/scheduler.py`, `apps/api/services/agent_intent_signals.py`,
   `apps/api/services/ingest_velocity.py`, `apps/api/models/visitor.py`,
   `apps/api/services/identity_classification.py`, `apps/api/config.py` (ingest-abuse settings
   block, verbatim precedent for the new config block), `apps/api/models/event.py`,
   `apps/api/schemas/visitors.py`, `apps/api/routers/visitors.py`, `apps/web/.../[visitorId]/page.tsx`,
   `apps/web/.../visitors/page.tsx`, `apps/api/migrations/versions/*d5b1f7c3a908*.py` (migration
   authoring precedent), `process/features/pixel/completed/ingest-abuse-hardening_25-07-26/` (plan
   structure precedent).
5. **Next step for a fresh agent picking up mid-execution:** VALIDATE PVL pass 2 confirms the plan
   is EXECUTE-ELIGIBLE. Proceed to EXECUTE at Step 0 (re-verify migration head is still
   `d5b1f7c3a908` or whatever the current live head is at that time — this is NOT assumed
   stale-safe across sessions, per the unbroken concurrent-migration-collision precedent). Run
   backend Fully-Automated/Hybrid gates first (Steps 1-11, 14), then implement Steps 12-13 (web
   badges) and perform the Agent-Probe manual render checks named in their Verification blocks.

## Current Execution State

- Current loop step: UPDATE PROCESS complete 26-07-26. EXECUTE (26-07-26, all 15 steps) and the
  mandatory EVL confirmation run (independent vc-tester, 26-07-26) are both done — ALL gates
  green (25 unit + 7 integration, 0 fix cycles), mutation-kill proved AC-3's conjunction
  non-vacuous. See `results.tsv` row 4 (`HALTED_SUCCESS`).
- Closeout classification: **Keep in active/testing** — this plan STAYS in `active/` and is NOT
  archived. 4 known-gaps are carried, none of which block EVL-green status but all of which block
  full archival: AC-8/AC-9 Agent-Probe manual render check not yet performed; AC-14 live-crawler
  validation (requires live production data, post-deploy); migration live round-trip
  (Docker-gated); Playwright/Clerk auth-harness leg. Full detail + operator go-live sequence:
  `process/features/pixel/backlog/cadence-bot-flag-deferred-gates_NOTE_26-07-26.md`.
- Previous loop step: PVL pass 2 (re-validation from V1) complete 26-07-26. G1 confirmed resolved
  and consistent across all plan sections. Execute-eligible.
- Validate-contract status: written 26-07-26 (pass 1, `Gate: CONDITIONAL` first-pass), re-validated
  and updated 26-07-26 (pass 2, `Gate: CONDITIONAL` — execute-eligible, 1 completed supplement
  cycle recorded in `results.tsv`). 2 cosmetic contract-wording corrections annotated in place at
  UPDATE PROCESS (26-07-26) — AC-5 grep-bundle "0 matches" wording and the migration offline
  `--sql` shorthand-vs-explicit-range wording — both bracketed `[EVL note, 26-07-26: ...]` inline,
  no history rewritten.

## Validate Contract

Status: CONDITIONAL (execute-eligible)
Date: 26-07-26 (PVL pass 2 — re-validation from V1 after PVL supplement cycle 1)
date: 2026-07-26
generated-by: outer-pvl
supersedes: 2026-07-26 (outer-pvl, PVL pass 1) — same-type outer-PVL re-validation cycle 2, run
after vc-plan-agent's PVL-supplement-mode fix (SUPPLEMENT_APPLIED received) resolved G1

Parallel strategy: sequential
Rationale: 2/7 signals present (S2 — schema/migration surface; S7 borderline at ~11 files, below
the 5+ HIGH threshold). Single cohesive design, one dominant risk class (additive migration), no
independent investigation branches — matches the plan's own INNOVATE/PLAN strategy recommendation.
A single sequential VALIDATE pass (this pass) covering V1–V7 is sufficient; confirmed via
`vc-agent-strategy-compare` re-scoring at V2 — no new signal surfaced that would raise the score.

### PVL Pass 2 — Re-Validation Summary (26-07-26)

V1 structural re-check: `node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs`
on this plan file returns 0 failures / 0 warnings (765 lines). All required sections present and
internally consistent.

G1 closure verification (the specific target of this pass): re-read every location in the plan
that references AC-8/AC-9's test-gate tier and confirmed all are consistently reclassified to
Agent-Probe with written rationale, and that no location still claims an automated
Fully-Automated/Hybrid component-render gate exists:
- SPEC AC → Step → Test Gate Traceability table (AC-8/AC-9 rows) — "Agent-Probe manual render
  check (reclassified from Hybrid/Fully-Automated, PVL supplement cycle 1 — see Known-Gaps #4)".
- Steps 12/13 Verification blocks — both explicitly say "(reclassified — PVL supplement cycle 1,
  26-07-26, see Known-Gaps #4)" and "No automated component-render test infrastructure exists in
  `apps/web`... this gate is Agent-Probe, not the Fully-Automated/Hybrid tier originally stated".
- Verification Evidence table (AC-8/AC-9 rows) — "Agent-Probe" strategy column, both rows.
- C3 test-gate table below (AC-8/AC-9 rows) — "Agent-Probe" strategy, gap-resolution `D`.
- Known-Gaps #4 — full written rationale (precedent: `ai_source` badge shipped without component
  tests; repo-wide Clerk auth-harness gap already blocks two prior programs' UI legs; new DOM-infra
  install would be scope expansion under PVL-supplement rules) plus an explicit non-vacuous-green
  statement: "This gate stays CONDITIONAL until an agent performs the manual check — it is not
  silently accepted as PASS."
- Test Infra Improvement Notes — G1 finding text plus the RTL/jsdom backlog candidate, both
  present and consistent with Known-Gaps #4.

No residual claim of an automated component test for AC-8/AC-9 was found anywhere in the plan.
No vacuous-green pattern: AC-8/AC-9 use Agent-Probe (one of the 3 legitimate proving strategies,
per C-4 reconciliation), not a bare Known-Gap with zero proving mechanism — and every occurrence
explicitly states the gate stays CONDITIONAL until the manual check is actually performed (at
EXECUTE/EVL time, once Steps 12-13 exist to check). This is why the net gate for this plan is
CONDITIONAL, not PASS — per the net-gate vacuous-green ban, a plan with any developed behavior
proven only by Agent-Probe cannot be a terminal PASS; CONDITIONAL with the residual named
explicitly is the correct and required classification.

Regression spot-check (verified 26-07-26, all match pass-1 findings — nothing drifted since PVL
pass 1):
- `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` → `d5b1f7c3a908 (head)` — single
  head, unchanged, matches the plan's Step 0/Step 2 assumption exactly.
- `apps/api/jobs/scheduler.py` — `_intent_signal_sweep_job` def block (~line 190) and its
  `scheduler.add_job(...)` registration block (~line 434-441) confirmed present and unchanged;
  still a valid structural clone target for Step 6.
- `apps/api/services/identity_classification.py:56` — `is_emailable_identity(provider,
  source_agent_visit_id=None, is_abuse_flagged=False)` — still exactly 3 parameters, unchanged.
- `apps/api/services/visitor_aggregator.py` — `FILTER (WHERE NOT is_flagged_abuse)` clauses
  confirmed present (5 occurrences, lines 255-303 range) and unchanged; Step 8's "no code change to
  this file" claim remains structurally sound.

Conclusion: 0 new FAILs, 0 new CONCERNs. The 3 pre-existing known-gaps (AC-14, migration live
round-trip, Playwright auth-harness leg) plus the newly-formalized 4th known-gap (AC-8/AC-9
Agent-Probe reclassification) are the only residuals — all pre-accepted, all named, all carried
with written rationale. G1 as an *active, unresolved* CONCERN is closed.

### Test gates (C3 5-column table)

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 | `compute_cadence_variance` distinguishes cron-like (low CV) from organic (high CV) inter-visit gaps; `None` on <2 gaps | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_cadence_bot_flag.py::test_compute_cadence_variance_cron_like tests/unit/test_cadence_bot_flag.py::test_compute_cadence_variance_organic tests/unit/test_cadence_bot_flag.py::test_compute_cadence_variance_insufficient_data -m unit -v` | A |
| AC-2 | `compute_engagement_ratio` returns 0.0 for pageview-only, correct ratio for mixed | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_cadence_bot_flag.py::test_compute_engagement_ratio_pageview_only tests/unit/test_cadence_bot_flag.py::test_compute_engagement_ratio_mixed -m unit -v` | A |
| AC-3 | Flag fires only on rigid-cadence AND low-engagement conjunction (4-quadrant matrix) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_cadence_bot_flag.py::test_evaluate_quadrant_matrix -m unit -v` | A |
| AC-4 | Batch-only detection; `POST /ingest` byte-identical with module present, sweep not yet run | Hybrid — precondition: local Postgres+Redis (`docker compose -f infra/docker-compose.yml up -d postgres redis`) | `.venv/bin/python3.11 -m pytest tests/integration/test_cadence_bot_flag.py::test_ingest_unaffected_by_new_module -m integration -v` | A |
| AC-5 | Zero `agent_visit` import, zero `is_abuse_flagged` write in the two new modules | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_cadence_bot_flag.py::test_no_agent_visit_import -m unit -v` plus Step 11 grep bundle: `grep -rn "agent_visit" apps/api/services/cadence_bot_flag.py apps/api/services/cadence_bot_flag_sweep.py` (**[EVL note, 26-07-26: the literal "0 matches required" wording is imprecise — the grep bundle does surface 2 docstring-prose negation mentions, e.g. "never touches agent_visits"; the substantive check is 0 import-statement matches, which EVL confirmed]**) | A |
| AC-6 | `is_bot_suspect=True` does not change `is_emailable_identity()` result; signature stays exactly 3 params | Hybrid — precondition: local Postgres+Redis | `.venv/bin/python3.11 -m pytest tests/integration/test_cadence_bot_flag.py::test_is_emailable_identity_unaffected -m integration -v` | A |
| AC-7 | Aggregation output for a flagged visitor is bit-for-bit identical to unflagged | Hybrid — precondition: local Postgres+Redis | `.venv/bin/python3.11 -m pytest tests/integration/test_cadence_bot_flag.py::test_aggregation_output_unchanged -m integration -v` | A |
| AC-8 | Detail-page badge renders conditionally on `visitor.is_bot_suspect` | Agent-Probe (reclassified from Hybrid, PVL supplement cycle 1 — see Known-Gaps #4; component-render infra does not exist in `apps/web`; re-confirmed accurate at PVL pass 2) | Manual agent verification: load detail page with `is_bot_suspect: true`/`false` fixtures or data, confirm badge present/absent | D — backlog test-building stub (RTL/jsdom infra, see Test Infra Improvement Notes); gate stays CONDITIONAL until manual check performed |
| AC-9 | List-page badge renders per-row on `v.is_bot_suspect` | Agent-Probe (reclassified from Fully-Automated, PVL supplement cycle 1 — see Known-Gaps #4; same missing infra as AC-8; re-confirmed accurate at PVL pass 2) | Manual agent verification: load list page with mixed flagged/unflagged fixtures or data, confirm per-row badge presence/absence | D — backlog test-building stub (RTL/jsdom infra, see Test Infra Improvement Notes); gate stays CONDITIONAL until manual check performed |
| AC-10 | New `is_bot_suspect: bool` field serializes on visitor detail response | Hybrid — precondition: local Postgres+Redis | `.venv/bin/python3.11 -m pytest tests/integration/test_cadence_bot_flag.py::test_visitor_detail_serializes_is_bot_suspect -m integration -v` | A |
| AC-11 | `cadence_bot_flag_enabled=False` is a no-op; thresholds read from `settings`, never literals | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_cadence_bot_flag.py::test_flag_disabled_is_noop tests/unit/test_cadence_bot_flag.py::test_thresholds_read_from_settings -m unit -v` | A |
| AC-12 | No PII in any new `structlog` call site | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_cadence_bot_flag.py::test_no_pii_in_log_calls -m unit -v` | A |
| AC-13 | Rigid-but-engaged "power user" is never flagged | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_cadence_bot_flag.py::test_rigid_engaged_power_user_not_flagged -m unit -v` | A |
| AC-14 | Live stealth-crawler validation against real production event history | Agent-Probe | Operator runbook (Step 15) — one-time post-deploy check against the motivating case's real `site_id`/`visitor_id` | D — pre-accepted known-gap (SPEC-level, cannot be automated; requires real production data) |
| Constraint — migration additive-only | Offline `--sql` upgrade+downgrade dry run proves syntax correctness both directions | Hybrid — precondition: none (fully offline) | `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head --sql > /tmp/cadence_up.sql` then `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini downgrade -1 --sql > /tmp/cadence_down.sql` — both exit 0, correct `ADD COLUMN`/`DROP COLUMN` statements present (**[EVL note, 26-07-26: `upgrade head --sql`/`downgrade -1 --sql` shorthand FAILS in this repo's `env.py` — an explicit `<from-rev>:<to-rev>` range is required, e.g. `upgrade d5b1f7c3a908:head --sql`; see Execution Notes deviation 2 and the `all-tests.md` gotcha added at UPDATE PROCESS]**) | A |
| Constraint — migration live-apply | Live `upgrade → downgrade -1 → upgrade` round-trip on a disposable Postgres | Agent-Probe (requires a live disposable DB; no dry-run substitute proves runtime constraint enforcement) | Deferred — no disposable Postgres available in this environment, matches the `c7d3b8e1f624`/`b7d3e9f1a4c2`/`c8e4f2a6b1d9`/`d5b1f7c3a908` precedent (none of the 4 most recent migrations are live-round-tripped either) | D — pre-accepted known-gap; backlog note at UPDATE PROCESS if unresolved at closeout |

gap-resolution legend:
- A — proven now (gate passes in this cycle once implemented)
- B — fixed in this plan (gate added by this plan's checklist, via the supplement cycle below)
- C — deferred to a named later phase/plan (repo-wide Clerk auth-harness gap, tracked elsewhere)
- D — backlog test-building stub (named residual; keep-active; continue)

C-4 reconciliation: `strategy:` column carries only Fully-Automated / Hybrid / Agent-Probe.
Known-Gap is never a strategy value — AC-14 and the migration live-apply row use Agent-Probe
as their strategy (closest of the 3) with gap-resolution D carrying the residual.

### Failing stubs (Fully-Automated rows only — Python-adapted per repo test runner; JS form used for the one frontend row)

AC-1:
```python
def test_should_distinguish_cron_like_from_organic_cadence():
    raise NotImplementedError("NOT IMPLEMENTED — TDD stub: compute_cadence_variance returns low CV for a cron-like series and high CV for an organic/human-jitter series; None on <2 gaps")
```

AC-2:
```python
def test_should_compute_engagement_ratio_from_event_types():
    raise NotImplementedError("NOT IMPLEMENTED — TDD stub: compute_engagement_ratio returns 0.0 for a pageview-only series and the correct ratio for a mixed-engagement series")
```

AC-3:
```python
def test_should_flag_only_on_conjunction_of_both_signals():
    raise NotImplementedError("NOT IMPLEMENTED — TDD stub: evaluate_cadence_bot_flag returns True ONLY for the rigid-cadence + low-engagement quadrant; the other 3 quadrants return False")
```

AC-5:
```python
def test_should_have_zero_agent_visit_or_abuse_flag_references():
    raise NotImplementedError("NOT IMPLEMENTED — TDD stub: cadence_bot_flag.py and cadence_bot_flag_sweep.py contain zero imports of agent_visit.py and zero writes to is_abuse_flagged")
```

AC-9 (frontend, JS — BLOCKED pending G1):
```
test("should render bot-suspect badge per row when v.is_bot_suspect is true", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: BLOCKED pending test-infra supplement (no @testing-library/react / jsdom vitest project exists yet in apps/web — see Open gaps G1)")
})
```

AC-11:
```python
def test_should_be_noop_when_feature_flag_disabled():
    raise NotImplementedError("NOT IMPLEMENTED — TDD stub: with cadence_bot_flag_enabled=False, the sweep wrapper never calls the pure detection functions and never writes")

def test_should_read_thresholds_from_settings_not_literals():
    raise NotImplementedError("NOT IMPLEMENTED — TDD stub: evaluate_cadence_bot_flag callers pass settings.cadence_bot_flag_max_variance_threshold / max_engagement_ratio, not hardcoded literals")
```

AC-12:
```python
def test_should_log_no_pii_on_flag_set():
    raise NotImplementedError("NOT IMPLEMENTED — TDD stub: every structlog call site in cadence_bot_flag_sweep.py passes only site_id, visitor_id, counts, and computed signal values — never email/name/PII")
```

AC-13:
```python
def test_should_not_flag_rigid_but_engaged_power_user():
    raise NotImplementedError("NOT IMPLEMENTED — TDD stub: a visitor with a rigid daily schedule (low CV) but high engagement ratio (scroll/click/time-on-page) is never flagged")
```

### Legacy line form

- Backend pure functions (`cadence_bot_flag.py`): Fully-Automated — `.venv/bin/python3.11 -m pytest tests/unit/test_cadence_bot_flag.py -m unit -v` — proves AC-1, AC-2, AC-3, AC-5, AC-11, AC-12, AC-13
- Sweep + ingest-isolation + regressions (`cadence_bot_flag_sweep.py`, scheduler, model): Hybrid — precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis` — `.venv/bin/python3.11 -m pytest tests/integration/test_cadence_bot_flag.py -m integration -v` — proves AC-4, AC-6, AC-7, AC-10
- Migration: Hybrid (offline, no precondition) — `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head --sql` + `downgrade -1 --sql` — proves additive-only migration correctness both directions
- Web badges: Agent-Probe (reclassified, PVL supplement cycle 1 — see Known-Gaps #4) / Agent-Probe (Playwright auth leg) — manual fixture-based render check; component-render infra does not exist in `apps/web`
- AC-14: known-gap: documented operator runbook (Step 15) — post-deploy verification against motivating-case data, not an automated gate

### Dimension findings

- Infra fit: PASS — APScheduler job def (`_intent_signal_sweep_job`, `apps/api/jobs/scheduler.py:190`) and registration block (`apps/api/jobs/scheduler.py:433-441`, jitter=90/misfire_grace_time=300 matching the `agent_verification_sweep`/`intent_signal_sweep` 60-min-class precedent) re-confirmed real, matchable, and unchanged since pass 1; migration head re-confirmed live via `alembic -c apps/api/alembic.ini heads` = `d5b1f7c3a908` (single head, unchanged, matches plan's assumption exactly); bounded-read constraint remains enforced by a concrete `cadence_bot_flag_lookback_days` setting + a `WHERE events.created_at >= now() - lookback` clause. The two pass-1 informational notes for execute-agent stand unchanged: (1) `config.py`'s existing feature-flag block headings use a single `#`, not the `##` the plan's Step 1 prose uses — trivial, self-correcting via Step 1's own grep instruction; (2) the internal `if not settings.cadence_bot_flag_enabled: return` guard in Step 6 is the correct choice for this job (unlike existing optional jobs, `events` rows exist regardless of the flag — retroactive detection is the point), not a deviation to flag as wrong.
- Test coverage: PASS (G1 resolved) — backend gate commands re-confirmed exact and runnable (`.venv/bin/python3.11 -m pytest` verified working). AC-8/AC-9 (Steps 12-13) are now correctly tiered Agent-Probe (not Fully-Automated/Hybrid as originally, incorrectly, stated) with written rationale in Known-Gaps #4 and consistent cross-references in every table that names them (SPEC traceability, Verification Evidence, C3 test-gate table, Steps 12/13 Verification text). No location in the plan still claims an automated component-render gate for AC-8/AC-9 — re-checked exhaustively this pass (see PVL Pass 2 — Re-Validation Summary above). This is the correct, non-vacuous resolution: Agent-Probe is a legitimate proving strategy, and every occurrence states the gate stays CONDITIONAL until the manual check is actually performed.
- Breaking changes: PASS — migration is 2 additive `nullable=False, server_default="false"` boolean columns (no destructive change); new API field `is_bot_suspect: bool = False` on `VisitorOut` (confirmed `model_config = {"from_attributes": True}` at `apps/api/schemas/visitors.py:50` — new ORM column auto-serializes via the existing `VisitorOut.model_validate(visitor)` call sites at `routers/visitors.py:117,589`, no router change needed); no existing field renamed/removed; no route added/removed; confirmed zero required edit to `routers/events.py` (AC-4). Unchanged since pass 1.
- Security surface: PASS — no new auth/authz surface; `is_emailable_identity()` signature re-confirmed unchanged at exactly 3 params (`provider, source_agent_visit_id=None, is_abuse_flagged=False`, `apps/api/services/identity_classification.py:56`) with a structural guard test asserting this; new field is additive/read-only, no new attack surface; config flag defaults OFF; sweep iterates per-site/per-visitor (tenant boundary preserved); no PII in new log lines (AC-12 has a dedicated structural test); no secrets touched. Unchanged since pass 1.

### Layer 2 — per-section feasibility

| Section | Status |
|---|---|
| A — Config + migration (Steps 0-2) | PASS |
| B — Pure detection functions + unit tests (Steps 3-4) | PASS |
| C — Sweep wrapper + scheduler registration (Steps 5-6) | PASS (informational note, see Infra fit above) |
| D — Model columns + regression proofs (Steps 7-9, 11) | PASS |
| E — API schema + serialization (Step 10) | PASS |
| F — Web badges + component tests (Steps 12-13) | PASS (G1 resolved via reclassification to Agent-Probe, PVL supplement cycle 1; residual carried as Known-Gap #4, not a blocking CONCERN) |
| G — Integration test suite (Step 14) | PASS |
| H — AC-14 operator runbook (Step 15) | PASS |

**Totals (PVL pass 2): 0 FAILs / 0 active CONCERNs / 8 PASS dimensions+sections. 4 pre-accepted
known-gaps carried as named residuals (AC-14 live-crawler validation, migration live round-trip,
Playwright auth-harness leg, AC-8/AC-9 Agent-Probe reclassification) — excluded from the
CONCERN/FAIL count per the Known-Gap exclusion rule, but present as the reason this gate is
CONDITIONAL rather than PASS (net-gate vacuous-green ban: AC-8/AC-9 rest on Agent-Probe alone, so
a terminal PASS is not permitted — CONDITIONAL with the residual named explicitly is required).**

**→ Net Gate: CONDITIONAL (execute-eligible — 1 completed PVL supplement cycle recorded in
`results.tsv`)**

### Open gaps

- **G1 — RESOLVED (PVL supplement cycle 1, 26-07-26; re-confirmed closed at PVL pass 2, 26-07-26):**
  AC-8/AC-9's test-gate strategy assumed React component-render test infrastructure that does not
  exist in `apps/web`. Resolved via option (C) reclassification — AC-8/AC-9 downgraded from
  Fully-Automated/Hybrid to Agent-Probe with written rationale (see Known-Gaps #4), carried forward
  as a named residual rather than left as an unbacked automated-gate claim. No longer an active
  CONCERN; superseded by Known-Gaps #4 below.
- AC-14 — live stealth-crawler validation: known-gap: documented — Agent-Probe by SPEC design (real
  production data required, cannot be synthesized); operator runbook (Step 15) required post-deploy;
  pre-accepted per repo precedent (matches `agent_detection_enabled`-class rollout gaps). Not a plan
  defect.
- Migration live round-trip: known-gap: documented — no disposable Postgres in this environment;
  matches the unbroken `c7d3b8e1f624`/`b7d3e9f1a4c2`/`c8e4f2a6b1d9`/`d5b1f7c3a908` precedent (none of
  the 4 most recent migrations are live-round-tripped either); offline `--sql` validation (proven
  both directions) is the interim gate. Not a plan defect.
- Playwright auth-harness leg for AC-8: known-gap: documented — same repo-wide Clerk auth-harness gap
  blocking other pixel/ads-audiences UI ACs; component-level render test (now Agent-Probe per Known-
  Gap #4) covers the badge presence/absence logic, the full-session leg stays Agent-Probe. Not a plan
  defect.
- AC-8/AC-9 Agent-Probe reclassification (Known-Gap #4): known-gap: documented — see Known-Gaps
  section for full rationale; gate stays CONDITIONAL until the manual check is performed at
  EXECUTE/EVL time (Steps 12-13 don't exist yet to check). Not a plan defect — a correctly-graded
  residual, not a vacuous pass.

### What this coverage does NOT prove

- The unit gates (AC-1, AC-2, AC-3, AC-5, AC-11, AC-12, AC-13) prove the pure detection math and structural isolation against synthetic fixtures only — they do NOT prove any real crawler's actual event history trips the flag in production (that gap is AC-14, explicit known-gap).
- The integration gates (AC-4, AC-6, AC-7, AC-10) prove behavior against a disposable-test Postgres+Redis with seeded fixtures — they do NOT prove behavior against production-scale data volume, concurrent sweep runs across multiple app instances, or real multi-tenant traffic shapes.
- The migration offline `--sql` dry run proves the generated SQL is syntactically correct in both directions — it does NOT prove the migration applies cleanly against a real running Postgres with existing production rows and constraints (that is the migration live-round-trip known-gap).
- The AC-8/AC-9 Agent-Probe manual checks (once performed, at EXECUTE/EVL time) will prove badge presence/absence logic against a manually-inspected rendered page — they will NOT prove the badge renders correctly inside a real authenticated Clerk dashboard session under load, and they are not repeatable/automatable the way a Fully-Automated or Hybrid gate would be (that remains the Playwright auth-harness known-gap plus the RTL/jsdom backlog candidate).
- No automated gate in this plan proves the operator-tunable thresholds (`cadence_bot_flag_max_variance_threshold=0.15`, `cadence_bot_flag_max_engagement_ratio=0.05`) are well-calibrated against real traffic — only that the code correctly reads and applies whatever value is configured. Threshold tuning against real data is an explicit post-launch operator responsibility (matches `site_ingest_limit_per_minute`'s "never ship the placeholder default live" precedent).

Gate: CONDITIONAL (0 FAILs; 0 active CONCERNs — G1 resolved via reclassification and re-confirmed
closed at PVL pass 2; 4 pre-accepted known-gaps carried forward: AC-14 live-crawler validation,
migration live round-trip, Playwright auth-harness leg, AC-8/AC-9 Agent-Probe reclassification —
none newly introduced or mishandled by this plan). 1 completed PVL supplement cycle recorded
(`results.tsv`: baseline row + cycle-1 row, `SUPPLEMENT_APPLIED` received, re-validated from V1).
**EXECUTE-ELIGIBLE** per the "CONDITIONAL with N≥1 recorded fix cycles" rule.
Accepted by: session (autonomous, standing-AUTOMATIC-loop execution) — all 4 known-gaps (AC-14
live-crawler validation, migration live round-trip, Playwright auth-harness leg for AC-8,
AC-8/AC-9 Agent-Probe reclassification) accepted per repo precedent; G1 itself was not "accepted
as a gap" — it was actively resolved by the PVL supplement cycle (reclassification with rationale),
then independently re-verified closed by this PVL pass 2 validation.

## Autonomous Goal Block

SESSION GOAL: Ship the cadence-bot-flag behavioral stealth-crawler detection signal (visibility-only,
structurally isolated from is_abuse_flagged/agent_visits/is_emailable_identity) per the locked SPEC's
14 ACs.
Charter + umbrella plan: N/A — single COMPLEX-lite plan, no phase-program umbrella.
Autonomy: Standing AUTOMATIC loop autonomy for this build (per orchestrator instruction) — VALIDATE
self-decides gate verdicts without an interactive menu pause; orchestrator drives PVL supplement
cycles on CONDITIONAL/BLOCKED per `process/development-protocols/orchestration.md` §PVL/EVL Loop
Routing.
Hard stop conditions / safety constraints:
- Never set `is_abuse_flagged` or `do_not_resolve` from the new flag (AC-5, AC-6).
- Never add a 4th parameter to `is_emailable_identity()` or otherwise wire the new flag into
  outreach eligibility (AC-6) — structural guard test asserts exactly 3 params.
- Never add the new flag to any `FILTER (WHERE NOT is_flagged_abuse)` aggregate exclusion in
  `visitor_aggregator.py` (AC-7).
- Never add a check to the `POST /ingest` write path (AC-4) — detection stays batch-only.
- Never live-apply the new migration in this plan — offline `--sql` validation only; live-apply is
  a separate explicit operator action, matching the unbroken 4-migration precedent.
- `cadence_bot_flag_enabled` must default OFF; enabling in a real environment is an explicit
  post-migration-live-apply operator action.
Next phase: EXECUTE (execute-eligible now — PVL pass 2 confirmed Gate: CONDITIONAL with 1 completed
supplement cycle recorded). Orchestrator: spawn vc-execute-agent against this plan. Re-verify
migration head at Step 0 before Step 2 (not assumed stale-safe across sessions). Implement backend
Steps 1-11 + 14 first (Fully-Automated/Hybrid gates), then Steps 12-13 (web badges) followed by the
Agent-Probe manual render checks named in their Verification blocks. After EXECUTE, the EVL
confirmation run (vc-tester re-running every gate command in the C3 table) is mandatory before
UPDATE PROCESS — execute-agent's internal iterate-until-green loop does not substitute for it.
Validate contract: inline in plan, `## Validate Contract` section above (this write, PVL pass 2).
Execute start: `.venv/bin/python3.11 -m pytest tests/unit/test_cadence_bot_flag.py -m unit -v` (fully-automated unit suite) | `.venv/bin/python3.11 -m pytest tests/integration/test_cadence_bot_flag.py -m integration -v` (hybrid, precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis`) | e2e spec: none required (no new route/page, badge-only UI change) | high-risk pack: no (schema/migration is Hybrid-tier per the High-Risk Class Table, not auth/billing/destructive — offline dry-run + explicit live-apply deferral is the accepted evidence, matching the unbroken 4-migration precedent; a full 5-artifact risk-evidence-pack is not required for this class at this tier).

## Strategy Recommendation for VALIDATE

**Recommended: Sequential, single `vc-validate-agent` (sonnet).** Score: 2/7 signals present
(S2 — schema/migration surface touched; S7 is borderline at ~11 touchpoint files, just under the
5+ threshold's higher bar for a HIGH classification but present as a MEDIUM-leaning signal). This
plan is a single cohesive design with one dominant risk class (the additive migration) — there is
no independent investigation branch or adversarial-review need that would benefit from parallel
subagents or an agent team. A single sequential VALIDATE pass covering V1–V7, with the Hybrid-tier
migration gate and the AC-5/AC-6/AC-7 structural-isolation checks as the dimension-agent focus in
V2, is sufficient. Alternatives considered: **parallel subagents** (rejected — no 5+ independent
directions; the checklist is one linear build-order, not fan-out-able work); **agent team**
(rejected — no cross-file adversarial coordination need; this is not a multi-owner phase-program
plan set); **workflow** (rejected — no repeated per-item sub-task shape, single plan not a sweep
across N items). This recommendation held unchanged across both PVL passes — the G1 fix was a
plan-text reclassification, not a scope/signal change.

## Strategy Recommendation for EXECUTE

**Recommended: Sequential, single `vc-execute-agent` (opus).** Score: 2/7 signals present (S2 —
schema/migration surface; S7 borderline at ~11 files). Same rationale as the VALIDATE strategy
above — one linear, dependency-ordered build (config → migration → pure functions → sweep →
scheduler → model → regressions → schema → structural checks → web badges → integration suite →
runbook), no independent parallel workstreams, no cross-agent coordination need. A single
sequential execute-agent pass implementing Steps 0-15 in order, running the C3 gate commands after
each relevant step group, is the correct fit. Alternatives considered: **parallel subagents**
(rejected — Steps 1-11 have real dependency ordering, e.g. Step 2's migration `down_revision`
depends on Step 0's live-head check, and Steps 12-13 depend on Step 10's schema field existing;
splitting this into concurrent agents risks migration-head races or badge code referencing a field
that doesn't exist yet); **agent team** (rejected — no adversarial or cross-specialty coordination
need); **workflow** (rejected — one plan, not a sweep across N independent items). After EXECUTE
reports done, the orchestrator MUST still spawn vc-tester for the EVL confirmation run against every
C3 gate command — this is mandatory regardless of what execute-agent's own iterate-until-green loop
reports.

---

**Status:** DONE
**Summary:** Cadence Bot Flag PLAN written at `process/features/pixel/active/cadence-bot-flag_26-07-26/cadence-bot-flag_PLAN_26-07-26.md` — COMPLEX-lite single-plan (no phase split), 15 implementation steps covering config → migration → pure detection functions → sweep wrapper → scheduler registration → model columns → regression proofs (AC-6/AC-7 untouched-surface verification) → API schema → structural-isolation code checks → web badges (detail + list) → integration suite → AC-14 operator runbook, every SPEC AC (1–14) traced to a step and a named test gate in both the AC→Step→Gate table and the Verification Evidence table, migration authoring includes the mandatory live-head re-verification step and offline `--sql` dry-run (live round-trip explicitly deferred as a named Known-Gap matching existing repo precedent), all required plan sections present (Touchpoints, Public Contracts, Blast Radius, Verification Evidence, Test Infra Improvement Notes, Resume and Execution Handoff, Validate Contract placeholder), VALIDATE strategy recommendation included (sequential, single sonnet agent).
**Concerns/Blockers:** None blocking. Three Known-Gaps carried forward explicitly (AC-14 live-crawler validation, migration live round-trip, Playwright auth-harness leg for AC-8) — none of these block PLAN→VALIDATE transition; all are documented with resolution rationale per the vacuous-green ban (none are silently accepted as PASS — all three keep their respective gates CONDITIONAL until resolved).

**PHASE_COMPLETE: PLAN — process/features/pixel/active/cadence-bot-flag_26-07-26/cadence-bot-flag_PLAN_26-07-26.md written. Proceed to VALIDATE.**

---

**Status:** DONE_WITH_CONCERNS
**Summary:** VALIDATE run complete for `cadence-bot-flag_PLAN_26-07-26.md` (PVL pass 1). V1 structural pre-check passed (plan-artifact validator: 0 failures/0 warnings; all 20+ file:line claims in Touchpoints/Overview/SPEC-evidence verified real via direct grep/read against the live repo, including scheduler.py job/registration line numbers, tracker.js event-type emission lines, `is_emailable_identity` 3-param signature, `visitor_aggregator.py` FILTER clauses, `VisitorOut.model_config.from_attributes`, and the live alembic head `d5b1f7c3a908` matching the plan's assumption exactly). V2 two-layer fan-out (4 Layer-1 dimensions + 8 Layer-2 sections) found 0 FAILs and 1 substantive CONCERN (G1: AC-8/AC-9's claimed frontend "component test" gate assumes React component-render test infrastructure — `@testing-library/react` + jsdom vitest environment — that does not exist anywhere in `apps/web` today; confirmed via `vitest.config.ts` content, package.json devDependencies, and a repo-wide `.test.tsx` file search). V3 synthesis: Net Gate = CONDITIONAL. The plan's 3 pre-existing SPEC/PLAN-level known-gaps (AC-14 live-crawler validation, migration live round-trip, Playwright auth-harness leg) were verified as correctly handled — not converted to FAILs, carried forward as pre-accepted known-gaps per repo precedent and the vacuous-green-ban rule (AC-1–AC-13 all have real automated gates; only AC-14 rests on Agent-Probe alone, which is permitted as a named, justified residual). Full validate-contract (C3 5-column test-gate table across all 14 ACs + 2 migration-constraint rows, failing-stub skeletons for every Fully-Automated row, 4-dimension + 8-section findings, Open gaps, "What this coverage does NOT prove", `generated-by: outer-pvl`, `date: 2026-07-26`) written into the plan file, replacing the placeholder. `## Autonomous Goal Block` written (BRANCH A — no umbrella plan exists for this single COMPLEX-lite plan) stating this is NOT yet execute-eligible. Per protocol, this is a first-pass CONDITIONAL — `PHASE_COMPLETE: VALIDATE` is NOT emitted; instead a SUPPLEMENT REQUEST is emitted below for the orchestrator to route to vc-plan-agent (PVL-supplement mode), after which vc-validate-agent should be re-spawned from V1.
**Concerns/Blockers:** G1 (CONCERN, not FAIL) — apps/web has no React component-render test infrastructure; AC-8/AC-9's Fully-Automated/Hybrid-component-leg claims are currently unbacked. Recommended fix: add `@testing-library/react` + `jsdom` as new `apps/web` devDependencies, add a jsdom-scoped vitest project/config, extend `vitest.config.ts`'s `include` glob to also match `src/**/*.test.tsx`. See SUPPLEMENT REQUEST below.

SUPPLEMENT REQUEST:
- Gap 1: Section test-infra-improvement-notes | Concern: AC-8/AC-9 test gates (Steps 12-13) claim "Fully-Automated" / "Hybrid (component leg automated)" component-render tests for the new bot-suspect badge, but `apps/web` has ZERO existing React component-test infrastructure — `vitest.config.ts` is explicitly `environment: "node"`, `include: ["src/**/*.test.ts"]` only (confirmed via file read: "First JS unit runner in apps/web — scoped to pure `src/lib` logic... not the DOM"), no `@testing-library/react` or `jsdom` in devDependencies, and no `.test.tsx` file exists anywhere in the repo. The Test Infra Improvement Notes section previously stated "(none identified yet)" which was inaccurate (now corrected inline by this VALIDATE pass). | Severity: CONCERN | Suggested addition: Add a new implementation step (e.g. Step 11b, before Step 12) to install `@testing-library/react` + `jsdom` as new `apps/web` devDependencies and add a jsdom-scoped vitest project/config (or a per-file `// @vitest-environment jsdom` pragma) plus update `vitest.config.ts`'s `include` glob to also match `src/**/*.test.tsx`; alternatively, if infra setup is judged out of scope for this plan, reclassify AC-8/AC-9's Steps 12-13 test-gate strategy from Fully-Automated/Hybrid down to Agent-Probe/Known-Gap with written rationale and update the Verification Evidence + SPEC AC traceability tables accordingly.

Gate: CONDITIONAL
Plan path: process/features/pixel/active/cadence-bot-flag_26-07-26/cadence-bot-flag_PLAN_26-07-26.md
Validate-contract written: yes
Next step: PVL supplement cycle (first-pass CONDITIONAL) — orchestrator spawns vc-plan-agent in PVL-supplement mode with the SUPPLEMENT REQUEST above, then re-spawns vc-validate-agent from V1.

---

**Status:** DONE
**Summary:** VALIDATE PVL pass 2 (re-validation from V1) complete for `cadence-bot-flag_PLAN_26-07-26.md`, following vc-plan-agent's PVL-supplement-mode fix (`SUPPLEMENT_APPLIED` received, 1 gap addressed). V1 re-run: structural validator 0 failures/0 warnings; `## Inner Loop Refresh Note` not applicable (this is an outer-PVL re-validation, not an inner-loop trigger — orchestrator re-spawned directly per the standard PVL supplement-cycle routing). V2/V3 re-confirmed: G1 closure verified real and consistent across every location that references AC-8/AC-9's test-gate tier (SPEC traceability table, Steps 12/13 Verification text, Verification Evidence table, C3 test-gate table, Known-Gaps #4, Test Infra Improvement Notes) — no residual claim of an automated component-render gate remains anywhere in the plan; no vacuous-green pattern (Agent-Probe rows are explicitly labeled as a named residual that stays CONDITIONAL until manually checked, never silently counted as automated proof). Regression spot-check re-confirmed all 4 key file:line anchors from pass 1 unchanged: scheduler.py `_intent_signal_sweep_job` def (~line 190) and registration block (~lines 434-441); `is_emailable_identity` still exactly 3 params at `identity_classification.py:56`; `visitor_aggregator.py`'s `FILTER (WHERE NOT is_flagged_abuse)` clauses present and unchanged (5 occurrences); live alembic head re-confirmed `d5b1f7c3a908` (single head) via `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads`. 0 new FAILs, 0 new CONCERNs found. Net Gate: **CONDITIONAL** — required (not merely permitted) by the net-gate vacuous-green ban, since AC-8/AC-9 rest on Agent-Probe alone with no Fully-Automated/Hybrid proof; a terminal PASS is not available for this plan, and CONDITIONAL-with-named-residual is the correct classification. This CONDITIONAL is **execute-eligible**: 1 completed PVL supplement cycle is recorded in `results.tsv` (baseline row + cycle-1 row, `SUPPLEMENT_APPLIED` signal received and consumed), satisfying the "Gate = CONDITIONAL with N≥1 recorded fix cycles" rule. `## Validate Contract` rewritten in place (Date/date unchanged calendar date but marked "PVL pass 2"; `supersedes: 2026-07-26 (outer-pvl, PVL pass 1)` added per the canonical supersedes rule; `generated-by: outer-pvl` unchanged; Totals/Net Gate/Open gaps/Gate line/Layer 2 Section F all updated to reflect G1's resolved status; a new "PVL Pass 2 — Re-Validation Summary" subsection documents the closure evidence). `## Current Execution State`, `## Resume and Execution Handoff`, and `## Autonomous Goal Block` (`Next phase`) all updated to point to EXECUTE. A new `## Strategy Recommendation for EXECUTE` section was added (sequential, single opus vc-execute-agent — same 2/7 signal score, dependency-ordered build with no parallelizable workstreams). Mandatory pre-emit completeness check re-run: `grep -c "What this coverage does NOT prove"` = 1, `grep -c "Accepted by:"` = 2 (historical pass-1 reference inside this pass's narrative text plus the live pass-2 field — both present, no ambiguity), `grep -c "generated-by:"` = 1, Dimension findings section present, `grep -c "## Autonomous Goal Block"` = 1 (BRANCH A, no umbrella plan exists — already written, confirmed present, not re-duplicated).
**Concerns/Blockers:** None blocking. 4 pre-accepted known-gaps carried forward (AC-14 live-crawler validation, migration live round-trip, Playwright auth-harness leg for AC-8, AC-8/AC-9 Agent-Probe reclassification) — all named, all with written rationale, none silently dropped. The AC-8/AC-9 Agent-Probe manual checks themselves have NOT yet been performed (Steps 12-13 are not yet implemented) — this is expected and correct at VALIDATE time; the checks run at EXECUTE/EVL time once the badges exist.

PHASE_COMPLETE: VALIDATE — validate-contract written (after 1 validate-fix loop(s)). Proceed to EXECUTE.

Gate: CONDITIONAL
Plan path: process/features/pixel/active/cadence-bot-flag_26-07-26/cadence-bot-flag_PLAN_26-07-26.md
Validate-contract written: yes
Next step: EXECUTE MODE (CONDITIONAL with 1 completed PVL supplement cycle — execute-eligible per protocol)

---

**Status:** DONE
**Summary:** UPDATE PROCESS closeout complete for `cadence-bot-flag_PLAN_26-07-26.md`. EXECUTE
(26-07-26, all 15 steps) and the independent EVL confirmation run (26-07-26) are both done: ALL
contract gates green — 25/25 unit + 7/7 integration, 0 EVL fix cycles, mutation-kill proved AC-3's
conjunction non-vacuous, migration offline `--sql` validated both directions (never live-applied),
web typecheck clean. 2 cosmetic contract-wording corrections from the EVL handoff were annotated
in place in `## Validate Contract` (AC-5 grep-bundle wording; migration offline `--sql` rev-range
wording) — bracketed `[EVL note, 26-07-26: ...]` inline, no history rewritten. 1 backlog NOTE
written: `process/features/pixel/backlog/cadence-bot-flag-deferred-gates_NOTE_26-07-26.md` (4
known-gaps with resolution paths + a 7-step operator go-live sequence; also names the apps/web
RTL/jsdom test-infra backlog candidate as a future-plan item, not scheduled here).
`process/context/all-context.md` updated: Current Features `pixel` bullet, both migration-chain
mentions (AI-Agent-Traffic Layer section + Open Questions), env var groups line. No new
"Cadence Bot Flag" standalone summary section was added — the Current Features bullet plus the
migration-chain updates were judged sufficient (smallest-edit discipline; this is a smaller,
single-plan feature, not a multi-phase program warranting its own subsection).
`process/context/tests/all-tests.md` updated: 1 new bullet under Debugging Quick Reference /
Backend-pytest for the alembic offline `--sql` rev-range gotcha (with the `b7d3e9f1a4c2`
offline-unsafe cross-reference). Validators run: `validate-plan-inventory.mjs` and
`validate-context-discovery.mjs` (see results below); `git diff --check` clean. No harness/agent
files touched this session — `vc-audit-vc` not required. **Plan classification: Keep in
active/testing — the plan is explicitly NOT archived.** No source code, no commits.
**Concerns/Blockers:** None blocking. All 4 known-gaps are pre-accepted, named, and carried in
the new backlog NOTE — none are regressions, none silently dropped. Plan remains in
`process/features/pixel/active/cadence-bot-flag_26-07-26/` pending resolution of those gaps
(primarily: Docker-gated migration round-trip, and the Agent-Probe manual UI checks).

PHASE_COMPLETE: UPDATE PROCESS — cadence-bot-flag closeout captured; plan active pending known-gaps.

Gate: N/A (closeout, not a validate pass)
Plan path: process/features/pixel/active/cadence-bot-flag_26-07-26/cadence-bot-flag_PLAN_26-07-26.md
Archived: NO — plan stays in active/
Next step: resolve known-gaps per `process/features/pixel/backlog/cadence-bot-flag-deferred-gates_NOTE_26-07-26.md`, then re-run UPDATE PROCESS for archival.
