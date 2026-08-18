---
title: Cook closeout — scale-ready GetBeam P1–P3
date: 2026-08-18 13:28
severity: high
component: aggregation, ingest uniqueness, site ceiling, CF CIDR, statement_timeout
status: code-complete on dev_nhantc2; flags OFF; chưa prod
---

# Cook closeout: scale-ready GetBeam (3 phase)

**Date**: 2026-08-18 13:28
**Severity**: High
**Component**: aggregation / ingest / site-ceiling / CF peer / SET LOCAL
**Status**: Code-complete; blocked on operator (migrate, F9, Railway, soak)

## Context

Plan `plans/260818-0032-scale-ready-getbeam/`. Red-team 10 finding đã accept; Pro/ClickHouse/Queue deferred. Journal Phase 1 riêng: [260818-0136-phase-01-incremental-aggregation.md](./260818-0136-phase-01-incremental-aggregation.md). Entry này là **closeout đủ 3 phase**, không phải replay P1.

Nhánh `dev_nhantc2`, **chưa push**. 3 commit: `8ffeb32` P1, `bbae139` P2, `73142d1` P3.

## What happened

| Phase | Commit | Landed |
|-------|--------|--------|
| P1 | `8ffeb32` | Watermark stamp **sau** full bootstrap (`since=None`); Redis mutex hold tới `finally`; Redis down + flag ON → skip agg (không fail-open additive); `events.created_at` = server `utcnow` |
| P2 | `bbae139` | `event_id` bắt buộc — batch 400 nếu thiếu; unique `(site_id, event_id)`; alembic `c3f6a9d1e8b2` **local only**; DSN guard fail-closed (remote chỉ khi `APP_ENV=production`) |
| P3 | `73142d1` | Trần site hard: **429, 0 INSERT**; CF header chỉ khi peer ∈ CF CIDR (`/29` IPv6 + unwrap v4-mapped); `SET LOCAL statement_timeout = 0` trên sweep / retention / ingest-agg / F9 bootstrap |

Tests: **153/153** sau khi sửa fixture `FakeSession.execute` (debounce). Defaults: mọi flag **False**, timeout **0**, ceiling number **155**.

Chưa làm: prod migrate, F9 bootstrap + soak, flip flag Railway, pause `buildtolaunch`. `docs/deployment-guide.md` mục Scale-ready có thể còn unstaged (mixed hosting).

## Decisions

- Flag-gated, default OFF — cook không flip Railway.
- Unique per-site, không global `event_id`.
- Alembic uniqueness không chạy remote trừ production DSN.
- Trần site là hard reject, không store-then-drop.
- CF trust theo CIDR, không tin header từ peer lạ.
- Timeout 0 trên job dài; không đổi default pool-wide.

Rejected (đứng nguyên từ plan): Queue, ClickHouse, migrate prod trong cook, đăng ký F9 vào `start_scheduler`.

## Impact

Ingest + agg path trên `dev_nhantc2` khớp contract scale-ready. Flip flag / migrate prod lúc này vẫn **unsafe**: watermark NULL → full recompute; unique index chưa trên prod; ceiling/CF chỉ sống khi flag ON. Pain: code xong, operator gate vẫn là chỗ chết.

## Next

1. **Không merge/push giả định prod-ready.** Operator: F9 `run_aggregation_watermark_bootstrap` trên staging/prod đến khi mọi site có events có `last_aggregated_at`.
2. Alembic `c3f6a9d1e8b2` trên prod **sau** DSN guard + `APP_ENV=production`.
3. Soak canary, rồi mới Railway flags. Trần 155 / timeout 0 giữ nguyên đến khi đo.
4. Pause `buildtolaunch` cho tới soak.
5. Stage `docs/deployment-guide.md` Scale-ready nếu còn mixed.

Owner: operator + branch owner `dev_nhantc2`. Timeline: trước mọi Railway flip.
