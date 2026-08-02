---
phase: 1
title: Vendor pixel PoC Leadpipe (Customers.ai later)
status: completed
priority: P1
dependencies: []
---

# Phase 1: Vendor pixel PoC (Leadpipe first)

## Overview

Reconnect snippet → tracker stacking for Leadpipe. Tracker already uses `data-stack-*`; snippet was emitting dead `data-identity-providers` JSON — fixed in `sites.py`. Customers.ai later when ID arrives. No Beam ingest of PII yet (Phase 2).

## Env check (local, secrets not logged)

| Key | Status |
|-----|--------|
| `LEADPIPE_API_KEY` | SET |
| `LEADPIPE_DEFAULT_PIXEL_ID` | SET |
| `LEADPIPE_ENABLED` | `true` (REST waterfall on) |
| `CUSTOMERS_AI_PIXEL_ID` | missing — skip Customers.ai this phase |
| Capturify pixel | missing — skip |

Note: pixel stack loads from `LEADPIPE_DEFAULT_PIXEL_ID` / per-site id **regardless** of `LEADPIPE_ENABLED`. That flag only gates Leadpipe REST in `identity_resolver`.

## Requirements

- Functional: Lab snippet emits attrs tracker understands; with Leadpipe pixel id set, `leadpipe.aws53.cloud/p/<id>.js` loads once per page
- Non-functional: no stack attrs without vendor ids; consent_mode unchanged for off sites

## Architecture

```
sites.py pixel snippet
  → data-stack="1" + data-stack-leadpipe="<id>"
tracker.js
  → append <script src=https://leadpipe.aws53.cloud/p/<id>.js>
Vendor graph observes browser session (their cookie/FP — not Beam fp2)
```

**Fix applied:** stop emitting ignored `data-identity-providers`; emit `data-stack` contract only.

## Related Code Files

- Modified: `apps/api/routers/sites.py` (`get_pixel_snippet`)
- Unchanged (already correct): `apps/pixel/src/tracker.js`
- Test: `tests/unit/test_pixel_snippet_stack_attrs.py` (+ existing `test_pixel_fingerprint.py`)

## Implementation Steps

1. [x] Align attr contract — snippet emits `data-stack=1` + `data-stack-leadpipe`
2. [x] Do **not** teach tracker JSON path — dead attr removed from snippet
3. [x] Unit assert Leadpipe attrs present / absent
4. [ ] Manual: DevTools on Lab page shows Leadpipe request (operator)
5. [x] Document Leadpipe-first + Customers.ai later in plan defaults

## Success Criteria

- [x] Tracker loads Leadpipe when configured (unit: emitted HTML has `data-stack-leadpipe`)
- [x] Without config, no vendor stack attrs
- [x] Consent-off sites: no consent attr churn
- [ ] Manual: DevTools shows vendor request on Lab page

## Risk Assessment

- Third-party JS = privacy/perf cost — keep opt-in via env/site pixel id
- Leadpipe/US graph skew — VN Lab traffic may show zero matches (expected; Phase 4 needs US)
- Pixel load ≠ Beam Candidate until Phase 2 ingest
