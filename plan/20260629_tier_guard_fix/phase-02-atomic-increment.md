# Phase 2 — Tăng counter atomic, hết race (lỗ #5)  ⬜

**An toàn (chỉ chặt hơn, không nới). Làm sớm.**

## Vấn đề
`check_usage_allowed` đọc count (billing.py:34, không khóa) rồi `increment_usage` ghi sau (billing.py:74) — 2 câu tách rời. 2 lần resolve song song (manual + sweep + celery + background) lúc count=9 cùng pass → count=11. Vượt cap chút ít.

## Thay đổi
Thêm hàm atomic trong `apps/api/services/billing.py`:
```python
async def try_consume_monthly(db, user_id) -> bool:
    # đọc limit theo plan (None=unlimited → return True luôn, không tăng)
    # UPDATE users SET monthly_identified_count = monthly_identified_count + 1
    #   WHERE id=:id AND monthly_identified_count < :limit
    # return rowcount == 1
```
- Gọi **tại thời điểm resolve thành công** thay cho cặp check→increment ở: `resolution_runner.py:73/87`, `visitors.py:654/666`, `tasks/resolution_tasks.py:83/98`, và path skip-reason `visitors_helpers.py:217` (chỗ này chỉ ĐỌC để báo lý do — giữ `check_usage_allowed` đọc-thường cho hiển thị, OK).
- Vẫn giữ `check_usage_allowed` cho mục đích HIỂN THỊ/skip-reason (không cần atomic).
- Giữ phần lazy monthly-reset (đang đúng — SQLAlchemy refresh, đã verify).

## Touchpoints
- `apps/api/services/billing.py` (+hàm mới, giữ reset)
- `apps/api/services/resolution_runner.py`, `apps/api/routers/visitors.py`, `apps/api/tasks/resolution_tasks.py`

## Lưu ý thứ tự với Phase 4 (BYOK)
Hàm atomic phải tôn trọng kết quả Phase 4: nếu BYOK = unlimited tháng thì `try_consume_monthly` trả True ngay (không tăng) cho user full-BYOK. Làm Phase 2 trước thì để TODO; hoặc làm Phase 4 trước rồi Phase 2 đọc luôn. → **Đề xuất gộp xét: làm Phase 4 ngay sau Phase 2, cùng đụng billing.py.**

## Blast radius
Đường resolve. Hành vi: cap được giữ ĐÚNG (không còn vượt). User bình thường không thấy khác.

## Kiểm thử
- Unit/integration: bắn N resolve song song lúc count=limit-1 → cuối cùng count == limit (không vượt). Mock resolve.
- Free user 10/tháng vẫn chặn đúng ở cái thứ 11.

## Rollback
Revert; cặp check→increment cũ vẫn chạy (chỉ quay lại race nhẹ).
