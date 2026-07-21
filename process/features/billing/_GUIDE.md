# billing

<!-- Part of Beam -->

## Scope

Monetization and quota enforcement. Gumroad is the active Merchant of Record (Stripe unavailable in Vietnam; Lemon Squeezy rejected the category) — its webhook is authenticated by a URL token, NOT an HMAC signature. Covers plan tiers (Free/Pro/Max), per-site daily budgets (identity 50/day, deep research 3/day), BYOK API keys (Fernet-encrypted), and referral rewards.

## Key Source Files

- `apps/api/routers/billing*.py` — Gumroad webhook (`?token=` auth + optional seller_id match), checkout URLs, portal
- `apps/api/config.py` — `GUMROAD_*` (active), `STRIPE_*` / `LEMONSQUEEZY_*` / `ls_variant_*` (legacy, kept for webhook compatibility)
- `apps/api/services/*budget*` / quota checks inside `identity_resolver.py` and `enricher.py`
- BYOK vault: `apps/api/models/api_key.py` (`UserApiKey`), `ENCRYPTION_KEY` Fernet
- `apps/api/routers/referrals*.py` + `REFERRALS_ENABLED` flag ("give quota, get quota")

## Related Context

- `process/context/all-context.md` — Env groups (Billing, Encryption); prod startup fails without encryption keys
- `process/context/tests/all-tests.md` — `test_gumroad_webhook.py`, `test_billing_gumroad_routes.py`, `test_resolution_budget.py`

## Current Status

Status: stable — Gumroad live; legacy Stripe/LS webhooks kept for historical events only.

## Folder Contents

```
process/features/billing/
  active/       -- in-progress plans (each task in a {slug}_{date}/ folder)
  completed/    -- archived completed plans
  backlog/      -- deferred/future plans
```

All artifacts colocate inside each `{slug}_{date}/` task folder. Do NOT create `reports/` or `references/` sibling dirs.
