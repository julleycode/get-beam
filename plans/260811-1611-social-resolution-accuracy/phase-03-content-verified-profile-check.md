---
phase: 3
title: "Content-verified profile check"
status: complete
priority: P2
effort: "M"
dependencies: [1, 2]
---

<!-- Updated: Validation Session 1 - D5 thêm bước đo offline; D3 chốt ngân sách 300 -->

# Phase 3: Content-verified profile check

## Overview

Nhánh đoán link (`resolve_via_rules`) dựng URL từ 16 mẫu thủ công rồi kết luận "tìm thấy"
khi web trả `HTTP 200` và slug còn trong URL cuối. Nhiều site trả 200 cho cả người không tồn tại
(đá về trang chủ hoặc trang login), nên phép kiểm này báo nhầm.

Thay bằng cách kiểm của WhatsMyName: **đọc nội dung trang**, kiểm chuỗi phải-có (`e_string`) và
chuỗi phải-không-có (`m_string`).

## Bằng chứng

**Đo báo nhầm** — username ma `zzqx7v3mklophantom9418`, logic hiện tại, 16 site:

| Kết quả | Số site |
|---|---|
| Báo nhầm (Instagram, Pinterest, Reddit, Telegram, TikTok, Twitch) | **6** |
| Loại đúng | 8 |
| Lỗi mạng | 2 |

**Đối chứng bằng logic WhatsMyName trên đúng 6 site đó:**

| Kiểm tra | Kết quả |
|---|---|
| Username ma → loại hết? | **6/6 loại đúng** |
| Người thật (torvalds, durov, instagram, tiktok, twitch, pinterest) → tìm thấy? | **5/6** |

Ca trượt duy nhất là Reddit — HTTP 403 chặn bot từ IP đo, **không phải lỗi logic**. Chính Reddit
này ở lần đo trước đã **báo nhầm** cho logic hiện tại.

**Dữ liệu WhatsMyName** (`wmn-data.json`, tải 11-08-26):

| Chỉ số | Giá trị |
|---|---|
| Tổng site | 708 |
| Có `e_string` | 706 |
| Có cả `e_string` + `m_string` | 673 |
| Trùng với Maigret top-500 | chỉ **215** |
| **Site Maigret top-500 KHÔNG có** | **465** |
| Thuộc nhóm B2B (social/coding/tech/business/finance) | 356 |

## Ràng buộc ngân sách (Quyết định D3)

Không đụng Maigret (yêu cầu của chủ dự án) → hai chặng chạy song song chia nhau **45 giây**.

Đo thực tế 11-08-26: độ trễ min 0.19s / trung vị 0.7s / max 1.53s, `osint_scan_concurrency = 10`.

Sức chứa của nhánh đoán link trong 45s, tính theo tỉ lệ request bị treo (treo ăn trọn 8s và
khoá 1/10 năng lực):

| Tỉ lệ treo | Chạy được |
|---|---|
| 2% | ~690 lần gọi |
| **5% (giả định làm việc)** | **~420 lần gọi** |
| 10% | ~280 lần gọi |

Máy chủ Beam chạy trên Railway (IP trung tâm dữ liệu) → gần các site Mỹ hơn nhưng **bị chặn
nhiều hơn**. Bị chặn thì rẻ (403 trả nhanh); **treo** mới đắt.

**Chốt ngân sách: ~300 lần gọi** (D3, validate 11-08-26), chừa biên an toàn.

Chủ dự án đã chấp nhận con số suy luận này thay vì chờ đo trên Railway, với điều kiện:
`osint_rules_max_requests` là **trần cứng trong config** nên không thể vỡ hạn, và **Phase 4 đo
số thật rồi chỉnh lại**.

Nhân đơn giản cho thấy vì sao không thể bê nguyên:

```
708 site × 10 ứng viên = 7.080 lần gọi ≈ 8 phút   ← vỡ ngân sách hơn 10 lần
```

**Chia hai tầng:**

| Tầng | Cách làm | Số lần gọi |
|---|---|---|
| Quét rộng | 1 ứng viên tốt nhất × ~150 site B2B | ~150 |
| Quét sâu | tối đa 10 ứng viên × 16 site giá trị cao | ~160 |
| | **Tổng** | **~310** |

## Bẫy đã biết — bộ lọc NSFW không khớp

`osint_scanner.py:165` so khớp **chính xác**:

