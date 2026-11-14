---
phase: graph-erasure-compliance
date: 2026-08-11
status: COMPLETE_WITH_GAPS
feature: visitors-identity
plan: process/features/visitors-identity/active/graph-erasure-compliance_07-08-26/graph-erasure-compliance_PLAN_07-08-26.md
---

# EXECUTE Report (session 2, 11-08-26) — deferred-gate closure

**TL;DR** — No new code was needed. All 30 checklist items (C-01…C-30) and binding instructions
E-1/E-2/E-3 were already applied and committed on 07-08-26 (`784aba2` + `2136219`); this session
verified that claim item-by-item against source and then **closed the gates the first session had to
defer**. Docker was in fact available (the standing false premise — CLI simply off `PATH`), so:
integration **T-I1…T-I10 = 14/14 PASS**, S16 scratch probe run **live** against real
Postgres + `sqlalchemy 2.0.35`, `erasure_requests` confirmed live on the dev DB, T-M1 offline-valid
both directions. Unit lane matches baseline exactly (1750 passed / 2 skipped). T-A2 (Playwright) is
**deliberately NOT run** — hard-stop class, see below. AC-7/AC-8 content stays CONDITIONAL (KG-4).

## What Was Done

Nothing was implemented. This session was verification-only. Zero source files modified.

Item-by-item audit confirming the prior session's work is genuinely on disk (not merely claimed):

| Checklist | Evidence found |
|---|---|
| C-01, C-02 | `apps/api/models/erasure_request.py` (97 lines) — all 13 columns, both indexes, `ERASURE_TARGETS`, `ERASURE_STATUSES`; `throttle_flagged` carries the "must never appear in a WHERE clause" docstring |
| C-03 | migration `d1a6c4e93f27_add_erasure_requests.py`, `down_revision = c9f4a7b31e85` — already in the committed chain; live head is now `f4b9d2a71c68`. **No new migration written or needed.** |
| C-04…C-06 | `services/suppression.py:25` `VALID_SCOPES` includes `"erased"`; `is_email_suppressed_any()` added; `is_email_suppressed()` preserved as a one-line delegate (`:57`); `models/suppression.py:23` docstring documents the scope |
| C-07…C-10 | `apps/api/services/graph_erasure.py` (583 lines) — advisory lock, `_claim_next` (Boundary 1 commit + RETURNING captured to locals), `_process_claimed` (Boundary 2 `async with db.begin():`, tombstone-first), Boundary 3 rollback + fresh UPDATE on captured `attempts`, `_emit_queue_health`, `lookup_graph_identity` |
| C-11…C-14 | `routers/visitors.py:432-445` — enqueue runs **before** the DELETE loop, try/except-wrapped with `sanitize_error`, uniform `"erasure_request": {id, status:"queued"}` response |
| C-15 | `services/identity_resolver.py:1346-1368` — the single ~6-line guard hunk inside `_upsert_beam_identity`, logging `graph_write_blocked` with `visitor_id[:8]` only |
| C-16 | `models/beam_identity.py:51-52` — stale "not yet read/written" comment replaced with the accurate description |
| C-17, C-18 | `jobs/scheduler.py:356-370, 750-755`; `config.py:741-770` |
| C-20, C-20a, C-21 | `routers/privacy.py` `GET /graph-identity` + `GET /erasure-queue-health`, both `Depends(require_admin)`; `schemas/privacy.py` `GraphIdentityLookupOut`. **The admin dependency discovery branch resolved to the HTTP route** — `apps/api/dependencies.require_admin` exists, so the CLI fallback was correctly not taken |
| C-22…C-26 | `privacy.html` (new "cross-tenant identity network" section, prior unqualified sentence qualified), `terms.html:138` (ownership claim qualified), `components/onboarding/cross-tenant-disclosure.tsx` shared by both install surfaces |
| C-27…C-29 | `tests/unit/test_graph_erasure.py` (27 tests), `tests/integration/test_graph_erasure_flow.py` (14 tests), `apps/web/e2e/onboarding.spec.ts:253-268` |
| C-30 | all **ten** backlog stubs present in `process/features/visitors-identity/backlog/` |

Binding Execute-Agent Instructions — verified honored, not just present:

