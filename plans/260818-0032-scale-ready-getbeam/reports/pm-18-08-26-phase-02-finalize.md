# PM Report — Phase 2 finalize (code complete; prod migrate + buildtolaunch remaining)

Date: 18-08-26
Plan: `plans/260818-0032-scale-ready-getbeam/`
Mode: ck:project-management finalize
Tasks: skipped (VSCode; plan-file sync-back only)
Verdict: **plan NOT complete**. Umbrella `in-progress`. Phase 2 code done; prod migration + `buildtolaunch` open. Phase 1 operator leftovers still open. Phase 3 pending.

## TL;DR

Phase 2 CODE + tests green (unit 32/32, integration 46/46 = 78/78). Review PASS_WITH_WARNINGS then DSN guard fail-closed (18 unit tests). Local alembic `c3f6a9d1e8b2` on `:5433` only. Prod **not** migrated: 682 NULL `event_id`, unique still global. **Cấm deploy API trước migrate.** Do **not** mark Phase 1 / Phase 2 / Phase 3 / umbrella completed. Finish remaining ACs.

## Plan status

| Artifact | Before | After |
|---|---|---|
| `plan.md` YAML | in-progress | **in-progress** (unchanged) |
| Phase 1 YAML | in-progress | **in-progress** (unchanged) |
| Phase 2 YAML | pending | **in-progress** (code complete; prod migration + buildtolaunch operator remaining) |
| Phase 3 YAML | pending | pending (unchanged) |

`plan.md` Phases table Phase 2: **In progress (code complete; prod migrate-then-deploy remaining)**

## Completion %

| Scope | Done / Total ACs | % | Status |
|---|---|---|---|
| Phase 1 | 6 / 8 | 75% | in-progress — code complete; operator F9/soak/flag remaining |
| Phase 2 | 6 / 8 | 75% | in-progress — code complete; prod migrate + buildtolaunch remaining |
| Phase 3 | 0 / 7 | 0% | pending |
| **Umbrella** | **12 / 23** | **52%** | **in-progress — NOT completed** |

## Phase 2 Success Criteria

| AC | State | Evidence |
|---|---|---|
| Ingest thiếu `event_id` → 400, 0 row | [x] | tests: missing/empty/partial-batch 400 |
| Retry same `(site_id, event_id)` → 204 | [x] | tests: idempotent, no double pageview |
| Same `event_id` other site both rows | [x] | tests: cross-site insert both |
| Prod `event_id IS NULL` = 0 after backfill | [ ] | **not done** — prod still 682 NULL; alembic `b7e3c9a4f215` |
| Unique `(site_id, event_id)` | [x] | code + local `:5433` (`uq_events_site_event_id`). **Prod still global `uq_events_event_id`** |
| Retention log `deleted=0` + `next_run_time` | [x] | code+AST; runtime fire **not** observed |
| APP_ENV nonprod + prod DSN abort | [x] | unit; fail-closed after review (unknown env abort) |
| Disk: no RPKI ingest; `buildtolaunch` paused | [ ] | RPKI this phase: **no ingest** (flag default False; scheduler gated; cook did not load `rpki_roas`). `buildtolaunch` still **ACTIVE_HEALTHY** |

## Quality gates (Phase 2 code)

| Gate | Result |
|---|---|
| Unit | 32/32 (`test_alembic_env_dsn_guard` 18 + `test_scheduler_job_config` 14) |
| Integration | 46/46 (ingest 26 + abuse 16 + watermark bootstrap 4) |
| Total | **78/78** |
| Code review | PASS_WITH_WARNINGS — then DSN guard tightened fail-closed |
| Local alembic | `c3f6a9d1e8b2` (head) on localhost:5433 only |
| Prod migrate | **not done** |
| Railway agg flag | still OFF (Phase 1 leftover; this cook did not flip) |

Non-blocking review notes (do not block code; **do block deploy**): migrate-then-deploy or ON CONFLICT 500s; no prod downgrade after F1 traffic; column still nullable; retention runtime fire unobserved.

Stale artifact: `reports/harness/phase-02/adversarial-validation.json` scenario "APP_ENV typo + remote DSN" still `ruled_out: false`. **Superseded** by fail-closed `assert_safe_alembic_dsn` + 18 unit tests. Residual closed.

