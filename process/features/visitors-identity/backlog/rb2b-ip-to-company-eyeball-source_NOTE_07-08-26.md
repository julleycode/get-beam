---
name: report:rb2b-ip-to-company-eyeball-source
description: "Idea: wire RB2B /api/v1/ip_to_company as a NEW company source for eyeball/residential IPs only — LIKELY_CUSTOMER relationship class, never overrides network-ownership evidence; endpoint currently not wired anywhere"
date: 07-08-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
  phase: ip-org-database-phase3-closeout
---

# RB2B `ip_to_company` as an eyeball/residential company source

Source: user discussion during ip-org Phase 3 closeout (07-08-26). Status: IDEA — the endpoint
is currently **NOT wired anywhere in the repo** (only `ip_to_hem` + `hem_to_business_profile`
are used). Priority: P3 (new capability, needs its own plan).

## The gap it fills

The in-house evidence graph (`ip_org_prefixes` + fusion) answers **"who owns/routes this
network"**. On eyeball/residential IPs it is *correctly silent* — org_kind='eyeball' rows are
filtered out of lookup v2 by design, because "Comcast" is not the visitor's employer. That
leaves ~27% of the prefix population (eyeball 26.9% as of the Phase 1-2 corpus) with no company
signal from the owned path.

RB2B's `/api/v1/ip_to_company` answers a DIFFERENT question: **"likely employer of the person
behind this IP"** — behavioral/panel-derived, not network ownership. These are complementary,
not competing, evidence classes.

## Design constraints (from the discussion — treat as locked intent)

1. **Eyeball/residential IPs ONLY.** Gate the RB2B call on the in-house lookup classifying the
   IP as eyeball (or returning None with an eyeball-class prefix match). On corporate IPs the
   network evidence is authoritative — **never let RB2B override network evidence on corporate
   IPs**.
2. **Relationship class = LIKELY_CUSTOMER**, not network ownership. If/when written into the
   evidence model, it must carry its own `relationship_type` value — it must not masquerade as
   `route_origin`/`registered_holder` evidence.
3. **Acceptance threshold:** top-1 confidence ≥ 0.7 AND a meaningful gap to the #2 candidate
   (exact gap value TBD at plan time).
4. **company_graph mapping:** `source='rb2b_ip'`, confidence ≤ 0.6 (below the rir_asn 0.45? no —
   above; the ceiling 0.6 keeps it below rDNS/paid-provider direct evidence). Follows the
   existing write-through pattern in `company_resolver.py`.
5. **Budget + mock:** RB2B credits are SHARED with the existing `ip_to_hem` waterfall usage —
   this source needs its OWN budget cap (config setting) so it cannot starve identity
   resolution, plus a `MOCK_EXTERNAL_APIS` deterministic mock path (repo-wide rule).
6. Standard provider hygiene: waterfall-gated, toggleable via env flag (default OFF), timeout +
   retry/backoff, 30-day no-retry on failed resolution, Redis cache per existing provider
   conventions.

## Known RB2B operational facts (from memory note `rb2b-api-suite-error-signatures`)

New RB2B accounts must activate each endpoint in the catalog ("Use API" button); expect
`service_unavailable_for_key` until activated, 402 = credits, `rb2b_no_match` = working. Check
the IP is not a CF edge IP before interpreting no-match.

## Next step

Own RESEARCH → PLAN pass when prioritized. Prereq: ip-org lookup v2 live (flag ON) so the
eyeball-classification gate has real data to gate on.
