---
name: plan:site-limit-enforcement
description: "Enforce per-plan website (Site) count limits at POST /sites/, matching the pricing page (free 1 / pro 3 / max unlimited)"
date: 26-07-26
feature: billing
---

# PLAN — Per-Plan Site Limit Enforcement (SIMPLE)

**Date**: 26-07-26
**Status**: PLANNED (validate-contract written; awaiting EXECUTE approval)
**Complexity**: SIMPLE

TL;DR: add `PLAN_SITE_LIMITS` + `get_site_limit()` to `services/billing.py`, count the user's sites in `create_site` *after* the dedup return, raise 402 with structured detail, surface an upgrade CTA in onboarding. ~5 files, 1 new unit test file, no migration, no env vars.

Spec: `site-limit-enforcement_SPEC_26-07-26.md` (same folder).

## Context Envelope

| # | Field | Value |
|---|---|---|
| 1 | feature | billing |
| 2 | phase | PLAN → VALIDATE |
| 3 | session-goal | Enforce per-plan website limits at site creation |
| 4 | branch | main |
| 5 | worktree | main |
| 6 | context-group | tests, planning |
| 7 | blast-radius-packages | apps/api (billing service, sites router), apps/web (onboarding page), tests/unit |
| 8 | active-plan | this file |
| 9 | test-runner | pytest (unit) \| pytest (integration) |
| 10 | validate-contract | see §Validate Contract below |

## Approach (locked)

Mirror the existing quota pattern exactly: a `PLAN_*` dict + a `get_*` helper in `services/billing.py`, read at the call site through the already-canonical `get_effective_plan()` derivation. No new abstractions, no flag, no schema change.

## Acceptance Criteria

- AC1 — Free user with 1 site POSTing a new URL → 402 `site_limit_reached`; site count unchanged.
- AC2 — Same user re-POSTing an owned URL at/over limit → 200 with the existing site (dedup unaffected).
- AC3 — Pro blocked at 3 sites; `max` never blocked.
- AC4 — Limits live in one place (`apps/api/services/billing.py`) and match the pricing page.
- AC5 — Effective plan derived via the existing `get_effective_plan(user.plan, user.current_period_end)`.
- AC6 — Count query scoped to `Site.user_id == user.id`.
- AC7 — Onboarding create-site flow renders the message + a `/pricing` upgrade link.
- AC8 — Unit tests green for: at limit, under limit, dedup bypass, unlimited tier, grandfathered over-limit, unknown plan key, lapsed paid plan.

## Phase Completion Rules

Single-phase plan. It is complete only when: all 7 checklist items are applied, every gate in Verification Evidence has been run (or explicitly recorded as a known-gap with reason), and the accepted gaps below are unchanged. Code-only completion is `CODE DONE`, never `VERIFIED` — `VERIFIED` requires the hybrid integration gate to have actually run against Postgres.

## Touchpoints

| File | Change |
|---|---|
| `apps/api/services/billing.py` | ADD `PLAN_SITE_LIMITS` dict + `get_site_limit(plan) -> Optional[int]` (read) |
| `apps/api/routers/sites.py` | EDIT `create_site` — count check after dedup, before `Site(...)` construction |
| `apps/web/src/app/dashboard/onboarding/page.tsx` | EDIT `handleCreate` catch — render upgrade CTA when the error is a site-limit block |
| `apps/web/src/lib/api.ts` | EDIT `request()` error path — preserve structured `detail` objects (currently stringifies to `[object Object]`) |
| `tests/unit/test_site_limit.py` | NEW — helper + router-level limit behavior |
| `apps/api/models/site.py` | READ only (no change) |
| `apps/web/src/app/pricing/page.tsx` | READ only — source of truth for the numbers |

## Public Contracts

**Changed:** `POST /api/v1/sites/` gains a new failure mode.

```
HTTP 402 Payment Required
{
  "detail": {
    "code": "site_limit_reached",
    "message": "Your Free plan includes 1 website. Upgrade to add more.",
    "plan": "free",
    "limit": 1,
    "current_count": 1,
    "upgrade_url": "/pricing"
  }
}
```

