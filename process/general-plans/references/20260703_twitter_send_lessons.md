# Lessons Learned — Twitter/X draft send failures (2026-07-03)

Bối cảnh: draft "chưa duyệt" không hiện ở tab Pending → điều tra ra 3/3 draft đã duyệt đều gửi Twitter thất bại (`status=failed`). Quá trình chẩn đoán đi sai hướng vài bước. Ghi lại để lần sau không lặp.

---

## 1. Sự thật cuối cùng (ground truth)

- **Tab Pending trống là ĐÚNG dữ liệu**, không phải bug. Cơ chế: 1 post → AI tạo 1–3 draft `pending`; duyệt 1 cái thì các cái còn lại tự chuyển `rejected` (`_auto_reject_siblings` trong `apps/api/routers/drafts.py`). "Draft chưa duyệt" nằm ở tab **Rejected**, không phải Pending.
- **App X CÓ quyền ghi.** Đo trực tiếp: `GET /2/users/me` → 200, header `x-access-level = read-write`, scope `tweet.write`. Đã trả tiền X API. → Không phải lỗi quyền, không phải lỗi gói free.
- Lỗi gửi nhắm vào **vòng đời token/refresh**, không phải quyền.

---

## 2. Bài học — cách CHẨN ĐOÁN (cho lần sau)

**BL-1. Đừng nhảy ngay vào giải pháp browser-cookie khi gửi Twitter fail.**
Đường Playwright (`twitter_browser/`) chỉ là fallback khi API trả 403. Bước ĐẦU TIÊN phải là kiểm tra API path: `x-access-level` (read-write?) + token còn hạn không. Xác định API 200 hay 403/401 TRƯỚC, rồi mới quyết định.

**BL-2. X CHẶN login tự động — đường browser là ngõ cụt.**
Chạy `twitter_login.py` bằng Playwright/Chrome-for-Testing → X trả *"We've temporarily limited your login"* (anti-bot). Không lấy được cookie qua automation. Khi API đã có quyền ghi thì KHÔNG dùng browser fallback. Bấm login lại nhiều lần chỉ càng bị siết.

**BL-3. Đừng đăng nhập X bằng nút "Continue with Google/Apple" trong browser tự động.**
Google chặn OAuth trên automated browser. Nếu buộc phải login thủ công thì dùng username + password trực tiếp.

**BL-4. "Diagnostic chỉ đọc" mà gọi token refresh thì KHÔNG còn là chỉ-đọc.**
X OAuth2 refresh-token là **dùng-một-lần, tự xoay** (single-use rotation, do scope `offline.access`). Mỗi lần refresh: token cũ chết, X trả token mới. Gọi refresh = làm thay đổi trạng thái bên X.
→ Muốn đo an toàn: **(a)** dùng token còn hạn, KHÔNG refresh; hoặc **(b)** nếu buộc refresh thì phải LƯU token mới về DB ngay trong cùng thao tác. **Tuyệt đối không refresh-mà-không-lưu trên prod** — sẽ làm chết refresh-token trong DB (chính lỗi đã mắc hôm nay → phải reconnect Twitter).

**BL-5. Tên service Railway = `retarget-agent`** (không phải `api`). `railway logs --service retarget-agent`. Env = production, url api.getbeam.fyi.

---

## 3. Bài học — về CODE (để không tái diễn)

**CODE-1. `sender._refresh_if_expired` nuốt lỗi refresh.**
Khi refresh fail, nó trả lại access-token đã hết hạn → gửi lên X ăn 401/403 → draft `failed`. Người dùng chỉ thấy "failed" mơ hồ. Nên: refresh fail → báo lỗi rõ "Reconnect Twitter", đừng âm thầm dùng token chết.

**CODE-2. Rủi ro RACE trên refresh-token dùng-một-lần.**
Nếu 2 draft được duyệt gần như đồng thời → cả hai đọc cùng refresh-token → cả hai refresh → chỉ 1 rotation thắng, cái kia làm refresh-token vừa lưu thành cũ → lần gửi sau fail. Fix: serialize gửi theo từng account (advisory lock hoặc khoá per-account), giống pattern trong `[[job-architecture-preferences]]`.

**CODE-3. Fallback browser mong manh — cân nhắc bỏ.**
Khi API đã có `tweet.write`, đường browser chỉ thêm điểm gãy. Giữ lại chỉ khi thực sự cần vượt giới hạn free-tier; còn không thì để API 403 báo lỗi thẳng.

---

## 4. Việc cần làm để chốt (còn mở)

1. **User reconnect Twitter** (Social Accounts → ngắt @julleybuilds → nối lại) — ghi token tươi qua luồng OAuth của app. Bắt buộc, vì diagnostic đã tiêu refresh-token trong DB.
2. Sau reconnect: tail `railway logs --service retarget-agent`, tạo draft mới → Approve → đọc kết quả gửi thật (200 hay 403/401 + lý do) → sửa dứt điểm.
