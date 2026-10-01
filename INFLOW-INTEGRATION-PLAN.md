# InFlow Payments integration plan

Guide: https://app.inflowpay.ai/integration.md (template:
https://app.inflowpay.ai/integration-queue-template.md). Running under the Directory
coordinator — see `COMMERCE-INTEGRATION-PLAN.md`. Executable plan, not a changelog.
Never record credentials or personal data here.

## Goal and scope

- Target repository and application: `github.com/julleycode/get-beam`, local `~/get-beam`, branch
  `feat/agentic-commerce`. Payment boundary in `apps/web` (Next.js 14, Vercel, Node runtime);
  fulfillment in `apps/api` (FastAPI, Railway) via new internal endpoints.
- Selected SDK and version (npm, 2026-09-28; source inflow-node @ 7a98bbc):
  `@inflowpayai/mpp-seller@0.8.3` + `mppx@^0.8.17`; `@inflowpayai/x402-seller@0.8.0` + `@x402/core@^2.27`
  + `@x402/hono@^2.27` + `hono@^4.13`; `@inflowpayai/mpp-buyer@0.7.3`; `@inflowpayai/x402-buyer@0.10.0`.
  Exact versions re-verified with `npm view` and pinned at install (task 30). Node >= 22 required.
- Selected role: Both (Seller + Buyer).
- Selected protocols and payment capabilities: MPP (`inflow` method, USDC → InFlow balance rail, single
  charge) + x402 (`balance` on `inflow:1`, `exact` on Base / Base Sepolia). No subscriptions.
- Integration type: first MPP/x402 integration (confirmed by assessment).
- Environment: Sandbox for Seller checks; production for deploy and Buyer (resellers are mainnet-only).
- Included work:
  - Seller: 4 paid agent endpoints, USDC —
    `POST /api/paid/enrich-email` ($0.05), `POST /api/paid/ip-company` ($0.02),
    `POST /api/paid/deep-research` ($0.25), `POST /api/paid/outreach-draft` ($0.05).
  - Supporting Python internal endpoints (shared-secret auth), config, rate limits, tests, docs.
  - Buyer: Locus Apollo people-enrichment via a secret-protected internal Next route, used as an opt-in
    enricher fallback (flag OFF by default) when no direct Apollo key; caps $0.05/request, $1.00/day.
- Explicitly excluded work: tenant-bound ops (visitor identify, segments, campaign plan) — revisit in AEP;
  AEP and ODP implementation; subscriptions; refund code; Next.js upgrade; new Railway service; global
  fetch patching; Python port of the SDK; fixing the Hunter/Apollo 402-as-no_match bug (follow-up).
- Completion criteria: all ordered tasks complete or approved-deferred; Project acceptance and InFlow
  acceptance (below) met, local / preview / production results recorded separately.

## Current assessment

Read-only assessment 30-09-26 (4 parallel read-only agents; no code changed, no DB commands).
Paths relative to `apps/api/` unless noted. Runtime behavior not exercised.

**Stack / runtime**
- `apps/api`: Python 3.11 FastAPI, Railway Docker (`Dockerfile` python:3.11-slim, no Node toolchain),
  start runs `alembic upgrade head` then uvicorn; health `/health`, `/health/ready` (`main.py:576,582`).
- `apps/web`: Next.js 14.2.35, npm, no `engines`; CI uses Node 20 (`.github/workflows/test.yml:11`).
  Deployed on Vercel (inferred: `@vercel/analytics`, `DEPLOYMENT_CHECKLIST.md:60-62`). No `app/api/**`
  routes; browser calls FastAPI directly (`apps/web/src/lib/api.ts:84`).
- `apps/web/src/middleware.ts:15-37`: Clerk protects every non-public route, and the matcher always runs on
  `/(api|trpc)(.*)` (`:57-65`) — new `/api/paid/*` and internal buy route must be added to public routes.
- Other Node: `apps/pixel` + retired beacon are Cloudflare Workers. No Node server exists.

**Existing payments / protocols:** none. No x402/MPP code; only 402 is site-limit (`routers/sites.py:152`).
"MPP" hits = Apple Mail Privacy Protection. Billing = Gumroad subscriptions (`routers/billing.py:233`),
plan quotas only (`services/billing.py:15-30`: free 10 / pro 50 / max unlimited identified visitors/month).
No per-operation price anywhere; `services/api_pricing.py` holds Beam's *provider cost estimates*
(pdl $0.01, rb2b $0.09, proxycurl $0.01, osint-industries $1.00, gemini $0).

**Auth:** every operation route uses `get_current_user` (`dependencies.py:233-416`, Clerk RS256 or legacy
HS256 JWT) + `verify_site_access` (`dependencies.py:29-43`, 404 on miss). No inbound API-key/machine
auth. `UserApiKey` is outbound BYOK only. Existing shared-secret precedent: `X-Beam-Fetch-Secret` on
`POST /api/v1/agents/fetch-beacon` (`routers/agents.py:37-57`).

