# Plan red-team: Failure Mode Analyst

**Plan:** `plans/260818-0032-scale-ready-getbeam/`
**Roles:** Fact Checker + Flow Tracer
**Posture:** hostile. No praise. Findings only.

## Flow Tracer verdict (bootstrap claim)

Umbrella claim (`plan.md` Overview): flag ON **không stamp** `sites.last_aggregated_at` trên full recompute → ingest watermark NULL luôn `since=None` → full mãi. **PROVED TRUE.**

Trace A — ingest `_background_aggregate`:

1. Redis `agg:sweep_pending:{site_id}` → yield (events.py:933-936).
2. Redis `SET NX EX` `agg:debounce:{site_id}` TTL `aggregation_min_interval_seconds` (events.py:938-943). **Không** `release` debounce khi xong.
3. Flag ON: `since = get_aggregation_watermark()` (events.py:947-951). NULL → `since=None`.
4. `aggregate_visitors_for_site(..., since=since)` (events.py:952).
5. Aggregator chỉ `SELECT now()` / `_advance_watermark` khi `since is not None` (visitor_aggregator.py:490-492, 539-540). Full **không stamp**.
6. Comment events.py:949-950 ("which then stamps") là **sai so với code**.

Trace B — `_aggregation_sweep_job` → `_sweep_one_site`:

1. Cùng debounce `SET NX EX` 60s (scheduler.py:458).
2. Luôn `aggregate_visitors_for_site(..., since=None)` (scheduler.py:496-500). **Cấm stamp** — khớp plan Phase 1.
3. `finally` chỉ `release(sweep_pending)` (scheduler.py:505-508), không giữ debounce hết lúc query chạy.

Hệ quả: Phase 1 stamp ở **caller ingest** là điều kiện cần để incremental bắt đầu. Sweep **không** bootstrap fleet. Debounce **không** phải mutex hết thời gian full recompute. Các finding dưới dựa trên trace này.

---

## Finding 1: Debounce 60s không khóa hết full recompute — G1 double-count sau stamp

- **Severity:** Critical
- **Location:** Phase 1, sections "Architecture", "Risk Assessment" ("25 site full cùng lúc… debounce 60s"); Phase 1 Success Criteria "Prod soak: không double-count pageviews"
- **Flaw:** Plan coi `agg:debounce:{site_id}` là khóa tuần tự ingest vs sweep cho cả lần full. Code là cooldown `SET NX EX` 60s, không gia hạn, không `release` khi xong. Sweep không vào `_aggregating` (set in-memory chỉ ingest). Sau bootstrap stamp, ingest đi nhánh **ADD**; sweep vẫn **SET**. Hết 60s, ingest incremental chạy song song sweep full → `total_pageviews` cộng dồn lên bản SET chưa commit / commit sau đè sai.
- **Failure scenario:** Flag ON, canary đã stamp. Sweep hourly full 90 ngày. Ở x20 (~66k events/ngày × 90) query >> 60s. Giây 61 một batch ingest lấy debounce, `since=watermark`, `_bulk_upsert_visitors_incremental` ADD trong lúc sweep SET cùng hàng visitor. Đây đúng failure G1 mà capacity-hardening E17 mô tả (full-vs-incremental). Soak 24h trên ~3.3k events/ngày (full < 60s) **không** bắt được. Success criterion "không double-count" xanh giả.
- **Evidence:**
  - Code: `apps/api/services/aggregation_debounce.py:38-44` (`SET NX EX`); `apps/api/routers/events.py:938-952` (acquire rồi aggregate, không release); `apps/api/jobs/scheduler.py:458-500` (cùng TTL, `since=None`); `apps/api/config.py:128-131` (`aggregation_min_interval_seconds: int = 60`); `apps/api/services/visitor_aggregator.py:526-527` vs `499-524` (incremental ADD vs full SET); `apps/api/jobs/scheduler.py:444-450` (E17: full racing incremental inflates counters).
  - Plan: Phase 1 Risk "25 site full cùng lúc lúc flip | Sequential sweep sẵn; bootstrap per-ingest; debounce 60s"; Success "không double-count pageviews trên site canary".
