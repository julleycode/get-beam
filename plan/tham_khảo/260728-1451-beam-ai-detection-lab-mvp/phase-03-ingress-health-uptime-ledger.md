---
phase: 3
title: "Ingress Health & Uptime Ledger"
status: pending
priority: P1
dependencies: [2]
effort: ""
---

# Phase 3: Ingress Health & Uptime Ledger

# Xử lý lỗ hổng G1 — phase quan trọng nhất về tính đúng đắn

## Overview

Làm cho kết luận âm có nghĩa. Không có phase này, `origin_fetch_not_observed` gộp chung 4 nguyên nhân
(AI không fetch / edge chặn / tunnel chết / máy tắt) và toàn bộ số liệu lớp search-index và
training-crawl trở nên vô giá trị.

Vì origin chạy trên máy cá nhân bật/tắt theo ngày, đây không phải rủi ro lý thuyết — nó sẽ xảy ra hằng ngày.

## Requirements

**Functional**
- Heartbeat 60s ghi trạng thái ingress sống/chết.
- External probe: fetch canary qua đúng chuỗi edge→tunnel→origin **và qua security stack của zone** để chứng minh đường vào thông suốt.
- Tính `coverage_pct` cho một khoảng thời gian bất kỳ.
- Gate outcome: thiếu bằng chứng ingress → ép `inconclusive_ingress_unverified`.

**Non-functional**
- Heartbeat không được ghi "up" khi thực chất chỉ có process sống mà tunnel đã đứt.

## Architecture

Hai loại bằng chứng, đừng nhầm:

| Loại | Đo cái gì | Tần suất | Nguồn |
|---|---|---|---|
| **Internal heartbeat** | Process FastAPI còn sống | 60s | chính app |
| **External probe** | Chuỗi CF edge→tunnel→origin thông (Worker); nếu cần cả DNS/anycast từ Internet thì dùng GitHub Actions | trước + sau observation window, và mỗi 15 phút | dịch vụ ngoài |

Internal heartbeat **một mình là vô dụng** — app có thể sống trong khi tunnel đã chết.
External probe là bằng chứng thật.

### Cách chạy external probe không cần VPS

Probe phải xuất phát từ ngoài máy, và **phải đi qua đúng security stack mà crawler thật gặp**.
Hai ràng buộc kỹ thuật quyết định nơi deploy:

- Subrequest **same-zone** (Worker gắn route trên chính zone lab) bỏ qua toàn bộ security stack của
  zone (WAF, Bot Fight Mode) → probe luôn báo `up` kể cả khi edge đang chặn GPTBot thật. **Cấm**
  gắn probe Worker vào route của zone lab.
- Subrequest cross-zone đặt `CF-Connecting-IP = 2a06:98c0:3600::103` (IP cố định của Workers) →
  dùng IP này làm tín hiệu `is_probe` phụ, song song với header secret, và loại khỏi thống kê IP-range.

Ba lựa chọn, chọn 1:

1. **Cloudflare Worker cron trên `*.workers.dev`** (khác zone, free plan có cron trigger) — fetch
   hostname mỗi 15 phút. Worker **luôn** ghi kết quả (up lẫn down, kèm `http_status`,
   `CF-Cache-Status`) vào KV; app đọc KV backfill lúc startup và mỗi 5 phút, đồng thời Worker POST
   về `/_probe/report` như kênh nhanh. Lý do bắt buộc có KV: khi tunnel chết, POST không bao giờ
   tới được app — sự kiện `down` chỉ tồn tại nếu Worker tự lưu lại.
2. **GitHub Actions schedule** — nằm hẳn ngoài Cloudflare, đo được cả DNS/anycast; ghi artifact
   trong repo hoặc gọi webhook về lab.
3. **Uptime monitor free** (UptimeRobot…) + đọc API.

Khuyến nghị (1) với điều kiện deploy trên `*.workers.dev`. Lưu ý probe từ Worker đo
`CF edge → tunnel → origin`, không rời mạng Cloudflare — không kiểm chứng DNS/anycast từ Internet.
Nếu cần bằng chứng DNS, dùng (2).

**Probe phải mang UA của crawler**, ví dụ `GPTBot/1.0`, chứ không phải UA mặc định — mục đích là phát hiện
edge có chặn UA crawler hay không. Probe bằng curl mặc định sẽ pass trong khi GPTBot thật bị chặn.