| Capability | Current implementation | Evidence | Planned change |
| ---------- | ---------------------- | -------- | -------------- |
| Identify one visitor | `POST /api/v1/visitors/{site_id}/{visitor_id}/resolve`, sync, JWT + owned site; monthly quota before work, daily attempt budget inside resolver | `routers/visitors.py:883-1021,959`; `services/identity_resolver.py:628-635` | None (tenant-bound; AEP follow-up) |
| Identify site batch | `POST /api/v1/visitors/{site_id}/resolve`, BackgroundTasks | `routers/visitors.py:1332-1420` | None |
| Enrichment lookup | No standalone route; runs inside resolve (PDL → Apollo → Proxycurl → Twitter), 7-day Redis cache by sha256(email) | `routers/visitors.py:971`; `services/enricher.py:206-339,113` | New paid endpoint over supplied email (tasks 20, 40) |
| IP → company | Resolver ladder incl. rDNS / ip-org / PDL-IP / IPinfo; runs with `db=None` in demo | `services/company_resolver.py`; `routers/demo.py:113-130` | New paid endpoint over supplied IP |
| Deep research | `POST .../{visitor_id}/enrich`, sync Gemini+grounding, 3/day cap | `routers/visitors.py:825-880`; `services/enricher.py:958` | New paid endpoint over supplied person fields |
| Outreach draft | `/api/v1/demo/generate-draft` LLM draft from supplied profile | `routers/demo.py:688` | New paid endpoint |
| AI segments / campaign plan | Tenant-data-bound, no quota | `routers/segments.py:65-106`; `routers/campaigns.py:85-165` | None (AEP follow-up) |
| Demo arbitrary-input routes | slowapi + global 50/day Redis budget that fails open; XFF spoofable | `routers/demo.py:92-110,556-595` | Not reused for gating; logic reused only |
| Agent-facing surface | manifest/offers/llms.txt + read-only MCP; flag `agent_gateway_enabled=False` | `routers/agent_gateway.py`; `routers/agent_mcp.py:117-200`; `config.py:512` | None here (ODP/AEP) |
| Rate limiting | slowapi IP limiter; none of the operation routes limited | `services/rate_limiter.py:48-52`; `main.py:124-126` | Limits on internal paid endpoints |
| Idempotency | None on any operation route | — | Protocol-level (x402 payment-identifier, MPP replay guard) |
| Outbound providers (Buyer) | ~15 per-call `httpx.AsyncClient` sites, no shared client; system keys in `config.py`; no dollar cap; provider 402 = unavailable or no_match | `services/identity_providers/*.py`; `services/enricher.py:491-771`; `usage_limits.py:55-89` | One fallback call site in enricher Apollo step (task 70) |
| Tests / gates | pytest unit (287) + integration (102, PG 5433 + Redis); web vitest + Playwright; CI runs backend unit, integration, e2e only; no lint/typecheck/coverage in CI | `pyproject.toml:1-10`; `.github/workflows/test.yml:38,88,126-178`; `process/context/tests/all-tests.md:68-74` | Project acceptance below |

**SDK facts (inflow-node @ 7a98bbc, npm 2026-09-28)**
- `@inflowpayai/mpp-seller` 0.8.3 (peer `mppx ^0.8.17`), `x402-seller` 0.8.0 (peer `@x402/core ^2.27`),
  `mpp-buyer` 0.7.3, `x402-buyer` 0.10.0. All require **Node >= 22**.
- No InFlow Python SDK (`inflow-python` repo empty; nothing on PyPI). Official Python `x402` / `pympp` exist
  but do not implement InFlow's `inflow` MPP method or `balance`/`inflow:1` x402 scheme.
- MPP seller: `mppx.charge(...)(req)` returns 402 challenge or validates **and** broadcasts (settles) before
  the handler runs (`packages/mpp-seller/README.md` Quickstart). `secretKey` >= 32 bytes, stable across
  deploys. Currency selects rail (USDC → balance). `environment` defaults to production — always set it.
- x402 seller: `paymentMiddlewareFromConfig` (`@x402/hono`) + `createInflowFacilitator`,
  `createInflowSellerClient`, `inflowAccepts`, `inflowSchemeRegistrations`
  (`examples/x402-seller-hono/src/index.ts`). Verify before handler, settle after; handler status >= 400 skips
  settlement; process exits on permanent config failure. `@x402/next` example requires Next ~16.3.
- x402 buyer: `createInflowClient` + `x402HTTPClient`, no fetch patching; routes InFlow-acceptable
  (scheme, network) through InFlow MPC signing, else foundation external-wallet schemes
  (`packages/x402-buyer/README.md:1-60`). MPP buyer patches `globalThis.fetch` unless `polyfill: false`.
- Seller needs an InFlow **Seller** account key (can also buy).

**Buyer findings (external)**
- PDL, Hunter, Apollo, IPinfo do **not** accept x402/MPP on their official APIs.
- Resellers do: Locus `apollo.x402.paywithlocus.com/apollo/people-enrichment` (listed ~$0.038) and
  `apollo.mpp.paywithlocus.com`; x402 on Base mainnet USDC, MPP via `tempo` only. InFlow payability unverified.

## Sources and unresolved questions

| Requirement or fact | Authoritative source and version | Implementation boundary |
| ------------------- | -------------------------------- | ----------------------- |
| MPP wire: 402 `WWW-Authenticate: Payment`, retry `Authorization: Payment`, `Payment-Receipt` | https://mpp.dev, paymentauth.org | `apps/web` paid route handler |
| x402 V2 wire: `PAYMENT-REQUIRED`, `PAYMENT-SIGNATURE`, `PAYMENT-RESPONSE` | https://docs.x402.org | `apps/web` paid route handler |
| SDK APIs | inflow-node @ 7a98bbc, packages listed above | `apps/web/src/lib/payments/*` |
| PII/GDPR guardrail | `process/context/all-context.md` Business Guardrails 3 | Python internal endpoints |

