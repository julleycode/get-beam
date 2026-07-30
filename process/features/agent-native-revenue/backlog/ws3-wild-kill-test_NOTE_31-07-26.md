---
name: report:ws3-wild-kill-test-note
description: "WS3 Step 5 known-gap — AC-WS3-5/6 wild kill test (WS0-gated, real-world wait; NOT closeable in EXECUTE)"
date: 31-07-26
metadata:
  node_type: memory
  type: report
  feature: agent-native-revenue
  phase: WS3
---

# WS3 — Wild Kill Test (AC-WS3-5 / AC-WS3-6) — Deferred Known-Gap

**Status:** OPEN known-gap. NOT closeable in the WS3 PLAN/EXECUTE/VALIDATE cycle.
WS3 Steps 1-4 reached **CODE DONE** (all Fully-Automated/Hybrid gates green, 31-07-26);
this plan must NOT be marked `✅ VERIFIED` until AC-WS3-5/6 close on real wild data.

## Why deferred (three hard gates, none satisfiable in a build cycle)

1. **WS0 exit metric** — AC-WS0-5 (>=1 real `identified_visitors` row via handoff on
   production) must be met first (umbrella Join Conditions).
2. **Steps 1-4 merged + live** on exactly one pilot site, with
   `agent_concierge_qualification_enabled` + `agent_concierge_conversion_enabled`
   flipped ON there (both default OFF; flipping is an explicit operator action after
   the 2 WS3 migrations are live-applied — see Migration note below).
3. **A real 1-week wild observation window** with a real MCP client (ChatGPT Developer
   Mode / Claude) pointed at the pilot site's MCP URL — a real-world wait + manual
   review, not a code deliverable.

## Operator steps to run the wild week (once WS0 is live)

1. Live-apply the 2 WS3 migrations in order (re-run `alembic heads` first):
   `b4d9e1a7c052` (agent_profiles.qualified_content) → `c5e0f2b8d163`
   (agent_leads + agent_tool_calls). Chain tip at EXECUTE was `a2f8d61c9e37`; other
   concurrent work may have advanced it — re-confirm live before applying.
2. On the ONE pilot site: author `AgentProfile.qualified_content`, set
   `AgentProfile.enabled=True`, and flip `agent_gateway_enabled` +
   `agent_concierge_qualification_enabled` + `agent_concierge_conversion_enabled` ON.
3. Get the pilot site's MCP URL (`POST /api/v1/agent/{site_id}/mcp`) into ChatGPT
   Developer Mode / Claude as an MCP server. Do NOT spoof — a real agent must drive it
   (CF WAF verifies real bots; classifier posture).
4. Wait 1 week. Target: >=20 real wild ChatGPT/Claude queries.
5. Run `assemble_kill_test_report(db, site_id, window_start, window_end)`
   (`apps/api/services/agent_kill_test_report.py`) over the window. Read the 4 rates:
   tool-discovery count, tool-call rate, param-fill rate, lead count.
6. **AC-WS3-6:** write the signed GO/NO-GO verdict citing that report.

## What is already built + proven (does NOT wait on this)

- `initialize` handshake, param-gated read tools, `request_quote`/`book_demo`
  conversion tools, `AgentLead` (isolated) + `AgentToolCall` (metrics) tables,
  free-only company lookup (Must-Fix 3), dedicated rate limit (Must-Fix 1),
  sanitization (Must-Fix 2), GO/NO-GO report helper — all lab-tested green
  (12 Hybrid integration + Fully-Automated unit gates, 31-07-26).
- The kill-test instrumentation (`agent_tool_calls`) records discovery/call/param-fill
  the instant a concierge flag is ON — so the wild week produces analyzable data with
  zero further code.

## Dependency edge

`AC-WS3-5/6` ⟵ blocks-on ⟵ `AC-WS0-5` (WS0 handoff exit metric on prod).
