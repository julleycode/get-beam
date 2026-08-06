---
phase: graph-erasure-compliance
date: 2026-08-07
status: COMPLETE_WITH_GAPS
feature: visitors-identity
plan: process/features/visitors-identity/active/graph-erasure-compliance_07-08-26/graph-erasure-compliance_PLAN_07-08-26.md
---

# EXECUTE Report — Cross-Tenant Identity Graph Erasure & Disclosure

**TL;DR** — All 30 checklist items (C-01…C-30) applied. Every gate that can run in this
environment is green: 1165/1165 unit tests (27 new), migration offline-validated both directions,
web typecheck clean, presence checks pass. Docker is down, so the 14 integration gates (T-I1…T-I10)
and the migration live round-trip are **deferred, not passed**. AC-7/AC-8 content stays CONDITIONAL
by design (counsel). Ten backlog stubs written.

## What Was Done

**Phase A — model + migration**
- `apps/api/models/erasure_request.py` (NEW): `ErasureRequest` + `ERASURE_TARGETS` +
  `ERASURE_STATUSES`. Plaintext-free by construction (blind indexes + fingerprints only).
- Migration `d1a6c4e93f27_add_erasure_requests.py` (NEW): table + the two indexes.
  **Head re-derived LIVE** (`alembic ... heads` → `c9f4a7b31e85`, single head) and chained onto it.
  Not hardcoded.

**Phase B — tombstone**
- `services/suppression.py`: `"erased"` added to `VALID_SCOPES`; new `is_email_suppressed_any()`;
  `is_email_suppressed()` rewritten as a one-line delegate — signature and behaviour unchanged.
- `models/suppression.py`: `"erased"` documented in the class docstring.

**Phase C — sweep** (`services/graph_erasure.py`, NEW)
- `enqueue_erasure()`, `run_graph_erasure_sweep()`, `queue_health()`, `lookup_graph_identity()`.
- Only `_try_acquire_lock` / `_release_lock` / own-session are modelled on
  `referral_activation.py`; nothing else. All three §4a boundaries implemented exactly:
  1. the claim commits ALONE with `RETURNING` captured into locals before any destructive statement;
  2. tombstone INSERT then graph DELETE inside ONE explicit `async with db.begin():`, no
     intervening commit;
  3. failure path = rollback, then a FRESH `UPDATE` using the CAPTURED `attempts`.
- `_cascade_suppress` is NOT called. Both tombstone rows come from one raw `pg_insert` using the
  stored `email_bidx` directly as `email_hash`.
- `erasure_queue_health` emits per pass; warns on a stale queue **or** any `failed` row.

**Phase D — producer** (`routers/visitors.py`)
- Enqueue happens after `_verify_site_access` and **before the DELETE loop** (C-11 — the loop
  destroys the only source of the match keys). try/except-wrapped; the tenant-facing delete can
  never break.
- Response gains `erasure_request: {id, status:"queued"}` and is uniform regardless of graph state.
  No synchronous graph read anywhere in the request path.

**Phase E — write boundary** (`services/identity_resolver.py`)
- Exactly ONE hunk, ~10 lines inside `_upsert_beam_identity`, immediately after the
  `if not fp or not email: return` line. Nothing else in that file touched.
- `models/beam_identity.py`: the stale `not yet read/written` comment corrected. No dual-write added.

**Phase F — wiring + operator surface**
- `config.py`: settings block with the default-ON deviation argued inline, and **E-3's "NOT A CAP"
  comment** on `graph_erasure_max_per_minute`.
- `jobs/scheduler.py`: `_graph_erasure_sweep_job` interval job with explicit `jitter` +
  `misfire_grace_time` (Phase 4c convention).
- `routers/privacy.py`: `GET /graph-identity` and `GET /erasure-queue-health`. **C-20's discovery
  branch resolved: `require_admin` exists in `apps/api/dependencies`, so the HTTP routes shipped —
  no CLI fallback needed.** Both are double-gated (admin dependency + `graph_identity_lookup_enabled`,
  default OFF, 404 when off).
- `schemas/privacy.py`: `GraphIdentityLookupOut`, `ErasureQueueHealthOut`.

**Phase G — disclosure (requirements only, no legal copy drafted)**
- `privacy.html`: new "cross-tenant identity network" section (reuse / pooled fields / erasure route
  / subprocessor pointer); the unqualified "we do not share visitor data with third parties"
  sentence qualified.
- `terms.html`: "you own the data you bring to beam" qualified.
- Onboarding install step: `data-testid="cross-tenant-disclosure"`, rendered outside the `detecting`
  branch so it shows before AND during pixel install.
- All three carry the literal marker `cross-tenant identity` and an inline comment marking them as
  **requirements placeholders, not counsel-approved wording**.
- C-26 verified: `next.config.mjs` rewrites only `/` and `/onboarding`; privacy/terms are served
  directly from `public/` at `/beam/*.html`. **No new route wiring needed.**

**Phase H — tests + backlog**
- `tests/unit/test_graph_erasure.py` (NEW, 27 tests), `tests/integration/test_graph_erasure_flow.py`
  (NEW, 14 tests), AC-9 assertion added to `apps/web/e2e/onboarding.spec.ts`.
