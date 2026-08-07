---
name: plan:post-docker-gate-followups
description: "Backlog: full-integration-lane failure inventory (REBASED 07-08-26 to the measured set: 478 passed / 23 failed / 17 errors — the old 5-failure set did NOT reproduce), plus a conftest Redis-isolation hardening recommendation (hazard now confirmed twice)"
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

## 1. Full-integration-lane failure inventory — REBASED 07-08-26

**The originally recorded 5-failure set (24-07-26) is STALE and did NOT reproduce in the
07-08-26 Docker gate run** — `test_handoff_correlation_integration.py` and
`test_intent_signal_integration.py` both PASSED. The measured 07-08-26 result of the full
lane is: **478 passed / 23 failed / 17 errors.** Breakdown:

| Group | Count | Signature / cause |
|---|---|---|
| **P0 — `GET /visitors` pre-existing 500** (in prod: present on `main` AND `devjulley`) | 10 F | `routers/visitors.py:227` assigns `confidence_score` to `VisitorOut`; field only exists on `VisitorDetailOut` (`schemas/visitors.py:91`) → pydantic ValueError → 500. Failures: `test_visitor_filters` ×7, `test_visitor_list_email` ×2, `test_candidate_endpoints` ×1 |
| graph-erasure fixture bugs (files never executed before) | 5 F + 2 E | `test_graph_erasure_flow.py`: `IdentifiedVisitor` has no `first_seen`/`last_seen` (live on `Visitor`, `models/visitor.py:24-25`); `Site` has no `domain` col, requires `name`+`url` NOT NULL |
| job-change fixture bug | 15 E | `test_job_change_detection.py`: `Visitor` inserted without NOT NULL `first_seen`/`last_seen` |
| identity-vocab-reconcile vocab drift | 1 F | `test_visitor_stats.py:309` expects `could_enrich`; code returns `candidates` (rename shipped by identity-vocab-reconcile — TEST needs update, not code) |
| Untriaged | 7 F | `promotion_sweep` ×4, `optout_flow` ×1, `ai_resolution_priority` ×1, `campaign_mid_send_promotion_cutover` ×1 — mix of `first_seen` fixture-class and behavioral asserts |

Full detail + fix routing: `docker-gate-run-findings_NOTE_07-08-26.md` (same folder).

**Action:** P0 needs a source fix (quick-fix-class: drop the bad assignment or add the field);
fixture-bug groups need test-file fixes only. None taken this session (reconciliation-only).

## 2. conftest Redis-isolation hardening (durable fix candidate)

**What:** `tests/conftest.py:19` sets a `REDIS_URL` default that assumes no local Redis is
reachable during the unit lane (tests rely on hitting the "Redis unreachable" branch). When an
ambient/unrelated container occupies port 6379 (as happened this session —
`itemintern-redis-1`), unit tests that depend on the Redis-down branch can self-poison shared
`db15`, producing flaky/wrong results that look like product bugs but are actually test-harness
fixture gaps.

**Round 2 (07-08-26): hazard CONFIRMED with a SECOND independent source** — a host brew
`redis-server` 8.6.3 (PID 733, running since Aug 2) held port 6379 and shadowed the compose
`redis:7` for the ENTIRE 07-08-26 Docker gate run; `db15` carries 98 residue keys.
Recommended immediate operator action: `brew services stop redis`. The conftest-level
hardening below is no longer speculative — two different ambient occupants (container, then
brew service) have now poisoned the same assumption. Prioritize the fix decision.

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
