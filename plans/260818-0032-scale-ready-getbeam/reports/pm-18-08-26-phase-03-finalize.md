# PM Report — Phase 3 finalize (code completed; Railway flags OFF by design)

Date: 18-08-26
Plan: `plans/260818-0032-scale-ready-getbeam/`
Mode: ck:project-management finalize
Tasks: skipped (VSCode; plan-file sync-back only)
Verdict: **plan NOT complete**. Umbrella `in-progress`. Phase 3 **code ACs 7/7** → YAML `completed`. Phase 1 + Phase 2 still operator leftovers. Do **not** archive.

## TL;DR

Phase 3 CODE done. All 7 Success Criteria `[x]` and test-proven. Regression **153/153** (P1 46/46, P2 58/58, P3 49/49). Defaults still False/0. No Railway flags. No prod migrate. Railway ON is **not** an AC leftover (unlike P1 soak). Mark phase-03 `completed` for code. Umbrella + Phase 1 + Phase 2 stay in-progress. **Finish remaining operator ACs.**

## Plan status

| Artifact | Before | After |
|---|---|---|
| `plan.md` YAML | in-progress | **in-progress** (unchanged — operator leftovers) |
| Phase 1 YAML | in-progress | **in-progress** (unchanged) |
| Phase 2 YAML | in-progress | **in-progress** (unchanged) |
| Phase 3 YAML | complete (non-canonical) | **completed** (code ACs 7/7) |

`plan.md` Phases table Phase 3: **Completed (code; Railway flags still OFF by design)**

Phase 1 table: In progress (code complete; operator soak/flag remaining) — unchanged.
Phase 2 table: In progress (code complete; prod migrate-then-deploy remaining) — unchanged.

## Completion %

| Scope | Done / Total ACs | % | Status |
|---|---|---|---|
| Phase 1 | 6 / 8 | 75% | in-progress — code complete; operator F9/soak/flag remaining |
| Phase 2 | 6 / 8 | 75% | in-progress — code complete; prod migrate + buildtolaunch remaining |
| Phase 3 | 7 / 7 | 100% | **completed** (code; Railway flags OFF by design) |
| **Umbrella** | **19 / 23** | **83%** | **in-progress — NOT completed** |

Do **not** mark umbrella `completed`. 4 operator ACs still `[ ]` (P1: 2, P2: 2).

## Phase 3 Success Criteria

| AC | State | Evidence |
|---|---|---|
| Ceiling ON → 429, 0 INSERT | [x] | tests: 12 diverse-IP, limit=5; row count == 204s; `assert 429 in statuses` |
| Site limiter, not IP 100/min | [x] | tests: per-IP 100/min unchanged; site ceiling separate |
| CF spoof ignored unless peer in CF ranges | [x] | tests: 8.8.8.8 / 1.2.3.4 ignored; `172.64.0.1` trusted |
| `pg_sleep` over budget killed; sweep SET LOCAL | [x] | tests: 500ms kills `pg_sleep(2)`; SET LOCAL 0 survives; no pool leak after COMMIT |
| Pool comment 15 → 60 | [x] | `config.py` comments; pool 3/2 unchanged |
| Runbook in `docs/deployment-guide.md` | [x] | §Scale-ready x20–x30; trigger table verbatim |
| Defaults safe if Railway forgotten | [x] | `site_ingest_limit_enabled=False`; `db_statement_timeout_ms=0` |

Railway `SITE_INGEST_LIMIT_ENABLED` / `SITE_INGEST_LIMIT_PER_MINUTE=155` / `DB_STATEMENT_TIMEOUT_MS=30000` still **OFF**. By design. Not a checkbox leftover.

## Quality gates (Phase 3 code)

| Gate | Result |
|---|---|
| Phase 1 regression | **46/46** |
| Phase 2 regression | **58/58** |
| Phase 3 tests | **49/49** (IP + timeout + abuse) |
| Total | **153/153** |
| Code review | PASS_WITH_WARNINGS then residual patches |
| Railway P3 flags | **not set** |
| Prod migrate | **not done** (Phase 2 leftover) |
| Railway agg flag | still OFF (Phase 1 leftover) |

Execute: `DONE_WITH_CONCERNS`. Tester confirm-only after debounce `_FakeSession.execute` fixture: 0 fail.

## Residual patches (applied; not open ACs)

Post-review harden. Do **not** reopen Phase 3 ACs.

| Patch | Why |
|---|---|
| CF IPv6 `/29` + unwrap | review: bundled `2a06:98c0::/32` vs published `/29`; fail-closed unwrap |
| SET LOCAL 0 on ingest agg + F9 bootstrap + after aggregator commit | review: long jobs besides sweep/retention must not inherit 30s |
| `is_flagged_abuse` comment | velocity P4 still flag-but-store; do not confuse with hard 429 ceiling |

