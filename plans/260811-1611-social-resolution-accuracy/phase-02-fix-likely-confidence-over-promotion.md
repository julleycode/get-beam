---
phase: 2
title: "Fix likely-confidence over-promotion"
status: complete
priority: P1
effort: "S"
dependencies: [1]
---

<!-- Updated: Validation Session 1 - D2 chốt phương án B; D6 gộp phát hành với Phase 1 -->

# Phase 2: Fix likely-confidence over-promotion

> **Đơn vị phát hành (D6):** phase này đi cùng Phase 1. Cả hai vào rồi mới coi là hoàn tất.

## Overview

`_classify()` nâng một phỏng đoán lên `"likely"` chỉ vì **email có đăng ký trên site đó**.
Email test đăng ký ở **90 site**, nên luật này biến mọi username đoán mò trên 90 site thành
"likely" — và `"likely"` là mức **được hiển thị cho người dùng**.

Suy luận sai nằm ở đây:

> Bạn có tài khoản Spotify. Có ai đó tên `nhanto` trên Spotify.
> → **kết luận sai:** `spotify.com/nhanto` có thể là bạn.

`nhanto` là tên rất phổ biến với người Việt. Hai mệnh đề trên không dẫn tới kết luận đó.

## Requirements

**Chức năng**
- Một phỏng đoán username không được lên `"likely"` chỉ vì email đăng ký trên site đó.
- Giữ được ý đồ gốc: khi tín hiệu site-overlap **thực sự** thu hẹp về một người.
- Dòng có username **không xuất hiện trong URL** không bao giờ được vượt mức `"guess"`.

**Phi chức năng**
- Không đổi bộ từ vựng `confirmed` / `likely` / `guess`. UI đang đọc đúng ba giá trị này.

## Bằng chứng

28 dòng "likely" trong lần chạy thật. Không dòng nào tên khớp URL. Ba dòng sai lộ liễu vẫn
lọt qua mọi lớp kiểm tra:

| Site | URL | Sai chỗ nào |
|---|---|---|
| HackTheBox | `https://www.hackthebox.com/` | Trang chủ, **không có username nào trong URL** |
| StackOverflow | `.../users/filter?search=nhanto` | URL **tìm kiếm**, không phải profile |
| Plurk | `https://gab.com/nhanto` | Tên site Plurk, URL lại là gab.com |

## Architecture

### Luật hiện tại (`social_resolver.py:91-110`)

```python
if engines & _EMAIL_KEYED:                              return "confirmed"
if pname and name_matches(pname, full_name):            return "confirmed"
if extra.get("cand_source") == "known":                 return "likely"
if _canon_site(acc.site_name).lower() in registered_sites:  return "likely"   # ← thủ phạm
return "guess"
```

### Quyết định D2 — ĐÃ CHỐT: phương án B (thu hẹp)

**Chốt ở validate 11-08-26.** Chỉ áp dụng luật site-overlap khi site có **duy nhất một** ứng
viên profile.

Lý do chọn B thay vì bỏ hẳn (phương án A):

- Giữ nguyên ý đồ gốc mà vẫn chặn được thổi phồng.
- `test_site_overlap_is_likely` **vẫn xanh, không phải sửa** — trong test đó GitHub chỉ có
  đúng một dòng profile. Không lật quyết định cũ.
- **Đo được là có tác dụng** (validate 11-08-26): 28/28 dòng hiển thị và 386/392 dòng ẩn đều
  đã gộp ≥2 username. Sau Phase 1 chúng tách ra → `per_site ≥ 2` → **B hạ hạng đúng 100% ca lỗi**.
  Số dòng profile chỉ có 1 username: **0**.

Giá phải trả: cần đếm số dòng theo site trước khi chấm điểm (rẻ, một `Counter`).

Hạn chế còn lại, có ghi nhận: "duy nhất 1 ứng viên" vẫn có thể sai khi cái duy nhất đó tình
cờ là người khác. Luật URL-phải-chứa-username bên dưới bù một phần; Phase 4 đo phần còn lại.

### Luật mới thêm — URL phải chứa username

Độc lập với D2, luôn áp dụng:

```
username không rỗng AND username không nằm trong URL  →  ép về "guess"
```

Diệt sạch HackTheBox và StackOverflow ở bảng trên. Chọn **hạ hạng** chứ không **loại bỏ**, để
site dùng ID số trong URL không bị mất oan — chúng rơi xuống `guesses` (bị ẩn) chứ không biến mất.

## Related Code Files

- Modify: `apps/api/services/social_resolver.py` — `_classify()`, `_verify_identity()`
- Modify: `tests/unit/test_social_resolver.py` — **chỉ thêm test mới**.
  `test_site_overlap_is_likely` **giữ nguyên, không sửa** (D2 = B đã chốt).

