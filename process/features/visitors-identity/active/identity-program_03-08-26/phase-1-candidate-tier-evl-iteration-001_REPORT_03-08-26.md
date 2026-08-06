# EVL Iteration 001 — Phase 1 candidate-tier (late-detected full-lane failures)

Date: 2026-08-03
Loop: EVL (fix cycle 1, Phase 1 scope)
Driver: orchestrator

## Trigger

During Phase 2/3 EVL, the UNFILTERED unit lane (1586+ tests) surfaced 3 failures that Phase 1's
own gate missed because it ran `-m unit` (833 marker-selected tests only):

1. `tests/unit/test_timeseries.py::test_known_day_populated`
2. `tests/unit/test_timeseries.py::test_missing_metric_keys_default_zero`
3. `tests/unit/test_svid_reconcile.py::test_matches_prior_identification_by_svid`

Suspected causes (per execute/tester observations, unconfirmed):
- timeseries ×2: stale assertions vs Phase 1's INTENTIONAL new `candidates` metric key
- svid_reconcile ×1: Phase 1's A1a laundering-path fix changed svid_reconcile semantics
  (intentional), OR stray local Redis on 6379 self-poisoning (known repo gotcha,
  memory: unit-tests-assume-no-local-redis)

## Fix cycle 1 scope

vc-execute-agent (supplement mode) scoped to EXACTLY these 3 tests: diagnose root cause per test;
if behavior change is intentional per Phase 1 plan → update the stale test assertions (never
weaken the laundering-path/candidate-tier fixes); if env poison → document + neutralize per
repo convention. Then vc-tester re-runs the 3 tests + full unfiltered unit lane cold.

Gate lesson recorded: phase gates must run the UNFILTERED unit lane, not `-m unit`, from Phase 4 on.