- **Suggested fix:** Debounce phải là mutex hết thời gian chạy (gia hạn TTL / lock token + `release` trong `finally`), và sweep phải tham gia cùng lock với ingest. Soak bắt buộc một site synthetic có full recompute > 2× TTL. Không dùng soak traffic hiện tại làm chứng minh x20.

## Finding 2: Trần site Phase 3 không chặn disk/CPU — flag-but-store 204, test cấm 429

- **Severity:** Critical
- **Location:** Phase 3 Overview / Requirements ("một site không ăn hết disk/CPU"); Success Criteria "Site ceiling ON … có test 429"; Risk "Ceiling thấp → false 429"; `plan.md` Red Team "Site ceiling 3000/min là placeholder"
- **Flaw:** Trần site **không** 429. `site_ceiling_tripped` cố ý không dùng decorator `@limit`. Trip → vẫn 204, vẫn INSERT, chỉ `is_flagged_abuse=True`. Aggregation SQL vẫn đọc mọi row `events` (lookback/LAG); disk vẫn lớn. Requirement Phase 3 và AC "test 429" mâu thuẫn với contract đã lock (Option C) và với test hiện có `assert 429 not in statuses`.
- **Failure scenario:** Tenant/attacker xoay IP, vượt p99×5. Plan bật `SITE_INGEST_LIMIT_ENABLED`. Operator thấy "ceiling ON" tưởng disk an toàn. Mọi batch vẫn 204, `events` phình tới Free 500 MB read-only. Visitor rollup loại flagged (FILTER `NOT is_flagged_abuse`) nên dashboard "ổn" trong khi disk chết. Trigger Phase 3 "429 rate" đứng yên vì không có 429.
- **Evidence:**
  - Code: `apps/api/services/rate_limiter.py:67-74` ("Deliberately NOT a slowapi `@limit` decorator: a decorator hard-rejects with 429, while the locked design … is Option C (flag-but-store)"); `apps/api/routers/events.py:351-356` ("a tripped signal NEVER rejects the request … rows are still written"); `tests/integration/test_ingest_abuse_hardening.py:306-357` (`assert 429 not in statuses`, `assert set(statuses) == {204}`).
  - Plan: Phase 3 Requirements "một site không ăn hết disk/CPU"; Success "có test 429"; Risk "false 429 khách thật".
- **Suggested fix:** Hoặc đổi AC: trần = flag-but-store, **không** bảo vệ disk — thêm hard-reject/quota bytes riêng; hoặc thay Option C bằng 429 thật và viết lại test abuse. Không để "test 429" và flag-but-store cùng phase.

## Finding 3: Flip flag prod = N full song song — sweep tuần tự không serialize ingest

- **Severity:** High
- **Location:** Phase 1 Implementation step 6 + Risk "25 site full cùng lúc"; Architecture "bootstrap per-ingest"
- **Flaw:** Watermark chỉ stamp từ ingest caller sau full (Phase 1). Sweep **cấm** stamp. Soak 1 site canary không stamp các site còn lại. Flip Railway `AGGREGATION_INCREMENTAL_ENABLED=true` → mọi site watermark NULL. `_aggregating` và debounce là **per-site**. Pool mặc định 3+2=5. 25 site ingest cùng lúc = 25 `asyncio.create_task(_background_aggregate)` full-history trên 5 connection.
- **Failure scenario:** Canary 24h xanh. Operator bật flag prod. 25 site có traffic trong phút đầu. 25 full SQL + `_resolve_companies` (await, limit 20 lookup) tranh pool. Ingest p95 nhảy; deploy overlap thêm container thứ hai (debounce 60s, `_aggregating` không cross-process). Đúng lúc plan tuyên bố "điểm gãy là aggregation full-history".
- **Evidence:**
  - Code: `apps/api/routers/events.py:554-563` (`if site_id not in _aggregating` — per site, rồi `create_task`); `apps/api/jobs/scheduler.py:496-500` (sweep `since=None`, không stamp); `apps/api/jobs/scheduler.py:520-524` (sweep sequential "one open session at a time"); `apps/api/config.py:90-91` (`db_pool_size=3`, `db_max_overflow=2`); `apps/api/models/database.py:70-71`.
  - Plan: Phase 1 Architecture "sweep … MUST NOT stamp"; Risk "Sequential sweep sẵn; bootstrap per-ingest"; step 6 "Railway production set `AGGREGATION_INCREMENTAL_ENABLED=true`".
