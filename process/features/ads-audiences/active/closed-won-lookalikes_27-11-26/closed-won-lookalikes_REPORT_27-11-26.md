---
phase: closed-won-lookalikes-execute
date: 2026-11-27
status: COMPLETE_WITH_GAPS
feature: ads-audiences
plan: process/features/ads-audiences/active/closed-won-lookalikes_27-11-26/closed-won-lookalikes_PLAN_27-11-26.md
---
# Closed-won lookalikes — EXECUTE report

TL;DR: All sections A–E built behind `closed_won_lookalikes_enabled` (OFF). Every plan gate is green except the full integration lane, which was not re-run because the host disk had about 240 MB free. A targeted run of 74 integration tests passed. UD1–UD6 were accepted by the user.

## What Was Done
- A: `ClosedWonDeal`/`ClosedWonFetch` + non-abstract `fetch_closed_won` (crm/base.py); HubSpot (pipelines won stages, 10k re-window, deals.read scope, needs_reconnect), Pipedrive, Salesforce fetchers with mocks; webhook `POST /crm/{site_id}/webhook/deal` (E6 order); erased-tombstone skip on every ingest path; model `crm_closed_won_contacts` + migration `f7d1b3c84e29` (down `e5c2a9f71d36`); APScheduler `poll_closed_won` (gated at registration + runtime, jitter 120, misfire 1800, no next_run_time); scheduler arithmetic 30/26/3.
- B: CSV upload (10k cap, email required, optional country/company_domain); site-scoped match; exclusion matrix; dedicated seed builder `services/closed_won_seed.py`; `closed_won_seed` sentinel link upsert.
- C: `LookalikeSpec`/`LookalikeResult` + non-abstract `create_lookalike`; Meta (country only ≤ v26, <100 warning, provider error surfaced); Google (lookalikeUserList, DUPLICATE_LOOKALIKE → exists, <1,000 warning, Demand Gen note, EEA fail-closed); LinkedIn hashed CSV.
- D: routes `POST closed-won/csv`, `GET closed-won/seed`, `GET closed-won/linkedin.csv`, `POST closed-won/lookalike`; site-delete cascade; graph-erasure delete by bidx; web types, api client, `closed-won-lookalike-card.tsx` mounted in the ads panel.
- E: tests `test_closed_won_readback.py`, `test_meta_lookalike.py`, `test_google_lookalike.py`, `test_closed_won_seed.py`, `test_closed_won_erasure.py`.

## What Was Skipped or Deferred
- Full integration lane (G5 second half): not run (disk ~240 MB). EVL must run it.
- KG-L/KG-SF/KG-HS live provider legs: backlog `backlog/closed-won-lookalikes-live-provider-gates_NOTE_27-11-26.md`.

## Test Gate Outcomes
| Gate | Result |
|---|---|
| G1 | 11 passed |
| G2 + G2b (+ scheduler) | 26 passed |
| G3 + G8 + G7 (flag ON, :5433) | 19 passed |
| G4 migration up/down/up (fresh DB, dropped) | PASS, head f7d1b3c84e29 |
| G5 unit | 3222 passed; 3 failures in `test_paid_x402.py` only (shared-Redis 429 concurrency state; file untouched) |
| G5 integration | targeted 74 passed; full lane not run |
| G6 tsc | 0 errors besides pre-existing `@sentry/nextjs` missing from shared node_modules |

## Plan Deviations
1. E7/E8: no `get_lookalike_spec`. The spec is stored in the sentinel `segment_id` (`closed_won_lookalike:{CC}:{ratio|expansion}`), checked against the allow-list first, and written under `SELECT … FOR UPDATE` on the seed link. Steps 8a/9 and Touchpoints still mention the method.
2. Added a nullable `country` column to `crm_closed_won_contacts`. UD3's optional CSV country needed somewhere to live.
3. No cursor column. Each poll uses `since = max(updated_at) − 1 day` per connection. The upsert is idempotent, so the overlap is safe.
4. `needs_reconnect` is stored as a sentinel `CrmConnection.last_error` string (no schema change) and shown in `GET seed`.
5. Added a fourth route, `GET closed-won/linkedin.csv`, for step 10. There is no separate seed-push route: the lookalike route pushes the seed when none exists or when `push_seed=true`. Repeating with the same spec makes zero adapter calls.
6. Google `DUPLICATE_LOOKALIKE` returns `status=exists` with no id, because Google returns none. The stored id is kept.
7. Webhook payload is `{deal_id, emails[], closed_at?, company_domain?, country?}`, signed with the `X-Beam-Signature` hex HMAC (outcomes pattern).
8. The company-exclusion call shape (`load_exclusions(db, site_id)`, `match_excluded(exclusions, domain=…)`, `.reason`) is assumed, because the module is absent. It is import-guarded and fails closed on error.
9. The graph-erasure delete runs for every claimed request that has a bidx, rather than as a named target. `test_graph_erasure.py` T-U8 now expects the extra statement.
10. Phase-1 scheduler test edits are mirrored: counts re-derived per the gate's own instruction.

## Test Infra Gaps Found
- `test_paid_x402.py` shares Redis concurrency counters across lanes → flaky 429s (harness-drift).
- Worktree has no `apps/web/node_modules`; G6 ran via a temporary symlink to the main checkout (removed). Main's node_modules lacks `@sentry/nextjs`.
- Host disk pressure (~240 MB free) blocks the 21-minute integration lane.

## Closeout Packet
- Plan: `process/features/ads-audiences/active/closed-won-lookalikes_27-11-26/closed-won-lookalikes_PLAN_27-11-26.md`
- Verified: all of the gates listed above. Unverified: the full integration lane and all live provider legs.
- Classification: Keep in active/testing (harness review-decision REJECT until the full lane is green).
- Next: EVL (vc-tester) with the full integration lane, then UPDATE PROCESS.

## Forward Preview
### Test Infra Found
`tests/integration/test_closed_won_seed.py` uses a detached `SimpleNamespace` principal for `get_current_user`. An ORM `User` expires after a commit and then lazy-loads outside the request's greenlet.
### Blast Radius Changes
New: `models/crm_closed_won.py`, `services/closed_won_seed.py`, migration `f7d1b3c84e29`, `web/components/closed-won-lookalike-card.tsx`. Edited additively: crm base/hubspot/pipedrive/salesforce, ads base/meta/google/linkedin, routers ads/crm/sites, graph_erasure, scheduler, config, models/__init__, schemas/ads, web api.ts/api-types.ts/ad-connect-panel.tsx.
### Commands to Stay Green
G1/G2/G2b/G3/G7/G8 commands from the Validate Contract, with DSN `localhost:5433/retarget_agent_test_lane_b` and `REDIS_URL=redis://localhost:6379/14`.
### Dependency Changes
None. Alembic head is now `f7d1b3c84e29`; ad-insights must chain off it.
