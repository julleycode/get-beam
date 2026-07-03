# Phase 05 — Google verification + chống lỗi + đo

Trạng thái: ⬜ · Rủi ro: Ngoài tầm code (chờ Google) · Phụ thuộc: Phase 02–04

## Google app verification (ngoài code, làm SONG SONG)
- Chuẩn bị: privacy policy + terms trên getbeam.fyi, video demo scope, giải thích vì sao cần `gmail.send`.
- Nộp qua OAuth consent screen → "Publish app" → submit for verification.
- Vì `gmail.send` là restricted scope → có thể cần **security assessment**. Thời gian: vài tuần → nhiều tháng tuỳ Google.
- Trong lúc chờ: giữ **Testing mode**, add early users làm test user (≤100). App hoạt động đầy đủ cho họ.

## Chống lỗi token (code)
- Refresh fail / `invalid_grant` (user gỡ quyền, đổi mật khẩu) → đánh dấu `email_senders.is_active=false`, campaign send **fallback Beam** + hiện banner "Gmail mất kết nối, bấm reconnect".
- Không để 1 sender hỏng làm chết cả campaign (đã fallback ở Phase 03).

## Đo / quan sát
- Log kênh gửi (gmail vs beam) + tỉ lệ fallback.
- (Tuỳ) đếm gmail send/ngày để cảnh báo gần ngưỡng.

## Docs
- Hướng dẫn ngắn cho user: "Kết nối Gmail để gửi từ email của bạn" (1 trang, có ảnh nút Connect).
- Ghi vào memory sau khi ship: kênh gửi mới + gotcha verify.

## Definition of done
- User connect Gmail → campaign + test-send đi qua Gmail user, Gmail KHÔNG hiện "via".
- User chưa connect → gửi y như cũ (Beam), không regression.
- Token hỏng → fallback Beam êm, có báo reconnect.
- Không đụng email hệ thống.