## Phase 1 / Phase 2 (do not mark complete)

Phase 1: still **in-progress**. 6/8. F9 prod bootstrap, soak canary, Railway `AGGREGATION_INCREMENTAL_ENABLED` **not** done. Default still False.

Phase 2: still **in-progress**. 6/8. Prod still 682 NULL `event_id`, alembic `b7e3c9a4f215`, global unique. Local `:5433` is `c3f6a9d1e8b2`. `buildtolaunch` still ACTIVE_HEALTHY. **Cấm deploy API before migrate.**

## Remaining operator checklist (MUST finish the plan)

Owner: operator / orchestrator. DoD = AC checkbox `[x]` only after live proof.

### Phase 1 (2 leftover)

1. F9 prod bootstrap until 0 NULL watermarks on sites with events.
2. Soak canary 1 site.
3. Then Railway `AGGREGATION_INCREMENTAL_ENABLED=true`. Default code still False.

### Phase 2 (2 leftover)

1. Backup prod, apply `c3f6a9d1e8b2` with `APP_ENV=production`.
2. Re-count `event_id IS NULL` live — must be 0. Confirm unique `(site_id, event_id)`.
3. **Then** deploy ingest API. **Cấm** ship before migrate (ON CONFLICT 500).
4. Pause `buildtolaunch` if unused, or write keep-reason.

### Phase 3 flags (operator after P1 soak — not ACs)

Do **not** set ceiling/timeout Railway until Phase 1 soak green. Code defaults already safe.

## Scope / risk

| Item | Note |
|---|---|
| Scope change | Phase 3 cooked while P1 soak + P2 prod migrate still open (user override vs P2 PM "no cook P3"). Logged. Flag not flipped. |
| Closed risk | hard 429 0 INSERT; CF spoof fail-closed; SET LOCAL no pool leak; defaults False/0 |
| Residual closed | IPv6 /29; SET LOCAL 0 on ingest/F9/post-commit; abuse-comment |
| Open risk | P2 deploy-before-migrate → 500; P1 flag-ON with NULL watermark; ceiling ON before soak; `buildtolaunch` disk |
| Blocker | operator P1 soak/flag + P2 migrate — **not** a Phase 3 code blocker; **is** a live-flag / deploy blocker |

## Files changed (this PM pass)

- `plans/260818-0032-scale-ready-getbeam/plan.md` (Phases table Phase 3 only)
- `plans/260818-0032-scale-ready-getbeam/phase-03-tenant-ceilings-timeout-and-x20-x30-runbook.md` (YAML `completed` + status note)
- `plans/260818-0032-scale-ready-getbeam/reports/pm-18-08-26-phase-03-finalize.md` (this file)

Not edited: `phase-01-*.md`, `phase-02-*.md`, `apps/`, `tests/`. Umbrella YAML stays `in-progress`. No commit.

## Docs

Phase 3 pending → completed → `./docs` roadmap due. Runbook already in `docs/deployment-guide.md` (execute). Do **not** rewrite that here. Delegate docs-manager for `project-roadmap.md` / `codebase-summary.md` after operator leftovers or at UPDATE PROCESS.

## Next actions (orchestrator)

| # | Action | Owner | DoD |
|---|---|---|---|
| 1 | Backup + apply `c3f6a9d1e8b2` to prod | operator | alembic head = `c3f6a9d1e8b2`; NULL `event_id` = 0 |
| 2 | Deploy ingest API **after** migrate | operator | no ON CONFLICT 500 |
| 3 | Pause `buildtolaunch` or write keep-reason | operator | paused **or** documented |
| 4 | F9 prod bootstrap + soak canary 1 site | operator | 0 NULL watermarks; canary green |
| 5 | Railway `AGGREGATION_INCREMENTAL_ENABLED=true` after 4 | operator | Phase 1 8/8 |
| 6 | Tick remaining P1/P2 ACs + re-run PM | PM | umbrella 23/23 only then |
| 7 | After soak: consider Railway ceiling + 30s timeout | operator | not before P1 soak; defaults stay False/0 until then |

**Main agent: finish the plan.** Phase 3 code is 100% — leftover is **not** optional operator work on Phase 1 (F9/soak/flag) and Phase 2 (prod migrate + `buildtolaunch`). Umbrella 83%. Do not archive. Do not mark umbrella / Phase 1 / Phase 2 completed. Close operator ACs before any live Railway ON.

## Unresolved questions

1. Who applies `c3f6a9d1e8b2` to prod, and when (backup window)?
2. Confirm `buildtolaunch` unused before pause?
3. Who runs F9 bootstrap + soak canary, and which site?
4. When (if ever) to set `SITE_INGEST_LIMIT_ENABLED` / `DB_STATEMENT_TIMEOUT_MS=30000` after soak?
