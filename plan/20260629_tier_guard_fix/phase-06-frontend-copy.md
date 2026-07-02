# Phase 6 — Đồng bộ giá + bỏ hardcode (lỗ LOW)  ⬜

**An toàn. Tuỳ chọn, làm sau cùng.**

## Vấn đề
Giới hạn gói hardcode 3 nơi: `services/billing.py` PLAN_LIMITS (chuẩn), `pricing/page.tsx`, `dashboard/billing/page.tsx`. Đổi 1 nơi → 2 trang marketing nói sai. Cùng 1 trang billing có thể hiện 2 số khác nhau.

## Thay đổi
1. Expose bảng entitlement/limit qua API (vd thêm vào `GET /billing/status` hoặc endpoint `/billing/plans`).
2. Frontend render pricing + billing cards TỪ API thay vì chuỗi cứng.
3. Sửa lại câu marketing cho khớp Phase 5d (bỏ/sửa team seats, priority ID, API access nếu hoãn).

## Touchpoints
- `apps/api/routers/billing.py` (+ field/endpoint)
- `apps/web/src/app/pricing/page.tsx`, `apps/web/src/app/dashboard/billing/page.tsx`, `api-types.ts`

## Blast radius
Chỉ hiển thị. Không gate gì.

## Kiểm thử
- Đổi `PLAN_LIMITS["free"]` → cả 2 trang đổi theo, không lệch.
- `npm run build`.

## Rollback
Revert; quay lại chuỗi cứng.
