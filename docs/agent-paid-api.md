# Agent-Paid API (MPP + x402 via InFlow)

Last updated: 2026-09-30

**BLUF:** External AI agents can pay per request, in USDC over MPP or x402, for four Beam operations.
Payment is verified in `apps/web` (Next.js route handlers, InFlow Node SDK). The actual work runs in
`apps/api` behind internal endpoints protected by a shared secret. **Both sides default OFF.**

Plan and verification state: `INFLOW-INTEGRATION-PLAN.md` (repo root). Coordinator plan:
`COMMERCE-INTEGRATION-PLAN.md`.

## Request flow

```
agent ──POST /api/paid/<op>──▶ apps/web (Vercel, Node runtime)
          │  no payment      → 402 with x402 PAYMENT-REQUIRED + MPP WWW-Authenticate (Python not called)
          │  MPP credential  → validate → call Python → 200 ? settle + Payment-Receipt : pass status, no charge
          │  x402 signature  → verify → call Python → settle only if status < 400
          ▼
apps/api  POST /internal/v1/paid/<op>   (X-Beam-Internal-Secret + X-Beam-Client-IP)
```

Only a Python **200** is ever charged. Every other status (404 no match, 413, 422, 429, 502, 503) returns
to the agent without settlement.

## Public endpoints (`apps/web`)

All are `POST` with `Content-Type: application/json` and a body of at most 16 KB. Prices are defaults and
can be overridden with env vars.

| Route | Default price (USDC) | Request body | 200 response |
| ----- | -------------------- | ------------ | ------------ |
| `/api/paid/enrich-email` | 0.05 | `{ "email" }` | `full_name, job_title, company_name, company_domain, linkedin_url, location{city,region,country}` |
| `/api/paid/ip-company` | 0.02 | `{ "ip" }` (public IPv4/IPv6 only) | `company_name, domain, confidence, source` |
| `/api/paid/deep-research` | 0.25 | `{ "full_name", "company_name"?, "job_title"?, "linkedin_url"?, "email"? }` | `summary, researched_at, model` |
| `/api/paid/outreach-draft` | 0.05 | `{ "visitor_name", "visitor_role"?, "visitor_company"?, "user_url"?, "recent_post"? }` | `draft, source` |

Error bodies: `404 {"error":"no_match"}`, `415`, `413`, `422` (field locations only, input never echoed),
`429`, `502 {"error":"upstream_error"}`, `503 {"error":"unavailable"}`. The flag being off, or an unknown
route, returns `404 {"error":"not_found"}`.

Payment options offered (Sandbox): MPP `inflow` method (USDC, InFlow balance rail), and x402 `balance` on
`inflow:1`, `exact` on Base Sepolia (`eip155:84532`), and `exact` on Solana devnet. MPP challenges are bound
to the route (`scope`), so a credential cannot be reused on another operation.

Privacy rules (enforced in `apps/api/services/agent_paid.py`):
- Only professional fields are returned. Never emails, phone numbers, or raw provider payloads.
- An email on the suppression list or linked to a `do_not_resolve` visitor looks exactly like no match.
- If the privacy check can't run, the request fails closed with 503.
- Logs carry route, outcome and provider only.
- `/internal/v1/paid` is always excluded from request-body logging.

## Configuration (names only, never commit values)

`apps/web` (Vercel project env, server-only, **never `NEXT_PUBLIC_`**):

| Name | Purpose |
| ---- | ------- |
| `AGENT_PAID_ENABLED` | `"true"` enables `/api/paid/*`; anything else returns 404 |
| `INFLOW_API_KEY` | InFlow **Seller** account API key (Sandbox or production, matching the environment below) |
| `INFLOW_ENVIRONMENT` | `sandbox` or `production`. **Required, no default** (the SDK itself defaults to production) |
| `MPP_SECRET_KEY` | At least 32 bytes and stable across deploys (`openssl rand -base64 32`). Rotating it invalidates outstanding MPP challenges |
| `BEAM_API_BASE` | Base URL of `apps/api` (existing variable) |
| `INTERNAL_PAID_API_SECRET` | Shared secret. Must equal `apps/api`'s `INTERNAL_PAID_API_SECRET` |
| `PAID_PRICE_ENRICH_EMAIL`, `PAID_PRICE_IP_COMPANY`, `PAID_PRICE_DEEP_RESEARCH`, `PAID_PRICE_OUTREACH_DRAFT` | Optional USDC decimal overrides. Applied at the next cold start or redeploy |

`apps/api` (Railway env; `apps/api/config.py`):

| Name | Default | Purpose |
| ---- | ------- | ------- |
| `AGENT_PAID_ENABLED` | `false` | Enables `/internal/v1/paid/*`; otherwise 404 |
| `INTERNAL_PAID_API_SECRET` | `""` | Shared secret. If empty, the routes stay 404 |
| `AGENT_PAID_RATE_LIMIT` | `30/minute` | Per-agent-IP slowapi limit (IP from `X-Beam-Client-IP`) |
| `AGENT_PAID_MAX_BODY_BYTES` | `16384` | Body cap |

Runtime: `apps/web` requires **Node 22 or later** (`engines`, CI). Set the Vercel project's Node version to 22.

## Local checks

```bash
cd apps/web && npm test                      # payment handler/config/SDK wiring (mocked)
PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_agent_paid_internal.py tests/unit/test_outreach_draft.py -q
```

Unpaid probe (no payment made). Run it with `AGENT_PAID_ENABLED=true` and Sandbox credentials in your
local shell env:

```bash
curl -i -X POST -H 'content-type: application/json' --data '{"ip":"8.8.8.8"}' http://localhost:3000/api/paid/ip-company
```

Paid checks use the InFlow CLI (`inflow mpp pay` / `inflow x402 pay`). They need `inflow vault unlock`,
`inflow auth login`, and an explicit spend limit. See `INFLOW-INTEGRATION-PLAN.md` § InFlow acceptance.

## Known limits

- Deep research by name alone can't be checked against the suppression list (there's no email to match).
  Output redaction of contact details is best-effort regex.
- Existing provider code logs partial identifiers on misses (`email[:5]`, `ip[:8]`).
- Outreach draft reuses the demo LLM call (legacy model id, 8s timeout).
- `@x402/core` calls `process.exit(1)` if its background init fails. `paid-payments.ts` avoids that path by
  initializing manually. Keep it that way when upgrading the SDK.
