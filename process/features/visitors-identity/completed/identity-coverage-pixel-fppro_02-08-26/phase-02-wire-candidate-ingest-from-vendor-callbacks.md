---
phase: 2
title: "Wire candidate ingest from vendor callbacks"
status: pending
priority: P1
dependencies: [1]
---

# Phase 2: Wire candidate ingest from vendor callbacks

## Overview

Bring vendor person matches into Beam as `provider_candidate` (not verified, not emailable). Prefer webhook/export API documented by Customers.ai; bind to Beam `visitor_id` / `server_visitor_id` / site_id.

## Requirements

- Functional: inbound identity → `IdentifiedVisitor` + `identity_status=provider_candidate` + `resolution_provider=customers_ai` (or vendor name)
- Apply P0 gates: skip if privacy-relay IP; reject name/email inconsistent; never add to `EMAILABLE_PROVIDERS`
- Non-functional: idempotent upsert; auth webhook secret

## Architecture

```
Vendor webhook/API
  → POST /api/v1/webhooks/identity/{vendor}
  → resolve Beam visitor (pixel id / email / time+IP window — pick documented key)
  → _save_identified-equivalent with provider=customers_ai
  → status provider_candidate
```

If vendor only offers dashboard export (no webhook): Phase 2 MVP = pull job + match on email/HEM/time window (document limitation).

## Related Code Files

- Create: webhook router or extend `apps/api/routers/webhooks.py`
- Modify: `identity_classification.py` — add provider to `PERSON_LEVEL` + `PAID_PERSON_GRAPH` (not EMAILABLE)
- Modify: `identity_resolver` / save path reuse
- Config: webhook secret env
- Tests: unit webhook → candidate; emailable still false

## Implementation Steps

1. Read Customers.ai (or chosen vendor) callback/export contract; pick one ingest shape.
2. Add provider string to PAID_PERSON_GRAPH_PROVIDERS.
3. Implement authenticated ingest → save as candidate.
4. Correlation strategy doc: must attach to existing Beam visitor_id when possible.
5. Tests for reject/relay/emailable invariants.

## Success Criteria

- [ ] Fixture webhook creates `provider_candidate` row
- [ ] `is_emailable_identity("customers_ai") is False`
- [ ] Name/email mismatch rejected
- [ ] Duplicate delivery idempotent

## Risk Assessment

- Weak correlation → wrong visitor attach — prefer vendor-supplied click id / email over IP-only
- No webhook API → delay Phase 2 to export poll; do not fake coverage
