# AEP integration plan

Guide: https://www.aep.foundation/integration.md (template:
https://www.aep.foundation/integration-queue-template.md). Running under the Directory
coordinator — see `COMMERCE-INTEGRATION-PLAN.md`. Executable plan, not a changelog.
Never record credentials, tokens, private keys, or personal claim values here.

## Goal and scope

- Target repository and application: `github.com/julleycode/get-beam`, local `~/get-beam`,
  branch `feat/agentic-commerce`. AEP Service hosted in `apps/api` (FastAPI, Railway) at origin
  `https://api.getbeam.fyi`; `apps/web` paid handler (Next.js 14, Vercel) verifies via Python.
- Selected SDK and version: Python `agent-enrollment-protocol==0.1.1` (aep-python tag v0.1.1,
  commit `11dea0d9`; Alpha) — exact pin re-verified at install (task 30).
- Specification revisions: aep-specs @ `7c1ee7d6` (2026-09-17): core -04, claims -01,
  did-web-identity-method -00, api-key-session-credential -04, platform-hosted-identity -01.
- Selected role: Service.
- Selected capabilities:
  - (a) Customer's agent: owner pre-registers an agent DID, assigns sites + scopes
    `read` / `spend` / `generate`; agent enrolls (active immediately when pre-registered, else
    `pending` + `owner_action_required`), grants an api-key, calls allow-listed site routes.
  - (b) Independent agents: auto-active enrollment; AEP identity OPTIONAL on `/api/paid/*`
    (verified before payment; attaches agent id for per-agent rate limits/attribution).
- Included work: inspect + DID document, Enroll/Status/Grant/Revoke, did:web verifier (ES256 +
  EdDSA), durable Postgres stores + Redis replay/idempotency, api-key grant (`x-beam-agent-key`,
  24h, salted hash, revocable), principal dependency + scope allow-list, owner dashboard page,
  paid-route integration, docs, verification.
- Explicitly excluded work: any send/approve/billing/BYOK/connector/site-mutation/delete/privacy/
  DSAR/export/CRM-Ads-push route for agents; oauth-bearer and basic grant types; `aep-jwt` on
  protected resources; Agent-application role; Platform role; ODP (next child); Payments changes
  beyond the optional identity hook; Buyer (paused).
- Completion criteria: all ordered tasks complete or approved-deferred; Project acceptance and
  InFlow acceptance below met (local / deployed recorded separately).

## Current assessment

Read-only assessment 01-10-26 (2 agents; no code changed, no secrets files read, no DB commands).

**Specs** (aep-specs @ `7c1ee7d6`, 2026-09-17; protocol `aep_version "1.0"`): core
draft-kavian-agent-enrollment-protocol-04; claims-01; did-web-identity-method-00;
api-key / basic / oauth session-credential -04; platform-hosted-identity-01.
- Inspect `GET /.well-known/aep` (unauthenticated, `application/aep+json`); `service.did`
  (did:web) origin MUST equal the Inspect URL origin; same-origin redirects only.
- Commands under `http.endpoint_base` (default `/aep/`): Enroll, Status, Grant, Revoke;
  baseline `Authorization: AEP <JWS>` (EdDSA + ES256 required; `aud`=service.did; `op`;
  `exp-iat` ≤ 300s; replay cache on (sub, jti)); `Idempotency-Key` mandatory on
  Enroll/Grant/Revoke (≥1h cache, 409 on mismatch).
- Only identity method: `did:web` (platform-hosted identities are did:web too).
- Lifecycle: active / pending / unavailable / suspended / terminated / rejected. Owner action =
  `owner_action_required:"true"` flag only — **approval UX is Service-defined, out-of-band**;
  the Agent polls Status.
- Claims (contact.email, contact.mobile, person.*) are **unverified** assertions.
- Session credentials: api-key (≥128-bit, Service-chosen header, MUST expire, salted hash stored),
  oauth-bearer, basic; all need `credential_id`, `expires_at`, Revoke support.
- Protected resources advertise `authentication.methods`; anonymous → `401`
  `WWW-Authenticate: AEP service_did=…,inspect=…`; `insufficient_scope` 403; authN ≠ authZ.
