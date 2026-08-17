---
phase: 3
title: "Tenant ceilings timeout and x20-x30 runbook"
status: pending
priority: P2
effort: S
dependencies: [1, 2]
---

# Phase 3: Tenant ceilings, timeout, and x20-x30 runbook

## Overview

Sau incremental soak: bật trần ingest theo **p99 đo được**, `statement_timeout` 30s (sweep tách timeout), và runbook operator cho x20/x30 + nâng Pro sau.

## Requirements

- Functional: một site **không ghi** thêm events khi quá trần (hard 429, 0 INSERT — Validation S1). Request-path chết 30s. Sweep không bị 30s giết (F5).
- Non-functional: không Queue, không replica 2, không Celery worker trừ khi trigger §bảng dưới.

## Architecture

F3: Option C flag-but-store **không** cứu disk. Trần site = **hard 429, không INSERT** (Validation S1). Viết lại `test_ingest_abuse_hardening.py` (hiện `assert 429 not in statuses`). Lock origin Railway → chỉ CF trước khi tin `CF-Connecting-IP`.
<!-- Updated: Validation Session 1 - hard 429 only -->

Ceiling = ~5× p99 events/min/site, không placeholder 3000.

F5: một engine hôm nay (`database.py:59-78`). Timeout request 30s **chỉ** sau `SET LOCAL` trên sweep/retention (giá trị cao) **và** `RESET`/`SET LOCAL` lại khi checkout request — cùng PR, trước khi operator set Railway `DB_STATEMENT_TIMEOUT_MS`. Không SET leak qua pool.

## Related Code Files

- Modify: `apps/api/config.py` comments pool math (live `max_connections=60`, comment "15" stale)
- Operator: Railway `SITE_INGEST_LIMIT_ENABLED`, `SITE_INGEST_LIMIT_PER_MINUTE`, `DB_STATEMENT_TIMEOUT_MS`
- Modify: `apps/api/database.py` / sweep job session — timeout override cho repair
- Tests: `tests/integration/test_db_statement_timeout.py` (đã có); thêm sweep session không inherit 30s
- Docs: `docs/deployment-guide.md` — bảng trigger (copy từ đây)

## Implementation Steps

1. Đo 7 ngày: events/min/site p99; ingest p95; disk; connections.
2. Set ceiling từ dữ liệu. Flag default code vẫn `False`. Railway ON sau khi số có.
3. `db_statement_timeout_ms=30000` **chỉ sau** Phase 1 soak xanh. Sweep: `0` hoặc ≥ 5 phút trên session đó.
4. Metrics tối thiểu: disk 60/75/85%; events/day/site; ingest p95; 429 rate; `aggregation_sweep` duration; scheduler last-success.
5. Runbook operator — nâng Pro khi: disk ≥ 85% Free **hoặc** trước khách trả tiền. Pause `buildtolaunch`. `pg_dump` custom format → R2. `DATABASE_URL` giữ `:5432`. Spend cap ON.
6. Không làm: Queue, partition `events`, replica 2, Chromium tách image, xóa keep-warm (optional sau UptimeRobot).

## Success Criteria

- [ ] Site ceiling ON: quá trần → **429**, 0 row INSERT
<!-- Updated: Validation Session 1 - hard 429 only -->
- [ ] Test site limiter, không nhầm IP `100/minute`
- [ ] Origin không nhận spoof `CF-Connecting-IP` (lock CF hoặc ignore header ngoài CF)
- [ ] Request `pg_sleep(31)` bị kill; sweep full 1 site 25-site hiện tại không timeout
- [ ] Comment pool 15-client đã sửa thành 60
- [ ] Runbook Pro + trigger x20/x30 nằm trong `docs/deployment-guide.md`
- [ ] Defaults code vẫn an toàn nếu quên set Railway

## Scale triggers (copy vào docs)

| Trigger | Action |
|---|---|
| Disk ≥ 85% quota hiện tại | Nâng Pro / xác nhận autoscale |
| Ingest p95 > 300 ms / 15 phút | Trace agg vs PG |
| Ingest p95 > 800 ms hoặc error > 1% | Incremental phải ON; Queue chỉ sau đó |
| Sustained ingest > 20 rps | Split scheduler **hoặc** replica 2 |
| Events > 50k/day × 7 ngày | Ceiling ON (nếu chưa) |
| Events > 200k/day | Lên plan partition + R2 archive — **plan mới**, không phase này |
| Scheduler last-success > 2× interval | Split worker |

x20 (66k/day) và x30 (99k/day) **không** bật hàng trên trừ p95/error. Vẫn 1 replica.

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Timeout giết sweep → `intent_score` đóng băng | Session timeout riêng |
| Ceiling thấp → false 429 khách thật | 5× p99; flag-but-store ingest abuse đã có |
| Pro autoscale quên spend cap | Bật cap trước upgrade |

## Security Considerations

Rate limit theo site+CF IP, không theo một IP edge. 429 không leak site nội bộ. Quota không đụng billing credits trừ plan đã có `site-limit-enforcement`.