## Implementation Steps

1. **Đếm số dòng profile theo site** trước khi chấm, trong `_verify_identity`:

   ```python
   from collections import Counter

   def _verify_identity(accounts, full_name, registered_sites) -> None:
       per_site = Counter(_canon_site(a.site_name).lower() for a in accounts)
       for a in accounts:
           a.confidence = _classify(a, full_name, registered_sites, per_site)
   ```

2. **Thu hẹp luật site-overlap** trong `_classify`:

   ```python
   site = _canon_site(acc.site_name).lower()
   # Site-overlap chỉ đáng tin khi nó thu hẹp về MỘT ứng viên. Nhiều ứng viên trên
   # cùng site nghĩa là "email có đăng ký ở đây" không chỉ ra được ai trong số đó.
   if site in registered_sites and per_site.get(site, 0) == 1:
       return "likely"
   ```

3. **Thêm luật URL-phải-chứa-username**, đặt **trước** mọi nhánh trả `confirmed`/`likely`:

   ```python
   username = (extra.get("username") or "").strip().lower()
   if username and username not in (acc.url or "").lower():
       logger.info("social_url_username_mismatch", site=acc.site_name, username=username)
       return "guess"
   ```

4. **Thêm test** vào `tests/unit/test_social_resolver.py`:
   - `test_site_overlap_not_likely_when_many_candidates` — 3 username trên GitHub, email có
     đăng ký GitHub → cả 3 đều `guess`
   - `test_site_overlap_still_likely_when_single_candidate` — 1 username → `likely` (giữ ý đồ gốc)
   - `test_url_username_mismatch_forces_guess` — url là trang chủ, username không rỗng → `guess`
   - `test_url_mismatch_beats_name_match` — kể cả tên người khớp, URL lệch vẫn `guess`

5. **Kiểm chứng bằng dữ liệu thật**: chạy lại đường ống trên visitor test và xác nhận 3 dòng
   HackTheBox / StackOverflow / Plurk không còn nằm trong `profiles`.

## Success Criteria

- [ ] Nhiều ứng viên trên cùng site → không ai được `"likely"` nhờ site-overlap
- [ ] Duy nhất một ứng viên → vẫn `"likely"` (ý đồ gốc còn nguyên)
- [ ] `test_site_overlap_is_likely` xanh **mà không phải sửa** (D2 = B, nên đây là bắt buộc)
- [ ] Không dòng nào ở mức `confirmed`/`likely` mà username lệch URL
- [ ] HackTheBox, StackOverflow, Plurk biến khỏi danh sách hiển thị
- [ ] Test unit toàn xanh

## Test Gate

```bash
cd d:/cong_viec/22-22/get-beam
.venv/Scripts/python.exe -m pytest tests/unit/test_social_resolver.py -q
.venv/Scripts/python.exe -m pytest tests/unit/ -q -k "osint or social"
```

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| ~~Luật "duy nhất 1" không bao giờ kích hoạt → B thoái hoá thành A~~ **ĐÃ ĐO — BÁC BỎ** | ~~Cao~~ → **Thấp** | Đo trên `osint_result.json` (validate 11-08-26): **28/28 dòng hiển thị** và **386/392 dòng ẩn** chắc chắn đã gộp ≥2 username (username lệch URL ⇒ ít nhất 2 dòng bị nhập). Sau Phase 1 chúng tách ra → `per_site ≥ 2` → **B hạ hạng đúng 28/28 dòng có vấn đề**. Số dòng profile chỉ có 1 username: **0**. B kích hoạt trên 100% ca lỗi. |
| Ngược lại: B có thể hạ hạng **quá tay**, không còn gì hiển thị | Trung bình | Đo ở Phase 4. Kết quả rỗng vẫn tốt hơn kết quả sai — nhưng cần kiểm UI có trạng thái rỗng tử tế. |
| Site dùng ID số trong URL bị hạ hạng oan | Trung bình | Hạ hạng (không loại bỏ) + ghi log `social_url_username_mismatch` để đếm tần suất |
| Kết quả rỗng: người dùng bấm nút và không thấy gì | Trung bình | Đúng chức năng — thà không có còn hơn sai. Nhưng cần kiểm UI có trạng thái rỗng tử tế. Ghi nhận, không sửa ở phase này. |
| `_EMAIL_KEYED` → `confirmed` có thể quá rộng sau khi Phase 1 đổi cách hợp engine | Thấp | Lần chạy thật cho `confirmed_count = 0`, nhánh này chưa từng bắn. Theo dõi ở Phase 4. |
