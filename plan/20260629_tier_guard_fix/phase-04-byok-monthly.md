# Phase 4 — BYOK mở cap tháng (lỗ #2)  ⬜

**Nới lỏng (tốt cho user). Rủi ro thấp. Làm cùng billing.py với Phase 2.**

## Vấn đề
`check_usage_allowed` (cổng cap THÁNG) không bao giờ gọi `is_full_byok`. Cap NGÀY thì có honor BYOK, docstring + UI + câu lỗi đều hứa "Add your own API keys to unlock unlimited" — nhưng user free nạp đủ key vẫn bị chặn ở 10/tháng.

## Quyết định cần xác nhận (Quyết định #2 ở plan.md)
**Đề xuất: BYOK = không giới hạn THÁNG thật** (vì chạy bằng key của user, mình không tốn tiền — khác paid-OSINT là key hệ thống nên KHÔNG miễn).

## Thay đổi (theo hướng đề xuất)
1. `check_usage_allowed` (và `try_consume_monthly` ở Phase 2): **return True sớm khi `is_full_byok(db, user_id)`** (không tăng counter).
   - Lưu ý: `check_usage_allowed` hiện nhận `user_id` — cần truyền `db` (đã có). `is_full_byok` nhận `uuid.UUID`; ép kiểu cho khớp.
2. Đồng bộ sự thật: sửa docstring `usage_limits.py:5` cho đúng (BYOK miễn cả ngày lẫn tháng).
3. Câu lỗi: chỗ nào còn chặn (non-BYOK) giữ "Add your own API keys..."; với BYOK thì không bao giờ tới đó nữa → không còn dead-end.

### Nếu bạn chọn KHÔNG miễn (giữ cap tháng cho BYOK)
→ KHÔNG đổi logic; thay vào đó **bỏ lời hứa sai**: sửa câu ở `visitors.py:659`, `visitors_helpers.py:232`, docstring `usage_limits.py:5` → nói rõ BYOK chỉ mở cap NGÀY, cap THÁNG theo gói vẫn áp; và bỏ "unlimited" ở dashboard cho user còn bị cap tháng.

## Touchpoints
- `apps/api/services/billing.py` (check_usage_allowed + try_consume_monthly)
- `apps/api/services/usage_limits.py` (docstring)
- (nhánh không-miễn) `apps/api/routers/visitors.py`, `visitors_helpers.py`, `apps/web` dashboard copy

## Blast radius
Hướng đề xuất chỉ NỚI cho user full-BYOK → không cắt ai. Không rủi ro tốn tiền (key của họ).

## Kiểm thử
- Free user + đủ 6 key BYOK hợp lệ → resolve cái thứ 11 trong tháng vẫn được; counter không chặn.
- Free user KHÔNG BYOK → vẫn chặn ở 10.

## Rollback
Revert; quay lại BYOK-blind (chặt nhầm BYOK).
