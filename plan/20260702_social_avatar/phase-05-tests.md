# Phase 05 — Test (chứng minh chạy đúng, không vỡ cái cũ)

**Mục tiêu:** Test tối thiểu nhưng đủ: schema có field, enricher ghi avatar, helper OSINT hoạt động, và không phá test cũ.

Chạy backend test theo memory (brew postgres@16 + local redis, docker-compose stack — KHÔNG dùng prod).

---

## 5.1 — Unit test enrichment avatar (backend)

**Cách 1 (gọn):** thêm vào `tests/unit/test_twitter_fallback.py` (đã có sẵn `_SeqClient`, fixtures `enricher/seq/cfg`).
**Cách 2:** file mới `tests/unit/test_avatar_enrich.py` import lại pattern đó. Chọn Cách 1 cho đỡ trùng.

**Ca cần test:**

1. **Twitter official 200 → có avatar nét:**
```python
OFFICIAL_OK_AVATAR = {"data": {
    "description": "bio",
    "public_metrics": {"followers_count": 5},
    "profile_image_url": "https://pbs.twimg.com/profile_images/1/abc_normal.jpg",
}}

async def test_official_avatar_upgraded_to_400(self, enricher, seq, cfg):
    _SeqClient._queue = [_resp(200, OFFICIAL_OK_AVATAR)]
    out = await enricher._enrich_twitter("jack", api_key="bearer")
    assert out["avatar_url"] == "https://pbs.twimg.com/profile_images/1/abc_400x400.jpg"
```

2. **TwitterAPI.io fallback → lấy `profilePicture`:**
```python
FALLBACK_AVATAR = {"status": "success", "data": {
    "description": "bio", "followers": 9,
    "profilePicture": "https://pbs.twimg.com/profile_images/2/xyz_normal.jpg",
}}

async def test_fallback_avatar(self, enricher, seq, cfg):
    _SeqClient._queue = [_resp(200, FALLBACK_AVATAR)]
    out = await enricher._enrich_twitter("jack", api_key=None)
    assert out["avatar_url"].endswith("_400x400.jpg")
```

3. **Helper `_upgrade_twitter_avatar`:**
```python
from apps.api.services.enricher import _upgrade_twitter_avatar

def test_upgrade_avatar():
    assert _upgrade_twitter_avatar("https://x/abc_normal.jpg") == "https://x/abc_400x400.jpg"
    assert _upgrade_twitter_avatar(None) is None
    assert _upgrade_twitter_avatar("https://x/nochange.jpg") == "https://x/nochange.jpg"
```

4. **`_apply_twitter` set + không ghi đè bằng null:**
```python
def test_apply_twitter_avatar():
    from apps.api.services.enricher import _apply_twitter
    class P: avatar_url = None; twitter_bio = None; twitter_follower_count = None; twitter_recent_topics = []
    p = P()
    _apply_twitter(p, {"avatar_url": "https://x/a_400x400.jpg"})
    assert p.avatar_url == "https://x/a_400x400.jpg"
    _apply_twitter(p, {})  # không có avatar_url → giữ nguyên
    assert p.avatar_url == "https://x/a_400x400.jpg"
```

5. **Helper OSINT `_avatar_from_social_context`:**
```python
from apps.api.services.enricher import _avatar_from_social_context

def test_avatar_from_osint():
    sc = {"social_resolution": {"profiles": [
        {"extra": {"username": "x"}},                       # không có ảnh
        {"extra": {"avatar": "https://cdn/p.png"}},         # có ảnh
    ]}}
    assert _avatar_from_social_context(sc) == "https://cdn/p.png"
    assert _avatar_from_social_context(None) is None
    assert _avatar_from_social_context({}) is None
```

---

## 5.2 — Schema có field (backend)

Kiểm nhanh `VisitorDetailOut` chấp nhận `avatar_url`:
```python
def test_detail_schema_has_avatar():
    from apps.api.schemas.visitors import VisitorDetailOut
    assert "avatar_url" in VisitorDetailOut.model_fields
```

---

## 5.3 — Không phá test cũ

- Chạy `pytest tests/unit -q` — đặc biệt `test_twitter_fallback.py` phải xanh (các assert cũ chỉ check bio/follower, không đụng avatar → không vỡ).
- Nếu có integration test enrich (ví dụ trong `tests/integration/`) chạy được thì chạy luôn. Nhớ gotcha: `ASGITransport` KHÔNG chạy lifespan → fixture phải tự tạo bảng (CLAUDE.md).

---

## 5.4 — Frontend (tuỳ chọn nhẹ)

- Bắt buộc: `cd apps/web && npx tsc --noEmit` + `npm run lint` sạch.
- Tuỳ chọn E2E `apps/web/e2e/visitors.spec.ts`: mở trang chi tiết, assert avatar hiện. **Theo đúng luật Playwright trong CLAUDE.md:**
  - Dùng `await expect(locator).toBeVisible({ timeout: 15_000 })`, KHÔNG `waitForTimeout + isVisible`.
  - Nếu dùng `.or()` phải `.first()`.
  - Selector cụ thể (ví dụ `img[alt]` trong hero, hoặc kiểm tra chữ viết tắt khi không có ảnh).
  - ĐỌC source thật trước khi viết selector.
  - E2E này CHỈ chạy được nếu môi trường test có data visitor có avatar (mock). Nếu không có, giữ ở mức tsc+lint.

---

## Nghiệm thu phase-05
- `pytest tests/unit -q` xanh (mới + cũ).
- `npx tsc --noEmit` + `npm run lint` (web) sạch.
- Đã có bằng chứng: avatar_url được ghi (twitter + osint), nâng nét, fallback không ghi đè null, schema có field.
