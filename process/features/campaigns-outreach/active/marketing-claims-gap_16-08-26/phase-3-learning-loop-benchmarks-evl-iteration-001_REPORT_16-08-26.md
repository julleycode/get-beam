# EVL Iteration 001 — phase-3-learning-loop-benchmarks
date: 2026-08-16
cycle: 1 (EVL confirmation run, independent vc-tester)
verdict: PASS (runnable gates), WITH_GAPS
gates_green: targeted-unit 75 passed | full-unit 2926 passed / 2 skipped (baseline 2863, delta +63, zero regressions) | vitest 185 passed / 12 files (baseline 174/11) | tsc --noEmit clean | alembic single head a8c2f47e91b6 | no new send_campaign_emails caller | validate-plan-artifact 0/0 | contract grep/AST gates
gates_blocked_infra: AC-4/5/6/7 integration flag-ON+OFF pairing | AC-11 migration live round-trip — Docker down, PG :5433 and Redis :6379 both absent
non_vacuity: (a) benchmark table columns = id, category_normalized, period, sends, opens, clicks, conversions, site_count, created_at, updated_at — no site/visitor/email column, NO foreign keys (pinned by test); k-floor enforced in code at campaign_benchmark.py:235 (discards, does not write suppressed row), BENCHMARK_K_FLOOR=5 pinned; (b) co-op consent block untouched — contribution_enabled appears only as diff context, coop_terms_version + identity_contribution_consent_acceptances absent from diff; (c) /outcomes keeps grouped-aggregate shape, imports shared predicates, conv_rows untouched; (d) scheduler guards RE-DERIVED not relaxed — total stayed exact equality ==24 -> ==25, interval count ==21 unchanged (new job is cron), cron allow-list widened by exactly one entry, no wildcards
known_gaps: flag-ON positive case unproven (flag-OFF-only evidence vacuous per ip-org G8/G10 errata); AC-8b web-panel caveat has no render-level proof (apps/web lacks component-render capability); AC-8/AC-10 Agent-Probe not run; open-rate accuracy under Apple MPP unmodellable by any gate
follow_up: reply-tracking backlog note; subject-line-ranking backlog note; cross-phase blast-radius registry absent (Phase 1 and 3 both claim models/site.py, routers/sites.py, schemas/sites.py, agents/campaign_planner.py)
closeout_classification: WITH_GAPS