## Phase 1 / Phase 3

Phase 1: still **in-progress**. 6/8. F9 prod bootstrap, soak canary, Railway flag **not** done. Do **not** mark complete.

Phase 3: **pending**. 0/7. Do **not** cook. Do **not** mark complete.

## Remaining operator checklist (Phase 2 — MUST finish)

Owner: operator / orchestrator. DoD = AC checkbox `[x]` only after live proof.

1. **Backup prod**, then apply `c3f6a9d1e8b2` with `APP_ENV=production`. Guard aborts `local|development|test|ci` + unknown env against remote DSN.
2. **Re-count** `event_id IS NULL` live — must be 0. Do not hardcode 682.
3. **Confirm** unique is `(site_id, event_id)` on prod (`uq_events_site_event_id`; global `uq_events_event_id` gone).
4. **Then deploy** ingest code. **Cấm** ship API before migrate (ON CONFLICT 500).
5. **Pause `buildtolaunch`** if unused, or write reason to keep. Still ACTIVE_HEALTHY.
6. **Do not** mark Phase 2 complete until ACs 2 remaining are `[x]`.
7. **Do not** cook Phase 3 until Phase 2 operator ACs done (or explicit user override).

## Remaining operator checklist (Phase 1 — still open)

1. F9 prod bootstrap until 0 NULL watermarks on sites with events.
2. Soak canary 1 site.
3. Railway `AGGREGATION_INCREMENTAL_ENABLED=true` only after 1+2. Default code still False.

## Scope / risk

| Item | Note |
|---|---|
| Scope change | user override cooked Phase 2 while Phase 1 soak still open — logged; flag not flipped |
| Closed risk | missing `event_id` 400; cross-tenant unique; DSN typo-bypass (fail-closed) |
| Open risk | deploy-before-migrate → ingest 500; prod 682 NULL until backfill; `buildtolaunch` disk; Phase 1 flag-ON with NULL watermark |
| Blocker | operator prod migrate + backup — **not** a code blocker; **is** a deploy blocker |

## Files changed (this PM pass)

- `plans/260818-0032-scale-ready-getbeam/plan.md` (Phases table Phase 2 only)
- `plans/260818-0032-scale-ready-getbeam/phase-02-disk-and-event-id-survival-on-free.md` (YAML + ACs)
- `plans/260818-0032-scale-ready-getbeam/reports/pm-18-08-26-phase-02-finalize.md` (this file)

Not edited: `phase-01-*.md`, `phase-03-*.md`, `apps/`, `tests/`. No commit.

## Docs

Phase 2 status pending → in-progress → `./docs` roadmap due. Not written this pass (PM finalize scoped to plan sync-back). Delegate docs-manager after operator leftovers or at UPDATE PROCESS.

## Next actions (orchestrator)

| # | Action | Owner | DoD |
|---|---|---|---|
| 1 | Backup + apply `c3f6a9d1e8b2` to prod (`APP_ENV=production`) | operator | alembic head = `c3f6a9d1e8b2`; NULL `event_id` = 0 |
| 2 | Deploy ingest API **after** migrate | operator | no ON CONFLICT 500 |
| 3 | Pause `buildtolaunch` or write keep-reason | operator | paused **or** documented |
| 4 | Tick remaining Phase 2 ACs + re-run PM | PM | Phase 2 8/8 |
| 5 | Close Phase 1 F9 + soak + flag | operator | Phase 1 8/8 |
| 6 | Cook Phase 3 only after Phase 2 operator ACs closed | execute | tenant ceilings / timeout / runbook |

**Main agent: finish the plan.** Phase 2 is 75% — leftover is operator migrate-then-deploy + `buildtolaunch`, not optional. Phase 1 still 75% operator. Umbrella 52%. Do not archive. Do not mark completed. Close prod migrate before any Phase 3 cook.

## Unresolved questions

1. Who applies `c3f6a9d1e8b2` to prod, and when (backup window)?
2. Confirm `buildtolaunch` unused before pause?
3. Cook Phase 3 while Phase 1 soak **and** Phase 2 prod migrate still open? (PM: no.)
4. When does the 24h zero-null-insert window for deferred NOT NULL start (after prod backfill)?