| Unresolved question | Evidence and context | Options and recommendation | Decision |
| ------------------- | -------------------- | -------------------------- | -------- |
| MPP charge only on success | `mppx.charge()` settles before handler. Core `mppx/server` (0.8.19) exposes `validateCredential()` (non-mutating) and `broadcastCredential()` (settles), both taking `{ request, scope }` to bind a credential to route + amount (`mppx/dist/server/Mppx.d.ts:105-112,206-221`) | Flow: validate → fulfill → broadcast → return result only if broadcast succeeds; replayed credential may cost one wasted fulfillment (rate-limited) | Viable (spike 30-09-26): validate → fulfill → `charge(req)` settle → `withReceipt`. Live paid happy path + no-match-not-charged deferred to task 80 (needs CLI vault unlock + auth + Sandbox spend authorization) |
| x402 on Next 14 | `@x402/next` needs Next 16 | Hono app in App Router catch-all via `hono/vercel` `handle`, `runtime = "nodejs"` | **Proven (spike):** Next 14.2.35 + Hono 4.13.11 + `@x402/hono` 2.28.0 + `@inflowpayai/x402-seller` 0.8.0 on Node runtime, live Sandbox config. Note: `@x402/hono` middleware *returns* its 402 Response — wrapper must use the return value, not `c.res` (bug found + fixed in spike) |
| Next 14 webpack bundling of `@inflowpayai/mpp-seller` | `next build` fails: `mppx/dist/mcp/server/Transport.js` → `Can't resolve '@modelcontextprotocol/sdk/types.js'` (optional peer), via `mppx/dist/server/index.js` | Options: install `@modelcontextprotocol/sdk`; mark `mppx` / InFlow packages as `experimental.serverComponentsExternalPackages`; import a narrower mppx entry | **Resolved (spike):** `experimental.serverComponentsExternalPackages` = `mppx`, `@inflowpayai/mpp-seller`, `@inflowpayai/x402-seller`, `@x402/core`, `@x402/hono`, `@x402/evm`, `@x402/extensions` → build passes, SDK loads at runtime, MCP optional import never hit; no extra dependency |
| MPP + x402 on one route without double charge | Two independent middlewares | Dispatch on credential header; unpaid 402 carries both challenges | **Proven (spike, live Sandbox):** unpaid → one 402 with x402 `PAYMENT-REQUIRED` (accepts: `exact` eip155:84532, `exact` Solana devnet, `balance` inflow:1; amount 0.02 USDC) + MPP `WWW-Authenticate: Payment method="inflow"`. Fake `PAYMENT-SIGNATURE` → 402, no fulfillment. Malformed `Authorization: Payment` → 402 `malformed-credential` problem, no fulfillment |
| Sandbox Seller credentials | Developer supplied a key in chat (30-09-26); stored only in the scratch spike folder, mode 600, never in repo/plan | Read-only check: Sandbox `GET /v1/mpp/config` and `/v1/x402/config` = 200 (Seller account); production = 401 → Sandbox-only key. Sandbox offers MPP `inflow` (USDC/USDT/PYUSD balance, USD instrument) and x402 USDC on `eip155:84532` + Solana devnet | Developer should rotate the key after testing |
| InFlow buyer can pay Locus (MPP `tempo` / x402 `exact` Base mainnet)? | Unverified | Read-only `inflow mpp inspect` / `inflow x402 inspect` | Pending — task 60 gate |
| InFlow CLI install on dev machine | Was 0.12.2 (installed 2026-09-21); upgraded via `brew upgrade --cask inflowpayai/tap/inflow` | — | Installed 0.13.0 (30-09-26, developer-requested) |
| CLI environment selection (Sandbox vs production) | Not shown in 0.13.0 `--help`; inflow-cli @ 6ee10e2 `docs/development/surfaces-and-testing.md:109-118,316`: `--sandbox`, `--environment sandbox`, or `INFLOW_ENVIRONMENT=sandbox`; connection stored per environment | Every task-80 CLI command runs with `INFLOW_ENVIRONMENT=sandbox` **and** `--sandbox`; confirm with `inflow auth status --format json` before paying | Resolved (30-09-26) |
| CLI vault + auth | Developer reset vault (forgotten PIN), re-initialized, logged in (30-09-26) | — | Done: `inflow auth status --sandbox` = authenticated, environment `sandbox`, `https://sandbox.inflowpay.ai` |
| Sandbox buyer funds | `inflow balances list --sandbox`: USDC/USDT/PYUSD available 0 (30-09-26); deposit addresses exist for BASE, SOLANA, TEMPO | Developer funds with **testnet** USDC (e.g. Circle faucet, Base Sepolia) to the BASE deposit address from `inflow deposit-addresses list --sandbox` | Pending (developer action) |
| Local api for paid checks | Full `main.py` boots `start_scheduler()` unconditionally and `.env` holds real provider/SendGrid keys | Scratch harness `scratchpad/paid_only_app.py` mounts only the paid router; asserts local DB + `MOCK_EXTERNAL_APIS=true` | Ready (recreated after session restart) |
| CLI paid checks against localhost | `inflow mpp pay` / `mpp inspect` on `http://localhost:3000/api/paid/ip-company` → `PAYMENT_FAILED` / `INSPECT_FAILED`: "InFlow TAP signing failed. The Service request was not sent." (~56s). inflow-cli @ 6ee10e2 `packages/core/src/client.ts:190-195`: device-login auth → CLI asks InFlow `POST /v1/tap/signatures` to sign the target URL (`tap-request.ts:199-240`); skipped for API-key auth. Likely rejects non-public/non-HTTPS targets (inferred). No payment attempted; balance 20 USDC | (a) temporary public HTTPS tunnel to local web; (b) CLI with `--api-key` of a separate buyer (Developer) account (TAP skipped); (c) Vercel preview deploy | Pending developer decision |
| Task 80 Seller InFlow acceptance summary (01-10-26) | 8 paid (4 routes × MPP/x402) + 2 no-match + 1 duplicate pair; Python calls: 9× 200 + 2× 404, exactly one per settled payment, none for replay. Gross Sandbox spend $0.76 of $2.00; balance 20 → 19.9772 (fees only; buyer = seller account). Tunnel + local servers stopped afterwards (tunnel URL now 530) | Remaining: deployed checks (task 90) | Seller local verification DONE |
| Tunnel + agent-run CLI pay | Developer chose temporary tunnel; `cloudflared` quick tunnel → local :3000 (unpaid 402 confirmed via tunnel). Two agent-run `inflow mpp pay` attempts (ip-company, $0.02) → `PAYMENT_FAILED: The InFlow vault daemon did not respond.`; balance unchanged 20 USDC, Python not called | Developer runs the pay command in their own terminal (vault daemon may require an interactive/human client) | Pending developer run. Cause traced (inflow-cli @ 6ee10e2 `vault-sync-secret-store.ts:31,93-96`): CLI waits max 10s for vault daemon IPC; daemon did not answer agent-spawned processes in time (peer-verified daemon, `vault-daemon.ts:279-282`) — inferred, not proven. Stack restarted 01-10-26 after machine sleep; new tunnel URL issued |
| First real MPP credential rejected (01-10-26) | Developer ran `inflow mpp pay` in own terminal → approval (tx `aaf747f9-…`) → CLI sent credential → our handler returned 402 `PAYMENT_NOT_ACCEPTED`. Web log: `stage: validate, error: MissingPaymentSchemeError`. Cause: handler stripped `Payment ` before `mppx.validateCredential()`; mppx `Credential.deserialize` requires the full header (`mppx/dist/Credential.js:38-41`). Unit fakes did not check format | **Fixed:** `paid-handler.ts` passes trimmed full header; new test pins it. tsc ok, lint clean, vitest 270/270, build ok, web restarted. Not settled → no charge (balance 20) | Re-run pay |
| Sandbox buyer funded | Faucet 20 testnet USDC → BASE deposit address (Base Sepolia); on-chain 20.0; InFlow balance 20 USDC (30-09-26) | — | Done |
| Local stack for task 80 | Harness `127.0.0.1:8765` (paid router only, mock providers, local DB, throwaway test `PII_HMAC_KEY` — without it privacy gate correctly failed closed 503); web `next start :3000` reading developer's local env file. Unpaid → 402 both challenges; harness match 200 / no-match 404 | — | Running |
| Session restart (30-09-26) | Scratch folder reset: spike, scratch copy of Sandbox key, harness removed; Docker stopped; vault re-locked (policy: lock on sleep, 8h idle) | Docker restarted; harness recreated; web Sandbox creds now go in a developer-created local env file in `apps/web` (gitignored; agent never reads it) | Developer: `inflow vault unlock`, create the web local env file, fund wallet |
| Vercel Node runtime version | Unknown; SDK needs >= 22 | Developer sets Node 22 in Vercel project | Pending (developer action) |

