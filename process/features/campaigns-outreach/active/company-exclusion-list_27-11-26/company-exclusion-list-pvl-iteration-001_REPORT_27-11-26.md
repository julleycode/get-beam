---
domain: plan
iteration: 1
date: 2026-11-27
loop_status: CONTINUE
plan: company-exclusion-list_PLAN_27-11-26.md
---
# PVL iteration 001

- Input verdict: Gate CONDITIONAL (outer-pvl pass 1) — 0 FAIL, 7 CONCERN.
- Supplement applied (vc-plan-agent, opus): 7/7.
  1. UI panel → dashboard/connectors/page.tsx + components/exclusions-panel.tsx.
  2. Guard census: send loop (~261 load, ~385-387 check), _get_segment_visitors, campaigns.py:125, _resolve_linkedin_targets (pre-loop filter), AutoDrafter.generate_for_visitor; crm_push/contact_mapper/exports/ads_push covered via _get_segment_visitors.
  3. Filter in run_segmentation, not build_visitor_profiles.
  4. <2-label + public-suffix rejection; own freemail set (superset-tested vs enricher); canonical_visitor_id for merged.
  5. AC-9 reworded (behavior-identical, zero new queries).
  6. G7 structural census pytest; `.venv/bin/python -m pytest`; flag-ON AutoDrafter/LinkedIn/CRM cases.
  7. Known-contacts vs exclusion table; Excluded badge wins.
- Added: high-risk evidence pack, sibling-plan rebase note, Open User Decisions (5 provisional).
- Validator: 0 FAIL, 1 WARN (exact-path all-context.md match).
- Next: re-run vc-validate-agent from V1.
