---
name: spec:site-limit-enforcement
description: "Enforce per-plan website (Site) count limits at site creation, matching pricing page promises"
date: 26-07-26
feature: billing
---

# SPEC — Per-Plan Site Limit Enforcement

TL;DR: the pricing page sells 1 / 3 / unlimited websites per tier; the backend enforces nothing. Add a count check at `POST /api/v1/sites/` only.

## Goal

Backend enforcement of the website-count entitlement already advertised on `/pricing`, so free-tier users cannot create unlimited sites.

## Use Cases

| # | Actor | Scenario | Expected |
|---|---|---|---|
| U1 | Free user with 1 site | POST a new URL | 4xx, structured upsell detail, no site created |
| U2 | Free user at/over limit | POST a URL they already own | 200, existing site returned (dedup unaffected) |
| U3 | Pro user with 3 sites | POST a new URL | blocked |
| U4 | Max user with 50 sites | POST a new URL | allowed (unlimited) |
| U5 | Grandfathered free user with 4 sites | existing sites | all keep working; only new creates blocked |
| U6 | Any user | receives block | dashboard/onboarding shows readable message + upgrade CTA to `/pricing` |

## Limits (from `apps/web/src/app/pricing/page.tsx`, plan ids verified against `PLAN_LIMITS`)

| Plan key | Sites |
|---|---|
| `free` | 1 |
| `pro` | 3 |
| `max` | unlimited (`None`) |
| unknown key | 1 (safe default — mirrors `get_plan_limits` fallback-to-free posture) |

## Acceptance Criteria

- AC1 — Free user with 1 site + new URL → 4xx with machine-readable detail; DB site count unchanged.
- AC2 — Same user re-POSTing an owned URL at/over limit → 200 with the existing site.
- AC3 — Pro blocked at 3; `max` never blocked.
- AC4 — Limits live in one place in `apps/api/services/billing.py` and match the pricing page numbers.
- AC5 — Effective plan comes from the existing `get_effective_plan(user.plan, user.current_period_end)` derivation (lapsed paid plan → free).
- AC6 — Count query is user-scoped (`Site.user_id == user.id`).
- AC7 — Frontend create-site flow renders the message + a link to `/pricing`.
- AC8 — Unit tests cover: at limit, under limit, dedup bypass, unlimited tier, grandfathered over-limit user, unknown plan key.

## Out of Scope

- Retroactive deletion, disabling, or read-only-ing of sites owned above the limit.
- Downgrade-time enforcement (Gumroad webhook path untouched).
- Site-count display/meter in the dashboard sidebar.
- A soft-limit / warning state.
- Strict concurrency protection (advisory locks, SERIALIZABLE) — see accepted risk below.
- New env vars or feature flags.

## Constraints

- Only one Site creation path exists in the API (`apps/api/routers/sites.py::create_site`) — verified by grep; no other module constructs `Site(`.
- Dedup returns an existing row and creates nothing → must sit *before* the limit check.
- Race: two concurrent POSTs can both pass the count check and produce limit+1. Accepted risk (documented, not silently ignored): worst case is one extra site for a user who deliberately races; the pricing tiers are small and no money is lost. A DB-level fix is disproportionate.
- Frontend `api.ts:176` does `throw new Error(body.detail || ...)`; an object `detail` stringifies to `[object Object]`. The error contract must therefore carry a human-readable string the frontend explicitly reads.
- Ship enforcement ON. The repo's default-OFF flag precedent applies to *operator-risky infra* (ingest velocity, agent detection) where a wrong threshold breaks ingest. This is product gating with exact, already-published numbers and a reversible, user-visible failure mode — a flag would just be dead config.
