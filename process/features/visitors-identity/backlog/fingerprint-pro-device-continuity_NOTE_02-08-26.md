# NOTE: Fingerprint Pro for device continuity

**Date:** 02-08-26 · **Status:** deferred  
**Parent:** `identity-p1p2-status-observability_02-08-26`

## Problem

Custom `fp2_*` + `_rta_svid` may lose continuity under Safari ITP / aggressive cookie clears. Fingerprint Pro offers a more stable `visitorId`.

## Why deferred

- Does **not** return name/email (no fix for cold ID false positives).
- Cost + SDK size vs unproven Lab continuity loss rate.
- Beam already has free first-party sticky paths (P0/P1).

## Kill / revisit criteria

Revisit when Lab shows measurable return-visitor re-identify paid spend caused by lost svid/fp (e.g. ≥X% of resolutions are re-pays for same person within 30d).
