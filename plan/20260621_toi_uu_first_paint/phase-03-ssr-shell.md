# Phase 03 — Cho dashboard SSR cái khung thật (bọc useSearchParams + bỏ flag)

**Trạng thái:** ⬜ TODO (phụ thuộc kết luận Phase 1)
**Rủi ro:** Vừa (sửa 11 page + 1 config; KHÔNG đụng Clerk auth)
**Mục tiêu:** Server trả HTML có **khung + skeleton** (200), không còn trang 404 trắng → first paint hiện ngay.

---

## Điều kiện vào

Phase 1 đã kết luận nguyên nhân là CSR bailout từ `useSearchParams` (giả thuyết a). Nếu Phase 1 ra (b)/(c) → sửa lại phase này theo kết luận đó trước.

## Cách bọc (mẫu chuẩn, lặp cho từng page)

Mỗi page hiện gọi `useSearchParams()` ngay trong component top-level → tách phần đó ra component con, bọc `<Suspense>`:

```tsx
// TRƯỚC: page.tsx
export default function VisitorsPage() {
  const searchParams = useSearchParams();   // ← gây bailout
  // ...phần còn lại...
}

// SAU:
import { Suspense } from "react";
import { TableSkeleton } from "@/components/skeletons";

function VisitorsInner() {
  const searchParams = useSearchParams();
  // ...y nguyên phần còn lại...
}

export default function VisitorsPage() {
  return (
    <Suspense fallback={<TableSkeleton />}>
      <VisitorsInner />
    </Suspense>
  );
}
```

→ Server render `fallback` (skeleton) cho phần phụ thuộc query; khung quanh nó SSR bình thường. Client hydrate đọc query thật. **Logic không đổi.**

## Bước (chia lô, verify từng lô)

11 file dùng `useSearchParams`:
`settings, visitors, visitors/[visitorId], costs, exports, social-accounts/callback, campaigns, campaigns/[campaignId], segments, billing` (+ Overview nếu Phase 1 chỉ ra).

- **Lô A (3–4 page ít rủi ro):** segments, exports, costs → bọc → `npm run build` → curl 200 + có text khung → commit.
- **Lô B:** visitors, campaigns, billing → bọc → verify → commit.
- **Lô C:** các trang `[id]` chi tiết + settings + callback → bọc → verify → commit.
- **Cuối:** bỏ `missingSuspenseWithCSRBailout: false` khỏi `next.config.mjs` → `npm run build` phải PASS (không còn warning missing-suspense) → commit.

## Verify (bắt buộc mỗi lô, prod-build local)

```bash
cd apps/web && npm run build && npm start &
for p in /dashboard/segments /dashboard/visitors /dashboard/campaigns; do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3000$p)
  has=$(curl -s http://localhost:3000$p | grep -ioE "EasyTrack|animate-pulse|skeleton" | head -1)
  echo "$p -> $code  shell:$has"
done
# Mong: 200, shell có text. KHÔNG còn "404: This page".
```

Và test tay trên preview: mỗi trang vẫn đọc đúng `?site=...` sau khi hydrate (filter/select hoạt động như cũ).

## Xong khi

- [ ] 11 page bọc Suspense, mỗi page vẫn đọc query đúng sau hydrate.
- [ ] Bỏ flag, `npm run build` pass.
- [ ] Mọi `/dashboard/*` curl ra 200 + có khung (không còn 404 page).
- [ ] Preview: cold load (F5) thấy khung+skeleton ngay, không trắng.
- [ ] Mỗi lô 1 commit, revert độc lập được.

## Nếu hỏng

- Build fail sau khi bỏ flag = còn `useSearchParams` chưa bọc → tìm nốt, bọc, build lại.
- Page mất filter sau hydrate = component con chưa nhận query đúng → kiểm tra `useSearchParams` nằm trong `VisitorsInner`, không phải ngoài Suspense.
- Bất kỳ lỗi Clerk/redirect lạ = DỪNG, revert lô đó, báo lại (đường Clerk nhạy cảm).
