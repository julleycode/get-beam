# Phase 16 — Dọn nốt phần hoãn (cleanup)

> Gom các phần hoãn từ P10/P11/P13. CHỈ làm phần an toàn behavior-exact/defensive.
> Nhánh `refactor/p16-cleanup`. Bỏ các phần đổi-hành-vi (P10 concurrency, api.ts 401 dedup, worker.js).

## Phạm vi (user duyệt: 3 việc)

### 1. companies page_size cap (defensive)
`routers/companies.py`: `page_size: int = 50` không có trần → thêm `Query(50, ge=1, le=100)` + `page Query(1, ge=1)`. Chặn query không giới hạn. Near-behavior-exact (chỉ từ chối input lạm dụng).

### 2. Dedup ~19 inline ownership select → `verify_site_access`
P13 đã làm core (gộp 5 helper). Còn ~19 chỗ tự `select(Site).where(site_id==, user_id==user.id)` + 404 "Site not found" — y hệt `dependencies.verify_site_access`. Thay:
- exports.py (1), segments.py (2), campaigns.py (5), sites.py (11).
- companies.py: ĐÃ dùng verify_site_access từ trước.
- `verify_site_access` trả về site → chỗ dùng `site` giữ `site = await verify_site_access(...)`; chỗ không dùng → `await verify_site_access(...)`.
- KHÔNG đụng `sites.py:shopify_callback` (no user_id, 400 "Invalid state" — KHÁC, không phải ownership).
- Xóa import `Site` chết ở exports/segments/campaigns sau khi gộp.

### 3. Reconcile requirements.txt (1 nguồn sự thật)
2 file: root `requirements.txt` (Dockerfile + CI dùng) + `apps/api/requirements.txt` (cũ Jun14, KHÔNG ai tham chiếu). File cũ chỉ chứa cruft: sendgrid/geoip2/maxminddb/pyjwt — **app KHÔNG import** (sendgrid qua httpx REST, geoip qua httpx, jwt qua python-jose). → **Xóa `apps/api/requirements.txt`**. Root không đổi → prod build không rủi ro.

## BỎ (đổi hành vi / rủi ro / điều tra)
- P10 concurrency (billing atomic, TOCTOU, events coalescing, NULL-event_id) — chỉ ý nghĩa khi tải cao; prod tí hon.
- api.ts core-fetch/401 dedup — đổi đường auth-retry, rủi ro > lợi.
- Xóa Cloudflare worker.js — có thể là first-party-pixel; chỉ điều tra, không xóa.

## Verify
- [ ] `pytest tests/unit` (353) + integration (router ownership) pass
- [ ] e2e (sites/dashboard/settings dùng ownership endpoints)
- [ ] PR Railway env smoke → merge main