```python
if cat_name.lower() in skip_categories:   # skip_categories = {"adult","nsfw","porn"}
```

Danh mục của WhatsMyName ghi là **`xx NSFW xx`** → **không khớp** → **39 site người lớn lọt qua**.

Bắt buộc sửa trong phase này. Chuyển sang so khớp "có chứa":

```python
if any(tok in cat_name.lower() for tok in skip_categories):
```

## License

`wmn-data.json` — **CC BY-SA 4.0**, © Micah Hoffman (WebBreacher/WhatsMyName).
Chủ dự án đã chấp nhận (11-08-26). Bắt buộc:

- Vendor **nguyên trạng**, không sửa nội dung file.
- Ghi công + link license trong header module và trong file (hoặc `NOTICE` cạnh file).
- Nếu sau này **sửa** file, bản sửa phải chia sẻ lại cùng license.

Lọc theo danh mục/số lượng thực hiện **lúc chạy**, không phải bằng cách sửa file — giữ nguyên
trạng để tránh nghĩa vụ ShareAlike.

## Related Code Files

- Create: `apps/api/data/wmn-data.json` — vendor nguyên trạng
- Create: `apps/api/data/wmn-data.NOTICE` — ghi công CC BY-SA
- Modify: `apps/api/services/social_rules.py` — thay `resolve_via_rules` + `SITE_URL_TEMPLATES`
- Modify: `apps/api/services/osint_scanner.py` — so khớp danh mục NSFW
- Modify: `apps/api/config.py` — thêm cận trên ngân sách
- Modify: `tests/unit/test_social_pipeline_helpers.py` — test kiểm nội dung
- Modify: `tests/unit/test_osint_scanner.py` — test lọc danh mục

## Implementation Steps

1. **Vendor dữ liệu** — tải `wmn-data.json` từ `WebBreacher/WhatsMyName@main`, đặt vào
   `apps/api/data/`, kèm `wmn-data.NOTICE` ghi tác giả + license + ngày tải + commit hash.

2. **Thêm config** vào `apps/api/config.py`, cạnh khối `osint_*` sẵn có:

   ```python
   osint_rules_broad_sites: int = 150      # số site cho tầng quét rộng
   osint_rules_broad_candidates: int = 1   # số ứng viên cho tầng quét rộng
   osint_rules_deep_sites: int = 16        # số site cho tầng quét sâu
   osint_rules_categories: str = "social,coding,tech,business,finance"
   osint_rules_max_requests: int = 300     # trần cứng, chặn vỡ ngân sách
   ```

3. **Đo offline để chốt danh sách site (D5 — bắt buộc, làm TRƯỚC bước 4)**

   `wmn-data.json` **không có trường xếp hạng**. Lấy "150 site đầu file" là tuỳ tiện —
   validate 11-08-26 xếp đây là rủi ro CAO, và quyết định là **đo trước, chốt sau**.

   - Viết script dùng một lần trong thư mục tạm (KHÔNG commit vào `apps/`).
   - Chạy toàn bộ **356 site nhóm B2B** với 2-3 username thật đã biết
     (`nhantochi95`, `torvalds`, `durov`), **không giới hạn thời gian** — chạy ngoài luồng
     request nên không tốn ngân sách 45s.
   - Ghi cho mỗi site: có trả kết quả không, `e_string` còn khớp không, độ trễ, tỉ lệ 403.
   - **Loại** site: chặn bot cứng (403 mọi lần), timeout mọi lần, `e_string` đã mục.
   - **Chốt** `osint_rules_broad_sites` bằng danh sách rút ra từ số đo này, không bằng thứ tự file.
   - Lưu kết quả vào `plans/260811-1611-social-resolution-accuracy/reports/wmn-site-survey.md`.

   Nếu số site dùng được ít hơn 150 → dùng đúng số đó, đừng độn thêm cho đủ.

4. **Nạp + lọc dữ liệu** trong `social_rules.py`:
   - Nạp một lần, cache ở module (giống `maigret_engine._load_db`).
   - Bỏ site không có `e_string`.
   - Bỏ site có danh mục khớp `osint_scan_skip_categories` (so khớp "có chứa").
   - Lọc theo `osint_rules_categories`, giữ đúng danh sách site đã chốt ở bước 3.
   - `wmn-data.json` **không có trường xếp hạng** — thứ tự trong file là thứ tự duy nhất có.
     Ghi rõ trong comment rằng danh sách đến từ **phép đo ở bước 3**, không phải thứ tự file;
     không bịa ra "top-N theo độ phổ biến".

