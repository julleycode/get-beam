---
name: plan:outlier-traffic-damping
description: "Damp statistical-outlier/internal-traffic influence on analytics and identity-resolution budget, per-site opt-in"
date: 27-07-26
feature: general-plans
phase: "n/a"
---

# Outlier / Internal Traffic Damping — Implementation Plan

**Date**: 27-07-26
**Status**: VALIDATED (see Validate Contract)
**Complexity**: COMPLEX


## Context (measured live, production, 2026-07-27)

Read-only production queries run 27-07-26; script: `scripts/m2_agentic_traffic_audit.sql`.

**Query A — share of 90-day events from "heavy" visitors (>=200 events):**

| Site | Heavy visitors | Share of all events | Max single visitor |
|---|---|---|---|
| `site_1944ab523384` | 1 | 94.8% | 8,476 |
| `site_f44740b94cea` | 15 | 92.2% | 15,867 |
| `site_af21533730fe` | 17 | 89.3% | 30,562 |
| `beam_getbeam_fyi` | 3 | 39.2% | 1,735 |

**Query B — heavy visitors are over-resolved:**

| Cohort | N visitors | % identified | Avg intent_score |
|---|---|---|---|
| heavy (>=200 ev) | 36 | 11.1% | 50 |
| normal | 1195 | 2.0% | 14 |

**Query C — budget skew:** on `site_f44740b94cea`, 3 of 8 identified visitors were heavy = 37.5% of that site's identity-resolution budget.

**Deep-dive, `site_af21533730fe` (Grade Coach, grade.coach):** top visitor had 30,562 events over 20 days across 12 distinct IP /16 blocks, 15,891 scroll events, 5,003 dwell events — a real human returning constantly from many networks, almost certainly site owner/staff. Burst visitors there averaged 1,993 events vs 12 for normal visitors; 0% of them lacked engagement signals.

**Mechanism of harm (confirmed in code):** `apps/api/services/resolution_runner.py:80` selects candidates `.order_by(Visitor.intent_score.desc()).limit(max_resolve)`. A visitor generating tens of thousands of events accumulates very high `intent_score`, so they are resolved FIRST on every sweep and consume the site's `daily_resolution_budget` (`apps/api/models/site.py:23`, default 50).

## Honesty Constraint (binding on all copy + framing)

"Heavy" is NOT proven to equal "the site owner." It is inferred from the Grade Coach pattern and is not verified for every site — a heavy visitor could be a genuinely obsessed prospect. This feature dampens the influence of **statistical outliers**, it does not "detect the owner." All user-facing copy MUST say something like "unusually high activity" — never assert it is the customer themselves. This constraint governs the badge tooltip, the manual-override label, and any dashboard copy written in EXECUTE.

## Design (decided upstream — implement, do not redesign)

Two distinct harms, two treatments:

1. **Analytics distortion** → exclude flagged visitors from aggregate metrics (row still stored, never dropped).
2. **Budget skew** → deprioritise flagged visitors in identity resolution ordering.

Detection, two paths:

- **Automatic (default)** — statistical outlier WITHIN each site: event count vastly exceeds that site's own median, sustained across multiple days, AND full engagement signals present (distinguishes a heavy human from a scraper — scrapers don't scroll). Never a fixed global threshold — site scale varies by orders of magnitude in the data above (29–532 visitors/site).
- **Manual (optional)** — a "This is me / my team" action on the visitor detail page. Exact, for customers willing to click. Manual override always wins over the automatic scorer and is permanent. **Resolved at VALIDATE: this action is standalone — it works regardless of whether `internal_damping_enabled` is on for the site (see checklist item 10).**

## Reuse Precedents (mandatory — do not invent new subsystems)

| Precedent | File | What to copy |
|---|---|---|
| Visibility-only sticky flag column | `apps/api/models/visitor.py:84` (`is_bot_suspect`) | Exact column shape for `is_internal_suspect` |
| Pure, I/O-free scoring functions | `apps/api/services/cadence_bot_flag.py` | Function shape: `compute_*` (pure) + `evaluate_*_flag` (pure boolean decision), thresholds passed in, never read from settings inside pure fns |
| Batch sweep wrapper | `apps/api/services/cadence_bot_flag_sweep.py` | Bounded-read window, per-visitor try/except fail-open, sticky OR-merge write via `update().where(...is_(False))` |
| APScheduler wiring | `apps/api/jobs/scheduler.py:221-245,484-487` (`_cadence_bot_flag_sweep_job`) | Add a sibling job function + `add_job(...)` call |
| **Cross-visitor aggregate exclusion (VALIDATE-CORRECTED — was: `visitor_aggregator.py` FILTER clause)** | `apps/api/services/daily_digest.py::_site_day_stats` (~lines 224-240) — uses `human_only_visitor_filter()` as its exclusion precedent | Add `Visitor.is_internal_suspect.is_(False)` to the existing `.where(...)` clause, same shape as the `human_only_visitor_filter()` call already there. **`visitor_aggregator.py`'s FILTER clauses are event-scoped and are NOT a valid precedent for this column — see Validate Contract Dimension Findings for why.** |
| APScheduler wiring | `apps/api/jobs/scheduler.py:221-245,484-487` (`_cadence_bot_flag_sweep_job`) | Add a sibling job function + `add_job(...)` call |
| Single choke-point visitor filter | `apps/api/services/agent_visitor_filters.py` (`human_only_visitor_filter()`) | Reference only — NOT to be modified (that filter excludes synthetic agent rows, a different concern) |
| Default-OFF feature flag block | `apps/api/config.py` (`cadence_bot_flag_enabled` block, ~line 320-385) | Copy block shape + inline rollout-order comment convention |
| Dashboard badge precedent | `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx:479-486`, `apps/web/src/app/dashboard/visitors/page.tsx:695` | Copy `<span className="rounded-full bg-warning-muted ...">` badge shape + honesty-constraint-compliant tooltip |
| Per-site boolean toggle column | `apps/api/models/site.py:23-31` (`auto_identify_enabled`, `hot_alert_enabled`) | Column shape for new `internal_damping_enabled` per-site toggle |

## Hard Safety Constraints (verbatim from upstream design — non-negotiable)

1. **Flag-but-store.** Never delete or drop events. Excluded from aggregates only; forensics preserved.
2. **Do NOT touch the emailability guardrail.** `apps/api/services/identity_classification.py::is_emailable_identity` MUST keep exactly 3 parameters — arity assertion at `tests/unit/test_cadence_bot_flag.py:293`, literal-field-name tripwire at `tests/unit/test_agent_origin_exclusion.py:207-223`. This feature is data quality, not outreach eligibility — `is_internal_suspect` is NEVER read by `is_emailable_identity` and is NEVER added as a 4th parameter. **VALIDATE independently re-read `identity_classification.py:56-60` and confirmed the signature is exactly `(provider, source_agent_visit_id=None, is_abuse_flagged=False)` — 3 params, matches.**
3. **Reversible.** A mis-flagged visitor must be clearable in one click; the manual override always wins over the automatic scorer, permanently (i.e. once a human sets the override, the automatic sweep must never overwrite it back to "not internal" OR re-flag it — override is sticky in BOTH directions once set).
4. **Default OFF**, enabled per-site (`internal_damping_enabled` on `Site`), so a customer can see before/after.
5. **Migration head discipline.** Re-run `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` LIVE immediately before writing `down_revision` — this repo has had repeated concurrent-session migration collisions. **Confirmed live 27-07-26 at PLAN time: current head is `b1e7f3c9d425`** (`add_last_daily_digest_sent_at`) — NEWER than the `e6b2d4a1c837` head documented in `process/context/all-context.md` (daily-digest work landed concurrently). **VALIDATE independently re-ran `alembic -c apps/api/alembic.ini heads` on 27-07-26 and confirmed a single head: `b1e7f3c9d425` — matches this plan's claim.** EXECUTE MUST re-run `alembic heads` again immediately before writing the new migration's `down_revision` — do not trust this plan's recorded head, the chain may have moved again. For offline `--sql` validation use an explicit `<from-rev>:<to-rev>` range — the `head`/`-1` shorthand fails mid-chain in this repo (see `process/context/tests/all-tests.md` gotcha re: `b7d3e9f1a4c2`).

