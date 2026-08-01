---
phase: 2
title: "Edge Deployment & Config Snapshot"
status: pending
priority: P1
dependencies: [1]
effort: ""
---

# Phase 2: Edge Deployment & Config Snapshot

# Xử lý lỗ hổng G2

## Overview

Đưa lab ra Internet tại `studio.nhantown.com` qua Cloudflare named tunnel, và **version hoá cấu hình edge**.
Cấu hình edge (Bot Fight Mode, WAF rule, robots.txt) là biến của thí nghiệm — thay đổi nó làm đổi kết quả.
Không snapshot thì chu kỳ sau không so được với chu kỳ này, mà so sánh chính là mục tiêu của lab.

## Requirements

**Functional**
- Named tunnel với hostname cố định (không Quick Tunnel).
- Tách 2 vùng: public test surface (AI vào được, không auth) và private dashboard (chặn ngoài).
- Snapshot cấu hình edge thành bản ghi bất biến, gắn vào từng evidence bundle.
- `cloudflared` chạy như Windows service, chống sleep trong observation window.

**Non-functional**
- Origin/tunnel down → Cloudflare trả lỗi edge/tunnel unavailable, không phải origin 404. Không khóa test vào một mã lỗi cụ thể.
- Dashboard không được lộ ra Internet trong bất kỳ cấu hình nào.

## Architecture

```
Internet
   ↓
Cloudflare zone (free)  ← Bot Fight Mode tắt; AI bot policies Allow; managed robots.txt tắt
   ↓ named tunnel
cloudflared (Windows service)
   ↓
FastAPI public app — 127.0.0.1:8000 (đích duy nhất của tunnel)
   ├─ /            public test surface
   ├─ /t/{run}/{token}   canary
   ├─ /robots.txt  sinh động theo test run policy
   └─ /_probe/*    nhận kết quả probe (phase 3)

FastAPI dashboard app — 127.0.0.1:8001, KHÔNG xuất hiện trong bất kỳ ingress rule nào
   └─ /_lab/*      dashboard
```

Dashboard chạy **app riêng, port riêng** (`localhost:8001/_lab`). Lý do: `cloudflared` chạy trên cùng
máy và kết nối tới origin qua loopback, nên với mọi request đi qua tunnel, TCP peer mà uvicorn thấy
đều là `127.0.0.1` — kiểm tra `request.client.host` là loopback **không phân biệt được** traffic
tunnel với traffic local. Phòng thủ 3 lớp:

1. Dashboard bind port riêng, không nằm trong ingress rule nào của tunnel.
2. Ingress rule tường minh trả 404 cho `/_lab` (đặt trước rule catch-all).
3. Public app trả 404 cho mọi path `/_lab`, và từ chối request mang header `CF-*`
   (`CF-Ray`, `CF-Connecting-IP`) tới route nhạy cảm — đây mới là tín hiệu phân biệt thật
   giữa traffic qua Cloudflare và traffic local.

Không cần Cloudflare Access.

### Edge config snapshot

```sql
CREATE TABLE edge_config_snapshot (
  snapshot_id        TEXT PRIMARY KEY,
  captured_at        TEXT NOT NULL,
  hostname           TEXT NOT NULL,
  tunnel_id          TEXT NOT NULL,
  bot_fight_mode     TEXT NOT NULL,   -- on | off | unknown
  ai_block_rule      TEXT NOT NULL,   -- on | off | unknown
  waf_rules_json     TEXT,            -- danh sách rule đang bật, nếu đọc được
  robots_txt_body    TEXT NOT NULL,
  robots_txt_sha256  TEXT NOT NULL,
  sitemap_submitted  INTEGER NOT NULL DEFAULT 0,
  cache_bypass_enabled TEXT NOT NULL,  -- on | off | unknown
  cache_rules_json   TEXT,             -- cache rule đang bật, nếu đọc được
  notes              TEXT,            -- nhập tay cho thứ không đọc tự động được
  created_at         TEXT NOT NULL
);
```

Giá trị `unknown` là hợp lệ và **phải được hiển thị nổi bật** trên dashboard. Free plan không đọc
được hết cấu hình qua API; thà ghi `unknown` còn hơn đoán bừa `off`.

Mỗi lần bật lab: tạo snapshot mới nếu có gì đổi so với snapshot gần nhất, ngược lại tái dùng.
`evidence_bundle.edge_config_snapshot_id` trỏ tới snapshot đang hiệu lực lúc request.

