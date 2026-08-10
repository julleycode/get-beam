# PVL Iteration 001 — ip-org Phase 3 (evidence graph v2)

Date: 2026-08-07
Plan: ip-org-phase-3-evidence-graph_PLAN_07-08-26.md
Cycle: 1 of max 10
Loop: PVL (plan-validate-fix)

## Validate pass 1 (vc-validate-agent, sequential self-checks — no Agent tool in env)

Gate: BLOCKED — 4 FAIL / 13 CONCERN / 2 known-gaps excluded.

FAILs:
- F1: CAIDA (24h) + RIR (weekly) writers of ip_org_prefixes with separate advisory-lock keys → stale carry-over snapshot can silently drop the other source's rows.
- F2: "existing Hunter domain-search mixin" fictional — hunter.py is domain→employee-email, class-bound; no org-name→domain call exists in repo.
- F3: lookup_ip_org_v2 org_kind filter unspecified, contradicted by −0.15 datacenter/cdn weight; D9 safety property at risk (CDN/DC IP → company attribution regression class).
- F4: OrgHypothesis.classification no derivation rule; registry_only unreachable.

Notable CONCERNs: asn NULLABLE override ripple (12 touchpoints), _INDEX_TARGETS 4th entry (plan wording wrote a bug), AC2.1 wrong expected CIDR set (verified by execution: [8.8.8.0/23, 8.8.10.0/24]), universal −0.05 no-coverage penalty when RIR flag off, rpki.json unbounded fetch, 3 missing gates.

## Supplement (vc-plan-agent, PVL-supplement mode)

SUPPLEMENT_APPLIED — 17 gap(s) addressed. Key dispositions:
- D10: single table-scoped IP_ORG_WRITE_LOCK_KEY in models/ip_org_prefix.py for ALL ip_org_prefixes writers.
- D7 rewritten: Hunter leg DROPPED (25 calls/month shared free tier vs 102k orgs = 0.02% coverage) → DNS-heuristic-only domain mapping.
- D11: v2 keeps org_kind='org' filter; contradictory weight deleted; eyeball excluded.
- D12: 5-row first-match classification table; unreachable values deleted.
- D13: asn NULLABLE (orchestrator override), 12-touchpoint list applied.
- C5 accepted-not-optimized: 8–15 min single-txn swap OK for background job, >20 min = new finding.
- C11 → KG-3 (stale fused confidence in company_graph, bounded ≤0.65).
- 8 new gates G11–G18; plan validator 0 fail after supplement (1119 lines).

Judgment calls flagged for re-validation scrutiny: Hunter-drop (domain coverage now DNS-probe-only) and C5 accept.

Next: re-spawn vc-validate-agent from V1.
