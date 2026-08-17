---
phase: phase-3-learning-loop-benchmarks
date: 2026-08-17
status: COMPLETE_WITH_GAPS
feature: campaigns-outreach
plan: process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-3-learning-loop-benchmarks_PLAN_16-08-26.md
---

# Phase 3 — Learning Loop + Benchmarks — EXECUTE report

**TL;DR:** All 34 checklist items implemented. Unit lane **2926 passed / 2 skipped** (baseline
2863/2 — +63 new tests, 0 failures). Web `vitest` **185 passed** (baseline 174) and `tsc --noEmit`
clean. Migration `a8c2f47e91b6` chains off the live head `f6a3c81d5e27` and is offline-validated
both directions; single head confirmed. **Two gate classes are BLOCKED-infra: the integration lane
and the live migration round-trip — Postgres :5433 is DOWN in this session.** `campaign_benchmark_enabled`
ships default OFF, so runtime behavior is unchanged until an operator flips it.

## What Was Done

### Step A — Category normalization
- **A1 (sampling, recorded as required).** Confirmed against source: **onboarding source (a) does
  not exist** — there is no category option list anywhere in `apps/web/src`; `api-types.ts:122`
  types it as free `string`, and `site-settings-dialog.tsx` has no category control. Source (b),
  the site-analysis path, is unbounded model free text: `site_analysis.py:171` prompts for
  `"category": "<= 100 chars"`, `:288` stores whatever comes back, and `:325` shows a fallback
  example value of `"Software"`. The local dev DB is a 0-row database, so no live value sample was
  possible. The authored vocabulary is therefore AUTHORED, not enumerated — exactly as A1 predicted.
  Design safety is unaffected: `"other"` catches everything unmapped and nothing is dropped.
- **A2/A3/A4.** `apps/api/services/campaign_benchmark.py` defines a 12-bucket vocabulary
  (`BENCHMARK_CATEGORIES`) and `normalize_category(raw) -> str` — pure, deterministic,
  case/whitespace-insensitive, no LLM, `"other"` for unknown/None. Module docstring notes it is
  intended to be reusable by `agents/segmenter.py` later; **not wired there** in this phase.

### Step B — Per-site stats rollup
- **B1/B2/B5.** NEW `apps/api/services/campaign_stats.py` exports the LOCKED dual shape:
  (a) `sent_count_expr` / `opened_count_expr` / `clicked_count_expr` — the shared SQL predicate set;
  (b) a PURE `summarize(rows, *, channel=None, conversions=0) -> CampaignStats`.
  `routers/outcomes.py` now imports the three expressions INTO its existing grouped aggregate. Its
  `group_by(Campaign.id, Campaign.name)` is preserved, no rows are materialized, and `conv_rows`
  (the `Conversion` merge) is untouched — verified by automated assertion.
- The `sent`-vs-`opened`/`clicked` asymmetry is reproduced exactly (`sent` carries
  `status == "sent"`; all three carry `sent_at >= cutoff`), AST-asserted.
- **B3/B3b.** `CampaignStats.has_data` is False and `open_rate` is `None` with zero sends;
  N sends / 0 opens yields a measured `0.0`. `OPEN_RATE_CAVEAT` is a single constant consumed by
  every surface. Nothing is gated on `identity_signals_enabled`.
- **B4b.** The benchmark rollup passes `channel="email"`; `/outcomes` stays unfiltered. The send
  path was **not modified** — `campaign_sender.py` is byte-unchanged.
- **B4.** Conversions are counted from the `Conversion` table for the window, which includes the
  Phase 1 "Demo booked" goal automatically (no goal-type special-casing needed).

### Step C — Benchmark table + job
- **C0/C0b.** `Site.benchmark_contribution_enabled` (nullable, default False, server_default
  "false"). `schemas/sites.py`: field DECLARED on `SiteOut` **first**, then added to the
  `mode="before"` validator (the M3 import-failure hazard), plus `SiteUpdate`. `routers/sites.py`
  applies it in a structurally separate, unconditional branch and emits the
  `benchmark_contribution_toggled` structlog audit line (site_id, user_id, enabled — no PII).
