---
name: plan:evallayer-phase-04-live-range-refresh-note
description: "Backlog: scheduled fetch+diff of OpenAI/Perplexity published IP-range docs vs committed JSON, with drift alerting"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: backlog
---

# Backlog — Phase 04 Live Range Refresh

**Deferred from:** Phase 04 (IP-range verification)

## What this is

Phase 04 ships a small, static, checked-in set of published OpenAI/Perplexity CIDR
ranges under `apps/api/data/agent_ip_ranges/`. Vendors periodically add/rotate ranges
(e.g. OpenAI's `gptbot.json` / `chatgpt-user.json` / `searchbot.json` endpoints). This
backlog item covers keeping that dataset current over time:

- A scheduled task (APScheduler, same convention as `_resolution_sweep_job`) that
  fetches each vendor's live published range document, diffs it against the committed
  JSON, and either auto-updates (with a git-visible diff) or raises a drift alert for
  manual review.
- Alerting/reporting when a vendor's published format changes shape (defensive parsing
  failure) rather than silently going stale.
- Extending the tracked-vendor list (e.g. Amazonbot, cohere-ai) once those become
  relevant enough to warrant a v2 dataset entry — explicitly NOT built in Phase 04 v1
  per SPEC Resolved Open Question 6.

## Why deferred

- This is a live external HTTP call (vendor publishes ranges via URL, not just a static
  file) — out of scope for Phase 04, which explicitly avoids new live-provider calls in
  this pass. Doing this would require its own mock path, budget/rate limits, and a
  distinct scheduled-job registration.
- Not required for Phase 04's exit gate — the static dataset is sufficient to prove the
  confidence-tier mechanism (SPEC AC8).

## Not started — no code written for this yet.
