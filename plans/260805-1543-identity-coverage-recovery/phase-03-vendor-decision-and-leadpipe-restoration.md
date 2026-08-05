---
phase: 3
title: "Vendor decision and Leadpipe restoration"
status: pending
priority: P1
dependencies: [2]
---

# Phase 3: Vendor decision and Leadpipe restoration

# ⚠️ GATE — phase này mở đầu bằng một quyết định business, không phải việc kỹ thuật

## Overview

<!-- Updated: EXECUTE session 3 (05-08-26) — bằng chứng mới từ audit chạy thật -->

> **⚠️ Bằng chứng mới từ Phase 2 (05-08-26) — đọc trước khi quyết định vendor.**
> Audit chạy thật trên Postgres: `ipinfo` **9 lần / 0 thành công**, `pdl_ip_enrich` **9 lần / 0
> thành công**, `rb2b` 14 lần / 8 thành công, `leadpipe` **0 dòng**. Nghĩa là Leadpipe chưa từng
> ghi một dòng `resolution_logs` nào — nó không thể là bên đã khoá oan visitor, dù 403 là thật.
> Hai hệ quả cho phase này:
> 1. Tiêu chí "Đã từng tạo ra identity đúng?" với Leadpipe không phải "chưa từng chạy" theo nghĩa
>    thất bại — mà là **chưa từng được gọi tới mức ghi log**. Đừng đọc nhầm thành bằng chứng chống
>    lại Leadpipe.
> 2. `ipinfo` và `pdl_ip_enrich` mới là hai provider đang tiêu slot mà không ra kết quả. Chúng
>    **không** nằm trong khung quyết định vendor hiện tại của phase này. Cân nhắc đưa vào.
>
> Ngoài ra một nửa nguyên nhân 9-lần-0-thành-công đã được sửa ở Phase 2 (H-1: provider thiếu key
> vẫn bị ghi "đã thử"). Nên **đo lại sau khi Phase 2 lên môi trường thật** trước khi kết luận về
> ipinfo/pdl.

Phase 1–2 chạy được mà không cần vendor nào. Phase này thì không: nó bắt đầu bằng câu hỏi
**có tiếp tục dùng person-graph không**, và chỉ khi trả lời "có" thì phần vận hành (giải quyết
tài khoản, quản lý pixel) mới có nghĩa.

Chi phí không phải rào cản (có API token free). Rào cản là **org hiện tại đã hết hạn** nên API bị
chặn hoàn toàn — pixel phục vụ được nhưng dữ liệu không đọc về được. Mục đích của phase này là
buộc quyết định dựa trên tiêu chí viết ra trước, thay vì mặc định "cứ mở tài khoản mới cho xong".

## Requirements

- Quyết định giữ/bỏ từng provider phải dựa trên tiêu chí đã viết ra, có số liệu kèm theo.
- Nếu giữ Leadpipe: **API phải trả 2xx** (pixel đã verify chạy rồi — nút thắt nằm ở tài khoản).
- Không bật `auto_identify_enabled` cho tới khi provider health xanh.

## Architecture

### Câu hỏi chặn: có đủ traffic US để validate không?

Đây là câu hỏi phải trả lời **trước** câu "chọn vendor nào".

| Dữ kiện | Giá trị hiện tại | Nguồn |
|---|---|---|
| Visitor US trong DB | `8` | handoff doc |
| Trong đó đã định danh đúng | `~0` (1 row duy nhất là false-positive) | handoff doc + audit |
| Cỡ mẫu benchmark cần | `N >= 30` ground-truth tester — **đã hoãn chính thức (session 2)** | plan program Phase 4 |
| Traffic VN validate được US graph không | **Không** | `vendor-pixel-benchmark_NOTE_02-08-26.md` |

Chi phí không còn là rào cản, nên câu hỏi không phải "có đáng tiền không" mà là **"đo được kết quả
không"**. Nếu chưa có nguồn traffic US ổn định, mở org mới vẫn cho ra coverage nhưng
**precision không kiểm chứng được** — đúng cái bẫy RB2B đã mắc (8 success, 1 identity, và sai).

Plan này không tự quyết. Nó chỉ từ chối để câu hỏi đó bị bỏ qua.