## Decisions

| Decision | Rationale | Approval |
| -------- | --------- | -------- |
| All three capabilities; order Payments → AEP → ODP | Coordinator recommendation | Developer "go" (30-09-26) |
| Work on branch `feat/agentic-commerce`; no commits/PRs without approval | Developer choice | Developer (30-09-26) |
| Skip repo RIPER-5 harness; follow InFlow guide stages directly | Developer instruction | Developer (30-09-26) |
| Role Both; protocols Both; first integration; Sandbox first | Interview answers | Developer (30-09-26) |
| Seller scope: 4 new agent-callable paid endpoints over caller-supplied input | Existing ops tenant-bound | Developer (30-09-26) |
| Tenant-bound ops excluded; revisit in AEP | Need authenticated site owner | Developer (30-09-26) |
| Runtime A: Next.js route handlers in `apps/web` run InFlow SDK; call Python internal endpoints with shared secret | Node already present; no new service | Developer (30-09-26) |
| Buyer: one provider via reseller — Locus Apollo | Developer choice | Developer (30-09-26) |
| Plan approved | — | Developer "approve plan" (30-09-26) |
| Sandbox spend authorization: $2.00 total cap for task-80 Seller checks (Sandbox only; production spend not authorized) | Covers MPP + x402 per route + no-match + duplicate (~$1.54 list) | Developer "approve $2 Sandbox" (30-09-26) |
| Pin Node 22 in `apps/web` (`engines`) and CI (`NODE_VERSION`) — applied in task 30 | SDK requires Node >= 22 | Developer (30-09-26) |
| Stage 4 defaults: prices above in USDC from env config; charge only on success; anonymous paid access; shared-secret internal auth; x402 payment-identifier + MPP replay guard; MPP charged-but-failed → reconciliation log, no refund code; per-IP rate limit + body cap; professional fields only, suppression + `do_not_resolve`, no PII logs; Node 22 pin; stay on Next 14; Buyer flag OFF, $0.05/req, $1/day, pending approval = failure, scoped client; Seller key server-only; `environment` always explicit | Recommended defaults | Developer "defaults ok" (30-09-26) |

