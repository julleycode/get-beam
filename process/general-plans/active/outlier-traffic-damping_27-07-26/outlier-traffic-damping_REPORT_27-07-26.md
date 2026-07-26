---
phase: outlier-traffic-damping
date: 2026-07-27
status: COMPLETE_WITH_GAPS
feature: general-plans
plan: process/general-plans/active/outlier-traffic-damping_27-07-26/outlier-traffic-damping_PLAN_27-07-26.md
---

# EXECUTE exit summary — outlier / internal-traffic damping

## What Was Done

All 22 Implementation Checklist items complete.

**Schema (1-6).** Live `alembic heads` re-run immediately before writing `down_revision`:
returned `b1e7f3c9d425`, single head — matched the plan's recorded value, but was
re-confirmed rather than trusted. New migration `f3a7c9e21b48_add_internal_traffic_damping`
adds 4 additive columns: `visitors.is_internal_suspect`, `visitors.internal_override`,
`identified_visitors.is_internal_suspect`, `sites.internal_damping_enabled`.

**Reversibility — the core safety property.** `is_internal_suspect` is deliberately NOT
modelled on the two existing precedents. `is_bot_suspect` and `is_abuse_flagged` are
one-way sticky, OR-merged forever; this flag is neither. The sweep writes the CURRENT
verdict in both directions (`values(is_internal_suspect=flagged)`), so a visitor whose
volume normalises is automatically un-flagged and returns to aggregates and to the front of
the resolution queue. The sweep skips any visitor with a non-NULL `internal_override`, which
is the single mechanism enforcing "the human's call wins permanently, in BOTH directions".

**Pure scorer (7).** `apps/api/services/outlier_traffic_damping.py` — I/O-free, no settings
reads, mirrors `cadence_bot_flag.py`. Site-relative by construction: score is
`visitor_event_count / median(that site's per-visitor event counts)`, so a 29-visitor site
and a 532-visitor site are judged on the same scale-free axis. Median not mean, so a huge
visitor cannot drag the baseline up and mask themselves. Four-way conjunction with the
sample-size precondition first. Engagement polarity is INVERSE to the cadence-bot flag
(`>=` floor, not `<=` ceiling) — engagement present is what separates a heavy human from a
heavy scraper. `compute_engagement_ratio` reused verbatim from `cadence_bot_flag.py`.

**Sweep + scheduler + config (8-10).** New sweep mirrors `cadence_bot_flag_sweep.py`
(bounded read, per-visitor/per-site fail-open) but with the reversible write described
above. Per-site opt-in: only sites with `internal_damping_enabled=True` are read at all, so
with nobody opted in the sweep issues one cheap query and exits. New `config.py` block with
documented rollout order and explicit "these are placeholders, tune before enabling" notes.

**Aggregate exclusion (11).** Applied the VALIDATE correction — `daily_digest.py::_site_day_stats`,
NOT `visitor_aggregator.py`. Gated on the site's flag (threaded through from the caller's
site query), so damping-OFF sites get a byte-identical query. `visitor_aggregator.py` was
not touched by this feature; an automated test asserts it stays free of the new column.

**Resolution deprioritisation (12).** `order_by(Visitor.is_internal_suspect.asc(),
Visitor.intent_score.desc())` when the site opts in. Deprioritise, never exclude — the
flagged visitor still resolves if budget remains. Reads the toggle via
`getattr(site, ..., False)` so it fails SAFE to "damping off" for any site object predating
the column; damping can never switch itself on by accident.

**Manual override endpoint (13).** `POST /{site_id}/{visitor_id}/internal-override`,
tenant-scoped via the existing `_verify_site_access` (404 on foreign ids). Standalone — NOT
gated on `internal_damping_enabled`, per the VALIDATE resolution; an automated AST test
proves the gate is absent from the function body. Writes `is_internal_suspect` immediately
so the UI and aggregates reflect the decision without waiting for the next sweep tick, and
mirrors it to `IdentifiedVisitor`.

