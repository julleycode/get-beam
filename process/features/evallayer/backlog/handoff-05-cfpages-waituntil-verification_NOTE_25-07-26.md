---
name: report:handoff-05-cfpages-waituntil-verification
description: "KG-2 — verify Cloudflare Pages event.waitUntil beacon delivery post-deploy (H5)"
date: 25-07-26
metadata:
  node_type: memory
  type: report
  feature: evallayer
  phase: H5
---

# KG-2: CF-Pages `event.waitUntil` beacon delivery (deploy-gated)

**Status:** OPEN — deploy-gated known-gap from Handoff Detection H5.

`apps/web/src/middleware.ts` fires the fetch beacon via `ev.waitUntil(fireFetchBeacon(...))`.
Whether the Cloudflare Pages Edge runtime actually keeps the background POST alive after the
response is returned is **unverifiable without a real deploy** (local `next build`/dev does not
exercise the CF Pages waitUntil lifecycle).

**To close:** after deploy + `agent_fetch_beacon_enabled=true` + secret set, trigger a real
ChatGPT/Perplexity browse of getbeam.fyi and confirm a new row appears in the Agents dashboard
(agent_visits / agent_fetch_events). If waitUntil drops the request, fall back to a synchronous
(still fire-and-forget, short-timeout) dispatch or a CF-native mechanism.
