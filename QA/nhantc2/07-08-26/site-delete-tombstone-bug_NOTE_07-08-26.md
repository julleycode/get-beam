# QA Note — Delete site fail (site_tombstones thiếu cột)

- **QA by:** nhantc2
- **Date:** 07-08-26
- **Branch local:** `dev_nhantc2` (đã merge `origin/main`)
- **Related commit:** `1a16662` — `feat(pixel): site-id lifecycle with delete tombstones`
- **Severity:** P0 (UI Delete site luôn fail)

---

## Triệu chứng

Trên dashboard Overview → Delete site (Demo SaaS App):

- UI hiện: **Failed to delete site**
- API: `DELETE /api/v1/sites/site_demo123456`
- Response: `{"detail":"Failed to delete site"}` (HTTP 500)

Các request `webpack.hot-update.*` là HMR của Next.js — **không liên quan**.

---

## Nguyên nhân (ngắn)

Commit `1a16662` thêm bảng `site_tombstones` + khi xóa site thì ghi 1 dòng tombstone.

- **Model** `SiteTombstone` kế thừa `Base` → SQLAlchemy expect có `created_at`, `updated_at`
- **Migration** chỉ tạo: `id`, `site_id`, `normalized_url`, `user_id`, `deleted_at`
- → Insert tombstone crash vì cột không tồn tại → rollback → fail

Lỗi DB thật khi reproduce:

```text
column site_tombstones.created_at does not exist
```

### Ví dụ dễ hiểu

Form (code) yêu cầu ghi thêm Email, nhưng bảng Excel (DB) chưa có cột Email → lưu thất bại.

---

## Cách chữa local (SQL)

Chỉ cần bổ sung 2 cột cho khớp `Base`. Chạy trên DB local (`retarget_agent`):

```sql
ALTER TABLE site_tombstones
  ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
```

Sau đó thử lại **Delete site** trên UI — kỳ vọng **204 / xóa thành công**, và có 1 row trong `site_tombstones`.

### Verify nhanh

```sql
\d site_tombstones
-- phải thấy created_at, updated_at

SELECT site_id, normalized_url, deleted_at, created_at, updated_at
FROM site_tombstones
ORDER BY deleted_at DESC
LIMIT 5;
```

---

## Ghi chú thêm cho repo (chưa làm trong note này)

SQL trên là **hotfix local**. Để mọi môi trường / máy khác không bị lại:

- Nên thêm 1 Alembic migration tương đương (không chỉ chạy tay trên máy QA)
- Hoặc (ít khuyến nghị hơn) sửa model bỏ inherit `created_at`/`updated_at` — sẽ lệch với pattern `Base` của project

---

## Checklist QA liên quan batch julleycode (context)

| # | Case | Kết quả |
|---|---|---|
| 1 | Visitors list không 500 | (chưa ghi trong note này) |
| 2 | Delete site | **FAIL** — bug tombstone cột thiếu (note này) |
| 3 | Imported Contacts / seed data | DB gần trống nếu chưa `-FullSeed` |

---

## TL;DR

Delete site fail vì `site_tombstones` thiếu `created_at` / `updated_at`. Chạy `ALTER TABLE ... ADD COLUMN` ở trên là đủ để unblock QA local.
