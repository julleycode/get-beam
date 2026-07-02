# Phase 1 — Sửa map variant → gói (lỗ #4)  ⬜

**An toàn, không đổi hành vi user. Làm trước.**

## Vấn đề
`_variant_to_plan` ([apps/api/routers/billing.py:92](../../apps/api/routers/billing.py)) build map theo `settings.ls_variant_*`, mặc định `""`. Env trống/gõ sai:
- Khách Max thật → map ra `"free"` (tự hạ cấp âm thầm).
- Payload thiếu `variant_id` → `str(... or "")` = `""` → nếu env cũng trống thì ra `"max"` (cho nhầm gói cao).

## Thay đổi
1. Trong `_variant_to_plan`: build map **chỉ từ key truthy sau `.strip()`**; lookup cũng `.strip(str(variant_id))`. Empty/không map được → `"free"`.
2. `_apply_subscription` (billing.py:377): nếu `variant_id` rỗng nhưng status entitled → **log cảnh báo + giữ plan cũ của user** (đừng đổi mù).
3. Startup assert: khi billing bật (`lemonsqueezy_webhook_secret` có) mà 1 trong 4 `ls_variant_*` rỗng → log error rõ ràng lúc boot (`main.py` startup hoặc `config.py`).

## Touchpoints
- `apps/api/routers/billing.py` (`_variant_to_plan` ~92-100, `_apply_subscription` ~377-384)
- `apps/api/main.py` hoặc `apps/api/config.py` (assert lúc khởi động)

## Blast radius
Chỉ ảnh hưởng đường webhook LS. Không đụng user đang dùng. Prod hiện env có set đủ → hành vi bình thường không đổi.

## Kiểm thử
- Unit: `_variant_to_plan("")` → `"free"`; có whitespace `" 111"` vs `"111"` → map đúng; env trống → không collapse ra `"max"`.
- Test webhook idempotency cũ vẫn pass (`tests/integration/test_backlog_fixes.py`).

## Rollback
Revert 1 commit. Không state thay đổi.
