# Phase 02 — Thêm loading.tsx skeleton mỗi route

**Trạng thái:** ⬜ TODO
**Rủi ro:** Thấp (thêm file mới, không sửa logic)
**Mục tiêu:** Khi chuyển trang trong app, hiện skeleton **tức thì** thay vì đứng yên chờ data.

---

## Ý tưởng

Next App Router: file `loading.tsx` trong 1 route segment = Suspense fallback tự động cho segment đó. Khi user bấm sang trang, Next hiện `loading.tsx` ngay lập tức trong khi page mới tải/fetch.

Component skeleton đã có sẵn (`@/components/skeletons`: `TableSkeleton`, `ListCardSkeleton`, `SiteCardSkeleton`...). Chỉ cần wrap lại thành `loading.tsx`.

## Bước

1. Thêm `loading.tsx` cho các route nặng-data trước (ROI cao nhất):
   - `src/app/dashboard/loading.tsx` (Overview — dùng skeleton 3 card)
   - `src/app/dashboard/visitors/loading.tsx` (`TableSkeleton`)
   - `src/app/dashboard/campaigns/loading.tsx` (`TableSkeleton`)
   - `src/app/dashboard/segments/loading.tsx`
   - `src/app/dashboard/drafts/loading.tsx`

   Mẫu (tái dùng skeleton có sẵn, đừng vẽ mới):
   ```tsx
   import { TableSkeleton } from "@/components/skeletons";
   export default function Loading() {
     return <TableSkeleton />;
   }
   ```

2. Verify trên preview: bấm chuyển giữa các trang → thấy skeleton chớp ngay, không còn khựng.

3. 1 commit: `perf(web): route-level loading skeletons for dashboard`.

## Lưu ý

- `loading.tsx` chủ yếu giúp **điều hướng trong app** (soft navigation). Với **cold load** (gõ URL/F5) nó chỉ giúp nếu route đã SSR/stream được — cái đó là Phase 3. Nên Phase 2 và 3 bổ trợ nhau.
- Không cần `loading.tsx` cho mọi route, chỉ route data-nặng. Trang tĩnh (settings) bỏ qua được.

## Xong khi

- [ ] 5 route data-nặng có `loading.tsx` dùng skeleton sẵn có.
- [ ] Preview: chuyển trang hiện skeleton tức thì.
- [ ] tsc + lint sạch, 1 commit.
