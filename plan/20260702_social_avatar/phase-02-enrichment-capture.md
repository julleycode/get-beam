# Phase 02 — Enrichment: bắt URL ảnh (Twitter chính, OSINT phụ)

**Mục tiêu:** Khi enrich xong, `profile.avatar_url` được ghi:
1. Ưu tiên ảnh Twitter/X (nét — bản `_400x400`)
2. Nếu không có Twitter → thử ảnh từ `social_context` (OSINT)

Tất cả nằm trong `apps/api/services/enricher.py`.

---

## Bước 2.1 — Lấy ảnh trong `_enrich_twitter`

**File:** `apps/api/services/enricher.py`
**Hàm:** `_enrich_twitter` (dòng 476-564)

### (a) Nhánh chính — X API v2 (dòng 508-513)
X API v2 trả `profile_image_url` khi ta xin `user.fields`. Hiện code chỉ xin `description,public_metrics`. Cần thêm `profile_image_url`:

Sửa params (dòng 506):
```python
params={"user.fields": "description,public_metrics,profile_image_url"},
```

Sửa block map 200 (dòng 509-513):
```python
u = resp.json().get("data", {})
data = {
    "twitter_bio": u.get("description"),
    "twitter_follower_count": u.get("public_metrics", {}).get("followers_count"),
    "avatar_url": _upgrade_twitter_avatar(u.get("profile_image_url")),
}
```

### (b) Nhánh fallback — TwitterAPI.io (dòng 552-555)
TwitterAPI.io user/info trả ảnh ở key `profilePicture` (camelCase). Map thêm:
```python
data = {
    "twitter_bio": u.get("description"),
    "twitter_follower_count": u.get("followers"),
    "avatar_url": _upgrade_twitter_avatar(u.get("profilePicture") or u.get("profile_image_url")),
}
```
> Ghi chú execute: TwitterAPI.io trả field ảnh tên `profilePicture`. Nếu payload thật khác, log ra 1 lần để xác nhận; cứ `.get(...)` an toàn nên không vỡ nếu thiếu.

### (c) Mock mode (dòng 492-495)
Thêm avatar giả để test đường mock:
```python
data = {
    "twitter_bio": f"Mock bio for @{handle.lstrip('@')}",
    "twitter_follower_count": 1234,
    "avatar_url": "https://pbs.twimg.com/profile_images/000/mock_400x400.jpg",
}
```

---

## Bước 2.2 — Helper nâng ảnh Twitter lên nét

**File:** `apps/api/services/enricher.py` (đặt cạnh `_apply_twitter`, ~dòng 92, cấp module)

URL ảnh Twitter mặc định có đuôi `_normal.jpg` = 48px (mờ). Đổi `_normal.` → `_400x400.` để nét:
```python
def _upgrade_twitter_avatar(url: str | None) -> str | None:
    """Twitter/X trả ảnh 48px (đuôi `_normal.`); nâng lên 400px cho nét."""
    if not url:
        return None
    return url.replace("_normal.", "_400x400.")
```
> An toàn: nếu URL không có `_normal.` (ví dụ ảnh OSINT), `.replace` không đổi gì → trả nguyên URL.

---

## Bước 2.3 — Ghi `avatar_url` trong `_apply_twitter`

**File:** `apps/api/services/enricher.py`
**Hàm:** `_apply_twitter` (dòng 92-100)

Thêm (giữ đúng quy tắc "không ghi đè bằng null"):
```python
    if (v := twitter_data.get("avatar_url")) is not None:
        profile.avatar_url = v
```

---

## Bước 2.4 — Helper lấy ảnh từ OSINT (nguồn phụ)

**File:** `apps/api/services/enricher.py` (cấp module, cạnh helper trên)

`social_context` chứa `social_resolution.profiles` (list OsintAccount) và mỗi account có `extra` giữ 1 trong các key ảnh: `avatar` (osint_scanner) / `profile_pic` / `picture` (paid_osint).

```python
def _avatar_from_social_context(social_context: dict | None) -> str | None:
    """Lấy ảnh đại diện đầu tiên tìm được từ các profile OSINT trong
    social_context. Trả None nếu không có. Chỉ dùng làm nguồn PHỤ."""
    if not isinstance(social_context, dict):
        return None
    res = social_context.get("social_resolution")
    if not isinstance(res, dict):
        return None
    for account in (res.get("profiles") or []):
        extra = account.get("extra") if isinstance(account, dict) else None
        if not isinstance(extra, dict):
            continue
        for key in ("avatar", "profile_pic", "picture"):
            val = extra.get(key)
            if isinstance(val, str) and val.startswith("http"):
                return val
    return None
```
> Ghi chú: chỉ nhận URL bắt đầu `http` để tránh nhận nhầm data rác. Không đổi kích thước (chỉ Twitter mới có trò `_normal`).

---

## Bước 2.5 — Gán nguồn phụ trong `enrich_tier1`

**File:** `apps/api/services/enricher.py`
**Hàm:** `enrich_tier1` (dòng 136-239)

Twitter stage (dòng 210-220) đã set `avatar_url` khi có Twitter (qua `_apply_twitter`). Sau **Step 4** (`_fetch_and_store_content`, dòng 224) và **trước** khi tính completeness (dòng 226), thêm fallback OSINT **chỉ khi Twitter chưa cho ảnh**:

```python
        # Nguồn phụ: nếu Twitter không có ảnh, thử ảnh từ OSINT (social_context).
        if not profile.avatar_url:
            osint_avatar = _avatar_from_social_context(profile.social_context)
            if osint_avatar:
                profile.avatar_url = osint_avatar
```
> Đặt sau Step 4 vì `social_context` có thể được ghi/cập nhật ở đó. Nếu `social_context` được set ở nơi khác (social resolver chạy tách), fallback vẫn đọc được giá trị hiện có trên profile.

---

## Nghiệm thu phase-02
- Unit test (phase-05): `_enrich_twitter` (mock 200) trả `avatar_url`; `_upgrade_twitter_avatar("...x_normal.jpg")` → `..._400x400.jpg`.
- `_apply_twitter({"avatar_url": "..."}, profile)` set đúng, và `_apply_twitter({}, profile)` KHÔNG xoá avatar cũ.
- `_avatar_from_social_context` lấy đúng ảnh đầu tiên từ `profiles[].extra`.
- Không đổi hành vi bio/follower cũ (test_twitter_fallback.py vẫn xanh — các assert cũ không đụng `avatar_url`).