- `402` chosen over `403`: `403` is already used in `dependencies.py` for admin-gating, and the paywall semantics are clearer for the frontend switch. `401` is the only status the web client special-cases, so `402` passes through the generic `!res.ok` branch cleanly.
- `detail.message` is a human-readable string so any caller that naively renders `detail` still degrades gracefully once `api.ts` is fixed.
- New exported symbols: `billing.PLAN_SITE_LIMITS`, `billing.get_site_limit`.
- Unchanged: `GET /sites/`, dedup 200 path, cross-user 409 path, `SiteOut` schema.

## Blast Radius

- **Files:** 6 (4 edited, 1 new test, 1 read-only reference).
- **Packages:** `apps/api` (2 modules), `apps/web` (2 modules), `tests/unit` (1 new).
- **Risk class:** billing/credits (HIGH) — entitlement gating on a revenue surface.
- **Data:** none. No migration, no column, no backfill, no deletion. Existing rows untouched.
- **Runtime:** one extra `SELECT count(*)` per site-creation request (rare path, indexed on `user_id`).
- **Downstream consumers:** onboarding page is the only caller of `api.createSite` (verified by grep — 1 call site). Playwright `onboarding` spec exercises this flow.

## Implementation Checklist

1. **`apps/api/services/billing.py`** — after `PLAN_LIMITS`, add:
   - `PLAN_SITE_LIMITS: dict[str, Optional[int]] = {"free": 1, "pro": 3, "max": None}` with a comment pointing at `apps/web/src/app/pricing/page.tsx` as the copy that must stay in sync.
   - `def get_site_limit(plan: str) -> Optional[int]: return PLAN_SITE_LIMITS.get(plan, 1)` — unknown key falls back to the most restrictive tier, mirroring `get_plan_limits`' fallback-to-free posture. Docstring must state `None = unlimited`.
2. **`apps/api/routers/sites.py`** — import `get_effective_plan`, `get_site_limit` from `apps.api.services.billing`; import `func` from `sqlalchemy`.
3. **`create_site`** — insert the check *immediately after* the `if existing:` block returns (so both the 409 and the dedup-200 paths short-circuit first) and *before* `site = Site(...)`:
   - `effective_plan = get_effective_plan(user.plan, user.current_period_end)`
   - `limit = get_site_limit(effective_plan)`
   - `if limit is not None:` → `count = (await db.execute(select(func.count()).select_from(Site).where(Site.user_id == user.id))).scalar_one()`
   - `if count >= limit:` → `logger.info("site_limit_blocked", user_id=str(user.id), plan=effective_plan, limit=limit, current_count=count)` then `raise HTTPException(status_code=402, detail={...})` per the Public Contracts shape. Note `>=` (not `>`) is what makes grandfathered over-limit users blocked-but-intact.
4. **`apps/web/src/lib/api.ts`** (~line 174) — in the `!res.ok` branch, when `body.detail` is a non-null object, throw `new Error(body.detail.message || \`Request failed: ${res.status}\`)` and attach the raw object (e.g. `Object.assign(err, { detail: body.detail })`) so callers can branch on `detail.code`. String `detail` behavior unchanged.
5. **`apps/web/src/app/dashboard/onboarding/page.tsx`** `handleCreate` catch — if the thrown error carries `detail.code === "site_limit_reached"`, set an upgrade-flavored error state that renders the `message` plus a link to `/pricing` ("View plans"). Otherwise keep the existing generic message. Keep it minimal — reuse the existing `error` state and add one conditional link; do not add a modal.
6. **`tests/unit/test_site_limit.py`** — NEW, `pytestmark = pytest.mark.unit`. Cases:
   - `get_site_limit` returns 1 / 3 / None for free / pro / max, and 1 for `"enterprise"` (unknown key).
   - `PLAN_SITE_LIMITS` keys are a subset of `PLAN_LIMITS` keys (drift guard against a renamed tier).
   - Router behavior with a stubbed `AsyncSession` (mirror the mocking style in existing unit router tests): under limit → creates; at limit → 402 with `detail["code"] == "site_limit_reached"`; dedup path at limit → returns existing, never reaches the count query; unlimited plan → no count query issued; grandfathered `count > limit` → blocked with the true `current_count`.
   - Lapsed paid plan (`plan="pro"`, `current_period_end` in the past) → limit resolves to 1 via `get_effective_plan`.