- **Suggested fix:** Job bootstrap một lần: sequential full + stamp (hoặc stamp từ sweep **một lần** khi NULL). Chỉ flip flag sau khi `last_aggregated_at IS NOT NULL` cho mọi site có events. Không stamp-from-ingest-only.

## Finding 4: Retention 24h không có boot offset — disk Free dựa trên job có thể không bao giờ chạy

- **Severity:** High
- **Location:** Phase 2 Overview / Implementation step 4 / Success "Retention: evidence log 7d request_logs / 90d events trong 48h"
- **Flaw:** APScheduler in-memory. Job interval `hours=24`, **không** `next_run_time` boot offset. Chính file đó giải thích vì sao `aggregation_sweep` **phải** có offset 90s: restart trước khi interval trôi → job không bao giờ fire. Retention không được offset đó. Scheduler chỉ log `retention_purge_job_complete` khi `result.get("deleted")` truthy — purge 0 row = im lặng. Plan bảo "nếu job không chạy: sửa registration" trong khi job **đã** register; lỗi là first-fire + deploy cadence.
- **Failure scenario:** Railway redeploy nhiều lần/ngày. Interval 24h reset mỗi boot. 48h không có `retention_purge_complete`. Disk 424/500 MB tiếp tục lớn. Operator grep đúng tên log plan ghi, hoặc grep scheduler event khi `deleted=0`, kết luận "không thấy log = chưa sửa registration", thêm log, vẫn không xóa.
- **Evidence:**
  - Code: `apps/api/jobs/scheduler.py:630-641` (`_retention_purge_job`, không `next_run_time`); `apps/api/config.py:1221` (`retention_purge_interval_hours: int = 24`); `apps/api/jobs/scheduler.py:61-85` (`if result.get("deleted"): logger.info("retention_purge_job_complete", …)`); `apps/api/jobs/scheduler.py:723-731` (aggregation_sweep `next_run_time` +90s, comment "would NEVER fire"); `apps/api/services/retention.py:156` (`retention_purge_complete` chỉ sau vòng xóa).
  - Plan: Phase 2 step 4 "Verify retention scheduler misfire + last success in prod logs. Nếu job không chạy: sửa registration, không viết purge mới"; Success "evidence log … trong 48h".
- **Suggested fix:** Gắn `next_run_time` sớm như các sweep khác; log `status=ok deleted=0` mỗi lần chạy; AC dựa trên `scheduler last-success`, không phụ thuộc `deleted>0`.

## Finding 5: `statement_timeout` trên pool chung — bleed 30s vào sweep hoặc 5 phút vào request