## Active work

- Stage: Implementation
- State: Waiting for developer
- Current task: 20 done (30-09-26). Files: new `apps/api/routers/agent_paid_internal.py`, `services/agent_paid.py`,
  `schemas/agent_paid.py`, `services/outreach_draft.py`, `tests/unit/test_agent_paid_internal.py` (49),
  `tests/unit/test_outreach_draft.py` (6); modified `config.py` (4 settings), `main.py` (mount),
  `routers/demo.py` (calls extracted draft service), `services/enricher.py` (prompt extracted, visitor path
  unchanged), `services/request_logger.py` (always exclude `/internal/v1/paid` from request-body capture)
- Task 30 (30-09-26): `engines.node >=22`; CI `NODE_VERSION: "22"`; exact pins added — `@inflowpayai/mpp-seller@0.8.3`,
  `mppx@0.8.19` (latest is 0.12.0 but peer range is ^0.8.17), `@inflowpayai/x402-seller@0.8.0`, `@x402/core@2.28.0`,
  `@x402/extensions@2.28.0`, `@x402/hono@2.28.0`, `hono@4.13.12`. Optional `@x402/evm` not added (passthrough schemes
  suffice per spike). Buyer packages deferred to task 70. On Node 22.23.3: `npm ci` ok, lint clean, vitest 205/205,
  `next build` exit 0 (SDK not yet imported — bundling config lands in task 40)
- Task 40 (30-09-26): new `apps/web/src/lib/payments/{paid-config,paid-handler,paid-payments}.ts` (+3 test files, 64 tests),
  `src/app/api/paid/[[...route]]/route.ts`; edited `src/middleware.ts` (Clerk public `/api/paid(.*)`, beacon skip),
  `next.config.mjs` (`serverComponentsExternalPackages`). Env names (server-only): `AGENT_PAID_ENABLED`, `INFLOW_API_KEY`,
  `INFLOW_ENVIRONMENT` (required, no default), `MPP_SECRET_KEY`, `BEAM_API_BASE`, `INTERNAL_PAID_API_SECRET`,
  `PAID_PRICE_{ENRICH_EMAIL,IP_COMPANY,DEEP_RESEARCH,OUTREACH_DRAFT}`. `@x402/core` background init calls `process.exit(1)` on
  config failure → avoided: manual `x402HTTPResourceServer.initialize()` in try/catch + `paymentMiddlewareFromHTTPServer(..., false)`.
  Review fix: MPP validate + charge bound to route via mppx `scope` (credential for one $0.05 op cannot be redeemed on the other).
  Live Sandbox (local `next start`, Python unreachable): all 4 routes → 402 with x402 `PAYMENT-REQUIRED` (balance inflow:1, exact
  Base Sepolia, exact Solana devnet; 50000/20000/250000/50000 atomic USDC) + MPP `WWW-Authenticate` with scoped `opaque`; fake MPP /
  x402 → 402; GET/unknown → 404; text/plain → 415; 0 Python calls. On Node 22: tsc 0 errors, lint clean, vitest 269/269, build ok
- Task 50 (30-09-26): new `docs/agent-paid-api.md` (flow, endpoint contract, prices, env names for web + api, local checks,
  known limits); `process/context/all-context.md` routing row + env-var group line. Env example file NOT edited (repo privacy
  hook requires approval to open it) — names documented in `docs/agent-paid-api.md` instead
- Next action: task 80 (Seller part) — local verification: full unit + integration suites, then authorized Sandbox paid checks
  (`inflow mpp pay` / `inflow x402 pay` per route, no-match, duplicate). Buyer track (60-70) follows per plan order.
  Prerequisites (developer): `inflow vault unlock` + `inflow auth login` to a **Sandbox** buyer account with test funds;
  Docker Desktop running (PG :5433 + Redis :6379); Sandbox spend authorized ($2.00 cap, 30-09-26)
- Approval needed: none for task 30 (approved). Before task 80: developer runs `inflow vault unlock` + `inflow auth login`;
  Docker Desktop running for integration suite; Sandbox spend authorization; Node 22 in Vercel

## Ordered tasks

Seller and Buyer are separate tracks. Buyer (60–70) starts only after the Seller track is locally verified.