- **C1/C2/C3.** `models/campaign_benchmark.py` with exactly the D1 columns, unique on
  `(category_normalized, period)`. Migration `a8c2f47e91b6` re-derived LIVE and chained off
  `f6a3c81d5e27`. Offline `--sql` validated up and down; `alembic heads` → single head
  `a8c2f47e91b6`. **Live round-trip BLOCKED-infra** (see gaps).
- **C4/C5/C6.** `aggregate_weekly_benchmarks()` reads ONLY
  `Site.benchmark_contribution_enabled.is_(True)`; sub-k-floor categories are discarded outright
  (the log line carries the category and period, never a site); non-opted-in sites are never
  fetched, so no per-site trace exists.
- **C7.** `_campaign_benchmark_job` registered in `start_scheduler()` behind
  `campaign_benchmark_enabled`, wrapped in try/except with a `campaign_benchmark_crashed` structlog
  line, `CronTrigger(day_of_week="sun", hour=3)` — deliberately clear of the Monday 15:00 digest.

### Step D — Surfaces
- **D1.** `DigestStats` is **unchanged**. `build_digest_email` gained a keyword-only
  `benchmark: DigestBenchmark | None = None`; the positional signature and `tuple[str, str]` return
  are untouched and all 6 existing positional call sites still pass. The rendered line says
  "category average", carries the MPP caveat, and renders "no sends this week" (never 0%) for a
  site with no sends.
- **D2/D6.** `/outcomes/{site_id}/report` gained additive `whats_working`, `open_rate_caveat`, and
  optional `benchmark`. Ranked by **campaign and segment only** — no subject text is read anywhere.
  The web panel renders the caveat on the open-rate column header AND as body copy.
- **D3.** `_measured_stats_note()` injects last-30-day measured stats into
  `CAMPAIGN_PLANNING_PROMPT`, flag-gated, returning `""` when the site has sent nothing.
- **D4.** No injection into `apps/api/services/auto_drafter.py` — it is byte-unchanged and
  unimported by every new module (asserted, with the path assertion that makes the gate non-vacuous).
- **D5.** No tenant-derived free text enters any prompt in this phase (the subject path is deferred),
  so no new `clean_text` call site was needed.

### Step E — Safety + backlog
- **E1/E2/E14.** Automated assertions: no new module references `send_campaign_emails`;
  `campaign_planner.py` references neither it nor `campaign_sender`; the benchmark table has no
  tenant-identifying column and no foreign keys; no benchmark surface computes a period-over-period
  delta (grep + AST over subtraction nodes); the word "median" appears in no executable code.
- **E2b (privacy note, recorded here as required).** Published aggregates are **irreversible under
  GDPR erasure** — a conversion already summed cannot be un-counted. This is acceptable by design
  because the rows are k-anonymous and PII-free, so `graph_erasure.py` has nothing to sweep.
  **Period-differencing risk:** near the k-floor, comparing consecutive periods can narrow one
  tenant's numbers. Both mitigations are live: (1) rows below `site_count >= 5` are discarded;
  (2) **no period-over-period delta is published anywhere**, gated by the AC-14 automated
  assertion — so mitigation (2) is enforced, not merely asserted in prose. `site_count` is exposed
  on no tenant-visible surface.
- **E3/E4.** Both backlog notes written.
- **E5 (recorded here as required).** Marketing copy implying auto-send or auto-adjustment —
  "coordinated automatically", "learn and adjust automatically" — **must be REWORDED**. This phase
  deliberately did NOT implement auto-adjustment (D6/umbrella P4): the learning loop writes PROMPTS
  and REPORTS only, drafts still require human approval, and nothing about a live campaign is
  auto-adjusted. The copy fix is umbrella checklist P4, not this phase.

## What Was Skipped or Deferred

- **Subject-line ranking** — named deferral (D2), decided in the plan, not during EXECUTE. Both
  extraction paths are recorded in the plan for the follow-up phase. Panel copy says
  campaign/segment and never "subject" (asserted in the vitest lane).
- **Reply tracking** — out of scope (D8); backlog note written.
- **`normalize_category` reuse in `agents/segmenter.py`** — noted in the docstring, not wired (A4).

## Test Gate Outcomes