- **Composition with MPP/x402 explicitly allowed:** AEP credential in `AEP-Authorization` (or the
  api-key header) next to `Authorization: Payment` / `PAYMENT-SIGNATURE`; AEP auth runs **before**
  payment; AEP layer must not touch the payment header.

**SDKs**
- aep-python `agent-enrollment-protocol` 0.1.1 (Alpha, Py ≥3.11, ASGI-only adapter):
  `Service(ServiceOptions)` with ports (verifier, enrollment/idempotency/replay/credential stores,
  enrollment policy, grant types); **no did:web verifier, only in-memory stores, no owner-approval
  hook**; passes `Authorization: Payment` through.
- aep-node `@aep-foundation/service` 0.3.4 (+ core 0.6.0): did:web + hosted-platform verifiers;
  in-memory stores only; `@aep-foundation/next` needs Next ≥15 (Beam is 14.2).
- Reference: inflow-node `examples/mpp-aep-seller-express` — api-key grant in header
  `x-aep-api-key`; per-route `requireAep` → `mppx.charge` → handler.
- InFlow CLI agents: `did:web:sandbox.inflowpay.ai:agents/{id}`, **ES256 only**; requests carry
  TAP `Signature`/`Signature-Input`/`Content-Digest` headers. CLI: `inflow aep
  inspect|enroll|status|grant|fetch|revoke` (vault, developer-run).

**Repository** (paths under `apps/api/` unless noted)

| Area | Current behavior | Evidence | Implication |
| ---- | ---------------- | -------- | ----------- |
| User auth | `HTTPBearer`; Clerk RS256 → else legacy HS256; each call runs `record_user_activity` (auto-resumes paused sites) | `dependencies.py:24,241-413,359-362` | Separate principal dependency; skip activity side-effects for agents |
| Tenancy | Single owner per site; no orgs/roles except `is_admin`; `verify_site_access` → 404 | `dependencies.py:30-44`; `models/site.py:15-16` | Grant carries explicit site allow-list |
| Inbound machine creds | None (BYOK keys outbound; shared secrets only) | `models/api_key.py`; `routers/agents.py:37-79` | New tables for agents + credentials |
| Approval UX precedent | Only Beam-as-OAuth-client flows; Redis one-time state; append-only consent table | `services/oauth_state.py:21-104`; `models/identity_coop.py:179-205`; `/dashboard/agent-gateway` | Build owner-approval page + audit trail |
| Candidate ops (a) | Read: sites, visitors, segments, campaigns, agent analytics, companies. Spend: resolve one visitor, deep research. Generate: run segmentation, campaign plan (draft), ai/ask (site required) | `routers/sites.py`; `visitors.py:69,671,825,883`; `segments.py:21,65`; `campaigns.py:66,85`; `agents.py:82-196`; `ai.py:156` | Scope-gated allow-list |
| Must NOT expose | Sends/approvals (campaign status PATCH, start, send, test-send, LinkedIn; draft approve/retry), billing, BYOK, connectors, site create/patch/delete, deletes, privacy/erasure, DSAR, CRM/Ads push, contacts import | `campaigns.py:58-63,321,430,555,634,826,946`; `drafts.py:258,345` | Guardrail "never auto-send" |
| Paid routes (b) | MPP uses `Authorization` + 402 `WWW-Authenticate`; Python sees only client IP | `apps/web/src/lib/payments/paid-handler.ts:300-322,421-448,169-180` | AEP via `AEP-Authorization` / api-key header, before payment; forward `x-beam-agent-id` |
| Persistence | Postgres (UUID base; Alembic head `c5a91f3e07d4`); Redis (limiter, budgets, state; some in-memory fallbacks) | `models/database.py:81-88`; `services/redis_client.py` | Durable Postgres stores; Redis replay/idempotency failing closed |
| Origins | Dashboard API `api.getbeam.fyi` (FastAPI); paid routes `getbeam.fyi` (Next); no `.well-known` on API | `config.py:267-273`; `apps/web/src/app/.well-known/` | Service origin / DID decision |
| Tests | Auth unit/integration tests; e2e uses legacy HS256 login | `tests/unit/test_agent_paid_internal.py`; `apps/web/e2e/auth.setup.ts` | Add principal/scope tests; keep e2e green |