| Order | State | Task | Dependencies | Output | Verification | Approval needed |
| ----- | ----- | ---- | ------------ | ------ | ------------ | --------------- |
| 10 | Done (live paid check deferred to 80) | **Spike (throwaway, scratch dir, not merged):** Next 14 + Node 22. Prove (a) Hono + `@x402/hono` + InFlow x402 seller in App Router catch-all via `hono/vercel`, `runtime="nodejs"`; (b) mppx split validate → work → broadcast so MPP charges only after success; (c) single 402 with both challenges + header dispatch. Sandbox Seller key from developer's local env. No payments | Plan approval; Sandbox key | Findings in Sources table; response contract fixed | Unpaid request → 402 with both challenges; app boots | Plan approval |
| 20 | Done — unit verified; integration pending (Docker PG/Redis not running) | **Python internal paid endpoints:** `apps/api/routers/agent_paid_internal.py` at `/internal/v1/paid/{enrich-email,ip-company,deep-research,outreach-draft}`; dependency checks `X-Beam-Internal-Secret` via `hmac.compare_digest` (setting `internal_paid_api_secret`; empty → 404); flag `agent_paid_enabled=False`; reuse `Enricher` (PDL → Apollo), `company_resolver`, Gemini deep-research, demo draft logic; Pydantic schemas; professional fields only; suppression + `do_not_resolve` via email blind index; 404 on no match; structlog keys only; slowapi limits keyed on client-IP header trusted only after secret check; body cap | 10 | Router, schemas, `config.py` fields, mount in `main.py` | New unit + integration tests with service-layer mocks; existing suites green | Plan approval |
| 30 | Done (30-09-26) | **Node 22 + dependencies:** `apps/web/package.json` `engines.node >=22`; CI `NODE_VERSION: "22"`; add pinned SDK + foundation deps | 10 | `package.json`, lockfile, `.github/workflows/test.yml` | `npm ci`, lint, vitest, `next build` on Node 22 | Plan approval; developer sets Vercel Node 22 |
| 40 | Done (30-09-26) — unit + live Sandbox unpaid/invalid checks; paid path pending task 80 | **Seller payment boundary in `apps/web`:** `src/lib/payments/inflow-config.ts` (env validation, explicit `environment`, prices from env, server-only); `src/app/api/paid/[[...route]]/route.ts` Hono app: x402 middleware for 4 routes, MPP split charge, dispatcher, 402 composition; forwards body + client IP + secret to Python; no-match → 404 / no settle; MPP charged-but-failed → structured reconciliation log (tx id, route, status; no PII). `middleware.ts`: add `/api/paid(.*)` to Clerk public routes; skip fetch-beacon for it | 20, 30 | Lib + route files, middleware edit | vitest (mocked facilitator / InFlow client): unpaid, invalid, paid, no-match, Python error, secret missing; lint; build | Plan approval |
| 50 | Done (30-09-26) | **Seller docs:** env var names (no values) in env example file + `apps/web` docs section; endpoint contract, prices; pointer in `process/context/all-context.md` | 40 | Docs | Review | Plan approval |
| 60 | Not started | **Buyer feasibility gate:** read-only `inflow mpp inspect` + `inflow x402 inspect` on Locus Apollo; confirm an offered (method/scheme, network) is payable via InFlow-managed signing. If not → stop, report, ask (defer Buyer) | CLI install; 80 Seller local done | Findings recorded | Inspect output | CLI install |
| 70 | Not started | **Buyer implementation:** `src/app/api/internal/buy/apollo-enrich/route.ts` (secret-protected, Clerk-public) with scoped `x402HTTPClient(createInflowClient(...))` or `mppx.fetch` + `polyfill:false`; policy rejects > $0.05; pending approval → failure. Python `services/enricher.py`: fallback when `apollo_api_key` empty and `reseller_apollo_enabled=True`; Redis daily spend reservation ($1.00, fail closed) before call; mock-mode short-circuit; `log_api_call` with cost | 60 pass | Route, enricher change, config | Unit tests: 402→paid, over-cap, pending, timeout, cap exhausted, flag off; existing enricher tests | Plan approval |
| 80 | Seller part DONE (01-10-26) — InFlow Sandbox acceptance PASS; unit/integration/lint/vitest/build/auth/e2e: no regression | **Local verification** (Project acceptance + local InFlow Sandbox checks) | 20–50; 70 for Buyer | Results in Exit criteria | See Exit criteria | Sandbox payment-test authorization |
| 90 | Not started | **Deploy + deployed verification:** Vercel env + Node 22, Railway env (secret, flags); deployed CLI checks; Buyer production real request | 80 | Deployment evidence | See Exit criteria | Deploy authorization; production spend authorization |
| 100 | Not started | **Coordinator handoff:** update `COMMERCE-INTEGRATION-PLAN.md`; ODP follow-up (advertise 4 paid Actions + prices + protocols); AEP follow-up (tenant-bound ops) | 80 (90 may stay pending) | Coordinator updated | — | — |

## Review and verification

Seven-step template review applies to every implementation task (trace requirements, list failure cases
first, small slices, skeptical review of external calls / payments / auth / retries, run checks, inspect every
changed file, hand back with exact evidence).

| Check | Command or procedure | Result | Evidence or limitation |
| ----- | -------------------- | ------ | ---------------------- |
| Repository checks | See Project acceptance | Not run | — |
| Integration behavior | See InFlow acceptance | Not run | — |
| Final diff review | Review all changed files | Not run | — |

## Risks and discovered work

