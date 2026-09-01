# Agent fetch beacon (Cloudflare Worker) — RETIRED

**Do not `wrangler deploy` this directory.** GetBeam production fetch-beacon
runs in Next.js middleware on `getbeam.fyi` (`apps/web/src/lib/fetch-beacon.ts`),
not this Worker.

This folder is kept as reference for the on-demand UA beacon logic only.
The Cloudflare script `beam-agent-beacon-splittrip` was deleted from the
account on 01-09-26 (routes were already unbound).

## Retired lab binding

A Cloudflare env named `splittrip` used to attach a Worker route on a
**third-party** hostname. That route is removed from `wrangler.toml`.

- Do not re-add a Worker route on that hostname from GetBeam.
- Do not delete that hostname's CNAME/A — it is not a GetBeam DNS record.

## Why the pixel is not enough

`ChatGPT-User`, `Claude-User` and `Perplexity-User` fetch a page's HTML when a
person asks an assistant about it, then leave. They never execute the Beam
pixel, so the pixel path cannot see them. The only component that observes the
request is whatever sits in front of the origin (Worker or Pages Functions).

PROD: `apps/web/src/middleware.ts` + `BEAM_API_BASE` on Vercel.

## Local API check (not this Worker)

If `AGENT_FETCH_BEACON_ENABLED=true` on a local API:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  -H 'content-type: application/json' \
  -H 'x-beam-fetch-secret: <secret>' \
  -d '{"site_id":"site_e3a2c56e01ed","user_agent":"ChatGPT-User/1.0","path":"/"}' \
  http://localhost:8000/api/v1/agents/fetch-beacon
```

| Response | Meaning |
|---|---|
| `202` | Written — a row is on the Agents tab |
| `204` | Recognised call, unrecognised User-Agent — nothing written, by design |
| `401` | Wrong or missing secret |
| `404` | `AGENT_FETCH_BEACON_ENABLED` is false |

## Scope

Only **on-demand** tokens are beaconed. Keep the token list in sync with
`_ON_DEMAND_TOKENS` in `apps/api/services/agent_classifier.py`.
