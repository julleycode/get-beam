# Khảo sát site WhatsMyName — chốt danh sách tầng quét rộng (D5)

**Ngày đo:** 11-08-26 · **Phase:** 3, bước 3 · **Loại:** bước ĐO, không sửa code sản phẩm

Quyết định D5 yêu cầu **đo trước, chốt sau**: `wmn-data.json` không có trường xếp hạng,
nên "lấy 150 site đầu file" là tuỳ tiện. Báo cáo này là phép đo thay cho thứ tự file.

## TL;DR

- Đo **356 site** nhóm B2B × (3 username thật + 1 username ma) = **1.424 lần gọi**, hết **54 giây**.
- **0/356 site báo nhầm username ma.** Cách kiểm nội dung của WhatsMyName không sinh dương tính giả
  trên toàn bộ mẫu — đây là bằng chứng trực tiếp cho tiền đề của Phase 3.
- Loại **76 site**, giữ **280**. Chốt **150** site cho tầng rộng, xếp theo độ trễ tăng dần.
- Giả định "5% treo" của D3 **thận trọng quá mức**: đo được **1,5%**. Trần 300 lần gọi còn dư biên lớn.

## Phương pháp

| Hạng mục | Giá trị |
|---|---|
| Nguồn | `apps/api/data/wmn-data.json`, commit `c03273c8`, tải 11-08-26 |
| Lọc đầu vào | `cat ∈ {social, coding, tech, business, finance}`, có `e_string`, bỏ `xx NSFW xx` |
| Số site vào đo | 356 |
| Username thật | `nhantochi95`, `torvalds`, `durov` |
| Username ma | `zzqx7v3mklophantom9418` |
| Luật tính "tìm thấy" | `status == e_code` AND `e_string` có trong body AND `m_string` (nếu có) KHÔNG có |
| Đồng thời / timeout | 24 / 8s |
| Script | `wmn_site_survey.py` (thư mục tạm, **không** commit vào `apps/`) |

Username ma là trọng tâm: site nào báo nó **tìm thấy** thì là máy sinh dương tính giả, loại thẳng
bất kể nhanh đến đâu.

> **Lưu ý về một lỗi đo đã sửa.** Lần chạy đầu bấm giờ *trước* khi lấy semaphore, nên "độ trễ" gồm
> cả thời gian xếp hàng → median 30,58s, vô nghĩa. Đã sửa (bấm giờ sau khi lấy semaphore) và đo lại.
> Mọi số dưới đây là của lần đo đã sửa. Số của lần đầu không được dùng ở đâu cả.

## Kết quả

| Kết luận | Số site |
|---|---|
| **Giữ** | **280** |
| Loại — chặn bot cứng (403 mọi lần) | 48 |
| Loại — lỗi/timeout mọi lần | 28 |
| Loại — báo nhầm username ma | **0** |

Độ trễ của 280 site giữ lại: **median 0,71s · p90 1,42s · p99 2,36s · max 3,84s**.
Median khớp đúng con số 0,7s mà plan đã ghi từ lần đo 11-08-26.

### Mức probe (n = 1.424)

| Chỉ số | Tỉ lệ | Ý nghĩa cho ngân sách |
|---|---|---|
| Treo / timeout | **1,5%** | Đây là loại **đắt** — ăn trọn 8s và khoá 1/10 năng lực |
| Tổng lỗi (gồm DNS, refused) | 8,5% | Phần ngoài timeout **hỏng nhanh**, gần như miễn phí |
| HTTP 403 | 14,6% | **Rẻ** — trả về ngay |
| Probe chậm > 4s | 0 | Không có đuôi chậm ẩn |

### Đối chiếu với D3 (ngân sách 300 lần gọi)

Bảng sức chứa trong Phase 3 quy ra: 2% treo → ~690 lần gọi; 5% treo → ~420. Đo được **1,5%**,
tức nằm **ngoài đầu thuận lợi** của bảng. Trần **300** giữ nguyên, còn dư biên rất lớn.