## Touchpoints

| File | Change |
|---|---|
| `apps/api/models/visitor.py` (after `is_bot_suspect`, ~line 89) | Add `Visitor.is_internal_suspect: bool` (sticky, default False, server_default false) and `Visitor.internal_override: str \| None` (nullable tri-state: `None` = no manual action, `"internal"` = user confirmed "this is me/my team", `"not_internal"` = user explicitly cleared/rejected an automatic flag) |
| `apps/api/models/visitor.py` (`IdentifiedVisitor` class, mirrors `is_bot_suspect` at ~line 129) | Add `IdentifiedVisitor.is_internal_suspect: bool` (copied from `Visitor.is_internal_suspect` at aggregation time, same pattern as the existing `is_bot_suspect` copy-down) |
| `apps/api/models/site.py` (after `hot_alert_enabled`, ~line 31) | Add `Site.internal_damping_enabled: bool` (default False, server_default false) — per-site opt-in gate |
| `apps/api/migrations/versions/{new_rev}_add_internal_traffic_damping.py` | New Alembic migration: 3 additive nullable/defaulted columns, chained onto the live-confirmed head |
| `apps/api/services/outlier_traffic_damping.py` (new file) | Pure, I/O-free scoring functions: `compute_event_count_percentile` (or z-score vs site median), `compute_multi_day_persistence`, `evaluate_outlier_flag` — mirrors `cadence_bot_flag.py` shape exactly |
| `apps/api/services/outlier_traffic_damping_sweep.py` (new file) | Batch DB-loop wrapper — mirrors `cadence_bot_flag_sweep.py` shape: bounded read, per-site median calc, per-visitor evaluate + sticky OR-merge write, respects `internal_override` (never overwrites a set override in either direction) |
| `apps/api/jobs/scheduler.py` (near `_cadence_bot_flag_sweep_job`, ~line 221 and ~line 484) | Add `_outlier_traffic_damping_sweep_job()` + `add_job(...)` registration |
| `apps/api/config.py` (near `cadence_bot_flag_*` block, ~line 320-385) | New settings block: `outlier_traffic_damping_sweep_interval_minutes`, `outlier_traffic_damping_lookback_days`, `outlier_traffic_damping_min_visit_days`, `outlier_traffic_damping_percentile_threshold` (or z-score threshold), `outlier_traffic_damping_min_engagement_ratio` — all operator-tunable, no magic numbers in pure functions |
| ~~`apps/api/services/visitor_aggregator.py` (~lines 281-340)~~ **REMOVED at VALIDATE — do not modify this file.** `is_internal_suspect` is a `Visitor`-level column set by an async sweep; it is not a column on `events` and is not visible inside this per-visitor, events-scoped SQL (the `FILTER (WHERE NOT is_flagged_abuse)` clauses read `events.is_flagged_abuse`, an ingest-time per-event column — a structurally different concept). This query also builds a flagged visitor's OWN row (their own true per-visitor stats), which "flag-but-store" does not require altering. See Validate Contract Dimension Findings for the full mechanical-feasibility finding. | No change. |
| **`apps/api/services/daily_digest.py` (`_site_day_stats`, ~lines 224-240) — VALIDATE ADDITION** | This is the real site-level cross-visitor aggregate this plan's Query A harm measures: `func.count().filter(Visitor.first_seen >= cutoff)` + `func.sum(Visitor.total_pageviews).filter(Visitor.last_seen >= cutoff)`, scoped `.where(Visitor.site_id == site_id, human_only_visitor_filter())`. Add `Visitor.is_internal_suspect.is_(False)` to that `.where(...)` clause — same additive pattern as the existing `human_only_visitor_filter()` exclusion already applied there. Gate this behind `site.internal_damping_enabled` (pass the site's flag value into `_site_day_stats` or check it at the caller) so damping-OFF sites see byte-identical digest numbers. |
| **Grep sweep for other site-level cross-visitor `Visitor` aggregates — VALIDATE ADDITION** | Run `grep -rn "func.sum(Visitor\|func.avg(Visitor\|func.count().*Visitor\|select_from(Visitor)" apps/api/routers apps/api/services` and apply the same `is_internal_suspect.is_(False)` exclusion (gated on `internal_damping_enabled`) to every SITE-LEVEL cross-visitor SUM/COUNT/AVG call site found (confirmed present: `apps/api/routers/dashboard.py::get_overview`'s `visitor_rows` grouped-count query is a per-site COUNT, not a SUM of a distortable metric — evaluate whether `eligible_for_resolution`/`total` counts should exclude flagged visitors too, or whether count-only metrics are lower priority than the SUM-based ones; use judgment, note the decision in the phase report). **Company-level totals (`apps/api/routers/companies.py`, incremented via `_upsert_company`'s `companies.total_pageviews + EXCLUDED.total_pageviews` merge in `visitor_aggregator.py` ~line 836) are OUT OF SCOPE for this plan** — fixing them requires changing an increment-on-conflict accumulator, not a filtered SELECT, and is a larger structural change. Document as a known-gap if still open at closeout (see Test Infra Improvement Notes). |
| `apps/api/services/resolution_runner.py:66-80` | Add a deprioritisation clause to the eligibility query's `.order_by(...)`: outlier-flagged visitors sort AFTER non-flagged visitors (e.g. `order_by(Visitor.is_internal_suspect.asc(), Visitor.intent_score.desc())` — non-flagged/False sorts first since `False < True`), never excluded outright — still eventually resolvable if budget allows. **VALIDATE confirmed this is mechanically trivial**: `site: Site` is already an in-scope parameter of `run_resolution_for_site`, so the conditional order-by is a plain Python branch (`order_by(Visitor.is_internal_suspect.asc(), Visitor.intent_score.desc()) if site.internal_damping_enabled else order_by(Visitor.intent_score.desc())`), not a SQL CASE — no ambiguity remains. |
| `apps/api/routers/visitors.py` (new endpoint, near `resolve_one_visitor` ~line 788 or `manual_identify_visitor` ~line 909) | New `POST /{site_id}/{visitor_id}/internal-override` endpoint accepting `{"override": "internal" \| "not_internal" \| null}`, writes `Visitor.internal_override` (multi-tenant scoped via existing `Site.user_id == user.id` pattern) |
| `apps/web/src/lib/api-types.ts` | Add `is_internal_suspect: boolean` and `internal_override: "internal" \| "not_internal" \| null` to the visitor type(s) that already carry `is_bot_suspect` |
| `apps/web/src/lib/api.ts` | Add client method for the new override endpoint (mirrors existing visitor action methods, e.g. `resolveVisitor`/`identifyVisitor`) |
| `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` (~lines 479-486, second occurrence ~line 839) | Add badge (honesty-constraint copy: "Unusually high activity") + "This is me / my team" action button wired to the new endpoint |
| `apps/web/src/app/dashboard/visitors/page.tsx` (~line 695) | Add matching badge on the visitor list row (same tooltip copy) |
| `apps/web/src/components/site-settings-dialog.tsx` | Add `internal_damping_enabled` per-site toggle (mirrors existing `auto_identify_enabled`/`hot_alert_enabled` toggle UI in the same dialog) |
| `tests/unit/test_outlier_traffic_damping.py` (new file) | Unit tests for the pure scoring functions — mirrors `tests/unit/test_cadence_bot_flag.py` structure |
| `tests/unit/test_identity_classification.py` or existing arity/tripwire tests | Extend arity assertion coverage if a shared test asserts `is_emailable_identity` signature — confirm still 3 params (no new param added by this plan) |
| `tests/integration/` (existing visitor/aggregator/resolution/digest integration test files — exact filenames confirmed at RESEARCH re-entry in EXECUTE) | Add coverage for cross-visitor aggregate exclusion (`daily_digest.py`) + resolution deprioritisation |

