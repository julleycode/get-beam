# Phase 04 (L) — Server-prefetch data: bỏ khúc "skeleton rồi chờ"

**Trạng thái:** ⬜ TODO — ĐÂY LÀ HƯỚNG ĐÚNG (sau Phase 1 + xác nhận triệu chứng)
**Rủi ro:** Vừa–cao (đụng kiến trúc fetch + Clerk server-side). Làm theo lát, verify từng bước.
**Triệu chứng khớp:** user thấy khung+skeleton ngay, data mới về lâu (2026-06-21).

---

## Vì sao L sửa đúng

Hiện data đi đường client: HTML về (skeleton) → tải ~320KB Clerk JS → Clerk init → `ClerkTokenGate` đợi `getToken()` → MỚI fetch `me`/`sites` → rồi `visitor-stats`. Cả khúc Clerk client (~1–2s) nằm TRƯỚC khi fetch đầu tiên chạy.

L: fetch `me` + `sites` ngay trên **server** (Clerk `auth()` lấy token server-side, gọi backend), nhét sẵn vào react-query cache (`HydrationBoundary`). → HTML về đã kèm data → client hydrate là hiện luôn, KHÔNG đợi Clerk client + token round-trip.

Backend đã validate Clerk JWT → token server-side dùng được ngay, không đổi backend.

---

## Làm theo lát (lát 1 an toàn nhất → mở rộng dần)

### Lát 1 — Overview: prefetch `sites` + `me` (ROI cao nhất, là trang user hay vào)

1. Tách Overview thành **server component** bọc ngoài + client component cũ bên trong:
   ```tsx
   // page.tsx (SERVER — bỏ "use client")
   import { auth } from "@clerk/nextjs/server";
   import { QueryClient, dehydrate, HydrationBoundary } from "@tanstack/react-query";
   import DashboardClient from "./dashboard-client"; // phần "use client" cũ

   export default async function DashboardPage() {
     const { getToken } = auth();
     const token = await getToken();
     const qc = new QueryClient();
     if (token) {
       await Promise.all([
         qc.prefetchQuery({ queryKey: ["me"], queryFn: () => serverFetch("/api/v1/auth/me", token) }),
         qc.prefetchQuery({ queryKey: ["sites"], queryFn: () => serverFetch("/api/v1/sites", token) }),
       ]);
     }
     return (
       <HydrationBoundary state={dehydrate(qc)}>
         <DashboardClient />
       </HydrationBoundary>
     );
   }
   ```
   - `serverFetch` = helper nhỏ: `fetch(API_BASE+path, { headers: { Authorization: \`Bearer ${token}\` }, cache: "no-store" })`.
2. `DashboardClient` = nội dung Overview cũ, NHƯNG đọc `sites` qua `useQuery(["sites"])` thay cho `useEffect + listSites` (để khớp key đã prefetch). `me` đã là `useQuery(["me"])` rồi → tự ăn cache hydrate.
3. Vì data đã có sẵn lúc render → bỏ luôn `OverviewSkeleton` flash cho trường hợp có data.

**Verify lát 1:** đăng nhập → mở Overview → site cards hiện gần như tức thì, không còn skeleton-rồi-chờ. Đăng xuất vẫn redirect đúng. Kiểm Network: `me`/`sites` KHÔNG gọi lại ở client (đã hydrate).

### Lát 2 — mở rộng `visitor-stats` per site (nếu lát 1 ăn)

- Prefetch song song `["visitor-stats", siteId]` cho mỗi site ngay trên server → card hiện kèm số liệu luôn.

### Lát 3 — áp pattern cho trang con hay vào (visitors, campaigns)

- Cùng cách: server wrapper prefetch list theo `?site=`, client đọc từ cache.

---

## Rủi ro & chặn

- **Clerk server `auth()`**: chỉ đọc token, không sửa luồng auth. Nhưng phải test kỹ — memory ghi Clerk gây sập prod repo này ([[clerk-provider-crash-pattern]], [[dashboard-page-auth-gate]]). Nếu `auth()` server-side trả token rỗng/lỗi → fallback render skeleton như cũ (đừng để crash).
- **`ClerkTokenGate` (layout)**: vẫn còn, vẫn chặn `<main>` tới khi client có token. Lát 1 cần kiểm: gate có nuốt mất lợi ích prefetch không? Nếu có, cân nhắc cho gate render children ngay khi đã có data hydrate (CẨN THẬN — đường Clerk).
- **Token hết hạn giữa SSR và client**: react-query staleTime lo phần refetch; data hydrate vẫn hiện ngay (stale-while-revalidate).
- **Mỗi lát = 1 commit, verify preview trước khi push, revert độc lập.**

## Xong khi (lát 1)

- [ ] Overview tách server/client, prefetch `me`+`sites`.
- [ ] Đăng nhập: site cards hiện ngay, hết "skeleton rồi chờ".
- [ ] Network: không double-fetch `me`/`sites` ở client.
- [ ] Đăng xuất / không token: vẫn an toàn (skeleton fallback, không crash).
- [ ] tsc + lint sạch, verify preview, 1 commit.
