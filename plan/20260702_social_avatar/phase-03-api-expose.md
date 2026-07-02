# Phase 03 — API: đưa `avatar_url` ra ngoài (endpoint chi tiết)

**Mục tiêu:** `GET /api/v1/visitors/{site_id}/{visitor_id}` trả thêm `avatar_url`.

---

## Bước 3.1 — Thêm field vào schema

**File:** `apps/api/schemas/visitors.py`
**Class:** `VisitorDetailOut` (dòng 45-68)

Thêm (đặt cạnh nhóm social, ví dụ sau `twitter_bio` dòng 58):
```python
    avatar_url: str | None = None
```
> Style: khớp các field khác trong class (đều `str | None = None`).

**KHÔNG** thêm vào `VisitorOut` (list) ở MVP — xem plan.md mục 8. (List query hiện không lấy avatar; thêm sẽ phải sửa query list → để dành.)

---

## Bước 3.2 — Map field trong endpoint

**File:** `apps/api/routers/visitors.py`
**Hàm:** `get_visitor_detail` (dòng 458-546)
**Vị trí:** block `if enriched:` map các field enrichment (dòng 522-533)

Thêm 1 dòng vào `data.update({...})`:
```python
    if enriched:
        data.update({
            "job_title": enriched.job_title,
            "company_name": enriched.company_name,
            "industry": enriched.industry,
            "linkedin_url": enriched.linkedin_url,
            "twitter_handle": enriched.twitter_handle,
            "linkedin_headline": enriched.linkedin_headline,
            "twitter_bio": enriched.twitter_bio,
            "enrichment_completeness": enriched.enrichment_completeness,
            "social_context": enriched.social_context,
            "avatar_url": enriched.avatar_url,   # ← thêm dòng này
        })
```
> Khi visitor chưa enrich (`enriched` là None) → `avatar_url` không được set → schema mặc định `None`. Không lỗi.

---

## Nghiệm thu phase-03
- Chạy backend local (docker-compose + mock APIs), enrich 1 visitor có Twitter → gọi endpoint → JSON có `"avatar_url": "https://.../..._400x400.jpg"`.
- Visitor chưa enrich → `"avatar_url": null`.
- Integration test (nếu thêm) hoặc curl thủ công đều được. Xem gotcha test ở `phase-05` (ASGITransport không chạy lifespan; fixture phải tạo bảng).
