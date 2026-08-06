---
name: report:job-change-detection-evl-iteration-001
description: EVL cycle 1 — independent vc-tester confirmation run found 1 real gate failure (scheduler job-count regression test not updated for new sweep job)
date: 2026-08-07
metadata:
  node_type: report
  type: evl-iteration
  domain: tests
  cycle: 1
  plan: job-change-detection_PLAN_07-08-26.md
---

# EVL Iteration 001 — job-change-detection

## Trigger

`PHASE_COMPLETE: EXECUTE` (DONE_WITH_CONCERNS) → mandatory independent EVL confirmation run by spawned vc-tester.

## Gate results (independent run)

**Green (9):**
- `tests/unit/test_job_change_detector.py` — 36 passed
- `tests/unit/test_job_change_config.py` — 5 passed
- Named regressions (`test_content_enrich` / `test_agent_origin_exclusion` / `test_identity_signals`) — 51 passed
- Migration offline upgrade `f1a7c3e05b92:c9f4a7b31e85` — clean
- Migration offline downgrade `a4f2b8c15d70:f1a7c3e05b92` — clean
- `alembic heads` — single head confirmed
- `job_change_detection_enabled` default `False` — confirmed
- No email column in `job_change_event.py` — confirmed
- No `print()` in new modules (structlog only) — confirmed

**Failed (1):**
- Full unit lane `tests/unit -m unit`: `tests/unit/test_scheduler_job_config.py::TestAC13IntervalJobHardening::test_the_asserted_set_is_derived_not_hardcoded` — expects 17 `add_job` calls, found 18. The new job-change sweep interval job was added by this plan; the hardcoded AST-count regression test was not updated. 1128 passed / 2 skipped otherwise. Real miss, not flaky.

**ENV-BLOCKED (1):**
- `tests/integration/test_job_change_detection.py` — 15 tests, connection refused 127.0.0.1:5433; Docker daemon absent in sandbox. Consistent with known repo state (execute session saw the same). Tests collect cleanly.

## Environment finding (not a defect)

True alembic head is now `c9f4a7b31e85`, not `a4f2b8c15d70` as the validate-contract records — two concurrent WS2 migrations (`b8e3f6a2c904` add events.agent_sig, `c9f4a7b31e85` add is_agent_operated flags) landed on top. Chain verified clean; job-change's own migration validates up/down correctly within it. Contract note needs updating (fix-cycle scope).

## Fix-cycle scope (execute-fix agent, supplement mode)

1. Update `tests/unit/test_scheduler_job_config.py::TestAC13IntervalJobHardening` counts: total 17→18 (+ interval split, likely 15→16) reflecting the new job-change sweep job. Keep the test's derived-not-hardcoded intent.
2. Update the plan's validate-contract head note: current head `c9f4a7b31e85` (concurrent WS2 migrations), job-change migration `a4f2b8c15d70` chains beneath.

## Status

Cycle 1 fix dispatched. Plateau: n/a (first cycle). Cap: 1/10.
