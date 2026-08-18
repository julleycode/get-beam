# Agent fetch beacon (Cloudflare Worker) — **lab only**

**Not GetBeam PROD.** This Worker is routed only at the test customer site
`splittrip.nhantown.com`. It POSTs to `https://beam-api.nhantown.com` with
`BEAM_SITE_ID=site_e3a2c56e01ed`. GetBeam production (`getbeam.fyi`) beacons via
**Vercel Edge middleware** (`apps/web/src/middleware.ts`) to `api.getbeam.fyi`.
Confirmed with the operator 2026-08-18.

Makes an AI that does **not** run JavaScript visible on Beam's Agents tab (for
the site this Worker is routed to).

## Canonical Cloudflare target (pinned 09-08-26, scope clarified 18-08-26)

| Field | Value |
|---|---|
| **Account Worker name** | `beam-agent-beacon-splittrip` |
| Worker id (tag) | `9e74d04215224c4ab2cecc3e65939d21` |
| Source | `infra/cloudflare/agent-beacon-worker/` |
| Wrangler base `name` | `beam-agent-beacon` |
| Deploy env | `splittrip` → Cloudflare names the script `{name}-{env}` |
| Route | `splittrip.nhantown.com/*` (zone `nhantown.com`) |

**Rule for agents / MCP / deploy:** when listing Workers, fetching Worker details, reading builds, or pushing a deploy for this beacon path, always target **`beam-agent-beacon-splittrip`**. Do **not** use `quota-tracker` (unrelated account Worker) or the bare base name `beam-agent-beacon` without `--env splittrip`.

Deploy / secret commands must use `--env splittrip` (see below). Cloudflare MCP `workers_get_worker` / builds tools: pass name or id of `beam-agent-beacon-splittrip`.

## Why the pixel is not enough

`ChatGPT-User`, `Claude-User` and `Perplexity-User` fetch a page's HTML when a
person asks an assistant about it, then leave. They never execute the Beam
pixel, so the pixel path cannot see them — no configuration changes that. The
only component that observes the request is whatever sits in front of the
origin. On Cloudflare, that is a Worker.

This is a structural limit, documented in `docs/agent-detection-architecture.md`
§2: for a customer site running only the pixel, index-tier crawlers are
essentially invisible.

## Deploy

```bash
cd infra/cloudflare/agent-beacon-worker
npx wrangler secret put BEAM_FETCH_BEACON_SECRET --env splittrip   # paste the API's value
npx wrangler deploy --env splittrip
# Resulting Cloudflare script name: beam-agent-beacon-splittrip
```

The API side must already have:

```dotenv
AGENT_FETCH_BEACON_ENABLED=true
BEAM_FETCH_BEACON_SECRET=<same value>
```

With the flag off the endpoint answers **404** (dormant, not revealed). With the
secret empty it answers **401** — an empty configured secret is rejected before
the constant-time compare, because `compare_digest('', '')` returns true and
would otherwise accept an empty header.

## Verify without waiting for a real AI

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  -H 'content-type: application/json' \
  -H 'x-beam-fetch-secret: <secret>' \
  -d '{"site_id":"site_e3a2c56e01ed","user_agent":"ChatGPT-User/1.0","path":"/"}' \
  https://beam-api.nhantown.com/api/v1/agents/fetch-beacon
```

| Response | Meaning |
|---|---|
| `202` | Written — a row is on the Agents tab |
| `204` | Recognised call, unrecognised User-Agent — nothing written, by design |
| `401` | Wrong or missing secret |
| `404` | `AGENT_FETCH_BEACON_ENABLED` is false |

Then confirm the Worker itself is wired, from outside:

```bash
curl -s -o /dev/null -H 'User-Agent: ChatGPT-User/1.0' https://splittrip.nhantown.com/
```

A row for vendor `openai` should appear on the Agents tab within seconds.

## What the verification column will say

A forged `ChatGPT-User` header sent from your own machine records as
**`ip-mismatch`** — OpenAI publishes IP ranges and your address is not in them.
That is the spoof detector working, not an error. A real ChatGPT fetch arrives
from a published range and records as `ip-verified`. Anthropic publishes no
ranges at all, so its traffic can never exceed `ua-only`; that ceiling is
deliberate, since absence of evidence is not evidence of forgery.

## Scope

Only **on-demand** tokens are beaconed — the ones that mean a person is waiting
on the answer right now. Index crawlers are excluded on purpose: reporting them
would bury the human-intent signal under routine robot traffic. Keep the token
list in sync with `_ON_DEMAND_TOKENS` in
`apps/api/services/agent_classifier.py`; the API silently 204s anything it does
not recognise, so drift costs signal without raising an error.
