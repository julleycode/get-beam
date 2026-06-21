# Phase 01 — Điều tra vì sao dashboard trả 404 ở server

**Trạng thái:** ⬜ TODO
**Rủi ro:** 0 (chỉ đọc/đo, không sửa code)
**Mục tiêu:** Biết CHÍNH XÁC vì sao mọi route `/dashboard/*` trả trang 404 của Next ở server, để Phase 3 sửa đúng chỗ.

---

## Bối cảnh

- `/dashboard` (Overview) KHÔNG dùng `useSearchParams` mà server vẫn trả 404 → không chỉ do CSR bailout của các page khác.
- Cần repro local (`npm run build && npm start`, KHÔNG phải dev mode) vì dev mode che mất hành vi prerender thật.

## Bước

1. Build prod local:
   ```bash
   cd apps/web && npm run build 2>&1 | tee /tmp/beam-build.log
   ```
   - Đọc log: Next có in cảnh báo route nào "client-side rendering" / "deopted into client rendering" / "missing suspense" không? Ghi lại danh sách route.
   - Xem bảng route cuối build: `/dashboard*` là `○ (Static)`, `λ (Dynamic)`, hay bị đánh dấu lạ?

2. Chạy prod local + curl từng route, ghi status + có text khung không:
   ```bash
   npm start &
   for p in /dashboard /dashboard/visitors /dashboard/segments; do
     curl -s -o /dev/null -w "$p -> %{http_code}\n" http://localhost:3000$p
   done
   ```

3. Phân biệt 3 khả năng (kết luận chọn 1):
   - **(a)** CSR bailout từ `useSearchParams` + flag `missingSuspenseWithCSRBailout:false` → fix = bọc Suspense (Phase 3).
   - **(b)** Toàn nhánh dynamic do Clerk/`ClerkProvider` đọc gì đó lúc render → fix có thể là `export const dynamic` hoặc cấu trúc lại.
   - **(c)** Prerender lúc build sinh ra 404 vì thiếu env/redirect → fix = cấu hình build.

4. Test nhanh giả thuyết (a): tạm bọc `useSearchParams` của 1 page (vd `segments`) trong `<Suspense>`, build lại, xem route đó còn 404 không. **Đây là test, revert sau** — không tính là sửa thật.

## Xong khi

- [ ] Có 1 câu kết luận: "Dashboard trả 404 SSR vì ___" (chọn a/b/c, kèm bằng chứng từ build log + curl).
- [ ] Biết Phase 3 cần bọc Suspense là đủ, hay cần thêm việc gì.
- [ ] Ghi kết luận vào cuối file này.

## Kết luận (chạy 2026-06-21)

**Dashboard trả 404 ở server VÌ Clerk middleware bảo vệ route, KHÔNG phải CSR bailout.**

Bằng chứng:
- `npm run build` PASS, mọi route là `ƒ (Dynamic) — server-rendered on demand`, kể cả `/dashboard` (8.08kB / 126kB). Build có in `Middleware 91.9 kB`.
- `src/middleware.ts` dùng `clerkMiddleware` + `auth().protect()` cho mọi route không-public. `/dashboard*` không nằm trong `isPublicRoute`.
- Curl `/dashboard` (signed-out) → header:
  ```
  HTTP/1.1 404 Not Found
  x-clerk-auth-reason: protect-rewrite, dev-browser-missing
  x-clerk-auth-status: signed-out
  x-middleware-rewrite: /clerk_1782019620618
  ```
- `/login` (public) → 200. `/dashboard/visitors` (protected) → 404 cùng `protect-rewrite, signed-out`.

→ **404 khi curl là Clerk chặn request chưa đăng nhập — chuyện bình thường, không phải lỗi render.** Khi user đã đăng nhập, middleware cho qua, page `ƒ Dynamic` **SSR bình thường** (ClerkTokenGate render skeleton lúc SSR vì `useAuth` client chưa loaded → server trả HTML có khung+skeleton).

## Hệ quả (QUAN TRỌNG)

- **Tiền đề Plan M (blank/404 do CSR bailout) SAI.** Giả thuyết (a) bị bác. Đúng là (b): Clerk middleware.
- **Phase 3 (bọc Suspense + bỏ flag) gần như VÔ NGHĨA** — page đã SSR được, không bị bailout chặn.
- Không đo được trải nghiệm signed-in bằng curl. Cần biết user **THẤY GÌ** lúc chậm (trắng? khung+skeleton rồi chờ? hiện hết nhưng lag?) để chọn fix đúng.
- Nghi vấn mới: nếu signed-in đã SSR skeleton ngay → chậm là **khoảng từ skeleton → data thật** (Clerk 320KB load + session resolve + fetch). Fix thật = **L (server-prefetch data qua `auth()` server-side)**, không phải M.