## Sources and unresolved questions

| Requirement or fact | Authoritative source and version | Implementation boundary |
| ------------------- | -------------------------------- | ----------------------- |
| AEP docs / specs | https://www.aep.foundation/documentation/, https://www.aep.foundation/protocol/ (revisions to record in assessment) | — |

| Unresolved question | Evidence and context | Options and recommendation | Decision |
| ------------------- | -------------------- | -------------------------- | -------- |
| aep-python 0.1.1 on FastAPI | **Spike PASS (01-10-26)**, scratch `aep-spike/` (43 ASGI checks + real-socket loopback with SDK `Agent`): Inspect (`application/aep+json`, did:web:api.getbeam.fyi, EdDSA+ES256, api-key `x-beam-agent-key`, `supports_per_credential_revoke`), Enroll pre-registered→active / unknown→pending+owner_action_required, Status, Grant (api_key, header, credential_id, expires_at 24h, scopes), Revoke; per-route `authenticate_protected_resource` dependency (401 `WWW-Authenticate: AEP service_did=…,inspect=…`; invalid/revoked/expired → 401 `not_recognized`; valid → principal with agent_did, credential_id, scopes); `Authorization: Payment` untouched; TAP headers ignored; replayed jti 401; idempotency replay identical, mismatch 409, missing key 400. Ports/records cited in spike notes (types.py:55-269, service.py:171-176,363-424, asgi.py:53-111) | Proceed with design below | Resolved |
| **SDK dependency floor vs Beam pins** | SDK requires pydantic ≥2.13.4, httpx ≥0.28.1, cryptography ≥50.0.1,<51, pyjwt ≥2.13; Beam pins pydantic[email]==2.9.2, httpx==0.27.2, cryptography==44.0.0 (`requirements.txt:12,19,22`) → unresolvable together; resolves with those 3 bumped (fastapi 0.115.0, python-jose 3.3.0, anthropic 0.43.0 unchanged). No `proxies=` / `AsyncClient(app=)` usages found in apps/tests (httpx 0.28 removals) | New task 15: bump the 3 pins alone, run full unit + integration + e2e, then continue | **Pending developer approval** (scope change) |
| did:web verification of InFlow-hosted agents (ES256) | SDK ships no verifier; example lacks SSRF guard, cache, assertionMethod and alg/key-type checks | Beam verifier: HTTPS only, no redirects, public-IP only with resolved-IP pinning (DNS rebinding), 64 KB cap, 300s cache, assertionMethod + alg/key-type checks | Task 30 |
| SDK behaviors to design around | (1) any `Authorization: Bearer` is treated as an AEP credential → call AEP auth only when `x-beam-agent-key` is present, Clerk otherwise; (2) Grant idempotency replay stores plaintext api_key → encrypt idempotency bodies at rest, short TTL ≥1h; (3) Enroll replay may show stale `pending` ≤1h (Status is authoritative); (4) policy runs only on first enroll; no approve/reject API → Beam writes the store; (5) jti consumed before idempotency/validation; (6) Starlette 0.38 middleware needs a small adapter, add inside CORS/body-size; `app.mount` unusable; (7) resource URL from configured origin, never Host; (8) stores must filter expiry with request `current_time` (else 500); (9) SDK does not enforce scopes — route must | Spike notes | Tasks 20–40 |
| Local verification needs `service.did` origin = Inspect origin | did:web binds to origin | `AEP_SERVICE_ORIGIN` config; local checks via a temporary HTTPS tunnel to the api | Pending — task 80 |
| Live Railway replica count; Redis availability in prod | Unverified | Stores must be multi-replica safe; Redis fail closed | Verify at deploy |

## Decisions

