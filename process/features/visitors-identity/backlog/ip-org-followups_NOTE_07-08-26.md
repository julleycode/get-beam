---
name: report:ip-org-followups
description: "Deferred follow-ups from ip-org-database Phases 1-2 closeout: load-transaction optimization, skip-ratio alerting, alembic local-host guard gap, G6 distribution audit, plus cross-program flags (identity-coop-owned broken unit tests, conftest enum-teardown race)"
date: 07-08-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
  phase: ip-org-database-closeout
---

# ip-org-database follow-ups (Phases 1-2 closeout, 07-08-26)

Source: `active/ip-org-database_07-08-26/ip-org-database-evl-iteration-001_REPORT_07-08-26.md`
(EVL known-gaps + addendum). Phases 1-2 shipped `3215fb0` (devjulley, unpushed), flag
`ip_org_lookup_enabled` OFF. None of these block the operator prod-enable sequence, but items
1 and 3 should be weighed before enabling scheduled refresh in prod.

## 1. Load runs as one 158-341s transaction with GiST maintained during inserts

Priority: P2 (perf/ops).
Problem: `refresh_ip_org_dataset --apply` loads 967k rows into staging in a single
transaction with the GiST index live during inserts — 341s cold / 158s re-run on local dev.
Fine locally; on prod (Railway → Supabase) a 3-6 min write transaction holds vacuum horizon
and risks statement/idle timeouts.
Fix options: (a) build GiST index AFTER bulk load (drop from staging DDL, `CREATE INDEX` before
swap) — likely the single biggest win; (b) chunked COPY with batched commits into staging
(swap still atomic); (c) both.

## 2. Skip-ratio drift alerting on scheduled refresh

Priority: P3 (observability).
Problem: join skip-ratio was 12.7% (as2org 2026-07-01 lagging pfx2as 2026-08-05). Ratio drifts
with snapshot-age mismatch; the camelCase defect class (100% skip, silent) would today only be
caught by the `if not rows` swap-refusal. No alert when ratio degrades short of total failure.
Fix: threshold check in `refresh_ip_org_dataset` status path (e.g. WARN structlog event +
refuse swap above ~40% skip, configurable), surfaced in scheduler job logs.

## 3. `apps/api/migrations/env.py` has NO local-host guard (`.env` → Supabase PROD)

Priority: P1 (safety).
Problem: `.env` `DATABASE_URL` points at Supabase production and alembic's env.py applies it
unguarded — a bare `alembic upgrade` from repo root is a prod DDL apply. Discovered + refused
at gate 07-08-26. `scripts/refresh_ip_org.py` got a fail-closed guard (+15 tests,
`tests/unit/test_refresh_ip_org_guard.py`), but **alembic itself remains unguarded**.
Fix: port the same guard into `migrations/env.py` — refuse non-local DSN unless an explicit
env override (e.g. `ALEMBIC_ALLOW_REMOTE=1`) is set; unparseable DSN = refuse. Must NOT break
the Railway deploy path (Dockerfile CMD runs `alembic upgrade head` on boot against the
injected prod DSN — the override needs to be set there deliberately).
Cross-refs: all-context.md Open Questions bullet; memory note
`getbeam-env-points-to-supabase-prod`.

## 4. G6 validated counts only — org_kind/normalize distribution un-audited

Priority: P3 (quality).
Problem: the live dry-run gate matched parse counts exactly (independent re-parse), and the
addendum spot-checked org_kind on known orgs (Apple/Cloudflare → cdn, Deloitte → org), but no
systematic audit of org_kind assignment or `normalize_org_name` truncation/collision across
the 102k-org population exists.
Fix: sampled audit script (stratified by org_kind) + collision report on normalized names;
fold into Phase 3 quality-metric work.

## Cross-program flags (NOT owned by ip-org — routed to owners)

- **identity-coop owns 2 broken unit tests:**
  `tests/unit/test_identity_resolver_parallel.py::TestBeamIdentityNetwork` — 2 failures caused
  by identity-coop's `_upsert_beam_identity` return-type change (their `d78b4f1`). Confirmed
  pre-existing/unchanged across ip-org's G5 full-lane runs (2137→2140 passed, failure set
  identical). Flag to the identity-coop program to fix with their Phase 1 follow-ups.
- **conftest enum-teardown race (pre-existing infra debt):** integration lane degraded by a
  stale `platform` ENUM + `engagement_attributions` teardown race — ip-org's
  `test_ip_org_pipeline.py` passed only "by union" across attempts (zero test-body failures).
  Needs DB reset + teardown fix; independent of any one program (also seen in the 07-08-26
  Docker gate run findings).
