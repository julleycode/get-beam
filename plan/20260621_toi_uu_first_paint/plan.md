# Plan M — Dashboard hiện ngay (first paint), bớt trắng màn

**Ngày:** 2026-06-21
**Trạng thái:** 🔁 RESCOPED → Phase 4 (L). M (Phase 3) bỏ. User xác nhận triệu chứng = "skeleton rồi chờ data" → hướng đúng là server-prefetch (`phase-04-server-prefetch.md`).
**Người duyệt:** chủ repo (non-tech, review tay)

> ## ⚠️ CẬP NHẬT sau Phase 1 (2026-06-21)
>
> Phase 1 chứng minh **tiền đề ban đầu SAI**: `/dashboard` trả 404 khi curl **vì Clerk middleware bảo vệ route** (`auth().protect()` → `protect-rewrite` cho signed-out), KHÔNG phải CSR bailout. Build cho thấy `/dashboard` là `ƒ Dynamic` — **SSR bình thường khi đã đăng nhập**.
>
> Hệ quả:
> - **Phase 3 (Suspense + bỏ flag) gần như vô nghĩa** — page không bị bailout.
> - **Phase 2 (`loading.tsx`) vẫn hợp lệ** — rủi ro thấp, giúp điều hướng trong app.
> - Fix thật nhiều khả năng là **L (server-prefetch data qua `auth()` server-side)**, không phải M.
> - **CHẶN:** cần user mô tả họ THẤY GÌ lúc chậm (trắng / khung+skeleton rồi chờ / hiện hết nhưng lag) → mới chốt được fix. Chi tiết: `phase-01-dieu-tra.md` mục Kết luận.
>
> Phần dưới giữ nguyên làm hồ sơ, nhưng ĐỪNG làm Phase 3 theo nó tới khi rescope.

---

## 1. Vấn đề (đã đo, không đoán)

Dashboard sau khi đăng nhập load chậm **không phải vì số request**, mà vì **cách build**: toàn bộ vẽ trên browser (client-render), Clerk nặng chặn first paint.

Số đo prod (2026-06-21):

| Thứ | Đo được |
|-----|---------|
| Landing `getbeam.fyi` | nhanh, ~0.4–0.8s, 57KB ✅ |
| Backend API `/health` | ấm ~0.5s, không cold ✅ |
| Clerk JS `clerk.browser.js` | **320 KB**, ~0.9s tải |
| Clerk kiểm session `/v1/environment` | 0.5–1.3s |
| `/dashboard` ở server | trả **trang 404 của Next** (10.5KB), KHÔNG có khung dashboard |
| `loading.tsx` skeleton | **không có** ở route nào |

→ Người dùng mở `/dashboard`: thấy **trắng/404 chớp** trong ~2–4s tới khi tải xong ~320KB Clerk + chunk Next, hydrate, Clerk resolve session, rồi mới fetch data và vẽ.

**Đã làm trước plan này (không thuộc M):**
- `390576e` — dedup request (getMe 2→1, visitor-stats 2N→N, cache khi quay lại). Giảm số request, KHÔNG sửa first-paint.
- `acea970` — preconnect Clerk + API. Bớt ~0.1–0.4s handshake. Nhỏ.

---

## 2. Mục tiêu M

Biến first paint từ **trắng/404** → **hiện ngay cái khung (sidebar) + skeleton** trong khi Clerk + data tải nền.
Đây là cú nhảy "cảm giác nhanh" lớn nhất với công sức vừa.

**Thành thật về giới hạn:** M làm **cái khung/skeleton** hiện ngay. **Data thật** (visitor, site...) vẫn về SAU khi Clerk 320KB tải + resolve xong — M không sửa được khúc đó. Muốn data hiện ngay first paint là **L** (server-fetch sẵn, plan riêng).

---

## 3. Nguyên nhân kỹ thuật (giả thuyết mạnh + 1 ẩn số)

11 page dashboard là `"use client"` gọi thẳng `useSearchParams()` ở top-level. Cộng với `next.config.mjs` đặt `missingSuspenseWithCSRBailout: false` → Next cho cả route **render client hoàn toàn** (bỏ SSR) → server trả trắng/404.

**Ẩn số:** trang Overview (`/dashboard/page.tsx`) KHÔNG dùng `useSearchParams` mà server vẫn trả 404. → Phải repro + tìm chính xác lý do ở **Phase 1** trước khi sửa. Không sửa mù.

Cách sửa chuẩn (Phase 3): bọc mỗi `useSearchParams` trong `<Suspense fallback={skeleton}>` → route SSR được cái khung; bỏ flag `missingSuspenseWithCSRBailout` để bật lại rào chắn. **Không đụng logic Clerk auth.**

---

## 4. Các phase (an toàn → rủi ro hơn)

| Phase | Việc | Rủi ro | ROI cảm-giác-nhanh |
|-------|------|--------|--------------------|
| **01** | Điều tra + repro vì sao mọi route dashboard trả 404 SSR. Chỉ đọc/đo, không sửa. | 0 | (nền tảng) |
| **02** | Thêm `loading.tsx` skeleton mỗi route. Hiện skeleton tức thì khi chuyển trang trong app. | Thấp | Vừa |
| **03** | Bọc `useSearchParams` trong Suspense theo lô + bỏ flag → route SSR khung thật. Verify từng route 200. | Vừa | Cao |
| **04** (tùy chọn, = L) | Server-fetch sẵn user+sites, hiện data thật first paint. Plan riêng. | Cao | Rất cao |

Làm tuần tự, **dừng review sau mỗi phase**. Phase 3 chia lô (3–4 page/lô), verify rồi mới qua lô sau.

Chi tiết: `phase-01-dieu-tra.md`, `phase-02-loading-skeleton.md`, `phase-03-ssr-shell.md`.

---

## 5. Rủi ro & rollback

- **Clerk:** memory ghi Clerk từng làm sập prod repo này nhiều lần (ClerkProvider crash, instance switch, token race). M **cố tình không sửa** logic Clerk — chỉ thêm Suspense/loading + bỏ 1 flag config. Nếu lỡ đụng, dừng.
- **Bỏ flag `missingSuspenseWithCSRBailout`:** chỉ bỏ SAU khi đã bọc HẾT `useSearchParams`, nếu không **build fail**. Phase 3 bọc trước, bỏ flag là bước cuối + verify build.
- **Rollback:** mỗi phase 1 commit riêng, revert được độc lập. Verify trên preview trước khi push.
- **Verify mỗi route:** sau Phase 3, curl từng `/dashboard/*` phải trả 200 + có text khung (sidebar/skeleton), không còn "404: This page".

---

## 6. Không làm trong M (out of scope)

- Không bỏ/Thay Clerk. Không đổi luồng đăng nhập.
- Không sửa `ClerkTokenGate` / `ClerkAuthGuard` (đường auth nhạy cảm).
- Không giảm 320KB Clerk JS (việc đó nằm ngoài tầm, do Clerk).
- Server-fetch data = Phase 04/L, plan riêng.
