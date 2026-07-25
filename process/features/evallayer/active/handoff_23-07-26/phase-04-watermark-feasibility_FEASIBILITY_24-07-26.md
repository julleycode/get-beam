---
slug: handoff-h4-citation-watermark
date: 24-07-26
corrected-on: 25-07-26
verdict: VIABLE
originating-phase: pvl
---

> **CORRECTION (25-07-26) — supersedes the 24-07-26 INCONCLUSIVE verdict below.**
> Live re-probe via Claude-in-Chrome on the founder's real browser drove BOTH ChatGPT and Gemini to
> fetch `https://getbeam.fyi/pricing-overview/ptio5ny`. Both returned Beam's REAL pricing (Free $0 /
> 10 identified visitors; Pro $19→$15 yearly / 50; Max $49→$39 yearly / unlimited) and cited the
> exact minted-token URL back verbatim. This proves the citation-watermark mechanism end-to-end: a
> unique per-fetch token survives into the AI's cited source URL. The root cause of the original
> failed fetch was NOT a domain-wide WAF block — it was `<meta name="robots" content="noindex">` on
> the probe page (ChatGPT explicitly said the page appeared unindexed). Fixed in commit `6252f92`
> (noindex → index,follow) and confirmed live (robots meta now `index, follow` on
> `getbeam.fyi/pricing-overview/ptio5ny`). The user's Cloudflare dashboard also showed
> `ChatGPT-User` = Allowed — the domain-wide-WAF-block theory in this document's original Verdict
> and Evidence sections is retracted; see the companion correction in
> `process/features/evallayer/backlog/aeo-waf-blocks-ai-fetchers_NOTE_24-07-26.md`. The original
> body below is preserved verbatim for audit trail; treat its Verdict/Design-Constraint sections as
> superseded by this note and the updated `## Resulting Design Constraint` at the bottom of this file.

# Feasibility Verdict — Does a per-fetch URL token survive into a returned AI citation link?

## Hypothesis
A per-fetch, Beam-controlled query-string/path token served on a public probe page
(`/pricing-overview/{t}`) survives verbatim into the citation link an AI agent returns when asked
to browse and cite that page — enabling deterministic fetch-to-click linkage as a watermarking
mechanism.

## Mechanism Under Test
Whether an on-demand AI answer-engine fetcher (a) successfully fetches the tokenized probe page at
all, and (b) if it does, whether the token in the fetched URL's canonical/path segment is preserved
unmodified in the citation URL the engine surfaces to the end user.

## Probe Family
4 — External API/product shape capture (live third-party product behavior, not an internal system)

## Probe Cost Class
`needs-live-provider`. Gate met via explicit double opt-in: the founder personally ran the probe
against a live ChatGPT session (no automated/scripted dispatch was performed by any agent).

## Probe Method
Founder-run manual probe, per the plan's "Founder Instructions" block:

1. Founder confirmed (attempted) the probe page was reachable at
   `https://getbeam.fyi/pricing-overview` (302 → `/pricing-overview/{token}`, PREP code shipped
   and gate-green per `phase-04-watermark-feasibility_REPORT_23-07-26.md`).
2. Founder pasted into ChatGPT: *"Browse https://getbeam.fyi/pricing-overview and summarize Beam's
   pricing. Please cite your source."*
3. Founder reported ChatGPT's response verbatim and pasted back what (if anything) was cited.

Cross-check performed by the orchestrator this session (read-only diagnostic, not part of the
probe itself): `WebFetch` against `https://getbeam.fyi/pricing-overview` and
`https://getbeam.fyi/` — both returned **HTTP 403 Forbidden** to an external bot-classed
user-agent.

## Evidence Captured

**ChatGPT response (founder-reported):**
> "I couldn't retrieve the page directly."

No fetch occurred, and consequently no citation link was produced. ChatGPT then answered from
prior/model knowledge about a *different* product also named "Beam" — a construction/invoicing
tool (estimates, invoices, lien waivers; tiers "Core" Free / "Plus" $250 / "Scale" $500) — which is
**not** the real Beam (visitor-identification AI agent; real tiers Free $0 / Pro $19 / Max $49, see
Blast Radius of the PREP plan). This is a hallucinated answer about a namesake product, not a
result derived from the probe page in any way.

**Orchestrator diagnostic (this session, `WebFetch`):**
- `GET https://getbeam.fyi/pricing-overview` → `403 Forbidden`
- `GET https://getbeam.fyi/` → `403 Forbidden`

Both requests were blocked at the domain level, not the specific probe route — indicating a
domain-wide anti-bot layer (Cloudflare-class WAF or equivalent), not a routing/deploy defect
specific to the H4 PREP code.