**Chưa kết luận được:** phép đo này chạy từ máy ở Việt Nam. Máy chủ thật ở Railway (IP trung tâm
dữ liệu) sẽ **bị chặn nhiều hơn** — riêng 403 đã 14,6% từ IP dân dụng. 403 thì rẻ, nhưng tỉ lệ treo
có thể khác. **Phase 4 đo lại trên đường chạy thật rồi chỉnh** — đúng như D3 đã chốt.

## Danh sách đã chốt

- Ghi ra: `apps/api/data/wmn-broad-sites.json` (**150** site).
- Xếp theo **độ trễ median tăng dần** — tầng C bị chặn bởi thời gian, nên site nhanh đáng giá hơn.
  Site chậm nhất được chọn: **0,76s**.
- Đã **trừ 16 site tầng sâu** khỏi tầng rộng để không kiểm hai lần → còn 270 ứng viên, lấy 150.
- File này do **Beam tạo từ số đo**, không phải bản sửa của `wmn-data.json` → không phát sinh nghĩa
  vụ ShareAlike. `wmn-data.json` giữ **nguyên trạng**.

Có 280 site dùng được nhưng chỉ lấy 150 theo `osint_rules_broad_sites`. Nới trần lên 280 là việc
Phase 4 quyết bằng số đo thời gian thật, không quyết ở đây.

## Site bị loại

**Chặn bot cứng — 403 mọi lần (48):** ADVFN, Beacons, BiggerPockets, Cloudflare, CodeSandbox, DOU,
DRIVE2.RU, Destructoid, Digitalspy, Donatello, Fodors Forum, Freelance.RU, Freelancehunt (Employer),
Freelancehunt (Freelancer), Hackernoon, HulkShare, Immunefi, Instagram (Imginn), Kick, KnowYourMeme,
Letterboxd, Marshmallow, Mastodon-C.IM, MyBuilder.com, Opencollective, PCPartPicker, Peerlist, Peing,
Producthunt, Quora, Raddle.me, Reddit, RoutineHub, SPOJ, Substack, Teespring, Truth Social, Udemy,
Untappd, Voices.com, Weblancer, Weibo, fanpop, hackrocks, npm, solo.to, tripadvisor, vsco.

**Lỗi/timeout mọi lần (28):** Anime-Planet, BabyPips, CodePen, Coub, Cracked, Etoro, Fark, Folkd,
Ko-Fi, LeakIX, MYM, Mastodon API, Mastodon-mastodon, Minds, MySpace, Orbys, Our Freedom Book,
Pastebin, Plurk, … (đầy đủ trong `wmn-survey.json` ở thư mục tạm).

**Đáng chú ý:** `Reddit` và `Substack` bị chặn 403 ở tầng rộng. Cả hai vẫn nằm ở **tầng sâu** với
URL riêng — tầng sâu không dùng danh sách này. `Plurk` timeout, khớp với việc dòng Plurk trong lần
chạy 11-08-26 vốn đã là rác.

## Điều chưa giải quyết

1. **Đo từ IP Việt Nam, không phải Railway.** Tỉ lệ 403/treo trên prod có thể khác hẳn. Phase 4 đo lại.
2. **`e_string` mục theo thời gian.** 0 dương tính giả là số của *hôm nay*. Cần đo lại định kỳ;
   ngày tải đã ghi trong `wmn-data.NOTICE`.
3. **Site có 0 lần trúng thật không bị loại.** 3 username mẫu không thể có tài khoản ở khắp 356 site,
   nên "không trúng" chủ yếu nghĩa là "không có tài khoản", không phải "`e_string` hỏng". Phép đo
   này **không** phân biệt được hai ca đó. Bộ lọc thật là username ma, và nó sạch 356/356.
4. **`uri_check` của WMN đôi khi là endpoint API**, không phải URL profile cho người xem. Tầng sâu
   tránh được vì dùng template riêng; tầng rộng thì không — ghi nhận, chưa sửa.