5. **Viết lại `resolve_via_rules`** theo hai tầng:

   ```python
   async def resolve_via_rules(candidates, *, semaphore, per_check_timeout, deadline):
       # Tầng sâu : 16 site giá trị cao × tất cả ứng viên
       # Tầng rộng: ~150 site B2B × ứng viên tốt nhất (candidates[0])
       # Trần cứng osint_rules_max_requests; vượt thì cắt và ghi log
   ```

   Kiểm mỗi lần gọi:

   ```python
   text = resp.text
   e_ok = site["e_string"] in text
   m_bad = site["m_string"] in text if site.get("m_string") else False
   hit = resp.status_code == site["e_code"] and e_ok and not m_bad
   ```

   Giữ nguyên `_bounded_check` (semaphore + deadline) — đừng viết lại cơ chế chặn.

6. **Sửa so khớp danh mục NSFW** trong `osint_scanner.py` (xem mục Bẫy ở trên).
   Áp dụng cho cả `UserScannerAdapter` và `HoleheAdapter`.

7. **Test**:
   - `test_wmn_data_loads_and_filters` — nạp được, loại site thiếu `e_string`, loại NSFW
   - `test_nsfw_category_substring_match` — `"xx NSFW xx"` bị loại (test hồi quy cho đúng bẫy)
   - `test_content_check_rejects_soft_404` — `e_string` vắng → không tính là tìm thấy
   - `test_content_check_rejects_on_m_string` — `m_string` xuất hiện → không tính
   - `test_request_budget_capped` — tổng số lần gọi ≤ `osint_rules_max_requests`
   - `test_broad_tier_uses_single_candidate` — tầng rộng chỉ dùng `candidates[0]`

8. **Kiểm chứng bằng script gốc** — chạy lại `fp_probe.py` với logic mới; kỳ vọng **0/16 báo nhầm**.

## Success Criteria

- [ ] Username ma → **0 báo nhầm** (hiện 6/16)
- [ ] Người thật vẫn tìm ra trên ≥5/6 site đối chứng
- [ ] Danh mục `xx NSFW xx` bị loại; có test hồi quy
- [ ] Tổng số lần gọi mạng ≤ `osint_rules_max_requests` mọi lúc
- [ ] Nhánh đoán link chạy xong trong hạn 45s ở lần chạy thật
- [ ] `wmn-data.json` nguyên trạng + có NOTICE ghi công
- [ ] Test unit toàn xanh

## Test Gate

```bash
cd d:/cong_viec/22-22/get-beam
.venv/Scripts/python.exe -m pytest tests/unit/test_social_pipeline_helpers.py \
  tests/unit/test_osint_scanner.py -q
.venv/Scripts/python.exe -m pytest tests/unit/ -q -k "osint or social or pixel"
```

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Giả định 5% treo sai → vỡ ngân sách 45s | **Cao** | Trần cứng `osint_rules_max_requests` + deadline sẵn có. Phase 4 đo con số thật và chỉnh lại. |
| ~~Không có trường xếp hạng → "150 site đầu" là tuỳ tiện~~ **ĐÃ XỬ LÝ (D5)** | ~~Cao~~ → **Thấp** | Validate 11-08-26 chốt: **bước 3 đo offline toàn bộ 356 site** trước khi chốt danh sách. Danh sách đến từ số đo, không từ thứ tự file. Kết quả khảo sát lưu ở `reports/wmn-site-survey.md`. |
| `e_string`/`m_string` mục nát khi site đổi giao diện | Trung bình | Fail-closed (không khớp = không tìm thấy). Ghi ngày tải trong NOTICE; nêu nhu cầu làm mới định kỳ. |
| Tải cả body trang (thay vì chỉ đọc status) tốn băng thông/bộ nhớ | Trung bình | `httpx` sẵn có timeout; cân nhắc `resp.text[:200_000]`. Đo bộ nhớ ở Phase 4. |
| IP máy chủ bị site chặn khi quét 300 lần/lượt | Trung bình | Đã có `osint_scan_daily_budget = 5`/site/ngày. Theo dõi tỉ lệ 403 ở Phase 4. |
| Nghĩa vụ ShareAlike vô tình phát sinh | Thấp | Không bao giờ sửa file; lọc lúc chạy |
