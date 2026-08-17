# EVL Iteration 002 — container-gate closure (all 3 phases)
date: 2026-08-17
trigger: Docker daemon came back up; infra-postgres-1 (:5433) + infra-redis-1 (:6379) started

## Round 1 — blocked gates finally run
integration lane: 642 passed / 7 failed
- phase1 test_booking_goal_preset.py 6/6 PASS
- phase2 test_icp_fit_persistence.py 4 FAILED / 6 passed -> SOURCE DEFECT
- phase3 test_campaign_benchmark_job.py 7/7 PASS; flag-ON and flag-OFF pairing both 7/7 (non-vacuous)
- migration live round-trip from EMPTY DB: e4b1d78c3a05, f6a3c81d5e27, a8c2f47e91b6 all up/down/up CLEAN, single head; DDL objects verified present
- unit 2926/2 and vitest 185/12 unchanged
triage of 7 failures: 4 = phase2 source defect; 1 = phase3 never-executed test (missing import); 2 = pre-existing ordering flakes (pass in isolation, not program-attributable)

## The defect (why flag-OFF evidence was vacuous)
apps/api/services/visitor_aggregator.py bulk write used update(Visitor) + WHERE + param list.
SQLAlchemy 2 raises InvalidRequestError; the contract-mandated try/except swallowed it into
logger.warning("icp_fit_pass_failed"), so icp_fit was NEVER written when icp_fit_enabled=true.
Silent no-op in production. Survived 4 PVL cycles + 2 EVL passes because every gate ran flag-OFF.
Exactly the ip-org G8/G10 vacuity precedent.

## Round 2 — fix cycle
fix: retarget the write to the Core table (update(Visitor.__table__), visitors_tbl.c.id).
synchronize_session=None alone was NECESSARY BUT INSUFFICIENT — it surfaced a second error
(ORM bulk-update-by-PK demanding PK-keyed dicts). Core table bypasses the ORM bulk path.
Also fixed: missing function-local CampaignTouchpoint import in test_outcomes_report.py
(matches that file's universal style; module-scope would risk the mapper-registry gotcha).
Docs: phase-1 contract errata (gate named a nonexistent tests/integration path; real file is
tests/unit/test_campaign_send_booking_link.py); backlog note credentials corrected to
retarget/retarget_dev/retarget_agent (pytest: retarget_agent_test).

## Round 3 — independent EVL confirmation
gates: icp_fit 10/10 | outcomes 8/8 (dead test now executes and passes on substance) |
unit 2926/2 zero drift | booking+benchmark 13/13
non-vacuity a-e ALL PASS:
 (a) AC-15 single-statement holds — one Core executemany, no loop; TestQueryBound uses a real
     before_cursor_execute listener on .sync_engine and asserts absolute == 4 (3 reads + 1 write),
     so a skipped write gives 3 and goes red
 (b) flag-ON test asserts the PERSISTED value is not None (not "no exception") — reverting the
     write to the broken form turns it red
 (c) containment unchanged byte-for-byte (if since is None: guard + try/except + rollback + warning)
 (d) intent_score untouched (diff is one comment + one statement hunk)
 (e) function-local import correct — file has ZERO module-scope ORM imports and 4 function-local ones

## Verdict
phase_1: VERIFIED
phase_2: VERIFIED
phase_3: VERIFIED (automated gate set)
residual: prod flags icp_fit_enabled / campaign_benchmark_enabled remain OFF (operator step);
schema-applied != feature-enabled.
