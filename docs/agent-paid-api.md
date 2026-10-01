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

## Buyer (reseller) path

**BLUF:** When no direct Apollo key is configured, the enricher can buy the same Apollo
person-match from a reseller (Locus Apollo people-enrichment, listed $0.038) and pay with
InFlow over x402 or MPP. **OFF by default on both sides.** Capped at $0.05 per call and
$1.00 per UTC day. Every failure mode refuses to pay rather than guess.

```
enricher (Apollo step, no apollo_api_key, reseller_apollo_enabled)
  └─ services/reseller_apollo.py: Redis reserve $0.05 (fail closed) ─ POST once, no retry ─▶
apps/web POST /api/internal/buy/apollo-person   (X-Beam-Internal-Secret)
  ├─ unpaid probe → not 402? return upstream status + JSON, nothing paid
  ├─ price every offer BEFORE creating a payment; unknown asset/decimals = not payable
  ├─ InFlow-managed signing only (no external wallets) → pay ≤ 20 s → replay ONCE
  └─ 200 {provider, protocol, amount_usd, transaction, data}
```

Route responses (apps/web):

| Status | Body | Paid? | apps/api reservation |
| ------ | ---- | ----- | -------------------- |
| 200 | `{provider:"locus_apollo", protocol, amount_usd, transaction, data}` | yes | trimmed to `amount_usd` |
| 402 | `{error:"price_above_cap"}` | no | released |
| 402 | `{error:"no_payable_offer"}` (InFlow cannot sign any offer) | no | released |
| 402 | `{error:"payment_pending_or_declined"}` (approval needed, declined or > 20 s; approval cancelled) | no | released |
| 502 | `{error:"upstream_error", paid: true \| false \| null}` + `reseller_reconcile` log | maybe | released only if `paid:false` |
| 404 | `{error:"not_found"}` (flag off, bad secret, unknown path) | no | released |
| other | upstream status/JSON passed through (no 402 was issued) | no | released |

A timeout or network error on the apps/api → apps/web call keeps the full reservation (the
payment may have happened). Only `match` and `no_match` results enter the 7-day
`enrich:apollo:*` cache, so a cached answer never pays again.

Privacy and cost: only `email`, `first_name`, `last_name`, `domain`, `linkedin_url`,
`organization_name` are forwarded; `reveal_personal_emails` and `reveal_phone_number` are
always forced `false` (the phone reveal would cost +$0.28 and is also above the cap).
Upstream response headers are never forwarded; logs carry status, protocol and
transaction reference only.

Configuration (names only):

| Side | Name | Default | Purpose |
| ---- | ---- | ------- | ------- |
| web | `RESELLER_BUY_ENABLED` | off | `"true"` enables `/api/internal/buy/*`, else 404 |
| web | `INFLOW_BUYER_API_KEY` | falls back to `INFLOW_API_KEY` | InFlow key used to pay (a Seller account can buy) |
| web | `INFLOW_ENVIRONMENT` | required | `sandbox` or `production` |
| web | `INTERNAL_PAID_API_SECRET` | required | Same shared secret as the Seller path |
| web | `RESELLER_APOLLO_URL_X402` | Locus x402 URL | Override for self-tests |
| web | `RESELLER_APOLLO_URL_MPP` | Locus MPP URL | Override for self-tests |
| web | `RESELLER_PROTOCOL` | `auto` | `x402`, `mpp`, or `auto` (x402, then MPP only if x402 had no payable offer) |
| web | `RESELLER_MAX_PRICE_USD` | `0.05` | Per-call cap; offers above it are never paid |
| api | `RESELLER_APOLLO_ENABLED` | `false` | Enables the fallback (only when `APOLLO_API_KEY` is empty) |
| api | `RESELLER_DAILY_BUDGET_USD` | `1.00` | Daily ceiling, Redis key `reseller:apollo:spend:{YYYYMMDD}` (micro-USD) |
| api | `RESELLER_MAX_PRICE_USD` | `0.05` | Per-call reservation; keep ≥ the web cap |
| api | `BEAM_WEB_INTERNAL_BASE` | `""` | apps/web base URL for server-to-server calls |
| api | `INTERNAL_PAID_API_SECRET` | `""` | Shared secret (reused) |

Known limits:
- Locus accepts only mainnet: x402 `exact` on Base (`eip155:8453`) and MPP `tempo`. **InFlow
  Sandbox cannot pay either**, and production InFlow support for those offers is unverified.
  Until it is, the route answers `no_payable_offer` and pays nothing.
- With an API-key buyer, InFlow may still require dashboard approval. The route waits at most
  20 s, then cancels the approval and returns `payment_pending_or_declined`. Whether
  approval is required for API-key buyers is unverified.
- The paid Locus response shape (`{"person": {...}}`, Apollo `people/match`) comes from the
  listing and has not been observed on a real paid call.
- `x402 exact` and `mpp tempo` prices are recognized only for the known assets (Base / Base
  Sepolia USDC, InFlow ledger USDC, the Locus TIP-20 currency). Any other asset is refused.

### Self-test against our own Sandbox Seller (later, not run yet)

The buyer code can pay real Sandbox money to Beam's own Seller (`/api/paid/enrich-email`), which
offers `balance` on `inflow:1` (x402) and the `inflow` method (MPP), both payable from Sandbox.

1. Start the Seller stack exactly as for the task-80 checks (local `next start` + paid-only Python
   harness + tunnel). Seller env: `AGENT_PAID_ENABLED=true`, Sandbox `INFLOW_API_KEY`.
2. In the same web env add: `RESELLER_BUY_ENABLED=true`,
   `RESELLER_APOLLO_URL_X402=<tunnel>/api/paid/enrich-email`,
   `RESELLER_APOLLO_URL_MPP=<tunnel>/api/paid/enrich-email`, `RESELLER_PROTOCOL=x402` (then `mpp`).
   The Seller price ($0.05) equals the default cap, so it is payable.
3. Call the buy route directly with the shared secret and `{"email": "<fixture email>"}`.
   **Caveat:** the buy route always adds `reveal_personal_emails:false, reveal_phone_number:false`,
   and the Seller's Python schema is `extra="forbid"` (`apps/api/schemas/agent_paid.py:12`), so the
   Seller answers **422 after the payment credential is presented, and does not settle**. The buy
   route then returns `502 {"error":"upstream_error","paid":null}` plus a `reseller_reconcile`
   log (a non-402 failure without a receipt is treated as ambiguous; the Seller log and InFlow
   balance show it was not settled). That still proves the real InFlow payment-creation and replay formats
   and the "no charge on upstream failure" path end to end. A 200 self-test needs a seller route
   that ignores unknown fields (not built; never drop the forced reveal flags to make it pass).
   Expect at most one InFlow approval per call; if Sandbox requires dashboard approval, the
   route returns `payment_pending_or_declined` after 20 s.
4. Buyer and Seller are the same Sandbox account, so the balance moves only by fees. Count gross
   spend against the Sandbox authorization.
