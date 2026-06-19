# Chuyển thanh toán: Stripe → Lemon Squeezy

**Ngày:** 19-06-2026
**Lý do:** Stripe không hỗ trợ Việt Nam. Lemon Squeezy là Merchant of Record (tự lo thuế/VAT), trả tiền về VN qua Wise, hợp indie ở VN.
**Phạm vi:** Chỉ đổi đường thu tiền gói Pro/Max. Free signup + onboarding KHÔNG đổi (đã live).

---

## A. Việc của bạn — trên Lemon Squeezy (làm song song khi mình code)

⬜ 1. Đăng ký [lemonsqueezy.com](https://lemonsqueezy.com), điền hồ sơ, tạo **Store**.
⬜ 2. Settings → Payouts → nối **Wise** (hoặc PayPal) để nhận tiền về VN.
⬜ 3. Tạo **2 product**, mỗi product **2 variant** (tổng 4):
   - Pro — Monthly $19, Yearly $190
   - Max — Monthly $49, Yearly $490
   - (giá tùy bạn sửa)
⬜ 4. Lấy **API key**: Settings → API → tạo key.
⬜ 5. Lấy **Store ID** + **4 Variant ID** (mở từng variant, ID nằm trên URL/trang).
⬜ 6. Tạo **Webhook**: Settings → Webhooks → Add:
   - URL: `https://api.getbeam.fyi/api/v1/billing/webhook`
   - Events: `subscription_created`, `subscription_updated`, `subscription_cancelled`, `subscription_payment_failed`
   - Lưu → lấy **Signing secret**
⬜ 7. Đưa mình 7 giá trị (API key, Store ID, 4 Variant ID, Webhook secret) — hoặc tự dán vào Railway.

> ⚠️ Test trước: LS có **Test mode** riêng (toggle trong dashboard). Làm 1 lần ở test, chạy thông rồi mới chuyển live.

---

## B. Việc của mình — code

### Phase 1 — Backend (`apps/api`)  ⬜
- `config.py`: thêm biến — `lemonsqueezy_api_key`, `lemonsqueezy_store_id`, `lemonsqueezy_webhook_secret`, `ls_variant_pro_monthly/yearly`, `ls_variant_max_monthly/yearly`.
- `services/billing.py`: map `plan+interval ↔ variant_id` (thay cho price_id của Stripe).
- `routers/billing.py`:
  - `POST /checkout`: gọi LS API tạo checkout, gắn `user_id` vào custom data, trả URL.
  - `POST /webhook`: verify chữ ký HMAC-SHA256, xử lý 4 event, cập nhật `user.plan` + `subscription_status` + ngày gia hạn.
  - `POST /portal`: trả `customer_portal` URL của subscription LS (khách tự huỷ/đổi gói).
  - `GET /status`: giữ nguyên.
- Model `user`: **tái dùng cột cũ** (`stripe_customer_id`, `stripe_subscription_id` lưu id của LS) → KHÔNG cần migration DB.

### Phase 2 — Frontend (`apps/web`)  ⬜
- `pricing/page.tsx`, `dashboard/billing/page.tsx`, `lib/api.ts`: giữ nguyên hợp đồng `createCheckout`/`createPortal` — chỉ kiểm tra lại cho khớp. Gần như không đổi.

### Phase 3 — Bật & test  ⬜
- Bạn dán 7 biến vào Railway (production env, service retarget-agent) → backend tự deploy lại.
- Test mua thật 1 lần → kiểm tra tài khoản lên gói Pro + webhook chạy.

---

## C. KHÔNG đụng tới
- Free signup, onboarding (đang live).
- Code Stripe cũ: để yên (dormant), gỡ hẳn sau khi LS chạy ổn.

---

## Trạng thái: ⬜ Chờ duyệt → code Phase 1+2
