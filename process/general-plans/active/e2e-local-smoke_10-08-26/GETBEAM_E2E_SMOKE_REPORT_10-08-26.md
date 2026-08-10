# Báo cáo E2E + Smoke GetBeam — 10-08-26

## TL;DR

Local E2E/smoke trên GetBeam (web `:3000`, API `:8000`) kết thúc **DONE_WITH_CONCERNS**. Core loops (Add site, Agents, Visitors, Ask AI, Pixel beamlab, Outcomes, Agent Gateway, Drafts/Referrals/Feature Board/Contacts) **PASS**. Social OAuth, Campaigns, Billing **BLOCKED** (thiếu keys/segment/Gumroad). Segments / Feed / Connectors **PARTIAL**. CORS `127.0.0.1` đã fix trong session.

Evidence agents: `0cbdd7ca`, `1d8590ff`, `db766efe`, `d1b483af`.

## Môi trường

| Thành phần | Giá trị |
|---|---|
| Web | `http://localhost:3000` (canonical) |
| API | `:8000` |
| Postgres | `:5433` |
| Auth | JWT local demo |
| Origin note | Browser coi `127.0.0.1` ≠ `localhost` → cần CORS cả hai |

## Thay đổi kèm theo (CORS)

File: `apps/api/main.py`

Thêm origins:

- `http://127.0.0.1:3000`
- `http://127.0.0.1:3001`

Mục đích: login/dashboard local JWT hoạt động dù user gõ `localhost` hay `127.0.0.1`.

Liên quan session (auth UX): `apps/web/src/lib/api.ts` — form login/signup không hard-redirect khi 401; surface `"Invalid email or password"`.

## Ma trận kết quả

| Luồng | Kết quả | Ghi chú |
|---|---|---|
| Add site | PASS | Hit limit → 402 (expected) |
| Agents | PASS | |
| Visitors | PASS | |
| Social OAuth | BLOCKED | Keys EMPTY |
| Ask AI | PASS | |
| Pixel verify | PASS | beamlab |
| Outcomes | PASS | |
| Agent Gateway | PASS | |
| Segments | PARTIAL | Cần data enriched |
| Campaigns | BLOCKED | Cần segment |
| Feed | PARTIAL | |
| Connectors | PARTIAL | 501 |
| Billing | BLOCKED | Gumroad unset |
| Drafts | PASS | load |
| Referrals | PASS | load |
| Feature Board | PASS | load |
| Contacts | PASS | load |

**Status tổng:** `DONE_WITH_CONCERNS`

## Chi tiết luồng

### PASS

- **Add site:** tạo site OK; khi vượt limit trả **402**.
- **Agents / Visitors / Ask AI / Outcomes / Agent Gateway:** smoke OK.
- **Pixel verify:** xác minh trên site **beamlab** OK.
- **Drafts / Referrals / Feature Board / Contacts:** trang load OK.

### PARTIAL

- **Segments:** UI/API chưa đủ data enriched; copy UI đề cập “10+” trong khi API ngưỡng ≥3 — lệch copy.
- **Feed:** một phần surface chưa đủ evidence xanh.
- **Connectors:** endpoint/surface trả **501** (chưa implement hoặc stub).

### BLOCKED

- **Social OAuth:** provider keys EMPTY → không chạy nối OAuth thật.
- **Campaigns:** phụ thuộc segment hợp lệ → blocked.
- **Billing:** Gumroad unset → không verify checkout/webhook.

## Gap

### P0

- CORS `127.0.0.1` vs `localhost` — **đã fix** trong `apps/api/main.py`.

### P1

- Agents `by_vendor` count (số liệu/aggregate chưa khớp kỳ vọng).
- Sites trailing slash → **307** redirect (client/API path hygiene).
- Social UI silent error khi keys trống (không báo rõ “chưa cấu hình”).
- Pixel remote URL (khác local beamlab path) chưa cover đầy đủ.

### P2

- Segments copy “10+” vs API ≥3.
- Connectors 501 cần product decision (implement vs hide).
- Feed partial — cần dataset / seed ổn định cho retest.

## Luồng chưa test / BLOCKED

| Hạng mục | Lý do |
|---|---|
| Social OAuth end-to-end | Keys EMPTY |
| Campaigns create/send | Cần segment enriched |
| Billing / Gumroad | Env unset |
| Connectors full CRUD | 501 |
| Pixel trên remote URL production-like | Chỉ verify beamlab local |

## Khuyến nghị

1. Merge/deploy CORS `127.0.0.1` trước khi tiếp tục local JWT demo trên IP loopback.
2. Seed segment enriched → mở khóa retest Campaigns + Segments (đóng gap copy 10+ vs ≥3).
3. Set Social keys (hoặc mock) + surface lỗi UI rõ khi EMPTY.
4. Cấu hình Gumroad sandbox trước Billing smoke.
5. Quyết định Connectors: implement hoặc ẩn UI khi 501.
6. Retest sau seed: Segments → Campaigns → Feed → Connectors → Billing.

---

*Nguồn: tổng hợp session E2E/retest agents `0cbdd7ca`, `1d8590ff`, `db766efe`, `d1b483af` — không bổ sung claim ngoài evidence đã ghi.*