### Tiêu chí quyết định cho từng provider

Áp dụng cùng một khung, quyết riêng từng cái:

| Tiêu chí | Ngưỡng giữ | Ngưỡng bỏ |
|---|---|---|
| Có doc chính thức xác minh được? | Có | Không → bỏ, không đoán endpoint |
| Host/endpoint phân giải và trả 2xx? | Có | Không → bỏ |
| Tài khoản còn hiệu lực? | Có, hoặc mở được org free mới | Phải trả phí vượt giá trị đo được → hoãn |
| Có đủ traffic đúng loại để validate? | Có | Không → **hoãn**, không bỏ hẳn |
| Đã từng tạo ra identity đúng? | ≥1 ca xác minh được | 0 sau khi hạ tầng đã xanh → bỏ |

Trạng thái hiện tại theo khung này:

<!-- Updated: EXECUTE session 3 (05-08-26) — thêm ipinfo + pdl_ip vào bảng; thêm cột giá -->

Bảng phủ **toàn bộ** provider trả phí trong waterfall, không chỉ 3 person-graph. Giá lấy từ
[api_pricing.py](apps/api/services/api_pricing.py) — lưu ý `price_for()` trả `0.0` khi
`success=False`, nên **gọi trượt luôn miễn phí**; chỉ match mới tính tiền.

| Provider | Giá / match | Doc | Endpoint | Đã tạo identity đúng | Kết luận sơ bộ |
|---|---|---|---|---|---|
| **Leadpipe** | $0 (free trial) | ✅ docs.leadpipe.com | ⚠️ pixel **200**, nhưng API **403 org expired** | ❌ chưa từng chạy | **Giữ — tạo org free mới** (chốt session 2). Chặn ở tài khoản, không phải lỗi code |
| **Capturify** | $0 (free trial) | ❌ không có doc công khai | ❌ DNS không tồn tại | ❌ chưa từng gọi được | **Bỏ**, trừ khi lấy được doc thật |
| **RB2B** | **$0.09** | ✅ có | ✅ 200 | ❌ 8 success → 1 identity, và sai | Giữ nhưng phải đo lại sau khi bug ledger lên PROD. **Đắt nhất bộ, và đang trả tiền cho false-positive** |
| **ipinfo** | $0 (free tier) | ✅ có | ✅ có | ⚠️ **9 lần / 0 thành công** — nhưng số này KHÔNG đáng tin, xem dưới | Đo lại rồi mới quyết |
| **pdl_ip_enrich** | $0.01 | ✅ có | ✅ có | ⚠️ **9 lần / 0 thành công** — cùng lý do | Đo lại rồi mới quyết |
| **Hunter** | $0 (free tier) | ✅ có | ✅ có | chưa đo | Ngoài phạm vi phase này |
| **Apollo** | $0 (free tier) | ✅ có | ✅ có | chưa đo | Ngoài phạm vi phase này |

**Vì sao con số 9/0 của ipinfo + pdl_ip chưa dùng để kết luận được:** trước Phase 2,
`_resolve_ip_company_parallel` ghi "đã thử, thất bại" **kể cả khi provider thiếu key nên chưa từng
được gọi** — nó chỉ kiểm cờ `*_enabled` (mặc định `True`), không kiểm key. Vậy 9 dòng đó có thể là
9 lần *không hề gọi*. Bug đã sửa (H-1, session 3). **Chạy lại `scripts/identity_locked_visitors_audit.sql`
sau khi Phase 2 lên môi trường thật** rồi mới chấm điểm hai provider này.

**Điểm đáng chú ý về chi phí:** trong cả bộ chỉ RB2B ($0.09) và pdl ($0.01) là tốn tiền thật —
và RB2B đang là bên **duy nhất** tạo ra identity, nhưng identity đó sai. Cost-per-**correct**-identity
hiện tại là **∞**. Bốn provider còn lại đều $0, nên giữ/bỏ chúng là quyết định về nhiễu và thời
gian chờ, không phải về tiền.

Lưu ý về RB2B: bug ghi sổ đã sửa ở `dev_nhantc2` nhưng **chưa lên `main` (PROD)**. Nên mọi số
liệu RB2B đo trên PROD hiện giờ vẫn sai. Không kết luận về RB2B trước khi merge — user đã chủ
động hoãn việc merge, nên đây là phụ thuộc cần theo dõi chứ không phải việc tự làm.