- **E-1** — `tests/unit/test_graph_erasure.py` builds the session mock deliberately (`db.begin =
  MagicMock(return_value=txn)` with `AsyncMock` `__aenter__`/`__aexit__`, exactly as E-1's
  no-precedent warning requires). T-U8 asserts `db.begin.call_count == 1`, `__aexit__` call count +
  exception info, and `db.execute.call_args_list` ordering. **No `db.commit()` assertion exists for
  Boundary 2** — grep-confirmed. T-U6's Boundary-1 commit assertion is retained and separate.
- **E-2** — the T-I10 source assertion is `test_volume_marker_is_never_a_filter_on_the_claim_path`,
  which AST-parses `_claim_next` / `_process_claimed`, strips docstrings, and asserts
  `throttle_flagged` is absent from the *executable* source only — then positively asserts
  `enqueue_erasure` **does** write it. Correctly narrowed; the unsatisfiable whole-file grep is gone.
- **E-3** — `config.py:756-767` carries the full inline "NOT A CAP, DESPITE THE NAME … the 61st
  request in a minute does NOT fail" comment.

## Test Gate Outcomes

| Gate | Command | Result |
|---|---|---|
| T-U1…T-U9b (27 tests) | `.venv/bin/python3.11 -m pytest tests/unit/test_graph_erasure.py -m unit -q` | **27 passed** |
| T-R1 unit lane | `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` | **1750 passed / 2 skipped** — exact baseline match, zero regression |
| T-I1…T-I10 (14 tests) | `.venv/bin/python3.11 -m pytest tests/integration/test_graph_erasure_flow.py -m integration -q` | **14 passed** in 44s — **first time these have ever run**; the 07-08-26 session deferred all of them |
| T-R1 integration lane | `.venv/bin/python3.11 -m pytest tests/ -m integration -q` | 574 passed / **2 failed** — `test_outcome_digest.py::test_sends_once_stamps_and_throttles`, `test_referrals.py::test_no_events_no_reward`. **Both pass in isolation** (re-run: 2 passed) → cross-test pollution, classification **harness-drift**, outside this plan's blast radius, pre-existing |
| T-M1 migration | `alembic upgrade c9f4a7b31e85:d1a6c4e93f27 --sql` / `downgrade d1a6c4e93f27:c9f4a7b31e85 --sql` (explicit range, `DATABASE_URL` pinned to localhost) | **PASS both directions** — CREATE TABLE + 2 indexes emitted; DROP TABLE emitted |
| T-M1 live (KG-5, partial) | live introspection of the dev DB | `erasure_requests` exists with all 13 columns matching the model. This is live-apply evidence; a full down/up round-trip on a disposable DB was still not run this session, so **KG-5 stays open** |
| T-A1 presence | `grep -l "cross-tenant identity" …` | **PASS** — privacy.html, terms.html, cross-tenant-disclosure.tsx |
| T-A2 e2e | `npm run test:e2e -- onboarding.spec.ts` | **NOT RUN — deliberate hard stop.** See Deviations |
| T-P1 content probe | manual read of all three surfaces | **Requirements met** (reuse disclosed, pooled fields enumerated, erasure route stated, subprocessor surface named; the unqualified privacy.html sentence and the terms.html ownership claim are both qualified). All three carry an explicit "REQUIREMENTS PLACEHOLDER, NOT COUNSEL-APPROVED WORDING" marker. **Content half stays CONDITIONAL — KG-4** |
| T-P2 log probe | audit of every `logger.*` call on the erasure paths | **PASS.** Every line carries ids/counts only (`visitor_id[:8]`, `site_id`, `request_id`, counts). Both PII-adjacent error sites route through `sanitize_error()` (email-regex strip + 500-char truncate). `graph_erasure.py:106`'s bare `str(exc)` is on the advisory-lock statement, which binds no PII; `:415`'s `logger.exception` is inside the plaintext-free sweep. No plaintext email, name, or ciphertext is reachable by any log line |

**S16 scratch probe (C-08 sub-bullet) — the one item the plan explicitly asked EXECUTE to confirm:**
run live against this repo's pinned `sqlalchemy 2.0.35` and a real Postgres —
`SELECT 1` → `await db.commit()` → `async with db.begin():` → `SELECT 1` completed cleanly.
**No autobegin conflict. The named fallback (`await db.begin()` guard) is NOT needed.** The
implementation's existing `async with db.begin():` shape is confirmed correct on this exact version.

## Plan Deviations

