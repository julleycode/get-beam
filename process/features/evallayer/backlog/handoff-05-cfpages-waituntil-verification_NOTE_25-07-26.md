---
name: report:handoff-05-cfpages-waituntil-verification
description: "KG-2 — verify Vercel Edge Middleware event.waitUntil beacon delivery post-deploy (H5); reframed 25-07-26 from Cloudflare Pages to Vercel"
date: 25-07-26
metadata:
  node_type: memory
  type: report
  feature: evallayer
  phase: H5
---

# KG-2: Vercel Edge Middleware `event.waitUntil` beacon delivery (deploy-gated)

**Correction (25-07-26, live verification):** this note originally assumed the web app was hosted
on Cloudflare Pages. Live verification (Claude-in-Chrome, `x-vercel-id`/`x-vercel-cache` response
headers) confirmed getbeam.fyi's web app is hosted on **Vercel** (project `retarget-agent`, org
`tranthaiwork-droid`, repo `julleycode/retarget-agent`, auto-deploys `main`). Cloudflare only
proxies DNS/WAF in front — it does not host the app.

**Status:** LARGELY RESOLVED / DOWNGRADED — Vercel Edge Middleware supports `event.waitUntil`
natively (this is a documented, stable Vercel platform capability, unlike the original open
question about Cloudflare Pages Edge runtime behavior). The runtime-support risk that motivated
this Known-Gap no longer applies.

**Residual (the only thing still open):** confirm live beacon delivery on the real Vercel
deployment once the 3 beacon env vars (`BEAM_FETCH_BEACON_SECRET`, `BEAM_API_BASE`, `BEAM_SITE_ID`)
are set correctly on **Vercel** (not Cloudflare Pages, where they were mistakenly set during the
verification pass that surfaced this correction — root cause of the observed 0-capture) and the
project is redeployed.

**To close:** after setting the env vars on Vercel → `retarget-agent` → Settings → Environment
Variables (Production) and redeploying, trigger a real ChatGPT/Perplexity/Gemini browse of
getbeam.fyi (`beam_getbeam_fyi` site_id) and confirm a new row appears in the Agents dashboard
(agent_visits / agent_fetch_events). Given Vercel's native `waitUntil` support, this residual check
is expected to pass without a runtime workaround; retain a fallback (synchronous fire-and-forget
with a short timeout) only if the confirmation surprises us.
