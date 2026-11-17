---
phase: 3
title: "Fingerprint Pro device continuity"
status: pending
priority: P2
dependencies: [1, 2]
---

# Phase 3: Fingerprint Pro device continuity

## Overview

Integrate [Fingerprint Pro](https://fingerprint.com/demo/) to get a stable `visitorId` + Smart Signals (VPN/bot). Use for free prior-signal reuse and stronger privacy-relay/VPN gating. **Does not** produce name/email.

## Requirements

- Functional: browser agent collects Pro `visitorId`; server stores on Visitor (new column or reuse fingerprint field with prefix `fpro_`); `_check_prior_signals` can match prior verified/candidate by Pro id
- Smart Signals: if VPN/relay flagged by Pro, skip paid person promote (align with `vpn_filtered`)
- Keep Beam `fp2_*` as fallback when Pro key absent
- Non-functional: Pro public API key only in pixel; secret server-side for Server API if used

## Architecture

```
tracker.js → FingerprintJS.load(apiKey) → get()
  → emit event _fpro / visitorId + requestId
API ingest → Visitor.fingerprint_pro_id (or fingerprint if empty)
prior_signals: fingerprint_pro_match → reuse identity (status preserved)
Smart Signals VPN → vpn_filtered before paid graphs
```

Ref product behavior: stable ID across incognito/VPN claims on demo page — validate in Phase 4, do not market until measured.

## Related Code Files

- Modify: `apps/pixel/src/tracker.js`
- Modify: `apps/api/schemas/events.py`, `events` router, `Visitor` model + migration
- Modify: `identity_resolver._check_prior_signals`
- Config: `FINGERPRINT_PRO_PUBLIC_KEY`, `FINGERPRINT_PRO_SECRET_KEY`, `FINGERPRINT_PRO_ENABLED`
- Tests: ingest stores id; prior match; disabled = no-op

## Implementation Steps

1. Account + keys; feature flag default off.
2. Pixel: load agent only when enabled + key present (CDN per Fingerprint docs).
3. Persist visitorId write-once (like fingerprint).
4. Prior-signal path + optional Server API verify requestId (anti-tamper).
5. Map Smart Signals VPN/relay into existing vpn_filtered gate.
6. Docs: clarify Pro ≠ person identification.

## Success Criteria

- [ ] With flag on, Visitor gets Pro id from ingest
- [ ] Return visit with new Beam client id but same Pro id reuses identity free
- [ ] Flag off: zero Pro network calls
- [ ] Unit tests cover match + disable path

## Risk Assessment

- Cost per identification API call — budget gate
- Bundle size — async load, fail-open to fp2
- Over-trusting Pro VPN signal — combine with existing prefix/IPinfo, don't drop ingest
