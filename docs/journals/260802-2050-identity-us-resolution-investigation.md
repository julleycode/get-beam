---
title: Điều tra định danh visitor US — snapshot lịch sử
date: 2026-08-02 20:50
severity: medium
component: identity resolution, Leadpipe, local Docker stack
status: ongoing — snapshot lịch sử, live bị chặn
---

## Context
Đây là snapshot lịch sử của buổi điều tra ngày 2026-08-02. Trạng thái hiện hành có thể đã đổi; đọc [handoff Identity US hiện tại](../identity-us-current-handoff.md) để lấy truth mới nhất.

Mục tiêu hôm nay là:
- kiểm tra liệu solution hiện tại có tăng định danh đúng cho visitor US hay không
- test readiness của Docker PostgreSQL 16 và Redis 7 local
- không chạm vào DB write path, deploy, hay state trả phí của provider

## What happened
Docker PostgreSQL 16 và Redis 7 lên khỏe. Local DB cho thấy `sites=2`, `auto-identify sites=0`, `verified pixels=1`, `visitors=17`, `US=8`.

Trong 8 visitor US, có `7 unresolvable + 1 legacy identified`. Row đã identified duy nhất có mismatch tên/email quá rõ nên baseline đúng thực tế vẫn là `0/8`.

Sáu trong bảy US-unresolvable có recent resolution logs và bị coi như retry-locked trong 30 ngày. Leadpipe logs = 0. RB2B logs có `13 attempts / 8 success logs`, nhưng toàn bộ success lại dồn vào một visitor false-positive, không phải 8 người đúng.

Live read-only Leadpipe trả về: account endpoint `200` nhưng `healthy=false`, `org_status=expired`, `credits_remaining=500`, `pixels_total=0`, `pixels_active=0`. Data domain endpoint `403`, pixels endpoint `403`, URL tracker dựng từ local UUID trả `404`.

## Findings
- `f11004e` đã cải thiện RB2B parser/normalization và chặn hashed email-like values.
- Work in progress còn đang thêm relay/mismatch gates, phân biệt Candidate vs Verified, after-save logs, honest KPIs, pixel stack attributes, cookie/fingerprint continuity, và UI/tests.
- Fresh tests: `50 passed + 52 passed = 102 passed`.
- `git diff --check` passed.
- Không có bằng chứng live nào cho thấy số visitor US được định danh đúng tăng lên.
- Buổi điều tra chỉ dùng read-only provider/account GET; không đổi file, DB row, deployment, commit hay paid-provider state.

## Reflection
Điểm khó chịu nhất là local stack xanh nhưng provider live path vẫn bị chặn. Chúng ta có measurement tốt hơn, safety tốt hơn, và parser sạch hơn, nhưng chưa có một con số live nào chứng minh uplift thật.

Nói thẳng: phase 1 chỉ mới xong ở mức unit/structural, còn live path thì blocked hoặc fail. Nếu chỉ nhìn vào test pass mà tự tin quá sớm thì sẽ tự lừa mình. Đây là kiểu bug lặng, rất dễ tiêu hết thời gian nếu không giữ kỷ luật với evidence.

## Decisions
- Ghi nhận entry này như snapshot lịch sử, không thay thế current handoff.
- Chấp nhận baseline hiện tại là `0/8` US identified-correct, không gọi đó là cải thiện.
- Xem plan hiện tại là stale cho đến khi có plan phase 2 được chọn và VALIDATE lại.
- Giữ nguyên nguyên tắc: chỉ làm tiếp khi có explicit approval, vì provider health/install/error semantics chưa xong.

## Next
1. Chọn và reconcile đúng một Phase 2 plan.
2. Quyết định rõ: reactivate Leadpipe hay replace/drop nó.
3. Revising + VALIDATE provider health, install, và error semantics.
4. Chỉ execute khi có approval rõ ràng.
5. Sau đó mới bật controlled Lab auto-identify/retry.
6. Chạy smoke 5 session và benchmark `N>=30`.

## Unresolved Questions
- Leadpipe có còn đáng giữ hay phải bỏ hẳn?
- Tại sao success logs RB2B dồn vào false-positive visitor thay vì người đúng?
- Khi nào mới có live evidence đủ để nói uplift thật, không phải chỉ unit-level safety?
