---
title: "Social resolution accuracy - stop mixing identities"
description: >-
  Pipeline social-resolution đang trộn nhiều người khác nhau vào một dòng kết quả,
  rồi gắn nhãn "có thể là người này". Đo trên dữ liệu thật: 28/28 dòng sai, và 9/10
  kết quả ĐÚNG đã bị chính hàm gộp trùng của Beam xoá mất. Plan này sửa 3 lỗi trong
  code Beam (không đụng Maigret) và đo lại bằng cùng phép đo đã phát hiện ra lỗi.
status: in-progress
priority: P1
branch: "dev_nhantc2"
tags:
  - osint
  - social-resolution
  - identity
  - data-integrity
blockedBy: []
blocks: []
created: "2026-08-11T09:15:25.173Z"
createdBy: "ck:plan"
source: skill
---

# Social resolution accuracy - stop mixing identities

## Overview

`POST /visitors/{site_id}/{visitor_id}/resolve-social` tìm profile mạng xã hội cho một
visitor **đã có tên và email**. Kết quả hiện ra thẳng trên trang chi tiết visitor, nơi
sales nhìn vào để đi tiếp cận.

**Chạy thật ngày 11-08-26 trên `nhantochi95@gmail.com` (site `beamlab`, DB local):**

| Chỉ số | Kết quả |
|---|---|
| Profile đạt mức "confirmed" | **0** |
| Profile gắn nhãn "likely" (được hiển thị) | 28 |
| Trong 28 đó, số dòng có username khớp URL | **0 / 28** |
| Số kết quả ĐÚNG bị hàm gộp trùng xoá mất | **9 / 10** |
| Người dùng xác nhận đúng | 0 (dòng GitHub hiện tên đúng nhưng **link sai người**) |

Ba lỗi độc lập, xếp theo mức nghiêm trọng:

1. **Gộp trùng làm lẫn danh tính** — `_dedupe` gộp theo tên site, nên
   `github.com/nhantochi95` (đúng) và `github.com/nhanto` (người khác, tài khoản có thật)
   bị nhập làm một dòng: giữ **link của người kia** + **username của người này**.
2. **Nâng hạng "likely" quá tay** — luật "email có đăng ký trên site X → mọi phỏng đoán
   username trên site X là likely". Email này đăng ký ở 90 site, nên luật tự thổi 28 phỏng
   đoán rác lên mức được hiển thị.
3. **Xác minh bằng mã trạng thái** — nhánh đoán link chỉ kiểm `HTTP 200`. Đo bằng username
   ma: **6/16 site báo nhầm**.

### Nguyên tắc xuyên suốt

> **Không đụng Maigret.** Cả 3 lỗi nằm trong code Beam. Maigret trả kết quả đúng chức năng
> của nó (`github.com/nhanto` là tài khoản có thật của người khác) và tự gắn nhãn "guess".
> Chính Beam gộp sai và chấm điểm sai.

> **Sửa tại chỗ dùng sai, không lật quyết định cũ.** Hai test đang bảo vệ đúng hành vi cần
> đổi (`test_dedupe_collapses_same_site_prefers_profile`, `test_site_overlap_is_likely`).
> Cả hai **hợp lý trong ngữ cảnh gốc**. Vấn đề là hàm được tái dùng cho việc thứ hai mà nó
> không được thiết kế cho. Phase 1 và 2 phải giữ nguyên hành vi gốc.

> **Đo lại bằng đúng phép đo đã tìm ra lỗi.** Phase 4 chạy lại kịch bản 11-08-26 và so số.

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Fix dedupe identity collision](./phase-01-fix-dedupe-identity-collision.md) | Done |
| 2 | [Fix likely-confidence over-promotion](./phase-02-fix-likely-confidence-over-promotion.md) | Done |
| 3 | [Content-verified profile check](./phase-03-content-verified-profile-check.md) | Done |
| 4 | [Re-measure on real data](./phase-04-re-measure-on-real-data.md) | Done — 2 findings, chờ quyết |

Phase 1 → 2 → 3 tuần tự (2 phụ thuộc kết quả 1; 3 độc lập nhưng đo được sau 1+2).
Phase 4 chạy cuối, cần cả 3.

## Blast radius