- **Severity:** High
- **Location:** Phase 3 Architecture / Implementation step 3 / Success "Request `pg_sleep(31)` bị kill; sweep full … không timeout"
- **Flaw:** Một `engine` + `async_session` cho ingest và sweep. Timeout gắn `connect_args` `server_settings` (database.py:45-46, 74-76). Plan: "session `SET statement_timeout` cao hơn hoặc engine riêng". `SET` trên connection pooled **không** RESET khi trả pool (SQLAlchemy default return = rollback, không `RESET ALL`). Sweep SET ≥5 phút rồi trả connection → request kế thừa 5 phút (`pg_sleep(31)` test xanh giả). Request SET 30s rồi trả → sweep 30s chết. Engine riêng gấp đôi pool (5+5) lúc deploy overlap — comment cũ 15-client từng gây EMAXCONNSESSION; live `max_connections=60` đỡ hơn nhưng plan không khóa pool math cho engine thứ hai.
- **Failure scenario (A):** Ship override sweep trước, operator bật `DB_STATEMENT_TIMEOUT_MS=30000`. Sweep full site lớn bị kill. `intent_score` đóng băng — đúng risk Phase 3 đã ghi, nhưng xảy ra nếu SET quên/mất trên checkout mới. **(B):** SET 5 phút leak sang request. Statement timeout "30s" trên giấy, query ingest treo 5 phút, pool 5 slot kiệt.
- **Evidence:**
  - Code: `apps/api/models/database.py:28-46, 59-78` (một engine, timeout trong `connect_args`); `apps/api/jobs/scheduler.py:495-500` (`async with async_session()`); `apps/api/config.py:60-66` ("NOTE the full-recompute repair sweep … still runs an unbounded query"; default `db_statement_timeout_ms: int = 0`); `apps/api/config.py:67-69` (15-client cap / deploy overlap).
  - Plan: Phase 3 Architecture "`db_statement_timeout_ms=30000` trên engine request. Sweep/retention: session SET … hoặc engine riêng"; step 3 "chỉ sau Phase 1 soak xanh".
- **Suggested fix:** Engine/sessionmaker **riêng** cho sweep+retention, `statement_timeout` trong `connect_args` (không SET trên pool chung), pool_size của engine đó tính vào công thức overlap. Cấm bật Railway timeout trước khi binary đó live. Test: checkout connection sau sweep, `SHOW statement_timeout` phải là 30s trên request engine.

## Finding 6: Caller stamp sau `aggregate_visitors_for_site` — stamp nằm sau `_resolve_companies`

- **Severity:** High
- **Location:** Phase 1 Architecture "stamp thuộc caller"; Implementation step 2 "sau full commit thành công"
- **Flaw:** `await db.commit()` nằm **trong** aggregator (visitor_aggregator.py:529). Caller không thấy điểm đó. Full path **await** `_resolve_companies` (limit 20 IP lookup) trước khi return (547-549). Stamp ở `events.py` sau lời gọi = stamp sau resolve. `run_started_at` chỉ tồn tại khi `since is not None` (490-492) — caller full không lấy được clock "trước read" trừ khi thêm API mới. Comment Site model (site.py:99-102) và events.py:949-950 đã nói "full rồi stamp" — sai; plan lặp pattern đó ở caller dễ stamp bằng `datetime.utcnow()` lúc return → cửa sổ `created_at > wm` **nuốt** events giữa read và stamp (đúng điều step 2 muốn tránh).
- **Failure scenario:** Flag ON, site NULL watermark. Full SQL 40s, resolve 20 IP thêm 30s. Stamp `now()` lúc return. Events ingest lúc giây 10 có `event.ts` < stamp return → incremental sau bỏ (`created_at > wm`). Sweep hourly SET mới chữa. Soak "incremental=true" xanh, counters thiếu đến sweep. Deploy overlap: container 2 không có `_aggregating` của container 1; debounce 60s đã hết lúc đang resolve; watermark vẫn NULL → full thứ hai.
- **Evidence:**
  - Code: `apps/api/services/visitor_aggregator.py:529-549` (commit → revive → watermark chỉ nếu `since` → `_resolve_companies` await); `apps/api/services/visitor_aggregator.py:763-791` (limit 20, `resolve_company_cached`); `apps/api/routers/events.py:946-952` (caller không stamp hôm nay); `apps/api/models/site.py:99-102` ("the next run does a full recompute and then stamps this").
  - Plan: Phase 1 Architecture "full recompute (since=None) → stamp last_aggregated_at = now() taken BEFORE read"; "Stamp thuộc caller (`events.py` / `aggregation_tasks.py`)"; step 2 "sau full commit thành công, stamp now() lấy trước query".