### ✅ KẾT LUẬN 05-08-26 — pixel phục vụ được, API bị chặn cứng vì org hết hạn

Test bằng API key thật (user chạy 05-08-26 09:30 UTC):

```
GET  /v1/data?domain=beamlab.nhantown.com  → 403
POST /v1/data/pixels                        → 403
{"error":{"code":"HTTP_ERROR","message":"Organization is expired"}}
```

**Bức tranh cuối cùng — hai mặt tách rời nhau:**

| Mặt | Trạng thái | Ý nghĩa |
|---|---|---|
| Pixel JS phục vụ từ CDN | ✅ **200** | file tĩnh, CDN không kiểm tra trạng thái org |
| API đọc dữ liệu (`GET /v1/data`) | ❌ **403 org expired** | Beam **không đọc được** ai đã nhận diện |
| API tạo pixel (`POST /v1/data/pixels`) | ❌ **403 org expired** | không provisioning được domain mới |

Nghĩa là: pixel vẫn nạp trên site lab, nhưng **dữ liệu không lấy về được**. Leadpipe hiện coi như
**không dùng được** cho Beam, dù thẻ script trông vẫn "chạy".

Điều này cũng giải thích `pixels_total=0` trong handoff doc: khi org hết hạn, endpoint account
trả số liệu không đáng tin — pixel rõ ràng tồn tại và phục vụ được.

**Ba lựa chọn:**

<!-- Updated: Validation Session 2 - chốt lựa chọn 1 (tạo org free mới) -->

| # | Hành động | Kéo theo |
|---|---|---|
| **1** ✅ **ĐÃ CHỌN** | Tạo org free MỚI trên Leadpipe | API key mới + phải tạo lại pixel cho domain → **pixel id đổi** → phải thay thẻ script dán tay trên site lab |
| 2 | ~~Gia hạn org hiện tại~~ | loại: cần biết chi phí, chưa tra được, trong khi token free đã có sẵn |
| 3 | ~~Bỏ Leadpipe khỏi đường coverage~~ | loại: waterfall sẽ chỉ còn RB2B, mà RB2B có bug ghi sổ chưa lên PROD |

**Quyết định (validation session 2): lựa chọn 1 — tạo org free mới.** Hệ quả bắt buộc, không được
bỏ qua: token free mới thuộc org mới, nên pixel id cũ (`3ead3e50-…`) **thành vô dụng**. Phải tạo
pixel mới qua `POST /v1/data/pixels` và **thay thẻ script dán tay** trên
`infra/cloudflare/beam-lab/public/index.html`. Nếu quên bước thay thẻ, pixel cũ vẫn nạp 200 (CDN
không kiểm tra org) nhưng dữ liệu vẫn không về — đúng cái bẫy "trông như đang chạy" hiện tại.

**Không có gì phía Beam cần sửa để "khôi phục" Leadpipe** — code đọc `/v1/data` vốn đúng. Đây
thuần tuý là việc tài khoản phía vendor.

### Bối cảnh kiểm tra pixel (giữ lại làm tham chiếu)

Kiểm tra live trên `beamlab.nhantown.com`:

| Kiểm tra | Kết quả |
|---|---|
| Thẻ script Leadpipe trên site lab | **CÓ** — `leadpipe.aws53.cloud/p/3ead3e50-…d708.js` |
| URL đó tải được? | **HTTP 200**, 1154 bytes (handoff doc 02-08 báo 404) |
| Nội dung có phải pixel thật? | **Có** — `"domain":"beamlab.nhantown.com"`, `org_slug":"to-s-workspace"` |
| SDK chain `cdn.pixel.leadpipe.com/pixels/…/p.js` | **HTTP 200**, 15795 bytes |

**Hệ quả — ba giả định trong handoff doc không còn đúng:**

<!-- Updated: Validation Session 2 - mục 3 đã lỗi thời, API ĐÃ test lại -->

1. ~~URL dựng từ UUID là sai~~ → **SAI**. Pattern `leadpipe.aws53.cloud/p/<uuid>.js` **đúng**,
   trả pixel thật. Không cần sửa `tracker.js:624`.
