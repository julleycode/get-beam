# Phase 4 — đo lại trên dữ liệu thật

**Ngày đo:** 11-08-26 · **Loại:** cổng nghiệm thu, không sửa code sản phẩm

Chạy lại đúng kịch bản đã phát hiện cả 3 lỗi, cùng visitor / cùng email / cùng site.

## TL;DR

**Cả 3 lỗi đã sửa và đo được.** Nhưng mục tiêu cuối — *sales nhìn vào và dùng được* —
**chưa đạt**, vì hai lý do mới, cả hai đều cần bạn quyết:

- Dòng duy nhất còn hiển thị là **sai người** (Freelancer.com), lọt qua bằng `name_matches`,
  một hàm **nằm ngoài phạm vi plan này**.
- Kết quả **đúng** (`github.com/nhantochi95` và 5 site khác) **đã được tìm ra** nhưng bị
  xếp `guess` nên **bị ẩn**.

## Môi trường

```
DB      localhost:5433/retarget_agent   (ghim rõ — .env trỏ Supabase PROD)
site    site_92e8f1f8a71c   (beamlab)
visitor 4719d9fe-3041-422e-b25f-6aa34a46b7f6
email   nhantochi95@gmail.com   ·  full_name = "Nhan To"
cache   đã xoá 2 khoá Redis trước khi đo (TTL 7 ngày — không xoá thì đo lại kết quả cũ)
gemini  tắt (run_gemini=False) để tách nhiễu
```

## Bảng trước / sau

| Chỉ số | Trước (11-08-26) | Sau | |
|---|---|---|---|
| Dòng hiển thị ("likely"+"confirmed") | 28 | **1** | |
| Trong đó username khớp URL | **0 / 28** | 0 / 1 | ❌ xem F1 |
| Dòng "confirmed" | 0 | 1 | ❌ sai người |
| "guess" (ẩn) | 392 | 1.237 | ⚠️ đúng dự đoán Phase 1 |
| Kết quả đúng bị gộp xoá mất | 9 / 10 | **0** | ✅ |
| `github.com/nhantochi95` là dòng riêng | **Không** | **Có** | ✅ |
| HackTheBox / StackOverflow / Plurk trong danh sách hiển thị | có | **0 / 0 / 0** | ✅ |
| Báo nhầm với username ma | 6 / 16 | **0 / 16** | ✅ |
| Thời gian chặng đoán link | (chưa tách) | **19,0s** / hạn 45s | ✅ |
| Số lần gọi mạng chặng đoán link | ~160 | 278 / trần 300 | ✅ |
| Site người lớn lọt bộ lọc | 39 | **0** | ✅ |
| Người dùng xác nhận đúng | 0 | **chờ bạn xác nhận** | ⏳ |

## Ba điều bắt buộc (Phase 4 bước 3)

| Kiểm | Kết quả |
|---|---|
| `github.com/nhantochi95` là dòng riêng, username khớp URL | ✅ |
| HackTheBox / StackOverflow / Plurk không nằm trong danh sách hiển thị | ✅ |
| Mọi dòng hiển thị đều có username khớp URL | ❌ **1/1 lệch** — xem F1 |

### Lỗi gộp danh tính: đã hết

Trước đây GitHub chỉ còn **một** dòng, mang URL của người này và username của người kia.
Bây giờ là **9 dòng riêng**, mỗi dòng username khớp đúng URL của chính nó:

```
guess  nhanto       https://github.com/nhanto        maigret,rule-base
guess  tonhan       https://github.com/tonhan        maigret,rule-base
guess  nhan-to      https://github.com/nhan-to       rule-base
guess  nto          https://github.com/nto           rule-base
guess  nhant        https://github.com/nhant         rule-base
guess  nhantochi95  https://github.com/nhantochi95   rule-base   ← ĐÚNG
```

## F1 — dòng hiển thị duy nhất là sai người

```json
{"site_name": "Freelancer.com", "confidence": "confirmed", "source_engine": "maigret",
 "url": "https://www.freelancer.com/api/users/0.1/users?usernames%5B%5D=nhanto&compact=true",
 "extra": {"username": "nhanto", "fullname": "Nhanto", "created_at": "2018-02-07"}}
```

Lọt qua bằng `name_matches("Nhanto", "Nhan To")` trong `social_rules.py`:

```
token chung   : {"nhanto"} ∩ {"nhan","to"} = ∅          → không đạt luật ≥2 token
nối chuỗi     : "nhanto" ⊂ "nhanto"  (≥6 ký tự)          → ĐẠT  → "confirmed"
```

Luật nối chuỗi vốn để bắt handle kiểu `nathannguyennhat` ⊂ `Nathan Nguyen Nhat`. Với tên
Việt hai âm tiết, nó biến **mọi** người tên `Nhanto` trên Internet thành "chính là bạn" —
đúng cái mà chính plan đã cảnh báo: *"`nhanto` là tên rất phổ biến với người Việt"*.

**`name_matches` không nằm trong phạm vi plan này** (blast radius không liệt kê nó, và cả 3
lỗi gốc đều ở chỗ khác). Đây là **lỗi thứ tư**, phép đo mới lộ ra.

Ghi chú thêm: dòng này lẽ ra bị luật handle-phải-khớp-URL chặn, nhưng theo quyết định bạn
chốt hôm nay, nhánh khớp-tên được **miễn trừ** khỏi luật đó. Với thứ tự gốc trong plan, nó
đã bị hạ xuống `guess`. Đây là bằng chứng đo được về cái giá của miễn trừ đó.

## F2 — kết quả đúng bị tìm ra rồi bị ẩn

Chặng đoán link tìm đúng `nhantochi95` trên **6 site**, tất cả đều `guess`:

```
GitHub     https://github.com/nhantochi95
GitLab     https://gitlab.com/nhantochi95
X          https://x.com/nhantochi95
Twitch     https://www.twitch.tv/nhantochi95
Pinterest  https://www.pinterest.com/nhantochi95
Dev.to     https://dev.to/nhantochi95          ← đã xác nhận ĐÚNG hôm 11-08-26
```

Không dòng nào được nâng hạng, vì cả ba cửa đều đóng:

| Cửa nâng hạng | Vì sao không mở |
|---|---|
| `_EMAIL_KEYED` → confirmed | rule-base không phải nguồn khoá theo email |
| khớp tên → confirmed | chặng đoán link không đọc tên người từ trang |
| `cand_source == "known"` → likely | `nhantochi95` đến **từ email**, không phải handle đã biết |
| site-overlap + duy nhất 1 ứng viên → likely | GitHub có 9 ứng viên → `per_site ≥ 2` |

Đây đúng là rủi ro Phase 2 đã ghi: *"B có thể hạ hạng quá tay, không còn gì hiển thị"*.
Plan yêu cầu **báo, không tự đổi** — nên tôi báo.

## Kiểm chứng D2 (phương án B) — bước 6

Dự đoán lúc validate: sau Phase 1 hầu hết site sẽ có `per_site ≥ 2`, nên B hạ hạng gần hết.

| Chỉ số | Đo được |
|---|---|
| Tổng số site có dòng | 424 |
| Site chỉ có **đúng 1** ứng viên | **7** (1,7%) |

**Dự đoán đúng.** B hoạt động như thiết kế. Nó không thoái hoá thành A, nhưng cũng gần như
không còn nâng hạng cho ai — đó chính là F2.

## Kiểm chứng D3 (ngân sách 300) — bước 5

| Chỉ số | Đo được | Ghi chú |
|---|---|---|
| Số lần gọi đã lên lịch | 278 | 16 site sâu × 8 ứng viên + 150 site rộng × 1 |
| Trần cứng | 300 | không chạm |
| Thời gian chặng | **19,0s** | hạn 45s, dư 26s |
| Tỉ lệ treo (khảo sát 1.424 probe) | **1,5%** | giả định làm việc là 5% → **thận trọng quá mức** |
| Tỉ lệ 403 | 14,6% | rẻ, trả nhanh |

**Kết luận: giữ nguyên 300.** Còn dư biên để nâng `osint_rules_broad_sites` (150 → tối đa 180
site sạch đã khảo sát), nhưng **chưa nên chỉnh** cho tới khi đo trên Railway — IP trung tâm dữ
liệu bị chặn nhiều hơn IP dân dụng đã đo ở đây.

## Đo thứ tự ứng viên D4 — bước 7, CHỈ ĐO

| Nguồn ứng viên | Số dòng kết quả |
|---|---|
| `name` (từ họ tên) | 1.232 |
| `email` (phần đầu email) | 6 |
| `known` (handle đã biết) | 0 |