7. Run the verification gates below.

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `.venv/bin/python3.11 -m pytest tests/unit/test_site_limit.py -q` | Fully-Automated | AC1, AC2, AC3, AC4, AC5, AC8 |
| `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` (no regressions) | Fully-Automated | AC4 (no collateral break in billing helpers) |
| `.venv/bin/python3.11 -m pytest tests/integration/test_site_delete.py -q` (nearest existing site-router integration) | Hybrid — precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis` | AC6 (real user-scoped query against Postgres) |
| `cd apps/web && npm run lint` | Fully-Automated | AC7 compiles/lints |
| Manual: free user at limit → onboarding shows message + `/pricing` link | Agent-Probe | AC7 |

Failing stubs (red-first, for the fully-automated rows):

```
def test_get_site_limit_matches_pricing_page():
    raise AssertionError("NOT IMPLEMENTED — TDD stub for: free=1, pro=3, max=None")

def test_create_site_blocked_at_limit_returns_402_site_limit_reached():
    raise AssertionError("NOT IMPLEMENTED — TDD stub for: at-limit create is blocked")

def test_create_site_dedup_bypasses_limit():
    raise AssertionError("NOT IMPLEMENTED — TDD stub for: dedup returns existing at/over limit")
```

## Test Infra Improvement Notes

- No existing unit-lane fixture for router functions with a stubbed `AsyncSession`; the new test file may need a small local helper. If it grows beyond ~20 lines, note it for promotion to `tests/conftest.py` in the phase report.
- No e2e coverage for billing surfaces (known repo gap, `tests/all-tests.md`). Not closed by this plan.

## Known Gaps / Accepted Risks

| Gap | Decision |
|---|---|
| Concurrent double-create can yield limit+1 | ACCEPTED. Small tiers, no revenue loss, self-healing on next block. Documented, not silently ignored. A serializable txn / advisory lock is disproportionate. |
| Downgrade (pro→free) leaves the user over limit | ACCEPTED and intentional — grandfathering (SPEC out-of-scope). Only new creates are blocked. |
| Pricing-page copy and `PLAN_SITE_LIMITS` are two sources that must be kept in sync manually | Mitigated by a code comment + the drift-guard test; a shared constant across Python/TS is out of scope. |
| Integration test for the 402 path not written (unit-only) | ACCEPTED — the count query shape is exercised by the existing site-router integration suite; the branch logic is fully unit-covered. |

## Resume and Execution Handoff

1. **Selected plan:** `/Users/apple/getbeam/process/features/billing/active/site-limit-enforcement_26-07-26/site-limit-enforcement_PLAN_26-07-26.md`
2. **Last completed step:** VALIDATE complete (contract below). No code written.
3. **Validate-contract status:** written (26-07-26).
4. **Context loaded:** `process/context/all-context.md`, `process/context/tests/all-tests.md`, `apps/api/services/billing.py`, `apps/api/routers/sites.py`, `apps/api/routers/billing.py`, `apps/web/src/app/pricing/page.tsx`, `apps/web/src/lib/api.ts`, `apps/web/src/app/dashboard/onboarding/page.tsx`.
5. **Next step for a fresh agent:** start at Implementation Checklist item 1. Write the failing stubs first (item 6 scaffolding), then implement 1→5, then run the gates.

## Validate Contract

```yaml
generated-by: outer-pvl
date: 2026-07-26
plan: process/features/billing/active/site-limit-enforcement_26-07-26/site-limit-enforcement_PLAN_26-07-26.md
gate: CONDITIONAL
risk-class: billing/credits
mode: deep
```

### V1 — Pre-check

Plan file exists; Touchpoints / Public Contracts / Blast Radius / Verification Evidence / Test Infra Improvement Notes / Resume-Handoff all present. No prior `## Inner Loop Refresh Note`. PASS.

### V2/V3 — Two-layer findings

**Layer 1 dimensions**

