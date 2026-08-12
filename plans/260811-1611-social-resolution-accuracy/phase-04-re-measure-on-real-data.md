---
phase: 4
title: "Re-measure on real data"
status: complete
priority: P1
effort: "S"
dependencies: [1, 2, 3]
---

# Phase 4: Re-measure on real data

## Overview

Chạy lại **đúng** kịch bản đã phát hiện ra cả 3 lỗi, so số trước/sau. Đây là cổng nghiệm thu —
không phải bước sửa.

Cũng là nơi giải quyết một câu hỏi mở mà bằng chứng hiện tại chưa đủ để trả lời: **thứ tự ưu tiên
ứng viên username**.

## Requirements

**Chức năng**
- Chạy lại trên đúng visitor cũ, cùng email, cùng site.
- So từng chỉ số với đường cơ sở 11-08-26.
- Ghi lại số đo vào một báo cáo, không chỉ nói miệng.

**Phi chức năng**
- Không sửa code sản phẩm trong phase này, trừ khi phép đo lộ ra hồi quy.

## Đường cơ sở (11-08-26, trước khi sửa)

| Chỉ số | Trước |
|---|---|
| Tổng dòng "likely" (hiển thị) | 28 |
| Dòng có username khớp URL | **0 / 28** |
| Dòng "confirmed" | 0 |
| "guess" (ẩn) | 392 |
| Kết quả đúng bị gộp xoá mất | 9 / 10 |
| `github.com/nhantochi95` hiện thành dòng riêng | **Không** |
| Báo nhầm với username ma | 6 / 16 |
| Thời gian hai chặng username | 67 giây |
| Người dùng xác nhận đúng | 0 dòng dùng được |

**Môi trường tái lập:**

```
DB      localhost:5433/retarget_agent
site    site_92e8f1f8a71c   (beamlab)
visitor 4719d9fe-3041-422e-b25f-6aa34a46b7f6
email   nhantochi95@gmail.com
đúng    github.com/nhantochi95, dev.to/nhantochi95
```

Dữ liệu test **đã tồn tại** trên DB local (chủ dự án chọn giữ 11-08-26).

## Related Code Files

- Create: `plans/260811-1611-social-resolution-accuracy/reports/measurement-after-fixes.md`
- Không sửa file sản phẩm (trừ khi lộ hồi quy → mở phase sửa riêng)

## Implementation Steps

1. **Ép chạy lại**, bỏ qua cache Redis (kết quả cũ có TTL 7 ngày):

   ```bash
   # xoá cache OSINT của email test trước khi đo
   ```

   Rồi chạy `resolve_social` với `run_gemini=False` để đo **riêng** hai chặng username, tách
   khỏi nhiễu do Gemini.

2. **Ghi bảng so sánh** cho toàn bộ chỉ số ở đường cơ sở.

3. **Kiểm 3 điều bắt buộc**:
   - `github.com/nhantochi95` là **dòng riêng**, username khớp URL
   - HackTheBox / StackOverflow / Plurk **không** nằm trong danh sách hiển thị
   - Mọi dòng hiển thị đều có username khớp URL

4. **Chạy lại `fp_probe.py`** với logic mới → kỳ vọng 0/16 báo nhầm.

5. **Đo giả định 5% treo của Phase 3**: đếm request hoàn tất / timeout / 403 trong một lượt,
   đối chiếu với con số ngân sách. Chỉnh `osint_rules_*` nếu lệch.

6. **Kiểm chứng D2 (đã chốt = phương án B)**: đếm số site có đúng 1 ứng viên profile sau Phase 1.

   Dự đoán từ validate 11-08-26: gần 0 — vì 28/28 dòng lỗi đều gộp ≥2 username, nên sau Phase 1
   `per_site ≥ 2` ở hầu hết site và B hạ hạng đúng chúng.

   - Nếu đúng dự đoán → B hoạt động như thiết kế, ghi lại số.
   - Nếu **ngược lại** (nhiều site chỉ có 1 ứng viên mà vẫn là người sai) → B chưa đủ,
     mở phase sửa tiếp. **Không** tự ý chuyển sang phương án A mà không hỏi.

