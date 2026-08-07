---
phase: identity-coop-phase-1-ledger-substrate
date: 2026-08-07
status: COMPLETE
feature: visitors-identity
plan: process/features/visitors-identity/active/identity-coop_07-08-26/phase-1-ledger-substrate_PLAN_07-08-26.md
---

# Phase 1 — Ledger + Contribution Substrate — EXECUTE Report

**TL;DR** — All checklist items done, all 16 validate-contract gates green including all three
Hybrid gates (Docker 29.4.2 was up, so nothing was deferred). 21 new unit tests + 10 new integration
tests, all passing. Migration round-trip clean on a disposable `postgres:16-alpine`. Resolver diff
11 changed lines (budget ≤ 12). Zero production exposure — both flags default OFF and neither
migration is applied anywhere. The 5-artifact high-risk evidence pack is written and deliberately
carries `PENDING USER APPROVE/REJECT`; it needs a human verdict before this phase is "ready".

## Context Envelope

| # | Field | Value |
|---|---|---|
| 1 | feature | visitors-identity |
| 2 | phase | EXECUTE |
| 3 | session-goal | Implement identity-coop Phase 1 (ledger substrate) exactly per the approved plan |
| 4 | branch | devjulley |
| 5 | worktree | /Users/apple/getbeam (main) |
| 6 | context-group | tests |
| 7 | blast-radius-packages | apps/api/{models,services,routers,schemas,migrations}, tests/{unit,integration} |
| 8 | active-plan | process/features/visitors-identity/active/identity-coop_07-08-26/phase-1-ledger-substrate_PLAN_07-08-26.md |
| 9 | test-runner | pytest (unit lane) \| pytest (integration lane) |
| 10 | validate-contract | inline in plan §Validate Contract (outer-pvl, 2026-08-07, Gate: CONDITIONAL) |

## Alembic Head Record (E-6 / A1)

- **Head re-derived LIVE as the first EXECUTE action:** `d1a6c4e93f27` — exactly ONE head. A1's
  STOP-and-re-chain condition did not fire.
- Both new revisions chained onto that live value, never onto a head string quoted in a document:
  - `e7b3d5f19c46_add_identity_coop_tables.py` (revises `d1a6c4e93f27`)
  - `f2c81a6b4d09_add_site_contribution_enabled.py` (revises `e7b3d5f19c46`)
- **Head moved again during this session.** A concurrent session's `a3e8d5c71f02_add_ip_org_prefixes.py`
  landed with `down_revision = f2c81a6b4d09` — it chained onto THIS phase's head. `alembic heads` now
  returns a single head `a3e8d5c71f02`. **No fork, no re-chain needed.** Re-derive again before any
  live apply; this repo's head moved twice inside one EXECUTE session.

## What Was Done

**Step A — models and migrations**
- `apps/api/models/identity_coop.py` (NEW) — `ContributionEvent`, `CreditLedgerEntry`,
  `ContributionConsentAcceptance`, following the `identity_signal.py` shape, Python 3.11 hints only.
- `apps/api/models/site.py` — additive `contribution_enabled` column, default False,
  `server_default="false"`, commented in the `auto_identify_enabled` style.
- `apps/api/main.py` — mapper registration import (A6), so unit tests can construct the ORM objects.
- Two additive-only migrations in `apps/api/migrations/versions/` (the corrected path — the plan's
  original `apps/api/alembic/versions/` does not exist and is not scanned).
- A7 offline `--sql` with an explicit revision range: clean.

**Step B — config** — five settings (not four) under `## ─── Identity co-op (Phase 1) ───`, all
default OFF/inert, with the required rollout order documented inline (erasure LIVE → migrations
applied → legal review + re-pin the digest → global flag → per-site flag via the API only).
`coop_terms_version` is pinned to a 64-hex digest.

