---
domain: plan
iteration: 1
date: 2026-11-27
loop_status: CONTINUE
plan: onsite-greeting_PLAN_27-11-26.md
---
# PVL iteration 001

- Input verdict: Gate CONDITIONAL (outer-pvl pass 1) — 0 FAIL, 9 CONCERN, 7 supplement gaps.
- Supplement applied (vc-plan-agent, opus): 7/7.
  1. Cache only `greeting_company:{ip}`; site/Origin/visitor checks per request.
  2. Read-only sources named; resolve_company_cached / check_ip_privacy / ipinfo / PDL / rDNS forbidden.
  3. site_id String(50); name from ip_org org_name → company_graph.company_name; domain-only → show:false.
  4. AC-6 = <6144 B gz (abort ≥6100), raw <36000 B; short-name comment-free loader.
  5. Origin host must equal Site.url host; Cache-Control: no-store.
  6. G2 seeds org prefix + public IP, asserts show:true; Playwright route for greeting.js.
  7. Production enable preconditions (KG-1 trusted_proxy_hops, KG-2 ip-org runbook); two-heads stop rule.
- Validator: 0 FAIL, 0 WARN.
- Residual: Decision Summary still mentions "(site, ip) cache" and "6000 B budget" — stale lines for validator to flag.
- Open user decisions U1–U4 provisional.
- Next: re-run vc-validate-agent from V1.
