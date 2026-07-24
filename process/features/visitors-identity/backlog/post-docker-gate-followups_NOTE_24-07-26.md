---
name: plan:post-docker-gate-followups
description: "Backlog: 5 unrelated pre-existing integration failures surfaced by the full integration lane, plus a conftest Redis-isolation hardening recommendation — neither caused by owned-data-layer or first-party-capture"
date: 24-07-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
  phase: post-docker-gate-closure
---

# Post-Docker-Gate Followups — visitors-identity

**Why this note exists:** the 24-07-26 EVL final run that closed the Docker/browser gates on
`owned-data-layer` and `first-party-capture` (see
`owned-data-layer-docker-verification_NOTE_23-07-26.md` and
`first-party-capture-deferred-gates_NOTE_24-07-26.md`, both marked RESOLVED) also surfaced items
that are genuinely open but NOT caused by either plan. This note tracks those separately so they
don't get lost, and don't block archival of the two VERIFIED plans.

## 1. Five unrelated pre-existing integration failures

Surfaced by running the FULL `-m integration` lane (not scoped to `visitor_email`/`do_not_resolve`
as either plan's own gate commands specify) — these belong to other features
(`evallayer`/handoff-detection, intent-signals, ai-referral) and are cross-referenced here for
separate triage, not fixed in this session per the task's explicit "do NOT modify the 5 unrelated
failing tests" instruction.

| # | Test | Failure signature |
|---|---|---|
| 1 | `tests/integration/test_handoff_correlation_integration.py` (test A) | timezone-naive/aware `datetime` subtraction inside an asyncpg param-binding call — `TypeError: can't subtract offset-naive and offset-aware datetimes` (or equivalent asyncpg param coercion error) |
| 2 | `tests/integration/test_handoff_correlation_integration.py` (test B) | same root cause class as #1: a fixture/query path constructs one naive and one aware datetime and compares/subtracts them |
| 3 | `tests/integration/test_intent_signal_integration.py` (test A) | `sites.url` NOT NULL constraint violation — fixture creates a `Site` row without an explicit `url` value, DB schema requires NOT NULL |
| 4 | `tests/integration/test_intent_signal_integration.py` (test B) | same `sites.url` NOT NULL fixture gap as #3 |
| 5 | `tests/unit/test_visitor_aggregation.py::TestAiReferralAggregation::test_direct_then_perplexity_is_none` | assertion failure — expected `None` ai_source result for a direct-then-Perplexity-referral sequence, got a non-None value (ai-referral aggregation logic regression or stale fixture, not yet triaged) |

**Feature ownership for triage:**
- #1-2 → `evallayer` / Handoff Detection program (`process/features/evallayer/`)
- #3-4 → `evallayer` / Handoff Detection Phase H3 intent-signals (`process/features/evallayer/`)
- #5 → AI-referral attribution (`process/context/all-context.md` AI-Referral Attribution section) —
  no dedicated feature folder identified; may belong in `evallayer` or a new/general plan

**Action:** none taken this session (explicitly out of scope — do not modify). Flag for the owning
feature's next UPDATE PROCESS or a dedicated triage pass.

## 2. conftest Redis-isolation hardening (durable fix candidate)

**What:** `tests/conftest.py:19` sets a `REDIS_URL` default that assumes no local Redis is
reachable during the unit lane (tests rely on hitting the "Redis unreachable" branch). When an
ambient/unrelated container occupies port 6379 (as happened this session —
`itemintern-redis-1`), unit tests that depend on the Redis-down branch can self-poison shared
`db15`, producing flaky/wrong results that look like product bugs but are actually test-harness
fixture gaps.

**What was fixed this session (scoped, minimal):** `tests/unit/test_company_graph.py` — added an
explicit `get_redis` mock so this one file no longer depends on ambient Redis reachability
(commit `8c7ac6e`).

**What remains open (broader, durable fix):** the conftest-level assumption is still fragile for
any OTHER unit test that implicitly relies on "Redis unreachable." Two candidate fixes, not
decided/implemented this session:
1. Point the unit-lane `REDIS_URL` default at a definitely-unreachable address (e.g.
   `redis://127.0.0.1:1`) so "unreachable" is guaranteed regardless of ambient containers.
2. Add a centralized `no_redis` autouse fixture for the unit marker that mocks `get_redis`
   globally, so individual test files don't each need their own mock.

**Action:** deferred — flag for a decision (which of the two approaches, or another) at the next
`process/context/tests/all-tests.md`-scoped maintenance pass. Not blocking any current plan.

## Close status

Not scheduled. This note has no single close command — item 1 requires per-feature triage by the
owning feature's next session; item 2 requires a design decision before implementation. Re-visit
at the next `evallayer`/handoff-detection or `tests/all-tests.md` maintenance pass.