**Step C — service module** — `apps/api/services/identity_coop.py` (NEW) holds ALL co-op logic:
`maybe_record_contribution` (resolver-facing; resolves the per-site flag and the blind index),
`record_contribution` (the three gates), `spendable_balance` (derived, never stored),
`record_consent_acceptance` (append-only, does not commit — the caller shares its transaction).
No `identity_resolver` import at module level; no suppression symbol imported at all (D-B).

**Step D — the hook** — `wrote_graph = await self._upsert_beam_identity(...)` then
`if wrote_graph and settings.identity_coop_enabled:` + a local import + the call.
`_upsert_beam_identity` changed `-> None` → `-> bool` with exactly the D5 edit set: `return False` at
the fingerprint/email guard, `return False` at the combined `do_not_resolve` /
`GRAPH_WRITE_BLOCKING_SCOPES` guard, `return True` immediately after `await self.db.commit()`,
`return False` in the `except` path (which previously fell through to an implicit `None`), plus
signature and docstring. **Guard logic and ordering unchanged — only the returned value.**

**Step E — flag wiring (layers 1-4)** — `schemas/sites.py` gained `contribution_enabled` on both the
read and update schemas plus an optional `terms_version`; `routers/sites.py` rejects `422` unless
`terms_version` is 64-char lowercase hex AND equals `settings.coop_terms_version` (E4), and writes the
acceptance row before the handler's single `await db.commit()` so the flip and the audit row share one
transaction. Opting OUT needs no acceptance. E3's 404-not-403 is inherited from `verify_site_access`
and is now covered by a test.

**Step F — tests** — `tests/unit/test_identity_coop.py` (21 tests) and
`tests/integration/test_identity_coop_contribution.py` (10 tests).

**Step G — migration round-trip** — ad-hoc disposable `postgres:16-alpine`, never a shared or prod DB.

## Test Gate Outcomes

| Gate | Strategy | Result |
|---|---|---|
| `alembic heads` single head, live (E-6/A1) | Fully-Automated | PASS — `d1a6c4e93f27` |
| Offline `--sql`, explicit range (A7) | Fully-Automated | PASS — exit 0 |
| B2 — all FIVE settings default OFF/inert | Fully-Automated | PASS |
| AC-1 flag OFF ⇒ zero events, zero ledger rows (F1) | Fully-Automated | PASS |
| AC-2 non-contributor still gets graph matches (F2) | Fully-Automated | PASS — AST-asserted absence of any read-path gate |
| AC-3 merge-aware, one event per identity/day (F3) | Fully-Automated | PASS (+ integration leg vs the real constraint) |
| AC-5 one qualifying contribution ⇒ one ACCRUE lot (F4) | Fully-Automated | PASS |
| AC-9 abuse half ⇒ event kept, credit withheld (F5) | Fully-Automated | PASS |
| AC-9 bot half, `is_bot_suspect` (F11 / D-C) | Fully-Automated | PASS |
| AC-12 grandfathered rows contribute 0 (F7) | Fully-Automated | PASS |
| Best-effort hook never breaks resolve (F8) | Fully-Automated | PASS |
| D-A/D-B no graph write ⇒ nothing accrued (F9) | Fully-Automated | PASS — 3 parametrized no-op paths |
| D-B privacy invariant, no new bidx row (F10) | Fully-Automated | PASS |
| D-E no second credit on a later day (F12) | Fully-Automated | PASS (unit + integration) |
| AC-10 acceptance guard, 5 legs (F13 / E4) | Fully-Automated | PASS |
| D-A bool return + callers unaffected (F14) | Fully-Automated | PASS |
| Unit-lane regression | Fully-Automated | PASS — 1224 passed, 2 skipped, 0 failed |
| Integration-lane regression | Fully-Automated | PASS — **528 passed, 0 failed, 0 errors** (dedicated DB, isolated worktree) = 518 baseline + 10 new |
| Diff ≤ 12 lines on `identity_resolver.py` (D4/E-1) | Fully-Automated | PASS — 11 changed lines |
| **Migration round-trip, disposable Postgres (G1/G2)** | **Hybrid** | **PASS** — 66 revs from empty, down 2, up 2, clean both ways |
| **`uq_coop_accrued_site_email` partial index present** | **Hybrid** | **PASS** — `UNIQUE ... WHERE (accrued IS TRUE)` |
| **Duplicate `ACCRUE` raises `IntegrityError`** | **Hybrid** | **PASS** — via raw SQL, bypassing all service code |
| 5-artifact high-risk evidence pack (E-5) | Agent-Probe | WRITTEN — verdict deliberately `PENDING USER APPROVE/REJECT` |