- **Suggested fix:** Stamp **bên trong** aggregator ngay sau commit full **chỉ khi** caller truyền `bootstrap_watermark=True` (sweep không truyền). Sample `SELECT now()` trước SQL, giống incremental. Đừng để caller "sau return". `aggregation_tasks.py` không phải live cadence (xem Finding 8) — đừng coi là đường bootstrap.

## Finding 7: Phase 2 AC 422 vs ingest nuốt ValidationError thành 400

- **Severity:** High
- **Location:** Phase 2 Architecture "422 nếu thiếu"; Success "Ingest thiếu event_id → 422"; `plan.md` Red Team "400 + log"
- **Flaw:** `/ingest` không để FastAPI trả 422. `_parse_event_batch` → `EventBatch(**data)`; `except Exception: return 400`. Required `event_id` → `ValidationError` → **400**. Umbrella nói 400; phase nói 422. Test viết 422 sẽ fail hoặc bị sửa thành assert sai contract. Pixel cũ / hàng `localStorage` không `event_id` bị 400 cả batch (`EventBatch.events` min 1, một event thiếu id đổ cả batch) — plan "0 row" đúng, nhưng client chỉ thấy 400 giống JSON hỏng.
- **Failure scenario:** Ship schema required. Test AC 422 đỏ. Execute "sửa" endpoint bỏ try/except để lấy 422 → đổi contract 400 hiện tại của parse lỗi (events.py:198-201, stash comment "endpoint's own parse produces the 400"). Hoặc test bị đổi 422→400 im lặng, runbook operator grep 422 không thấy reject.
- **Evidence:**
  - Code: `apps/api/routers/events.py:114-125, 198-201`; `apps/api/schemas/events.py:24` (`event_id: str | None = Field(None, max_length=64)`); `apps/api/schemas/events.py:126-129`; `apps/pixel/src/tracker.js:289-290` (pixel mới mint uuid).
  - Plan: Phase 2 Architecture "422 nếu thiếu"; Success "→ 422, 0 row"; `plan.md` Red Team "400 + log".
- **Suggested fix:** Chốt **một** status (khớp `_parse_event_batch`: 400, hoặc ValidationError riêng 422). Sửa umbrella vs phase. Test fixture event thiếu id + batch mixed (một event thiếu) phải được ghi rõ: reject cả batch hay drop từng event.

## Finding 8: Watermark = DB `now()`, cửa sổ = client `event.ts` — double-count/miss; soak so với sweep SET

- **Severity:** Medium
- **Location:** Phase 1 Implementation step 2 "`created_at > watermark`"; Success "sai số lookback OK, không double"; Site comment "no event is ever merged twice"
- **Flaw:** Incremental filter `WHERE created_at > :since` (visitor_aggregator.py:351). `created_at` ghi từ `event.ts` client (events.py:459). Watermark là `SELECT now()` server (visitor_aggregator.py:492). Không upper-bound `run_started_at`. Clock client lệch trước/sau server → miss hoặc ADD lại row đã nằm trong full SET. Sweep hourly SET **che** double-count nếu đo sau sweep. Lookback 30 phút chỉ cho LAG, không trừ pageviews (window_clause vẫn `created_at > :since`).
- **Failure scenario:** Bootstrap stamp `now()` trước read. Pixel `ts: now()` JS lệch +2s so với PG. Event đã có trong full snapshot có `created_at > stamp` → ingest incremental ADD. `total_pageviews` > `count(*)` pageview đến sweep. Soak "so sánh total_pageviews vs count events 24h" chạy sau `aggregation_sweep` → SET chữa, AC xanh. Hoặc client ts chậm: event lúc full đang chạy có ts < stamp → miss đến sweep.
- **Evidence:**
  - Code: `apps/api/routers/events.py:459` (`created_at=event.ts.replace(...)`); `apps/pixel/src/tracker.js:379` (`ts: now()`); `apps/api/services/visitor_aggregator.py:338-351, 488-540`; `apps/api/models/site.py:101-102` ("so no event is ever merged twice").
  - Plan: Phase 1 step 2 "Events giữa read và stamp vào lần incremental sau (`created_at > watermark`)"; Success "sai số lookback OK, không double".
