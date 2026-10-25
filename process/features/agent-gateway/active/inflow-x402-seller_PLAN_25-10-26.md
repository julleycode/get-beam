---
name: plan:inflow-x402-seller
description: "InFlow x402 seller — pay-per-call /api/v1/paid/* routes behind INFLOW_X402_ENABLED"
date: 25-10-26
feature: agent-gateway
shape: SIMPLE
status: EXECUTE
---

# InFlow x402 Seller — PLAN (SIMPLE)

## Goal

Let AI agents pay per call (x402 v2, InFlow facilitator, `balance` scheme on `inflow:1`) for four
read-only Beam capabilities, without an account. Dormant by default: flag off => routes 404.

Approach **A1**: `inflowpay[x402]` (Seller + Facilitator) driving the upstream
`x402HTTPResourceServer` from our own per-route helper (NOT the `[fastapi]` extra — it needs
fastapi>=0.142; we stay on 0.115.0). `httpx` bumped 0.27.2 -> 0.28.1 (inflowpay requires >=0.28.1).
Resolution verified in a scratch py3.11 venv against the full `requirements.txt`.

## Touchpoints

| File | Change |
|---|---|
| `requirements.txt`, `pyproject.toml` | `httpx==0.28.1`, `inflowpay[x402]==0.3.2` |
| `apps/api/config.py` | `inflow_x402_enabled`, `inflow_api_key`, `inflow_environment`, `inflow_base_url`, 4 price settings |
| `.env.example` | placeholders only |
| `apps/api/models/paid_request.py` + migration | `paid_requests` ledger, unique `payment_hash` |
| `apps/api/services/x402_seller.py` | startup setup/teardown, `PaymentGate`, `run_paid()` flow, stores |
| `apps/api/routers/paid.py` | `POST /api/v1/paid/{company-from-domain,social-posts,generate-draft,detect-platform}` |
| `apps/api/routers/demo.py` | extract `fetch_social_posts()` / `generate_draft_text()` (behavior unchanged) |
| `apps/api/services/identity_providers/pdl.py` | module-level `enrich_company_by_domain()` (PDL `/v5/company/enrich`) |
| `apps/api/main.py` | lifespan setup/teardown when flag on; router mounted only when flag on; payment headers redacted in request log |
| `tests/unit/test_paid_x402.py` | fake-facilitator tests |

Blast radius: new surface only, plus the httpx bump (whole app) and two pure extractions in demo.py.

## Steps

1. Deps + config + env placeholders.
2. `paid_requests` model + alembic migration on head `c5a91f3e07d4`.
3. Payment flow (`run_paid`): no/invalid payment -> 402 (PAYMENT-REQUIRED header + JSON body from
   x402); replay of an already-settled payload -> cached response, upstream not called; claim row
   (`pending`, unique hash; concurrent duplicate -> 409); verify -> handler -> settle; handler error
   -> cancel, no settle, 500; settle failure -> 402 + `paid_settle_failed` loss log; success -> 200 +
   PAYMENT-RESPONSE, row `settled` with tx/amount/network/payer for reconciliation.
4. Router + slowapi limits; no user-visible writes in handlers.
5. main.py wiring + header redaction (`x-payment`, `payment-signature`, `payment-response`,
   `x-payment-response`).

## Verification

- Unit (fake facilitator through the real `x402ResourceServer`): 402 shape; verify fail; happy
  path + PAYMENT-RESPONSE; handler error => no settle; settle 409 retry (InFlow Facilitator) and
  settle fail => 402; replay cached; flag off => 404; header redaction.
- Full unit lane in a venv with the bumped deps; baseline before changes: 2049 passed / 2 skipped.
- Manual sandbox e2e (no key available here): set `INFLOW_X402_ENABLED=true`,
  `INFLOW_API_KEY=<sandbox seller key>`, `INFLOW_ENVIRONMENT=sandbox`, boot API, then as buyer use the
  `inflow` CLI (agentic-payments skill) against `POST /api/v1/paid/detect-platform`
  `{"url":"https://example.com"}`; expect 402 -> paid retry -> 200 + PAYMENT-RESPONSE and a
  `paid_requests` row `settled`; repeat the same signed request -> cached body, no second settle.

## Execution Result (25-10-26)

- Approach A1 held: `inflowpay[x402]==0.3.2` + `x402==2.25.0` + `httpx==0.28.1` install cleanly with the
  full `requirements.txt` (`pip check`: no broken requirements) in a py3.11 scratch venv.
- `tests/unit/test_paid_x402.py`: 18 passed (real Seller/Facilitator + real x402 server; only the
  InFlow HTTP API is faked via `httpx.MockTransport`).
- Unit lane with bumped deps: 2067 passed / 2 skipped (baseline 2049 + 18 new, 0 regressions).
- Migration `d3f8a2c61b47` offline `--sql` clean. NOT live-applied/round-tripped and
  `SqlPaidRequestStore` not run against Postgres (no PG on :5433 this session) — known gap.
- Deviations: x402 v2 only — `X-PAYMENT` (v1) is NOT accepted (upstream server ignores it; InFlow is
  v2-only), still redacted in logs. No existing PDL company-by-domain call existed — added
  `enrich_company_by_domain()` (PDL `/v5/company/enrich`, mock-mode branch).

## Out of scope / follow-ups

- `identify-by-email` (PII, pending legal).
- `exact` scheme on Base (EVM) — `balance` only for now.
- Listing paid offers in agent-gateway manifest/llms.txt (per-customer-site surface; not a fit).
- Tighten `/demo` bypass (demo routes stay free + budget-capped).
- FastAPI upgrade (would unlock `inflowpay[fastapi]` middleware).
- Live sandbox test.
