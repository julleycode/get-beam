---
title: Beam AI Detection Lab MVP
description: >-
  Lab quan sát traffic phân biệt human/automation/crawler/AI agent,
  evidence-first, replay được, kèm canary test xác minh AI có thật sự fetch
  origin
status: in-progress
priority: P2
branch: main
tags:
  - detection
  - ai-crawler
  - canary-test
  - fastapi
  - sqlite
blockedBy: []
blocks: []
created: '2026-07-28T07:57:20.336Z'
createdBy: 'ck:plan'
source: skill
---

# Beam AI Detection Lab MVP

## Overview

Lab quan sát mọi request đến một site canary, lưu bằng chứng trước khi phân loại, và kiểm chứng
AI có thật sự fetch origin hay trả lời từ cache. Hướng **research/instrument**, không phải production service.

Nguồn: [brainstorm report](../reports/brainstorm-scope-validation-260728-1429-beam-ai-detection-lab-report.md)

## Ràng buộc đã chốt

| Hạng mục | Quyết định |
|---|---|
| Stack | Python 3.11+ / FastAPI / SQLite / Jinja2 |
| Hạ tầng | Cloudflare zone `nhantown.com`; public hostname `studio.nhantown.com`; named tunnel tạo ở phase 2 |
| Origin | Máy cá nhân Windows, bật/tắt theo ngày |
| Driver AI | Chat UI thủ công (ChatGPT, Claude, +Perplexity) — không API |
| Takedown | Soft takedown: giữ hostname, canary path trả `410 Gone` |
| Trạng thái | Phase 1 hoàn tất; FastAPI + SQLite evidence store đã kiểm thử |

## Ba bất biến kiến trúc (không phase nào được vi phạm)

**INV-1 — Evidence-first.** Không có đường nào drop request trước khi ghi evidence.
Policy engine không tồn tại ở MVP; lab luôn `allow + store`.

**INV-2 — Detector là pure function.** `detect(bundle) -> DetectorResult`. Cấm tuyệt đối trong detector:
DNS lookup, HTTP call, đọc đồng hồ hệ thống, đọc file cấu hình "hiện tại".
Mọi dữ liệu ngoài (rDNS, IP range, edge config) phải được resolve lúc request và niêm phong vào bundle.
Đây là điều kiện cần để replay hoạt động. Vi phạm = mất khả năng chạy lại detector v2 trên data cũ.

**INV-3 — Kết luận âm phải kèm coverage.** `origin_fetch_not_observed` không được xuất hiện một mình.
Luôn kèm `coverage_pct` từ uptime ledger và trạng thái ingress probe.
Thiếu bằng chứng ingress sống → ép về `inconclusive_ingress_unverified`.

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Foundation & Evidence Store](./phase-01-foundation-evidence-store.md) | Completed |
| 2 | [Edge Deployment & Config Snapshot](./phase-02-edge-deployment-config-snapshot.md) | Pending |
| 3 | [Ingress Health & Uptime Ledger](./phase-03-ingress-health-uptime-ledger.md) | Pending |
| 4 | [Detector Framework & Replay Harness](./phase-04-detector-framework-replay-harness.md) | Pending |
| 5 | [Identity Verification & Control Group](./phase-05-identity-verification-control-group.md) | Pending |
| 6 | [Canary Test Orchestration](./phase-06-canary-test-orchestration.md) | Pending |
| 7 | [Dashboard & Manual Result Entry](./phase-07-dashboard-manual-result-entry.md) | Pending |
| 8 | [Scheduler & Run Diff](./phase-08-scheduler-run-diff.md) | Pending |

## Phase dependency graph

```
1 Foundation
├─→ 2 Edge Deploy ──→ 3 Ingress Health ─┐
└─→ 4 Detector Framework ──→ 5 Identity ─┴─→ 6 Canary ──→ 7 Dashboard ──→ 8 Scheduler
```