**Frontend (14-18).** Types, client methods (`setInternalDamping`, `setInternalOverride`),
detail-page badge + Activity row with "This is me / my team" / "Not me — clear flag" /
"Undo my choice" actions, list-row badge, and a per-site "Damp outlier traffic" toggle in
the site settings dialog.

**Honesty Constraint copy (verbatim, for the Agent-Probe record).** No string asserts the
visitor's identity:
- detail badge: `Unusually high activity` / tooltip "…this visitor's traffic volume is a
  statistical outlier for this site. This is a visibility signal only; they stay fully
  contactable and fully counted unless you confirm below."
- list badge: `High activity` / "…statistical outlier for this site. Visibility signal only:
  still fully contactable and fully counted."
- default Activity row: "Unusually high activity for this site — a statistical outlier, not
  a confirmed identity."
- after the user acts (the user telling us, not us asserting): "You marked this visitor as
  your own team's traffic."
- settings toggle: "Reduce the influence of visitors with unusually high activity…"
A unit test (`test_user_facing_copy_never_asserts_the_visitors_identity`) now enforces this
across all three files, converting part of the Agent-Probe gate into an automated one.

## Amendment — suggestion-only conversion (27-07-26, post-EVL)

**What changed.** The automatic scorer is now SUGGESTION-ONLY. `is_internal_suspect`
became a label (badge + "review these" surface) and no longer causes anything on its
own. Only an explicit human confirmation (`internal_override == "internal"`) excludes a
visitor from the `daily_digest` aggregate or deprioritises them in `resolution_runner`.
New plan ACs 10-12 record this; ACs 4 and 5 were amended in place.

**Why — calibration measured live on production, read-only, 2026-07-27:**

| Threshold | Flagged | Of those, ALREADY identified with a real email |
|---|---|---|
| ≥20x median & ≥3 days | 34 | 5 |
| ≥50x median & ≥3 days | 21 | 3 |
| ≥100x median & ≥5 days | 15 | 2 |

There are only **28 identified visitors in the entire production system**. Enabling
automatic exclusion at the shipped 20x default would have silently hidden **5 of 28 =
18% of every customer's real leads**. Even the strictest threshold still catches 2 real
identified people.

No statistical threshold can separate "site owner who browses 30k times" from
"extremely engaged prospect" — both are high-volume, multi-day, fully engaged. And the
two error types are wildly asymmetric: hiding a real lead destroys the exact thing the
customer pays for, silently, with no error surfaced; failing to hide an owner merely
leaves a slightly noisy dashboard. So the safe design is not a better threshold — it is
to stop the machine deciding at all. The machine suggests; the human decides. Risk of
silently hiding a real lead on the automatic path is now **structurally zero**, while
the product value is unchanged (the customer still cleans up their dashboard in two
clicks).

**What was kept exactly as built:** the sweep, the pure scorer, reversibility, the
two-layer override guard, per-site default-OFF, flag-but-store, the 3-param
`is_emailable_identity` arity, and the untouched `visitor_aggregator.py`.

**Concrete edits.**
- `daily_digest.py::_site_day_stats` — filter changed from
  `Visitor.is_internal_suspect.is_(False)` to
  `Visitor.internal_override.is_distinct_from("internal")`. `is_distinct_from`, not
  `!=`, so NULL (never reviewed) stays IN the aggregate instead of dropping out on
  three-valued logic. `internal_override` is a VARCHAR(20) tri-state
  (`"internal"` / `"not_internal"` / NULL), not a boolean.
- `resolution_runner.py` — ordering changed from `Visitor.is_internal_suspect.asc()` to
  `Visitor.internal_override.is_distinct_from("internal").desc()` (True = not confirmed
  sorts first). Still deprioritise-never-exclude, still per-site gated via `getattr`.
