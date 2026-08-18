---
title: "Scale-ready getBeam for x20-x30"
description: "Bật aggregation incremental thật sự, giữ disk sống trên Free, rồi trần tenant + timeout. Nâng Supabase Pro để sau (~+25% bill). Không migrate DB, không Queue, không ClickHouse."
status: in-progress
priority: P1
branch: "dev_nhantc2"
tags: [infra, backend, database, api, critical]
blockedBy: []
blocks: []
created: "2026-08-17T17:32:55.494Z"
createdBy: "ck:plan"
source: skill
---

# Scale-ready getBeam for x20-x30

## Overview

**Không đổi vendor.** Pixel CF → FastAPI Railway (1 replica) → Supabase session pooler `:5432` + Redis Railway. x20 ≈ 66k events/ngày, x30 ≈ 99k. Vẫn 1 API. Điểm gãy là **aggregation full-history** và **disk Free 424/500 MB**, không phải CPU.

Nâng Supabase Pro **không chặn** Phase 1–2. User nâng sau (bill ~+25% OK). x20 **không** sống mãi trên Free 500 MB — Pro là bước operator, không phải code.

**Lỗ hổng phải sửa trước khi flip flag:** `aggregation_incremental_enabled=True` hôm nay **không stamp** `sites.last_aggregated_at` trên full recompute (`visitor_aggregator.py:539-540`; test cố ý: full must not stamp). Ingest khi watermark NULL luôn `since=None` → full mãi. Flag ON = no-op cho đến khi có bootstrap stamp.

## Load model (baseline ~3.3k events/ngày, ~0.63 KB/row)

| | Events/ngày | 90d events disk | Queue | 2nd replica | Partition |
|---|---|---|---|---|---|
| Now | 3.3k | ~0.19 GB | no | no | no |
| x20 | 66k | ~3.7 GB | no | no | no |
| x30 | 99k | ~5.6 GB | no | only if p95 trigger | plan only |
| + ip-org | — | +0.25 GB | — | — | — |

x20/x30 vừa Pro 8 GB included. Không vừa Free 500 MB.

## Scope Challenge

- Existing: incremental SQL, debounce Redis, sweep repair, tests, flags — **đã có**. Redis timeout **đã ship**.
- Minimum: bootstrap watermark + soak flag; reject/backfill `event_id` NULL; verify retention jobs.
- Defer: CF Queue, ClickHouse, Celery worker, split scheduler, partition, anonymous visitor purge (flag OFF), RLS, migrate DB.
- Selected: **HOLD**. 3 phases. Không service mới.

## Cross-Plan Dependencies

| Relationship | Plan | Status |
|---|---|---|
| Supersedes remaining operator work | `process/general-plans/active/capacity-hardening_25-07-26/` | Code W1 exists; flag never ON; Redis 4d done |
| No overlap | identity-coverage, social-resolution, privacy-hook | in-progress / pending — khác blast radius |

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Incremental aggregation soak and prod flag](./phase-01-incremental-aggregation-soak-and-prod-flag.md) | In progress (code complete; operator soak/flag remaining) |
| 2 | [Disk and event_id survival on Free](./phase-02-disk-and-event-id-survival-on-free.md) | In progress (code complete; prod migrate-then-deploy remaining) |
| 3 | [Tenant ceilings timeout and x20-x30 runbook](./phase-03-tenant-ceilings-timeout-and-x20-x30-runbook.md) | Pending |

## Dependencies

- Research: `plans/reports/research-260817-2335-production-architecture-verdict.md`
- Live: `DATABASE_URL` session `:5432` (không `:6543`). `pr-64` / `function-bun` đã xóa 2026-08-18.
- Pixel `event_id` = `uuid()` (`apps/pixel/src/tracker.js:290`). Unique **đổi** thành `(site_id, event_id)` (F1). Agent-fetch đã scoped theo site.
- `created_at` ingest: **server `now()` luôn** (Validation S1) — không tin `event.ts`.
- Trần site vì disk = **hard 429, 0 INSERT** (Validation S1). Origin lock CF trước khi tin `CF-Connecting-IP`.

