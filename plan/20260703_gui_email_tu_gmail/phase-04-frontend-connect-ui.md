# Phase 04 — Frontend: card Connect Gmail

Trạng thái: ⬜ · Rủi ro: Thấp · Phụ thuộc: Phase 02 (status/connect API)

## Vị trí (ĐÃ CHỐT)
**Trong trang Campaigns** — `apps/web/src/app/dashboard/campaigns/page.tsx`.
Đặt card/nút Connect Gmail ngay trong màn campaigns, gần khu vực Send / Send test, để user thấy "email sẽ gửi từ đâu" đúng lúc chuẩn bị gửi. Ví dụ:
- 1 banner nhỏ trên đầu list: `📧 Gửi từ: you@gmail.com ✓` hoặc `Chưa nối Gmail — đang gửi qua Beam. [Connect Gmail]`.
- Trong modal "Send test" / trước khi "Start beam": hiện rõ địa chỉ From hiện tại + link connect nếu chưa.

## UI
- Card **"Gửi email từ Gmail của bạn"**:
  - Chưa nối: nút **Connect Google** → gọi `GET /api/v1/email/connect/google` → redirect `auth_url`.
  - Đã nối: hiện `✓ Đang gửi từ you@gmail.com` + nút **Disconnect**.
  - Dòng giải thích ngắn: "Campaign email sẽ gửi từ địa chỉ này, không còn 'via Beam'."
  - Nếu đang Testing mode (chưa verify): banner nhẹ "App đang chờ Google duyệt — hiện chỉ email được cấp quyền test mới gửi được."
- Trang callback: đọc query `?gmail=connected|error` → toast phù hợp, refresh status.

## API client
- `apps/web/src/lib/api.ts`: thêm `getEmailSenderStatus()`, `connectGmail()`, `disconnectGmail()`.
- Dùng react-query cho status (theo convention repo).

## Verify (preview_*)
- Card render đúng 2 trạng thái (mock status).
- Bấm Connect → điều hướng sang Google (kiểm tra url có client_id + scope).
- Sau callback giả lập `?gmail=connected` → hiện email + toast.
- Không lỗi console; tsc + lint sạch (Vercel build lint — 1 lỗi lint là fail deploy, xem memory [[vercel-cli-via-npx]]).
