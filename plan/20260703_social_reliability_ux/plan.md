# Plan — Social connection reliability UX (commercialize)

**Ngày:** 2026-07-03
**Trạng thái tổng:** 🔄 P1 `a621a28` · P2 `8ca2bf4` · P4 `550322c` SHIPPED (prod deploy) · còn P3, P5
**Bối cảnh:** sau sự cố Twitter send fail âm thầm (đã fix backend — token lifecycle, shipped main `75c7730`). Giờ làm phần **user tự hiểu + tự sửa** để bán được.

---

## Vấn đề

Kết nối mạng xã hội (X/LinkedIn...) là "trái tim" của Beam engage. Nhưng nó **gãy âm thầm**:

- Token hết hạn → gửi draft fail → user chỉ thấy chữ "Failed" trơ, không biết vì sao, không biết bấm gì.
- Không có cảnh báo TRƯỚC khi gãy.
- Draft "biến mất" (thực ra bị auto-reject khi duyệt bản khác) → user hoang mang.

Với sản phẩm **trả tiền**, đây là nguồn support ticket + churn số 1.

## Nguyên tắc

> User không bao giờ thấy lỗi thô mà thiếu **(a) lý do bằng tiếng người** + **(b) 1 nút sửa**. Và cảnh báo phải đến **trước** khi gãy, không phải sau.

Lưu ý: UI Beam = **tiếng Anh** (locale en-US) — copy mẫu dưới đây viết sẵn tiếng Anh. Giải thích plan bằng VN.

---

## 5 phase

| Phase | Mục tiêu 1 dòng | Migration? | Effort | ROI |
|---|---|---|---|---|
| **P1** — Connection health badge + Reconnect | Huy hiệu 🟢/🟡/🔴 trên Social Accounts + 1 nút Reconnect | Không | TB | Cao |
| **P2** — Fail reason + Retry | Draft failed hiện lý do tiếng người + nút Retry | **Có** (`drafts.failure_reason`) | TB | Cao |
| **P4** — Draft lifecycle relabel | Bản anh em auto-reject đổi nhãn "Not used — you picked another reply" | **Có** (`drafts.rejection_reason`) | Thấp–TB | TB (gỡ đúng confuse gốc) |
| **P3** — Proactive nudge | Cảnh báo in-app + email khi kết nối sắp/đã gãy | **Có** (`*.last_expiry_alert_sent_at`) | TB | Cao |
| **P5** — Connect-time write verify | Nối xong → kiểm quyền ghi → "Ready to post" / "Needs write access" | **Có** (`social_accounts.post_ready`) | Cao | TB |

## Thứ tự làm đề xuất (an toàn + ROI cao trước)

1. **P1 → P2 → P4** làm trước. Effort thấp/TB, **gỡ ~80% khó hiểu**, dữ liệu (`token_expires_at`) đã có sẵn ở API. P1 không cần migration → làm đầu tiên.
2. **P3 → P5** làm sau. P3 cần job nền + throttle; P5 effort cao (probe từng platform), là "nice-to-have" chốt trải nghiệm.

Mỗi phase độc lập, ship + deploy được riêng. Không phải làm hết mới có giá trị.

---

## Rủi ro chung

- **Timezone:** `token_expires_at` là UTC. Frontend phải quy về giờ local khi hiện "expiring soon". (Đã dính bug naive-UTC trước đây.)
- **Migration nhiều:** P2/P3/P4/P5 mỗi cái thêm cột. Alembic đang ở nhiều head trong lịch sử — chain migration cẩn thận off head hiện tại, tránh multi-head.
- **LinkedIn outreach accounts** (`outreach_connection_id`) dùng cookie, KHÔNG reconnect qua OAuth chuẩn → P1/P5 phải ẩn nút Reconnect/probe cho loại này.

## Rủi ro THƯƠNG MẠI (quyết trước khi scale — ngoài phạm vi code)

- **Auto-post lên X có trần chi phí.** Mọi khách nối X qua **1 app X của bạn** (gói API bạn trả) → giới hạn post chia cho TẤT CẢ khách. Nhiều khách active → đụng trần / phải lên gói X đắt.
- **Hướng giảm rủi ro:** gói rẻ để "reply" dạng **Copy/Open in X** (user tự đăng); auto-post để gói cao. Hợp mẫu [[beam-no-cli-decision]]. Cân nhắc khi định giá, không chặn plan này.

---

## Cách chạy / test (mỗi phase)

- Backend: `pytest` các file liên quan, chạy trên **pg local** (`brew postgresql@16`, override `DATABASE_URL`, KHÔNG đụng prod).
- Frontend: `tsc` + lint + chạy web local bấm thử; hoặc preview.
- Migration: `alembic upgrade head` local trước, verify off head hiện tại (không multi-head).
- Chi tiết từng phase ở `phase-0N-*.md`.

## File phase

- `phase-01-connection-health.md` — P1
- `phase-02-fail-reason-retry.md` — P2
- `phase-03-proactive-nudge.md` — P3
- `phase-04-draft-lifecycle-copy.md` — P4
- `phase-05-connect-verify.md` — P5