### Cache policy — một phần của biến thí nghiệm

Cloudflare mặc định cache theo đuôi file (CSS, PNG, JPG, JS, ICO…) và cache cả `robots.txt`;
TTL mặc định 200/301 = 120 phút, 302/303 = 20 phút, 404/410 = 3 phút. Không tắt cache thì:
asset của canary không bao giờ chạm origin (V4 và `request_shape` đo sai), và crawler nhận
robots.txt của run trước (V3 đo sai). Đây là lỗi làm **sai dữ liệu**, không phải làm chậm.

Bắt buộc:

- Cache Rule `Bypass cache` cho toàn bộ hostname lab (tối thiểu `/t/*` và `/robots.txt`).
- Origin trả `Cache-Control: no-store` cho mọi response canary và robots.txt — phòng trường hợp
  ai đó bật "Cache Everything" về sau.
- Ghi `cache_bypass_enabled` + `cache_rules_json` vào `edge_config_snapshot`.
- Kiểm chứng bằng header `CF-Cache-Status: DYNAMIC/BYPASS` trong probe response (phase 3)
  và bằng tay khi setup.

## Related Code Files

- Create: `src/beam_lab/edge/snapshot.py` — dựng + so sánh + lưu snapshot
- Create: `src/beam_lab/edge/cloudflare_api.py` — đọc zone setting qua API token read-only
- Create: `src/beam_lab/routes/robots.py` — sinh robots.txt theo test run policy
- Create: `src/beam_lab/routes/public.py` — test surface + nội dung site giả lập
- Create: `src/beam_lab/templates/public_*.html` — vài trang kiểu portfolio/company (open question #2)
- Create: `src/beam_lab/routes/lab.py` — dashboard, app riêng bind 127.0.0.1:8001
- Create: `deploy/cloudflared-config.example.yml` — versioned template only; rendered config and credentials stay outside Git
- Create: `deploy/install-service.ps1` — cài cloudflared service + tắt sleep
- Create: `deploy/README.md` — checklist thủ công không tự động được
- Create: `src/beam_lab/db/migrations/002-edge-config-snapshot.sql`
- Modify: `src/beam_lab/app.py` — giữ `create_app()`, thêm public/dashboard factories và startup snapshot
- Modify: `src/beam_lab/config.py`, `.env.example`, `.gitignore` — edge settings và secret hygiene
- Modify: `src/beam_lab/db/connection.py`, `src/beam_lab/intake/context.py` — snapshot persistence + bundle construction
- Modify: `src/beam_lab/intake/middleware.py` — gắn `edge_config_snapshot_id` vào bundle
- Create: `tests/test_edge_snapshot.py`
- Create: `tests/test_robots_policy.py`

## Implementation Steps

1. Dùng zone `nhantown.com` và hostname đã chốt `studio.nhantown.com`. Ghi hostname vào `.env`, không commit.
2. **Tắt Bot Fight Mode**; đặt Search/Agent/Training AI bot policies về `Allow`; không tạo AI Crawl Control block action; tắt Cloudflare managed robots.txt để origin giữ quyền sinh robots động. Chụp màn hình làm bằng chứng ban đầu vào thư mục vận hành đã ignore, không commit dữ liệu nhạy cảm.
3. Tạo locally-managed named tunnel (tên nội bộ đề xuất `nhantown-studio`), route `studio.nhantown.com` về `http://localhost:8000`.
4. `deploy/cloudflared-config.example.yml`: ingress tường minh — rule `path: ^/_lab` → `http_status:404` đặt **trước** rule `hostname → http://localhost:8000`, và final catch-all `http_status:404` đặt cuối. Render config thật ngoài Git. Không dùng pattern chung `^/_` vì `/_probe/report` (phase 3) phải đi qua tunnel được.
5. `routes/lab.py`: dashboard router chạy trong app riêng bind `127.0.0.1:8001`. Lớp phụ trong public app (:8000): trả 404 cho mọi path `/_lab` và từ chối request mang header `CF-*` tới endpoint nhạy cảm. **Không** dựa vào `request.client.host` — qua tunnel nó luôn là loopback.
6. `edge/cloudflare_api.py`: dùng API token **read-only** đọc zone settings. Field nào không đọc được → `unknown`, không suy đoán.
7. `edge/snapshot.py`: gom cấu hình + robots.txt hiện hành + hash → so sánh với snapshot mới nhất → tạo mới nếu khác.
8. Gọi `snapshot.ensure_current()` lúc app startup; cache `snapshot_id` trong app state.
9. `routes/robots.py`: robots.txt sinh động qua interface `RobotsPolicyProvider` — phase này cắm implementation trả list rỗng (bảng `test_run` chưa tồn tại); phase 6 thay bằng implementation đọc run active. Response kèm `Cache-Control: no-store`.
10. `deploy/install-service.ps1`: cài cloudflared service **và** uvicorn (cả 2 app) như Windows service (NSSM hoặc `sc.exe`) — reboot máy (Windows Update) mà tunnel sống nhưng app chết = Cloudflare trả 502, coverage tụt âm thầm. Thêm `powercfg /change standby-timeout-ac 0` và `hibernate-timeout-ac 0`.
11. `deploy/README.md`: checklist tay — mua domain, tắt Bot Fight Mode, tạo API token, tạo Cache Rule bypass, chạy script, verify `CF-Cache-Status`.
12. Nội dung site public: dựng vài trang giả lập theo template portfolio/company (open question #2), đủ để crawler coi là đáng index. Không chứa dữ liệu thật/nhạy cảm. Site trống = 2/3 lớp hành vi (index, training) không có traffic để đo.

## Success Criteria

- [ ] Hostname cố định truy cập được từ mạng ngoài, trả đúng trang public.
- [ ] Dashboard truy cập được từ `localhost:8001/_lab`; gọi `/_lab` qua hostname public trả 404 ở **cả hai** lớp: ingress rule và public app. Request mang header `CF-Ray` giả tới `/_lab` trên public app cũng 404.
- [ ] Tắt `cloudflared` → hostname trả lỗi Cloudflare 5xx/tunnel unavailable (tài liệu hiện hành nêu 1016 cho tunnel dừng), xác nhận bằng curl từ máy khác. **Không phải origin 404**.
- [ ] `edge_config_snapshot` có bản ghi; đổi robots.txt → snapshot mới được tạo, hash khác.
- [ ] Mọi `evidence_bundle` mới đều có `edge_config_snapshot_id` khác NULL.
- [ ] Field không đọc được từ API ghi `unknown`, không ghi `off`.
- [ ] Máy không sleep sau khi chạy `install-service.ps1` — kiểm bằng `powercfg /query`.
- [ ] Reboot máy → cả cloudflared lẫn uvicorn tự lên, hostname trả 200 trong vòng 5 phút.
- [ ] `CF-Cache-Status` của trang canary và robots.txt là `DYNAMIC` hoặc `BYPASS`, kiểm bằng curl lẫn probe; `edge_config_snapshot` ghi `cache_bypass_enabled=on`.
- [ ] robots.txt render qua `RobotsPolicyProvider`, response kèm `Cache-Control: no-store`. (Criterion "phản ánh đúng policy của run đang bật" thuộc phase 6, khi `test_run` đã tồn tại.)

## Risk Assessment

| Rủi ro | Mitigation |
|---|---|
| Bot Fight Mode vẫn chặn dù đã tắt (có báo cáo cộng đồng) | Phase 3 external probe là phép kiểm chứng duy nhất đáng tin. Không tin dashboard Cloudflare |
| Tên domain lộ mục đích lab → AI hành xử khác | Open question #1 ở plan.md. Tránh `lab`, `test`, `bot`, `canary`, `detect` |
| API token bị commit | Token read-only, lưu `.env`, thêm `.gitignore` từ đầu. Ghi rõ trong deploy/README |
| Dashboard rò rỉ qua tunnel — `request.client.host` không dùng được vì cloudflared kết nối từ 127.0.0.1 | Ba lớp: app+port riêng không nằm trong ingress rule, rule `path: ^/_lab → 404` trước catch-all, từ chối header `CF-*` trong code. Test khẳng định cả ba |
| Edge cache trả asset/robots.txt từ cache → V3/V4/request_shape đo sai | Cache Rule bypass + `no-store` ở origin + snapshot `cache_bypass_enabled` + kiểm `CF-Cache-Status` trong probe |
| Free plan không đọc được đủ cấu hình | Chấp nhận `unknown` + trường `notes` nhập tay. Không giả vờ biết |
