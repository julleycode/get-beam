---
name: report:agent-gateway-posture-reversal
description: "Cross-reference note reconciling Beam's anti-bot posture with the Phase 2 public agent gateway"
date: 26-07-26
metadata:
  node_type: memory
  type: report
  feature: agent-gateway
  phase: "phase-2"
---

# Posture reversal: anti-bot brand vs. a public agent gateway

**TL;DR** — Beam's anti-bot stance means *never auto-send outreach; a human always
approves*. It does not mean *refuse to talk to agents*. A structured, consented front
door is the opposite of spam. Phase 2 builds that front door deliberately, in writing,
rather than silently contradicting the earlier note.

## What the earlier posture said

- `apps/web/src/app/.well-known/ai-plugin.json/route.ts:2-4` advertises **no**
  machine-callable interface — "Anti-bot by design."
- `process/features/evallayer/.../phase-00-discoverability_PLAN_22-07-26.md:60-62`
  records a grep constraint asserting that no `openapi` / `api.getbeam.fyi` string
  appears in that manifest.

## Why Phase 2 does not violate it

1. The brand promise is about **outbound behavior** (no auto-send, human approval gate),
   not about refusing inbound machine readers.
2. The posture is already partly nominal: `api.getbeam.fyi/openapi.json` and `/docs` are
   publicly served today (`apps/api/main.py:104-108`).
3. The new surface is **read-only, customer-authored, and doubly opt-in**:
   `settings.agent_gateway_enabled` (global, default OFF) AND `AgentProfile.enabled`
   (per-site, default OFF). Either off ⇒ 404, endpoint not revealed. No customer is
   opted in by this phase shipping.
4. Nothing on the surface is visitor data or PII — only what the merchant typed into the
   dashboard.

## What actually changed in Phase 1+2

- **Nothing in `ai-plugin.json`.** `apps/web/src/app/.well-known/ai-plugin.json/route.ts`
  was NOT edited in this pass, so the evallayer Phase-0 grep constraint still holds as
  written. It is untouched, not broken.
- The new surface lives on the **API host** (`api.getbeam.fyi/api/v1/agent/...`), not in
  the web app's `.well-known` manifest.
- Dogfooding the gateway on getbeam.fyi itself (which *would* require revisiting that
  grep constraint) is **not** part of Phase 1+2 and is deferred.

## Deviation from the plan's checklist item 8

The Phase 2 checklist asks for a dated cross-reference note appended to
`process/features/evallayer/.../phase-00-discoverability_PLAN_22-07-26.md`. The EXECUTE
handoff for this pass explicitly forbids touching `process/features/evallayer/**`, so the
note was written **here**, inside the agent-gateway task folder, instead. The
reconciliation is on record in writing (AC10's substance); only its file location differs.

**Follow-up for UPDATE PROCESS:** append a one-line pointer to this file from the
evallayer Phase-0 plan when that path is writable, so a reader arriving from the
evallayer side finds the reconciliation.
