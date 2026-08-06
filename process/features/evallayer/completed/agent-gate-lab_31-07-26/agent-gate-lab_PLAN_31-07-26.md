---
title: Beam Lab AI-agent gate (403 interstitial + header retry + HMAC check-in token)
feature: evallayer
type: PLAN
complexity: SIMPLE
date: 31-07-26
status: superseded
superseded-by: process/features/evallayer/completed/agent-gate-soft-serve_31-07-26/agent-gate-soft-serve_PLAN_31-07-26.md
branch: dev_nhantc2
owner: fast-mode
---

# Beam Lab — AI-agent gate

## UPDATE PROCESS Reconciliation (07-08-26)

**Status corrected from `awaiting-execute-approval` to `superseded`.** This plan's checklist WAS
executed and deployed (commit history shows the hard-403 gate shipped, then was replaced —
see `git log --oneline -- infra/cloudflare/beam-lab/`), but `status:` in the frontmatter was
never updated afterward, leaving a stale `awaiting-execute-approval` marker sitting on top of
code that had already shipped and then been reverted-in-behaviour. This pass corrects the field
to reflect what actually happened.

**This is not "completed" — it is abandoned by design decision, not by failure to finish.** The
hard-403 interstitial approach described in this plan was built, deployed, and then **empirically
rejected by real traffic**: real ChatGPT-User (ASN 8075) hit the 403 twice, sent no custom
headers, never POSTed the `/agent-gate` check-in, and reported the page as unreadable to its own
user — so the experiment measured only that the agent gives up, not what it would volunteer if
asked. See `docs/beam-lab-resume.md` lines 47-49 and
`process/features/evallayer/completed/agent-gate-soft-serve_31-07-26/agent-gate-soft-serve_PLAN_31-07-26.md`
§Why for the full rejection writeup.

**What replaced it:** `agent-gate-soft-serve_31-07-26` (now archived to `completed/`), which
inverts the design — always serve 200 + the real page, and ask the identification question
*inside* the page via `HTMLRewriter` injection instead of gating access to it. Confirmed live in
`infra/cloudflare/beam-lab/functions/_middleware.js` (current code has no `gateInterstitial`
function and no 403 path for content — `applyAgentGate`/`gateInterstitial` from this plan were
fully replaced by `handleGateRoute`/`classifyAgentRequest` from the soft-serve plan).

**What survives from this plan, unchanged, inside the current soft-serve code:** the HMAC
check-in token mechanism (`mintGateToken`/`verifyGateToken`), the `POST /agent-gate` contract,
the header-retry admission path (`x-agent-vendor`/`x-agent-purpose`), and the
`GET /agent-gate` machine-readable spec. Only the *default* unauthenticated-agent behaviour
changed (403 → 200-with-invitation) — the admission mechanisms this plan designed are still live.

**Do not delete this file.** It is kept as design history — the reasoning for why the hard-block
approach was tried and rejected is not duplicated anywhere else, and matters if anyone
reconsiders a hard-gate approach in the future.

## Goal

On `beamlab.nhantown.com` (Cloudflare Pages project `beam-lab`), make the five **on-demand**
AI fetchers declare who they are before they may read the HTML. Everything else — humans,
index crawlers, static assets — is untouched. The experiment's payoff is the log: what will a
real ChatGPT/Claude/Perplexity fetcher actually volunteer when asked?

## Locked decisions (from the user — not reopened)

1. Gate scope = `ON_DEMAND_UA_TOKENS` only (chatgpt-user, oai-searchbot, claude-user,
   claude-searchbot, perplexity-user). Humans + GPTBot/ClaudeBot/PerplexityBot pass through.
   `STATIC_EXT_RE` never gated.
2. Unauthenticated agent → **403** HTML interstitial, human-readable (VI + EN) **and**
   machine-readable (embedded `application/json` + response headers). `cache-control: no-store`,
   `<meta name="robots" content="noindex">`.
