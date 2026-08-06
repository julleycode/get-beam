---
name: report:beam-lab-soft-serve-known-gaps
description: "Open items carried forward from the Beam Lab soft-serve agent-gate UPDATE PROCESS reconciliation (07-08-26) — none block the shipped behaviour, none are silently dropped"
date: 07-08-26
metadata:
  node_type: memory
  type: report
  feature: evallayer
  phase: beam-lab
---

# Beam Lab soft-serve — known gaps carried forward

Written during the UPDATE PROCESS pass that reconciled
`process/features/evallayer/completed/agent-gate-soft-serve_31-07-26/` (and the superseded
`agent-gate-lab_31-07-26/`) against the deployed reality documented in
`docs/beam-lab-resume.md`. All items below are doc-flagged open work from that resume doc's
"Open items" list — none are new findings from this pass, and none block the soft-serve
behaviour, which is confirmed live on `beamlab.nhantown.com`.

**Caveat that applies to every item below:** the actual running Cloudflare Pages deployment's
code was NOT re-fetched and diffed against the repo file during this UPDATE PROCESS pass — the
"live" claims here are inherited from `docs/beam-lab-resume.md` (dated 2026-08-01) and the repo's
own commit history (`74e85b1`), not a fresh independent verification. Treat deployment/repo
parity as UNVERIFIED-BUT-ASSUMED, not confirmed, until someone re-checks with
`wrangler pages deployment tail` or a fresh curl against the live host.

## 1. `_bfm` marker has no TTL policy

Unlike `_bam` (API-side, Fernet-encrypted, 7-day expiry), the edge-minted `_bfm` marker
(`_middleware.js`, `crypto.randomUUID()` hex) never expires. Decide a TTL policy; low urgency
since this is a research-only lab, not a product surface with real users.

## 2. Human click-through on a `_bfm`-marked link not verified end-to-end

The edge → agent → link-preserved-in-answer leg is verified live (2026-07-31). The remaining
leg — a real human clicking a `_bfm=`-stamped link and confirming the
`events.link_marker ↔ agent_fetch_events.link_marker` join fires correctly — has not been run.
The `_bam` path already has this proof; `_bfm` does not.

## 3. `link_marker` migrations only in local dev Postgres

`apps/api/migrations/versions/f3c8b2e91d47_*.py` (`agent_fetch_events.link_marker`) and
`a7d419e6c052_*.py` (`events.link_marker`) exist only in the local Docker Postgres used to run
the lab experiment (`retarget_agent`, NOT production). Neither has been applied to the real
production API database. This mirrors the same pending-live-apply posture already tracked for
the other 13 migrations in the AI-agent-traffic chain (see
`process/context/all-context.md` §AI-Agent-Traffic Layer) — add these two to that same rollout
gate before any production reliance on `_bfm ↔ events.link_marker` joins.

## 4. `BEAM_FULL_LOG="1"` still on

`infra/cloudflare/beam-lab/wrangler.toml` has `BEAM_FULL_LOG = "1"`, which logs the complete
request/response of every non-static visitor, humans included. This was intentionally turned on
for the 2026-07-31→08-01 debug window and was meant to be temporary. Turn it back to `"0"` once
the current investigation (ChatGPT-hop retest, item 6 below) is done.

## 5. Gemini-via-AWS-fetcher traffic silently dropped by the classifier

One observed fetch matched a Gemini eval window timing-wise but presented UA
`got (https://github.com/sindresorhus/got)` on ASN 14618 (Amazon, Ashburn) rather than
`Googlebot` / `google-cloudvertexbot`. The classifier does not treat `got` as an AI token, so no
`agent_fetch_events` row was written. This is a product gap, not a bug: if tracking
Gemini-via-third-party-fetcher traffic matters, `matchOnDemandUa`/the classifier's token list
needs an explicit `got`+ASN-14618 heuristic (or an equivalent), which is speculative without more
observed samples. Flagged, not actioned.

## 6. ChatGPT browse measured as "intermittent, not broken"

Canary-only/homepage fetches usually succeed and quote `FUCHSIA-0731` correctly. Whether ChatGPT
*hops* to a linked deep page varies by prompt wording; given a **direct** deep-page URL it
sometimes does not fetch at all, invents an excuse, or cites the wrong host even though the page
is a live public 200. This is a finding about ChatGPT's browsing behaviour, not a defect in Beam
Lab's own code — no action item beyond re-testing with a natural (non-instructed) prompt if the
question needs a firmer answer.

## Not carried forward (already resolved by this UPDATE PROCESS pass)

- Reconciling the two plans' `status: awaiting-execute-approval` fields against the live
  soft-serve deployment — done in this pass (see the two plan files' updated frontmatter and new
  `## UPDATE PROCESS Reconciliation` sections).
