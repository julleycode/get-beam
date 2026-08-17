---
phase: phase-2-icp-fit-scoring
date: 2026-08-17
status: COMPLETE_WITH_GAPS
feature: campaigns-outreach
plan: process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-2-icp-fit-scoring_PLAN_16-08-26.md
---

# Phase 2 — ICP-Fit Scoring — Execute Report

**TL;DR.** All checklist items C0→F implemented. Every Fully-Automated gate is green
(unit 2863 passed / 2 skipped — baseline 2832 + exactly my 31 new tests; vitest 174/174;
all grep gates; offline migration SQL clean both directions; single alembic head).
Every Hybrid gate is **BLOCKED-infra**: there is NO listener on :5433, so the integration
suite and the live migration round-trip could not run. The 10 integration tests are
written and collect cleanly but are UNEXECUTED.

Status: 🔨 CODE DONE. NOT `VERIFIED` — no flag-ON persistence gate has actually executed.

---

## Entry Gate

- `git status --short apps/api/services/site_analysis.py apps/api/models/site.py
  apps/api/migrations/versions/c5e1a9b73d20_add_site_profile.py` → only
  ` M apps/api/models/site.py`. `site_analysis.py` and migration `c5e1a9b73d20` are
  **committed and clean** (Phase 0 landed as `7081402`). The remaining `M` on
  `models/site.py` is Phase 1's `booking_url` work, not site-analysis. **Entry gate MET.**
- Listener check **run BEFORE the unit baseline**, per the plan's G-10 rule:
  `lsof -nP -iTCP -sTCP:LISTEN | grep -E ':5433|:6379'` → **NONE**.
  - **No Redis on 6379.** The plan and four PVL cycles recorded Redis as live in this
    worktree; it is not, so the unit-lane self-poisoning hazard did NOT apply to this
    baseline. The baseline is clean and comparable.
  - **No Postgres on 5433.** Docker daemon is down; not retried per the standing
    instruction. This is what blocks every Hybrid gate below.

---

## What Was Done

