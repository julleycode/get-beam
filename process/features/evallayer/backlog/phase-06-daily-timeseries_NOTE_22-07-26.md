---
name: plan:evallayer-phase-06-daily-timeseries
description: "Backlog — true daily 'agent visits over time' rollup, deferred from Phase 06"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: backlog
---

# Backlog — Phase 06 Daily Agent-Visit Time-Series

**Deferred from:** `process/features/evallayer/active/evallayer_22-07-26/phase-06-aggregation-analytics_PLAN_22-07-26.md`

## Why deferred

SPEC AC11 only requires vendor-breakdown and page-read-trend analytics — a snapshot aggregation
over the existing `agent_visits` rollup table. It does not require a true daily "agent visits over
time" chart. `AgentVisit` rows are upsert-rollups keyed by `(site_id, vendor, product_or_ua_token)`
with a single `last_seen_at` — there is no per-day history to chart from that table alone.

## What a real implementation needs

- A new append-only `agent_visit_daily` rollup table (one row per `site_id` × `vendor` × `date`,
  incrementing a daily counter) — Phase 2 (ingest wiring) territory, since it needs a write path
  hooked into the same place `AgentVisit` upserts happen today.
- A new Alembic migration for the table.
- Ingest wiring changes to write the daily rollup alongside the existing `AgentVisit` upsert.
- A new pure aggregation function (mirroring `services/timeseries.py`'s `build_series` gap-fill
  pattern) to turn the daily rows into a continuous day-by-day series for a line chart.
- A new dashboard card (can reuse the existing agents-page card area) with a `PeriodToggle` for
  window selection, matching the `traffic-fit-card.tsx` / KPI time-series conventions.

## Follow-on slice

This is a natural standalone follow-up feature slice after the evallayer program completes its
6 planned phases — not urgent, since AC11 is satisfied without it. Revisit if user/product
feedback specifically asks for an agent-traffic trend line.