| Gate | Strategy | Result |
|---|---|---|
| `pytest tests/unit/test_normalize_category.py -q` | Fully-Automated | **PASS** (AC-1) |
| `pytest tests/unit/test_campaign_stats.py -q` | Fully-Automated | **PASS** (AC-2, AC-13 rollup half) |
| `pytest tests/unit/test_campaign_benchmark.py -q` | Fully-Automated | **PASS** (AC-3, AC-9, AC-10, AC-13, AC-14) |
| `pytest tests/unit/test_outcome_digest_benchmark.py` + pre-existing `test_outcome_digest.py` | Fully-Automated | **PASS** (AC-8) — existing digest tests pass unchanged |
| `pytest tests/unit -q` (full lane) | Fully-Automated | **PASS** — 2926 passed / 2 skipped (baseline 2863/2) |
| `cd apps/web && npx vitest run` | Fully-Automated | **PASS** (AC-8b copy) — 185 passed / 12 files (baseline 174/11) |
| `cd apps/web && npx tsc --noEmit` | Fully-Automated | **PASS** — clean |
| `alembic upgrade f6a3c81d5e27:a8c2f47e91b6 --sql` + downgrade + `heads` | Hybrid (partial) | **OFFLINE PASS**; single head `a8c2f47e91b6`. Live round-trip **BLOCKED-infra** (AC-11) |
| `CAMPAIGN_BENCHMARK_ENABLED=true pytest tests/integration/test_campaign_benchmark_job.py` | Hybrid | **BLOCKED-infra** (AC-4, AC-5, AC-6, AC-7 pairing) |
| `ls` both backlog notes | Fully-Automated | **PASS** (AC-12) |
| `validate-plan-artifact.mjs` on the plan | Fully-Automated | **PASS** — `failures: []`, `warnings: []` |
| Digest/draft claim truthfulness | Agent-Probe | **NOT RUN** — named residual |
| Visual placement of the web caveat | Agent-Probe | **NOT RUN** — named residual (per AC-8b's locked proof shape) |

**BLOCKED-infra evidence (lsof, this session):**

```
postgres 699 apple 7u IPv6 ... TCP [::1]:5432 (LISTEN)
postgres 699 apple 8u IPv4 ... TCP 127.0.0.1:5432 (LISTEN)
```

Port **5433 is not listening** and Redis **6379 is not listening** (the plan's PVL cycles recorded
both live; that is stale). Docker was NOT retried per instruction. The integration lane was **not**
pointed at :5432 — the integration conftest calls `drop_all`/`create_all` and would destroy the dev
database. That is a hard FORBIDDEN, not a preference, so the lane stays unrun.

## Plan Deviations

| # | Deviation | Class | Rationale |
|---|---|---|---|
| 1 | Updated two assertions in the pre-existing `tests/unit/test_scheduler_job_config.py` (cron-id set gains `campaign_benchmark`; add_job count 24 → 25). | Within-blast-radius | These are inventory guards whose own docstring says to **re-derive the arithmetic when a job is added — never to relax the assertion**. The arithmetic was re-derived and the docstring history extended; no assertion was weakened or removed. Required by C7. |
| 2 | Added the `/outcomes` social-touchpoint regression (B5b) as a NEW test class in the existing `tests/integration/test_outcomes_report.py` rather than seeding the social row into the shared `report_setup` fixture. | Within-blast-radius | Seeding the shared fixture would have changed the existing suite's expected values (4,2,1 → 5,3,2), contradicting B5's "existing `/outcomes` values must be unchanged". The new leg asserts before/after around an ORM-constructed social row, which is strictly stronger: it proves each counter moves by exactly one, so a leaked channel filter is caught. |
| 3 | `summarize` gained a `conversions: int = 0` keyword parameter beyond the plan's stated signature. | Within-blast-radius | `CampaignStats` must carry conversions (B1), and conversions come from a different table than touchpoint rows. Purity is preserved; `channel` behaves exactly as specified. |
| 4 | Added `open_rate_caveat` to `OutcomesReportResponse` alongside the planned `whats_working` / `benchmark`. | Within-blast-radius | B3b requires every open-rate surface to render the caveat. `whats_working` carries open rates, so the caveat must travel with the response rather than be duplicated as a hardcoded frontend string. Additive and optional. |

No hard-stop deviations. The send path, the identity co-op consent path, `Site.contribution_enabled`,
`coop_terms_version`, and `identity_contribution_consent_acceptances` were **not touched**. No
`git stash`/`checkout --`/`revert`/`rebase` was run; the concurrent program's uncommitted work is intact.

## Test Infra Gaps Found

- **Postgres :5433 and Redis :6379 are both down this session** — the integration lane and the live
  migration round-trip cannot run. Classification: `harness-drift` (environment), not
  `product-breakage`. Everything provable without a database was proved.
- The multi-site k-floor fixture (≥5 opted-in sites in one category, <5 in another) was **built**
  in `tests/integration/test_campaign_benchmark_job.py` as real test-infra work — it is unrun, not
  unwritten.
- `apps/web` still has no component-render capability (`@testing-library/react` / jsdom /
  happy-dom all absent) and Playwright remains blocked by the Clerk auth-harness gap. Per AC-8b's
  locked resolution, no test stack was installed; the caveat copy is proven in the pure vitest lane
  and visual placement stays a named Agent-Probe residual.

## Known Gaps (carried forward)

1. **AC-11 live migration round-trip** — offline-validated only. Must run `upgrade head` →
   `downgrade -1` → `upgrade head` against a real PG on :5433 before any deploy.
2. **AC-4 / AC-5 / AC-6 / AC-7** — proven by written-but-unrun integration tests. AC-7's flag-OFF
   leg is meaningless alone; it must be run PAIRED with the flag-ON legs (ip-org G8/G10 errata).
3. **AC-8b visual placement** and **AC-8/AC-10 claim truthfulness** — Agent-Probe residuals.
4. **Live-data proof of the k-floor's positive case** — no environment has ≥5 opted-in sites in one
   category; the k-floor was NOT lowered to make a test pass.
5. **Open-rate accuracy is unmodellable** — Apple MPP and image blocking are not simulated by any
   gate. Every surface caveats the number; no test makes it accurate.
6. **The structlog consent audit is not transactional** — unlike the co-op's acceptance row, a log
   line can be lost or rotated. This is the accepted, locked D3 tradeoff.
7. No web opt-in UI for `benchmark_contribution_enabled` — the only path is `PATCH /sites/{id}`.

## Closeout Packet

- **Selected plan:** `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-3-learning-loop-benchmarks_PLAN_16-08-26.md`
- **Finished:** all 34 checklist items; 5 new test files; 1 migration; 2 backlog notes.
- **Verified:** every Fully-Automated gate, plus the offline migration validation and head check.
- **Unverified:** the integration lane, the live migration round-trip, and both Agent-Probes.
- **Classification:** `Keep in active/testing` — code-complete (🔨 CODE DONE), NOT ✅ VERIFIED.
  Per the plan's own Phase Completion Rules, VERIFIED requires the flag-ON Hybrid gates plus user
  confirmation of claim truthfulness.
- **Next:** EVL confirmation run by an independent vc-tester.

## Forward Preview

**Test Infra Found.** The multi-site k-floor fixture now exists and is reusable. The `_code_only()`
helper in `tests/unit/test_campaign_benchmark.py` (strips docstrings/comments before grepping) is
worth reusing for any future structural gate — a naive source grep matches the very prose that
explains the rule and produces false failures.

**Blast Radius Changes.** `apps/api/services/campaign_stats.py` is now the single funnel predicate
set: any future change to what "sent"/"opened"/"clicked" mean must happen there, and it moves both
`/outcomes` and the benchmark at once. `apps/api/schemas/sites.py` gained a third field in the
`mode="before"` validator — the declare-then-validate order is load-bearing (validator-only is a
class-definition-time crash, not a soft bug).

**Commands to Stay Green.**
```
.venv/bin/python3.11 -m pytest tests/unit -q                 # expect 2926 passed / 2 skipped
cd apps/web && npx vitest run                                # expect 185 passed / 12 files
cd apps/web && npx tsc --noEmit                              # expect clean
DATABASE_URL=postgresql+asyncpg://...@localhost:5433/... .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads   # expect a8c2f47e91b6
```

**Dependency Changes.** None. No package was added to `requirements.txt` or `apps/web/package.json`
— AC-8b was deliberately satisfied without a new test dependency.

**Operator steps before any enable.** (1) run the live migration round-trip on :5433; (2) run the
integration lane flag-ON and flag-OFF as a pair; (3) deploy (Railway auto-applies the migration);
(4) only then consider `CAMPAIGN_BENCHMARK_ENABLED=true`, and only once ≥5 real sites in one
category have opted in — otherwise the job correctly writes nothing.