| Finding | Impact | Evidence | Resolution or developer decision |
| ------- | ------ | -------- | -------------------------------- |
| Python backend; InFlow SDK Node >= 22 only | Payment runs in `apps/web`, not `apps/api` | Dockerfile; npm engines | Runtime A approved |
| Seller ops tenant-bound behind Clerk | Payment must not replace tenant auth | `dependencies.py:29-43,233-416` | New endpoints over supplied input only |
| MPP settles before handler | Could charge on no-match | mpp-seller README | Task 10 spike; fallback recorded |
| Next 14 vs `@x402/next` (Next 16) | x402 via Hono path instead | inflow-node example | Task 10 spike; no Next upgrade |
| Node 20 in CI; Vercel runtime unknown | Build/runtime mismatch | `test.yml:11` | Task 30 + developer Vercel setting |
| Resellers mainnet only; Sandbox keys sandbox only | Buyer test needs production + real funds | SDK README; Bazaar | Explicit spend authorization in task 90 |
| Reseller cost ~4x direct Apollo, ~25–35x for PDL | Fallback only, capped $1/day | Bazaar listings | Flag OFF by default |
| Email enrichment returns personal data to anonymous agents | GDPR/abuse | guardrail 3 | Professional fields, suppression, no PII logs, rate limits |
| Hunter/Apollo 402/401 counted as no_match | Existing bug | `hunter.py:70-72`, `apollo.py:68-70` | Out of scope; follow-up |
| Many providers lack mock short-circuit | Tests could hit real providers | `config.py:1024` | Mock at service layer in new tests |
| Repo `.env` `DATABASE_URL` points at Supabase prod | Unpinned DB command hits prod | `process/context/all-context.md` Safety | Pin local DSN for every DB/test command |
| Task 20 wire contract for task 40 | Next handler must settle/charge only on HTTP 200; 404 `{"error":"no_match"}`, 422, 413, 429, 502, 503 must never settle | `routers/agent_paid_internal.py:23-24,147-156` | Enforce + test in task 40 |
| Next handler must always send `X-Beam-Client-IP` | Otherwise all agents share one rate-limit bucket | `agent_paid_internal.py:80-93` | Done in task 40 (`x-real-ip` on Vercel, else first XFF; else `unknown`) |
| Off Vercel, `x-forwarded-for` spoofable | Affects rate-limit key only | `paid-handler.ts` extractClientIp | Accepted (prod on Vercel) |
| `onError` maps any uncaught exception to 503 | Hides details from agent (intended); logs name only | `paid-handler.ts:254` | Accepted |
| Prices read at payments init (per server instance) | Price env change needs redeploy | `paid-payments.ts` | Accepted |
| Name-only deep-research cannot be checked against suppression; output redaction is regex best-effort | Residual privacy risk | `services/agent_paid.py:299-352` | Accepted per defaults; revisit if abuse |
| Shared provider code logs partial PII (`email[:5]`, `ip[:8]`) on misses | Pre-existing, now reachable from paid path | `services/enricher.py` PDL/Apollo; `company_resolver.py` | Follow-up (out of scope) |
| Outreach draft reuses demo LLM call (legacy model id `claude-sonnet-4-20250514`, 8s timeout, 150 tokens) | Quality/latency of a paid product | `services/outreach_draft.py` | Follow-up: review model choice |
| Paid routes return 405 on GET even when flag off | Path discoverable, not usable | FastAPI routing | Accepted |
| Root cause of MPP `MissingPaymentSchemeError` (01-10-26) | Orchestrator's spike stripped `Payment ` before `mppx.validateCredential()` based on the type signature only (`string \| Credential`), never checking `Credential.deserialize`; spike's fake-credential 402 was misread as validation working (validate failed for every credential, 402 came from fallback); spec + fake-gateway unit tests repeated the assumption | Caught only by first real Sandbox payment; no charge | Lesson for remaining tasks (incl. Buyer 70): verify each external SDK call's input format against SDK source or a real round trip — never type signature or fakes alone |
| Clerk middleware matches `/api/*` | New routes 401/redirect unless public | `middleware.ts:18-29,57-65` | Task 40 adds public route |

## Completion and handoff

Not started.

## Exit criteria

### Project acceptance

| Criterion | Command or procedure | Expected result | Result and evidence |
| --------- | -------------------- | --------------- | ------------------- |
| Backend unit suite | `PYTHONPATH=. .venv/bin/python -m pytest tests/unit -q` (repo has no `.venv`; used `/Users/apple/getbeam/.venv`, Python 3.11) | 0 failures, new tests included | **Pass (task 80, 30-09-26, DSN pinned localhost:5433):** 3067 passed, 2 skipped, 0 failed |
| Backend integration suite | **Task 80 (30-09-26), DSN pinned localhost:5433:** full run 665 passed, 20 failed, 5 skipped. All 20 in `test_onboarding_canary_api.py` (19) + `test_ip_org_pipeline.py::TestLockSerialization` (1) — areas this work did not touch. Clean base worktree (HEAD `225774f`) failed the same subset (18); re-run of that subset on base and on this branch: 0 failures each (identical). Verdict: pre-existing state/order-dependent flakes, not a regression. New agent-paid code has unit coverage only (no integration tests added). Local Docker PG 5433 + Redis, `DATABASE_URL` pinned to localhost, then `PYTHONPATH=. .venv/bin/python -m pytest tests/ -m integration -q` | 0 failures | Pending |
| Web lint | `cd apps/web && npm run lint` | Clean | After task 40 on Node 22.23.3: clean — re-run at 80 |
| Web unit tests | `cd apps/web && npm test` | 0 failures, new payment tests included | After task 40: 269/269 (64 payment tests) — re-run at 80 |
| Web build / types | `cd apps/web && npx next build` on Node 22 | Build succeeds | After task 40: build ok; `tsc --noEmit` 0 errors — re-run at 80 |
| Web e2e regression | `cd apps/web && npx playwright test` in a clean worktree without `.env` (CI-like), DB pinned `localhost:5433`, `MOCK_EXTERNAL_APIS=true`, Node 22, Playwright 1.60 / chromium-headless-shell-1223 | No new failures vs base | **No regression (01-10-26)** — this branch: 44 passed / 18 failed / 8 skipped; clean base `225774f`: 46 passed / 18 failed / 6 skipped. 16 failures identical (onboarding platform-detection/verify, LinkedIn wizard, blog editor, onboarding canary, connectors-ads :93/:108). Diff = connectors-ads :60/:67 (ours-only) vs connectors-ads-push-warning :77/:101 (base-only); isolated re-run on this branch: :60/:67 pass → flaky. Pre-existing local e2e failures not investigated (out of scope) |
| Auth regression | Targeted checks: dashboard requires Clerk; `/api/paid/*` public; internal Python endpoints 404 without secret | As stated | **PASS (01-10-26)** — Clerk `createRouteMatcher` fed the exact public list from `src/middleware.ts` (11 entries): `/dashboard`, `/dashboard/visitors` → protected; `/api/paid`, `/api/paid/ip-company`, `/pricing`, `/sign-in` → public. Internal endpoints: unit tests + live probe → 404 without secret. Note: `/api/paid(.*)` also matches any future `/api/paid…`-prefixed route — keep that namespace payment-only |
| Final diff review | Every changed file reviewed; tested tree = delivered tree | No unrelated drift | Pending |

