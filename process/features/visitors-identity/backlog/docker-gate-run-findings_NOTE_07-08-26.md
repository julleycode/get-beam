---
name: note:docker-gate-run-findings
description: "Consolidated findings from the 07-08-26 Docker gate run: P0 pre-existing GET /visitors 500 (in prod), graph-erasure + job-change test-fixture bugs, vocab-drift test, 7 untriaged failures, Redis-shadowing hazard round 2, stale __pycache__ pollution"
date: 07-08-26
feature: visitors-identity
---

# Docker Gate Run Findings — 07-08-26

> **RESOLUTION UPDATE (same day, fix-batch executed 07-08-26):** every actionable item below
> is now CLOSED. P0 `GET /visitors` 500 fixed (`confidence_score` moved to `VisitorOut` base
> + `canon_rows` select gained the column — the latent sibling AttributeError died with it);
> graph-erasure fixtures repaired → **14/14 pass** (identity-coop entry-gate Docker leg now
> satisfied); job-change fixtures → **15/15**; vocab test updated; all 7 untriaged failures
> root-caused TEST-SIDE and fixed (notable harness facts: httpx default UA is bot-classified
> → `/ingest` silently 204s without a browser UA; `/ingest` never creates `visitors` rows —
> the aggregator does). Brew redis stopped, 6379 free, stale `__pycache__` purged.
> **Final: integration 518 passed / 0 failed / 0 errors; unit 1203 passed.** Remaining
> open here: nothing — kept for audit trail.

**TL;DR** — The first full Docker gate run since 24-07-26 closed the migration live
round-trip gap program-wide (full 64-rev chain from empty → head `d1a6c4e93f27`; 17-rev
down/up to `e6b2d4a1c837`) and closed social-context-merge AC-7, but surfaced one **P0
source bug shipping in prod**, two test-fixture bug clusters, one vocab-drift test, 7
untriaged failures, and a second confirmation of the Redis-shadowing hazard. Full-lane
measured result: **478 passed / 23 failed / 17 errors.**

## P0 — pre-existing 500 on `GET /visitors` (IN PROD: present on `main` AND `devjulley`)

- `apps/api/routers/visitors.py:227` assigns `confidence_score` to `VisitorOut` — but the
  field only exists on `VisitorDetailOut` (`apps/api/schemas/visitors.py:91`) → pydantic
  ValueError → HTTP 500.
- Accounts for **10 integration failures**: `test_visitor_filters` ×7,
  `test_visitor_list_email` ×2, `test_candidate_endpoints` ×1.
- **Second latent bug in the same block:** `visitors.py:200-208` — the `canon_rows` select
  omits `confidence_score`, while line 215 reads `r.confidence_score` → `AttributeError` in
  the canonical-alias branch (currently unexercised, would 500 the moment that branch runs).
- **Fix pending** — quick-fix-class source change (either stop assigning the field on the
  list path or add it to `VisitorOut` + the canon_rows select). Not fixed in this
  reconciliation session (no source edits permitted).

## Test-fixture bugs (files never executed before this run)

- `tests/integration/test_graph_erasure_flow.py` — **5 F + 2 E of 14**:
  - fixtures set `first_seen`/`last_seen` on `IdentifiedVisitor`, which has neither — those
    columns live on `Visitor` (`apps/api/models/visitor.py:24-25`)
  - fixtures give `Site` a `domain` value — `Site` has no `domain` column and requires
    `name` + `url` NOT NULL
  - **Consequence:** the graph-erasure Hybrid gate is **8/14 UNPROVEN** (7/14 pass) — these
    are TEST bugs, not source bugs, but the gate is not green, so the
    **identity-coop entry-gate Docker half is NOT cleared** (see
    `identity-coop-entry-gate-spec-a-live_NOTE_07-08-26.md`, clearing condition 1).
- `tests/integration/test_job_change_detection.py` — **15/15 ERRORS**: `Visitor` inserted
  without the NOT NULL `first_seen`/`last_seen` columns. Same fixture class.

## Vocab-drift test (identity-vocab-reconcile fallout)

- `tests/integration/test_visitor_stats.py:309` expects `could_enrich`; code returns
  `candidates` — the rename shipped by `identity-vocab-reconcile_07-08-26`. The TEST needs
  updating, not the code.

## Untriaged failures (7)

- `promotion_sweep` ×4, `optout_flow` ×1, `ai_resolution_priority` ×1,
  `campaign_mid_send_promotion_cutover` ×1 — a mix of the `first_seen` fixture-class above
  and genuine behavioral asserts. Needs a triage pass before any is attributed to source.

## Redis hazard — round 2 (now confirmed with TWO independent sources)

- Host brew `redis-server` 8.6.3 (PID 733, running since Aug 2) held port 6379 and
  **shadowed the compose `redis:7` for the entire run**; `db15` carries 98 residue keys.
- Previous occurrence: `itemintern-redis-1` container (24-07-26, see
  `post-docker-gate-followups_NOTE_24-07-26.md` §2).
- **Recommended:** `brew services stop redis` immediately, then implement the conftest
  Redis-isolation hardening (unreachable-address default or autouse `no_redis` fixture) —
  no longer speculative with two confirmed distinct occupants.

## Environment pollution — stale `__pycache__`

- Compiled bytecode from the pre-move path `/Users/apple/Downloads/retargeting user/`
  pollutes tracebacks. Clear it:
  `find . -name __pycache__ -type d -prune -exec rm -rf {} +` (repo root).

## What this run PROVED (for cross-reference)

- **Migration live round-trip CLOSED program-wide:** full 64-revision chain applied from an
  EMPTY `postgres:16-alpine` → head `d1a6c4e93f27`; downgrade 17 revisions to
  `e6b2d4a1c837`; re-upgrade clean. Resolved notes: ingest-abuse-hardening Gap 1,
  cadence-bot-flag Gap 1, site-id-lifecycle gate 1, job-change KG#1 round-trip item,
  graph-erasure-migration-live-roundtrip (KG-5), identity-coop clearing condition 2.
- **social-context-merge AC-7 CLOSED:** `tests/integration/test_usage_limits.py` 3/3 passed
  → plan promoted to VERIFIED.
- Production live-apply remains a separate explicit operator action (Railway auto-applies on
  push to `main`).
