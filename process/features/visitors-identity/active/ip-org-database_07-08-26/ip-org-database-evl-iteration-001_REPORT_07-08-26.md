# EVL Iteration 001 — ip-org-database

Date: 2026-08-07
Plan: ip-org-database_PLAN_07-08-26.md
Cycle: 1 of max 10
Loop: EVL (execute-validate-fix)

## Gate run 1 (pre-fix)

| Gate | Verdict |
|---|---|
| G1 targeted unit (ingest+lookup+company_resolver+scheduler) | PASS (111) |
| G2 alembic single head `a3e8d5c71f02` + offline up/down `f2c81a6b4d09:a3e8d5c71f02` | PASS |
| G3 integration test_ip_org_pipeline.py (9 tests) | PASS-by-union (pre-existing conftest enum-teardown race; no test-body failure) |
| G4 forbidden-file isolation (identity-coop concurrent work untouched, zero ip_org refs) | PASS |
| G5 full unit lane (2 failed / 2137 passed — failure set = pre-existing identity-coop pair) | PASS |
| G6 live CAIDA dry-run | **FAIL** — 0 orgs, 1,107,822/1,107,822 prefixes skipped |

## Defect

`parse_as2org` read `organization_id`/`org_id` (snake_case); live CAIDA as2org JSONL emits camelCase `organizationId`. Org map empty → join empty → 100% skip, silent. Unit fixtures had invented the same snake_case keys, masking the bug (fixture-encodes-the-bug class). Fail-safe held: `if not rows` guard refuses staging swap, so an --apply run would have errored, not blanked the table.

## Fix (vc-execute-agent supplement, scoped)

- `apps/api/services/ip_org_ingest.py` — org-id key order `organizationId` → `organization_id` → `org_id`; record discrimination by explicit `type: ASN|Organization` field with legacy asn-key heuristic fallback; KeyError caught on asn parse.
- `tests/unit/test_ip_org_ingest.py` — fixtures regenerated from real record shapes (camelCase, `type`, `opaqueId`, `changed`, `source`); +4 regression tests incl. real-shape join, type-field discrimination, legacy fallback, unknown-key-yields-zero. 24 → 31 tests.

## Gate run 2 (post-fix)

| Gate | Verdict |
|---|---|
| G1-redo | PASS (102) |
| G6-redo | **PASS** — orgs 102,624 / rows 967,079 / skipped 140,743 (12.7%, explained: as2org 2026-07-01 lags pfx2as 2026-08-05); tester independently re-parsed both raw .gz with own throwaway parser — all 4 counts matched exactly |
| G5-redo | PASS — failure set unchanged (2 pre-existing identity-coop), 2140 passed |
| G3-redo | PASS-by-union (same pre-existing conftest race; all 9 pass across attempts, zero test-body failures) |

## Known-gaps carried to closeout

1. `--apply` path never exercised — load/advisory-lock/staging-swap/index-rename unproven at 967k-row volume.
2. Migration `a3e8d5c71f02` offline `--sql` only; no live round-trip (GiST `inet_ops` unproven vs real server). Operator gate before flag flip.
3. Integration lane degraded by pre-existing conftest enum-teardown race (stale `platform` ENUM + `engagement_attributions` teardown) — independent infra debt, needs DB reset + teardown fix.
4. G6 validates counts only — live `org_kind` distribution + normalize truncation unexercised.
5. Skip-ratio drifts with snapshot age — alert threshold worth adding on scheduled refresh.
6. G5 passed-count delta unreconciled (+3 lane vs +7 file) — failure set confirmed unchanged (the actual gate).

loop_status: HALTED_SUCCESS (1 fix cycle)

## Addendum 07-08-26 — live --apply run (local dev DB), gaps 1+2 CLOSED

Safety incident first: initial dispatch found `.env` DATABASE_URL points at **Supabase production** (`aws-1-ap-southeast-1.pooler.supabase.com`) and `alembic/env.py` has no local-host guard — a bare `alembic upgrade` from repo root applies to prod. Agent refused at safety gate; nothing touched. Mitigations: memory note written (`getbeam-env-points-to-supabase-prod`), and `scripts/refresh_ip_org.py` gained a fail-closed local-host guard (`--apply` refuses non-local DSN unless `--allow-remote`; unparseable = refuse) + 15 unit tests (`tests/unit/test_refresh_ip_org_guard.py`), incl. live negative test against the real Supabase DSN.

Re-run with `DATABASE_URL` pinned to `localhost:5433/retarget_agent`:

- **Migration live-apply:** full chain from EMPTY DB to head `a3e8d5c71f02` in 8s; live down/up round-trip `a3e8d5c71f02`↔`f2c81a6b4d09` clean, GiST inet_ops restored. Gap 2 CLOSED.
- **--apply run 1:** failed 167s in — Postgres container killed from OUTSIDE the session (`fast shutdown request`, whole compose stack stopped; unattributed, see concurrent-session memory notes). Accidental crash-safety proof: live table 0 rows (never half-loaded), zero staging leak, migration intact — fail-open contract held through real mid-load server death.
- **--apply run 2:** OK, 341s, **967,079 rows** loaded. Advisory-lock path traced. org_kind: org 63.8% / eyeball 26.9% / datacenter 7.9% / cdn 1.4%.
- **--apply run 3 (swap re-run):** OK, 158s, table oid changed (real swap), index names canonical, zero staging leftovers. Gap 1 CLOSED.
- **Longest-prefix at volume:** 8.8.8.8 → /24 beats /12 and /9. Apple AS714 + Cloudflare bucket `cdn`, correctly excluded from org query. Real B2B resolves (Deloitte /22 /23 /24 → org).
- **EXPLAIN ANALYZE:** GiST index scan confirmed. Warm 2–6ms (0.43ms/lookup batched); COLD 26–385ms first touch after load/swap. <5ms target holds warm only — note before flag enable.

New concerns (not blockers):
- Load holds ONE transaction 158–341s with all 4 indexes (incl. GiST) maintained during chunked inserts — post-load index build would be materially faster. Next optimization candidate.
- Local dev DB left migrated + loaded (head `a3e8d5c71f02`, 967k rows) as evidence.
- Pre-existing compose healthcheck noise: `FATAL: database "retarget" does not exist` every ~6s (pg_isready without -d). Unrelated.

Remaining open gaps: G6 count-only validation (org_kind/normalize distribution un-audited), skip-ratio drift alerting, conftest enum-teardown race (infra debt), Phase 3 (domain mapping) unstarted.