No coverage threshold exists in the repo; none is added or lowered.

### InFlow acceptance

CLI syntax re-verified against the installed version before running. No secrets in commands or logs.

| Criterion | Environment and target | Prerequisites and authorization | Command or procedure | Expected result | Result and evidence |
| --------- | ---------------------- | ------------------------------- | -------------------- | --------------- | ------------------- |
| Unpaid request challenged | Sandbox, local `next start` :3998 | Local run | `curl -X POST` each route without credential | 402 with MPP + x402 challenges; no Python call | **Pass (local, 30-09-26)** — all 4 routes; 0 Python calls. Preview/prod pending |
| Invalid payment rejected | Sandbox, local | — | `curl` with malformed `Authorization: Payment` / `PAYMENT-SIGNATURE` | 402/4xx; no fulfillment | **Pass (local, 30-09-26)** — both 402, 0 Python calls |
| MPP paid, each route | Sandbox, local web via cloudflared quick tunnel (TAP signing requires public HTTPS target) | CLI run by developer in own terminal (agent-run CLI hits vault-daemon IPC timeout); Sandbox $2.00 cap | `INFLOW_ENVIRONMENT=sandbox inflow mpp pay <tunnel>/api/paid/<op> --sandbox --method POST --data '<fixture>' --payment-method inflow --currency USDC --interval 5 --max-attempts 24` + dashboard approval | 200 + receipt; one charge | **PASS all 4 routes (01-10-26)** — ip-company tx `da939030-…`, enrich-email, deep-research, outreach-draft tx `45b08f90-…`: each `✓ Paid (intent charge)`, `settled: success`, 200 + result, exactly 1 Python call per payment. Caveat: buyer and seller are the SAME InFlow account (sellerId `4c4ca2ad…`), so balance moves only by fees (inferred 3%); gross spend counted against cap |
| x402 paid, each route | Sandbox, local web via tunnel | Same | `INFLOW_ENVIRONMENT=sandbox inflow x402 pay <tunnel>/api/paid/<op> --sandbox --method POST --data '<fixture>' --scheme balance --network inflow:1 --interval 5` | 200 + `PAYMENT-RESPONSE`; one settlement | **PASS all 4 routes (01-10-26)** — ip-company tx `e3ede586-…`, enrich-email tx `6cb8abd9-…`, deep-research, outreach-draft tx `0a8d441b-…`: each `✓ Paid balance / inflow:1`, settled, result returned, 1 Python call per payment. 8 paid requests total (MPP + x402) → exactly 8 Python 200s. Gross spend $0.74; balance 20 → 19.9778 (fees only, same account). Script: `~/agent-paid-sandbox-checks.sh` |
| No match not charged | Sandbox, local web via tunnel | Same | `~/agent-paid-sandbox-checks.sh` step 7: MPP + x402 pay `enrich-email` with `nomatch@example.com` (mock no-match) | 404; no settlement | **PASS both (01-10-26)** — MPP: CLI `PAYMENT_NOT_ACCEPTED ... status 404`, body `{"error":"no_match"}` (tx `1ca9e450-…` approved but never broadcast); x402: 404, not settled. 2 Python calls → 404. Balance 19.9778 before and after (no charge) |
| Duplicate / retry | Sandbox, local web via tunnel | Same | Script step 8: `inflow mpp pay` ip-company with `--credential-file`, then `curl` replay of the same `Authorization: Payment …` | No second charge, no result | **PASS (01-10-26)** — first pay tx `5035eebe-…` settled 200; replay → HTTP 402; balance 19.9772 before and after replay; Python ip-company calls = 3 total (replay never reached fulfillment). x402 same-payment-id replay not exercised (CLI payment-id format unverified) — residual |
| Buyer reference check | Production, Locus Apollo endpoint | Production account; explicit spend authorization (proposed ≤ $0.10) | `inflow mpp pay` or `inflow x402 pay` against Locus | 200 enrichment | Pending |
| Buyer application check | Production, Beam internal buy route → Locus | Same; flag on only for the test | Trigger enricher fallback with one test email | Paid result, caps enforced, cost logged | Pending |
| Deployed Seller check | Vercel production + Railway | Deploy authorization | Repeat MPP + x402 pay per route | As local | Pending |

Local, preview, and production results recorded separately. Pending authorization is not a pass.
