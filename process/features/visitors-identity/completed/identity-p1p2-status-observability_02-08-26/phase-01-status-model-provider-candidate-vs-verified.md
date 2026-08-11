---
phase: 1
title: Status model provider_candidate vs verified
status: completed
priority: P1
dependencies: []
---

# Phase 1: Status model provider_candidate vs verified

## Overview

Expand `Visitor.identity_status` string values so paid person-graphs are `provider_candidate` and first-party/owned/manual are `verified`. Keep legacy `identified` readable as verified synonym. No new DB column.

## Requirements

- Functional: `_save_identified` sets status from provider class; manual identify → `verified`; UI badges + filters; KPI/timeseries count both verified and candidates (separate or combined — see below)
- Non-functional: no migration; P0 gates unchanged

## Architecture

```
provider in PAID_PERSON_GRAPH_PROVIDERS → identity_status = provider_candidate
provider in EMAILABLE_PROVIDERS | manual     → identity_status = verified
legacy rows with identified                  → treated as verified in readers
merged / vpn_filtered / unresolvable / anonymous unchanged
```

**KPI policy (locked):**  
- `identified_count` (existing metric name) = rows in (`verified`, `identified`) — trusted/first-party style  
- Add or reuse facet: `provider_candidate` counted separately where cheap (dashboard overview), else list filter only  

If adding a second KPI is too invasive: count `verified|identified|provider_candidate|merged` as "resolved" for timeseries continuity BUT UI label must not say "Identified" for candidates. Prefer split: trusted = verified+identified; candidates = provider_candidate.

## Related Code Files

- Modify: `apps/api/services/identity_classification.py` — `identity_status_for_provider()`
- Modify: `apps/api/services/identity_resolver.py` — `_save_identified` status write
- Modify: `apps/api/routers/visitors.py` — manual identify → `verified`
- Modify: `apps/api/services/kpi.py`, `timeseries.py`, `routers/dashboard.py`, `visitors_helpers.py`
- Modify: `apps/web/.../visitors/page.tsx`, `[visitorId]/page.tsx`, `status-badge.tsx`
- Test: `tests/unit/test_identity_quality_gates.py` (+ classification/KPI unit as needed)

## Implementation Steps

1. Add `identity_status_for_provider(provider) -> str` next to EMAILABLE/PAID sets.
2. `_save_identified`: `visitor.identity_status = identity_status_for_provider(provider)`.
3. Manual identify path → `verified`.
4. Reader helpers: `VERIFIED_STATUSES = frozenset({"verified","identified"})`, `RESOLVED_PERSON_STATUSES = VERIFIED | {"provider_candidate","merged"}`.
5. Update KPI/dashboard/list filters/UI badges (`Candidate` / `Verified`).
6. Unit tests for status mapping + one resolve/save wiring test.

## Success Criteria

- [ ] Paid graph save sets `provider_candidate`
- [ ] form_capture/svid/manual save sets `verified`
- [ ] UI shows distinct badge for candidate vs verified
- [ ] KPI does not count `provider_candidate` as trusted identified (or documents split)
- [ ] P0 emailable/relay/name-email tests still pass

## Risk Assessment

- KPI drop if owners expect RB2B in "identified" count — intentional honesty; surface candidate count if easy
- Filter dropdown missing new statuses — add both options