Request từ probe phải được đánh dấu `is_probe=1` để không lẫn vào dữ liệu quan sát — nhận diện bằng
header `X-Lab-Probe: {secret}` **hoặc** `CF-Connecting-IP = 2a06:98c0:3600::103`.

```sql
CREATE TABLE ingress_heartbeat (
  ts          TEXT NOT NULL,         -- ISO8601, làm tròn phút
  source      TEXT NOT NULL,         -- internal | external
  status      TEXT NOT NULL,         -- up | down | probe_unknown
  http_status INTEGER,               -- external: mã trả về thật
  probe_ua    TEXT,                  -- external: UA đã dùng
  latency_ms  INTEGER,
  detail      TEXT,
  PRIMARY KEY (ts, source)           -- internal và external cùng phút phải cùng tồn tại
);

CREATE INDEX idx_heartbeat_ts ON ingress_heartbeat(ts);
```

### Tính coverage — theo khoảng probe, không theo phút

Probe chạy 15 phút/lần nên dữ liệu external chỉ có ~96 mẫu/ngày; công thức "số phút có heartbeat"
là bất khả thi (trần coverage ≈ 6.7%). Thay vào đó, mỗi probe `up` tại thời điểm `t` **phủ khoảng
`[t, t+period)`**:

```
coverage_pct(window) = tổng thời lượng các khoảng up giao với window / độ dài window * 100
```

Quy tắc:

- Chỉ tính theo `source='external'`. Internal heartbeat dùng để chẩn đoán, không tính coverage.
- Khoảng trống giữa 2 probe > 1 chu kỳ = `probe_unknown` (Worker chết / hết quota / CF sự cố) —
  tính là không-covered nhưng **tách khỏi** `down`, vì đây là "phép đo chết", không phải "origin chết".
- Ghi `coverage_resolution_minutes` (= chu kỳ probe, mặc định 15) cạnh mọi giá trị coverage để
  người đọc biết độ phân giải: khoảng down ngắn hơn 15 phút nằm giữa 2 probe `up` là không thấy được.

### Outcome gating (INV-3)

```python
def gate_outcome(raw_outcome, window) -> tuple[str, float | None]:
    pre, post = probe_at_window_edges(window)
    if not (pre.up and post.up):
        return ("inconclusive_ingress_unverified", None)
    if raw_outcome == "origin_fetch_not_observed":
        return (raw_outcome, coverage_pct(window))
    return (raw_outcome, None)
```

Outcome lưu thành **2 cột riêng**: `outcome_code` + `coverage_pct` (xem schema phase 6). Chuỗi
hiển thị `origin_fetch_not_observed(coverage=NN%)` chỉ được ghép ở tầng render (dashboard/API) —
nếu nhúng coverage vào chuỗi lưu trữ, run diff (phase 8) sẽ báo "outcome đổi" khi thực chất chỉ
coverage nhích.

Quy tắc cứng: **không API nào được trả `origin_fetch_not_observed` mà thiếu coverage**. Luôn qua `gate_outcome`.

## Related Code Files

- Create: `src/beam_lab/health/heartbeat.py` — writer internal, chạy background task
- Create: `src/beam_lab/health/probe_ingest.py` — nhận kết quả probe ngoài + backfill từ Workers KV
- Create: `src/beam_lab/health/coverage.py` — tính coverage, gate_outcome
- Create: `src/beam_lab/routes/probe.py` — endpoint `/_probe/report` nhận kết quả, bảo vệ bằng shared secret
- Create: `deploy/worker/probe-worker.js` — Cloudflare Worker cron
- Create: `deploy/worker/wrangler.toml`
- Modify: `src/beam_lab/intake/middleware.py` — đánh dấu `is_probe`
- Modify: `src/beam_lab/db/schema.sql`
- Create: `tests/test_coverage_calc.py`
- Create: `tests/test_outcome_gating.py`

## Implementation Steps

