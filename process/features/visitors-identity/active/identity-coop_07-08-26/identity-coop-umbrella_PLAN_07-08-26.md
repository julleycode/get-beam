---
name: plan:identity-coop-umbrella
description: "Identity Co-op — umbrella/orchestration plan for the 3-phase opt-in contribution + spendable credit ledger program"
date: 07-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
  phase: umbrella
---

# Identity Co-op — Umbrella Plan

Date: 07-08-26
Complexity: COMPLEX
Status: ⏳ PLANNED — HARD-BLOCKED on two upstream dependencies (see Sequencing)

- Program type: PHASE PROGRAM (3 phases, strictly sequential)
- Feature folder: `process/features/visitors-identity/`
- Task folder: `process/features/visitors-identity/active/identity-coop_07-08-26/`
- SPEC: `process/features/visitors-identity/active/identity-coop_07-08-26/identity-coop_SPEC_07-08-26.md`

**TL;DR** — Turn the silent cross-tenant `beam_identity_graph` into an explicit opt-in co-op:
per-site flag (default OFF) + append-only contribution log + append-only credit ledger +
self-scoped contributor dashboard. 3 phases. Every flag ships OFF. Cannot start EXECUTE until
`identity-vocab-reconcile_07-08-26` reaches PASS/descope AND SPEC A
(`graph-erasure-compliance_07-08-26`) is LIVE.

---

## Overview

Beam already pools identity matches across every customer's site with no opt-in, no visibility, and
no benefit back to the contributing site. This program makes that pooling explicit and honest: a
per-site opt-in flag (default OFF), an append-only contribution log, an append-only spendable credit
ledger, and a self-scoped contributor dashboard. Delivered as 3 strictly sequential phases, gated
behind two upstream dependencies. Every flag ships OFF; production enablement is a separate operator
action outside this program.

---

## Phased Delivery Plan

See the Phase Sequence table below. Each phase's Implementation Checklist lives in its own phase
plan file; this umbrella owns ordering, gates, and program-level state only.

---

## Program Goal Charter

```
Identity Co-op — Program Goal Charter

North star:
- Make Beam's already-existing cross-tenant identity pooling honest: a site owner explicitly
  opts in, Beam measures what they contribute and consume, and Beam pays them back in a
  spendable, auditable credit ledger.

Definition of done (all three must hold, with the program's flags still OFF):
1. A site with contribution_enabled=OFF (the default for every existing and new site)
   produces zero counted contributions and zero credit accrual, proven by test.
2. A site with contribution_enabled=ON accrues auditable ledger credit for real,
   bot-filtered, non-erased, merge-deduplicated identity contributions — and can spend that
   credit against its monthly identity-resolution allowance, with sum(ledger) == balance
   holding exactly after any randomized accrue/spend/expire sequence.
3. A site owner can see ONLY their own contribution count, consumption count, and credit
   ledger on a dashboard surface, reachable only after explicitly accepting the recorded
   contractual pass-through terms.

What "verified" means (program level):
- Every phase carries a written validate-contract (never a placeholder) plus phase evidence
  plus regression evidence against previously verified overlapping surfaces.
- Every SPEC AC assigned to a phase has a named proving gate with a strategy tag
  (Fully-Automated / Hybrid / Agent-Probe). Known-Gap is a residual, never a PASS.
- Migration work is `--sql` offline-validated with an explicit <from>:<to> range; a live
  round-trip on a disposable Postgres is required before a phase reaches ✅ VERIFIED.
- validate-contract gates must be recorded alongside phase gates and regression evidence for
  a phase to reach VERIFIED. A phase without a validate-contract (or documented skip reason)
  cannot be marked VERIFIED.

Scope tiers → phase mapping:
- Tier 1 Measurement + reciprocity substrate (tables, flag, hook, fraud gate) → Phase 1
- Tier 2 Consumption accounting + spend + expiry (read aggregation, lots, allowance wiring) → Phase 2
- Tier 3 Contributor-facing surface (stats endpoint, opt-in UX, model policy language) → Phase 3
- This program retires Tiers 1-3.

Explicitly out of scope (deferred tier):
- Enabling ANY of this program's flags in production (separate, explicit operator action).
- Retroactive purge / re-consent / re-attribution of pre-program graph rows (AC-12: permanent
  known-gap, not a bug to schedule).
- Fixing the 5-file merged-visitor double-counting gap end-to-end (kpi.py, timeseries.py,
  campaign_sender.py, segmenter.py, csv_exporter.py). This program's counter is merge-aware by
  construction; the broader gap stays in backlog.
- Any change to graph erasure mechanics (SPEC A's scope) or to identity_resolver.py §3.2
  provider vocabulary (identity-vocab-reconcile's scope).
- Cash payout / discount / any non-credit reciprocity mechanism.
- Consumption-linked accrual ("earn when your row actually helps someone") — deferred
  candidate, needs a stable resolution→graph-row pointer that does not exist.
- Legal sign-off on the pass-through contract language (hard prerequisite for production
  enablement; not satisfiable inside this program).

Hard safety constraints (non-negotiable, per phase):
- NEVER enable any new flag in a real environment. Flags ship default OFF, matching
  agent_detection_enabled / company_graph_enabled / identity_signals_enabled precedent.
- NEVER apply a migration against a live/production Postgres. Offline --sql validation with an
  explicit <from>:<to> range, plus a disposable-container round-trip, only.
- NEVER modify the pixel-facing consent banner to add cross-tenant disclosure. The pass-through
  places that obligation on the site owner (locked decision #3).
- NEVER purge, re-attribute, or retro-credit pre-program graph rows.
- NEVER log PII. structlog keys/ids only; blind index + encryption for any stored PII.
- NEVER gate graph READ access on contribution (locked decision #5). Read stays unconditional.
- NEVER begin EXECUTE while identity-vocab-reconcile_07-08-26 is Gate: BLOCKED, or while SPEC A
  graph-erasure-compliance is not LIVE.
- Commit each phase's execution changes before starting the next phase. Keep process/plan/context
  commits separate from execution commits.
```