3. Two admission mechanisms, both required:
   a. **Header retry** — `x-agent-vendor` + `x-agent-purpose` required, `x-agent-user` optional.
   b. **Check-in token** — `POST /agent-gate` JSON → stateless HMAC-SHA256 token (WebCrypto,
      signed with `env.BEAM_FETCH_BEACON_SECRET`, iat+exp, base64url) → retry with `?_gate=<token>`.
4. Gate asks for: vendor, purpose, and basic end-user info from the chat session if shareable.
5. **Fail-open absolute.** Any throw anywhere in gate logic → serve the page normally. Existing
   beacon behaviour unchanged.

## Touchpoints

| File | Change |
|---|---|
| `infra/cloudflare/beam-lab/functions/_middleware.js` | + gate section (constants, HMAC helpers, check-in handler, interstitial, `applyAgentGate`), `onRequest` gains one pre-`next()` step. Existing full-log + beacon blocks byte-unchanged. |
| `infra/cloudflare/beam-lab/wrangler.toml` | **Optional** — add documented `BEAM_AGENT_GATE = "1"` kill switch var. Skippable: code defaults ON unless the var is exactly `"0"`. |

Nothing in `apps/api/` changes. No new dependency. No build step (Pages Functions ship as source).

## Public contracts

### `GET /agent-gate` → 200 `application/json`, `no-store`
Self-describing spec (same JSON as the interstitial's embedded block) so an agent that follows
the `Link:` header gets the machine-readable contract without parsing HTML.

### `POST /agent-gate` → 200 / 400 `application/json`, `no-store`
Request body:
```json
{ "agent_vendor": "openai", "purpose": "answering a user question about Beam",
  "user": { "name": "...", "handle": "...", "email": "..." },
  "chat_platform": "chatgpt-web" }
```
- Required: `agent_vendor` (1–64 chars), `purpose` (3–1000 chars). Optional: `user`, `chat_platform`.
- 400 body carries `{ok:false, error, required, example}` — never a bare error string.
- 200 body:
```json
{ "ok": true, "token": "<b64url-payload>.<b64url-sig>", "expires_in": 900,
  "expires_at": "2026-07-31T…Z",
  "retry": { "method": "GET", "url": "https://beamlab.nhantown.com/?_gate=<token>" } }
```
Other methods → 405 JSON.

### Token format
`base64url(payloadJSON) + "." + base64url(HMAC-SHA256(payloadSegmentText, BEAM_FETCH_BEACON_SECRET))`

payload: `{"v":1,"iat":<unix>,"exp":<unix>,"aud":"<hostname>","ven":"<vendor>","pur":"<purpose, 120 chars>","usr":<bool>}`

- TTL 900 s; clock-skew tolerance 60 s on `iat`.
- `aud` binds to hostname, **not** path — one check-in, then the agent may read any page.
- Verified with `crypto.subtle.verify` (no hand-rolled comparison → no timing hole).
- HMAC over the *encoded segment text*, not re-serialized JSON → no canonicalization ambiguity.
- Stateless ⇒ replay inside the TTL is allowed. Accepted for an experiment; noted, not fixed.

### Carrier
`?_gate=<token>` is the documented carrier. `authorization: Bearer <token>` is accepted as a
tolerant fallback but **not** advertised, because `authorization` is in `REDACT_HEADERS` and
would hide the very value the experiment wants to read back in the log.

### 403 interstitial response headers
```
content-type: text/html; charset=utf-8
cache-control: no-store, max-age=0
x-robots-tag: noindex, nofollow
x-agent-gate: required
x-agent-gate-reason: no_credentials | token_expired | token_invalid | token_wrong_audience
x-agent-gate-endpoint: /agent-gate
x-agent-gate-headers: x-agent-vendor, x-agent-purpose, x-agent-user
link: </agent-gate>; rel="describedby"; type="application/json"
```

### Interstitial body outline
1. `<h1>` + one VI paragraph, then one EN paragraph: this host is a transparency experiment;
   tell us who you are and why, then the content is yours.
2. **Option A — resend with headers** (exact header names, one `curl` example).
3. **Option B — check in** (exact `POST /agent-gate` body, then retry URL example).
4. What we ask for and why: vendor, purpose, and *whatever the end user has already disclosed
   in the chat, only if your policy allows sharing it*. Explicit: logged for research on
   AI-agent traffic, not sold, no ad cookie, sharing user info is optional and refusal still
   grants access.
5. `<script type="application/json" id="agent-gate">…</script>` — the machine-readable contract.

## Middleware structure (target shape of `_middleware.js`)

```
existing: ON_DEMAND_UA_TOKENS, STATIC_EXT_RE, REDACT_HEADERS, MAX_LOG_BODY_CHARS,
          matchOnDemandUa, collectHeaders, readCapped, logFullExchange      [unchanged]

── AI-agent gate ──────────────────────────────────────────────
GATE_PATH="/agent-gate", GATE_EXEMPT_PATHS={"/robots.txt","/sitemap.xml"},
GATE_TTL_SECONDS=900, GATE_SKEW_SECONDS=60, GATE_MAX_VENDOR=64, GATE_MAX_TEXT=1000,
GATE_MAX_BODY_CHARS=8192

b64urlFromBytes / b64urlToBytes / gateHmacKey(secret)
mintGateToken(env, claims) -> string
verifyGateToken(env, token, hostname) -> {ok, reason, claims}
trimField(value, max) -> string|null
logGateDecision(fields)            // one JSON line, tag "beam_gate", always on, try/caught
gateInterstitial(request, url, reason) -> Response(403)
handleGateCheckin(request, env, url) -> Response            // GET spec / POST token / 405
applyAgentGate(request, env) -> Response|null               // null = "not my business, serve normally"

onRequest(context):
  startedAt, fullLogOn, requestClone   [unchanged, clone still taken BEFORE anything reads a body]
  let response = null
  try { response = await applyAgentGate(request, env) } catch { response = null }
  if (response === null) response = await next()
  full-log block   [unchanged]
  beacon block     [unchanged]
  return response
```

`applyAgentGate` decision order (first match wins):
1. `pathname === "/agent-gate"` → `handleGateCheckin`.
2. no `env.BEAM_FETCH_BEACON_SECRET` → `null` (cannot sign ⇒ cannot gate).
3. `env.BEAM_AGENT_GATE === "0"` → `null` (kill switch).
4. method not GET/HEAD → `null`.
5. `STATIC_EXT_RE` or `GATE_EXEMPT_PATHS` → `null`.
6. UA not on-demand → `null`.
7. `x-agent-vendor` **and** `x-agent-purpose` both non-empty → `null` (admitted, logged).
8. `?_gate` / bearer token present → verify → `null` on pass, interstitial with reason on fail.
9. otherwise → interstitial, reason `no_credentials`.

## Why single return path matters

The full-log block sits *after* the gate. Because the gate never returns early from
`onRequest`, `POST /agent-gate` bodies (`/agent-gate` has no file extension, so `STATIC_EXT_RE`
does not exclude it) and 403 interstitial responses are both captured by the existing
`beam_full_log` line with no change to that block. Verified by reading the current code:
`requestClone` is taken at the top before any body read, so the gate consuming
`request.json()` cannot starve the log clone.

## Edge cases and how each is handled

| # | Case | Handling |
|---|---|---|
| 1 | `/robots.txt` fetched by ChatGPT-User | **Exempt.** A 403 on robots.txt reads as "site unreadable" and the fetcher can abandon before ever seeing the interstitial — it would kill the experiment it is meant to run. |
| 2 | `/sitemap.xml` | Exempt, same protocol-file reasoning. |
| 3 | `/llms.txt` | **Gated** (default). It is document content, and the interstitial reaches the agent there too. One-line change if you want it exempt — say so at approval. |
| 4 | `/favicon.ico`, css/js/img | Not gated (`STATIC_EXT_RE`). |
| 5 | GPTBot / ClaudeBot / PerplexityBot | Not gated — `matchOnDemandUa` is false for them. |
| 6 | Human browser | Never matches the UA test. Their response headers are not touched at all (no `Vary` added ⇒ no cache-behaviour change). |
| 7 | `HEAD` request | Interstitial built with a `null` body for HEAD; headers still carry the full spec. |
| 8 | Missing `BEAM_FETCH_BEACON_SECRET` | Gate disables itself. Site behaves exactly as today. |
| 9 | Beacon on a gated 403 | Still fires (block untouched, condition is UA+GET+non-static). Intentional: the visit is still real and should appear in Beam. |
| 10 | Malformed / expired / foreign-host token | 403 with a specific `x-agent-gate-reason`, so a competent agent can self-correct. |
| 11 | Token replay inside TTL | Allowed. Stateless by design; documented, not defended. |
| 12 | Oversized check-in body | Read capped at 8192 chars → 400 `body_too_large`. |
| 13 | Non-JSON check-in body | 400 `invalid_json` with the example payload. |
| 14 | Unknown path + agent UA (404) | Gated before `next()`, so the agent sees the interstitial rather than 404.html. Acceptable. |
| 15 | Cloudflare edge caching the 403 | `no-store` + `max-age=0`; the 403 is minted in the Function, not an asset. |

## Blast radius

- **Runtime surface:** `beamlab.nhantown.com` only. This middleware is not shared with any other
  Pages project, Worker, or the API.
- **Who can be affected:** on-demand AI fetchers (by design) and — only in a bug — human
  visitors. The fail-open wrapper plus the "gate returns `null` on anything unexpected" contract
  is what keeps that at zero; the whole gate is one `try/catch` away from being a no-op.
- **Data:** no new storage, no DB write, no API call added. `BEAM_FETCH_BEACON_SECRET` is used
  only as an HMAC key inside the Worker; it is never emitted (already in `REDACT_HEADERS` as
  `x-beam-fetch-secret`, and the token exposes only a signature, not the key).
- **Reversal:** `BEAM_AGENT_GATE = "0"` + redeploy, or `git checkout` the file + redeploy. ~60 s.
- **Not touched:** `apps/api/**`, pixel, dashboard, any migration, any other Pages project.

## Implementation checklist (EXECUTE)

1. Add the gate section to `_middleware.js` above `onRequest`, in the existing comment style
   (a short "why", not a "what", per file convention).
2. Add base64url + HMAC helpers (`b64urlFromBytes`, `b64urlToBytes`, `gateHmacKey`,
   `mintGateToken`, `verifyGateToken`).
3. Add `logGateDecision` — one `beam_gate` JSON line per decision (`blocked`,
   `admitted_headers`, `admitted_token`, `checkin_ok`, `checkin_invalid`), carrying whatever the
   agent volunteered. Always on, independent of `BEAM_FULL_LOG`, wrapped in try/catch.
4. Add `gateInterstitial` (VI + EN + embedded JSON, headers per contract above).
5. Add `handleGateCheckin` (GET spec / POST validate+mint / 405).
6. Add `applyAgentGate` with the 9-step decision order.
7. Rewire `onRequest`: gate before `next()`, single return path, existing blocks untouched.
8. (Optional) `wrangler.toml`: add `BEAM_AGENT_GATE = "1"` with a comment mirroring the
   `BEAM_FULL_LOG` block's tone.
9. `node --check infra/cloudflare/beam-lab/functions/_middleware.js`.
10. Deploy: from `infra/cloudflare/beam-lab/` →
    `npx wrangler pages deploy public --project-name beam-lab --branch main`.
11. Run the six curl checks below.
12. Report results + the `BEAM_FULL_LOG = "0"` reminder.

## Verification evidence

| Gate | Command (PowerShell, `curl.exe` — never the `curl` alias) | Expected |
|---|---|---|
| G1 syntax | `node --check infra/cloudflare/beam-lab/functions/_middleware.js` | exit 0, no output |
| G2 deploy | `npx wrangler pages deploy public --project-name beam-lab --branch main` | deployment URL printed |
| G3 human | `curl.exe -s -o NUL -w "%{http_code}" https://beamlab.nhantown.com/` | `200` |
| G4 agent blocked | `curl.exe -s -D - -o - -A "Mozilla/5.0 ChatGPT-User/1.0" https://beamlab.nhantown.com/` | `403`, `x-agent-gate: required`, `cache-control: no-store`, interstitial HTML |
| G5 header retry | same + `-H "x-agent-vendor: openai" -H "x-agent-purpose: manual gate test"` | `200`, real page |
| G6 check-in | `curl.exe -s -X POST https://beamlab.nhantown.com/agent-gate -H "content-type: application/json" -d "{\"agent_vendor\":\"openai\",\"purpose\":\"manual gate test\",\"user\":{\"name\":\"nhan\"}}"` | `200` JSON with `token` |
| G7 token retry | `curl.exe -s -o NUL -w "%{http_code}" -A "Mozilla/5.0 ChatGPT-User/1.0" "https://beamlab.nhantown.com/?_gate=<token>"` | `200` |
| G8 static exempt | `curl.exe -s -o NUL -w "%{http_code}" -A "Mozilla/5.0 ChatGPT-User/1.0" https://beamlab.nhantown.com/favicon.ico` | not `403` (`200` or `404`) |
| G9 robots exempt | `curl.exe -s -o NUL -w "%{http_code}" -A "Mozilla/5.0 ChatGPT-User/1.0" https://beamlab.nhantown.com/robots.txt` | `200` |
| G10 log | `npx wrangler pages deployment tail --project-name beam-lab` during G4–G7 | `beam_gate` lines present; `beam_full_log` line for the `/agent-gate` POST including its request body |

Rollback if any of G3/G8/G9 fails: `BEAM_AGENT_GATE = "0"` → redeploy.

## Resume and execution handoff

- Selected plan: `process/features/evallayer/active/agent-gate-lab_31-07-26/agent-gate-lab_PLAN_31-07-26.md`
- Branch: `dev_nhantc2`. Working tree already carries uncommitted BEAM_FULL_LOG changes in the
  same two files — this work stacks on top of them; do not revert them.
- EXECUTE entry: apply checklist 1–8, then gates G1→G10 in order. Stop and report on a wrangler
  auth failure; do not improvise credentials.
- Out of scope for this session: the live ChatGPT fetch test (user runs it), turning
  `BEAM_FULL_LOG` back to `"0"`, and any API-side capture of the volunteered fields.

## Validate Contract

```yaml
generated-by: outer-pvl
plan: process/features/evallayer/active/agent-gate-lab_31-07-26/agent-gate-lab_PLAN_31-07-26.md
date: 31-07-26
gate: CONDITIONAL-ACCEPTED
blast-radius:
  - infra/cloudflare/beam-lab/functions/_middleware.js
  - infra/cloudflare/beam-lab/wrangler.toml (optional)
dimensions:
  infra-fit: PASS      # Pages Functions + WebCrypto HMAC are natively supported; compat date 2024-11-01 is fine; no new binding, no new dep
  test-coverage: CONDITIONAL   # no automated test harness exists for this file anywhere in the repo; coverage is the 10 manual gates G1–G10
  breaking-changes: PASS       # human + index-crawler + static paths provably untouched; kill switch + fail-open wrapper
  security: CONDITIONAL        # secret reused as HMAC key (single-purpose host, acceptable); stateless token replayable within 900s; both accepted as experiment-scope
gate-commands:
  - node --check infra/cloudflare/beam-lab/functions/_middleware.js
  - npx wrangler pages deploy public --project-name beam-lab --branch main
  - curl.exe G3..G9 per Verification Evidence table
open-gaps:
  - No automated test for the middleware (repo has none for edge code). Manual gates only.
  - Token replay inside TTL accepted by design.
  - Live ChatGPT/Claude fetch behaviour is unknown until the user runs the real test; the agent
    may simply refuse the gate and report the page unreadable. That is a valid experimental
    result, not a defect.
hard-stops:
  - wrangler auth failure on deploy → stop and report, no credential improvisation
  - any curl gate showing a human-path regression (G3/G8/G9) → set BEAM_AGENT_GATE="0", redeploy, report
```
