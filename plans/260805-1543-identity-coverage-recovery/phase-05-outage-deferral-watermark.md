---
phase: 5
title: "Outage deferral watermark"
status: pending
priority: P2
dependencies: [2]
---

# Phase 5: Outage deferral watermark

> **Phase này sinh ra từ một lần thử THẤT BẠI ở session 3 (05-08-26).** Đã viết code, đã test
> xanh, rồi bị code review bác bằng bằng chứng chạy thật và **đã revert toàn bộ**. Đọc §Vì sao
> lần đầu hỏng trước khi làm lại — hai cái bẫy ở đó không nhìn ra được từ đọc code.

## Overview

Phase 2 gỡ khoá 30 ngày cho outage, nhưng **chưa gỡ được ai** vì còn một khoá thứ hai, mạnh hơn:

```
_resolve_full_waterfall  →  identity_status = 'unresolvable'   (kể cả khi MỌI provider đều chết)
resolution_runner.py     →  sweep CHỈ chọn identity_status = 'anonymous'
                            ⇒ visitor bị loại khỏi mọi lượt sweep về sau, vĩnh viễn
```

Đường quay lại duy nhất hiện nay: `revive_returning_unresolvable` (chỉ chạy khi **IP đổi**) hoặc
người bấm **Retry** tay.

## Requirements

- Functional: visitor mà **tầng provider có khả năng khớp nó** đều chết → không bị đánh
  `unresolvable`, và **được thử lại sau một khoảng chờ có giới hạn**.
- Functional: outage kéo dài **không được** làm visitor cũ chiếm hết slot sweep của visitor mới.
- Non-functional: cần **1 migration** (cột mốc hoãn) — đây là lý do phase này tách riêng, vì
  ràng buộc "không thêm migration" của plan gốc.

## Architecture

### Vì sao phải có cột DB, không dùng Redis được

Chốt chặn phải nằm **trong câu query của sweep**, không phải trong `resolve()`.

| Đặt chốt ở đâu | Chặn được gọi API? | Chặn được chiếm slot sweep? |
|---|---|---|
| Redis (circuit breaker) — đã thử, revert | ✅ | ❌ **Không** — row vẫn được SELECT, vẫn chạy `_check_prior_signals`, `check_ip_privacy`, vẫn ghi `api_usage_logs` |
| Cột `visitors.resolution_deferred_until` + filter trong sweep | ✅ | ✅ |

`resolution_runner.py` lấy `LIMIT 20`/site, sắp theo `intent_score DESC`. Visitor bị hoãn giữ
nguyên `anonymous` và **vẫn tiếp tục tăng intent** khi họ quay lại → luôn nằm top. Có ≥20 visitor
bị hoãn là **visitor mới không bao giờ lọt vào batch** cho tới khi outage hết. Redis không cứu
được vì nó chỉ bỏ qua lời gọi HTTP, không bỏ qua việc chọn row.

### Thiết kế đề xuất