- Ten backlog stubs (KG-1…KG-9 + the S4 `visitor_emails` observation).

### Operator response when `failed_count > 0` (C-20a, verbatim from §4 step 7)

1. Read the affected rows' `last_error` via `GET /api/v1/privacy/erasure-queue-health` and the
   admin surface — `last_error` is PII-sanitised, so it is safe to read.
2. Fix the underlying cause.
3. **Re-enqueue by resetting those rows to `status='pending'` with `attempts=0`** — the sweep
   re-claims them on its next pass and the operation is idempotent, so re-running a
   partially-completed erasure is safe.
4. If the cause cannot be fixed, the erasure has **not** been performed and the data subject's
   request is unfulfilled — that is a compliance event, not a backlog item, and must be escalated
   to the user, never silently left in `failed`.

Check command: `curl -H 'Authorization: ...' $API/api/v1/privacy/erasure-queue-health`.
"Stuck" looks like: `oldest_pending_age_hours > 168`, or any non-zero `failed`.

## What Was Skipped or Deferred

| Item | Reason |
|---|---|
| T-I1…T-I10 (14 integration tests) | **Docker daemon is down** in this environment. Tests are WRITTEN and collect cleanly (imports valid); they have never been executed. |
| Migration live round-trip (KG-5) | Same — Docker-gated. Offline `--sql` validated both directions only. |
| T-A2 (Playwright onboarding e2e) | Needs a running dev server + the Clerk auth harness (the same pre-existing gap as sibling plans). Assertion written. |
| T-P1 (counsel content review) | Legal judgment, hard SPEC constraint. Not satisfiable by any agent. |
| AC-7 / AC-8 content half | Stays **CONDITIONAL** (KG-4). Presence is green; correctness is not. |
| Legal copy drafting | Explicitly out of scope — requirements + placeholders only. |

## Test Gate Outcomes

| Gate | Status | Evidence |
|---|---|---|
| T-U1 do_not_resolve writes no row, no PII in log | **green** | `test_t_u1_...` |
| T-U2 erased tombstone blocks write | **green** | `test_t_u2_...` |
| T-U3 `is_email_suppressed` unchanged (4 scopes × match/no-match) | **green** | 8 parametrised cases + T-U3b/T-U3c |
| T-U4 exactly one blind-index implementation | **green** | `test_t_u4_...` |
| T-U5 state machine / claim idempotency | **green** | T-U5, T-U5b, T-U5c, T-U5d |
| T-U6 Boundary 1 — claim commits separately | **green** | asserts order `execute, execute, commit` |
| T-U7 Boundary 3 — never wedges at `processing`, `last_error` PII-free | **green** | T-U7, T-U7b, T-U7c |
| T-U8 Boundary 2 happy path | **green** | **per E-1**: asserts `db.begin.call_count==1`, `__aexit__` count + `exc_type is None`, and `execute` ordering `[tombstone_insert, graph_delete]`. **No `db.commit()` assertion.** |
| T-U8b Boundary 2 failure path | **green** | asserts `__aexit__` received `RuntimeError`, tombstone before delete, rollback→fresh update |
| T-U9 queue health warns on stale, no PII | **green** | + a fresh-queue stays-`info` counterpart |
| T-U9b queue health warns on `failed>0` with empty pending | **green** | `test_t_u9b_...` |
| E-2 claim query has no `throttle_flagged` filter | **green** | AST-scoped to `_claim_next`/`_process_claimed` only; also asserts `enqueue_erasure` DOES write it |
| T-R1 full unit regression | **green** | `1165 passed, 2 skipped` |
| T-M1 migration offline validation | **green** | `upgrade c9f4a7b31e85:head --sql` and `downgrade d1a6c4e93f27:c9f4a7b31e85 --sql` both clean; `heads` → `d1a6c4e93f27` single head |
| T-A1 disclosure presence | **green** | `grep -l "cross-tenant identity"` returns all three surfaces |
| C-19 mock mode | **green** | zero `httpx`/network references in the new service; unit lane green under `MOCK_EXTERNAL_APIS=true` |
| Web typecheck | **green** | `npx tsc --noEmit` clean |
| T-I1…T-I10 | **deferred** | Docker down. `--collect-only` passes (14 collected) |
| Migration live round-trip | **deferred** | Docker down (KG-5) |
| T-A2 Playwright | **deferred** | needs dev server + Clerk auth harness |
| T-P1 counsel review | **deferred** | legal judgment (KG-4) |
| T-P2 PII log probe | **partial (agent judgment)** | every new log call site inspected: only ids, counts, `visitor_id[:8]`, and `sanitize_error()` output. Asserted mechanically in T-U1/T-U2/T-U7/T-U9/T-U9b. Not run against a live DEBUG flow. |

## Plan Deviations

