# Stripe Billing System — Implementation Plan

**Date:** 31-05-26
**Branch:** feat/onboarding-real-detection
**Status:** Ready for execution

## Summary

Add complete Stripe billing infrastructure: backend config + models, billing API router (checkout, portal, status, webhook), usage metering + plan enforcement, frontend billing page, and a Stripe setup script.

## Pricing Tiers

| Plan | Monthly | Yearly | Visitors/mo |
|------|---------|--------|-------------|
| Free | $0 | $0 | 10 |
| Pro | $19 | ~$15 | 50 |
| Max | $49 | ~$39 | Unlimited |

## Touchpoints

- `apps/api/config.py` — Stripe keys + price IDs
- `apps/api/models/user.py` — billing fields
- `apps/api/main.py` — column migrations + router registration
- `apps/api/routers/billing.py` — new billing router (CREATE)
- `apps/api/services/billing.py` — new billing service (CREATE)
- `apps/api/tasks/resolution_tasks.py` — usage gate
- `apps/api/requirements.txt` — add stripe package
- `apps/api/scripts/setup_stripe.py` — new setup script (CREATE)
- `apps/web/src/lib/api.ts` — billing API methods + types
- `apps/web/src/app/dashboard/billing/page.tsx` — new billing page (CREATE)
- `apps/web/src/app/dashboard/layout.tsx` — Billing nav item

## Public Contracts

### POST /api/v1/billing/checkout
Request: `{ "plan": "pro"|"max", "interval": "monthly"|"yearly" }`
Response: `{ "checkout_url": str }`

### POST /api/v1/billing/portal
Response: `{ "portal_url": str }`

### GET /api/v1/billing/status
Response: `{ "plan": str, "status": str|null, "monthly_identified_count": int, "monthly_limit": int|null, "trial_ends_at": str|null, "current_period_end": str|null }`

### POST /api/v1/billing/webhook (NO AUTH)
Handles: checkout.session.completed, customer.subscription.updated, customer.subscription.deleted, invoice.payment_failed

## Blast Radius

- Webhook must NOT have `get_current_user` dependency
- `monthly_identified_count` and `billing_cycle_reset_at` are new columns — safe with ADD COLUMN IF NOT EXISTS
- `stripe_customer_id`, `plan`, `stripe_subscription_id`, `subscription_status`, `trial_ends_at`, `current_period_end` all new columns on users
- resolution_tasks.py change: when usage denied, skip resolution silently (log warning, do not raise)
- Mock mode (`MOCK_EXTERNAL_APIS=true`) returns dummy checkout/portal URLs

## Verification Evidence

- `GET /api/v1/billing/status` returns `{ plan: "free", monthly_identified_count: 0, monthly_limit: 10 }` for new user
- `POST /api/v1/billing/webhook` with signature mismatch returns 400
- `POST /api/v1/billing/checkout` with mock mode returns `{ checkout_url: "https://mock-stripe.com/..." }`
- Billing nav item visible in dashboard sidebar

## Implementation Checklist

### Phase 1: Backend Config + Models
- [ ] `apps/api/config.py` — add stripe_secret_key, stripe_webhook_secret, 4 price IDs, stripe_portal_config_id
- [ ] `apps/api/models/user.py` — add 8 billing fields
- [ ] `apps/api/requirements.txt` — add stripe>=8.0.0
- [ ] `apps/api/main.py` — add 8 ALTER TABLE statements for new user columns + import billing router

### Phase 2: Billing Service + Router
- [ ] `apps/api/services/billing.py` — get_plan_limits, check_usage_allowed, increment_usage, reset_monthly_usage
- [ ] `apps/api/routers/billing.py` — checkout, portal, status, webhook endpoints

### Phase 3: Usage Metering Wire-up
- [ ] `apps/api/tasks/resolution_tasks.py` — call check_usage_allowed before resolving, increment_usage after

### Phase 4: Frontend
- [ ] `apps/web/src/lib/api.ts` — add createCheckout, createPortal, getBillingStatus methods + BillingStatus type
- [ ] `apps/web/src/app/dashboard/billing/page.tsx` — billing page with plan display, usage bar, upgrade buttons
- [ ] `apps/web/src/app/dashboard/layout.tsx` — add Billing nav item to BOTTOM_ITEMS

### Phase 5: Setup Script
- [ ] `apps/api/scripts/setup_stripe.py` — create Products + Prices, print env var values

## Resume and Execution Handoff

Selected plan: `process/general-plans/active/stripe-billing_PLAN_31-05-26.md`

All 5 phases should be executed in order. The webhook endpoint needs to be listed before the auth-protected routes in main.py (or simply use no `Depends(get_current_user)` on the webhook function itself). No Alembic — use existing ALTER TABLE IF NOT EXISTS pattern.