7. **Đo thứ tự ứng viên (Quyết định D4)** — chỉ đo, không sửa:

   Comment trong `social_rules.py:108-109` khẳng định tên-từ-họ-tên nên xếp trước phần đầu email.
   Ca thật 11-08-26 cho kết quả **ngược lại**:

   | Nguồn ứng viên | Kết quả |
   |---|---|
   | Từ họ tên → `nhanto`, `tonhan` | toàn người khác |
   | Từ email → `nhantochi95` | **đúng** |

   **n = 1. Không đủ để đảo luật.** Việc cần làm ở đây:
   - Đếm số dòng cuối cùng theo `extra.cand_source` (`known` / `name` / `email`)
   - Ghi số vào báo cáo
   - Nêu rõ cần bao nhiêu mẫu nữa mới đủ kết luận
   - **Không sửa `derive_username_candidates`** trong phase này

8. **Nhờ chủ dự án xác nhận lại** danh sách kết quả mới (như đã làm 11-08-26) → ra tỉ lệ đúng thật.

## Success Criteria

- [ ] Báo cáo tồn tại kèm bảng trước/sau đầy đủ mọi chỉ số cơ sở
- [ ] `github.com/nhantochi95` là dòng riêng, username khớp URL
- [ ] 0 dòng hiển thị có username lệch URL (trước: 28/28 lệch)
- [ ] `fp_probe.py`: 0/16 báo nhầm
- [ ] Hai chặng username xong trong 45s; ghi con số thật
- [ ] D2 (phương án B) được kiểm chứng bằng số đo; nếu không đạt thì báo, không tự đổi
- [ ] D3 (ngân sách 300) đối chiếu với tỉ lệ treo/403 đo được; chỉnh `osint_rules_*` nếu lệch
- [ ] D4 có số đo và ngưỡng mẫu cần thiết; **không** đổi thứ tự ứng viên
- [ ] Chủ dự án xác nhận danh sách mới; ghi tỉ lệ đúng

## Test Gate

```bash
cd d:/cong_viec/22-22/get-beam
.venv/Scripts/python.exe -m pytest tests/unit/ -q -k "osint or social"
.venv/Scripts/python.exe -m pytest tests/integration/test_resolve_social_endpoint.py \
  tests/integration/test_osint_scan_endpoint.py -q
```

Test integration cần Postgres + Redis local — cả hai đang chạy (cổng 5433 / 6379).

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Cache Redis 7 ngày trả kết quả cũ → tưởng đã sửa xong | **Cao** | Xoá cache trước mỗi lần đo. Ghi rõ thành bước 1, không phải chú thích. |
| n = 1 người. Kết quả có thể không đại diện | **Cao** | Ghi thẳng vào báo cáo. Không tổng quát hoá từ một mẫu. Nêu số mẫu cần thêm. |
| Kết quả sau khi sửa gần như rỗng → không đo được gì | Trung bình | Rỗng cũng là kết quả hợp lệ: thà không có còn hơn sai. Ghi lại và bàn ngưỡng hiển thị. |
| Site bên ngoài đổi giao diện giữa hai lần đo → so lệch | Thấp | Đo trong cùng phiên khi có thể; ghi ngày giờ |
| Hạn 5 lượt/ngày/site chặn việc đo lặp | Thấp | Gọi thẳng `resolve_social` (bỏ qua endpoint) như đã làm 11-08-26 |

## Bước tiếp theo sau phase này

Sau khi có số:

- Nếu đạt hết tiêu chí → bàn việc bật `enable_osint_scan` trên môi trường staging.
- Nếu chưa → giữ tắt, mở plan sửa tiếp dựa trên số vừa đo.
- Ý tưởng Shodan InternetDB cho nhánh IP vẫn đang chờ, cần phép đo riêng — **không** gộp vào đây.