- `config.py` — `outlier_traffic_damping_outlier_threshold` 20.0 → **50.0**,
  `outlier_traffic_damping_min_visit_days` 5 → **3** (the calibrated 50x/3d row: a
  21-visitor review list a customer can clear in a minute). The full calibration table
  and the suggestion-only rule are now inline comments in the config block, the sweep
  docstring, and both consumer docstrings, so the reasoning cannot be lost.
- Copy — badge now asks rather than asserts: detail badge "Unusually high activity — is
  this you?", list badge "High activity?", Activity row "…is this you? A statistical
  outlier, not a confirmed identity. This is a suggestion for you to review: until you
  confirm, this visitor is counted and prioritised exactly like any other.", settings
  toggle "Flagging alone changes nothing: only the ones you confirm are damped."
- **No schema change and no new migration** — this is purely behavioural. `f3a7c9e21b48`
  is untouched; both columns already existed.

**Tests updated, not deleted.** Every test asserting the old auto-exclusion behaviour
was rewritten to assert the new behaviour:
- unit `test_digest_exclusion_is_gated_and_does_not_couple_to_emailability` and
  `test_resolution_deprioritises_and_never_excludes` now assert on `internal_override`.
- **New** unit `test_auto_flagged_but_unconfirmed_visitor_is_still_fully_counted_in_the_digest`
  and `test_auto_flagged_but_unconfirmed_visitor_keeps_normal_resolution_order` — these
  assert `is_internal_suspect` is ABSENT from both consumer modules entirely, which is
  the structural form of the guarantee.
- **New** unit `test_default_threshold_is_the_calibrated_suggestion_list_size` pins
  50.0 / 3.
- Integration: the exclusion/deprioritisation/reversibility tests now seed
  `override="internal"`, and **two new tests** prove an auto-flagged-but-unconfirmed
  visitor is fully counted in the digest (5010 pageviews, 2 visitors) and keeps pure
  intent ordering. These remain Docker-gated (not executed) as before.

Unit test count rose 28 → 31 for this feature; full unit lane 1378 → 1381 passed.

## What Was Skipped or Deferred

- Live migration round-trip — Docker daemon down. Backlog note written.
- Hybrid integration lane — same cause. Tests written, not executed.
- Company-level totals (`companies.py`) — accepted out-of-scope known-gap per plan.
- Threshold calibration — **DONE 27-07-26**, see the Amendment section above. Defaults
  are now the measured 50x/3d values, and the automatic path can no longer exclude
  anyone regardless of threshold.

## Test Gate Outcomes

| Gate | Command | Result |
|---|---|---|
| AC2 pure scorer | `pytest tests/unit/test_outlier_traffic_damping.py -m unit -q` | **28 passed** → re-run after the suggestion-only amendment: **31 passed** |
| AC6/AC9 guardrail regression | `pytest tests/unit/test_agent_origin_exclusion.py tests/unit/test_outbound_identity_gate.py tests/unit/test_cadence_bot_flag.py -m unit -q` | **43 passed, unmodified** → re-run after the amendment (no `-m unit`): **61 passed, still unmodified** |
| Full unit lane | `pytest tests/unit -q` | **1378 passed, 2 skipped, 0 failed** → re-run after the amendment: **1381 passed, 2 skipped, 0 failed** |
| AC1 migration upgrade | `alembic upgrade b1e7f3c9d425:f3a7c9e21b48 --sql` | **PASS** (4 additive ALTERs) |
| AC1 migration downgrade | `alembic downgrade f3a7c9e21b48:b1e7f3c9d425 --sql` | **PASS** (4 DROPs, reverse order) |
| Frontend build | `cd apps/web && npm run build` | **✓ Compiled successfully** (re-run after the amendment: ✓ Compiled successfully) |
| AC4/AC5/AC3/AC7 Hybrid | `pytest tests/integration/test_outlier_traffic_damping.py -m integration -q` | **NOT RUN — Docker down (known-gap)** |
| AC8 Agent-Probe | manual copy check | **PASS by source review + now automated** |
| Live migration round-trip | — | **Known-Gap (D)** |

