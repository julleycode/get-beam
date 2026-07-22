---
name: plan:evallayer-phase-02-latency-benchmark
description: "EvalLayer Phase 2 — NEW PLAN REQUIRED: ingest p95 latency benchmark for classify-then-branch restructure (SPEC AC5)"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-02-backlog
---

# Phase 2 latency benchmark — NEW PLAN REQUIRED

Date: 22-07-26
Source: Phase 2 (Ingest wiring) VALIDATE session — genuine zero-coverage Known-Gap, not an
environment-availability gap (no Docker issue here — no benchmark harness exists in this repo at
all yet).

## Gap

SPEC AC5 requires: "no material ingest latency added" by the classify-then-branch restructure in
`apps/api/routers/events.py` (the new `classify_agent()` call +, for a recognized agent UA, the new
`persist_agent_visit()` DB round-trip inserted before the existing datacenter/proxy-VPN checks).
No latency benchmark harness exists anywhere in this repo today that could measure ingest p95
before/after a code change — this is a Hybrid-tier gate with nothing to run it against.

## Files outside blast radius

None — this is a net-new test-infra gap, not a code gap. No files need to change outside Phase 2's
already-planned blast radius to ship Phase 2 itself; the missing piece is a load/latency-test
harness that does not exist as a category in this repo yet.

## New API surface

N/A — no new external API surface; this is purely a test/benchmark tooling gap.

## Proposed resolution (for whoever picks this up)

1. Add a lightweight local benchmark script (e.g. `scripts/bench_ingest_latency.py` or a
   `pytest-benchmark`-based test) that:
   - Fires N synthetic `/events/ingest` POST requests with `agent_detection_enabled=False` (today's
     baseline path) against a local test server, records p50/p95/p99.
   - Repeats with `agent_detection_enabled=True` and a recognized-agent UA (GPTBot), records the
     same percentiles for the classify-then-branch + `persist_agent_visit` path.
   - Asserts the delta is within an agreed tolerance (e.g. +10ms p95) — exact threshold is a product
     decision, not fixed by this note.
2. Requires `MOCK_EXTERNAL_APIS=true` and the local docker-compose Postgres+Redis stack running
   (per `TESTING.md`) — this is a Hybrid-tier gate, not Fully-Automated, since it needs a live DB
   connection to be meaningful (in-memory/mocked DB would not reflect real commit latency).
3. Suggested location: `tests/integration/test_ingest_latency.py` or a standalone
   `scripts/bench_ingest_latency.py`, whichever fits the eventual owning phase/plan better.

## Status

Open — not yet scheduled to a specific phase. Close this gap before Phase 2 (or the umbrella
program) is marked ✅ VERIFIED for AC5.
