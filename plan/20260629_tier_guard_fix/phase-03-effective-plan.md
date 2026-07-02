# Phase 3 — effective_plan: gói = plan VÀ thời gian (lỗ #3)  ⬜

**Sửa đúng. Chỉ hạ những user ĐÁNG bị hạ. Rủi ro thấp-vừa.**

## Vấn đề
Hạ gói CHỈ dựa vào webhook `subscription_expired`. Không chỗ nào so `current_period_end`/`trial_ends_at` với hiện tại. Mất 1 webhook → user giữ pro/max **mãi mãi**.

## Thay đổi
Thêm `effective_plan(user) -> str` (đặt trong `entitlements.py` mới, hoặc `billing.py`):
```
nếu user.plan == "free": return "free"
nếu subscription_status không thuộc tập entitled: return "free"
nếu current_period_end có và < now (trừ grace cho 'past_due' dunning, vd +3 ngày): return "free"
ngược lại: return user.plan
```
- `get_plan_limits` / mọi gate đọc `effective_plan(user)` thay vì `user.plan` thô.
- Áp tại: `check_usage_allowed` (billing.py), và các gate Phase 5.
- `get_plan_limits`: log warning khi gặp plan lạ (lỗ info #160) thay vì im lặng về free.

## Touchpoints
- `apps/api/services/billing.py` (hoặc `entitlements.py`)
- Các call site gate (đa số đã qua `check_usage_allowed` nên tập trung sửa ở đó).

## Blast radius
User đã hết hạn nhưng plan còn stale → bị về free (ĐÚNG, đó là mục tiêu). Có grace cho `past_due` để không cắt nhầm người đang trong kỳ thử lại thanh toán. Người trả tiền hợp lệ KHÔNG bị ảnh hưởng (current_period_end ở tương lai).

## Kiểm thử
- Unit `effective_plan`: plan=pro + period_end quá khứ → "free"; + status active + period_end tương lai → "pro"; past_due trong grace → giữ pro; on_trial + trial quá khứ → free.
- check_usage_allowed dùng effective_plan: user hết hạn bị chặn như free.

## Rollback
Revert; quay lại đọc `user.plan` thô (lại phụ thuộc webhook).