| Decision | Rationale | Approval |
| -------- | --------- | -------- |
| Coordinated mode: skip repeated welcome; reuse coordinator answers (repo, branch, skip RIPER-5 ceremony) | Directory guide rule | Coordinator (30-09-26) |
| Payments Buyer paused; proceed to AEP | Developer: "tạm pending chỗ buyer, làm AEP tiếp đi" | Developer (01-10-26) |
| Role Service; goals (a) + (b); new integration | Interview | Developer (01-10-26) |
| Scopes `read` / `spend` / `generate`; permanent deny-list (sends, approvals, billing, BYOK, connectors, site mutation, deletes, privacy/erasure, DSAR, exports, CRM/Ads push, contacts import) | Guardrail "never auto-send"; assessment evidence | Developer "defaults ok" (01-10-26) |
| Owner pre-registers agent DID + sites + scopes; unknown DIDs → `pending`; claimed email only a hint; owner can revoke | Claims are unverified per spec | Developer "defaults ok" (01-10-26) |
| AEP optional on `/api/paid/*`, verified before payment | Keeps anonymous paid access; spec composition rules | Developer "defaults ok" (01-10-26) |
| Python Service at `api.getbeam.fyi`, DID `did:web:api.getbeam.fyi` | Shares Postgres/Redis | Developer "defaults ok" (01-10-26) |
| api-key grant only, header `x-beam-agent-key`, 24h expiry, salted hash, revocable | Spec api-key draft; InFlow example pattern | Developer "defaults ok" (01-10-26) |

## Active work

- Stage: Implementation (plan approved 01-10-26: "approve, go")
- State: In progress
- Current task: 20 done
- Next action: task 30 — AEP Service module (stores, did:web verifier, policy, api-key grant, routes; flag OFF)
- Approval needed: schema migration (task 20) touches production DB only at deploy (task 90)

## Ordered tasks