1. `health/heartbeat.py`: background task ghi `source='internal', status='up'` mỗi 60s. Dùng `asyncio` task khởi tại lifespan.
2. `deploy/worker/probe-worker.js`: cron `*/15 * * * *`, deploy trên `*.workers.dev` (khác zone). Fetch `https://{hostname}/{probe-path}` với header `User-Agent: GPTBot/1.0`; **luôn** ghi kết quả (up/down, `http_status`, `CF-Cache-Status`) vào KV trước, rồi POST về `/_probe/report` kèm shared secret (kênh nhanh, chấp nhận mất khi tunnel chết).
3. `routes/probe.py`: verify shared secret, INSERT vào `ingress_heartbeat` với `source='external'`. Trả 204. Thêm job đọc KV backfill lúc startup và mỗi 5 phút (idempotent theo `(ts, source)`); khoảng trống dữ liệu probe ghi `probe_unknown`.
4. Đánh dấu request probe: probe gửi header riêng `X-Lab-Probe: {secret}`; middleware set `is_probe=1`, thêm cột vào `evidence_bundle`.
5. `health/coverage.py`: `coverage_pct(start, end)` theo mô hình khoảng probe ở trên, trả kèm `coverage_resolution_minutes`. Khoảng trống probe = `probe_unknown`, không tính là `down`.
6. `gate_outcome()` như pseudocode trên. Đây là hàm duy nhất được phép sinh chuỗi outcome cuối.
7. Test: chèn internal + external cùng phút (không vi phạm PK); giả lập window có lỗ hổng → coverage đúng theo mô hình khoảng; khoảng trống probe → `probe_unknown` tách khỏi `down`; probe biên fail → ép `inconclusive_ingress_unverified`.
8. Endpoint `/_lab/health` hiển thị timeline uptime để mắt thường thấy được lỗ hổng.

## Success Criteria

- [ ] Tắt `cloudflared` ≥ 1 chu kỳ probe → probe ghi `down` (đọc được qua KV backfill kể cả khi POST không tới được), coverage giảm tương ứng theo độ phân giải 15 phút.
- [ ] App sống nhưng tunnel chết → internal `up` nhưng external `down`. Coverage phản ánh external.
- [ ] Probe dùng UA `GPTBot/1.0`; nếu edge chặn UA này thì probe ghi `down` kèm `http_status` thật.
- [ ] **Bật Bot Fight Mode thủ công → probe phải ghi `down`** — bài test duy nhất chứng minh probe không bị bypass security stack (same-zone).
- [ ] Request từ probe có `is_probe=1` (theo header secret hoặc IP Workers) và bị loại khỏi mọi thống kê quan sát, kể cả thống kê IP-range.
- [ ] Giết Worker (gỡ cron) → khoảng trống ghi `probe_unknown`, dashboard phân biệt "phép đo chết" với "origin chết".
- [ ] `outcome_code` và `coverage_pct` là 2 cột riêng trong DB; chuỗi ghép chỉ tồn tại ở tầng render.
- [ ] Không có đường code nào trả `origin_fetch_not_observed` mà không qua `gate_outcome` — test grep khẳng định.
- [ ] Probe biên (trước/sau window) fail → outcome là `inconclusive_ingress_unverified`, không phải "AI không fetch".
- [ ] `/_lab/health` vẽ được timeline uptime theo ngày.

## Risk Assessment

| Rủi ro | Mitigation |
|---|---|
| Probe dùng UA thường → pass trong khi crawler thật bị chặn | Probe **bắt buộc** dùng UA crawler. Cân nhắc probe 2 UA: GPTBot + Chrome, so sánh |
| Worker gắn nhầm route của zone lab → subrequest same-zone bypass Bot Fight Mode/WAF, báo `up` giả | Deploy trên `*.workers.dev`; test bắt buộc: bật Bot Fight Mode → probe phải ghi `down` |
| Tunnel chết → POST kết quả probe không tới được app, sự kiện `down` bị mất | Worker luôn ghi KV trước; app backfill từ KV. Kênh POST chỉ là đường nhanh |
| Worker/CF sự cố trông giống origin chết | Trạng thái `probe_unknown` tách khỏi `down`; dashboard hiện rõ |
| Độ phân giải coverage 15 phút: khoảng down ngắn hơn 1 chu kỳ không thấy được | Ghi `coverage_resolution_minutes` cạnh outcome; cân nhắc chu kỳ 5 phút nếu cần (open question #4). Hạn mức Worker free (~96-288 lần/ngày) không phải vấn đề |
| Shared secret lộ → ai cũng ghi được heartbeat giả | Secret trong `.env`, không commit. Probe endpoint chỉ nhận POST, rate limit |
| Máy sleep giữa đêm làm coverage thấp bất ngờ | Đã xử ở phase 2 (`powercfg`). Dashboard cảnh báo khi coverage < 80% |
| Coverage thấp bị bỏ qua khi đọc kết quả | Tầng render luôn ghép coverage vào chuỗi outcome + badge màu (phase 7). DB giữ 2 cột riêng để run diff không vỡ |
