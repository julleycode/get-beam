---
name: report:ad-audiences-pvl-iteration-001
description: "PVL supplement cycle 1 — outer-PVL CONDITIONAL gaps (P1, P3) addressed by plan-agent supplement"
date: 25-07-26
feature: ads-audiences
metadata:
  domain: plan
  iteration: 1
---

# PVL Iteration 001 — ads-audiences program

## Trigger

Outer-PVL first pass (3 parallel vc-validate-agents, 25-07-26):
- Phase 1 Foundation — `Gate: CONDITIONAL` (4/6 concerns fixed in-validate; 2 execute-agent instructions not plan-tracked)
- Phase 2 Meta — `Gate: PASS` (no cycle needed)
- Phase 3 Google — `Gate: CONDITIONAL` (`google_ads_developer_token` needed a config.py extension point the registry didn't grant; SPEC OQ3 known-gap tagging)

## Fix batch (vc-plan-agent, PVL-supplement mode)

1. Phase 1: promoted the 2 execute-agent instructions into plan checklist items D5/D6 (stub providers → HTTP 501 when flag on + mock off; single documented status for flag-off connect attempts per repo precedent).
2. Registry: added scoped extension-point grant — Phase 3 may append the `google_ads_developer_token` field group to `apps/api/config.py` (otherwise Phase-1-owned), matching the existing extension-point declaration format.
3. Phase 3: Step A2 + Blast Radius now reference the registry grant; SPEC OQ3 (Google OAuth token refresh) explicitly tagged known-gap/research item.

Files touched: `phase-1-foundation_PLAN_25-07-26.md`, `phase-3-google-live_PLAN_25-07-26.md`, `phase-blast-radius-registry.md`. Phase 2, umbrella, SPEC, validate-contract sections untouched.

## Notable non-gap outcome this pass

Phase 3 validate agent resolved SPEC OQ1 via live docs-fetch of the Data Manager API discovery document: no audience-creation endpoint exists — two-API architecture required (Google Ads API creates the UserList; Data Manager API `audienceMembers.ingest` populates it), consent field casing confirmed (`adUserData`/`adPersonalization`, `CONSENT_GRANTED`), `termsOfService.customerMatchTermsOfServiceStatus: "ACCEPTED"` required, ingest is async (`requestId` only). Plan corrected in-validate; no `VC-FEASIBILITY-PROBE-NEEDED` escalation was necessary.

## Next

Re-spawn vc-validate-agent from V1 for Phase 1 and Phase 3 (confirming pass). Phase 2 contract stands.