---

## Stable Program Goal (copy-paste this to start autonomous execution)

```
SESSION GOAL: visitors-identity — Identity Co-op (opt-in contribution + spendable credit ledger)
Ref: process/features/visitors-identity/active/identity-coop_07-08-26/identity-coop-umbrella_PLAN_07-08-26.md

TARGET: Complete Phases 1→2→3 until:
- All 12 SPEC ACs are proven or explicitly recorded as known-gaps with backlog stubs
- Every phase has a written (non-placeholder) validate-contract and a green exit gate
- All program flags remain default OFF; no production enablement
- Test tiers: automated (iterate-until-green) / hybrid (fix-if-in-blast-radius) / agent-probe (record-judgment)

AUTONOMY: Before ANY subagent spawn, read:
1. Umbrella ## Current Execution State → loop step + validate-contract status
2. Phase plan ## Phase Loop Progress → first unchecked box = next subagent to spawn

PER-PHASE LOOP (7-step inner loop R → I → P → PVL → E → EVL → UP; never skip, never reorder; SKIPS SPEC):
  1. RESEARCH → 2. INNOVATE → 3. PLAN-SUPPLEMENT → 4. PVL → 5. EXECUTE → 6. EVL → 7. UPDATE-PROCESS
- PLAN-SUPPLEMENT: plan-agent writes research/innovate gaps into the phase plan (or "n/a — clean")
- PVL NEVER skipped; contract must follow example-validate-output.md full format; a partial
  contract (missing Plan updates applied / Execute-agent instructions / Test gates) = blocked
  same as placeholder
- Every subagent FIRST ACTION: run vc-context-discovery (context group files +
  process/context/tests/all-tests.md routing chain) AND vc-plan-discovery (same-feature full depth
  + other features active-only + general-plans active)
- Every phase-END: invoke vc-agent-strategy-compare for the next step's strategy

Report via phase reports. No approval between phases unless a hard stop is hit.

HARD STOPS (pause, wait for user):
- identity-vocab-reconcile_07-08-26 not PASS/descoped, OR SPEC A graph-erasure-compliance not LIVE
- Any migration apply against a non-disposable database
- Any request to flip a program flag ON
- Net gate = BLOCKED with no backlog resolution path
- Validate-contract is placeholder and vc-validate-agent cannot run

SAFETY (never override):
- Flags default OFF; no production enablement is part of any phase
- No PII in logs; blind index + encryption for stored PII
- Graph READ access stays unconditional (never gated on contribution)
- No pixel consent-banner change; no retro purge/credit of grandfathered rows
- Commit each phase before advancing; process and execution commits separate

TEST GATES (every phase exit):
  .venv/bin/python3.11 -m pytest tests/unit -m unit -q
  .venv/bin/python3.11 -m pytest tests/ -m integration -q
  alembic -c apps/api/alembic.ini heads
  alembic -c apps/api/alembic.ini upgrade <prev_head>:head --sql
  cd apps/web && npm run lint   # Phase 3 only

VALIDATE CONTRACT: Per-phase contracts written by vc-validate-agent into each phase plan before EXECUTE.

START: Phase 1, loop step RESEARCH (pending) — BLOCKED until both upstream dependencies clear.
```