**No Hybrid gate was deferred.** Docker 29.4.2 was up; the stale "permanently deferred in this
environment" sentence in the plan's Test Infra Improvement Notes was correctly not cited.

## Plan Deviations

All within blast radius; none touch a hard-stop class.

1. **`maybe_record_contribution` wrapper added to the co-op module** (not named in the plan).
   *Why:* D2 asks the resolver to resolve `site_contribution_enabled`, but doing that inline would
   have pushed the resolver diff well past the ≤ 12 budget, and the plan's own rule is that all logic
   lives in `identity_coop.py`. The wrapper puts the per-site lookup and the blind-index translation
   on the co-op side, keeping the resolver at 11 lines. *Impact:* strictly better separation; the
   `Site.contribution_enabled` lookup is a single indexed scalar select that only runs when the global
   flag is already ON (default OFF ⇒ zero cost) and never on the ingest hot path.
2. **D2's "cache on the resolver instance for the request" not implemented.** *Why:* the cache would
   have to live on the resolver, which re-couples the two modules the wrapper just separated, for a
   lookup that is already free while the flag is OFF. *Impact:* one extra scalar select per
   newly-identified visitor once the co-op is enabled. Noted for Phase 2 if it ever matters.
3. **Five plan-named unit tests (F3, F9–F12) use a fake `AsyncSession`.** *Why:* `ON CONFLICT` and a
   partial unique index are Postgres semantics; the unit lane has no DB by repo convention. *Impact:*
   net coverage is HIGHER than the plan required — the service-decision half is proven in the unit
   lane and the DB-enforcement half by the Hybrid gates plus three extra integration legs added for
   the same criteria. The split is disclosed in both files' docstrings.
4. **Four structural tripwire tests added** beyond the plan (AST-based "no suppression import",
   append-only consent trail, no `user_id` on the ledger, blind-index-only columns). *Why:* each
   guards a decision (D-B, D-D, AC-10, PII posture) that is otherwise only enforced by convention.
5. **`apps/api/main.py` modified** — not in the plan's Touchpoints list, but required by A6
   (mapper registration). One import block.

## Test Infra Gaps Found

- **The integration lane cannot be measured cleanly in the SHARED worktree right now.** A concurrent
  session was writing to it throughout EXECUTE, and both sessions share one test database
  (`retarget_agent_test` on port 5433). Three shared-DB full-lane runs produced three DIFFERENT
  failure sets (3F/5E, then 1F/18E in a *cleaner* tree), with symptoms like `401 User not found` and
  SQLAlchemy `IntegrityError` — i.e. tracking the environment, not the code.
- **Settled decisively, not by assumption.** The full lane in an isolated worktree carrying ONLY this
  phase's changes, against a DEDICATED disposable database and Redis slot:
  **528 passed, 0 failed, 0 errors** — exactly 518 baseline + 10 new. Supporting bisection: pristine
  HEAD → 15/15; HEAD + only identity-coop (concurrent config block surgically removed, verified
  `grep -c ip_org` = 0) → 15/15; shared worktree → failures. **The failures require the concurrent
  session's changes and a shared DB to appear.**
- This is the same conftest DB/Redis isolation weakness already tracked in
  `backlog/post-docker-gate-followups_NOTE_24-07-26.md`. Recommend hardening it to per-worker
  database names so two worktrees can run concurrently.
- **Classification:** `harness-drift` (shared test DB + concurrent session), NOT `product-breakage`.

## Follow-Up Stubs Created