| File | Thay đổi |
|---|---|
| `apps/api/services/osint_scanner.py` | `_dedupe` nhận thêm tham số khoá gộp; sửa so khớp danh mục NSFW |
| `apps/api/services/social_resolver.py` | `_classify` bỏ/thu hẹp luật site-overlap; gọi `_dedupe` với khoá mới |
| `apps/api/services/social_rules.py` | thay 16 template thủ công bằng kiểm nội dung theo dữ liệu WhatsMyName |
| `apps/api/data/wmn-data.json` | **file mới** — dữ liệu WhatsMyName (CC BY-SA 4.0, đã được chủ dự án chấp nhận) |
| `apps/api/config.py` | thêm cận trên số site/số ứng viên cho nhánh đoán link |
| `tests/unit/test_osint_scanner.py` | test mới cho khoá gộp; giữ nguyên 2 test cũ |
| `tests/unit/test_social_resolver.py` | test mới cho chấm điểm; sửa `test_site_overlap_is_likely` theo quyết định D2 |
| `tests/unit/test_social_pipeline_helpers.py` | test mới cho kiểm nội dung |

**Không đụng:** `maigret_engine.py`, `paid_osint.py`, `enricher.py`, schema DB, migration,
pixel, đường ống nhận diện (identity resolution).

## Không nằm trong phạm vi

- Đổi thứ tự ưu tiên ứng viên username (tên-người trước / email trước). Bằng chứng hiện
  tại là **n = 1**. Phase 4 chỉ **đo**, không sửa. Xem D4.
- Bất kỳ module nào khác của Hippie-OSINT-Toolkit (whois, crt.sh, GHunt, Discord/Telegram/
  TikTok/Reddit/Mastodon, reverse image). Đã loại sau phân tích 11-08-26.
- Shodan InternetDB cho nhánh IP. Ý tưởng riêng, cần phép đo riêng.
- Bật `enable_osint_scan` trên production.
- Sửa hook chặn `.env` (cơ chế `APPROVED:` hỏng — ghi nhận, không thuộc plan này).

## Quyết định — ĐÃ CHỐT (validate 11-08-26)

| # | Quyết định | Chốt | Phase |
|---|---|---|---|
| **D1** | Sửa `_dedupe` bằng tham số mới, không đổi khoá toàn cục | ✅ Tham số `by_username` | 1 |
| **D2** | Luật site-overlap | ✅ **Phương án B** — chỉ promote khi site có duy nhất 1 ứng viên | 2 |
| **D3** | Ngân sách nhánh đoán link | ✅ **~300** lần gọi, chỉnh lại ở Phase 4 bằng số đo thật | 3 |
| **D4** | Đổi thứ tự ứng viên username | ✅ **Không** — chỉ đo, bằng chứng mới n=1 | 4 |
| **D5** | Cách chọn ~150 site cho tầng quét rộng | ✅ **Đo offline 1 lần trước**, chốt danh sách theo dữ liệu | 3 |
| **D6** | Đơn vị phát hành | ✅ **Phase 1+2 là một đơn vị** — commit riêng, nhưng không bật cho ai dùng giữa chừng | 1, 2 |

## Điều kiện hoàn thành

- [ ] Không dòng kết quả nào có username lệch URL (hiện 28/28 lệch)
- [ ] `github.com/nhantochi95` xuất hiện thành **dòng riêng**, không bị đè
- [ ] Số nhãn "likely" giảm mạnh và mỗi nhãn còn lại giải thích được
- [ ] Đo lại bằng username ma: 0 báo nhầm (hiện 6/16)
- [ ] Toàn bộ test unit hiện có vẫn xanh (trừ những test đổi có chủ ý, ghi rõ lý do)
- [ ] Đường ống vẫn nằm trong ngân sách thời gian; ghi lại con số đo được

## Dependencies

Không có phụ thuộc chặn.

**Liên quan (không chặn):** `plans/260805-1543-identity-coverage-recovery/` — plan đó sửa
tầng *nhận diện* (Leadpipe/Capturify/RB2B tạo ra visitor có email). Plan này sửa tầng
*làm giàu* chạy **sau** khi đã nhận diện. Không đụng cùng file. Phase 4 đo dễ hơn nếu plan
kia đã cấp thêm visitor thật, nhưng không bắt buộc — dữ liệu test 11-08-26 vẫn còn trên DB local.

## Validation Log

### Session 1 — 11-08-26 (`/ck:plan validate`)