---

## Hard Sequencing Constraints (read before anything else)

```
identity-vocab-reconcile_07-08-26      (PVL cycle 2, Gate: BLOCKED)
        │  must reach Gate: PASS, or be explicitly descoped
        ▼
SPEC A  graph-erasure-compliance_07-08-26
        │  must complete EXECUTE and be LIVE (not merely planned)
        ▼
THIS PROGRAM:  Phase 1 ──► Phase 2 ──► Phase 3
```

**Why the erasure ordering is non-negotiable.** Paying a site owner spendable credit for
contributed identity rows while the erasure path is still broken is a *worse* legal position
than today's silent status quo: it adds explicit consideration (strengthening the CPRA
"sale"/"share" characterization) on top of an unfixed deletion gap. Ship erasure first.

**Shared-surface claim (recorded, not blocking).**
`process/features/visitors-identity/active/identity-program_03-08-26/` Phase 1 claims
`_save_identified` with status PLANNED (never executed). This program also touches
`_save_identified`. Do not block on it — record the overlap and re-check drift at Phase 1
RESEARCH.

**Interface SPEC A publishes that this program MUST honor:**

| Requirement | Behavior |
|---|---|
| Erased-row exclusion | Contribution and consumption counting MUST exclude graph rows tombstoned via `SuppressionEntry(scope="erased")`, filtering by blind index the same way `resolve()` already does. A site must never be credited for a row that legally no longer exists. |
| Clawback — **DECIDED: NO clawback** | Already-accrued credit is NEVER reversed when a row is later erased. Rationale: clawback creates negative balances, unbounded retroactive accounting, and a spend that can be un-spent after the fact. Instead: (a) erased-derived contribution events are marked `excluded_reason='erased'` and stop counting toward displayed contribution totals going forward, and (b) no *future* accrual can reference an erased row. Recorded as a deliberate, stated asymmetry — not an oversight. |

---

## Locked Decisions (do NOT re-litigate)

| # | Decision |
|---|---|
| 1 | Reciprocity = spendable credit ledger (decrements/expires). `bonus_monthly_quota` additive bump REJECTED. |
| 2 | Opt-in defaults OFF for every site, existing and new. |
| 3 | Consent = tenant opt-in with contractual pass-through (Bombora pattern). Beam supplies model policy language. No pixel consent-banner change. |
| 4 | Existing graph rows are grandfathered — no purge, no retroactive attribution. Permanent known-gap. |
| 5 | **AC-2 resolved as model (a): read access is UNCONDITIONAL.** Any site benefits from graph-served matches regardless of contribution. Credits are a reward, not a toll. |

---

## PLAN-Level Numeric Decisions (stated explicitly, per SPEC "Out of Scope")