2. ~~`pixels_total=0, pixels_active=0`~~ → có ít nhất 1 pixel đã đăng ký cho
   `beamlab.nhantown.com`.
3. ~~Account expired chặn mọi thứ~~ → **đúng một nửa.** Phía pixel không bị chặn (CDN phục vụ
   file tĩnh); phía API thì bị chặn hoàn toàn — đã test lại 05-08-26 với API key thật, cả
   `GET /v1/data` lẫn `POST /v1/data/pixels` đều `403 "Organization is expired"` (§KẾT LUẬN ở trên).

Nghĩa là handoff doc sai ở phần pixel, đúng ở phần org expired. **Trạng thái pixel tốt hơn tài
liệu; trạng thái API thì không.**

### 🔴 Mắt xích thiếu: Beam KHÔNG có code đăng ký domain / tạo pixel

Docs Leadpipe ([create-a-pixel-for-a-domain](https://docs.leadpipe.com/api-reference/pixels/create-a-pixel-for-a-domain)):

```
POST https://api.aws53.cloud/v1/data/pixels
Header: X-API-Key: sk_...
Body:   { "domain": "www.example.com", "name": "Example Pixel",
          "excludedPaths": [...] | "includedPaths": [...] }   # loại trừ nhau, tối đa 50
→ 201: { id (UUID), domain, name, status, code, createdAt }
```

`code` chính là **snippet cài đặt**. `id` là UUID — và đây là UUID xuất hiện trong URL
`leadpipe.aws53.cloud/p/<id>.js`, khớp với pixel đang chạy trên site lab. Nghĩa là cách dựng URL
trong `tracker.js` và `code` chính thức **không mâu thuẫn** — `code` bọc đúng URL đó.

**Grep toàn repo: không có bất kỳ code nào gọi `POST /v1/data/pixels`.** Duy nhất một lần nhắc
tới chuỗi đó là dòng ghi kết quả test hỏng trong handoff doc.

Hệ quả — đây là khoảng trống chặn multi-tenant:

| Bước onboard một site khách | Beam có làm không? |
|---|---|
| Đăng ký domain khách với Leadpipe (tạo pixel) | ❌ **KHÔNG có code** |
| Lấy `id`/`code` trả về, lưu theo site | ❌ không có chỗ lưu (`Site` thiếu cột) |
| Nhúng pixel vào snippet của site đó | ⚠️ có cơ chế `data-stack`, nhưng chỉ đọc 1 biến toàn cục |

Vì vậy `leadpipe_default_pixel_id` (một UUID dùng chung) chính là **cách chữa cháy cho việc thiếu
provisioning** — và nó sai về bản chất, vì pixel gắn cứng với một domain. Dùng pixel của
`beamlab.nhantown.com` cho site khách khác thì Leadpipe sẽ không nhận diện gì cho domain đó.

<!-- Updated: Validation Session 2 - giả thuyết "403 do sai method" đã bị bác bỏ -->

~~**Lưu ý về test cũ:** 403 có thể do sai method (GET thay vì POST)~~ — **đã bác bỏ 05-08-26.**
Test lại bằng đúng **POST** vẫn trả `403 "Organization is expired"`. 403 là gate ở tầng tài khoản,
không liên quan method. Không cần test thêm về việc này.

### Vấn đề còn lại: pixel dán tay, Beam không quản lý

Thẻ tracker Beam trên site lab:

```html
<script src=".../pixel/tracker.js" data-site="site_16c46453546f" data-api="..." defer>
```

**Không có `data-stack` nào.** Nghĩa là pixel Leadpipe được dán thủ công vào HTML của site lab,
**không đi qua cơ chế stacking của Beam**. Với site lab thì được; với site khách thật thì cơ chế
`data-stack` vẫn chưa từng được chứng minh chạy end-to-end.

Hai đường đi hợp lệ (B đã bị loại):

<!-- Updated: Validation Session 2 - chốt đường A; B gỡ khỏi diện lựa chọn -->

| Đường | Ưu | Nhược | Dùng khi |
|---|---|---|---|
| **A. Dán tay từng site** ✅ **ĐÃ CHỌN** | Đơn giản, đang chạy trên lab | Không scale; mỗi site sửa HTML thủ công + tạo pixel thủ công trên dashboard | 1–2 site, giai đoạn thử nghiệm |
| ~~B. `data-stack` + pixel-id toàn cục~~ | — | **LOẠI — sai về bản chất.** Pixel gắn cứng 1 domain; `sites.py:284` đã ghi rõ "global pixel id only, `Site` has no leadpipe_pixel_id column". Dùng chung 1 UUID cho site khác domain → Leadpipe không nhận diện gì | **Không dùng** |
| **C. Provisioning tự động** | Đúng mô hình multi-tenant | Phải viết: gọi `POST /v1/data/pixels` khi tạo site + cột lưu `pixel_id` theo site (**cần migration** — vi phạm ràng buộc hiện tại) | Khi có khách thật, plan sau |

**Quyết định (validation session 2): giữ A.** Chỉ đầu tư vào **C** sau khi đường ống đã chứng minh
chạy end-to-end trên một domain — viết provisioning cho một đường ống chưa chứng minh được là đặt
cược sai chỗ. **B không còn là lựa chọn hợp lệ ở bất kỳ chỗ nào trong plan này.**

Vì giữ A: **không bật `data-stack`** trên site lab. Nếu sau này bật, phải **gỡ thẻ dán tay trước**,
nếu không pixel nạp 2 lần.

### Trình tự còn lại

```
1. Tạo org free mới → lấy API key mới → POST /v1/data/pixels tạo pixel cho beamlab.nhantown.com
2. Thay thẻ script dán tay bằng pixel id mới (id cũ 3ead3e50-… thuộc org cũ, vô dụng)
3. GET /v1/data với key mới → phải 200 VÀ có dữ liệu visitor thật chảy về
4. Chỉ khi ③ xanh mới cân nhắc đường C (provisioning + cột pixel-id theo site) — plan riêng
5. Chỉ khi ①–③ xanh mới bật auto-identify
```

## Related Code Files

<!-- Updated: Validation Session 2 - tracker.js không cần sửa; Capturify chỉ vô hiệu, không gỡ -->

- Modify: `infra/cloudflare/beam-lab/public/index.html` — **thay pixel id trong thẻ script dán
  tay** bằng id của org mới (đây là thay đổi code duy nhất bắt buộc của phase này)
- Update: `docs/identity-us-current-handoff.md` — ghi quyết định từng provider + lý do, sửa các
  khẳng định lỗi thời (404 pixel, `pixels_active=0`)
- **KHÔNG sửa** `apps/pixel/src/tracker.js` — pattern `vendorUrls.leadpipe` đã verify đúng, chỉ
  dùng khi bật `data-stack` (đường B, đã loại)
- **KHÔNG sửa** `apps/api/routers/sites.py` — install code vẫn dạng UUID, đường A không đi qua đây
- **KHÔNG gỡ** Capturify khỏi `vendorUrls`/waterfall/`identity_classification.py` — Phase 1 đã vô
  hiệu bằng flag là đủ (quyết định session 2)

## Implementation Steps

<!-- Updated: Validation Session 2 - org mới đã chốt; bỏ nhánh B; Capturify không liên hệ vendor -->

1. **Tạo org free mới trên Leadpipe** (quyết định session 2 — không gia hạn, không bỏ). Lấy API
   key mới, rồi chạy đúng 2 lệnh này để xác nhận org sống:
   ```bash
   curl -s -w "\n%{http_code}\n" -X POST -H "X-API-Key: $NEW_KEY" \
     -H "Content-Type: application/json" \
     -d '{"domain":"beamlab.nhantown.com","name":"Beam Lab"}' \
     "https://api.aws53.cloud/v1/data/pixels"
   curl -s -w "\n%{http_code}\n" -H "X-API-Key: $NEW_KEY" \
     "https://api.aws53.cloud/v1/data?domain=beamlab.nhantown.com"
   ```
   Thứ tự này có chủ đích: phải tạo pixel **trước** thì `/v1/data` mới có gì để trả.
2. **Thay thẻ script dán tay** trên `infra/cloudflare/beam-lab/public/index.html` bằng `id` lấy từ
   response `201` ở bước 1. Pixel id cũ `3ead3e50-…` thuộc org cũ → vô dụng. **Bỏ qua bước này thì
   bước 3 chắc chắn không có dữ liệu**, dù pixel cũ vẫn nạp 200.
3. Xác nhận `/v1/data` trả **200 kèm dữ liệu visitor thật** (không phải mảng rỗng). Ghi kết quả
   vào handoff doc.
4. **Ghi nhận traffic US là đã hoãn chính thức.** Chưa có nguồn tester cam kết → **precision
   benchmark không làm được**. Coverage đo được, precision thì không. Không giả vờ ngược lại.
5. **Giữ đường A (dán tay).** Không bật `data-stack`, không viết provisioning. Đường B đã loại;
   đường C đẩy sang plan sau (cần migration, vi phạm ràng buộc hiện tại).
6. **Capturify: không làm gì thêm.** Phase 1 đã vô hiệu bằng flag. Không liên hệ vendor, không gỡ
   code (quyết định session 2 — việc liên hệ là hành động ngoài code không có thời hạn, treo plan).
7. Ghi quyết định từng provider + lý do vào handoff doc, **và sửa các khẳng định đã lỗi thời**
   trong đó (404 pixel, `pixels_active=0`).
8. Chỉ bật `auto_identify_enabled` trên lab sau khi bước 3 xanh, và có backup trước.

## Success Criteria

<!-- Updated: Validation Session 2 - tiêu chí bám org mới; bỏ nhánh B -->

- [ ] Org free mới đã tạo; `POST /v1/data/pixels` trả **201** kèm `id` mới
- [ ] Thẻ script trên `infra/cloudflare/beam-lab/public/index.html` đã thay sang pixel id mới;
      pixel id cũ `3ead3e50-…` không còn xuất hiện ở đâu
- [ ] `GET /v1/data` trả **200 kèm dữ liệu visitor thật** (không phải mảng rỗng); kết quả ghi vào
      handoff doc
- [ ] Mỗi provider có quyết định giữ/bỏ/hoãn kèm lý do (Leadpipe: giữ, org mới; Capturify: vô hiệu,
      không liên hệ; RB2B: giữ, đo lại sau khi bug ledger lên PROD)
- [ ] Đường A được giữ: **không** bật `data-stack`, **không** viết provisioning
- [ ] Không có site nào nạp pixel Leadpipe 2 lần
- [ ] Handoff doc đã sửa các khẳng định lỗi thời (404, `pixels_active=0`)
- [ ] Hạn chế "chưa đo được precision vì thiếu traffic US" được ghi rõ, không lấp liếm
- [ ] `auto_identify_enabled` chỉ bật sau khi `/v1/data` xanh **và** có backup

## Risk Assessment

<!-- Updated: Validation Session 2 - 2 rủi ro lỗi thời thay bằng rủi ro thật của đường org mới -->

| Rủi ro | Mitigation |
|---|---|
| **Tạo org mới xong quên thay thẻ script** → pixel cũ vẫn nạp 200, tưởng đang chạy, nhưng `/v1/data` rỗng vĩnh viễn | Bước 2 là bước bắt buộc riêng, và Success Criteria kiểm tra pixel id cũ không còn tồn tại ở đâu. Đây là cái bẫy đã mắc một lần |
| Org mới xanh nhưng vẫn không có identity nào vì thiếu traffic US | Đã ghi nhận là hạn chế có ý thức (bước 4). Coverage đo được, precision thì không — không suy diễn từ coverage ra chất lượng |
| Org free mới cũng hết hạn sau một thời gian, lặp lại đúng tình trạng hiện tại | Phase 2 chính là lớp phòng thủ: outage sẽ không còn khoá oan visitor 30 ngày và sẽ hiện ra trong `api_usage_logs` thay vì im lặng |
| Bật auto-identify sớm → đốt credit vào traffic sai | Ràng buộc cứng: chỉ bật sau khi **API** `/v1/data` trả dữ liệu thật (không phải chỉ pixel 200); giữ nguyên yêu cầu backup từ handoff doc |
| Quyết định vô hiệu Capturify rồi sau lại cần | Phase 1 vô hiệu bằng flag chứ không xoá; phần parse vẫn còn nguyên trong repo, bật lại chỉ cần đổi flag + base URL |
