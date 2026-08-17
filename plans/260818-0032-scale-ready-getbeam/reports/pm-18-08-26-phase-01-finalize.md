# PM Report — Phase 1 finalize (code complete; soak/flag remaining)

Date: 18-08-26
Plan: `plans/260818-0032-scale-ready-getbeam/`
Mode: ck:project-management finalize
Tasks: skipped (VSCode; plan-file sync-back only)
Verdict: **plan NOT complete**. Umbrella `in-progress`. Phase 1 code done; operator leftovers open. Phase 2–3 untouched.

## TL;DR

Phase 1 CODE + tests green (unit 31/31, integration 27/27 after UA fixture). Review PASS_WITH_WARNINGS, no prod blockers. Do **not** flip Railway flag. F9 prod bootstrap, soak canary, then `AGGREGATION_INCREMENTAL_ENABLED=true`. Phase 2–3 still pending. Finish remaining ACs before cook Phase 2.

## Plan status

| Artifact | Before | After |
|---|---|---|
| `plan.md` YAML | pending | **in-progress** |
| Phase 1 YAML | pending | **in-progress** |
| Phase 2 YAML | pending | pending (unchanged) |
| Phase 3 YAML | pending | pending (unchanged) |

## Completion %

| Scope | Done / Total ACs | % | Status |
|---|---|---|---|
| Phase 1 | 6 / 8 | 75% | in-progress — code complete; operator soak/flag remaining |
| Phase 2 | 0 / 8 | 0% | pending |
| Phase 3 | 0 / 7 | 0% | pending |
| **Umbrella** | **6 / 23** | **26%** | **in-progress — NOT completed** |

## Phase 1 Success Criteria

| AC | State | Evidence |
|---|---|---|
| Flag OFF parity (tests pass) | [x] | unit 31/31; integration 27/27 |
| Sweep không stamp (integration proven) | [x] | F6 integration |
| Redis degraded + flag ON skip (unit proven) | [x] | F7 unit |
| Mutex > 60s synthetic (integration proven) | [x] | F8 integration |
| Future event.ts không ADD lặp (integration proven after UA fix) | [x] | F2 HTTP after User-Agent fixture |
| Default config.py False | [x] | `aggregation_incremental_enabled` still False |
| Flag ON + NULL watermark F9 stamp hết site **trước flip** | [ ] | code exists (`run_aggregation_watermark_bootstrap`); **not run on prod** |
| Prod soak canary | [ ] | **not run** |

## Quality gates (Phase 1 code)

| Gate | Result |
|---|---|
| Unit | 31/31 |
| Integration | 27/27 (after User-Agent fixture fix) |
| Code review | PASS_WITH_WARNINGS — no production blockers (`approved-with-concerns`) |
| Railway flag | still OFF (default False) |
| Prod F9 / soak | **not done** |

Non-blocking review notes (do not block code; do block flag flip): F9 not in `start_scheduler` (intentional); hot sites can skip without yield marker; utcnow vs PG `now()` skew.

## Phase 2 / Phase 3

Untouched. All ACs remain `[ ]`. Do not start until Phase 1 operator leftovers close (F9 zero-NULL → soak canary → flag ON).

## Remaining operator checklist (Phase 1 — MUST finish)

Owner: operator / orchestrator. DoD = AC checkbox `[x]` only after live proof.

1. **F9 prod bootstrap** — run `run_aggregation_watermark_bootstrap` until **zero** `last_aggregated_at IS NULL` on sites **with events**. Re-run until clean. **Cấm flip flag nếu còn NULL.**
2. **Prod soak canary** — 1 site; no double-count pageviews vs full SET.
3. **Railway flag** — set `AGGREGATION_INCREMENTAL_ENABLED=true` **only after** (1)+(2) green. Rollback = flag false.
4. **Do not** mark Phase 1 complete until ACs 2 remaining are `[x]`.
5. **Do not** cook Phase 2 until Phase 1 operator ACs done (or explicit user override).

## Scope / risk

| Item | Note |
|---|---|
| Scope change | none this session — Phase 1 operator leftover was always in plan |
| Closed risk | flag-OFF parity; sweep stamp leak (test); mutex >60s (test) |
| Open risk | flag ON with leftover NULL watermark → full-scan forever; soak unproven |
| Blocker | operator prod access / Railway env — **not** a code blocker |

## Files changed (this PM pass)

- `plans/260818-0032-scale-ready-getbeam/plan.md`
- `plans/260818-0032-scale-ready-getbeam/phase-01-incremental-aggregation-soak-and-prod-flag.md`
- `plans/260818-0032-scale-ready-getbeam/reports/pm-18-08-26-phase-01-finalize.md` (this file)

Not edited: `phase-02-*.md`, `phase-03-*.md`, `apps/`, `tests/`. No commit.

## Docs

Phase status changed → `./docs` roadmap due. Not written this pass (PM finalize scoped to plan sync-back). Delegate docs-manager after operator leftovers or at UPDATE PROCESS.

## Next actions (orchestrator)

| # | Action | Owner | DoD |
|---|---|---|---|
| 1 | Run F9 on prod; repeat until 0 NULL watermarks on sites with events | operator | SQL count = 0 |
| 2 | Soak canary 1 site | operator | no double-count pageviews |
| 3 | Railway `AGGREGATION_INCREMENTAL_ENABLED=true` | operator | after 1+2; default code still False |
| 4 | Tick remaining Phase 1 ACs + re-run PM | PM | Phase 1 8/8 then decide Phase 2 cook |
| 5 | Cook Phase 2 only after Phase 1 closed | execute | disk + event_id ACs |

**Main agent: finish the plan.** Phase 1 is 75% — leftover is operator, not optional. Umbrella 26%. Do not archive. Do not mark completed. Close F9 + soak + flag, then Phase 2.

## Unresolved questions

1. Who runs F9 on prod, and when (staging first)?
2. Which site is the soak canary?
3. User override: start Phase 2 code while soak still open? (plan says no flip until F9 green; Phase 2 code does not require flag ON — confirm before cook.)
