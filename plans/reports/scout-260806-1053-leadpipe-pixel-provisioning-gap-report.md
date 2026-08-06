# Scout Report — Leadpipe pixel provisioning gap (Phase 3 review)

**Ngày:** 06-08-26 · **Branch:** `dev_nhantc2` · **Phạm vi:** đọc-only, không sửa code
**Liên quan:** `plans/260805-1543-identity-coverage-recovery/phase-03-vendor-decision-and-leadpipe-restoration.md`

---

## TL;DR

Hai giả thuyết của user: **(1) ĐÚNG — xác nhận bằng code**, **(2) đúng mục tiêu nhưng sai chỗ đặt**.
Và có **3 vấn đề nặng hơn** mà cả user lẫn Phase 3 chưa nêu — trong đó 1 cái là đường rò dữ liệu
cross-tenant đang sống trong code.

---

## 1. Xác minh 2 giả thuyết của user

### (1) "KH add site nhưng thiếu bước Create a pixel for a domain" → **ĐÚNG**

| Bằng chứng | Vị trí |
|---|---|
| `create_site` chỉ INSERT DB, zero vendor call | [sites.py:50-129](apps/api/routers/sites.py#L50-L129) |
| Grep toàn repo: **0 caller** của `POST /v1/data/pixels` | — |
| `Site` không có cột `leadpipe_pixel_id` | [site.py:11-26](apps/api/models/site.py#L11-L26) |
| Snippet phát 1 UUID toàn cục cho MỌI site | [sites.py:284-289](apps/api/routers/sites.py#L284-L289) |

### (2) "Check List all pixels trước khi get data" → **đúng mục tiêu, sai vị trí**

Đúng: hiện tại không có gate nào — [leadpipe.py:45-49](apps/api/services/identity_providers/leadpipe.py#L45-L49)
gọi thẳng `GET /v1/data?domain=…`.

Nhưng đặt check ở **resolve-time là sai**:
- `GET /v1/data/pixels` **không có filter domain, không có pagination** (docs) → trả *toàn bộ*
  pixel của org, mỗi visitor một lần.
- Đúng chỗ: check **lúc provisioning**, lưu `pixel_id` + `status` vào `Site`; resolve-time chỉ đọc cột local.
- `GET /v1/data/pixels` để dành cho reconcile định kỳ / sửa lệch, có cache.

**Bonus từ docs:** `POST /v1/data/pixels` trả **409 "Pixel already exists for domain"** → POST đã
tự idempotent. Không cần pre-check GET trong đường tạo: `POST → 201 (lưu id)` hoặc `409 → GET list
→ tìm domain → lưu id`.

---

## 2. Ba vấn đề nặng hơn, chưa ai nêu

### 2a. Global pixel id không phải "tạm được" — nó là **guaranteed-zero**

Docs xác nhận pixel ↔ domain là quan hệ **1-1 cứng** (409 khi trùng domain; `domain` là field bắt
buộc lúc tạo). [sites.py:288](apps/api/routers/sites.py#L288) phát pixel id của
`beamlab.nhantown.com` cho mọi site khách. Khách ở `customer.com` nạp pixel của domain khác →
`GET /v1/data?domain=customer.com` **rỗng vĩnh viễn**.

Phase 3 mô tả đường B là "không scale". Docs cho thấy nặng hơn: **chắc chắn 0 kết quả**.
Và Phase 3 đã *loại* đường B — nhưng **code vẫn đang chạy đường B**. Đây là mâu thuẫn plan↔code
hiện tại, không phải việc tương lai.

### 2b. "Không có pixel" đang bị map thành "no-match" → khoá oan visitor 30 ngày

Đường đi hiện tại:
```
GET /v1/data?domain=X → 200 + data:[] → return None (leadpipe.py:71-73)
  → resolver ghi "đã thử, thất bại" → was_recently_attempted khoá 30 ngày
     (identity_resolver.py:130-134)
```
Đúng **đúng loại bug** Phase 2 vừa sửa (outage ≠ no-match), nhưng đây là **trạng thái thứ ba:
not-configured**. Cần outcome riêng, **không ghi ResolutionLog**, y hệt cách Phase 2 xử outage.

### 2c. Fallback account-wide = đường rò dữ liệu cross-tenant

[leadpipe.py:40-44](apps/api/services/identity_providers/leadpipe.py#L40-L44): không biết site
domain → **bỏ param `domain`** → query feed toàn org. Beam dùng **một** org key chung
([identity_resolver.py:617](apps/api/services/identity_resolver.py#L617)) cho mọi khách → visitor
site A có thể match record thuộc domain site B.

Hiện chỉ được chặn bởi IP-equality ([leadpipe.py:92-94](apps/api/services/identity_providers/leadpipe.py#L92-L94)) —
đó là **ngẫu nhiên, không phải thiết kế**. Nguyên tắc đúng: **không có domain → không gọi**.

---

## 3. Hai điểm nhỏ hơn nhưng vẫn chặn

| # | Vấn đề | Bằng chứng |
|---|---|---|
| 3a | Gate phải là **exists AND active**, không chỉ exists | List response có `status` + `pausedReason` → pixel pause thì không có data; check thiếu status vẫn ra đúng triệu chứng |
| 3b | **BYOK leadpipe là no-op** | `schemas/api_keys.py:12` cho user nhập key riêng, nhưng resolver chỉ đọc `settings.leadpipe_api_key` → key khách không bao giờ được dùng; mọi domain khách chung 1 org + chung credit pool của Beam |

---

## 4. Đối chiếu với quyết định đã chốt của Phase 3

Phase 3 (validation session 2) đã chốt: **giữ đường A (dán tay)**, loại B, đẩy C (provisioning) sang
plan sau. Câu hỏi của user thực chất là **mở lại quyết định đó**.

| Lý do Phase 3 hoãn C | Còn đứng vững? |
|---|---|
| "Đừng viết provisioning cho đường ống chưa chứng minh end-to-end" | ✅ Còn — org đang **403 expired**, `POST /v1/data/pixels` không gọi được → viết bây giờ là code không test được |
| Cần migration (vi phạm ràng buộc hiện tại) | ✅ Còn |

| Bằng chứng mới nghiêng về đẩy C sớm hơn | |
|---|---|
| Docs 409 chứng minh B = 0 kết quả, không phải "kém scale" | Mới |
| Code vẫn chạy B dù plan đã loại B | Mới — đây là bug hiện tại, không phải nợ tương lai |

**Kết luận:** trình tự Phase 3 bước 1-3 (org mới → tạo pixel → `/v1/data` xanh) vẫn là **điều kiện
tiên quyết**, không bỏ qua được. Nhưng 2b + 2c **không phụ thuộc vào org** và nên sửa trước.

---

## 5. Đề xuất thứ tự (không tự quyết — user chốt)

**Làm ngay, không cần org mới:**
1. Tách outcome `provider_not_configured` khỏi no-match (không ghi ResolutionLog, không khoá 30 ngày)
2. Bỏ fallback account-wide: không có site domain → skip provider, không gọi API

**Sau khi org mới xanh (Phase 3 bước 1-3):**
3. Migration: `Site.leadpipe_pixel_id` + `Site.leadpipe_pixel_status`
4. Gọi `POST /v1/data/pixels` (409 → GET list → lấy id), lưu vào Site
5. Snippet đọc cột per-site thay vì `leadpipe_default_pixel_id`
6. Resolve-time gate: đọc cột local (exists AND active), không gọi list

---

---

## 6. Vòng validate lần 2 (06-08-26) — kết quả

### 6a. MỚI: có **hai** đường phát snippet, chỉ một đường có `data-stack`

| Đường | Nguồn | Có `data-stack-leadpipe`? |
|---|---|---|
| Dashboard / manual | [sites.py:317-321](apps/api/routers/sites.py#L317-L321) ← [pixel-install-guide.tsx:78](apps/web/src/components/pixel-install-guide.tsx#L78) | ✅ có |
| **Plugin WordPress** | [wordpress_plugin_generator.py:22](apps/api/services/wordpress_plugin_generator.py#L22) — snippet **hardcode** | ❌ **không** |

KH cài bằng plugin WP **không bao giờ** nạp pixel Leadpipe, kể cả khi mọi thứ khác đúng.
Mọi giải pháp kiểu "nhét id vào attribute" đều phải sửa **cả hai** emitter.

*(Ngoài phạm vi, ghi để không quên: snippet WP cũng thiếu `data-consent` → site WP không có consent
gating. Không sửa trong phạm vi này.)*

### 6b. Xác nhận lại 2b bằng code — và tìm được cách sửa rẻ

Taxonomy Phase 2 có đúng 3 outcome ([identity_resolver.py:1188-1197](apps/api/services/identity_resolver.py#L1188-L1197)):
`match` / `no_match` / `provider_unavailable`. `200 + data:[]` → `unavailable_detail is None` →
rơi vào `no_match` → ghi ResolutionLog → khoá 30 ngày. **Xác nhận.**

Nhưng **không cần thêm outcome thứ 4**: đường `attempted=False` đã có sẵn
([identity_resolver.py:631-632](apps/api/services/identity_resolver.py#L631-L632) +
[:702-703](apps/api/services/identity_resolver.py#L702-L703)) — nó bỏ qua ledger hoàn toàn.
Chỉ cần một `ProviderNotConfiguredError` (mirror của `ProviderUnavailableError` trong `base.py`)
để `_fetch` trả `attempted=False`. **Không migration, không outcome mới.**

### 6c. Xác nhận lại 2c

[leadpipe.py:41-44](apps/api/services/identity_providers/leadpipe.py#L41-L44): `params = {}`,
chỉ set `domain` khi có. Không có domain → query feed toàn org. **Xác nhận.**

### 6d. Không đọc `.env`

Bị privacy hook chặn. Không cần: [phase-01_REPORT_02-08-26.md:9](process/features/visitors-identity/active/identity-coverage-pixel-fppro_02-08-26/phase-01_REPORT_02-08-26.md#L9)
đã ghi `LEADPIPE_API_KEY` / `LEADPIPE_DEFAULT_PIXEL_ID`: **SET**.

---

## 7. Flow đề xuất — 3 tầng, chỉ tầng 0 làm ngay

### Tầng 0 — làm ngay, KHÔNG cần org sống, KHÔNG migration

| # | Việc | File |
|---|---|---|
| 1 | Bỏ fallback account-wide: không có site domain → **không gọi** | [leadpipe.py:41-44](apps/api/services/identity_providers/leadpipe.py#L41-L44) |
| 2 | Thêm `ProviderNotConfiguredError` → `attempted=False` → không ghi ledger, không khoá 30 ngày | `base.py` + [identity_resolver.py:635-681](apps/api/services/identity_resolver.py#L635-L681) |
| 3 | Chỉ phát `data-stack-leadpipe` cho site **đúng chủ** pixel đó (thêm env `LEADPIPE_DEFAULT_PIXEL_DOMAIN`, so với host của `site.url`) | [sites.py:288](apps/api/routers/sites.py#L288) |

Việc 3 gỡ được mâu thuẫn plan↔code: Phase 3 đã loại đường B nhưng code vẫn chạy B cho mọi site.

### Tầng 1 — sau khi org mới xanh (Phase 3 bước 1-3)

4. Migration: `Site.leadpipe_pixel_id`, `Site.leadpipe_pixel_status`
5. **Provision lazy trong `get_pixel_snippet`** — chưa có id → `POST /v1/data/pixels`
   (409 → `GET /v1/data/pixels` → lấy id) → lưu cột → phát vào snippet.
   Leadpipe chết → bỏ qua vendor, snippet vẫn phát bình thường (không fail endpoint)
6. Resolve-time gate: đọc cột local (`exists AND active`), **không** gọi list API

**Vì sao lazy tại `get_pixel_snippet`, không phải `create_site` / `verify-pixel`:**
- `verify-pixel` chạy **sau khi KH đã dán** → id sinh ra không vào được HTML. Loại.
- `create_site` đốt slot pixel cho site KH tạo rồi bỏ, không bao giờ xin snippet.
- `get_pixel_snippet` là điểm **duy nhất** biết chắc KH sắp dán; 409 làm nó tự idempotent.

### Tầng 2 — HOÃN, chỉ làm khi có nhu cầu thật

7. Endpoint runtime-config: `tracker.js` hỏi Beam lấy stack config theo `data-site` thay vì đọc
   attribute. Đây là thứ duy nhất fix được **cả hai**: plugin WP (6a) và bẫy "dán một lần"
   (đổi pixel id không cần KH dán lại). Đắt hơn: +1 request/pageload + endpoint mới.
   **Chưa có KH WordPress thật → chưa làm.**

**Hạn chế có ý thức của tầng 0+1:** KH cài bằng plugin WordPress vẫn **không** có Leadpipe cho tới
tầng 2. Ghi rõ, không lấp liếm.

---

## 8. Kết quả curl thật (06-08-26 04:15 UTC, key Beam đang dùng)

### 8a. 🔴 ROOT CAUSE THẬT: pixel và API key nằm ở **hai org khác nhau**

| Nguồn | Org |
|---|---|
| `GET /v1/data/account` (key Beam đang dùng) | name: **"Beam ai"**, status `expired`, **`pixels.total: 0`** |
| Pixel JS đang chạy trên lab (`leadpipe.aws53.cloud/p/3ead3e50-f6c0-…`) | `org_slug: "to-s-workspace"`, org id `b63c5727-…` |

Hai nguồn độc lập, cùng một kết luận: **pixel ghi dữ liệu vào org `to-s-workspace`, Beam đọc từ org
`Beam ai`.** Org `Beam ai` chưa từng có một pixel nào.

**Hệ quả:** kể cả org hết hạn có được gia hạn, `GET /v1/data` vẫn trả rỗng **vĩnh viễn** — vì
không có pixel nào ghi vào org đó. 403-expired là blocker **thứ hai**, không phải thứ nhất.

### 8b. Phase 3 chẩn đoán sai một chỗ

[phase-03:131-132](plans/260805-1543-identity-coverage-recovery/phase-03-vendor-decision-and-leadpipe-restoration.md#L131-L132)
viết: *"khi org hết hạn, endpoint account trả số liệu không đáng tin — pixel rõ ràng tồn tại"*.

**Sai.** `/v1/data/account` trả **HTTP 200** ngay cả khi org expired (endpoint duy nhất còn sống).
`pixels.total: 0` là **số thật**. Pixel tồn tại — nhưng ở org khác.

Trình tự Phase 3 bước 1-2 (tạo org mới → tạo pixel → thay thẻ script) vô tình vẫn **đúng**, vì nó
ép pixel và key về cùng một org. Nhưng chẩn đoán sai làm lớp bug này vô hình và sẽ tái phát.

### 8c. `/v1/data/account` là health-gate rẻ — endpoint duy nhất sống khi expired

| Lệnh | HTTP | Body |
|---|---|---|
| `GET /v1/data/account` | **200** | `healthy:false`, `organization.status:"expired"`, `credits{used:0, limit:500, remaining:500}`, `pixels{total:0,active:0,paused:0}` |
| `POST /v1/data/pixels` | 403 | `"Organization is expired"` |
| `GET /v1/data/pixels` | 403 | ″ |
| `GET /v1/data?domain=<không có pixel>` | 403 | ″ |
| `GET /v1/data?domain=beamlab.nhantown.com` | 403 | ″ |
| `GET /v1/data` (không param) | 403 | ″ |
| `GET /v1/data/account` **key rác** | **401** | `"Invalid API key"` |

Ba điều dùng được ngay:
1. **Preflight 1 call** thay vì phát hiện 403 ở từng visitor: `healthy` + `organization.status` +
   `pixels.total` cho biết provider dùng được hay không, cache được.
2. `pixels.total == 0` phát hiện được **đúng bug 8a** — key không có pixel nào — mà không cần
   `GET /v1/data/pixels` (endpoint này chết khi expired, account thì không).
3. **401 ≠ 403** phân biệt được "key sai" với "org hết hạn" → thông báo vận hành khác nhau.
   Code hiện gộp cả hai vào `ProviderUnavailableError`
   ([leadpipe.py:61-64](apps/api/services/identity_providers/leadpipe.py#L61-L64)) — đúng về
   hành vi khoá, nhưng mất thông tin chẩn đoán.

### 8d. Credit chưa tiêu đồng nào

`credits: used 0 / limit 500`. Khớp với audit Phase 2 (`leadpipe`: 0 dòng `resolution_logs`).
Org expired là hết hạn **theo thời gian**, không phải cạn credit. Free tier = 500 credit.

### 8e. CDN pixel có validate id

Gõ một UUID bịa → `HTTP 404` + `// Pixel not found`. Nghĩa là URL pixel **có** kiểm tra tồn tại
(khác với giả định "CDN phục vụ file tĩnh không kiểm gì" ở Phase 3). Nhưng chỉ kiểm **theo id**,
không theo domain, và không cho biết id thuộc org nào — nên nó **không** thay được gate 8c.

### 8f. Câu hỏi chưa trả lời được bằng key này

5-vs-6 (domain không pixel vs có pixel chưa traffic), chuỗi `status`, body 409 — cả ba đều bị
403 chặn trước khi tới logic. **Cần key của org `to-s-workspace`** (org đang thật sự sở hữu pixel
lab) để chạy lại. Nếu org đó còn sống, nó trả lời được cả ba trong một lượt.

---

## 9. Probe org `To's workspace` (key thứ 2, 06-08-26 04:30 UTC) — 3 câu treo đã có đáp án

Org này **khoẻ** (`status: trial`, `healthy: true`, 0/500 credit) và **đúng là chủ pixel lab**:

```
GET /v1/data/pixels → 200
[{ id: "3ead3e50-f6c0-4e81-b944-ae9ba86dd708", domain: "beamlab.nhantown.com",
   name: "beamlab", status: "active", pausedReason: null, createdAt: "2026-08-05" }]
```

### 9a. 🔴 Câu quyết định kiến trúc: `/v1/data` **KHÔNG** phân biệt được

| Query | HTTP | Body |
|---|---|---|
| `?domain=khong-ton-tai-abc.com` (**không** pixel) | 200 | `{"data":[],"meta":{"total":0,...}}` |
| `?domain=beamlab.nhantown.com` (**có** pixel active) | 200 | `{"data":[],"meta":{"total":0,...}}` |
| `?domain=…&timeframe=all` | 200 | ″ |
| không param (account-wide) | 200 | ″ |

**Giống hệt nhau.** → Không có đường rẻ. **Gate pixel là bắt buộc**: chỉ `/v1/data/pixels`
phân biệt được "chưa cài" với "cài rồi nhưng vắng khách".

### 9b. `status` và body 409

- `status: "active"` (chữ thường); có `pausedReason` khi pause
- **409 KHÔNG trả id cũ**: `{"error":{"code":"HTTP_ERROR","message":"Pixel already exists for this domain"}}`
  → provisioning phải `POST → 409 → GET /v1/data/pixels → khớp domain → lấy id`. Không tắt được bước GET.

### 9c. Pixel active 1 ngày, 0 identification

Org sạch: `credits.used: 0`, mọi query đều rỗng kể cả `timeframe=all`. Chưa phân biệt được là
**chưa có traffic**, **traffic không phải US**, hay **Leadpipe chưa match**. Cần traffic thật rồi đo lại.

---

## 10. Đã thực hiện — tầng 0 (06-08-26)

| # | Thay đổi | File |
|---|---|---|
| 1 | `ProviderNotConfiguredError` — "chưa bao giờ gọi được cho site này", tách khỏi `ProviderUnavailableError` | [base.py](apps/api/services/identity_providers/base.py) |
| 2 | `_fetch` map lỗi đó → `attempted=False` → **không** ghi `ResolutionLog`, **không** khoá 30 ngày, **không** tốn budget (cùng đường với "thiếu API key") | [identity_resolver.py](apps/api/services/identity_resolver.py) |
| 3 | `_leadpipe_active_domains()` — registry pixel, cache theo instance + Redis (TTL 1h). Gate `status == "active"`, không chỉ tồn tại. Registry đọc lỗi → `ProviderUnavailableError` (outage vẫn hiện, không âm thầm tắt Leadpipe cả org) | [leadpipe.py](apps/api/services/identity_providers/leadpipe.py) |
| 4 | Bỏ fallback account-wide: không có site domain → raise, **không** query feed toàn org | [leadpipe.py](apps/api/services/identity_providers/leadpipe.py) |
| 5 | ~~`leadpipe_default_pixel_domain` + gate host-equality~~ — **đã bị tầng 1 thay thế hoàn toàn** (xem §11); `leadpipe_default_pixel_id` gỡ khỏi `Settings` | [config.py](apps/api/config.py), [sites.py](apps/api/routers/sites.py) |

**Test:** `1541 passed`. Thêm `TestPixelRegistryGate` (4 case: không pixel / pixel paused /
site không domain / registry 403) + `test_pixel_snippet_omits_leadpipe_for_a_different_domain`.

**Pre-existing, KHÔNG do thay đổi này** (xác minh bằng `git stash` chạy đối chứng):
`test_agent_company_resolution.py` 2 failed, `test_content_company.py` 8 errors, và 3 file không
collect được vì thiếu dev-dep (`fakeredis`).

**Chưa làm (có ý thức):** preflight `/v1/data/account`. Registry `/v1/data/pixels` đã bao cả hai
việc (org chết → 403 → outage; không có pixel → gate), nên thêm call thứ hai là thừa.

---

## 11. Đã thực hiện — tầng 1: pixel per-site (06-08-26)

Thay hẳn mô hình "một pixel id toàn cục" bằng "mỗi site một pixel của riêng nó".

| # | Thay đổi | File |
|---|---|---|
| 1 | Cột `Site.leadpipe_pixel_id` (String(64), nullable). Chỉ **một** cột — `status` thật do registry ở resolve-time lo (§10.3), lưu thêm chỉ tạo ra nguồn lệch | [site.py](apps/api/models/site.py) |
| 2 | Migration `b4c9a71e35d8` (chain off `a7d419e6c052`). Additive, không index, không backfill | [b4c9a71e35d8](apps/api/migrations/versions/b4c9a71e35d8_add_site_leadpipe_pixel_id.py) |
| 3 | `ensure_pixel_for_domain()` — `POST` → 201 lấy id; **409 → `GET /v1/data/pixels` → khớp domain** (409 không trả id, xem §9b). Không bao giờ raise: lỗi → `None` | [leadpipe_pixels.py](apps/api/services/leadpipe_pixels.py) |
| 4 | Provision **lazy trong `get_pixel_snippet`** — chưa có id thì tạo, lưu, phát. Leadpipe chết → snippet vẫn ra, chỉ thiếu tag vendor | [sites.py](apps/api/routers/sites.py) |
| 5 | Gỡ `leadpipe_default_pixel_id` + `leadpipe_default_pixel_domain` khỏi `Settings`. `extra: "ignore"` nên `.env` còn dòng cũ vẫn khởi động bình thường | [config.py](apps/api/config.py) |

**Mock mode:** `MOCK_EXTERNAL_APIS=true` → id giả tất định theo domain (`mock-pixel-<domain>`), hai
lần gọi cùng domain trả cùng kết quả, đúng như cặp 201/409 thật.

**Vì sao lazy tại `get_pixel_snippet`, không phải `create_site`:** đó là điểm duy nhất biết chắc KH
sắp dán snippet — đủ sớm để id kịp vào HTML, đủ muộn để không đốt slot pixel cho site tạo rồi bỏ.
`verify-pixel` thì quá muộn (chạy sau khi đã dán).

**Test:** `1550 passed`. Mới: `test_leadpipe_pixel_provisioning.py` (8 case — 201 / 409→list /
409-nhưng-vắng-trong-list / 403 / lỗi mạng / thiếu key / provider tắt / mock mode) và 4 case snippet
(dùng id đã lưu / provision lần đầu rồi lưu / Leadpipe chết vẫn ra snippet / không vendor nào).

**Migration validate:** offline `--sql` sạch cả hai chiều (`upgrade a7d419e6c052:head` /
`downgrade head:a7d419e6c052`), `alembic heads` = `b4c9a71e35d8`, một head, không nhánh.

**Known-gap:** live round-trip trên Postgres dùng-một-lần **chưa chạy** — Docker daemon down trong
môi trường này. Cùng loại gap với các migration trước. Một `ALTER TABLE ADD COLUMN` nullable là dạng
migration ít rủi ro nhất, nhưng vẫn phải chạy round-trip trước khi apply lên PROD.

### Giả định cần anh xác nhận

`LEADPIPE_API_KEY` hiện trỏ org nào thì **pixel của mọi KH sẽ được tạo trong org đó**. Với key
`sk_8f38…` là org `To's workspace` — org cá nhân, đang chứa pixel test beamlab. Code không phụ
thuộc org (đọc thẳng `settings.leadpipe_api_key`), nên đổi org chỉ là đổi env. Nhưng nếu định tách
org riêng cho production thì đổi **trước** khi có KH thật, vì pixel đã tạo không di chuyển được
giữa các org.

---

## 12. Tạo org cho KH qua API — **KHÔNG làm được**, và đây là bằng chứng

Yêu cầu: "khi KH add site thì tạo org cho KH qua API luôn". Đã probe hết mọi đường, kết luận là không.

### 12a. Endpoint có tồn tại, nhưng thuộc mặt phẳng auth khác

`POST /v1/organizations` **có thật** (không nằm trong 40 endpoint của `llms.txt` — undocumented).
Nó validate body trước, nên lộ schema:

```
POST /v1/organizations  {}                    → 400 ZodError: name (string), slug (string) required
POST /v1/organizations  {name, slug}          → 401 "Missing or invalid authorization header"
POST /v1/organizations  {name, slug} + X-API-Key    → 401 (KHÔNG nhìn thấy API key)
POST /v1/organizations  {name, slug} + Authorization: Bearer <api key> → 401 "Invalid token"
GET  /v1/data/account   + Authorization: Bearer <api key> → 401
```

Đọc ra: Leadpipe có **hai mặt phẳng auth tách rời**.

| Mặt phẳng | Header | Phục vụ |
|---|---|---|
| `/v1/data/*` | `X-API-Key: sk_…` | tích hợp máy-với-máy (Beam đang dùng) |
| `/v1/organizations` | `Authorization: Bearer <token phiên đăng nhập>` | dashboard web của người dùng |

Org API key **không bao giờ** gọi được sang mặt phẳng kia — nó bị từ chối trước cả khi được nhìn
tới. Đây là ranh giới thiết kế, không phải thiếu tham số.

Không có bản ghi nào bị tạo trong quá trình probe (mọi lần đều 400/401).

### 12b. Hai đường thật còn lại

| # | Đường | Trạng thái |
|---|---|---|
| **A** | **Beam một org, mỗi KH một pixel theo domain** | ✅ **đã build xong** (§11) — và đây đúng là thứ duy nhất API hỗ trợ |
| **B** | KH tự đăng ký Leadpipe (thủ công, qua web), dán key vào Beam → Beam dùng key đó theo site | ❌ chưa build; đây là BYOK, cần wire `user_api_keys` vào resolver + provisioning |

Không có đường C tự động. Việc đăng ký org bắt buộc đi qua giao diện web của Leadpipe — nơi nào
cũng vậy, vì mỗi org free được 500 credit, nên nhà cung cấp không mở đường tự tạo org hàng loạt.

---

## 13. Migration live round-trip — known-gap ĐÃ ĐÓNG (06-08-26)

Docker bật lại, chạy trên `postgres:16-alpine` dùng-một-lần (port 55432, xoá sau khi xong):

| Bước | Kết quả |
|---|---|
| `upgrade head` (toàn chuỗi, tới `b4c9a71e35d8`) | ✅ sạch |
| `information_schema` sau upgrade | `leadpipe_pixel_id \| character varying \| YES` |
| `downgrade -1` | ✅ sạch |
| `information_schema` sau downgrade | `0` — cột biến mất hoàn toàn |
| `upgrade head` lần hai | ✅ sạch |
| `alembic current` | `b4c9a71e35d8 (head)` |
| Cột sau round-trip | ✅ trở lại đúng kiểu/nullable |

Đây là live round-trip **thật** trên Postgres, không phải offline `--sql`. Container đã xoá.
Vẫn KHÔNG phải là live-apply lên PROD — việc đó là thao tác vận hành riêng.

---

## 14. Vòng validate source (06-08-26) — tìm ra 1 defect tự gây, đã sửa

### 14a. 🔴 Defect: snippet endpoint sẽ gọi API thật trong test

`tests/integration/test_consent_mode.py` gọi `GET /api/v1/sites/{id}/pixel`, và `tests/conftest.py`
**không** set `mock_external_apis`. Với `LEADPIPE_API_KEY` thật trong `.env`, tầng 1 vừa build sẽ
`POST /v1/data/pixels` **thật** và **tạo pixel thật** cho domain fixture — chậm, flaky, và đốt
quota org cho dữ liệu rác.

**Sửa:** `leadpipe_pixel_autoprovision_enabled: bool = False`
([config.py](apps/api/config.py)), chặn ngay đầu `ensure_pixel_for_domain`. Đúng convention repo —
mọi switch chạm provider (`agent_detection_enabled`, `company_graph_enabled`, …) đều default OFF và
chỉ người vận hành bật. Đây cũng là đường Leadpipe **duy nhất GHI** state ở phía vendor, và pixel
đã tạo thì tốn quota org, không di chuyển được sang org khác.

Thêm 2 test: `test_autoprovision_off_by_default_makes_no_vendor_write`,
`test_autoprovision_defaults_off_in_real_settings`.

### 14b. Các kiểm tra khác — sạch

| Kiểm tra | Kết quả |
|---|---|
| `py_compile` 8 file đã sửa | ✅ |
| `from apps.api.main import app` | ✅ import sạch |
| `Settings` không còn `leadpipe_default_pixel_id` / `_domain` | ✅ (`extra: "ignore"` nên `.env` cũ vẫn boot) |
| `SiteOut` có lộ `leadpipe_pixel_id` ra API? | ✅ **không** — không khai báo trong schema |
| `demo.py` (`IdentityResolver(db=None)`) | không đổi hành vi — vốn đã chết vì `db=None`, `_try_graph` nuốt exception |
| Grep toàn repo tham chiếu setting đã gỡ | chỉ còn trong docs/plans lịch sử |
| Unit suite | **1552 passed** |
| Integration `test_consent_mode.py` (PG+Redis thật) | **5 passed** |

Còn lại đúng 2 failed + 8 errors pre-existing (`test_agent_company_resolution`,
`test_content_company`) — đã đối chứng `git stash`, và 3 file không collect được vì thiếu `fakeredis`.

### 14c. Doc kiến trúc đã đồng bộ

`docs/visitor-identity-flow-architecture.md` bị stale 4 chỗ sau thay đổi này, đã sửa:

- §6.2 mermaid: thay `ENV: LEADPIPE_DEFAULT_PIXEL_ID` bằng node flag + node provisioning; thêm
  node gate registry ở nhánh ③
- §6.3 lỗ hổng #2: đổi từ "code chết" sang "đã giải quyết bằng cột + cấp phát động"
- §6.3 thêm #2b: plugin WordPress không đi qua đường snippet (thiếu cả `data-stack` lẫn `data-consent`)
- §"Beam không có code tạo pixel": đổi thành đã làm, kèm phát hiện 409-không-trả-id và bằng chứng
  `/v1/data` không phân biệt được có/không pixel
- Thêm kết luận: không tự tạo org cho khách được (hai mặt phẳng auth)

---

## Unresolved Questions

1. **Tạo pixel ở `create_site` hay ở `verify-pixel`?** — `create_site` chưa biết domain có thật/
   verify được. Tạo sớm sẽ đốt slot pixel của org cho site rác. Gắn vào
   [sites.py:346 `verify_pixel_endpoint`](apps/api/routers/sites.py#L346) có vẻ đúng hơn, nhưng
   thành ra pixel Leadpipe chỉ tồn tại sau khi tracker Beam đã verify — chấp nhận được?
2. **Org free giới hạn bao nhiêu pixel?** — chưa tra được. Ảnh hưởng trực tiếp mô hình "1 org Beam
   dùng chung cho mọi khách".
3. **`status` nhận giá trị gì?** — docs không định nghĩa (`active`/`paused`?). Cần response thật từ
   org mới mới biết, chặn bước 6.
4. **BYOK leadpipe: bỏ khỏi UI hay wire vào resolver?** — quyết định sản phẩm, không suy ra được từ code.
