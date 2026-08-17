---
name: spec:private-beta-apply-form
description: "Re-arm getbeam private beta (invite-only) behind a public /apply form, admin-reviewed, feeding the existing invite-token flow"
date: 14-08-26
metadata:
  node_type: spec
  type: spec
  feature: onboarding-canary
---

# SPEC — Private Beta Apply Form

## TL;DR
Put getbeam back in invite-only mode. Keep the `/onboarding` canary demo fully public. Replace every "create an account" CTA with a public `/apply` form that collects who the applicant is and what they want Beam for. Admin reviews in the existing dashboard waitlist page and approves; the existing invite-email + token flow takes over unchanged.

## User Goals

| # | Goal |
|---|---|
| G1 | Stop uncontrolled account creation without losing the aha-before-commit demo funnel |
| G2 | Collect enough context per applicant to make approve/reject an informed decision (not just an email) |
| G3 | Reuse the existing waitlist + invite-token machinery rather than building a second system |
| G4 | Make the flip reversible by an operator without a code deploy |

## Key Use Cases

**UC1 — Prospect applies.** Lands on `/` or finishes `/onboarding` → CTA → `/apply` → fills the form → submit → sees a "you're on the list" confirmation state. Confirmation email sent; admin notified.

**UC2 — Admin reviews.** Opens `/dashboard/waitlist` → sees each applicant's email, site, what their business does, how they plan to use Beam, rough monthly visitors, role, company size, X handle → clicks Approve → existing `PATCH /approve` mints the token and sends the invite email.

**UC3 — Approved applicant signs up.** Clicks the invite link → `/signup?invite=…` stashes the token → Clerk account creation → `get_current_user` sees `invite_only=True`, finds the approved waitlist row **by email**, creates the Beam `User` → `dashboard/layout.tsx` consumes the token (one-use enforcement).

**UC4 — Email-mismatch recovery (the failure case that must not dead-end).** Applicant applies as `a@gmail.com` but completes Clerk signup under a different address. `_is_email_allowlisted` misses → 403 from `get_current_user`. They now hold a live Clerk account with no Beam `User` row. The product must show a comprehensible "this email isn't on the invite list" state with a path forward — not an infinite 403 loop or a blank dashboard.

**UC5 — Uninvited stranger.** Reaches `/sign-up` directly and creates a Clerk account. Gets the same 403 + explanatory state as UC4, pointed at `/apply`.

## Form Fields (locked by user)

| Field | Type | Required | Notes |
|---|---|---|---|
| email | string | yes | the unique key on `waitlist_signups` |
| website URL | string | yes | maps to existing `site_url` |
| what your business does | free text | yes | untrusted — read by admin UI |
| how you plan to use Beam | free text | yes | untrusted — read by admin UI |
| rough monthly visitors | enum/bucket | yes | bucketed, not free number |
| role | enum | yes | founder / marketer / agency / other |
| company size | enum | yes | bucketed |
| X handle | string | **no (opt-in)** | reuses existing `x_handle` semantics — supplying it IS consent for the public Founders Wall; never derived from email |

## Acceptance Criteria

| AC | Criterion |
|---|---|
| AC-1 | `/apply` is a public Next.js route, reachable without auth (`isPublicRoute` in `apps/web/src/middleware.ts`) |
| AC-2 | `/onboarding` stays public and un-gated; the middleware comment forbidding a re-gate is untouched |
| AC-3 | Submitting the form persists all 8 fields to `waitlist_signups` with `status='pending'` |
| AC-4 | Re-submitting the same email does not error and does not clobber non-empty stored values (upsert-with-backfill, matching current behavior) |
| AC-5 | Every free-text field is length-capped server-side and sanitized before storage |
| AC-6 | The admin waitlist page displays every new field for each signup |
| AC-7 | All 5 landing CTAs (`index.html`) and the onboarding end CTA (`onboarding-steps.js`) point at `/apply`, not `/sign-up` or account creation |
| AC-8 | With `INVITE_ONLY=true`, a Clerk signup whose email has no `approved`/`granted` waitlist row is refused |
| AC-9 | With `INVITE_ONLY=true`, a Clerk signup whose email HAS an approved row succeeds and creates the Beam `User` |
| AC-10 | With `INVITE_ONLY=false` (the default), account creation is unchanged — no regression |
| AC-11 | Existing users (matched by `clerk_user_id` or by email) are never blocked, regardless of waitlist state |
| AC-12 | A 403-from-invite-gate produces a comprehensible user-facing state pointing at `/apply` (UC4/UC5) |
| AC-13 | The invite-token consume path (`dashboard/layout.tsx` → `POST /consume-invite`) is unchanged and still enforces one-use |
| AC-14 | The Alembic migration is additive-nullable only, applies and rolls back cleanly on a local disposable DB |

## Out of Scope

- Any change to the invite-token minting, TTL (14 days), email templates, or one-use enforcement
- Any re-gating of `/onboarding`
- Changing `_is_email_allowlisted` from email-matching to token-matching (a design change, not this change)
- Applicant self-service status lookup ("where am I in the queue")
- Automated / scored approval — approval stays a human decision
- Retiring `waitlisted.html` if reuse is cheaper than replacement
- Running the migration or flipping `INVITE_ONLY` against production (both are operator steps recorded in the plan, not agent actions)

**Exception (ratified at PVL cycle 3):** `routers/waitlist.py`'s `invite_url` path constant `/signup` -> `/sign-up` is **in scope**. AC-13 is unreachable without it — the token is dropped at the `/signup` -> `/sign-up` redirect hop, so it is never stashed and `used_at` can never leave `NULL`. No other line of the invite email changes: not copy, not structure, not styling, not minting, not TTL, not one-use enforcement. Recorded here so a future reader of this SPEC alone can distinguish a ratified deviation from drift.

## Constraints Surfaced During RESEARCH

| # | Constraint |
|---|---|
| C1 | The invite gate keys on **email**, not token. Any design assuming token-at-signup is wrong. |
| C2 | `/onboarding` and `/` are STATIC files under `apps/web/public/beam/`, served via `next.config.mjs` rewrites. CTA rewiring is a static-asset edit, not a React edit. |
| C3 | The current Alembic head `c5e1a9b73d20` is **untracked/uncommitted** (owned by the in-flight `site-analysis-onboarding_13-08-26` plan). The chain target must be re-derived at EXECUTE. |
| C4 | `.env` `DATABASE_URL` points at Supabase PROD. Every alembic/DB command must pin `DATABASE_URL` to `localhost:5433` first. |
| C5 | Free text entered here is hostile input by repo policy and is rendered in an authed admin UI. |
| C6 | `status='granted'` also passes the allowlist, but `/grant` mints no token and sends no email. |
| C7 | Repo convention is default-OFF for new surfaces; `invite_only` already defaults `False`. |
