---
slug: handoff-h4-citation-watermark
date: 24-07-26
verdict: INCONCLUSIVE
originating-phase: pvl
---

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

## Verdict
INCONCLUSIVE

## Resulting Design Constraint
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
