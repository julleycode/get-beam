# EVL Iteration 001 — Phase 5 promotion-sweep (date-rollover test defect)

Date: 2026-08-05
Loop: EVL (fix cycle 1, surfaced during Phase 5 EVL; defect owned by program test file)
Driver: orchestrator

## Trigger

Phase 5 execute's full-lane gate: 1628 passed / 1 failed.
Failing: tests/unit/test_candidate_call_sites.py::TestTimeseries::test_query_counts_candidate_rows_separately
Root cause (per execute-agent diagnosis, to be confirmed by fix agent): the test hardcodes the
date string "2026-08-04" and iterates a series generated for "today" — on any later date the
next(...) lookup raises StopIteration inside a coroutine. Date-rollover flake, deterministic.

Ownership note: test_candidate_call_sites.py is a Phase 1 artifact of this program (execute-agent
attributed the failure to concurrent-session files timeseries.py/kpi.py — those are also Phase 1
touchpoints; regardless of who last edited, the hardcoded-date test is this program's defect).

## Fix cycle 1 scope

vc-execute-agent (supplement): make the test date-dynamic (derive from the same "today" the
series generator uses), assert same semantics (candidate rows counted separately). No source
changes expected. Then vc-tester cold re-run: the test file + full unfiltered unit lane
(target: 1629+/0) + Phase 5 contract gates.