None. No new backlog artifact was needed — the one gap found (shared-test-DB contention) is an
existing tracked note, and every plan-named gate went green.

## CONTEXT_PARTIAL Items

None.

## Closeout Packet

- **Selected plan:** `process/features/visitors-identity/active/identity-coop_07-08-26/phase-1-ledger-substrate_PLAN_07-08-26.md`
- **What was finished:** all of Steps A–G; 12 files touched; 31 new tests; both migrations written,
  offline-validated, and live round-tripped.
- **What was verified:** every Fully-Automated and every Hybrid gate in the contract (see table).
- **What is still unverified:** live apply of both migrations in a real environment (separate operator
  action); the placeholder `coop_terms_version` digest is not legally reviewed text. Nothing else —
  the integration lane was observed clean end-to-end (528/528) on a dedicated database.
- **What cleanup remains:** human APPROVE/REJECT on `harness/review-decision.json`; then archive the
  plan, mark `backlog/identity-coop-entry-gate-spec-a-live_NOTE_07-08-26.md` RESOLVED, and update the
  umbrella `## Current Execution State`.
- **Closeout classification:** **Keep in active/testing.** Code-complete and EVL-ready, but the
  high-risk evidence pack deliberately awaits a human verdict, which by the `vc-risk-evidence-pack`
  auto-stop rule means this work must not be called "ready to finalize" yet.
- **Single best next state:** human reviews `harness/` and records APPROVE/REJECT; then
  `ENTER UPDATE PROCESS MODE`.

## Forward Preview

**Test Infra Found**
- Docker 29.4.2 up; `docker compose -f infra/docker-compose.yml up -d postgres redis` works. Use
  `docker compose`, not `docker-compose`, and export
  `PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"` — note a `cd` in a compound command
  drops that PATH.
- Always `.venv/bin/python3.11 -m pytest`, never `.venv/bin/pytest` (broken shebang).
- Unit tests constructing ORM objects need `import apps.api.main` first.
- `DATABASE_URL` / `REDIS_URL` env overrides in `tests/conftest.py` are the lever for isolating a
  concurrent run onto its own database.
- Integration lane wall-clock: ~19–23 minutes. Budget for it.

**Blast Radius Changes**
- `apps/api/models/identity_coop.py` and `apps/api/services/identity_coop.py` now exist — Phase 2
  extends them rather than creating them.
- `_upsert_beam_identity` returns `bool`. Any future caller must handle that; there is still exactly
  one production caller.
- `apps/api/config.py` is CONTESTED — a concurrent IP→org program also added a block there.
- `SiteUpdate` / `SiteOut` gained `contribution_enabled`; `SiteUpdate` also gained `terms_version`.

**Commands to Stay Green**
```bash
.venv/bin/python3.11 -m pytest tests/unit -m unit -q
.venv/bin/python3.11 -m pytest tests/unit/test_identity_coop.py tests/integration/test_identity_coop_contribution.py -q
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads     # re-derive LIVE, never hardcode
git diff --stat apps/api/services/identity_resolver.py            # <= 12 changed lines
node .claude/skills/vc-risk-evidence-pack/scripts/validate-risk-artifacts.mjs \
  process/features/visitors-identity/active/identity-coop_07-08-26/harness/
```

**Dependency Changes**
- No new Python or JS dependencies.
- **Phase 2 binding constraint (D-D):** the ledger has NO `user_id` column. Phase 2's spend gate must
  aggregate across a user's sites via `identity_credit_ledger.site_id → sites.site_id → sites.user_id`
  and apply the balance at `billing.check_usage_allowed(db, user_id)` (`services/billing.py:94`).
  It MUST NOT add a `user_id` column to the now-frozen schema, and MUST NOT add a per-site monthly gate.
- **Phase 3 supersession:** E4's constant compare is a placeholder. Phase 3's `coop_terms.py` owns
  multi-version history and replaces it.
- Phase 1 wrote only layers 1–4 of the 7-layer flag wiring; the UI layers remain Phase 3's.