- **Suggested fix:** Cửa sổ nửa-mở trên **server** `created_at` (DB default `now()`) hoặc filter `created_at > wm AND created_at <= run_started_at` với `created_at` server. Soak so sánh **trước** sweep kế tiếp, không sau.

## Finding 9: `aggregation_tasks.py` không phải live bootstrap — plan gắn nhầm

- **Severity:** Medium
- **Location:** Phase 1 Related Code Files "Modify: `aggregation_tasks.py` (~31-42) — cùng bootstrap"
- **Flaw:** File tự ghi không có consumer (không worker, không beat). Live repair = APScheduler `aggregation_sweep`, và sweep **cấm** stamp. Sửa Celery task không bootstrap prod. Tạo ảo giác "hai caller stamp".
- **Failure scenario:** Execute stamp trong `_aggregate_all`, quên/không đủ ingest caller. Flag ON, sweep không stamp, ingest comment vẫn sai → full mãi (đúng lỗ hổng umbrella). Hoặc bật nhầm `celery_worker_enabled` + beat → **hai** full cadence (đúng HARD guard capacity-hardening: cấm `-B` khi đã có APScheduler sweep).
- **Evidence:**
  - Code: `apps/api/tasks/aggregation_tasks.py:19-28, 37-43`; `apps/api/config.py:106-114` (`celery_worker_enabled: bool = False`); `apps/api/services/celery_app.py:42-57` (beat schedule `aggregate_all_sites` dormant).
  - Plan: Phase 1 "Modify: `apps/api/tasks/aggregation_tasks.py` (~31-42) — cùng bootstrap".
- **Suggested fix:** Gạch `aggregation_tasks.py` khỏi Phase 1 live path. Bootstrap chỉ ingest **hoặc** one-shot sweep có `bootstrap_stamp`. Giữ cấm Celery beat.

---

## Fact Checker — claims vs repo

| Claim | Verdict |
|---|---|
| `visitor_aggregator.py:539-540` full không stamp | TRUE |
| `events.py:947-952` NULL wm → `since=None` | TRUE (947-952) |
| `test_visitor_aggregation_incremental.py:331` full must not stamp | TRUE |
| Pixel `tracker.js:290` `uuid()` | TRUE |
| Flag default `aggregation_incremental_enabled=False` | TRUE (`config.py:127`) |
| Redis `socket_timeout=5` đã ship | TRUE (`redis_client.py:33`) |
| `ingest_trust_cf_connecting_ip=True` | TRUE (`config.py:274`) — **không** biến trần thành 429 (Finding 2) |
| Unique `uq_events_event_id` global | TRUE (`models/event.py:80`, baseline migration) |
| 682 NULL / disk 424 MB | TRUE trong research MCP snapshot, **không** re-verify live ở plan cook |
| `aggregation_tasks.py` cùng live bootstrap | FALSE (Finding 9) |
| Trần site → 429 | FALSE (Finding 2) |
| Debounce khóa hết lần aggregate | FALSE (Finding 1) |
| Ingest thiếu `event_id` → 422 | FALSE với handler hiện tại (Finding 7) |
| Comment pool 15 stale; live `max_connections=60` | TRUE theo research 260817-2335 §connection cap — Phase 3 sửa comment là fact-ok |
| `ip_org_rpki_ingest_enabled` default False | TRUE (`config.py:857`); job tồn tại (`scheduler.py:787-796`) — "cấm load" chỉ là flag, không phải guard disk |

---

## Disposition for planner

Không EXECUTE Phase 1 cho đến khi Finding 1 (mutex thật) và Finding 3 (bootstrap fleet, không ingest-herd) có chỗ trong plan. Phase 3 không được ship với AC 429 khi code là flag-but-store. Phase 2 retention AC phải bắt boot-offset, không "sửa registration".
