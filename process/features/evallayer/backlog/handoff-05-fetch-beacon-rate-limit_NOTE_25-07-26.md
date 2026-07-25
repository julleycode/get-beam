---
name: report:handoff-05-fetch-beacon-rate-limit
description: "R-1 follow-up — add rate-limiting to POST /api/v1/agents/fetch-beacon (H5)"
date: 25-07-26
metadata:
  node_type: memory
  type: report
  feature: evallayer
  phase: H5
---

# R-1 follow-up: fetch-beacon endpoint rate-limiting

**Status:** OPEN — deferred hardening from Handoff Detection H5.

`POST /api/v1/agents/fetch-beacon` is authenticated by a shared secret but has **no per-caller
rate limit**. If the secret leaked, an attacker could flood the endpoint with forged on-demand
POSTs to inflate `agent_visits` / `agent_fetch_events` and pollute handoff correlation.

Blast radius is **bounded**: writes land only in the two structurally agent-only tables — never a
Visitor/IdentifiedVisitor/emailable identity (AC-H5-8 tripwire). So this is a data-quality/DoS
concern, not an identity or auth-escalation one.

**To close:** apply the existing slowapi limiter (see `apps/api/services/rate_limiter.py`) to the
route, keyed on site_id or source IP; consider a low ceiling (on-demand fetches per site are rare).
Rotate the secret if a leak is suspected.