1. Migration: thêm `visitors.resolution_deferred_until TIMESTAMP NULL`.
2. Đếm outage **theo tầng**, không gộp (xem bẫy #1 dưới):
   - tầng person-graph: leadpipe / capturify / rb2b
   - tầng IP→company: pdl_ip / ipinfo
3. Cuối waterfall: nếu **tầng đáng lẽ khớp được visitor này** không có ai trả lời →
   giữ `anonymous` + đặt `resolution_deferred_until = now() + backoff`.
4. Sweep thêm điều kiện: `(resolution_deferred_until IS NULL OR resolution_deferred_until <= now())`.
5. Backoff tăng dần + trần cứng (ví dụ 15p → 1h → 6h → 24h, tối đa N lần rồi mới chịu đánh
   `unresolvable`) — để credential hỏng vĩnh viễn không tạo vòng lặp vô tận.

## Vì sao lần đầu hỏng (session 3) — đọc kỹ trước khi làm lại

### Bẫy #1 — gộp bộ đếm 2 tầng làm fix không bao giờ chạy

Bản đầu dùng **một** cặp biến đếm `_providers_answered` / `_providers_unavailable` cho cả 5
provider. Chỉ cần **một** provider bất kỳ trả lời là `answered > 0` → vẫn đánh `unresolvable`.

Ca thực tế phổ biến nhất lại đúng là ca đó, tái hiện được bằng chạy thật:

```
leadpipe/capturify/rb2b  → 403 "Organization is expired"  (dùng CHUNG một tài khoản hỏng)
ipinfo                   → trả lời bình thường: không thấy công ty
⇒ answered=1, unavailable=3  →  identity_status = 'unresolvable'
```

Tức là fix **không ăn ở đúng ca nó sinh ra để sửa**. Bài học: nhánh code được test không đồng
nghĩa hệ thống được test — cả 4 test trạng thái cuối đều **tự gán tay** biến đếm rồi gọi thẳng
`_finalize_unmatched`, không lần nào chạy `resolve()` thật, nên không thể lộ ra lỗi này.

### Bẫy #2 — Redis circuit breaker chặn nhầm chỗ

Thêm breaker (Redis `INCR`/`EXPIRE`, mở mạch sau 3 lần lỗi liên tiếp) tưởng là chốt chặn
retry-storm. Nó bỏ qua được lời gọi HTTP nhưng **không** ngăn row bị SELECT → không giải quyết
vấn đề chiếm slot. Kèm theo 2 lỗi riêng của nó:

- `INCR` rồi `EXPIRE` **không nguyên tử**: chết giữa 2 lệnh → key không có TTL → provider bị tắt
  **vĩnh viễn, im lặng**, chỉ gỡ được bằng `redis DEL` tay. Ngược hẳn cam kết "fail-open" của
  chính module.
- Đếm theo *liên tiếp*: provider hỏng ngắt quãng 50% gần như không bao giờ đạt 3 lần liên tiếp →
  breaker không bao giờ mở.

### Bẫy #3 — hoãn rồi vẫn tốn tiền

Có 2 đường tiêu tiền/quota **nằm ngoài** breaker, vẫn chạy mỗi lượt sweep cho visitor bị hoãn:

- `check_ip_privacy` (ipinfo trả phí) chạy trước mọi bộ đếm, và **không cache khi lỗi**.
- `_log_resolution` vẫn ghi + commit `api_usage_logs` cho cả nhánh bị bỏ qua.

### Bẫy #4 — cache âm 24h nuốt mất lần thử sau

`_resolve_ip_company_parallel` chỉ trả về domain, người gọi không phân biệt được "IP này không có
công ty" với "cả 2 provider đều chết". Outage → ghi `__none__` TTL **24 giờ** cho IP đó → lượt
sweep sau bỏ qua hẳn bước IP→company dù provider đã hồi. Phải chặn ghi cache âm khi có outage.

## Related Code Files

- Modify: `apps/api/services/identity_resolver.py` — bộ đếm theo tầng, nhánh trạng thái cuối,
  chặn ghi cache âm khi outage
- Modify: `apps/api/services/resolution_runner.py` — thêm điều kiện lọc mốc hoãn vào sweep query
- Modify: `apps/api/models/visitor.py` + migration mới — cột `resolution_deferred_until`
- Modify: `apps/api/routers/visitors_helpers.py` — thêm skip reason `provider_outage`
  (hiện outage bị báo nhầm thành `recently_attempted`, xem Known-gap Phase 2)
- Tests: **bắt buộc có test chạy `resolve()` end-to-end** cho ca "graphs chết + ipinfo sống",
  không chỉ test `_finalize_unmatched` với biến gán tay

## Success Criteria

- [ ] Ca "3 person-graph chết 403 + ipinfo trả lời no-match" → visitor **không** bị `unresolvable`
      (test end-to-end qua `resolve()`, không gán tay bộ đếm)
- [ ] Ca "provider trả lời, không ai khớp" → vẫn `unresolvable` như cũ
- [ ] Ca "không cấu hình provider nào" → vẫn terminal, không tạo vòng lặp sweep
- [ ] Outage kéo dài: visitor bị hoãn **không** chiếm slot sweep (kiểm bằng query, có ≥20 visitor hoãn
      thì visitor mới vẫn vào được batch)
- [ ] Credential hỏng vĩnh viễn: backoff chạm trần rồi dừng, không lặp vô hạn
- [ ] Outage **không** ghi cache âm `__none__` cho IP
- [ ] `check_ip_privacy` không bị gọi lại mỗi lượt cho visitor đang hoãn

## Risk Assessment

| Rủi ro | Mitigation |
|---|---|
| Lặp lại bẫy #1 — fix không ăn ở ca thật | Test end-to-end qua `resolve()` là tiêu chí đóng phase, không phải test nhánh |
| Hoãn quá lâu → coverage tụt mà không ai biết | Log `resolution_deferred_provider_outage` + đếm được trong audit script |
| Backoff không trần → visitor kẹt mãi ở `anonymous`, sweep quay vòng | Trần cứng số lần hoãn, hết trần thì chấp nhận `unresolvable` |
| Migration thứ 13 chồng lên 12 cái đang chờ | Chạy `alembic heads` ngay trước khi tạo; round-trip trên Postgres dùng-một-lần |