| Dimension | Status | Findings |
|---|---|---|
| Infra fit | PASS | No migration, no env var, no container/worker surface. Edit targets verified present: `PLAN_LIMITS` at `services/billing.py:15`, `create_site` at `routers/sites.py:50`, `!res.ok` branch at `api.ts:174`, `handleCreate` catch at `onboarding/page.tsx:87`. `func` not yet imported in `sites.py` — checklist item 2 covers it. |
| Test coverage | CONCERN | Unit lane covers all branch logic; the real `select(func.count())` SQL is only exercised indirectly. Mitigated by reusing the existing integration site suite as a smoke gate. `.venv/bin/pytest` shebang is broken — gates correctly use `.venv/bin/python3.11 -m pytest`. |
| Breaking changes | CONCERN | New 402 failure mode on an existing endpoint. Only one consumer (`api.createSite`, 1 call site). The `api.ts` object-detail fix (item 4) touches the SHARED error path for every endpoint — must preserve string-`detail` behavior exactly or every other error message regresses. Flagged as the highest-risk edit. |
| Security surface | PASS | Count query is `user_id`-scoped (multi-tenancy pattern honored). No PII in the error body or the log line (ids/keys only). Enforcement is additive-restrictive: failure mode is "cannot create", never "can create more". No auth path touched. |

**Layer 2 sections**

| Section | Status | Notes |
|---|---|---|
| billing.py helper | PASS | Mechanically trivial; mirrors `get_plan_limits`. Plan keys `free`/`pro`/`max` verified against live `PLAN_LIMITS`, not assumed. |
| sites.py create_site | PASS | Ordering constraint (dedup/409 before count check) is explicit in item 3. `>=` vs `>` called out. Highest-risk edit here is placement — an insertion above the `if existing:` block would break AC2. |
| api.ts error path | CONCERN | Shared blast radius across all API calls. Mitigation: guard on `typeof body.detail === "object" && body.detail !== null`; leave the string branch byte-identical. |
| onboarding UI | PASS | Single call site; existing `error` state reused. |
| tests | CONCERN | No existing unit-lane precedent for stubbing `AsyncSession` at router level; if stubbing proves awkward, promote the at-limit/dedup cases to `tests/integration/test_site_limit.py` rather than dropping them. |

**Totals: 0 FAILs / 4 CONCERNs / 5 PASSes → Net Gate: CONDITIONAL**

### V4 — Strategy

Sequential, one `vc-execute-agent` (opus). Score 2/7 (S2 API surface, S6 billing high-risk). 6 files, one coherent change; fan-out would add coordination cost with no parallelism benefit.

### Execute-agent instructions

| # | Instruction | Trigger |
|---|---|---|
| E1 | Insert the limit check strictly AFTER the `if existing:` block returns. Re-read `create_site` before editing; if line numbers drifted, anchor on `site = Site(` and insert above it. | sites.py edit |
| E2 | In `api.ts`, only add an object-detail branch. Do NOT alter the string-`detail` path or the 401 branch. Re-run `npm run lint` and one unrelated failing-request path mentally before finishing. | api.ts edit |
| E3 | Use `>=` for the block comparison. A `>` would let grandfathered users add one more site. | sites.py edit |
| E4 | Read `PLAN_LIMITS` keys at edit time and key `PLAN_SITE_LIMITS` off the same strings. Do not hardcode assumed tier names. | billing.py edit |
| E5 | Write the three failing stubs first, confirm red, then implement. | test file |
| E6 | If the integration gate cannot run (Docker down), record it as a known-gap in the phase report — do not silently skip. | verification |

### Test gates (EVL commands)

```
.venv/bin/python3.11 -m pytest tests/unit/test_site_limit.py -q
.venv/bin/python3.11 -m pytest tests/unit -m unit -q
cd apps/web && npm run lint
# hybrid (precondition: docker compose -f infra/docker-compose.yml up -d postgres redis)
.venv/bin/python3.11 -m pytest tests/integration/test_site_delete.py -q
```

### Accepted gaps (CONDITIONAL)

1. No dedicated integration test for the 402 path (unit-covered branch logic + existing integration smoke).
2. Concurrency race accepted (see Known Gaps).
3. Pricing copy ↔ backend constant sync is manual, guarded by comment + drift test.
4. No e2e for billing surfaces (pre-existing repo gap).