Regression validators: agent-parity PASS, skills PASS, context-discovery PASS,
plan-inventory PASS, `git diff --check` CLEAN. kit-portability FAIL — **pre-existing**,
caused by the untracked `.claude/skills/yc-application-coach/` (explicitly out of my
touch-scope; matches the documented known pre-existing red).

## Plan Deviations

Three, all within blast radius, none re-litigating a VALIDATE resolution:

1. **`resolution_runner.py` reads the toggle via `getattr(site, "internal_damping_enabled",
   False)` instead of plain attribute access.** Plan said plain branch. A pre-existing unit
   test passes a `SimpleNamespace` site stub, which lacks the new column. `getattr` with a
   `False` default is the fail-safe direction (damping never self-enables) and avoids
   editing a test to accommodate production code. Impact: none behaviourally.
2. **`SiteOut` gained a `mode="before"` validator coercing `None` → `False`** for
   `internal_damping_enabled`. An unflushed ORM `Site` has `None` for the new column, which
   failed Pydantic validation in 4 pre-existing `test_site_limit` unit tests. Coercing to
   `False` matches the default-OFF posture. Impact: none.
3. **`tests/unit/test_scheduler_job_config.py` E20 arithmetic updated 14/12 → 15/13.** The
   test's own docstring instructs re-deriving the count when a job is added and explicitly
   forbids relaxing the assertion; the assertion shape is unchanged.

Grep-sweep decision (checklist 11, left to EXECUTE judgment): the swept call sites
(`kpi.py`, `sites.py:385`, `visitors.py:112`/`:1039`, `visitors_helpers.py:196`,
`segmentation_trigger.py`, `dashboard.py::get_overview`) are all COUNT-of-rows metrics — a
heavy visitor contributes exactly 1 row, same as everyone else, so volume outliers do not
distort them. Only `daily_digest.py::_site_day_stats` sums a distortable per-visitor metric
(`total_pageviews`), which is the measured Query A harm. Excluding flagged visitors from the
list-pagination count (`visitors.py:112`) would actively violate flag-but-store by hiding
rows; excluding them from `eligible_for_resolution` would make the count lie, since the
design deprioritises rather than excludes. **Decision: `daily_digest.py` only.**

## Test Infra Gaps Found

Docker daemon unavailable in the EXECUTE environment — blocks both the live migration
round-trip and the entire Hybrid integration lane. Same environmental gate as every other
pending-migration feature in this repo.

## Closeout Packet

- **Selected plan:** `process/general-plans/active/outlier-traffic-damping_27-07-26/outlier-traffic-damping_PLAN_27-07-26.md`
- **Finished:** all 22 checklist items; 4 of 5 runnable gate groups green.
- **Verified:** pure scorer, reversibility, override-both-directions (unit + structural),
  guardrail regression, full unit lane, migration offline both directions, frontend build.
- **Unverified:** DB-facing behaviour (integration lane), live migration round-trip.
- **Remaining:** Docker-gated gates; threshold calibration; context-doc update at UPDATE PROCESS.
- **Classification:** `Keep in active/testing` — code-complete, but per the plan's own Phase
  Completion Rules the plan reaches `VERIFIED` only after EVL re-confirms, and the Hybrid
  tier is still unrun.

## Forward Preview

**Test Infra Found:** new `tests/unit/test_outlier_traffic_damping.py` (28 tests) and
`tests/integration/test_outlier_traffic_damping.py` (9 tests, unrun).
**Blast Radius Changes:** none beyond the plan; `visitor_aggregator.py` untouched as corrected.
**Commands to Stay Green:** `.venv/bin/python3.11 -m pytest tests/unit -q`;
`cd apps/web && npm run build`.
**Dependency Changes:** none. No new packages.

## Follow-up stubs created

- `process/general-plans/backlog/outlier-traffic-damping-deferred-gates_NOTE_27-07-26.md`

## CONTEXT_PARTIAL items

None.
