---
name: spec:onsite-greeting
description: "Company-level on-site greeting for company-resolved pixel visitors (gap #5)"
date: 27-11-26
feature: pixel
---
# On-site Greeting — SPEC

TL;DR: opt-in, company-level, cache-only greeting rendered by a lazy-loaded snippet; never person-level, never on non-consented/GPC/DNT/do_not_resolve visitors.

## Goals
- G1 Site owner opts in per site (default OFF) and controls copy: a default template + optional per-industry templates (`{company}` is the only placeholder).
- G2 Visitor from a resolved real org (org_kind = `org`) sees a small dismissible greeting/CTA.

## Acceptance criteria
- AC-1 Global flag `onsite_greeting_enabled` (default False) AND `sites.greeting_enabled` (default False) both required; otherwise endpoint returns `{"show": false}` (never 404-vs-200 oracle beyond that).
- AC-2 Response contains ONLY `{show, template_id, text, cta_url?}` — no IP, domain, ASN, confidence, visitor id, person fields.
- AC-3 No greeting when: GATED && consent not `g`; OPTOUT (GPC/DNT); visitor `do_not_resolve`; is_bot_suspect/abuse flagged; org_kind != `org` (ISP/eyeball/datacenter/cdn); privacy relay/VPN.
- AC-4 Hot path does zero paid provider calls: reads only Redis company cache, `company_graph`, `ip_org_lookup` (local DB). Mock path deterministic under MOCK_EXTERNAL_APIS.
- AC-5 Rate limited (per-IP 30/min + per-site); CORS mirrors pixel (non-credentialed GET, wildcard ok; svid cookie read only if credentialed — decision: credentialed to read svid for do_not_resolve).
- AC-6 `tracker.min.js` stays < 6000 B gzipped; greeting code lives in separate `greeting.min.js`, loaded only when `data-greeting="on"`.
- AC-7 Rendered text is textContent (no HTML injection); owner templates sanitized server-side (length cap 200, `{company}` only).
- AC-8 No PII in logs (log site_id + show bool + reason code only).
- AC-9 Playwright: shown/not-shown matrix (consent, GPC, flag off, eyeball org) in `apps/pixel/e2e/`.

## Out of scope
- Person-level personalization (forbidden). Auto-DOM-rewriting of customer page content. A/B testing. Dashboard analytics of greeting impressions (v2).

## Constraints
Pixel size budget; consent G7 ordering; tenant scoping; default-OFF; high-risk class (public endpoint, trust boundary).