| Parameter | Value | Rationale |
|---|---|---|
| Accrual rate | **1 credit per qualifying contribution event** | Per-row-contributed (not consumption-linked). One event = one `(site_id, email_bidx, day)` tuple that passed the fraud gate. |
| Exchange rate | **1 credit = 1 identity resolution unit added to the site's monthly allowance (`monthly_limit`)** | Credits extend the MONTHLY allowance. They do NOT raise `Site.daily_resolution_budget` — raising the daily cap would change the abuse blast-radius math the P3 ingest-ceiling work exists to bound. |
| Expiry window | **90 days from accrual** | Lot-based FIFO. Each accrual row carries its own `expires_at`; unexpired lots are filtered at read time; a sweep writes an explicit `EXPIRE` ledger entry when a lot lapses. |
| Provisional hold | **24 hours before a credit lot becomes spendable** | Gives the batch `cadence_bot_flag` sweep time to catch slow bot patterns that `is_abuse_flagged` misses at write time. |
| Accrual policy | **Per-row-contributed** | Consumption-linked accrual deferred (needs a stable `api_usage_logs` → graph-row pointer that does not exist; building it reintroduces read-path write surface). |

---

## Corrected Research Fact (INNOVATE named the wrong table — verified 07-08-26)

INNOVATE stated consumption is already recorded in `resolution_logs`. **That is wrong.**
Verified by direct read of `apps/api/services/identity_resolver.py`:

- `_log_owned_resolution(visitor, provider)` (~`identity_resolver.py`, in the Save+Log block)
  calls `log_api_call(...)` → writes an **`ApiUsageLog` row into `api_usage_logs`**, with
  `provider='beam_identity_network'`, `category='identity'`, `cost_usd=0.0`, `success=True`.
- `_log_resolution(...)` is the one that writes `ResolutionLog` into `resolution_logs` (paid
  providers), and separately mirrors into `api_usage_logs`.
- `beam_identity_network ∈ OWNED_FREE_PROVIDERS` (`apps/api/services/identity_classification.py`)
  — confirmed, so the owned-log branch fires for every graph-served identification.

**Conclusion unchanged, table corrected:** consumption measurement still needs **zero new write
surface** — it is a read-only aggregation over **`api_usage_logs`** (NOT `resolution_logs`)
filtered on `provider='beam_identity_network' AND category='identity'`. Every phase plan below
uses the corrected table.

---

## Phase Sequence

| Phase | Plan file | Scope summary | Depends on |
|---|---|---|---|
| 0 (pre-program) | this file | Program artifacts created; upstream dependency status confirmed | — |
| 1 — Ledger + contribution substrate | `.../identity-coop_07-08-26/phase-1-ledger-substrate_PLAN_07-08-26.md` | 3 new tables, `Site.contribution_enabled` (7-layer), 2-line hook at `_save_identified`, `identity_coop.py` service, fraud gate on `is_abuse_flagged`, erased-row exclusion. No dashboard. | vocab-reconcile PASS + SPEC A LIVE |
| 2 — Consumption aggregation + spend | `.../identity-coop_07-08-26/phase-2-consumption-spend_PLAN_07-08-26.md` | Read-only consumption aggregation over `api_usage_logs`, FIFO lot expiry sweep, spend-against-`monthly_limit` wiring, AC-8 exact-reconciliation test. | Phase 1 exit gate |
| 3 — Contributor surface + opt-in UX | `.../identity-coop_07-08-26/phase-3-contributor-surface_PLAN_07-08-26.md` | Self-scoped stats endpoint, opt-in prompt + model policy language + acceptance flow, dashboard visibility. | Phase 2 exit gate |

### Join Conditions

- Phase 1 MUST NOT start until BOTH upstream dependencies clear (vocab-reconcile PASS/descoped, SPEC A LIVE).
- Phase 2 MUST NOT start until Phase 1 exit gate passes (tables + hook + accrual proven).
- Phase 3 MUST NOT start until Phase 2 exit gate passes (a stats surface with no spend/expiry behind it would show numbers that later change meaning).

---

## SPEC AC → Phase Coverage Map