Nguồn `name` sinh ra **99,5%** số dòng, và **không dòng nào đúng**. Nguồn `email` sinh 6 dòng,
và **đó là những dòng đúng**. Lặp lại kết quả 11-08-26 chứ không phải mẫu mới.

**Vẫn n = 1 người. KHÔNG đổi `derive_username_candidates`.** Cần tối thiểu **8–10 visitor thật**
đã xác nhận thủ công mới đủ để lật comment ở `social_rules.py:108-109`; một người thì bất kỳ
kết luận nào cũng chỉ là kể lại một giai thoại.

## Việc còn lại

- [ ] **Bạn xác nhận danh sách mới** (bước 8) — chưa làm được vì danh sách hiển thị chỉ có 1 dòng và nó sai.
- [ ] Quyết F1 (`name_matches`) và F2 (kết quả đúng bị ẩn) — xem phần dưới.
- [ ] Đo lại trên Railway trước khi bật `enable_osint_scan`.

---

# Lần đo 2 (12-08-26) — sau khi sửa F1

Quyết định của chủ dự án: **chỉ miễn trừ nguồn email-keyed** khỏi luật handle-phải-khớp-URL;
nhánh khớp-tên phải đi qua luật đó. Mẫu số `per_site` cũng sửa cho khớp: dòng email-keyed được
miễn trừ nhưng **vẫn tính là ứng viên** (nếu không, một phỏng đoán cạnh nó sẽ được nâng hạng
như thể nó đứng một mình).

## F1 — ĐÃ SỬA, xác nhận bằng số đo

| | Lần đo 1 | Lần đo 2 |
|---|---|---|
| `Freelancer.com` / `nhanto` | **confirmed, hiển thị** | **guess, ẩn** ✅ |

URL của nó là endpoint API (`.../api/users/0.1/users?usernames[]=nhanto`), đoạn cuối không phải
`nhanto` → luật URL hạ hạng. Trước đây nó thoát nhờ miễn trừ khớp-tên.

Bốn dòng `confirmed` còn lại **khác loại** với Freelancer:

| Site | Tên đọc được | Nhánh của `name_matches` |
|---|---|---|
| Facebook, Disqus, Duolingo, Chess | `"Nhan To"` | **mạnh** — khớp đủ 2 token |
| ~~Freelancer~~ | `"Nhanto"` | ~~yếu — nối chuỗi~~ (đã bị chặn) |

Đây là khớp tên **chính xác cả hai token** với tên thật của visitor, không phải trùng ngẫu nhiên
kiểu nối chuỗi. **Cần chủ dự án xác nhận** (bước 8): `facebook.com/nhanto` hiển thị tên "Nhan To"
có phải bạn không? Nếu có → đây là kết quả đúng đầu tiên mà đường ống tự tìm ra.

## F3 — PHÁT HIỆN MỚI: luật "duy nhất 1 ứng viên" không ổn định

Hai lần chạy cách nhau vài giờ, **cùng code, cùng visitor**:

| | Lần 1 | Lần 2 |
|---|---|---|
| Số dòng Maigret trả về | **1.208** | **406** |
| Tổng số dòng | 1.238 | 447 |
| Site chỉ có **đúng 1** ứng viên | **7** | **404** |
| Dòng hiển thị | 1 | **24** (4 confirmed + 20 likely) |

**Toàn bộ 20 dòng `likely` mới đều là site mà lần 1 có 2–3 ứng viên.** Ví dụ Plurk: lần 1 có 3
dòng (`nhanto`, `tonhan`, `nhan.to`) → `per_site = 3` → hạ hạng; lần 2 Maigret chỉ trả 1 dòng →
`per_site = 1` → **nâng lên `likely`**, và `https://gab.com/nhanto` quay lại danh sách hiển thị.

Nguyên nhân **không phải** thay đổi F1 — đã kiểm chứng: mỗi dòng `likely` mới đều có
`per_site = 1` ở lần 2 và `per_site ≥ 2` ở lần 1.

Hệ quả thiết kế, nói thẳng:

> **Maigret trả về càng ít kết quả, Beam càng tự tin.** Mạng chậm, bị chặn, hay hết hạn giờ đều
> làm giảm số ứng viên cạnh tranh, và luật "duy nhất 1 ứng viên" đọc đó thành "đã thu hẹp về một
> người". Độ tin cậy đang phụ thuộc vào **độ phủ của một engine bên ngoài hay hỏng**, theo chiều
> ngược với trực giác.

