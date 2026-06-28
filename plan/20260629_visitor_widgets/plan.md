# Visitor analytics → widget dashboard

Mục tiêu: biến 3 chart trên trang Visitors (Funnel, Traffic fit, Capture by browser)
thành dạng **widget gọn** kiểu App-Store-stat: mỗi widget có toggle **Last 30 days /
Lifetime**, có thể xem **line graph theo ngày**, và cho phép **thêm/bớt widget** tùy biến.

Tham khảo style: thẻ nhỏ, có nút period + "View As Graph" + "Add Widget".

---

## P1 — Widget gọn + toggle Last 30d/Lifetime  ✅ DONE (2026-06-29)

- [x] `components/ui/period-toggle.tsx` — segmented Last 30 days / Lifetime (+ `periodToDays`, lifetime = 36500 ngày = all-time).
- [x] KpiStrip / TrafficFitCard / BrowserCaptureCard: thêm state `period`, gọi API với `periodToDays(period)`, toggle ở header, bỏ `mb-6`.
- [x] Trang Visitors: gom 3 card vào grid `md:grid-cols-2 xl:grid-cols-3` (gọn, ít diện tích).
- Backend: không đổi — 3 endpoint đã nhận `days/window_days`.

## P2 — "View as graph": line graph theo ngày  ⬜ TODO

Cần:
1. **Backend**: endpoint chuỗi theo ngày, ví dụ
   `GET /api/v1/sites/{id}/timeseries?metric=visitors|identified|high_intent&days=30`
   → trả `[{date, value}, ...]`. Gom theo ngày từ events/visitors (naive-UTC, xem
   convention ở visitors.py). Cân nhắc cache.
2. **Chart lib**: cài `recharts` (nhẹ, React-friendly) — thêm dependency mới, build phải pass.
3. **Frontend**: mỗi widget thêm nút "View as graph" (toggle number ↔ line). Line dùng recharts `<LineChart>`, màu theo token brand.
4. Period toggle tái dùng cho cả graph (30d = 30 điểm, lifetime = gom tuần/tháng để không quá dày).

Rủi ro: dependency mới + endmpoint mới; query nặng nếu data lớn (hiện prod nhỏ nên ok).

## P3 — "Add widget" tùy biến  ⬜ TODO (tách plan riêng khi làm)

Cần:
1. **Widget registry**: danh sách widget khả dụng (funnel, traffic-fit, browser, +mới).
2. **Lưu layout per-user**: cột mới trên `users` (JSONB `dashboard_widgets`) hoặc bảng riêng.
   Backend GET/PUT layout.
3. **UI**: tile "Add widget" → chọn từ registry; bỏ widget; (kéo-thả sắp xếp = optional, sau).
4. Phần "Similar apps" trong ảnh tham khảo = không áp dụng (khác domain).

Đề xuất: làm P2 trước (giá trị xem-xu-hướng cao), P3 sau vì cần schema + persistence.

---

## Trạng thái
- P1: SHIPPED. P2: chưa bắt đầu. P3: chưa bắt đầu.