1. **No code was written.** The plan's Resume section says "No code written" — that is stale. The
   work was executed and committed on 07-08-26. Implementing again would have duplicated it. This is
   a within-blast-radius documentation deviation, surfaced rather than silently absorbed.
2. **`ERASURE_TARGETS` is `("beam_identity_graph", "identity_signals")`, not the plan's
   `("beam_identity_graph",)`.** The second target was added by the follow-on security commit
   `2136219` ("H6"), reasoning that `identity_signals` holds decryptable `email_ciphertext` keyed by
   the same blind index, so leaving it would let decryptable PII for an erased person survive. This
   is a *widening* of erasure — strictly safer, and exactly the extensible-constant change the plan's
   C4 contract was designed to accommodate. Not introduced by me; recorded because it differs from
   the literal plan text.
3. **T-A2 not run — hard-stop class, escalating rather than deciding.** The Playwright spec creates
   sites through the dashboard. `apps/web/.env.local` is on record (memory note
   `getbeam-env-local-points-web-at-prod-api`) as pointing the web app at the **prod Railway API**,
   and I was blocked by the privacy hook from reading the file to confirm the current value. Running
   it could have written test sites to production — an outward-facing, irreversible action outside
   the validate-contract. Per the deviation protocol I stopped instead of proceeding. The gate is
   otherwise ready: the assertion exists, is well-formed, uses the canonical
   `expect(locator).toBeVisible({timeout})` pattern (never `waitForTimeout`), the auth storageState
   is present and fresh, and T-A1 already proves the marker string mechanically. **Operator action
   needed:** confirm `.env.local` points at `localhost:8000`, then run
   `cd apps/web && npm run test:e2e -- onboarding.spec.ts`.

## Test Infra Gaps Found

- The two full-lane integration failures are cross-test pollution, reproducing only in the full run.
  This is the same class as the conftest Redis-isolation item already tracked in
  `post-docker-gate-followups_NOTE_24-07-26.md`.
- KG-9's mid-transaction fault-injection harness still does not exist (unchanged).

## Closeout Packet

- **Selected plan:** `process/features/visitors-identity/active/graph-erasure-compliance_07-08-26/graph-erasure-compliance_PLAN_07-08-26.md`
- **Finished:** all C-01…C-30 verified on disk; E-1/E-2/E-3 verified honored; every automated and
  hybrid gate run except T-A2.
- **Verified vs unverified:** verified — unit (1750/2), erasure integration (14/14), T-M1 both
  directions, live schema, T-A1, T-P1, T-P2, S16 probe. Unverified — T-A2 (env hard stop), KG-5 full
  round-trip, KG-9 fault injection, AC-7/AC-8 content (counsel).
- **Bar reached:** `EVL GREEN` for every engineering AC that can run in this environment.
  **NOT `✅ VERIFIED`** — that needs user confirmation plus T-A2, and AC-7/AC-8 content stays
  CONDITIONAL by design.
- **Classification:** **Keep in active/testing.** Not archivable: T-A2 is outstanding and AC-7/AC-8
  are counsel-gated.

## Forward Preview

- **Test infra found:** Docker IS available (CLI at `/Applications/Docker.app/Contents/Resources/bin/docker`,
  detect via `lsof` on 5433/6379). Test DSN is `retarget:retarget_dev@localhost:5433/retarget_agent`
  — **not** `postgres:postgres`. Every "environment-blocked" gate in this feature's backlog rests on
  the false premise and is re-classifiable as RUNNABLE.
- **Blast radius changes:** none — zero source files modified this session.
- **Commands to stay green:** `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` (1750/2);
  `.venv/bin/python3.11 -m pytest tests/integration/test_graph_erasure_flow.py -m integration -q` (14).
- **Dependency changes:** none.

## Known Gaps (accepted residuals, unchanged)

KG-1 (race window), KG-2 (historical reconciliation, not actionable), KG-3 (`CompanyGraphNode`,
legal read), KG-4 (AC-7/AC-8 counsel — **not attempted, correctly**), KG-5 (migration live
round-trip — narrowed but still open), KG-6 (other tenants' `IdentifiedVisitor` rows), KG-7
(authorization spoofing), KG-8 (no cumulative cap), KG-9 (no live fault-injection proof). All ten
backlog stubs (nine KGs + the S4 `visitor_emails` observation) are on disk.