D2/phương án B vẫn chặn đúng ca lỗi khi Maigret chạy đủ (lần 1: 28/28 → 0). Nhưng nó **không có
sàn**: khi engine chạy kém, luật tự mở. Đây là thứ mà cả phân tích lúc validate lẫn lần đo 1 đều
không thấy, vì cần **hai lần chạy** mới lộ ra.

Chưa sửa — theo đúng nguyên tắc của plan: đo, báo, không tự đổi.

---

# Lần đo 3 (12-08-26) — sau khi tắt luật đếm

Chủ dự án chốt: **tắt luật site-overlap**, đặt sau một công tắc mặc định TẮT
(`osint_site_overlap_promotes`), để bật lại được khi đủ mẫu mà không phải viết lại code.
`test_site_overlap_is_likely` **giữ nguyên, không sửa một dòng** — fixture bật cờ lên để test
đó vẫn kiểm đúng hành vi nó mô tả; đường mặc định TẮT có test riêng.

| | Lần 1 | Lần 2 | Lần 3 |
|---|---|---|---|
| Luật đếm | bật | bật | **tắt** |
| Dòng Maigret | 1.208 | 406 | **0** |
| Tổng dòng | 1.238 | 447 | 51 |
| Dòng hiển thị | 1 (sai người) | 24 (bất ổn) | **0** |

Luật đếm tắt ⇒ Maigret chạy kém **không còn** làm Beam tự tin hơn. Đó là điều cần đạt.

## F4 — Maigret không ổn định ở mức nghiêm trọng

Ba lần chạy cùng visitor, cùng code, cách nhau vài giờ: **1.208 → 406 → 0** dòng.

Lần 3 Maigret chạy (có trong `stages_run`) nhưng trả về **không dòng nào**. Toàn bộ 51 dòng còn
lại đến từ chặng đoán link.

Hệ quả: 4 dòng khớp tên thật (Facebook, Disqus, Duolingo, Chess) **biến mất** ở lần 3, vì tên
người chỉ đọc được từ Maigret. Chặng đoán link không đọc tên, nên nó không bao giờ tạo ra
`confirmed`.

Nói gọn: **hiện tại toàn bộ khả năng cho ra kết quả hiển thị đang phụ thuộc vào một engine trả
về lúc 1.208 lúc 0.** Plan cấm đụng Maigret (đúng, vì lỗi không nằm ở nó), nhưng độ tin cậy của
nó giờ là yếu tố chi phối. Chưa rõ nguyên nhân: hết hạn giờ, bị chặn IP, hay giới hạn tần suất —
**cần đo riêng**, chưa ai đo.

## Điều chưa giải quyết

1. ~~**F1 — `name_matches` nối chuỗi quá lỏng.**~~ **ĐÃ SỬA 12-08-26** bằng cách thu hẹp miễn trừ
   xuống chỉ còn nguồn email-keyed. Nhánh nối chuỗi của `name_matches` **vẫn còn nguyên** —
   nó chỉ không còn tự động vượt được luật URL. Nếu sau này gặp ca có URL khớp mà tên chỉ trùng
   theo kiểu nối chuỗi, nó sẽ lại lọt.
1b. **F3 — luật "duy nhất 1 ứng viên" phụ thuộc độ phủ của Maigret** (xem phần trên). Nghiêm
   trọng hơn F1 vì nó làm kết quả không tái lập được giữa hai lần chạy. Chưa có hướng sửa;
   cần quyết định riêng.
2. **F2 — không có đường nào để một ứng viên từ email được nâng hạng**, kể cả khi đã được
   xác minh nội dung. Chặng đoán link hiện không mang theo bằng chứng "đã xác minh nội dung"
   vào `_classify`.
3. **`guess` phình từ 392 lên 1.237.** Bị ẩn nên không lộ ra ngoài, nhưng nếu sau này có màn
   hình xem `guesses` thì cần phân trang.
4. **Chặng quét email (stage A) mất ~123s**, gấp đôi cả hai chặng username cộng lại. Nằm
   ngoài phạm vi plan, chưa ai đo trước đây.
5. **Đo từ IP Việt Nam.** Railway sẽ khác về tỉ lệ 403/treo.
