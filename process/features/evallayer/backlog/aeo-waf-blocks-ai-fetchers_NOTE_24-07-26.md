---
name: plan:aeo-waf-blocks-ai-fetchers-note
description: "RESOLVED/RETRACTED 25-07-26: original WAF-blocks-AI-fetchers theory was disproven by live re-probe — root cause was a noindex meta tag (fixed 6252f92), not a WAF block. Named AI fetchers (ChatGPT/OAI, Gemini/Google) reach getbeam.fyi and cite it correctly. Residual known-gap: Perplexity-User/Claude-User WAF status unverified."
date: 24-07-26
corrected-on: 25-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: program-closeout
  status: resolved-retracted
---

> **RESOLVED / RETRACTED (25-07-26).** This note's core premise — "getbeam.fyi's anti-bot WAF
> blocks on-demand AI fetchers domain-wide" — is **disproven**. Live re-probe via Claude-in-Chrome
> on the founder's real browser drove BOTH ChatGPT and Gemini to fetch
> `https://getbeam.fyi/pricing-overview/ptio5ny`. Both reached the origin (200, not blocked),
> returned Beam's REAL pricing (Free $0 / 10 identified visitors; Pro $19→$15 yearly / 50; Max
> $49→$39 yearly / unlimited), and cited the exact tokenized URL back. The user's own Cloudflare
> dashboard confirmed `ChatGPT-User` = Allowed.
>
> **Actual root cause:** the probe page carried `<meta name="robots" content="noindex">` — ChatGPT
> explicitly reported the page appeared unindexed and therefore never attempted/completed the
> fetch it later reported failing. Fixed in commit `6252f92` (noindex → index,follow); confirmed
> live (robots meta on `getbeam.fyi/pricing-overview/ptio5ny` is now `index, follow`).
>
> **What was actually observed at the time (re-explained):** the original orchestrator `WebFetch`
> 403s described below were against a generic/unnamed bot user-agent (the WebFetch tool itself),
> NOT the named on-demand AI fetcher UAs (`ChatGPT-User`, `Google-Extended`/Gemini). They were never
> valid evidence of a domain-wide or AI-fetcher-specific WAF block — conflating "some bot got a 403"
> with "AI fetchers are blocked" was the error in the original analysis.
>
> **No ops/Cloudflare action is required based on this note.** The "Recommended ops fix" section
> below is retracted — do not action it as written. The residual known-gap is narrower than
> originally framed: exact WAF allow-status for `Perplexity-User` and `Claude-User` specifically
> remains UNVERIFIED (only ChatGPT/OAI and Gemini/Google are proven Allowed and citation-capable).
> See the corrected verdict in
> `process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_FEASIBILITY_24-07-26.md`
> (H4 verdict updated INCONCLUSIVE → VIABLE on 25-07-26).
>
> Original body preserved verbatim below for audit trail.

# getbeam.fyi's Anti-Bot WAF Blocks On-Demand AI Fetchers (AEO Impact Finding)

**Priority: HIGH — flag for founder decision.** Discovered as a side effect of the H4
citation-watermark feasibility probe (`phase-04-watermark-feasibility_FEASIBILITY_24-07-26.md`,
verdict INCONCLUSIVE), but the finding itself is bigger than H4 — it is a direct, evidenced
conflict between the site's current anti-bot posture and any goal of AI-answer-engine visibility
(AEO/GEO).

## The finding

- Founder asked ChatGPT to browse `https://getbeam.fyi/pricing-overview` and cite its source.
  ChatGPT's response: **"I couldn't retrieve the page directly."** No fetch occurred — it then
  answered from prior model knowledge about a **different, namesake "Beam"** (a construction /
  invoicing product — estimates, invoices, lien waivers, tiers "Core" Free / "Plus" $250 / "Scale"
  $500) — not the real Beam (visitor-identification; real tiers Free $0 / Pro $19 / Max $49).
- Orchestrator diagnostic (`WebFetch`, same session) confirmed `https://getbeam.fyi/pricing-overview`
  **and** `https://getbeam.fyi/` both return **HTTP 403 Forbidden** to an external bot user-agent —
  a domain-wide block, not a defect specific to the new H4 probe route.

## Why this matters

The site's anti-bot WAF (Cloudflare-class, blocks generic scrapers) appears to ALSO block the
on-demand fetchers AI answer engines use when a user asks them to browse a specific URL
(`ChatGPT-User` and likely `Claude-User` / `PerplexityBot`'s on-demand variant). Net effect: AI
engines cannot read getbeam.fyi at all, so any AI-generated answer about "Beam" is either wrong
(as observed — a different product entirely) or stale. The site's AEO/GEO visibility is
structurally ~zero-or-actively-wrong today, independent of any watermarking work.

This is a direct instance of the on-demand-vs-index tier distinction EvalLayer Phase H1 already
built (see `apps/api/services/agent_classifier.py` tier split, `apps/api/data/agent_ip_ranges/`
published-IP-range data for OpenAI/Perplexity) — the classifier already knows how to distinguish
these fetchers; the site's edge config does not yet act on that distinction.

## Recommended ops fix (NOT code — infra/Cloudflare change, founder-executed)

Allowlist on-demand AI fetchers at the edge while keeping generic scrapers blocked:

1. Use Cloudflare's **Verified Bots** allowlist (or equivalent WAF rule) to permit `ChatGPT-User`,
   `Claude-User`, and `PerplexityBot`'s on-demand identity through, while leaving the
   generic-scraper block in place for everything else.
2. Where UA-string matching is insufficient/spoofable, cross-check against the **published IP
   ranges Beam already ships** at `apps/api/data/agent_ip_ranges/` (OpenAI + Perplexity) — the
   same source `apps/api/services/agent_verification.py` uses for UA→IP confidence upgrades.
3. This operationalizes exactly the on-demand-vs-index tier distinction H1 built for ingest
   classification — apply the same distinction at the edge/WAF layer, not just at the
   application layer.

## Precondition for

- **H4 watermark re-probe**: the citation-watermark hypothesis (does a per-fetch token survive
  into the citation) was never actually exercised because the fetch never happened. Re-probing is
  only meaningful after this WAF allowlist change ships.
- **Any real AEO/GEO strategy**: publishing an OpenAPI spec, an `ai-plugin.json`, or other
  AI-discoverability surfaces is moot while the underlying pages themselves 403 to the fetchers
  that would consume them (compare `evallayer-discoverability-posture` memory note — Transaction
  axis intentionally ~60 by design; this is a distinct, unintentional gap in the Data axis).

## Status

Not actioned. This is an infra/Cloudflare-console change outside this repo's automated scope —
requires an explicit founder decision (does the anti-bot stance stay maximally strict, or does it
carve out a narrow, verifiable allowlist for on-demand AI fetchers). No code change is proposed
here.