| AC | Requirement | Phase | Strategy | Notes |
|---|---|---|---|---|
| AC-1 | Opt-in flag defaults OFF, gates all NEW contribution | 1 | Fully-Automated | Integration test: flag OFF ⇒ zero counted contributions across a resolve cycle |
| AC-2 | Non-contributor read access explicitly decided | 1 | Fully-Automated | **Model (a) chosen (locked #5).** Test asserts a non-contributing site STILL receives graph-served identifications |
| AC-3 | Contribution countable per site, merge-aware | 1 | Fully-Automated | Unique key `(site_id, email_bidx, day)` dedupes merged duplicates structurally |
| AC-4 | Consumption countable, graph-served vs provider-purchased | 2 | Fully-Automated | Aggregation over `api_usage_logs` (corrected table), `provider='beam_identity_network'`, `cost_usd=0.0` |
| AC-5 | Credits accrue on verified contribution | 1 | Fully-Automated | One qualifying event ⇒ one positive ledger row (site_id, reason, timestamp, expires_at) |
| AC-6 | Credits spendable against resolution cost | 2 | Fully-Automated | Spend decrements FIFO lots; writes a `SPEND` ledger row; targets `monthly_limit` |
| AC-7 | Credits expire per stated policy | 2 | Fully-Automated | 90-day lot; read-time filter + explicit `EXPIRE` ledger entry from the sweep |
| AC-8 | Ledger auditable and reconcilable | 2 | Fully-Automated | `sum(ledger events) == spendable balance` after a randomized accrue/spend/expire sequence |
| AC-9 | Fraud resistance: no credit from synthetic/bot traffic | 1 | Fully-Automated | Accrual gated on `visitor.is_abuse_flagged is False`; contribution EVENT still logged. Residual: `cadence_bot_flag` batch lag → 24h provisional hold |
| AC-10 | Opt-in requires explicit acceptance of pass-through | 3 | Hybrid | Automated: flag cannot be set ON via API without an acceptance row in the same transaction. Agent-Probe: legal/human review of model policy copy |
| AC-11 | Contributor stats surface is self-scoped only | 3 | Fully-Automated | Site A auth ⇒ only Site A numbers; foreign site_id ⇒ 404 (never 403) |
| AC-12 | Grandfathered rows excluded from new accounting | 1 | Fully-Automated | Pre-existing `beam_identity_graph` rows have no contribution-event row ⇒ contribute 0 |

Every AC is covered. None deferred.

---

## Per-Phase Entry / Exit Gates

| Phase | Entry | Exit gate |
|---|---|---|
| 0 | Program start | Umbrella + 3 phase plans + blast-radius registry written; validators exit 0 |
| 1 | vocab-reconcile PASS/descoped AND SPEC A LIVE | 3 migrations offline-validated + disposable round-trip; unit + integration lanes green; AC-1/2/3/5/9/12 tests pass; flag default OFF proven |
| 2 | Phase 1 exit met | AC-4/6/7/8 tests pass, including the randomized reconciliation property test; expiry sweep proven idempotent; no new write surface added to the read path |
| 3 | Phase 2 exit met | AC-10/11 tests pass; `cd apps/web && npm run lint` clean; model policy language drafted and Agent-Probe-reviewed; stats endpoint returns 404 for foreign site_id |

---

## Per-Phase Loop

Each phase executes the canonical 7-step inner loop `R → I → P → PVL → E → EVL → UP`. This inner
loop SKIPS SPEC — SPEC runs once in the outer program loop, not per phase.

1. **RESEARCH** — research-agent: load context, read prior phase reports, check plan drift (especially `identity_resolver.py` drift from the two concurrent workstreams), document findings
2. **INNOVATE** — innovate-agent: decide approach; write Decision Summary (chosen + rejected)
3. **PLAN-SUPPLEMENT** — plan-agent: add gaps/pre-conditions found in 1-2 to this phase plan, or mark "n/a — research clean"
4. **PVL** — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md`
5. **EXECUTE** — vc-execute-agent per approved plan and validate-contract
6. **EVL** — vc-tester: run phase test gates to green; register follow-up stubs; write EVL HANDOFF SUMMARY
7. **UPDATE-PROCESS** — write phase report; rewrite umbrella `## Current Execution State` (overwrite, not append)

**PVL is NEVER skipped.** A placeholder `## Validate Contract` = blocked.

---

## Autonomous Execution Rules (During /goal)

- Agent self-decides at all V5 gates — no user approval needed between phases.
- CONDITIONAL net gate: proceed autonomously, fixes applied in-flight, gaps on record.
- BLOCKED net gate: document items in backlog, continue with remaining phase plans.
- Hard stops (must pause for user): upstream dependency not clear; any migration apply against a
  non-disposable DB; any request to flip a program flag ON; plan marks "pause required".
- The phase report is the communication channel for conflicts, errors, and learnings.

---

## Global Constraints

- Migrations chain onto the TRUE current head at execute time — run
  `alembic -c apps/api/alembic.ini heads` LIVE. Never hardcode a head. As of 07-08-26 the recorded
  head is `e6b2d4a1c837` with 13 pending live-apply migrations, and the chain has moved repeatedly
  under concurrent work.
- Offline `--sql` validation MUST use an explicit `<from>:<to>` range. Unscoped
  `alembic upgrade head --sql` fails mid-chain because `b7d3e9f1a4c2_add_ad_connections.py` calls
  `sa.inspect(bind)`, unsupported against alembic's offline `MockConnection`.
- Flags default OFF in `apps/api/config.py`, matching `agent_detection_enabled` /
  `company_graph_enabled` / `identity_signals_enabled` / `referrals_enabled`.
- Every external call needs a `MOCK_EXTERNAL_APIS=true` path.
- Multi-tenancy: every user-facing query filters `Site.user_id == user.id`; foreign ids → 404,
  never 403.
- PII: never log PII; structlog keys/ids only. Blind index + encryption for stored PII. Contribution
  events key on `email_bidx` (blind index), NEVER plaintext email.
- Python 3.11 type-hint syntax only. Async for all I/O. structlog, never `print()`.
- `apps/api/services/identity_coop.py` MUST NOT create a circular import back into
  `identity_resolver.py` at module-load time. Plain function call, no shared state, import inside
  the calling function if needed (matching the `_log_owned_resolution` local-import precedent).
- `.venv/bin/pytest` has a broken shebang — always use `.venv/bin/python3.11 -m pytest`.
- Describe the hook insertion point by CALL-GRAPH POSITION ("immediately after the
  `_upsert_beam_identity` call inside `_save_identified`"), never by line number. Two concurrent
  workstreams are rewriting this file.
- Commit each phase's execution changes before starting the next phase.

---

## Durable Report Destinations

| Phase | Report path (flat, inside the program task folder) |
|---|---|
| 0 (pre-program) | `process/features/visitors-identity/active/identity-coop_07-08-26/phase-0-program-setup_REPORT_07-08-26.md` |
| 1 — Ledger substrate | `process/features/visitors-identity/active/identity-coop_07-08-26/phase-1-ledger-substrate_REPORT_07-08-26.md` |
| 2 — Consumption + spend | `process/features/visitors-identity/active/identity-coop_07-08-26/phase-2-consumption-spend_REPORT_07-08-26.md` |
| 3 — Contributor surface | `process/features/visitors-identity/active/identity-coop_07-08-26/phase-3-contributor-surface_REPORT_07-08-26.md` |

---

## Program Status Table

| Phase | Status |
|---|---|
| 0 — Pre-program (plan creation) | ✅ COMPLETE |
| 1 — Ledger + contribution substrate | ⏳ PLANNED (blocked on upstream) |
| 2 — Consumption aggregation + spend | ⏳ PLANNED |
| 3 — Contributor surface + opt-in UX | ⏳ PLANNED |

Status values: ⏳ PLANNED | 🔨 CODE DONE | 🧪 TESTING | ✅ VERIFIED | 🚧 BLOCKED | ✅ COMPLETE

---

## Touchpoints

- `apps/api/models/identity_coop.py` (NEW — 3 models: contribution event, credit ledger entry, consent acceptance) — Phase 1
- `apps/api/services/identity_coop.py` (NEW — all co-op logic) — Phases 1, 2
- `apps/api/services/identity_resolver.py` (~2-line hook inside `_save_identified`) — Phase 1
- `apps/api/models/site.py` (`contribution_enabled` column) — Phase 1
- `apps/api/config.py` (`identity_coop_enabled` + numeric settings) — Phase 1
- `apps/api/alembic/versions/` (3 migrations across Phases 1-2) — Phases 1, 2
- `apps/api/schemas/sites.py`, `apps/api/routers/sites.py` — Phases 1, 3
- `apps/api/services/billing.py` (`monthly_limit` credit extension) — Phase 2
- `apps/api/tasks/` (expiry sweep job) — Phase 2
- `apps/api/routers/identity_coop.py` (NEW — stats endpoint) — Phase 3
- `apps/web/src/app/dashboard/visitors/page.tsx`, `apps/web/src/lib/api-types.ts`, `apps/web/src/lib/api.ts` — Phase 3
- `tests/unit/test_identity_coop*.py`, `tests/integration/test_identity_coop*.py` — all phases

---

## Public Contracts

- `beam_identity_graph` read behavior is UNCHANGED — read access stays unconditional for every
  site (locked decision #5, AC-2 model (a)).
- `_save_identified` return type and existing side effects are UNCHANGED. The hook is additive and
  best-effort (a co-op failure must never break a successful identification).
- `api_usage_logs` and `resolution_logs` write paths are UNCHANGED — consumption is read-only.
- Beam's pixel-facing consent banner is UNCHANGED.
- `PATCH /api/v1/sites/{site_id}` gains one additive boolean field; existing fields unchanged.
- `GET /api/v1/sites/{site_id}/coop-stats` is NEW (Phase 3), shaped after the existing
  `GET /api/v1/sites/{site_id}/ingest-health` precedent: tenant-scoped, counts only, zero PII.

---

## Blast Radius

Risk class: **billing/credits + schema/migration + multi-tenancy**. All three are high-risk
classes requiring at minimum a Hybrid test gate per phase.

- 3 new Alembic migrations (Phases 1-2)
- 3 new tables + 1 new `sites` column
- 2 new backend modules (`models/identity_coop.py`, `services/identity_coop.py`) + 1 new router
- ~2 modified lines inside `identity_resolver.py` (contested file — 2 concurrent workstreams)
- 1 modified billing surface (`monthly_limit` allowance computation)
- 3 modified web files (Phase 3)
- ~14-18 files total across the program

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` exits 0 | Fully-Automated | AC-3, AC-7, AC-8, AC-12 |
| `.venv/bin/python3.11 -m pytest tests/ -m integration -q` exits 0 | Fully-Automated | AC-1, AC-2, AC-4, AC-5, AC-6, AC-9, AC-11 |
| `alembic -c apps/api/alembic.ini heads` returns a single head; new migrations chain onto it | Fully-Automated | Migration-currency constraint |
| `alembic -c apps/api/alembic.ini upgrade <prev_head>:head --sql` exits 0 (explicit range) | Fully-Automated | Migration-currency constraint |
| Disposable-Postgres round-trip: `upgrade head` → `downgrade -1` → `upgrade head` | Hybrid (precondition: disposable container) | Schema/migration high-risk class |
| API: flag cannot be set ON without an acceptance row in the same transaction | Fully-Automated | AC-10 (automated leg) |
| Legal/human review of model policy + acceptance copy | Agent-Probe | AC-10 (judgment leg) |
| `cd apps/web && npm run lint` exits 0 | Fully-Automated | Phase 3 web surface |

---

## Test Infra Improvement Notes

(none identified yet)

---

## Risks (including one dissent, recorded once and then planned around)

| Risk | Handling |
|---|---|
| **Dissent on locked decision #1** — a spendable credit ledger makes the "valuable consideration" explicit and strengthens the CPRA "sale"/"share" characterization more than an additive quota bump would have. Recorded once as required; the program is planned with the credit ledger regardless. | Legal review is a stated hard prerequisite for production enablement (Charter, out-of-scope). Flags ship OFF. |
| `identity_resolver.py` three-way collision (this program + vocab-reconcile + identity-program Phase 1) | Hook described by call-graph position, never line number. ~2-line diff footprint. Phase 1 RESEARCH re-checks drift before EXECUTE. |
| `cadence_bot_flag` is a batch sweep — a site could farm credit before a slow bot pattern is flagged | 24-hour provisional hold before a credit lot becomes spendable. Residual gap recorded. |
| Erased-row asymmetry (no clawback) could be read as crediting deleted data | Deliberate and stated: no future accrual references an erased row; erased-derived events are marked and drop out of displayed totals. Recorded, not hidden. |
| Merged-visitor double-counting (5-file backlog gap) | This program's counter is structurally merge-immune via the `(site_id, email_bidx, day)` unique key. The broader 5-file gap stays in backlog, unchanged. |
| Joint-controllership exposure under GDPR Art. 26 | Flagged for the same legal review as AC-10. Not resolvable in code. |
| Grandfathered rows have no consent trail | Permanent known-gap (AC-12). Stated, not scheduled. |

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/visitors-identity/active/identity-coop_07-08-26/identity-coop-umbrella_PLAN_07-08-26.md`
- Last completed phase: Phase 0 (this umbrella plan + 3 phase plans + blast-radius registry)
- Validate-contract status: pending (vc-validate-agent writes per-phase)
- Supporting context files loaded: `process/context/all-context.md`, `process/context/tests/all-tests.md`, `identity-coop_SPEC_07-08-26.md`, `backlog/merged-visitor-consumer-awareness_NOTE_04-08-26.md`, direct reads of `identity_resolver.py`, `identity_classification.py`, `models/beam_identity.py`, `models/site.py`, `models/visitor.py`, `services/usage_logger.py`
- Current phase: Phase 1 (blocked)
- Next step for a fresh agent: confirm both upstream dependencies have cleared. If not cleared, do
  NOT spawn any Phase 1 agent — report BLOCKED. If cleared, spawn vc-research-agent for Phase 1
  with `phase-1-ledger-substrate_PLAN_07-08-26.md`.
- Execute-agent start instruction: Read this file. Read the Phase 1 plan. Run the Phase 1 research
  subagent first. Never EXECUTE from this umbrella file directly.

---

## Current Execution State

Last updated: 07-08-26
Completed phases: Phase 0 (Planning)
Current phase: Phase 1 — Ledger + contribution substrate
Current phase status: ⏳ PLANNED — **BLOCKED on two upstream dependencies**
  1. `identity-vocab-reconcile_07-08-26` — PVL cycle 2, `Gate: BLOCKED`; must reach PASS or be descoped
  2. SPEC A `graph-erasure-compliance_07-08-26` — must complete EXECUTE and be LIVE, not merely planned
Current loop step: RESEARCH (pending, gated)
Validate-contract status: pending — none written for any phase
Program Net Gate: PENDING
Latest validator run: 07-08-26 — see Phase 0 report

Loop step values: RESEARCH | INNOVATE | PLAN-SUPPLEMENT | PVL | EXECUTE | EVL | UPDATE-PROCESS
Orchestrator rule: read "Current loop step" and "validate-contract status" before spawning any
subagent. Never spawn execute-agent when loop step is RESEARCH, INNOVATE, PLAN-SUPPLEMENT, or PVL.

Note: The Stable Program Goal above is fixed. This section is the only part that changes —
update-process-agent rewrites it after every phase closeout (overwrite, not append).

---

## Pre-PVL Conflict Resolution

(placeholder — the orchestrator fills this before outer PVL begins. Must classify each shared
package as `parallel-safe` or `reassign` with the winning phase named, or state explicitly:
"No package conflicts — all phases are parallel-safe.")

Candidate conflict surfaces already known at plan time:
- `apps/api/services/identity_coop.py` — written in Phase 1, extended in Phase 2
- `apps/api/routers/sites.py` — touched in Phase 1 (flag) and Phase 3 (acceptance flow)
- `apps/api/models/identity_coop.py` — created in Phase 1, read-only thereafter

---

## Phase Ordering

1. Phase 1 — Ledger + contribution substrate
2. Phase 2 — Consumption aggregation + spend
3. Phase 3 — Contributor surface + opt-in UX

Strictly sequential. No phase may run in parallel with another: Phase 2's spend logic depends on
Phase 1's ledger schema, and Phase 3's stats surface depends on Phase 2's balance semantics.

---

## Phase Loop Progress

- [x] Phase 0 — program artifacts created
- [ ] Phase 1 — Ledger + contribution substrate
- [ ] Phase 2 — Consumption aggregation + spend
- [ ] Phase 3 — Contributor surface + opt-in UX

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
