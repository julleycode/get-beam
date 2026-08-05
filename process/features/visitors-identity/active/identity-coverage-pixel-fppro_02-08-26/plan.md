---
title: Identity coverage vendor pixel then Fingerprint Pro
description: >-
  Increase identification coverage: vendor person-pixels first, then Fingerprint
  Pro for device continuity. Preserve P0/P1 quality gates (candidate vs
  verified, relay block, name/email reject).
status: in-progress
priority: P1
effort: large
branch: main
tags:
  - identity
  - coverage
  - pixel
  - fingerprint-pro
blockedBy: ['project:260805-1543-identity-coverage-recovery']
blocks: []
created: '2026-08-02T11:35:10.284Z'
createdBy: 'ck:plan'
source: skill
---

# Identity coverage — vendor pixel → Fingerprint Pro

## Overview

**Goal:** nhiều kết quả định danh hơn (coverage), không phá P0/P1 (precision).

| Layer | Tool | Output |
|---|---|---|
| Person coverage | Vendor JS pixel (Leadpipe trước; Customers.ai/Capturify khi có ID) | `provider_candidate` name/email |
| Device continuity | [Fingerprint Pro](https://fingerprint.com/demo/) | Stable `visitorId` + Smart Signals — **không** PII |
| Verified | First-party form/login/magic-link (đã có) | `verified` emailable |

**Order locked:** Phase 1–2 pixel (Leadpipe) → Phase 3 Fingerprint Pro → Phase 4 US benchmark.

**Must not regress:** `EMAILABLE_PROVIDERS`, `is_privacy_relay_ip`, `name_email_consistent`, `provider_candidate` vs `verified`.

## Exact requirements

1. **Expected output:** Lab site loads vendor pixel; vendor hits land as `provider_candidate`; Fingerprint Pro `visitorId` stored + used for free reuse; benchmark sheet for US testers.
2. **Acceptance:** US residential session can produce Candidate from pixel path; Fingerprint visitorId stable across incognito/VPN *where Pro claims*; outreach still only Verified.
3. **Out of scope:** Treating Fingerprint Pro as person-ID; auto-Verified from vendor; full Luật 91 rewrite; OpenSend/Retention unless Phase 1 chooses them later.
4. **Constraints:** Pixel opt-in (existing `data-stack` model); no secrets in tracker; US-only expectation for person graphs.
5. **Touchpoints:** `apps/pixel/src/tracker.js`, `apps/api/routers/sites.py`, `config.py`, identity resolver/webhooks, new Fingerprint client module.

## Blocker cập nhật 05-08-26

Phase 1 báo DONE dựa trên structural/unit test, nhưng kiểm tra live cho thấy **FAILED**:
Leadpipe account expired, `pixels_active=0`, `/v1/data` trả 403, URL pixel dựng từ UUID trả 404.
Chi tiết: [identity-us-current-handoff.md](../../../../../docs/identity-us-current-handoff.md).

Phase 2 của program này (`wire candidate ingest`) bị chặn cho tới khi
`plans/260805-1543-identity-coverage-recovery/` gỡ xong blocker hạ tầng và chốt quyết định
giữ/bỏ vendor. Plan đó kế thừa Phase 2 và đổi vendor chính sang Leadpipe (có webhook push;
Customers.ai chưa có pixel-id). Phase 3 (Fingerprint Pro) và Phase 4 (US benchmark) của program
này **không đổi**.

## Scout finding (critical)

Snippet builder emits `data-identity-providers='…'` ([`sites.py`](apps/api/routers/sites.py)) but tracker only loads vendors when `data-stack="1"` + `data-stack-<vendor>` ([`tracker.js`](apps/pixel/src/tracker.js)). **Stacking is currently disconnected** — Phase 1 must wire this before any PoC can work.

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Vendor pixel PoC](./phase-01-vendor-pixel-poc-customers-ai-or-rb2b-pixel.md) | Completed |
| 2 | [Wire candidate ingest](./phase-02-wire-candidate-ingest-from-vendor-callbacks.md) | Pending |
| 3 | [Fingerprint Pro device continuity](./phase-03-fingerprint-pro-device-continuity.md) | Pending |
| 4 | [US ground-truth benchmark](./phase-04-us-ground-truth-benchmark-pack.md) | Pending |

## Dependencies

- Completed quality: `identity-p0-quality-gates_02-08-26`, `identity-p1p2-status-observability_02-08-26`
- Backlog notes: `vendor-pixel-benchmark_NOTE_02-08-26.md`, `fingerprint-pro-device-continuity_NOTE_02-08-26.md`
- Demo ref: https://fingerprint.com/demo/

## Defaults (locked unless you revise)

- **Primary pixel PoC:** Leadpipe (`LEADPIPE_DEFAULT_PIXEL_ID` present locally). Fix snippet → `data-stack-*` wiring.
- **Secondary later:** Customers.ai when ID pushed; Capturify when keys exist.
- **Fingerprint Pro:** after pixel path produces Candidates; use Pro Identification + Smart Signals (VPN) to reinforce gates, not replace graphs.

## Cook handoff

```
/ck:cook process/features/visitors-identity/active/identity-coverage-pixel-fppro_02-08-26/plan.md
```

Phase 1 done (Leadpipe stack attrs). Next: Phase 2 candidate ingest.
