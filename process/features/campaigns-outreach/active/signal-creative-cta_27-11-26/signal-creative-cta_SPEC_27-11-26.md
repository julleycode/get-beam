---
name: spec:signal-creative-cta
description: "Signal-aware creative variants + structured per-site CTA types with click attribution (gaps #8/#9; #10 verified no gap)"
date: 27-11-26
feature: campaigns-outreach
---
# SPEC — Signal-aware creative + structured CTAs

TL;DR: pick the draft angle from each visitor's dominant signal, give sites a menu of CTA types instead of only "Book a demo", record the chosen CTA on the touchpoint, and attribute clicks per CTA type. All behind default-OFF flags.

## Goals
- G1 (#8): each touchpoint carries a `signal_angle` chosen deterministically from the segment's dominant signal: `pricing_intent`, `repeat_visit`, `ai_referral`, `job_change`, `high_icp_fit`, fallback `general`.
- G2 (#9): sites configure enabled CTA types: `book_demo` (Site.booking_url), `free_trial`, `pricing_page`, `resource`, `reply`, each with a URL (except `reply`).
- G3: planner output carries structured `cta_type` (enum) alongside free-text `cta`; invalid/disabled types are coerced to the site default.
- G4: tracked links carry `cta_type`; click redirect records `cta_type` for per-type click counts.

## Findings locked from RESEARCH
- `calculate_intent_score` (visitor_aggregator.py:91) ALREADY counts repeat visits (`total_sessions>=2/3` +15/+25, plus recency-gap bonus). No change needed; `repeat_visit` angle reuses `total_sessions`.
- #10: no draft→approve→send gap. `send_draft` (services/sender.py:209) refuses non-`approved`; the only writes of `approved` are human endpoints `/drafts/{id}/approve` and `/retry` (routers/drafts.py:281,370). social_accounts.py:104-203 is connect/status only. apps/extension is a session-reading pipe, no send. No fix planned.

## Out of scope
- Auto-send of anything (never). A/B statistical testing of variants. Changing intent-score weights. Ad-creative variants (meta_ads touchpoint left as-is).

## Constraints
- Visitor-derived text into prompts only via `agents/prompt_safety.py`; signal angle is a closed enum computed server-side, never visitor text.
- Flags `signal_creative_enabled`, `cta_types_enabled` default OFF; flag-OFF output byte-identical to today.
- Tenant scoping via Site.user_id (404). No PII in logs (log cta_type + site_id only).
- Migration chains off `alembic heads` at EXECUTE time; DB gates pinned to localhost:5433 / disposable container.

## Acceptance criteria
- AC1 dominant-signal selector is pure and deterministic (precedence table tested).
- AC2 flag-ON planner prompt includes angle guidance + allowed CTA list; flag-OFF prompt unchanged.
- AC3 planner response `cta_type` validated/coerced; stored on campaign touchpoint JSON.
- AC4 site CTA config CRUD validated (https URLs, safe_dest-compatible host), tenant-scoped 404.
- AC5 click redirect with `ct=` param records cta_type; unknown value dropped; flag-ON path exercised against real PG.
- AC6 per-type click counts endpoint returns counts only, tenant-scoped.
