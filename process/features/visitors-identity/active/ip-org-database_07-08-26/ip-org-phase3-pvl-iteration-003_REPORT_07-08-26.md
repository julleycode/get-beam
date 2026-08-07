# PVL Iteration 003 — ip-org Phase 3 (evidence graph v2)

Date: 2026-08-07
Plan: ip-org-phase-3-evidence-graph_PLAN_07-08-26.md
Cycle: 3 of max 10 (supplement cycle 2 applied; validate cycle 3 pending)
Loop: PVL

## Supplement cycle 2 (vc-plan-agent)

SUPPLEMENT_APPLIED — 8 gap(s) addressed. Key dispositions:
- N1: AC1.5 rewritten to assertions that hold (shared key once in model module; rir_ingest zero literals + import).
- N2: AC4.2a = "exactly one row SELECTED under first-match"; mutual-exclusivity scoped rows 2-5; D12 prose corrected (row 1 overlaps by design → first-match rule).
- N4: corpus-EXISTS probe hoisted to module-level 300s-TTL cache invalidated on swap; <15ms warm budget; AC3.3+G8 = full v2 round-trip.
- N6: new D14 — slug algorithm locked (≤2 candidates, .com only); DNS answer necessary-not-sufficient; acceptance requires corroboration (company_graph prefix-interior row carrying domain, or existing name↔domain agreement); uncorroborated → NULL + 'heuristic_uncorroborated'. delta-airline fixture in AC4.8.
- N7: G19 (Hybrid, 500-org coverage sample) + G20 (Agent-Probe, 30-pair FP eyeball); AC4.12 = measurement-must-exist, no threshold.
- N8: G21 real full-volume --apply vs localhost:5433; 8-15min relabelled extrapolation until G21.
- N3/N10/nit: touchpoints merged, G1 mapping fixed, numbering ordered.

Validator: 0 fail (1282 lines). Cumulative 25/25 gaps closed over 2 supplement cycles.

Flagged for validate cycle 3 scrutiny: (1) D14 coverage-for-safety trade is a product decision embedded in plan supplement — surface to user at gate; (2) G19/G20 carry no pass threshold (can only fail on missing measurement, not bad number).
