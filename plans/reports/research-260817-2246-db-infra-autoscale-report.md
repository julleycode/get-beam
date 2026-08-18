---
type: researcher
date: 2026-08-17
topic: db-infra-autoscale
---

# Research: DB + infra auto-scale, rẻ nhất, khớp getBeam

**Timestamp:** 2026-08-17 22:46 ICT  
**PROD hiện tại:** Supabase Free `retarget-agent` 424/500 MB (85%). `ip_org_prefixes` 255 MB. Events 197k / 124 MB. Railway MCP không đọc được.

## Executive Summary

Hai thứ “auto-scale” khác nhau. getBeam đang cháy **disk**, không cháy CPU.

| Loại | Ai thật sự làm | getBeam cần tuần này? |
|---|---|---|
| Disk auto-scale | **Supabase Pro** (90% → +50%, max 60 TB) | Có — còn 76 MB là read-only |
| Compute auto-scale | **Neon** (min–max CU, scale-to-zero) | Không gấp. API + pixel + APScheduler **always-on** |

**Chọn:** nâng **Supabase Pro ~$25/tháng**. Zero migrate. Disk tự nở. Backup 7 ngày. Storage `blog-images` giữ nguyên. Session pooler :5432 giữ nguyên (advisory lock).

Neon rẻ hơn trên giấy (~$20 always-on 0.25 CU) nhưng: migrate, cold-start nếu scale-to-zero, pooled endpoint **phá** session advisory lock, mất Storage. Railway Postgres **không** auto-scale compute; volume $0.15/GB chỉ là disk. RDS/Cloud SQL đắt hơn, YAGNI.

## Research Methodology

- Sources: 5 web searches (cap skill). Gemini off (`skills.research.useGemini` absent).
- Date range: official docs 2025–2026.
- Terms: Neon pricing autoscaling, Supabase Pro disk, Railway volume Postgres, PgBouncer advisory locks, Neon vs Supabase vs Railway 2026.
- Eval: official pricing > aggregator blogs. Cross-check lock constraint với `apps/api` (retention advisory lock + `config.py` cấm transaction pooler :6543).

## Key Findings

### 1. getBeam constraints (không đổi)

- Postgres + GiST (`ip_org_prefixes`). Không MySQL/PlanetScale.
- Session advisory locks giữ **qua nhiều statement** (`retention.py`). Transaction pooler = hỏng. Neon pooled = PgBouncer transaction mode = **session advisory locks Never**.
- API Railway always-on (keep-warm vì cold-start 15–30s đã đau). Scale-to-zero DB = cùng class lỗi ingest.
- Auth = Clerk. Storage blog = Supabase. Pixel = CF. Web = Vercel.
- Pool app 3+2 vì cap ~15 client (Supabase).

### 2. Pricing (official, 2026)

