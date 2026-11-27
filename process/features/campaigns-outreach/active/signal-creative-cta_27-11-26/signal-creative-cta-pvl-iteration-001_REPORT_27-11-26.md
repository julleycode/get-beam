---
domain: plan
iteration: 1
date: 2026-11-27
loop_status: CONTINUE
plan: signal-creative-cta_PLAN_27-11-26.md
---
# PVL iteration 001

- Input verdict: Gate BLOCKED (outer-pvl pass 1) — 3 FAIL, 4 CONCERN.
- Supplement applied (vc-plan-agent, opus): 7/7 gaps.
  1. FAIL: added append-only no-PII `cta_click_events` table; `/c/` writes on every valid `ct`.
  2. FAIL: campaign_sender wraps CTA link via `/c/{site_id}?ct&t&cid` before decorate_links.
  3. FAIL: `{{cta_link}}` resolved in campaign_sender `_personalize`/`_compose_*` (booking_link sentinel pattern).
  4. CONCERN: `cta-clicks` route declared above campaigns.py:167 + reachability test.
  5. CONCERN: single CTA URL rule (validate_booking_url + https; safe_dest for site-host types; stored URL only).
  6. CONCERN: angle from raw profiles pre-sanitize; icp_fit flag-gated via `_STRONG_FIT_AT`.
  7. CONCERN: send-path render gate + integration twin of test_click_redirect; editor in site-settings-dialog.tsx.
- Plan-artifact validator: 0 FAIL, 1 WARN (all-context.md not cited).
- Open user decisions (provisional): 40% share rule; cross-domain CTA book_demo only; reply CTA untracked.
- Next: re-run vc-validate-agent from V1.
