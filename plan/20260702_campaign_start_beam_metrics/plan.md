# Campaign: 1 nút "Start beam" + Test email + Chỉ số open/click/quay lại

**Ngày:** 2026-07-02
**Trạng thái:** ✅ Code xong toàn bộ 5 phase (2026-07-02) — chưa commit/deploy

## Vấn đề

1. Trang Campaigns có 3 nút khác nhau tùy trạng thái (Approve / Start / Send emails) — rối, người dùng không biết bấm gì. Muốn 1 nút duy nhất: **"Start beam"**.
2. Chưa có cách gửi email thử về địa chỉ của mình để xem trước khi gửi thật.
3. Chưa có chỉ số: bao nhiêu người mở email (open rate), bấm link (click rate), và **ai** quay lại website.

## Hiện trạng (đã scan code)

- Flow trạng thái backend: `draft → approved → active → completed/paused` ([campaigns.py:24](apps/api/routers/campaigns.py)). Mỗi bước 1 nút riêng trên UI ([campaigns/page.tsx:131](apps/web/src/app/dashboard/campaigns/page.tsx)).
- Gửi email qua SendGrid ([email_sender.py](apps/api/services/email_sender.py)); người nhận lấy từ segment, có đủ gate an toàn (suppression, do_not_email, giới hạn 50 email/giờ, không gửi trùng).
- **Click tracking CÓ RỒI**: link trong email được gắn token `_bid`, khi bấm sẽ đi qua `/c/{site_id}` ([click.py:80](apps/api/routers/click.py)) → set cookie → khi quay lại site, pixel nhận ra đúng người. Nhưng chưa ghi `clicked_at` vào touchpoint.
- **Open tracking CHƯA CÓ**: cột `opened_at` trong bảng `campaign_touchpoints` có sẵn nhưng không ai ghi vào ([campaign.py:55](apps/api/models/campaign.py)).
- Chưa có endpoint thống kê campaign, chưa có test-send.

## Giải pháp — 5 phase (an toàn trước, ROI cao trước)

| Phase | Nội dung | Rủi ro |
|---|---|---|
| 1 | 1 nút "Start beam": endpoint `/start` gộp approve+activate+send (có dialog xác nhận trước khi gửi thật) | Thấp |
| 2 | Test email: nhập tay email admin, gửi bản thử có prefix `[TEST]` | Thấp |
| 3 | Ghi nhận open (pixel 1x1 trong email) + click (nối vào redirect có sẵn) | Thấp |
| 4 | API thống kê + UI: open rate, click rate, danh sách ai quay lại | Trung bình (query events) |
| 5 | Tests + verify toàn bộ | — |

## Quyết định thiết kế (cần anh xác nhận)

1. **"Start beam" = 1 bấm gửi luôn** (sau dialog xác nhận). Bấm nút = phê duyệt luôn, không còn bước Approve riêng. Vẫn giữ luật "người thật bấm mới gửi" — dialog xác nhận là chốt chặn.
2. **Pause/Resume giữ lại** làm nút phụ (không phải CTA chính) — dừng campaign vẫn cần.
3. Campaign social (không phải email): "Start beam" chỉ kích hoạt, không gửi gì.
4. **Open rate sẽ không tuyệt đối chính xác** — Apple Mail tự "mở" email nên số open thường bị đếm dư. Click rate + "ai quay lại" đáng tin hơn. Nói thật trước.

## Ngoài phạm vi

- Metrics cho social campaign (chỉ làm email).
- Resend/follow-up tự động theo lịch.
- Dashboard tổng hợp metrics nhiều campaign (chỉ làm trang chi tiết từng campaign).

## Tiến độ

- ✅ Phase 1 — Nút "Start beam" (endpoint `POST /{site}/{campaign}/start`; UI gộp 1 CTA + Pause phụ)
- ✅ Phase 2 — Test email (`POST /test-send`, EmailStr validate, đếm vào hourly cap, dialog nhập tay + nhớ localStorage)
- ✅ Phase 3 — Ghi open/click (router `/o/{touchpoint_id}` GIF 1x1; `_tp` trên link; events ingest stamp clicked_at+opened_at, site-scoped)
- ✅ Phase 4 — Thống kê + ai quay lại (`GET /stats`; trang chi tiết: StatTile + bảng returned visitors)
- ✅ Phase 5 — Tests + verify (7 integration mới + 5 unit mới; 807 pass toàn suite; tsc + lint + next build sạch)

## Sai lệch so với plan (có lý do)

1. **Phase 3 click**: plan viết "nối vào redirect /c/ có sẵn" — sai giả định. Link campaign KHÔNG đi qua /c/ (chỉ ESP-flow dùng). Cách làm thật: gắn `_tp={touchpoint_id}` cạnh `_bid` trên link; pixel vốn gửi full URL về ingest → backend parse `_tp` và stamp. **Không đụng pixel/tracker.js** (tránh gotcha minify), không đụng /c/.
2. **Phase 4 list page**: bỏ mini-metrics ("5 opens · 3 clicks") trên trang list — sẽ gây N+1 fetch mỗi row. Trang chi tiết có đủ.
3. Test-send KHÔNG decorate link (_bid/_tp) — click từ email test không được tạo VisitorEmail rác cho địa chỉ admin.

## Còn lại (ngoài code)

- 1 test fail có sẵn trên main (`test_demo_identify_graph` — 'device' vs 'person'), không liên quan thay đổi này (đã verify bằng stash).
- Chưa commit/deploy. Worktree đang lẫn thay đổi chưa commit của việc khác (social_avatar).
- Open tracking chỉ áp dụng cho email gửi SAU khi deploy (email cũ không có pixel/_tp).
