---
phase: 1
title: Foundation & Evidence Store
status: completed
priority: P1
dependencies: []
effort: ''
---

# Phase 1: Foundation & Evidence Store

## Overview

Dựng bộ xương FastAPI + SQLite và lớp lưu bằng chứng bất biến. Mọi request tới lab được sinh
`request_id`, chuẩn hoá thành evidence bundle niêm phong, lưu trước khi bất kỳ detector nào chạy.

## Requirements

**Functional**
- Middleware bắt mọi request, sinh `request_id`, dựng `RequestContext`.
- Evidence bundle bất biến, có `schema_version`.
- Lưu full response body của trang canary (bắt buộc cho takedown test ở phase 6).
- Privacy filter: IP thô sống tối đa 24h, sau đó chỉ còn `ip_hash` + `ip_prefix`.

**Non-functional**
- Ghi evidence không được làm hỏng response. Lỗi ghi → log + trả trang bình thường (INV-1 không được biến thành single point of failure).
- SQLite WAL mode để đọc dashboard song song với ghi ingest.

## Architecture

```
Request → IntakeMiddleware
            ├─ sinh request_id (uuid7 hoặc ulid)
            ├─ đọc header edge: CF-Connecting-IP, CF-IPCountry, CF-Ray
            ├─ resolve rDNS async, timeout 500ms trước route → lưu kết quả vào bundle
            ├─ đọc snapshot IP-range version hiện hành → lưu version hash vào bundle
            ├─ seal bundle (frozen dataclass / pydantic model, immutable)
            └─ INSERT evidence_bundle  → rồi mới trả response
```

**Sealed bundle** là hợp đồng trung tâm của cả dự án. Nó chứa *tất cả* dữ liệu ngoài mà detector
sẽ cần, được resolve tại thời điểm request. Detector ở phase 4 không được đọc gì khác.

### Schema SQLite

```sql
-- bundle bất biến, không UPDATE sau khi INSERT
CREATE TABLE evidence_bundle (
  request_id      TEXT PRIMARY KEY,
  schema_version  INTEGER NOT NULL,
  occurred_at     TEXT NOT NULL,          -- ISO8601 UTC
  test_run_id     TEXT,                   -- NULL nếu không thuộc test run
  method          TEXT NOT NULL,
  host            TEXT NOT NULL,
  path            TEXT NOT NULL,
  query_json      TEXT NOT NULL,
  headers_json    TEXT NOT NULL,          -- đã lọc, giữ nguyên tên header
  user_agent      TEXT,
  referrer        TEXT,
  ip_raw          TEXT,                   -- xoá sau 24h
  ip_hash         TEXT NOT NULL,
  ip_prefix       TEXT NOT NULL,          -- /24 v4, /48 v6
  country         TEXT,
  edge_ray_id     TEXT,
  rdns_result     TEXT,                   -- resolve lúc request; NULL nếu fail/timeout
  rdns_status     TEXT NOT NULL,          -- ok | nxdomain | timeout | error
  ip_range_snapshot_id TEXT,              -- FK → ip_range_snapshot (phase 5)
  edge_config_snapshot_id TEXT,           -- FK → edge_config_snapshot (phase 2)
  created_at      TEXT NOT NULL
);

CREATE INDEX idx_bundle_test_run ON evidence_bundle(test_run_id);
CREATE INDEX idx_bundle_occurred ON evidence_bundle(occurred_at);

-- nội dung trả về, bất biến, dùng chứng minh marker có mặt lúc AI fetch
CREATE TABLE content_snapshot (
  snapshot_id   TEXT PRIMARY KEY,
  request_id    TEXT NOT NULL REFERENCES evidence_bundle(request_id),
  status_code   INTEGER NOT NULL,
  content_type  TEXT,
  body          BLOB NOT NULL,
  body_sha256   TEXT NOT NULL,
  byte_len      INTEGER NOT NULL,
  created_at    TEXT NOT NULL
);

CREATE INDEX idx_snapshot_request ON content_snapshot(request_id);

CREATE TABLE schema_migration (
  version     INTEGER PRIMARY KEY,
  applied_at  TEXT NOT NULL
);
```

Ghi chú thiết kế:
- `headers_json` giữ tên header như nhận được, **nhưng không dùng làm signal về thứ tự** — Tunnel đã normalize. Lưu để audit, không để phân loại.
- `ip_raw` nullable và bị xoá bởi job retention; `ip_hash`/`ip_prefix` là vĩnh viễn.
- Không có bảng `classification` ở phase này. Classification là view dẫn xuất, sinh ở phase 4.
- `ip_range_snapshot_id` / `edge_config_snapshot_id` chỉ là chú thích FK, **không** khai báo `REFERENCES` — bảng đích chưa tồn tại ở phase này, `foreign_keys=ON` sẽ làm INSERT lỗi. Giữ nguyên khi implement.
- `SCHEMA_VERSION` phải tăng ở mọi phase thêm cột vào `evidence_bundle` (phase 3 thêm `is_probe` → 2, phase 5 thêm signature + `ip_range_match_json` → 3). Migration đánh số trong `db/migrations/`, chạy tuần tự lúc startup, idempotent nhờ kiểm tra `PRAGMA table_info` trước khi `ALTER`.

## Related Code Files

