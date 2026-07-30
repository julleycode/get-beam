---
name: report:ws2-activation-persistence-note
description: "WS2 activation follow-up — persist agent_sig end-to-end so the dormant classifier sweep can flag real sessions"
date: 30-07-26
metadata:
  node_type: memory
  type: report
  feature: agent-native-revenue
  phase: ws2
---

# WS2 Activation — Persistence Follow-Up (Backlog)

Date: 30-07-26
Priority: Medium-High (WS2's classifier is fully coded but structurally inert until this lands)
Status: Open — not started

## Problem

WS2's server-side classifier (`ws2_session_classifier.py`), sweep
(`ws2_session_classifier_sweep.py`), schema/migration, config, and scheduler wiring all shipped
(commit `5d4cf02`) and are EVL-green. But the client-side signal collection that would feed the
classifier's AND-gate behavioral fallback was **reverted during EXECUTE** — `agent_sig` is not
collected in `tracker.js`, not present on the `Event` Pydantic schema, and not persisted anywhere in
the `events` table. `ws2_session_classifier_sweep.py`'s `_extract_agent_sig()` unconditionally
returns `None` today, so the behavioral gate fails safe and the sweep flags nobody. The feature is
**DORMANT by design**, not by bug — but it needs a follow-up workstream to actually activate.

## Root Cause

Two independent constraints collided during EXECUTE:
1. **Size budget.** The real enforcing gate is `tests/unit/test_pixel_fingerprint.py::test_under_5kb_gzipped`
   (`< 5000` bytes gzip — NOT the `5120` figure recorded in the plan/CI/package.json, see the
   sibling contract-defect fix in this session's phase report). Current build: 4865 bytes gzip,
   leaving only ~135 bytes of real headroom — not enough to safely add 3 new accumulators
   (pointer-entropy, dead-center-click-rate, keydown-cadence) plus payload-assembly code without
   risking a build-time hard-fail or degrading the fidelity of collected signals.
2. **No persistence path.** Even if the client payload had fit, there is no `events.agent_sig`
   column and no schema field to receive it — shipping collection alone would have been dead client
   weight for zero behavioral benefit.

## What This Follow-Up Must Land (3 things, from the sweep's DORMANT docstring)

1. **Restore client-side signal collection in `tracker.js` UNDER the real budget.** Baseline
   headroom is ~135 bytes gzip (4865B used of <5000B). This will almost certainly require
   TRIMMING the signal set — reconsider whether all 3 original signals (pointer-entropy,
   dead-center-click-rate, keydown-cadence) are worth their gzip cost, or whether 1-2
   cheapest-per-byte signals (e.g. just the deterministic fast-path fields
   `navigator.webdriver`/`ua_ch_headless`, which are cheap booleans, deferring the pricier
   behavioral floats to a later iteration) get more signal per byte. Measure
   `cd apps/pixel && npm run build && gzip -c src/tracker.min.js | wc -c` after EVERY increment, not
   just at the end — this was the plan's own Execute-Agent Instruction E1 and remains correct
   guidance for this follow-up.
2. **Add an `events.agent_sig` column + migration.** Additive-only, mirrors the `Visitor`/
   `IdentifiedVisitor.is_agent_operated` precedent from this shipped workstream. Re-run
   `alembic heads` live before writing `down_revision` — this program has repeatedly seen
   concurrent migrations land on shared `main` (see `concurrent-program-migration-collision-rechain`
   memory note).
3. **Persist `agent_sig` at ingest in `events.py`.** Wire the new schema field through to the new
   column so `ws2_session_classifier_sweep.py`'s `_extract_agent_sig()` actually reads real data
   instead of `getattr(event, "agent_sig", None)` returning `None` unconditionally.

Once all three land, re-run the full WS2 Verification Evidence table (see the plan's
`## Verification Evidence`) — AC-WS2-2 (Playwright/CDP corpus TPR) and AC-WS2-3's lab leg (FPR on
human fixtures + filtered prod sample) both require a real persisted signal to measure against and
cannot be proven before this lands.

## Still-Open Wild ACs (unaffected by this follow-up — Agent-Probe/wild only)

- **AC-WS2-3 wild leg** — FPR check against real WILD production traffic. Needs a live traffic
  sample; already a named Known-Gap in the plan, not blocking CODE DONE/TESTING.
- **AC-WS2-4** — real Comet/Claude-in-Chrome wild session, before/after label evidence. Agent-Probe
  only; blocks ✅ VERIFIED per the plan's Phase Completion Rules, not CODE DONE/TESTING.
- **Live UA/Sec-CH-UA capture** for Comet/Claude-in-Chrome — deferred to WS2's own dedicated
  RESEARCH step (per the plan's Resume note), which has not yet run separately from the
  umbrella-level INNOVATE decision. Should run before finalizing thresholds in this follow-up.

## Suggested Scope for the Follow-Up Workstream

A single-phase plan (not a full new umbrella workstream) scoped to exactly the 3 items above, plus
re-running the deferred e2e corpus (plan checklist item 10) once real signal data exists. Should
reuse the existing `ws2_session_classifier.py`/`_sweep.py` modules unchanged — this is a persistence
wiring task, not a classifier redesign.
