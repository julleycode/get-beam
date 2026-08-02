# NOTE: Luật 91/2025/QH15 — identity consent & provider transfer

**Date:** 02-08-26 · **Status:** deferred (product/legal)  
**Parent:** `identity-p1p2-status-observability_02-08-26`

## Problem

Linking cookie + fingerprint + IP to name/email and sending to foreign providers needs transparent notice, purpose limitation, data-subject rights, and cross-border controls under Vietnam PDPL (Luật 91, hiệu lực 01/01/2026).

## Why deferred

- Legal/product copy + DPA review — not an engineering-only change.
- Existing GPC/DNT → `do_not_resolve` is a start, not full compliance surface.

## Kill / revisit criteria

Schedule with legal/product owner before VN GA marketing claims about person-level ID; block paid-graph enablement for VN sites until notice + purpose text reviewed.