## Verdict (original, 24-07-26)
INCONCLUSIVE — **superseded 25-07-26, see correction banner at top of file. Current verdict: VIABLE.**

## Resulting Design Constraint (original, 24-07-26 — superseded, kept for audit trail)
- **What this licenses:** nothing new — the watermark mechanism remains unproven. No design may
  claim citation-token survival is confirmed. H2's fetch-to-click temporal correlation remains the
  program's shipped, proven mechanism for "human behind the agent" — this probe neither strengthens
  nor weakens that conclusion.
- **What this forbids:** do NOT build any production citation-watermarking implementation. The
  hypothesis was never actually exercised — the fetch never happened, so there is nothing to
  license even provisionally. Per AC-H4-2, H4 is complete on any verdict other than VIABLE; this
  result closes the door on implementation for this program without reopening it.
- **What remains uncertain (known-gap, re-probe candidates):**
  1. Whether the site's WAF specifically blocks the `ChatGPT-User` on-demand fetcher UA (or
     on-demand AI fetchers generally), versus blocking all non-browser traffic indiscriminately —
     not distinguished by this probe.
  2. The original hypothesis (does a survived fetch's token appear verbatim in the citation) is
     completely untested — a fetch never occurred. Re-probing is only meaningful after the WAF is
     reconfigured to allow the relevant fetcher UAs through (see companion backlog finding:
     `process/features/evallayer/backlog/aeo-waf-blocks-ai-fetchers_NOTE_24-07-26.md`).

## Probe Cost Class Confirmation
`needs-live-provider` was the correct classification (matches plan Step C2). The probe correctly
required explicit double opt-in and was founder-dispatched, not agent-automated.

---

## CORRECTED Verdict (25-07-26)
**VIABLE**

Deciding evidence: live re-probe, 25-07-26, via Claude-in-Chrome on the founder's real browser
(founder-supervised, not an automated/scripted dispatch — satisfies the same `needs-live-provider`
double-opt-in gate as the original probe). Two independent AI answer engines — ChatGPT and Gemini —
were driven to fetch `https://getbeam.fyi/pricing-overview/ptio5ny`. Both:
1. Successfully fetched the page (200, not blocked).
2. Returned Beam's REAL pricing (Free $0 / 10 identified visitors; Pro $19→$15 yearly / 50 visitors;
   Max $49→$39 yearly / unlimited) — i.e. answered from the actual fetched content, not stale/model
   memory or a namesake product.
3. Cited the exact minted-token URL (`/pricing-overview/ptio5ny`) back in their response.

This directly exercises and confirms the original hypothesis: a per-fetch, Beam-controlled token
survives verbatim into the AI engine's returned citation link.

**Root cause correction:** the original 24-07-26 probe's failure was misattributed to a
domain-wide Cloudflare WAF block. The actual root cause was `<meta name="robots"
content="noindex">` on the probe page — ChatGPT explicitly reported the page appeared unindexed.
This was fixed in commit `6252f92` (noindex → index,follow) and confirmed live (robots meta on
`getbeam.fyi/pricing-overview/ptio5ny` is now `index, follow`). The user's own Cloudflare dashboard
showed `ChatGPT-User` = Allowed, contradicting the original "domain-wide WAF block" theory. The
earlier orchestrator `WebFetch` 403s were against a generic/unnamed bot UA (the WebFetch tool
itself), NOT the named on-demand AI fetcher UAs (`ChatGPT-User`, `Google-Extended`/Gemini) — so they
were never evidence of an AI-fetcher-specific block in the first place.

## CORRECTED Resulting Design Constraint (25-07-26)
- **What this licenses:** a per-fetch unique-token watermark is a viable correlation primitive.
  Named on-demand AI answer-engine fetchers (confirmed: ChatGPT/OpenAI, Gemini/Google) will fetch a
  properly indexable tokenized page and cite the tokenized URL verbatim in their response. Designs
  MAY rely on this for deterministic fetch-to-click/citation linkage, for these two vendors.
- **What this forbids:** do NOT rely on `noindex` (or otherwise non-indexable) pages for
  AI-citation-based correlation — engines will not fetch/cite pages that appear unindexed, and will
  fall back to stale or hallucinated (namesake-product) answers instead. Any watermark-page
  deployment must ship `index,follow` (or equivalent crawlable posture) on the token route.
- **What remains uncertain (known-gap):** per-vendor WAF allow-status for `Perplexity-User` and
  `Claude-User` specifically is UNVERIFIED — this probe only confirms ChatGPT/OAI and
  Gemini/Google as Allowed and citation-capable. Do not assume Perplexity or Claude behave the same
  until independently probed (re-probe candidate, same `needs-live-provider` gate).
