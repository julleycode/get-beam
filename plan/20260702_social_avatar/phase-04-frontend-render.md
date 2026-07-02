# Phase 04 — Frontend: hiện ảnh thật + fallback về chữ viết tắt

**Mục tiêu:** Component `Avatar` hiện `<img src={avatar_url}>` khi có; nếu ảnh lỗi/không có → chữ viết tắt như cũ.

---

## Bước 4.1 — Thêm field vào type

**File:** `apps/web/src/lib/api-types.ts`
**Interface:** `VisitorDetail` (dòng 202-225)

Thêm (cạnh nhóm social, ví dụ sau `twitter_bio` dòng 216):
```ts
  avatar_url?: string | null;
```

---

## Bước 4.2 — Cho `Avatar` nhận `src` và tự fallback khi lỗi

**File:** `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx`
**Component:** `Avatar` (dòng 74-101)

Component hiện là function thuần (không state). Để fallback khi ảnh 403/hỏng, cần 1 state nhỏ `imgFailed` + `onError`. Ghi chú: file đã `"use client"` và đã import `useState` (dòng 3) → dùng được ngay.

**Sửa signature + thân component:**
```tsx
function Avatar({
  name,
  email,
  variant,
  src,
}: {
  name?: string | null;
  email?: string | null;
  variant: "person" | "company" | "anonymous";
  src?: string | null;
}) {
  const [imgFailed, setImgFailed] = useState(false);
  const label = initials(name, email);
  const tone =
    variant === "company"
      ? "bg-warning-muted text-warning"
      : variant === "anonymous"
        ? "bg-muted text-muted-foreground"
        : "bg-primary/10 text-primary";
  const Icon = variant === "company" ? Building2 : UserRound;

  // Chỉ hiện ảnh khi: có src, chưa lỗi, và KHÔNG phải anonymous.
  const showImg = !!src && !imgFailed && variant !== "anonymous";
  if (showImg) {
    return (
      <img
        src={src!}
        alt={name || "avatar"}
        referrerPolicy="no-referrer"
        loading="lazy"
        onError={() => setImgFailed(true)}
        className="h-16 w-16 shrink-0 rounded-2xl object-cover"
      />
    );
  }

  return (
    <div
      className={cn(
        "flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl font-serif text-xl font-semibold",
        tone,
      )}
    >
      {label && variant !== "anonymous" ? label : <Icon className="h-7 w-7" />}
    </div>
  );
}
```

**Vì sao thế này:**
- `object-cover` + cùng `h-16 w-16 rounded-2xl` → ảnh vừa khít ô cũ, bo góc giống hệt.
- `onError` → khi ảnh 403/hỏng, `imgFailed=true` → render lại thành chữ viết tắt. KHÔNG hiện icon ảnh vỡ.
- `referrerPolicy="no-referrer"` → giảm khả năng `pbs.twimg.com` chặn hotlink theo referer.
- Anonymous vẫn giữ icon như cũ (không dí ảnh vào visitor ẩn danh).

---

## Bước 4.3 — Truyền `src` chỗ render header

**File:** cùng file, dòng 448-452

```tsx
          <Avatar
            name={visitor.full_name}
            email={visitor.email}
            variant={!identified ? "anonymous" : isCompanyLevel ? "company" : "person"}
            src={visitor.avatar_url}
          />
```

---

## Vì sao `<img>` thường (không `next/image`)
- `apps/web/next.config.mjs` **không có** block `images.remotePatterns/domains` → `next/image` sẽ **chặn** host ngoài như `pbs.twimg.com` (build/runtime error).
- Repo đã có tiền lệ dùng `<img>` thường để né cấu hình host (xem `apps/web/src/app/blog/[slug]/page.tsx:124`). Theo đúng lối đó cho nhất quán và đơn giản.

---

## Nghiệm thu phase-04
- `cd apps/web && npx tsc --noEmit` không lỗi type.
- `npm run lint` sạch (Vercel build lint sẽ fail deploy nếu bẩn — memory vercel-cli-via-npx).
- Visitor có avatar → thấy ảnh; không có → chữ viết tắt; ảnh URL rác → onError → chữ viết tắt.