| Order | State | Task | Dependencies | Output | Verification | Approval needed |
| ----- | ----- | ---- | ------------ | ------ | ------------ | --------------- |
| 10 | Done (01-10-26) — PASS; dependency floor conflict found | **Spike (scratch, not merged):** aep-python 0.1.1 in a throwaway venv with FastAPI: mount `AepAsgiApplication`; per-route `authenticate_protected_resource`; did:web ES256 + EdDSA verifier against a locally served did.json; confirm `Authorization: Payment` and TAP headers pass through; record exact SDK call formats with file:line | Plan approval | Findings in Sources table | Inspect/enroll/grant round trip with a locally generated did:web key | Plan approval |
| 15 | Done (01-10-26) — pins bumped: pydantic[email] 2.13.5, cryptography 50.0.2, pyjwt 2.15.1 (new), httpx 0.28.1; fresh venv `~/.venvs/get-beam` (outside repo; `.venv` is not gitignored here) + pytest 8.3.3 / pytest-asyncio 0.24.0 / fakeredis 2.35.1; unit 3101 passed / 2 skipped / 0 failed; app import ok (217 routes, pydantic DeprecationWarning-as-error clean); integration 664 passed / 21 failed / 5 skipped — failures = pre-existing canary family (incl. `test_demo_canary_public` failing identically on old deps: `geo.city` empty) + `test_referrals::test_no_events_no_reward` and `test_outcome_digest::test_sends_once_stamps_and_throttles`, which pass in isolation on BOTH old and new deps (order-dependent) → no regression; e2e (clean worktree, new deps): 44 passed / 18 failed / 8 skipped — identical to pre-bump branch run; diff vs base only the known flaky connectors-ads tests → no regression | **Dependency bump (isolated):** `requirements.txt` pydantic[email] 2.9.2→≥2.13.4, httpx 0.27.2→≥0.28.1, cryptography 44.0.0→50.x, add pyjwt ≥2.13 (exact pins from lock); no AEP code in this task | 10 | requirements change | Full unit + integration (local PG) + e2e vs base; app boot | Developer approval |
| 20 | Done (01-10-26) — `apps/api/models/aep.py` (6 tables), migration `6078903ea368` (down_revision `c5a91f3e07d4`); disposable PG round trip upgrade(empty→head, 82 revisions)/downgrade -1/upgrade OK; autogenerate drift 0 for aep tables; unit 3115 passed; integration `test_aep_models_db.py` 16 passed | **Data model + migration** (spike-refined: `aep_enrollments` with Beam owner/pre-registration fields; `aep_credentials` with HMAC secret_hash, header_name, last_used_at; `aep_idempotency` with in_flight/done state + encrypted body; Redis jti replay `SET NX EXAT` with Postgres fallback table): `aep_agents` (did, status, enrollment record JSON, claimed email as ciphertext + blind index), `aep_agent_authorizations` (owner user_id, agent did, site ids, scopes, status, approved_at, revoked_at), `aep_credentials` (credential_id, agent, salted key hash, scopes, expires_at, revoked_at), `aep_idempotency` (agent_did, key, command, body hash, response, expires_at), `aep_audit_events` (append-only). Alembic migration chained on current head; Redis for replay (fail closed) | 10 | Models, migration | Local disposable PG: upgrade → downgrade → upgrade; unit tests | Plan approval |
| 30 | Not started | **AEP Service module:** `services/aep/` — Postgres stores implementing SDK ports; did:web verifier (HTTPS-only, public-IP-only resolution, timeouts, 64 KB cap, short cache); enrollment policy (pre-registered DID → `active` scoped to that owner; unknown → `pending` + `owner_action_required`; independent agents for paid use → `active` without site access); api-key grant (`x-beam-agent-key`, ≥128-bit, 24h, salted hash); serve `/.well-known/aep`, `/.well-known/did.json`, `/aep/*`; flag `aep_enabled` default OFF; `AEP_SERVICE_ORIGIN` config | 20 | Router + services + config | Unit tests incl. spec error codes, idempotency 409, replay rejection, expiry, revoke | Plan approval |
| 40 | Not started | **Principal + scope enforcement:** new `get_principal` dependency (user OR agent); agent path: credential → authorization → site allow-list (404 outside) → scope check (403 `insufficient_scope`); no `record_user_activity`; allow-list only the approved read/spend/generate routes; `ai/ask` requires `site_id` for agents; per-credential rate limit; AEP `WWW-Authenticate` challenge added only when no credential is present; browser/Clerk behavior unchanged | 30 | Dependency + route wiring | Unit + integration: cross-tenant, deny-list routes stay user-only, scope matrix, existing auth tests green | Plan approval |
| 50 | Not started | **Owner dashboard:** user-authed API (`/api/v1/aep/authorizations` CRUD, pending list, approve/reject, revoke credentials, audit list) + web page `/dashboard/agent-access` | 40 | API + page | Unit + vitest + manual check | Plan approval |
| 60 | Not started | **Paid routes (b):** Next paid handler: if `x-beam-agent-key` present → verify via Python `POST /internal/v1/aep/verify` (shared secret) BEFORE payment; invalid → AEP 401, no payment; valid → forward `x-beam-agent-id`; Python rate-limit keys on agent id; absent → unchanged | 30 | Web + Python changes | vitest + unit; existing paid tests green | Plan approval |
| 70 | Not started | **Docs:** `docs/aep-service.md` (flow, scopes, owner steps, env names, limits) + context pointer | 60 | Docs | Review | Plan approval |
| 80 | Not started | **Verification:** project acceptance + InFlow acceptance (local via tunnel, developer-run CLI) | 70 | Evidence | See Exit criteria | Enrollment/credential authorization |
| 90 | Not started | **Deploy dormant + deployed checks** (migration applies on Railway boot) | 80 | Deployment evidence | See Exit criteria | Deploy authorization |
| 100 | Not started | **Coordinator handoff** (record ODP follow-ups: advertise AEP requirement/identity on Offerings) | 80 | Coordinator updated | — | — |

## Review and verification

Seven-step template review applies to every implementation task.

## Risks and discovered work