- Create: `pyproject.toml`
- Create: `src/beam_lab/__init__.py`
- Create: `src/beam_lab/app.py` — FastAPI app factory
- Create: `src/beam_lab/config.py` — settings từ env
- Create: `src/beam_lab/db/schema.sql`
- Create: `src/beam_lab/db/connection.py` — SQLite WAL, busy_timeout, migration runner
- Create: `src/beam_lab/db/migrations/` — migration đánh số, idempotent
- Create: `src/beam_lab/intake/middleware.py`
- Create: `src/beam_lab/intake/context.py` — RequestContext builder
- Create: `src/beam_lab/intake/bundle.py` — sealed EvidenceBundle model
- Create: `src/beam_lab/intake/privacy.py` — ip_hash, ip_prefix, retention job
- Create: `src/beam_lab/intake/rdns.py` — resolve async có timeout
- Create: `tests/test_bundle_immutable.py`
- Create: `tests/test_privacy_filter.py`
- Create: `tests/test_intake_middleware.py`
- Create: `tests/test_evidence_write_fallback.py`

## Implementation Steps

1. Khởi tạo project: `pyproject.toml`, dependency `fastapi`, `uvicorn`, `pydantic`, `jinja2`, `pytest`, `httpx`.
2. `db/connection.py`: mở SQLite với `PRAGMA journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000`; chạy migration đánh số từ `db/migrations/` (idempotent, ghi vào `schema_migration`). Mọi ghi DB từ request path đi qua `run_in_threadpool` — driver `sqlite3` là blocking, không được chặn event loop.
3. `intake/bundle.py`: định nghĩa `EvidenceBundle` là pydantic model `frozen=True`. Thêm `SCHEMA_VERSION = 1`.
4. `intake/privacy.py`: `ip_hash` = HMAC-SHA256(ip, salt từ env — salt không đổi giữa các run, nếu không mất khả năng correlate); `ip_prefix` cắt /24 và /48.
5. `intake/rdns.py`: resolve reverse DNS async, timeout 500ms, trả `(result, status)`.
   Resolve trước route để bundle bất biến được INSERT trước khi business route chạy; quá hạn ghi
   `timeout`. INV-1 được ưu tiên hơn tối ưu latency.
6. `intake/context.py`: đọc `CF-Connecting-IP` (fallback `X-Forwarded-For` rồi socket peer), `CF-IPCountry`, `CF-Ray`. Nhận diện `test_run_id` từ path pattern `/t/{run_id}/{token}`.
7. `intake/middleware.py`: dựng bundle → INSERT → gọi route → lưu `content_snapshot` từ response body. Bọc try/except: lỗi ghi thì log + tăng counter `evidence_write_failures` + append bundle ra file JSONL fallback (append-only, backfill sau), không raise. Evidence mất âm thầm là false negative nguy hiểm nhất của lab — request có thật nhưng không được ghi sẽ bị chấm nhầm `origin_fetch_not_observed` — nên phải lộ ra bằng counter và fallback file.
8. Retention job: script xoá `ip_raw` cho bản ghi cũ hơn 24h. Chạy tay hoặc theo scheduler ở phase 8.
9. Route tạm `/health` và một trang tĩnh để test middleware end-to-end.

## Success Criteria

- [x] `EvidenceBundle` không thể mutate sau khi tạo — test khẳng định raise khi gán thuộc tính.
- [x] Mọi request qua middleware sinh đúng 1 hàng `evidence_bundle` và 1 hàng `content_snapshot`.
- [x] `body_sha256` khớp với body thật; đọc lại từ DB cho bytes giống hệt.
- [x] `ip_raw` được xoá sau retention job, `ip_hash`/`ip_prefix` còn nguyên.
- [x] Cùng một IP + cùng salt luôn cho cùng `ip_hash` giữa các lần khởi động app.
- [x] Lỗi ghi DB không làm request lỗi — test inject lỗi và khẳng định response vẫn 200, counter `evidence_write_failures` tăng, và bundle xuất hiện trong file JSONL fallback.
- [x] `rdns_status` được ghi đúng cho cả 3 trường hợp: ok, nxdomain, timeout.

## Risk Assessment

| Rủi ro | Mitigation |
|---|---|
| rDNS chậm làm tăng latency response | timeout cứng 500ms trước route để bảo toàn INSERT evidence-first; ghi `timeout` nếu quá hạn. Theo dõi latency trước khi phase 5 thêm signature verify; tổng overhead phải dưới ~1s |
| `sqlite3` blocking trong middleware async; WAL chỉ cho một writer; heartbeat/scoring/scheduler ghi song song → `database is locked` | `busy_timeout=5000`, ghi qua threadpool, counter `evidence_write_failures` + JSONL fallback khi fail |
| `ALTER TABLE` tay chạy lại → `duplicate column`; bundle cũ bị đọc nhầm khi schema đổi | Bảng `schema_migration` + migration đánh số idempotent; bump `SCHEMA_VERSION` mỗi lần thêm cột bundle; detector khai báo `min_schema_version` (phase 4) |
| Lưu full body làm phình DB | Chỉ lưu body cho path canary và trang lab; bỏ qua asset tĩnh. Thêm giới hạn byte (vd 1MB) và ghi `truncated` |
| Đổi salt làm mất khả năng correlate lịch sử | Salt lưu trong env file, không sinh ngẫu nhiên lúc khởi động. Ghi rõ trong README |
| SQLite lock khi dashboard đọc lúc ingest ghi | WAL mode + connection riêng cho đọc |
