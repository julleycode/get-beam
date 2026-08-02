---
title: Identity P1/P2 status honesty and observability
description: >-
  Split identity_status into provider_candidate vs verified; fix resolution
  log-after-save; defer Fingerprint Pro / Luật 91 to backlog.
status: completed
priority: P1
effort: medium
branch: main
tags:
  - identity
  - visitors
  - p0-followup
blockedBy: []
blocks: []
created: '2026-08-02T11:20:29.694Z'
createdBy: 'ck:plan'
source: skill
---

# Identity P1/P2 status honesty and observability

## Overview

P0 đã chặn relay + name/email mismatch + paid graphs không emailable, nhưng KPI/UI vẫn gọi RB2B là `identified`. Plan này hoàn thiện honesty:

1. **P1** — `provider_candidate` (paid graphs) vs `verified` (first-party/owned/manual)
2. **P2** — log resolution success chỉ sau khi save OK; script/ops cleanup Lab false-positive
3. **P3** — ghi backlog Fingerprint Pro / vendor pixel PoC / Luật 91 (không implement)

**Block P0 regressions:** `EMAILABLE_PROVIDERS`, `is_privacy_relay_ip`, `name_email_consistent`.

**Depends on:** completed P0 `identity-p0-quality-gates_02-08-26`.

## Exact requirements

| # | Locked |
|---|---|
| Output | Status strings + UI badges; KPI counts honest; resolution_logs không ghi success khi save reject |
| AC | Paid graph save → `provider_candidate`; owned/manual → `verified`; legacy `identified` vẫn đọc như verified; unit+scoped tests xanh |
| Out | Fingerprint Pro SDK, OpenSend/Retention pixel PoC, full Luật 91 legal rewrite, schema migration cột mới |
| Constraints | Expand string status only (`String(30)`); no new DB column; outreach vẫn qua `is_emailable_identity` |
| Touchpoints | `identity_resolver`, `identity_classification`, `kpi`, `timeseries`, `dashboard`, `visitors*` UI/API, `status-badge` |

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Status model provider_candidate vs verified](./phase-01-status-model-provider-candidate-vs-verified.md) | Completed |
| 2 | [Resolution observability and Lab cleanup](./phase-02-resolution-observability-and-lab-cleanup.md) | Completed |
| 3 | [Backlog deferrals Fingerprint Pro Luat 91](./phase-03-backlog-deferrals-fingerprint-pro-luat-91.md) | Completed |

## Dependencies

- Completed: `process/features/visitors-identity/completed/identity-p0-quality-gates_02-08-26/`
- Research: `plans/reports/brainstorm-research-260802-1756-cookie-fp-vs-rb2b-identity-providers-report.md`

## Cook handoff

```
/ck:cook process/features/visitors-identity/active/identity-p1p2-status-observability_02-08-26/plan.md --auto
```