**Verification Results**
- Claims checked: 13
- Verified: 12 | Failed: 0 | Unverified: 0 | Corrected: 1
- Tier: Standard (4 phases → Fact Checker + Contract Verifier)
- Đã xác minh: 3 chỗ gọi `_dedupe` (`osint_scanner.py:479`, `social_resolver.py:224,253`);
  `_dedupe` tại `osint_scanner.py:373`; `_classify` tại `social_resolver.py:91`;
  so khớp danh mục kiểu exact tại `osint_scanner.py:165`; `SITE_URL_TEMPLATES` = 16;
  `apps/api/data/` tồn tại; khối config `osint_*` tại `config.py:1265-1271`;
  `maigret_engine._load_db` (mẫu cache module); chỉ dòng `kind == "profile"` vào `_dedupe`
  ở `social_resolver.py:216-224`.
- Chỉnh: tham chiếu `social_rules.py:110` → `108-109` (Phase 4).
- **Không có failure.** Plan đủ điều kiện triển khai.

**Phép đo bổ sung — bác bỏ một rủi ro do chính plan nêu**

Plan (Phase 2) từng xếp rủi ro CAO: "sau Phase 1, luật *duy nhất 1 ứng viên* có thể không bao giờ
kích hoạt, phương án B thoái hoá thành A". Đo lại trên `osint_result.json`:

| Chỉ số | Giá trị |
|---|---|
| Dòng hiển thị chắc chắn đã gộp ≥2 username | **28 / 28 (100%)** |
| Dòng ẩn chắc chắn đã gộp ≥2 username | 386 / 392 (98%) |
| Dòng profile chỉ có 1 username | **0** |

Phương pháp: `extra.username` lệch URL ⇒ ít nhất hai dòng khác username đã bị nhập làm một.
Sau Phase 1 chúng tách ra ⇒ `per_site ≥ 2` ⇒ **B hạ hạng đúng 100% ca lỗi**.
→ Rủi ro **bác bỏ**, bảng rủi ro Phase 2 đã cập nhật.

**Quyết định người dùng chốt**

| # | Câu hỏi | Chốt | Lan xuống |
|---|---|---|---|
| D2 | Luật site-overlap: bỏ hẳn hay thu hẹp? | **Thu hẹp (B)** | Phase 2 |
| D6 | Phase 1 phát hành riêng hay gộp với Phase 2? | **Gộp làm một đơn vị** | Phase 1, 2 |
| D5 | Chọn ~150 site thế nào khi không có trường xếp hạng? | **Đo offline 1 lần trước rồi chốt** | Phase 3 |
| D3 | Ngân sách 300 lần gọi (chưa đo trên Railway)? | **Chấp nhận 300**, chỉnh ở Phase 4 | Phase 3, 4 |

### Whole-Plan Consistency Sweep

Đã đọc lại `plan.md` + cả 4 `phase-*.md` sau khi lan quyết định.

| Kiểm | Kết quả |
|---|---|
| Khung "hai phương án A/B" trong Phase 2 còn sót sau khi chốt B | ✅ Đã sửa thành quyết định đã chốt |
| Bảng rủi ro Phase 2 còn nêu rủi ro đã bị bác bỏ | ✅ Đã thay bằng số đo |
| Phase 1 chưa nói việc gộp phát hành với Phase 2 | ✅ Đã thêm |
| Phase 3 chưa có bước đo offline (D5) | ✅ Đã thêm thành bước 3 |
| Phase 4 vẫn ghi "chốt D2" dù D2 đã chốt | ✅ Đổi thành "kiểm chứng D2" |
| Tham chiếu dòng code trong 4 phase | ✅ Khớp code thật |
| Số liệu (28/28, 6/16, 9/10, 708/706/673, 215/465, 67s) trùng nhau giữa các file | ✅ Nhất quán |

**Mâu thuẫn chưa giải quyết: không có.**

## Bằng chứng gốc

- Dữ liệu chạy thật: `osint_result.json` (thư mục tạm phiên 11-08-26, 420 dòng)
- Visitor test còn nguyên trên DB local: site `site_92e8f1f8a71c`, visitor
  `4719d9fe-3041-422e-b25f-6aa34a46b7f6`, email `nhantochi95@gmail.com`
- Script đo báo nhầm: `fp_probe.py`, `wmn_check.py` (thư mục tạm)
