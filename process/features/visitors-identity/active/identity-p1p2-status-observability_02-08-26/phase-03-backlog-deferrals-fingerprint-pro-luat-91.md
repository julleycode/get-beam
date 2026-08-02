---
phase: 3
title: Backlog deferrals Fingerprint Pro Luat 91
status: completed
priority: P3
dependencies:
  - 1
  - 2
---

# Phase 3: Backlog deferrals Fingerprint Pro / Luật 91

## Overview

Không implement Fingerprint Pro, vendor pixel PoC, hay rewrite Luật 91 trong cook này. Ghi backlog NOTE rõ ràng để không mất ý.

## Requirements

- Functional: write `process/features/visitors-identity/backlog/` NOTE(s) with problem, why deferred, kill criteria
- Out: any SDK/pixel/legal copy changes

## Implementation Steps

1. Write `fingerprint-pro-device-continuity_NOTE_02-08-26.md` — when to revisit (Safari ITP loss rate evidence)
2. Write `vendor-pixel-benchmark_NOTE_02-08-26.md` — Customers.ai/OpenSend PoC needs US traffic + ground truth panel
3. Write `luat-91-2025-identity-consent_NOTE_02-08-26.md` — consent/transparency for cookie+FP+provider transfer; product/legal owner
4. Mark phase complete after NOTES exist (no code)

## Success Criteria

- [ ] 3 backlog NOTES written under `process/features/visitors-identity/backlog/`
- [ ] plan.md links to NOTES
- [ ] No Fingerprint Pro / Luật 91 code shipped in this cook

## Risk Assessment

None — documentation only.