**Supabase** — [pricing](https://supabase.com/pricing) · [database-size](https://supabase.com/docs/guides/platform/database-size)

- Free: 500 MB DB → read-only. Pause 7 ngày idle. Không backup.
- Pro: **$25/org** + $10 compute credit (1 Micro 24/7). 8 GB disk rồi **$0.125/GB**. Disk auto-scale lúc 90% (+50%, 4 lần/24h). Backup 7 ngày. Compute **cố định** — không autoscale CPU. Spend cap mặc định ON.

**Neon** — [pricing](https://neon.com/pricing) · [serverless](https://neon.com/docs/introduction/serverless)

- Free: 0.5 GB + 100 CU-h. getBeam 0.42 GB → Free Neon cũng sát trần.
- Launch: **không min spend**. Compute **$0.106/CU-hour**. Storage **$0.35/GB-month**. Autoscale tới 16 CU. Scale-to-zero 5 phút (tắt được).
- Always-on 0.25 CU: `0.25 × 730h × $0.106 ≈ $19` + ~$0.35 storage ≈ **$20/tháng**.
- Pooled host `-pooler`: transaction mode. Direct host cho migrate / SET / **session advisory locks**. [Neon pooling](https://neon.com/docs/connect/connection-pooling)

**Railway** — [plans](https://docs.railway.com/pricing/plans) · [volumes](https://docs.railway.com/volumes/reference)

- Hobby $5 / Pro $20 = floor, cộng usage.
- Volume **$0.15/GB-month**. Live resize. Hobby volume cap 5 GB.
- Postgres = container + volume. **Không** compute autoscale. Không HA. Backup tự lo.
- Tiny PG ước lượng: RAM+CPU idle + 1 GB disk ≈ vài $/tháng **cộng** bill API hiện tại. Rẻ disk, yếu managed.

**Loại:** Fly self-manage, RDS/Aurora Serverless, Cloud SQL — đắt / ops nặng. Bỏ.

### 3. Best practices (khớp repo)

- Prod always-on ingest: **tắt scale-to-zero**.
- Advisory lock đa-statement: **direct hoặc session pooler**, không transaction pooler.
- Disk emergency: đừng ingest `rpki_roas` trên Free (bảng đang 0 row).
- ip-org 255 MB là dataset tĩnh — truncate nếu flag OFF và chưa mua disk.

### 4. Security

- Free: không backup. Mất project = mất PII.
- Pro: backup 7 ngày. PITR Supabase $100/7 ngày — không cần.
- RLS public off (API đi `DATABASE_URL`, không anon) — không phải lý do đổi vendor.
- Railway PG: tự snapshot. Neon Launch: restore add-on $0.20/GB-month.

### 5. Performance

- getBeam bottleneck = **full-history aggregation + disk quota**, không vCPU DB.
- Neon cold start (scale-to-zero) xung đột pixel ingest.
- Neon compute scale-up hữu ích **sau này** nếu query nặng; tuần này không.
- Cùng region: Neon/Supabase `ap-southeast-1` khớp Railway/Supabase hiện tại. Railway PG cùng project = latency thấp nhất, không autoscale.

## Comparative Analysis

```
                 Disk auto     Compute auto    Always-on $     Migrate    Storage blog    Locks OK
Supabase Free    no (500MB)    no              $0 (sắp chết)   n/a        yes             session :5432
Supabase Pro     YES           no              ~$25            none       yes             session :5432
Neon Launch      bill/GB       YES             ~$20 nếu 0.25CU dump/restore  no (R2/CF)    chỉ DIRECT
Railway PG       live resize   no              ~$5+usage       dump       no              yes (direct)
```

“Gọn một vendor Railway” ≠ volume trên API. Vẫn 2 service (API + PG).

## Implementation Recommendations

### Quick Start (làm tuần này)

1. Upgrade org Supabase → Pro. Tắt panic disk. Giữ `DATABASE_URL`.
2. Tắt Spend Cap chỉ khi disk > 8 GB (hiện 0.42 GB — không).
3. Không load `rpki_roas` cho tới khi Pro live.
4. Không đổi Railway topology.

### Nếu sau này cần compute auto-scale

Neon Launch, **disable scale-to-zero**, min 0.25 / max 2–4 CU, **direct** connection string. Migrate `pg_dump` → Neon. Storage: Cloudflare R2 hoặc giữ Supabase chỉ Storage (không gọn). Viết lại pooler note trong `config.py`.

### Common Pitfalls

- Neon `-pooler` + `pg_advisory_lock` session = lock dính pid kế / job sweep vỡ.
- Neon Free 0.5 GB = lặp cliff 500 MB.
- Scale-to-zero + keep-warm API: API sống, DB ngủ → ingest timeout.
- Railway volume trên `retarget-agent`: không phải Postgres.

## Cost — getBeam size hôm nay (~0.42 GB, always-on)

| Phương án | $/tháng | Disk headroom | Ghi chú |
|---|---|---|---|
| Ở Free | 0 | 76 MB rồi read-only | Không phải option |
| **Supabase Pro** | **~25** | 8 GB rồi $0.125/GB | **KISS, mạnh disk** |
| Neon 0.25 CU always-on | ~20 | $0.35/GB | Rẻ hơn, migrate + mất Storage |
| Neon scale-to-zero | vài $ | $0.35/GB | Cấm — ingest |
| Railway PG Hobby | ~5–15 + API | 5 GB hobby | Không compute auto-scale |
| RDS/Aurora | $15–50+ | lớn | Overkill |
| OCI Always Free ADB | $0 | 20 GB/instance | **Oracle SQL, không Postgres** — rewrite app |
| OCI Ampere self-host PG | $0 | ~200 GB block | Tự làm DBA. ARM 2 OCPU/12 GB. Reclaim idle. Không auto-scale |
| OCI Database with PostgreSQL | compute+storage paid | dynamic storage | Managed PG, **không Always Free**. Đắt hơn Pro cho size này |

## Addendum: Oracle Cloud (OCI) — 2026-08-17

Always Free ([docs](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)):

- 2× Autonomous AI Database: 1 OCPU + **20 GB, cannot scale**. Workload = ATP/JSON/APEX/Lakehouse = **Oracle Database**, không Postgres.
- Ampere A1: **2 OCPU + 12 GB** (cắt nửa từ 4/24; enforce ~18 Aug 2026). AMD micro 2× 1 GB.
- Idle reclaim: CPU + net + mem (A1) đều <20% trong 7 ngày → thu hồi VM.
- Capacity: region hay hết ARM (“Out of host capacity”).

Ba cửa OCI:

1. **Autonomous DB Always Free** — cấm. App dùng `asyncpg`, JSONB, `inet` GiST, `pg_advisory_lock`, Alembic PG. Đổi engine = viết lại backend.
2. **Tự cài Postgres trên Ampere** — $0. Bạn là DBA (backup, patch, firewall 5432, ARM Playwright nếu dời API). Không compute auto-scale. Quota Oracle đổi im lặng. Pixel ingest always-on thì phải fake load kẻo reclaim — trái KISS.
3. **OCI Database with PostgreSQL (paid)** — managed, storage động. Billing = shape OCPU + optimized storage + VPU. Không free. Không rẻ hơn Supabase Pro ở 0.42 GB.

Kết: OCI “rẻ” chỉ khi chấp nhận **tự host + rủi ro reclaim/quota**. Không phải hạ tầng mạnh. Không khớp “DB auto-scale”.

## Verdict (YAGNI)

**Pro tuần này.** getBeam cần disk auto-scale + backup + không đụng code. Compute auto-scale là bài toán năm sau, vendor = Neon lúc đó.

Không convert Railway volume. Không Neon Free. Không Aurora. **Không OCI Autonomous. Không self-host Ampere cho prod.**

## Resources

- https://supabase.com/pricing
- https://supabase.com/docs/guides/platform/database-size
- https://neon.com/pricing
- https://neon.com/docs/connect/connection-pooling
- https://docs.railway.com/pricing/plans
- https://www.pgbouncer.org/features.html (session advisory locks × transaction pool)

## Unresolved

- Bill Railway hiện tại (Hobby vs Pro) — MCP Railway lỗi.
- `IP_ORG_LOOKUP_ENABLED` trên prod? Truncate 255 MB chỉ an toàn nếu OFF.
- Neon `ap-southeast-1` availability exact vs getBeam latency — chưa probe.
- Giá Neon Launch “no monthly minimum” vs blog cũ ghi $5 min — lấy official pricing page ($0 floor, pay-per-use).

## Next steps

1. Operator: nâng Pro trước khi DB > 480 MB.
2. Optional: truncate `ip_org_prefixes` nếu lookup OFF và Pro bị delay.
3. Không mở plan migrate Neon/Railway cho tới khi Pro ổn ≥ 30 ngày.
