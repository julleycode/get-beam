---
name: report:handoff-05-gemini-ua-token-unverified
description: "KG-3 — confirm the real live Gemini/Google on-demand fetch UA and promote to on-demand tier (H5)"
date: 25-07-26
metadata:
  node_type: memory
  type: report
  feature: evallayer
  phase: H5
---

# KG-3: Gemini/Google on-demand fetch UA token unverified

**Status:** OPEN — data/verification known-gap from Handoff Detection H5.

H5 added a `google` vendor to `apps/api/services/agent_classifier.py` `_VENDOR_TOKENS` with the
single documented token **`google-cloudvertexbot`**, kept **INDEX-tier** (NOT in
`_ON_DEMAND_TOKENS`). This is deliberately conservative (E5/R-5): the exact User-Agent Gemini
presents when a user asks it to browse a page live is **undocumented/unverified**. Keeping it
index-tier means a real on-demand Gemini fetch is currently MISSED (204'd), never MISLABELED as a
human-behind-the-agent signal.

Deliberately NOT used: `google-extended` / `applebot-extended` — those are robots.txt AI-control
directives, not fetch UAs, and `tests/unit/test_agent_classifier.py::TestAC13Exclusion...` pins
them as never-classified.

**To close:** capture the real Gemini/Google on-demand fetch UA from live fetch logs post-deploy
(or CF AI Crawl Control). If confirmed user-driven, add that token to `_VENDOR_TOKENS["google"]`
and to `_ON_DEMAND_TOKENS`, update the tier-completeness test (`test_agent_fetch_events.py`
`_EXPECTED_ON_DEMAND`), and mirror it into `apps/web/src/lib/fetch-beacon.ts` `ON_DEMAND_UA_TOKENS`.