## Out of scope

- Migrate Postgres. Cloudflare Queue. ClickHouse. Railway Postgres. 2nd replica theo lịch. Celery Beat. Enable RLS 56 bảng. PITR $100.

## Red Team Review

### Session — 2026-08-18
**Findings:** 10 reviewed (10 accepted, 0 rejected this round). Reports: `reports/from-code-reviewer-to-planner-red-team-*-plan-review-report.md`.
**Severity:** 2 Critical, 8 High.

| # | Finding | Severity | Disposition | Applied To |
|---|---|---|---|---|
| F1 | Unique `(site_id, event_id)` | High | Accept | Phase 2 |
| F2 | `created_at` = server now() | Critical | Accept → Validation: now() only | Phase 1+2 |
| F3 | Trần site hard 429 | Critical | Accept → Validation: 429 only | Phase 3 |
| F4 | Thiếu `event_id` → 400; list tests | High | Accept | Phase 2 |
| F5 | SET LOCAL timeout + RESET cùng PR | High | Accept | Phase 3 |
| F6 | Stamp chỉ `_background_aggregate` | High | Accept | Phase 1 |
| F7 | Redis down + flag ON → skip ingest agg | High | Accept | Phase 1 |
| F8 | Debounce = mutex hết lúc chạy | High | Accept | Phase 1 |
| F9 | Sequential fleet bootstrap trước flip prod | High | Accept | Phase 1 |
| F10 | Retention boot offset; alembic mọi non-prod | High | Accept | Phase 2 |

Planner-pass watermark deadlock vẫn đúng; F6 thu hẹp caller.

### Whole-Plan Consistency Sweep
- Files reread: plan.md, phase-01, phase-02, phase-03
- Decision deltas checked: 10
- Reconciled stale references: unique global; 422; flag-but-store-as-429; celery stamp; ingest_trust ceiling
- Unresolved contradictions: 0

## Validation Log

### Session 1 — 2026-08-18
**Trigger:** User chose `/ck:plan validate` after red-team apply
**Questions asked:** 4
**Verification:** skipped Step 2.5 (Red Team Review already has file:line evidence)

#### Questions & Answers

1. **[Architecture]** Phase 3 trần site khi vượt p99×5?
   - Options: Hard 429 không INSERT (Recommended) | 204 drop row | Giữ flag-but-store
   - **Answer:** Hard 429, không INSERT
   - **Rationale:** Disk survival; viết lại test abuse

2. **[Assumptions]** Cột cửa sổ incremental?
   - Options: server now() (Recommended) | clamp ±5 phút | giữ event.ts
   - **Answer:** created_at = server now() luôn
   - **Rationale:** Client ts không được tin

3. **[Tradeoffs]** Batch thiếu 1 event_id?
   - Options: 400 cả batch (Recommended) | drop từng event | server mint
   - **Answer:** 400 cả batch
   - **Rationale:** Khớp parser hiện tại; sendBeacon fire-and-forget

4. **[Scope]** Thời điểm nâng Supabase Pro?
   - Options: disk ≥85% hoặc trước khách trả tiền (Recommended) | ngay sau Phase 2 | không runbook
   - **Answer:** disk ≥ 85% Free hoặc trước khách trả tiền
   - **Rationale:** Đúng plan; không chặn Phase 1–2

#### Confirmed Decisions
- Ceiling: hard 429, zero INSERT
- created_at: server now() only
- Missing event_id: reject whole batch 400
- Pro: operator at 85% disk or before paid customer

#### Action Items
- [x] Phase 3: bỏ nhánh "drop row"
- [x] Phase 1+2: bỏ clamp ts
- [x] Phase 2: ghi rõ 400 cả batch

#### Impact on Phases
- Phase 1: ingest `created_at=now()`
- Phase 2: batch reject
- Phase 3: 429 only

### Whole-Plan Consistency Sweep
- Files reread after propagate: plan.md, phase-01, phase-02, phase-03
- Decision deltas checked: 4
- Reconciled stale references: clamp; drop-or-429
- Unresolved contradictions: 0