| Step | Change |
|---|---|
| A1–A3 | ICP contract read from source (`schemas/site_analysis.py:20-33`, `services/site_analysis.py:239` sanitizer) and transcribed verbatim into `icp_fit.py`'s module docstring. Sole `site_profile` writer confirmed: `routers/sites.py:621` (the PUT confirm). |
| C0 | `icp_fit_enabled: bool = False` declared in `apps/api/config.py:1446`, in its own `# ─── ICP-fit scoring ───` block beside `site_analysis_*`. Additive-only; distinct region from Phase 3's future `campaign_benchmark_enabled`. |
| C1 | `Visitor.icp_fit: Mapped[float | None] = mapped_column(Float, nullable=True)` on the **`Visitor`** class, directly under `intent_score`. |
| C2 | Live head re-derived with `DATABASE_URL` pinned → was `e4b1d78c3a05` (Phase 1). |
| C3 | New revision `f6a3c81d5e27_add_visitor_icp_fit.py`, `down_revision = "e4b1d78c3a05"`. Additive nullable, no backfill/default/index. |
| D1 | `_score_icp_fit_for_site(db, site_id)` added. 1 SELECT profile → 1 bulk SELECT enrichment (dict keyed by `visitor_id`) → 1 SELECT visitors (`id`, `visitor_id`, `country_code` only) → 1 executemany UPDATE. Called ONLY from the `since is None` branch, after that branch's `await db.commit()`, beside `revive_returning_unresolvable`. |
| D1.6 | Call wrapped in `try / await db.rollback() / logger.warning("icp_fit_pass_failed", ...)`, mirroring `_advance_watermark`'s never-fails-the-run posture. |
| D2 | Guarded on `settings.icp_fit_enabled` AND `site_profile is not None`; a `None` score skips the row entirely (never 0). |
| D3 | Staleness caveat documented at the call site AND next to the `DELIBERATELY ABSENT (D7)` block. |
| B1–B8 | `apps/api/services/icp_fit.py` — NEW, 300 lines, **stdlib imports only** (`re`, `dataclasses`). `normalize` / `score_role` / `score_firmographics` / `score_geography` / `estimate_icp_fit` / `icp_fit_verdict`, `_ISO_COUNTRY` (45 codes), `MIN_SCORED_DIMENSIONS = 2`, weights role .5 / firmo .3 / geo .2. `normalize` returns an ORDERED de-duplicated tuple, never a set. |
| E1 | ICP clause **appended to `head` AFTER the `parts[:3]` slice**, beside `intent {score}`. Signature unchanged (`build_conviction(d: dict)`), score read via `d.get("icp_fit")`, no kwarg. Early-return guard untouched. |
| E1b | ONE line in `routers/visitors.py`: `data["icp_fit"] = visitor.icp_fit`, immediately after the `VisitorOut.model_validate(...)` seed. Nothing else in that file touched; the list-path call at `:271` is untouched. |
| E2 | `icp_fit: float | None = None` on **`VisitorDetailOut`** only. |
| E3 | `icp_fit?: number \| null` added to `VisitorDetail` in `api-types.ts` (additive-only, on top of Phase 1's landed state). Band chip + `title=` tooltip rendered in `dashboard/visitors/[visitorId]/page.tsx` beside `<IntentRing>`, built from `apps/web/src/lib/icp-fit-copy.ts`. |
| E4 | No prompt injection point added — `grep -rn "site_profile" apps/api/agents/` returns nothing. `wrap_untrusted` not needed. |
| F1 | `tests/unit/test_icp_fit.py` — 18 tests incl. the AST purity walk. |
| F2 | `tests/unit/test_conviction.py` — NEW file, 13 tests: 8 characterization + 5 clause, incl. the mandatory H-6 case. |
| F3/F4/F5/F7 | `tests/integration/test_icp_fit_persistence.py` — 10 tests. **Written, collect-clean, NEVER EXECUTED.** |
| F6 | Adversarial-copy assertions in both unit files (conviction clause half). |
| F8 | `apps/web/src/lib/icp-fit-copy.ts` + `icp-fit-copy.test.ts` — 7 vitest tests (tooltip half). |

### Design notes worth carrying forward

- **`_overlap` is target-normalised, not symmetric** — the fraction of ICP tokens found in
  the provider string. A long provider job title is not penalised for tokens the ICP never
  mentioned. `"VP of Engineering"` vs `"Engineering leader"` → 0.5, satisfying AC-3.
- **The web copy builder takes a NUMBER, not the profile.** That is the structural reason
  AC-14's tooltip half holds: there is no channel for `site_profile` text to reach the
  browser at all, not merely a filter on one.

---

## Test Gate Outcomes

### Fully-Automated — ALL GREEN

| Gate | Result |
|---|---|
| `pytest tests/unit/test_icp_fit.py -q` | **18 passed** |
| `pytest tests/unit/test_conviction.py -q` | **13 passed** |
| `pytest tests/unit -q` (whole lane) | **2863 passed, 2 skipped** — baseline 2832+2, delta = exactly my 31 new tests. Zero regressions. |
| AST purity walk (inside test_icp_fit.py) | **passed** — no sqlalchemy/httpx/requests/redis/models/gemini import |
| `grep -rn "site_profile_candidate" icp_fit.py visitor_aggregator.py` | **no matches** (AC-2) |
| `grep -rn "site_profile" apps/api --include=*.py \| grep -iE "contains\|jsonb_\|->>"` | **no matches** (AC-11) |
| `grep -n "icp_fit_enabled" apps/api/config.py` | **`1446: icp_fit_enabled: bool = False`** (AC-6 precondition) |
| `cd apps/web && npx vitest run src/lib/icp-fit-copy.test.ts` | **7 passed** (AC-14 tooltip half) |
| `cd apps/web && npx vitest run` (whole suite) | **174 passed / 11 files** — zero regressions |
| `cd apps/web && npx tsc --noEmit` | **clean, 0 errors** |
| `alembic heads` (DATABASE_URL pinned) | **`f6a3c81d5e27 (head)`** — single head, no branching |
| `alembic upgrade e4b1d78c3a05:f6a3c81d5e27 --sql` | `ALTER TABLE visitors ADD COLUMN icp_fit FLOAT;` |
| `alembic downgrade f6a3c81d5e27:e4b1d78c3a05 --sql` | `ALTER TABLE visitors DROP COLUMN icp_fit;` |
| `validate-plan-artifact.mjs` | `"failures": []`, `"warnings": []` |
| No new `send_campaign_emails` caller | confirmed — only pre-existing `campaigns.py` call sites, untouched |

### Hybrid — ALL BLOCKED-infra

Evidence: `lsof -nP -iTCP -sTCP:LISTEN | grep -E ':5433|:6379'` → **no output**. Docker
daemon down; not retried per standing instruction. Native postgres :5432 was **NOT** used —
conftest's `drop_all` would have destroyed the dev DB.

| Gate | AC | State |
|---|---|---|
| `pytest tests/integration/test_icp_fit_persistence.py -q` | AC-6, AC-7, AC-8, AC-9, AC-15, AC-16 | **BLOCKED-infra** — 10 tests collect cleanly (`--collect-only` → `10 tests collected`), none executed |
| Live migration round-trip up/down/up on :5433 | AC-10 | **BLOCKED-infra** — offline `--sql` clean both directions is the only evidence |

**This is the single largest gap in this phase.** No flag-ON code path has ever run. The
flag-ON persistence case is precisely the anti-vacuity gate the plan added, and it is
unexecuted — so AC-6, AC-7, AC-8, AC-9, AC-15 and AC-16 are all **unproven**, not merely
untested. Do not read the green unit lane as evidence the feature works end to end.

### Agent-Probe — not run

| Gate | AC | State |
|---|---|---|
| Visitor detail page read-through: does the clause read truthfully? | AC-12 (copy quality) | **Named residual** — requires a running app + a scored visitor, which requires the DB |
| E3 visual placement: chip sits correctly beside `<IntentRing>`, conviction render un-regressed | E3 | **Named residual** — the STRING is gated by F8 vitest; the PLACEMENT is not. No Playwright leg in this phase, by plan. |

---

## Plan Deviations

Two, both within blast radius, both documented rather than silently applied:

1. **`_score_icp_fit_for_site` guarded by `if since is None:` at the CALL SITE.** D1 says
   "call it ONLY from the `since is None` branch", but the anchor symbol it names
   (`revive_returning_unresolvable`, `:533`) is on the **unconditional** path — it runs for
   both branches. Placing the call beside it verbatim would have run the pass on the
   incremental branch too, violating D5 and AC-7. Resolved by wrapping the call in
   `if since is None:` at that exact anchor point. `test_incremental_branch_never_writes_icp_fit`
   pins the intended behavior.

2. **One docstring reworded to keep the AC-2 grep gate honest.** My first draft of
   `_score_icp_fit_for_site`'s docstring contained the literal string
   `site_profile_candidate` in prose ("…is NEVER read"), which tripped the AC-2 grep gate
   even though nothing read the column. Reworded to "the unreviewed candidate column". The
   gate is a literal grep; a comment that defeats it is a false red.

No hard-stop-class deviation. No schema change beyond the one additive nullable column the
plan specifies. No auth, billing, send-path or secret surface touched.

---

## Test Infra Gaps Found

- **`lsof` shows NO listener on 5433 or 6379** — contradicting four consecutive PVL cycles
  that recorded both as live. Environment state in a plan goes stale fast; the plan's own
  G-10 rule (re-check before baselining) is what caught it. Worth keeping.
- **`before_cursor_execute` still has zero precedent in this repo.** F7's
  `event.listen(test_engine.sync_engine, ...)` is the first instance and is written but
  unexecuted, so the `.sync_engine` hop is **verified by reading `conftest.py:92` only, not
  by a passing test**. Treat it as unproven plumbing until the DB is up.
- **`_resolve_companies` needed an autouse no-op fixture** in the new integration file.
  Any future test that drives `aggregate_visitors_for_site` end to end needs the same, or
  it reaches the company-resolution path.

---

## Closeout Packet

- **Selected plan:** `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-2-icp-fit-scoring_PLAN_16-08-26.md`
- **Finished:** every checklist item C0→F; 31 new Python tests + 7 new vitest tests; 1 migration.
- **Verified:** all Fully-Automated gates, on real runs.
- **Unverified:** everything requiring Postgres — the entire flag-ON path (AC-6, AC-7, AC-8,
  AC-9, AC-10, AC-15, AC-16) plus both Agent-Probe residuals.
- **Remaining cleanup:** run the integration suite + live migration round-trip once Docker
  is back; then the AC-12 copy probe.
- **Classification: `Keep in active/testing`.** Code-complete, but a phase whose flag-ON
  path has never executed is exactly the flag-off-vacuity failure this plan was written to
  prevent. Not archivable.

### Follow-up stubs created

None as separate files — the two BLOCKED-infra gates and the two Agent-Probe residuals are
enumerated above and are the phase's own exit criteria, not new work.

### CONTEXT_PARTIAL

`CONTEXT_PARTIAL: integration-lane behavior` — the 10 integration tests are authored from
source reading (`conftest.py`, `visitor_aggregator.py`, `test_privacy_hold_clear.py` as the
fixture template) and have never run. Fixture-shape bugs of the class this repo has hit
before (`IdentifiedVisitor` has no `first_seen`; `Site` has no `domain`) would not have been
caught.

---

## Forward Preview

### Test Infra Found
`tests/conftest.py` gives `test_engine` / `test_db` / `test_client`; `test_client` overrides
`get_db` and disables slowapi. The signup-then-own-a-site pattern in
`tests/integration/test_privacy_hold_clear.py:32-118` is the cheapest route to an authed
request test. `Site.user_id` has no FK constraint, so DB-only tests can use a bare `uuid4()`.

### Blast Radius Changes
11 files + 1 migration, exactly as planned. Two files are now shared:
`apps/api/config.py` (Phase 3 will add `campaign_benchmark_enabled` — different region,
additive-only) and `apps/web/src/lib/api-types.ts` (Phase 1 owns it; my edit was additive).

### Commands to Stay Green
```
.venv/bin/python3.11 -m pytest tests/unit -q                 # expect 2863 passed, 2 skipped
cd apps/web && npx vitest run                                 # expect 174 passed
DATABASE_URL=postgresql+asyncpg://USER:PW@localhost:5433/DB \
  .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads   # expect f6a3c81d5e27
```
Never run bare alembic — repo `.env` points at Supabase PROD.

### Dependency Changes
None. No new package in `requirements.txt` or `package.json`. `icp_fit.py` is stdlib-only
by contract.