## Public Contracts

- **New DB columns** (additive, nullable/defaulted — no breaking change to existing rows): `visitors.is_internal_suspect`, `visitors.internal_override`, `identified_visitors.is_internal_suspect`, `sites.internal_damping_enabled`.
- **New API surface:** `POST /api/v1/visitors/{site_id}/{visitor_id}/internal-override` — new endpoint, additive, tenant-scoped identically to existing visitor endpoints (404 on foreign site_id, never 403 — matches repo convention in `process/context/all-context.md` Multi-tenancy section).
- **Response shape change:** `VisitorDetailOut` / visitor list response schemas gain two new fields (`is_internal_suspect`, `internal_override`) — additive, non-breaking for existing consumers (same pattern as `is_bot_suspect` addition).
- **No change** to `is_emailable_identity` signature (constraint #2) — this feature never touches outreach eligibility.
- **No change** to `human_only_visitor_filter()` — orthogonal concern (agent-derived exclusion), not modified.

## Blast Radius

- **Risk class:** data-quality / analytics correctness + identity-resolution budget allocation. NOT auth, NOT billing, NOT destructive-migration (additive-only schema change), NOT public API contract breakage (additive fields only). One net-new small API endpoint (tenant-scoped, same pattern as existing endpoints — low risk). **VALIDATE confirms this is NOT a high-risk trust-boundary class per `orchestration.md` §High-Risk Execution Handoff — no auth/identity, no billing/credits, no destructive migration, no public API contract break, no deploy/runtime/container/proxy/gateway change, no permission/secret/trust-boundary logic. The 5-artifact evidence pack (`vc-risk-evidence-pack`) is NOT required for this plan; EXECUTE should not block waiting for it.**
- **Packages touched:** `apps/api` (models, services, jobs, routers, migrations), `apps/web` (dashboard components, api client, types), `tests/unit`, `tests/integration`.
- **File count:** ~17 files touched/created (see Touchpoints table — `visitor_aggregator.py` removed, `daily_digest.py` added net-neutral, plus the grep-sweep may touch 0-2 more site-level aggregate call sites) — within COMPLEX-plan-but-single-package-cluster range, not a phase program (single cohesive feature, no independent multi-week phases).
- **Reversibility:** fully reversible — sticky flags can be manually cleared via `internal_override`; migration is additive (clean `downgrade()` drops the 3 columns); feature flag `internal_damping_enabled` allows instant per-site rollback to pre-feature behavior without touching data.

## Implementation Order (encode as the checklist below)

1. Schema: `is_internal_suspect` + `internal_override` on Visitor, mirrored `is_internal_suspect` on IdentifiedVisitor, `internal_damping_enabled` on Site + migration.
2. Pure scoring function (site-relative outlier + multi-day persistence + engagement-present conjunction), zero I/O, fully unit-testable.
3. Wire into a new batch sweep (mirrors `cadence_bot_flag_sweep.py`), registered in the existing APScheduler job list.
4. Exclude flagged visitors from SITE-LEVEL cross-visitor aggregate metrics (`daily_digest.py` and any other cross-visitor `Visitor` aggregate found by the grep sweep — NOT `visitor_aggregator.py`'s per-visitor row builder); deprioritise (not exclude) in `resolution_runner.py` ordering.
5. UI: badge on visitor row/detail (honesty-constraint copy), "This is me / my team" action (standalone, independent of `internal_damping_enabled`), per-site enable toggle in site settings dialog.

## Implementation Checklist

1. **Confirm live migration head.** Run `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` and use the real returned revision as `down_revision` — do NOT reuse `b1e7f3c9d425` from this plan without re-confirming; the chain may have moved.
2. **`apps/api/models/visitor.py`** — add `is_internal_suspect: Mapped[bool]` (Boolean, default False, server_default false, nullable False) to `Visitor`, placed directly after the existing `is_bot_suspect` column (~line 89), with an inline comment following the `is_bot_suspect` comment convention (visibility-only, sticky, structurally independent of `is_abuse_flagged`/`is_emailable_identity`). Add `internal_override: Mapped[str | None]` (String, nullable=True, no default — `None` means "no manual action taken") immediately after, with an inline comment documenting the 3-state semantics (`None`/`"internal"`/`"not_internal"`) and the "manual always wins, sticky in both directions" rule.
3. **`apps/api/models/visitor.py`** — add mirrored `is_internal_suspect: Mapped[bool]` to `IdentifiedVisitor`, matching the existing `is_bot_suspect` mirror pattern (~line 129), with an inline comment noting it is copied from `Visitor.is_internal_suspect` at aggregation time.
4. **`apps/api/models/site.py`** — add `internal_damping_enabled: Mapped[bool]` (default False, server_default false, nullable False) after `hot_alert_enabled` (~line 31), with an inline comment: "When True, outlier/internal-traffic damping (sweep-detected + manual override) is applied to this site's aggregates and resolution ordering. Default OFF."
5. **New migration** `apps/api/migrations/versions/{new_rev}_add_internal_traffic_damping.py` — additive `op.add_column` for the 3 new columns (2 boolean with `server_default=sa.false()`, 1 nullable string with no default), `down_revision` set from step 1's live-confirmed head, docstring following the `e6b2d4a1c837` migration's docstring conventions (additive/non-destructive framing, OFFLINE-VALIDATED-ONLY note, chain confirmation note). `downgrade()` drops the 3 columns in reverse order.
6. **Offline `--sql` validate** the new migration using an explicit `<confirmed-head>:<new-rev>` range (per Hard Safety Constraint #5 — the `head`/`-1` shorthand is broken in this repo). Do NOT run a live `alembic upgrade` against any real database as part of this plan.
7. **New file `apps/api/services/outlier_traffic_damping.py`** — pure, I/O-free functions matching `cadence_bot_flag.py`'s shape exactly:
   - `compute_event_count_outlier_score(visitor_event_count: int, site_event_counts: list[int]) -> float | None` — returns a site-relative measure (e.g. z-score vs the site's own median/stddev of per-visitor event counts, or a percentile rank) — `None` when the site has too few visitors to judge (sample-size floor, mirrors `compute_cadence_variance`'s `None`-on-insufficient-data pattern).
   - reuse `compute_engagement_ratio` from `cadence_bot_flag.py` directly (**VALIDATE confirmed**: `compute_engagement_ratio(event_types: list[str]) -> float` is already fully generic — event-type list in, ratio out — safe to import and reuse verbatim, no duplication needed).
   - `compute_multi_day_persistence(visit_timestamps: list[datetime], min_days: int) -> bool` — True only when the elevated activity is sustained across `min_days` distinct calendar days (not a single-day burst).
   - `evaluate_outlier_flag(outlier_score: float | None, engagement_ratio: float, persistent: bool, min_sample_met: bool, outlier_threshold: float, min_engagement_ratio: float) -> bool` — pure decision function; conjunction of (a) sample-size precondition met, (b) score exceeds threshold, (c) persistence True, (d) engagement ratio >= `min_engagement_ratio` (the human-heavy-user signal — NOT `<=` like the bot-cadence flag; a heavy human scrolls/clicks/dwells, so engagement must be PRESENT, inverse polarity from `cadence_bot_flag`'s `evaluate_cadence_bot_flag`). All thresholds passed in as parameters — never read from settings inside these pure functions, matching the `cadence_bot_flag.py` convention. **VALIDATE confirmed `evaluate_cadence_bot_flag`'s structure (sample-size-first, then strict conjunction, thresholds passed in) is a directly applicable structural precedent.**
8. **New file `apps/api/services/outlier_traffic_damping_sweep.py`** — batch wrapper mirroring `cadence_bot_flag_sweep.py`:
   - top-level entrypoint `run_outlier_traffic_damping_sweep(db)` — no-op / zero queries when no site has `internal_damping_enabled=True` (mirrors the `cadence_bot_flag_enabled` global no-op gate, but per-site here since damping is a per-site toggle).
   - bounded read: `events.created_at >= now() - outlier_traffic_damping_lookback_days` (NON-NEGOTIABLE, same rationale as the cadence sweep's bounded read).
   - per-site: compute the site's own event-count distribution across its visitors first (needed for the site-relative percentile/z-score), then evaluate each visitor.
   - **Override precedence (Hard Safety Constraint #3):** before evaluating or writing, check `Visitor.internal_override`. If `internal_override == "not_internal"`, skip entirely (never re-flag). If `internal_override == "internal"`, the visitor is already treated as flagged (see step 10) — skip the automatic evaluation (it would be redundant and must never "unset" a manual "internal" call either). Only evaluate visitors where `internal_override IS NULL`.
   - sticky OR-merge write on `Visitor.is_internal_suspect` (and the mirrored `IdentifiedVisitor.is_internal_suspect`), exact same `update().where(...is_(False))` shape as `_flag_visitor` in `cadence_bot_flag_sweep.py`.
   - fail-open per-site and per-visitor try/except, matching the existing sweep's resilience shape.
9. **`apps/api/jobs/scheduler.py`** — add `_outlier_traffic_damping_sweep_job()` near `_cadence_bot_flag_sweep_job` (~line 221), following its exact structure (settings-gated early return, import-inside-function, try/except with `logger.exception`), and register via `add_job(...)` near line 484 with `minutes=settings.outlier_traffic_damping_sweep_interval_minutes`, `id="outlier_traffic_damping_sweep"`.
10. **`apps/api/config.py`** — new settings block placed near the `cadence_bot_flag_*` block (~line 320-385), following its inline-comment convention (rollout-order note, "no magic number in pure functions" note, default-OFF-per-site framing since this flag is per-Site not global): `outlier_traffic_damping_sweep_interval_minutes: int = 60`, `outlier_traffic_damping_lookback_days: int = 90`, `outlier_traffic_damping_min_visit_days: int = 5` (sample-size floor, mirrors `cadence_bot_flag_min_visits`), `outlier_traffic_damping_outlier_threshold: float` (tune value TBD by EXECUTE-time data spot-check against the Query A numbers above — start conservative, e.g. calibrated so only visitors clearly in the "heavy" tail per the measured distributions would trip it), `outlier_traffic_damping_min_engagement_ratio: float = 0.1` (placeholder — inverse-polarity threshold vs the cadence-bot 0.05 ceiling; tune before enabling in prod, never ship untuned).

    **RESOLVED at VALIDATE (was: open design ambiguity):** the manual `Visitor.internal_override` write endpoint requires NO flag gate — it is always available regardless of `internal_damping_enabled`. Rationale: (a) the SPEC explicitly frames manual override as "exact, for customers willing to click," independent of the statistical layer; (b) gating it behind `internal_damping_enabled` would block a customer who is wary of the automatic sweep's false-positive risk from manually flagging a known team member — an unnecessary restriction with no safety upside, since a single-visitor manual action has zero blast radius regardless of the site-level toggle; (c) this matches Hard Safety Constraint #3's "reversible, always available" framing. EXECUTE implements the endpoint unconditionally; do not add an `internal_damping_enabled` check to it.
11. **`apps/api/services/daily_digest.py`** (**VALIDATE-CORRECTED — was: `apps/api/services/visitor_aggregator.py`**) — in `_site_day_stats` (~lines 224-240), add `Visitor.is_internal_suspect.is_(False)` to the existing `.where(Visitor.site_id == site_id, human_only_visitor_filter())` clause, gated so this only applies when the site has `internal_damping_enabled=True` (pass the site's flag into the function or check at the call site — resolve exact shape at EXECUTE time). **Do NOT modify `visitor_aggregator.py`'s `FILTER (WHERE NOT is_flagged_abuse)` clauses** — `is_internal_suspect` is a `Visitor`-level column set by an async sweep, not a column on the `events` table, and is not visible inside that per-visitor, events-scoped SQL; that query also builds a flagged visitor's own row (their own true stats), which "flag-but-store" does not require altering. Then **grep for every other SITE-LEVEL cross-visitor `Visitor` aggregate** (`grep -rn "func.sum(Visitor\|func.avg(Visitor\|func.count().*Visitor\|select_from(Visitor)" apps/api/routers apps/api/services`) and apply the same exclusion, gated the same way, to each one found — do not miss any (a missed call site would silently let a flagged visitor's inflated numbers keep distorting that one metric). Company-level totals (`apps/api/routers/companies.py`, incremented via `_upsert_company`'s `+=` merge) are OUT OF SCOPE — document as a known-gap if still open at closeout.
12. **`apps/api/services/resolution_runner.py:80`** — change `.order_by(Visitor.intent_score.desc())` to a conditional order-by: when `site.internal_damping_enabled` is True, `.order_by(Visitor.is_internal_suspect.asc(), Visitor.intent_score.desc())`; otherwise keep `.order_by(Visitor.intent_score.desc())` unchanged (byte-identical for damping-OFF sites). This is deprioritisation, not exclusion — a flagged visitor still resolves if budget allows after all non-flagged eligible visitors are processed for that sweep. **VALIDATE confirmed this is mechanically trivial**: `site: Site` is already an in-scope parameter of `run_resolution_for_site`, so the condition is a plain Python branch, not a SQL CASE expression — no ambiguity remains here. Add an inline comment explaining the ordering rationale (referencing this plan / the measured budget-skew numbers).
13. **`apps/api/routers/visitors.py`** — new `POST /{site_id}/{visitor_id}/internal-override` endpoint. Request body: `{"override": "internal" | "not_internal" | null}`. Multi-tenant scoped identically to sibling endpoints (`Site.user_id == user.id`, 404 on foreign ids per repo convention). Writes `Visitor.internal_override` directly (no sweep re-evaluation triggered synchronously — the next sweep tick picks up the override precedence rule from step 8). When `override == "internal"`, also set `is_internal_suspect = True` immediately (so the UI/aggregates reflect the manual call without waiting for the next sweep tick); when `override == "not_internal"`, also set `is_internal_suspect = False` immediately. Available unconditionally per the resolved item 10.
14. **`apps/web/src/lib/api-types.ts`** — add `is_internal_suspect: boolean` and `internal_override: "internal" | "not_internal" | null` to the visitor type(s) already carrying `is_bot_suspect`.
15. **`apps/web/src/lib/api.ts`** — add a client method for the new override endpoint, mirroring the existing visitor-action method shapes (e.g. matching `resolveVisitor`/`identifyVisitor` signature conventions: `(siteId, visitorId, override) => Promise<...>`).
16. **`apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx`** — add a badge at both existing badge-rendering call sites (~line 479-486 and ~line 839, mirroring the `is_bot_suspect` badge exactly) rendered when `visitor.is_internal_suspect` is true, with tooltip copy honoring the Honesty Constraint: e.g. `"Unusually high activity — this visitor's traffic volume is a statistical outlier for this site. This is a visibility signal only; they stay fully contactable and fully counted unless you confirm below."` Add a "This is me / my team" button (and, when already flagged, a "Not me — clear flag" counter-action) wired to the new API client method from step 15, visible near the badge.
17. **`apps/web/src/app/dashboard/visitors/page.tsx`** — add the matching badge on the visitor list row (~line 695), same tooltip copy as step 16, no action button needed at list-row granularity (action lives on the detail page).
18. **`apps/web/src/components/site-settings-dialog.tsx`** — add an `internal_damping_enabled` toggle, mirroring the existing `auto_identify_enabled`/`hot_alert_enabled` toggle UI pattern in the same dialog (label + description honoring the Honesty Constraint, e.g. "Damp outlier traffic — reduce the influence of unusually high-activity visitors on your analytics and identity-resolution budget").
19. **`tests/unit/test_outlier_traffic_damping.py`** (new) — unit tests for every pure function in step 7, mirroring `tests/unit/test_cadence_bot_flag.py` structure: sample-size floor returns `None`/False, conjunction requires ALL conditions, engagement-ratio polarity is inverse of the cadence-bot test (engagement PRESENT required, not absent), no I/O / no DB session imports anywhere in the pure module (structural test, mirrors the existing `test_emailability_and_aggregator_do_not_read_the_flag`-style source-text assertion — add an equivalent assertion that `identity_classification.py` and `daily_digest.py`'s exclusion logic do not accidentally couple `is_internal_suspect` to emailability).
20. **Regression test** — add or extend a test asserting `inspect.signature(is_emailable_identity).parameters` still has length 3 (confirm the existing `tests/unit/test_cadence_bot_flag.py:293` assertion continues to pass unmodified; do not touch that test, just confirm it stays green after this plan's changes — it is the tripwire proving constraint #2 held).
21. **Integration tests** — extend the relevant existing integration test file(s) covering `daily_digest.py` and `resolution_runner.py` (exact filenames confirmed at EXECUTE-time RESEARCH re-entry per the phase-program inner-loop convention, even though this is a single-plan COMPLEX build, not a phase program) to cover: (a) an outlier-flagged visitor's events are excluded from the `_site_day_stats` cross-visitor sum/count (row still stored in `visitors` table, never deleted), (b) an outlier-flagged visitor sorts after non-flagged visitors in the resolution eligibility query, (c) manual override via the new endpoint is honored by the sweep (never re-flagged/un-flagged by the automatic path once set), (d) damping-OFF sites (`internal_damping_enabled=False`) see byte-identical `_site_day_stats` and resolution ordering behavior.
22. **Run the 5 regression validators** (see Verification Evidence) before closing EXECUTE.

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `pytest tests/unit/test_outlier_traffic_damping.py -m unit -q` | Fully-Automated | Pure scoring functions correctly conjunction-gate on sample-size, outlier-score threshold, persistence, and engagement-PRESENT polarity (inverse of cadence-bot) |
| `pytest tests/unit/test_cadence_bot_flag.py::test_emailability_and_aggregator_do_not_read_the_flag -q` (existing, must stay green unmodified) | Fully-Automated | Constraint #2 — `is_emailable_identity` arity stays 3, `is_internal_suspect` never read by eligibility/aggregator source | proven by: existing tripwire test — strategy: Fully-Automated |
| `pytest tests/unit/test_agent_origin_exclusion.py -m unit -q` (existing regression, full file) | Fully-Automated | No regression to the AC10 agent-origin outreach guard or the literal-field-name tripwire — this plan touches none of the 4 guarded files' `source_agent_visit_id` literal | proven by: existing regression suite — strategy: Fully-Automated |
| New integration test: outlier-flagged visitor excluded from `daily_digest.py::_site_day_stats` cross-visitor sum/count | Hybrid (needs local Postgres+Redis via `docker compose -f infra/docker-compose.yml up -d postgres redis`) | Constraint #1 (flag-but-store) — row survives in `visitors` table, site-level digest aggregate excludes it |
| New integration test: `resolution_runner.py` orders flagged visitor after non-flagged in eligibility query, only for `internal_damping_enabled=True` sites | Hybrid (same precondition) | Design decision — deprioritisation not exclusion; fixes the measured budget-skew (Query C); damping-OFF sites unaffected |
| New integration test: manual `internal_override` write via the new endpoint is honored (sweep never overwrites in either direction once set) | Hybrid (same precondition) | Constraint #3 (reversible, manual always wins, sticky both directions) |
| Offline `alembic upgrade <confirmed-head>:<new-rev> --sql` and `downgrade <new-rev>:<confirmed-head> --sql` | Fully-Automated | Migration is additive/reversible per Constraint #5's explicit-range requirement; no destructive schema change |
| Manual dashboard check: badge tooltip copy on visitor detail + list page reads "unusually high activity" (not "the owner"/"you") | Agent-Probe | Honesty Constraint — copy never asserts identity, only statistical-outlier framing |
| Live migration round-trip on a disposable Postgres | Known-Gap (residual — Docker/live-Postgres not exercised in this sandbox per repo precedent) | Full production-parity migration safety — **kept CONDITIONAL**, backlog stub required per vacuous-green ban (see Test Infra Improvement Notes) |

## Test Matrix

| Layer | Command | Precondition |
|---|---|---|
| Unit (pure functions) | `.venv/bin/python3.11 -m pytest tests/unit/test_outlier_traffic_damping.py -m unit -q` | None |
| Unit (regression — emailability arity) | `.venv/bin/python3.11 -m pytest tests/unit/test_cadence_bot_flag.py -m unit -q` | None |
| Unit (regression — agent-origin guard) | `.venv/bin/python3.11 -m pytest tests/unit/test_agent_origin_exclusion.py -m unit -q` | None |
| Integration (digest + resolution) | `.venv/bin/python3.11 -m pytest tests/integration/ -m integration -q -k "digest or aggregator or resolution"` | `docker compose -f infra/docker-compose.yml up -d postgres redis` |
| Full integration lane (final gate before close) | `.venv/bin/python3.11 -m pytest tests/ -m integration -q` | Same as above |
| Offline migration dry-run | `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade <confirmed-head>:<new-rev> --sql` and the matching `downgrade` | None (offline) |
| Agent-probe (dashboard copy) | Manual visual check of badge + toggle copy against Honesty Constraint | Dev server running |
| Frontend build | `cd apps/web && npm run build` | None |

## Risks

| Risk | Mitigation |
|---|---|
| Migration head moves again between VALIDATE and EXECUTE (this repo has a documented history of concurrent-session collisions — head already moved once between the SPEC context doc and this PLAN, and VALIDATE independently reconfirmed `b1e7f3c9d425` on 27-07-26) | Checklist item 1 mandates a fresh live `alembic heads` check immediately before writing `down_revision`; never trust this plan's recorded head value |
| Threshold miscalibration (outlier_threshold / min_engagement_ratio) flags a genuinely high-intent normal visitor, or fails to flag the measured heavy visitors | Ship default OFF per-site; document in config.py that thresholds must be tuned against real event-count distributions (the Query A/B numbers above) before any site enables the flag in production — same rollout-order discipline as `cadence_bot_flag_*` |
| `resolution_runner.py` ordering change silently affects sites with `internal_damping_enabled=False` | Checklist item 12 explicitly requires the ordering change to be conditional on the site's flag (a Python-level branch, confirmed trivial by VALIDATE) — behavior must stay byte-identical for damping-OFF sites |
| **(VALIDATE-FOUND) Aggregate exclusion targeted the wrong file/mechanism** — the original checklist named `visitor_aggregator.py`'s events-scoped FILTER clauses, but `is_internal_suspect` is a `Visitor`-level column invisible to that SQL; the real Query A distortion lives in cross-visitor aggregates like `daily_digest.py` | Corrected in this VALIDATE pass: checklist item 11 now targets `daily_digest.py::_site_day_stats` + a grep sweep for other cross-visitor `Visitor` aggregates; `visitor_aggregator.py` is explicitly left untouched |
| Company-level totals (`companies.py`) not excluded from outlier influence — increment-based `_upsert_company` merge, not a filtered SELECT | Documented out-of-scope known-gap; write a backlog note if still open at closeout |
| Aggregator FILTER clause miss (one of the ~14 FILTER expressions not updated) | N/A — superseded; `visitor_aggregator.py` is no longer touched by this plan |
| Copy drift — a future PR could accidentally reintroduce "this is the owner" language | Agent-Probe gate in Verification Evidence catches this at EXECUTE close; Honesty Constraint documented at top of this plan as binding context for any agent touching UI copy |

## Test Infra Improvement Notes

- Live migration round-trip on a disposable Postgres is a Known-Gap for this plan (Docker-gate parity with every other pending-migration feature in this repo — see `process/context/all-context.md` migration chain notes). Per the vacuous-green ban: this gap requires a backlog stub, and the "migration safety" gate stays CONDITIONAL, never silently PASS-able on the Known-Gap alone (this is not vacuously green — the migration also has real Fully-Automated offline `--sql` coverage in both directions; the live-Postgres round-trip is an additional residual on top of that, not the sole gate). EXECUTE/UPDATE-PROCESS must write a backlog note (e.g. `process/general-plans/backlog/outlier-traffic-damping-live-migration-round-trip_NOTE_{date}.md`) if this gap is still open at closeout.
- No existing test file name is confirmed for `tests/integration/` coverage of `daily_digest.py`/`resolution_runner.py` at VALIDATE time — EXECUTE must do a quick RESEARCH re-entry (grep for existing test files covering those two modules) before deciding whether to extend an existing file or create a new one. This is noted as an open item, not a blocker.
- Company-level total distortion (`companies.py`) is an accepted out-of-scope known-gap for this plan (see Risks table) — write a backlog note if still open at closeout.

## Acceptance Criteria

1. `visitors.is_internal_suspect`, `visitors.internal_override`, `identified_visitors.is_internal_suspect`, `sites.internal_damping_enabled` exist as additive columns via a clean, reversible Alembic migration (offline `--sql` validated both directions).
2. Pure scoring functions in `outlier_traffic_damping.py` correctly conjunction-gate on sample-size floor, site-relative outlier threshold, multi-day persistence, and engagement-ratio PRESENT (inverse polarity of the cadence-bot-flag ceiling) — proven by unit tests with zero I/O.
3. The new batch sweep flags outlier visitors sticky (OR-merge, never un-flags automatically) and NEVER overwrites an explicit `internal_override` in either direction.
4. **(AMENDED 27-07-26 — suggestion-only, see AC10)** `daily_digest.py::_site_day_stats` (and any other site-level cross-visitor `Visitor` aggregate found by the checklist-item-11 grep sweep) excludes every **human-CONFIRMED** (`internal_override == "internal"`) visitor from its computation, gated on `internal_damping_enabled` (flag-but-store — rows never deleted). `is_internal_suspect` MUST NOT appear in this query. `visitor_aggregator.py`'s per-visitor row-building SQL is unchanged.
5. **(AMENDED 27-07-26 — suggestion-only, see AC10)** `resolution_runner.py` deprioritises (sorts after, never excludes) **human-CONFIRMED** (`internal_override == "internal"`) visitors in the eligibility query, only for sites with `internal_damping_enabled=True`; behavior is byte-identical for damping-OFF sites. `is_internal_suspect` MUST NOT appear in this ordering.
6. `is_emailable_identity` signature stays exactly 3 parameters; `is_internal_suspect` is never read by it or by any outreach-eligibility path.
7. The manual "This is me / my team" endpoint lets a user set `internal_override` to `"internal"` or `"not_internal"`, tenant-scoped, works standalone (no `internal_damping_enabled` dependency), and that value always wins over and is never overwritten by the automatic sweep.
8. Feature is default OFF per site (`internal_damping_enabled=False`); dashboard badge and toggle copy never assert the flagged visitor's identity — only "unusually high activity" framing (Honesty Constraint).
9. All 5 regression validators pass; full existing unit + integration suites show no regressions, in particular the AC10 agent-origin exclusion tests and the `is_emailable_identity` arity tripwire.
10. **SUGGESTION-ONLY (added 27-07-26, post-calibration — supersedes the automatic-exclusion reading of AC4/AC5).** The automatic scorer produces a SUGGESTION, never a decision. `is_internal_suspect` is a label: it drives a badge and a "review these" surface and nothing else. It MUST NOT by itself exclude a visitor from the `daily_digest` aggregate and MUST NOT by itself deprioritise them in `resolution_runner`. **Only an explicit human confirmation (`internal_override == "internal"`) causes exclusion or deprioritisation.** An auto-flagged, unconfirmed visitor (`is_internal_suspect=True`, `internal_override IS NULL`) must be fully counted in the digest and hold normal resolution order — proven by dedicated tests at both unit and integration level.

   **Calibration data (measured live on production, read-only, 2026-07-27):**

   | Threshold | Flagged | Of those, ALREADY identified with a real email |
   |---|---|---|
   | ≥20x median & ≥3 days | 34 | 5 |
   | ≥50x median & ≥3 days | 21 | 3 |
   | ≥100x median & ≥5 days | 15 | 2 |

   There are only **28 identified visitors in the entire production system**. Automatic exclusion at 20x would therefore have silently hidden **5 of 28 = 18% of every customer's real leads**. Even the strictest threshold still catches 2 real identified people. No statistical threshold can separate "site owner who browses 30k times" from "extremely engaged prospect" — both are high-volume, multi-day, fully engaged. The two error types are wildly asymmetric: hiding a real lead destroys the exact thing the customer pays for, silently, with no error surfaced; failing to hide an owner merely leaves a slightly noisy dashboard. Hence: the machine suggests, the human decides. Risk of silently hiding a real lead on the automatic path is now structurally zero.

11. **Calibrated defaults (added 27-07-26).** `outlier_traffic_damping_outlier_threshold = 50.0` and `outlier_traffic_damping_min_visit_days = 3` — the 50x/3d row above. This sizes a SUGGESTION list a customer can review in about a minute (21 visitors across all sites), not an exclusion set.
12. **Copy is a question, not a verdict (added 27-07-26).** User-facing strings must read as a suggestion needing review ("Unusually high activity — is this you?"), must state that nothing changes until the user confirms, and must never assert that the visitor IS the customer. Enforced by `test_user_facing_copy_never_asserts_the_visitors_identity`.

## Phase Completion Rules

This is a SIMPLE-to-COMPLEX single-package-cluster plan (not a phase program) — there is one completion gate, not per-phase gates:

- Plan moves from `Ready for VALIDATE` → `VALIDATED` when `vc-validate-agent` writes a `Gate: PASS` or accepted-`CONDITIONAL` verdict into the Validate Contract section below. **Done — see Validate Contract: Gate: CONDITIONAL.**
- Plan moves from `VALIDATED` → `CODE DONE` when all Implementation Checklist items are complete and all Fully-Automated + Hybrid gates in Verification Evidence are green (Known-Gap rows stay CONDITIONAL per the vacuous-green ban and do not block CODE DONE, but must have a backlog stub — see Test Infra Improvement Notes).
- Plan moves from `CODE DONE` → `VERIFIED` only after EVL (execute-validate-loop) independently re-confirms every gate via a spawned `vc-tester` run — never on execute-agent's self-report alone.
- Plan is archived (`process/general-plans/completed/`) only after UPDATE PROCESS runs and any open known-gaps have a written backlog note.

## Validate Contract

Status: CONDITIONAL
Date: 27-07-26
date: 2026-07-27
generated-by: outer-pvl

Parallel strategy: sequential
Rationale: Score 2/7 (S6 borderline-no — not actually a high-risk class per independent re-check; S7 — 17 files touched). Single cohesive COMPLEX plan, not a phase program; Layer 1 + Layer 2 checks were run as a single-agent sequential VALIDATE pass (no coordination needed across independent agents in this session) rather than a multi-agent fan-out, given the scope fit comfortably in one grounded read-through of every touchpoint file.

Test gates (5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC2 | Pure scoring functions conjunction-gate correctly (sample-size, threshold, persistence, engagement-PRESENT) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_outlier_traffic_damping.py -m unit -q` | B |
| AC6 | `is_emailable_identity` arity stays 3; flag never read by eligibility | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_cadence_bot_flag.py -m unit -q` | A |
| AC9 (regression) | No regression to AC10 agent-origin guard / literal-field tripwire | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_agent_origin_exclusion.py -m unit -q` | A |
| AC4 | Flagged visitor excluded from `daily_digest.py::_site_day_stats` cross-visitor sum/count, gated on `internal_damping_enabled`, row never deleted | Hybrid | `.venv/bin/python3.11 -m pytest tests/integration/ -m integration -q -k "digest or aggregator or resolution"` (precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis`) | B |
| AC5 | `resolution_runner.py` deprioritises flagged visitor, byte-identical for damping-OFF sites | Hybrid | same integration command as AC4 | B |
| AC3 / AC7 | Manual override wins in both directions permanently; sweep never overwrites it | Hybrid | same integration command as AC4 | B |
| AC1 | Migration additive/reversible, explicit-range offline validated | Fully-Automated | `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade <confirmed-head>:<new-rev> --sql` and matching `downgrade <new-rev>:<confirmed-head> --sql` | A |
| AC8 | Honesty Constraint copy never asserts identity | Agent-Probe | Manual dashboard visual check of badge/toggle copy | B |
| Frontend build | No TypeScript/build regressions from new types/components | Fully-Automated | `cd apps/web && npm run build` | A |
| Live migration round-trip | Production-parity migration safety on a real Postgres | Known-Gap | — (residual; Docker daemon not available in this sandbox, matching repo-wide precedent) | D |

gap-resolution legend:
- A — proven now (gate passes in this cycle)
- B — fixed in this plan (gate added by this plan's checklist)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

C-4 reconciliation: the `strategy:` column carries ONLY the 3 proving strategies (Fully-Automated / Hybrid / Agent-Probe). Known-Gap is a named residual row (gap-resolution D), never a proving strategy.

Legacy line form (retained for existing validate-contract consumers):
- Pure scoring functions: Fully-automated: `pytest tests/unit/test_outlier_traffic_damping.py -m unit -q`
- Emailability regression: Fully-automated: `pytest tests/unit/test_cadence_bot_flag.py -m unit -q`
- Agent-origin regression: Fully-automated: `pytest tests/unit/test_agent_origin_exclusion.py -m unit -q`
- Cross-visitor aggregate exclusion + resolution deprioritisation: Hybrid: `pytest tests/integration/ -m integration -q -k "digest or aggregator or resolution"` + `docker compose -f infra/docker-compose.yml up -d postgres redis`
- Migration safety: Fully-automated: `alembic upgrade <confirmed-head>:<new-rev> --sql` + `downgrade <new-rev>:<confirmed-head> --sql`
- Dashboard copy: agent-probe: manual visual check against Honesty Constraint
- Frontend build: Fully-automated: `cd apps/web && npm run build`
- Live migration round-trip: known-gap: documented, backlog stub required

Dimension findings:
- Infra fit: PASS — sweep/scheduler/config/model changes mirror `cadence_bot_flag.py`/`cadence_bot_flag_sweep.py` exactly; live `alembic heads` independently re-run by VALIDATE on 27-07-26 confirms single head `b1e7f3c9d425`, matching the plan's claim exactly.
- Test coverage: CONCERN (accepted) — one Known-Gap (live migration round-trip on a real Postgres) with real Fully-Automated offline coverage underneath it, not vacuously green; backlog stub required at closeout per the plan's own Test Infra Improvement Notes.
- Breaking changes: PASS — all schema/API changes are additive; `is_emailable_identity` signature independently re-read and confirmed still 3 params; `human_only_visitor_filter()` untouched.
- Security surface: PASS — no auth/identity, no billing/credits, no destructive migration, no public-contract break, no deploy/runtime/container/proxy/gateway change, no secret/trust-boundary logic. This is NOT a high-risk trust-boundary class per `orchestration.md` §High-Risk Execution Handoff — the 5-artifact evidence pack (`vc-risk-evidence-pack`) is explicitly NOT required; EXECUTE must not block waiting for it.
- Section — Schema/migration (checklist 1-6): PASS — mechanically sound; live head independently reconfirmed.
- Section — Pure scoring functions (checklist 7): PASS — `compute_engagement_ratio` confirmed generic/reusable verbatim; `evaluate_cadence_bot_flag`'s structure confirmed as a valid precedent for `evaluate_outlier_flag`.
- Section — Batch sweep + scheduler wiring (checklist 8-10): PASS after fix — checklist item 10's manual-override-gating ambiguity is now RESOLVED in this contract (standalone, no `internal_damping_enabled` dependency); override precedence logic (step 8) correctly achieves bidirectional-sticky reversibility, improving on both reused precedents (`is_bot_suspect` and `is_abuse_flagged` are one-way-sticky with no override; this design deliberately adds a tri-state override the precedents lack).
- Section — Aggregate exclusion + resolution deprioritisation (checklist 11-12): CONCERN → FIXED IN THIS PASS — the original checklist item 11 named `apps/api/services/visitor_aggregator.py`'s `FILTER (WHERE NOT is_flagged_abuse)` clauses (~lines 281-340) as the fix location. VALIDATE independently read that file and confirmed those clauses operate on `events.is_flagged_abuse`, a per-EVENT column set at ingest time — the SQL runs `FROM events` (via `session_boundaries`/`session_numbered` CTEs) and has no visibility into `Visitor.is_internal_suspect`, which is a per-VISITOR column set by an asynchronous batch sweep. The literal instruction ("`FILTER (WHERE NOT is_flagged_abuse AND NOT is_internal_suspect)`") would either fail at runtime (`column "is_internal_suspect" does not exist`) or require an unplanned JOIN that still wouldn't fix the measured harm — that query builds a flagged visitor's OWN row from their OWN events, which "flag-but-store" does not require altering. VALIDATE traced the plan's own motivating evidence (Query A: 89-95% of 90-day events from heavy visitors) to the actual mechanism that would show this distortion — `apps/api/services/daily_digest.py::_site_day_stats` (~lines 224-240), a genuine SITE-LEVEL cross-visitor aggregate (`func.sum(Visitor.total_pageviews)` + `func.count()` across all of a site's visitors, already gated by the `human_only_visitor_filter()` precedent) — and corrected the plan's Touchpoints, checklist item 11, Risks, Acceptance Criteria, and Verification Evidence accordingly. `resolution_runner.py`'s checklist item 12 required no correction — independently confirmed mechanically trivial (plain Python conditional on an already in-scope `site` parameter, not a SQL-level concern).
- Section — API endpoint (checklist 13): PASS — mirrors existing tenant-scoped pattern exactly (`Site.user_id == user.id`, 404-on-foreign-id convention independently confirmed present elsewhere in `routers/visitors.py`).
- Section — Frontend (checklist 14-18): PASS — types/client/badge/toggle targets independently confirmed present at (approximately) the cited line numbers; minor line-number drift from concurrent unrelated work (`intent-score-info.tsx`/`visitor_aggregator.py` intent-score changes) does not block — targets remain uniquely matchable by content, not just line number.
- Section — Tests (checklist 19-21): PASS — `test_cadence_bot_flag.py:293` arity tripwire and `test_agent_origin_exclusion.py:207-223` literal-field tripwire independently read and confirmed to exist exactly as the plan describes; new test file confirmed not to already exist (no collision).

Open gaps:
- Live migration round-trip on a disposable Postgres — known-gap: documented as backlog stub required at closeout (see Test Infra Improvement Notes); not "NEW PLAN REQUIRED", just deferred verification within this same plan's lifecycle.
- Company-level total distortion (`companies.py`, increment-based merge) — known-gap: out of scope for this plan by design (structural fix, not a filtered SELECT); backlog note if still open at closeout.
- `apps/api/routers/dashboard.py::get_overview`'s visitor COUNT metrics (`total`, `eligible_for_resolution`, etc.) were not independently re-derived as in-scope or out-of-scope by VALIDATE — checklist item 11's grep sweep leaves this decision to EXECUTE's judgment, documented in the phase report either way. This is a design-judgment item, not a mechanical gap.

What this coverage does NOT prove:
- The Fully-Automated unit gates prove the pure scoring functions' logic in isolation; they do NOT prove the batch sweep correctly reads real site-scale distributions from a live database, or that the chosen threshold values are well-calibrated against real traffic (thresholds are explicitly placeholders pending EXECUTE-time data spot-check).
- The Hybrid integration gates prove correctness against a local disposable Postgres; they do NOT prove behavior against a production-scale dataset or under concurrent sweep/resolution contention.
- The offline `--sql` migration gate proves the SQL is syntactically valid and additive; it does NOT prove a live `alembic upgrade` succeeds against a real running Postgres instance (this is the named Known-Gap).
- The Agent-Probe copy check proves the specific reviewed strings comply with the Honesty Constraint at review time; it does NOT prove no future PR reintroduces "the owner" language (only the Agent-Probe gate at each future EXECUTE close catches that, per the Risks table).
- Nothing in this contract proves the `dashboard.py::get_overview` COUNT-based metrics' in/out-of-scope judgment call was correct — that remains an open, non-blocking design decision for EXECUTE.

Gate: CONDITIONAL (concerns noted and fixed in-plan; one accepted known-gap matching established repo precedent)
Accepted by: session (autonomous VALIDATE pass) — the migration-live-round-trip known-gap matches the identical, already-precedented pattern this repo has shipped and archived CONDITIONAL multiple times (ingest-abuse-hardening, cadence-bot-flag, ads-audiences Phase 1/2 — see `process/context/all-context.md`), and the plan's own Phase Completion Rules section already anticipates this exact outcome ("Known-Gap rows stay CONDITIONAL... do not block CODE DONE"). The company-level-totals known-gap is accepted as a deliberate scope boundary (structural fix, not proportionate to this plan's size).

## Autonomous Goal Block

SESSION GOAL: Ship outlier/internal-traffic damping — dampen statistical-outlier visitor influence on analytics and identity-resolution budget, per-site opt-in, fully reversible.
Charter + umbrella plan: N/A — single plan (not a phase program).
Autonomy: Standard /goal autonomous execution rules (`process/development-protocols/orchestration.md` §Autonomy Mode + §Autonomous /goal Phase Program Execution). CONDITIONAL gate already accepted above — EXECUTE may proceed without re-pausing on the accepted known-gaps. BLOCKED sub-items during EXECUTE → backlog note + continue.
Hard stop conditions / safety constraints:
- Never modify `apps/api/services/identity_classification.py::is_emailable_identity` signature (must stay exactly 3 params) or let `is_internal_suspect` be read by it or any outreach-eligibility path.
- Never delete/drop stored events or visitor rows — flag-but-store only.
- Never let the automatic sweep overwrite an explicit `Visitor.internal_override` in either direction once a human has set it.
- Never ship `internal_damping_enabled` defaulted to True, or ship un-tuned threshold defaults live without an explicit operator calibration step.
- Never assert visitor identity ("this is the owner"/"you") in any user-facing copy — "unusually high activity" framing only (Honesty Constraint).
- Do NOT modify `apps/api/services/visitor_aggregator.py`'s FILTER clauses for this feature (VALIDATE-corrected — see Dimension Findings).
- Re-run `alembic heads` live immediately before writing the migration's `down_revision` — do not trust any previously recorded head value.
Next phase: EXECUTE: `process/general-plans/active/outlier-traffic-damping_27-07-26/outlier-traffic-damping_PLAN_27-07-26.md`
Validate contract: inline in plan (see `## Validate Contract` section above)
Execute start: fully-auto commands: `.venv/bin/python3.11 -m pytest tests/unit/test_outlier_traffic_damping.py tests/unit/test_cadence_bot_flag.py tests/unit/test_agent_origin_exclusion.py -m unit -q` then `cd apps/web && npm run build` | e2e spec: integration `-k "digest or aggregator or resolution"` (needs `docker compose -f infra/docker-compose.yml up -d postgres redis`) | probe scenario: manual dashboard badge/toggle copy check | high-risk pack: no (not a high-risk trust-boundary class — see Dimension Findings)

## Resume and Execution Handoff

1. **Selected plan file path:** `process/general-plans/active/outlier-traffic-damping_27-07-26/outlier-traffic-damping_PLAN_27-07-26.md`
2. **Last completed phase or step:** VALIDATE (this pass) — Gate: CONDITIONAL, plan corrected in-place. Ready for EXECUTE.
3. **Validate-contract status:** written (27-07-26), Gate: CONDITIONAL, accepted by session per established repo precedent.
4. **Supporting context files loaded:** `process/context/all-context.md`, `process/context/tests/all-tests.md`, `process/development-protocols/orchestration.md`, plus live reads of `apps/api/services/resolution_runner.py`, `apps/api/models/visitor.py`, `apps/api/models/site.py`, `apps/api/services/cadence_bot_flag.py`, `apps/api/services/cadence_bot_flag_sweep.py`, `apps/api/jobs/scheduler.py`, `apps/api/config.py`, `apps/api/services/visitor_aggregator.py` (full FILTER-clause + upsert-merge context, ~lines 175-345 and ~520-710), `apps/api/services/daily_digest.py` (~lines 200-250), `apps/api/routers/companies.py`, `apps/api/routers/dashboard.py` (`get_overview`), `apps/api/services/identity_classification.py`, `apps/api/services/agent_visitor_filters.py`, `tests/unit/test_cadence_bot_flag.py` (line 293), `tests/unit/test_agent_origin_exclusion.py` (lines 200-226), `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx`, `apps/web/src/app/dashboard/visitors/page.tsx`, `apps/api/routers/visitors.py`. Independently re-ran `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` (confirmed `b1e7f3c9d425`, single head) and `node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs` (0 failures/warnings) during this VALIDATE pass.
5. **Next step for a fresh agent picking up mid-execution:** Say "ENTER EXECUTE MODE" to run `vc-execute-agent` against this plan. Follow the Implementation Checklist in order (items 10, 11 already resolved/corrected by VALIDATE — do not re-litigate them). Re-run `alembic heads` LIVE immediately before writing the new migration's `down_revision` — do not trust `b1e7f3c9d425` without re-confirming.