| Finding | Impact | Evidence | Resolution or developer decision |
| ------- | ------ | -------- | -------------------------------- |
| Repo `.env` `DATABASE_URL` points at Supabase prod | Unpinned DB commands hit production | `process/context/all-context.md` | Pin local DSN for every DB command |
| InFlow CLI only works reliably when run by the developer (vault-daemon IPC timeout from agent shell) | `inflow aep …` acceptance checks need developer-run commands | Payments task 80 findings | Plan developer-run CLI steps |
| aep-python is Alpha (0.1.1); no did:web verifier or durable stores | Beam owns security-critical code | SDK assessment | Spike first; verify SDK formats against source (lesson from MPP bug) |
| `get_current_user` falls through non-RS256 tokens to HS256 | Token-confusion risk if AEP is added there | `dependencies.py:365-413` | Separate dependency; never accept agent keys in `Authorization: Bearer` |
| Campaign approval gate is a status PATCH | Agent scope must exclude it | `campaigns.py:58-63,321` | Deny-list |
| Drafts are user-scoped, not site-scoped | Doesn't map to site grants | `drafts.py:85` | Excluded from agent scopes |
| did:web resolution = outbound HTTP to attacker-chosen hosts | SSRF risk | Spec + architecture | HTTPS only, public IPs only, caps, timeouts |
| Two origins (`getbeam.fyi` paid, `api.getbeam.fyi` Service) | Discovery/audience binding | Assessment §origins | Paid routes' 401 challenge points `inspect=` at the api origin |
| `pii_crypto.encrypt_pii` stores plaintext when no PII/encryption key configured | Claimed email could be stored in clear | Task 20 agent finding | Task 30 store must refuse to write the email (store NULL) when ciphertext == plaintext / key absent |
| Models built by `create_all` in integration lane vs Alembic in prod | Drift risk | Task 20 drift check = 0 | Keep model + migration in sync; re-run drift check after changes |
| CF-Connecting-IP trusted on the api | IP must not bind identity | `config.py:267-273` | Identity only from credentials |

## Completion and handoff

Not started.

## Exit criteria

### Project acceptance

| Criterion | Command or procedure | Expected result | Result and evidence |
| --------- | -------------------- | --------------- | ------------------- |
| Backend unit suite | `PYTHONPATH=. .venv/bin/python -m pytest tests/unit -q` (sibling venv) | 0 failures; new AEP tests included | Pending |
| Backend integration suite | DSN pinned `localhost:5433`, `pytest tests/ -m integration -q` | No new failures vs base | Pending |
| Migration round trip | Disposable local PG: `alembic upgrade head` → `downgrade -1` → `upgrade head` (DSN pinned) | Clean | Pending |
| Web lint / tsc / vitest / build | Node 22 | Clean / 0 / all pass / ok | Pending |
| Web e2e regression | Clean worktree, CI-like env | No new failures vs base | Pending |
| Auth regression | Existing auth tests + new: Clerk/legacy users unaffected; agent cannot reach deny-list routes; cross-tenant 404 | As stated | Pending |
| Final diff review | All changed files | No drift | Pending |

### InFlow acceptance

CLI syntax re-verified against installed 0.13.0; developer runs CLI commands; no secrets logged.

| Criterion | Environment and target | Prerequisites and authorization | Command or procedure | Expected result | Result and evidence |
| --------- | ---------------------- | ------------------------------- | -------------------- | --------------- | ------------------- |
| Inspect | Local api via HTTPS tunnel (`AEP_SERVICE_ORIGIN` = tunnel origin) | `aep_enabled` on locally | `inflow aep inspect <tunnel> --sandbox --format json` | `application/aep+json`; did:web origin matches; api-key advertised | Pending |
| Enroll — unknown DID | Same | Authorization to enroll | `inflow aep enroll <tunnel> --sandbox` | `pending` + `owner_action_required` | Pending |
| Owner approval → active | Same | Owner action in local dashboard | Approve; `inflow aep status <tunnel> --sandbox` | `active` | Pending |
| Grant api-key | Same | Authorization | `inflow aep grant <tunnel> --sandbox --grant-type api-key --scope read` | Credential stored by CLI; `x-beam-agent-key`; 24h expiry | Pending |
| Protected resource | Same | — | `inflow aep fetch <tunnel>/api/v1/sites/ --sandbox` (+ a site-scoped read) | 200 for granted site; 404 other site; 403 for unscoped op | Pending |
| Missing / invalid credential | Same | — | `curl` without / with bogus key | 401 with `WWW-Authenticate: AEP …`; no data | Pending |
| Revoke | Same | Authorization | `inflow aep revoke <tunnel> --sandbox`; re-fetch | 401 after revoke | Pending |
| Paid route + AEP identity | Local web via tunnel | Sandbox spend ≤ $0.05 | MPP pay with `x-beam-agent-key` header | Payment settles; agent id attached; invalid key → 401 with no payment | Pending |
| Deployed | Railway + Vercel | Deploy authorization | Inspect + one enroll/grant/fetch against `api.getbeam.fyi` | As local | Pending |