Phase 2 và 4 chạy song song được sau khi phase 1 xong. Phase 6 cần cả 3 và 5.

## Lỗ hổng bắt buộc xử lý trong plan (không để phase sau)

| ID | Lỗ hổng | Xử lý tại |
|---|---|---|
| G1 | Negative result không phân biệt "AI không đến" vs "ingress chết" | Phase 3 — uptime ledger + external probe + outcome gating |
| G2 | Edge config là biến thí nghiệm chưa được version (gồm cả cache policy) | Phase 2 — snapshot edge config + cache rules + robots.txt hash vào từng test run |
| G3 | Detector chưa bị ràng buộc pure-function → replay không chạy được | Phase 4 — sealed evidence bundle + IO guard test |

Ba cái này là điều kiện tiên quyết cho tính đúng đắn của toàn bộ dữ liệu lab. Bỏ qua = số liệu vô nghĩa.

## Ngoài phạm vi MVP

Velocity detector, cadence detector, probabilistic sessionization, policy/blocking engine,
feature flag system, Cloudflare bot metadata, TLS/JA3 fingerprint, header-order signal,
marketing attribution layer, machine learning.

Lý do bỏ header-order: Tunnel normalize header case/order → signal cho dữ liệu **sai**, không phải thiếu.
Lý do bỏ velocity/cadence: traffic lab tự sinh, không có baseline thật để so.

## Acceptance criteria (MVP đạt khi)

1. Mọi request tới canary URL được lưu evidence bundle bất biến trước khi chạy detector.
2. Chạy lại detector version mới trên toàn bộ bundle cũ cho kết quả tái lập, có diff v1 vs v2.
3. Test có IO guard chứng minh không detector nào gọi mạng/DNS/clock.
4. Phân biệt được `verified` / `claimed_only` / `spoofed_bot` cho ít nhất OpenAI + Anthropic + Perplexity.
5. Web Bot Auth (RFC 9421) verifier đúng spec — chứng minh bằng fixture ký bằng key test + vector từ directory thật của vendor. Chữ ký thật quan sát được là observation item (vendor có ký hay không nằm ngoài tầm kiểm soát của lab).
6. Tạo được test run với 5 page variant, canary URL không đoán được, marker one-time-use.
7. Mọi outcome âm đều kèm `coverage_pct`; ingress probe fail → ép `inconclusive_ingress_unverified`.
8. Dashboard drill-down từ classification xuống evidence gốc, và có form nhập kết quả thủ công.
9. Soft takedown bật được và phân biệt `content_served_after_takedown` với fetch thật.
10. So sánh được run N vs N-1 trên cùng test template.

## Open questions

1. **Đã chốt:** `studio.nhantown.com`. Tên trung tính, phù hợp site portfolio/company giả lập và không chứa `lab`, `test`, `bot`, `canary`, `detect`. Public DNS chưa được tạo.
2. Nội dung site canary theo template nào? Cần "giống site thật" đủ để crawler coi là đáng index, không chứa dữ liệu thật/nhạy cảm. Tham khảo Duke/CMU: portfolio hoặc company site. **Đã gán làm deliverable của phase 2** — site trống thì lớp index/training không có traffic để đo.
3. Có submit sitemap vào Search Console / Bing Webmaster không? Đẩy nhanh lớp index/training nhưng làm nhiễu — traffic đến vì được submit, không phải vì AI tự tìm thấy. Khuyến nghị: **không** ở chu kỳ đầu, để đo khả năng tự khám phá; bật ở chu kỳ sau và ghi vào edge config snapshot.
4. Độ phân giải coverage: giữ probe 15 phút hay giảm xuống 5 phút? Ảnh hưởng trực tiếp tới ngưỡng cảnh báo 80%/50% trên dashboard và khả năng phát hiện khoảng down ngắn.

## Dependencies

Không có plan nào khác trong `plans/`. Không có cross-plan dependency.