1. **Match-key collection lives inside `enqueue_erasure()` rather than inline in the router.**
   C-11 describes collecting keys in `delete_visitor_data`; Touchpoint 3 places `enqueue_erasure` in
   `graph_erasure.py`. Putting the collection behind the service call keeps the `visitors.py` hunk
   minimal and keeps all queue logic in one module. **The binding constraint is unaffected**: the
   whole call still happens before any DELETE statement. Within blast radius.

2. **`enqueue_erasure()` commits its own insert.** The plan did not specify the commit point.
   Committing immediately means the queued request survives even if the caller's subsequent local
   deletion partially fails — strictly safer for the compliance guarantee.

3. **C-15's guard is ~10 lines, not ~6.** Two local imports plus a multi-line condition. Still one
   hunk, still inside `_upsert_beam_identity`, nothing else in the file touched.

4. **`tests/unit/test_scheduler_job_config.py` edited** (not in the checklist). Its E20 arithmetic
   gate asserts an exact `add_job` count and instructs, in its own docstring, to *re-derive the
   arithmetic when a job is added — never to relax the assertion*. Updated 18/16/2 → 19/17/2 with
   the reason recorded. This is following the gate, not weakening it.

5. **`sanitize_error()` used for the router's `erasure_enqueue_failed` log.** The plan sanitises
   `last_error` only. Key collection reads plaintext emails, so a driver error there could echo an
   address into a log — sanitising is required by Business Guardrail #3 regardless.

No hard-stop-class deviation occurred. No schema change beyond the additive new table. No auth,
billing, or public-contract change beyond the additive C1 field and the two admin-gated C2 routes.

## Test Infra Gaps Found

- **Mid-transaction fault injection with a second observing connection does not exist** in
  `tests/integration/`. This is KG-9 and blocks any real-Postgres proof of Boundary 2's atomicity.
  T-U8/T-U8b prove **code shape only** — do not read them as proving ACID behaviour.
- **No context-manager session mock existed anywhere in this repo** before this plan (`db.begin()`
  has zero hits under `tests/`). The mock in `tests/unit/test_graph_erasure.py::_work_session` is
  the first, and is reusable by any future plan asserting a transaction-scope property.
- Docker unavailability blocks the entire Hybrid tier — the same standing gap as every recent plan.

## Closeout Packet

- **Selected plan:** `process/features/visitors-identity/active/graph-erasure-compliance_07-08-26/graph-erasure-compliance_PLAN_07-08-26.md`
- **Finished:** C-01…C-30, all 30 items.
- **Verified:** unit tier (1165 tests, 27 new), migration offline both directions, presence checks,
  web typecheck, mock mode.
- **Unverified:** the whole Hybrid tier (Docker), Playwright, counsel review, real-Postgres atomicity.
- **Classification:** `Keep in active/testing`. Per the plan's own Phase Completion Rules this is
  `CODE DONE`, **not** `EVL GREEN` — `EVL GREEN` requires every Hybrid gate to have been *run* with
  its precondition satisfied, and none has been. `✅ VERIFIED` additionally requires user
  confirmation, and AC-7/AC-8 content is blocked from it by counsel (KG-4) regardless.
- **Remaining cleanup:** run the integration lane and the migration round-trip once Docker is up;
  obtain counsel review of the three disclosure surfaces.
- **Follow-up stubs created (10):** `graph-erasure-race-window`, `graph-erasure-historical-reconciliation`,
  `company-graph-erasure-legal-read`, `privacy-copy-counsel-review`, `graph-erasure-migration-live-roundtrip`,
  `cross-tenant-identified-visitor-erasure-gap`, `graph-erasure-authorization-spoofing-gap`,
  `graph-erasure-cumulative-cap`, `graph-erasure-boundary2-live-fault-injection` (pre-existing, verified),
  `visitor-emails-erasure-gap` — all `_NOTE_07-08-26.md` in `visitors-identity/backlog/`.
- **CONTEXT_PARTIAL:** none.

## Forward Preview

**Test Infra Found** — `_work_session` (context-manager session mock) is the repo's first; reuse it
for any transaction-scope assertion. Mid-transaction fault injection still missing (KG-9).

**Blast Radius Changes** — 3 new backend files, 1 migration, 8 edited backend files, 4 edited web
files, 2 new test files, 2 edited test files. `identity_resolver.py` touched in exactly one hunk, as
promised to the two colliding plans.

**Commands to Stay Green**
```
.venv/bin/python3.11 -m pytest tests/unit -m unit -q
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads
cd apps/web && npx tsc --noEmit
grep -l "cross-tenant identity" apps/web/public/beam/privacy.html apps/web/public/beam/terms.html apps/web/src/app/dashboard/onboarding/page.tsx
# Docker-gated:
docker compose -f infra/docker-compose.yml up -d postgres redis
.venv/bin/python3.11 -m pytest tests/integration/test_graph_erasure_flow.py -m integration -q
```

**Dependency Changes** — none. No new packages.

**Deploy warning** — `graph_erasure_sweep_enabled` defaults **True** (argued deviation), and Railway
runs `alembic upgrade head` on every boot. Pushing to `main` therefore both applies migration
`d1a6c4e93f27` and starts the sweep. `graph_identity_lookup_enabled` stays default False.
