---
title: GetBeam PROD topology vs splittrip lab beacon
date: 2026-08-18 00:38
severity: medium
component: vercel, railway, supabase, cloudflare-worker, fetch-beacon, docs
status: documented — live MCP + operator correction
---

## Context

Session hỏi Vercel đã login chưa, rồi “GetBeam PROD gắn gì”. Lượt đầu ghi Cloudflare Worker
`beam-agent-beacon-splittrip` (`splittrip.nhantown.com`) vào bảng PROD vì MCP CF chỉ list
Worker đó. Operator sửa: **trang đó là site test, không phải source main GetBeam.**

## What happened

Live MCP 2026-08-18 (Vercel / Railway / Supabase / Cloudflare bindings):

| Lớp | PROD | Lab — đừng gộp |
|-----|------|----------------|
| Web | Vercel `retarget-agent` → `getbeam.fyi` | `splittrip.nhantown.com`, `beamlab.nhantown.com` |
| API | Railway `retarget-agent` → `api.getbeam.fyi` | `beam-api.nhantown.com` (tunnel) |
| DB | Supabase `hylcleqxlkdblibpdhhm` (org `vercel_icfg_…`) | Docker local / lab DB |
| Fetch-beacon | Vercel middleware `apps/web/src/middleware.ts` | Worker `beam-agent-beacon-splittrip` |

```text
splittrip.nhantown.com  →  CF Worker splittrip  →  beam-api.nhantown.com   (lab)
getbeam.fyi             →  Vercel middleware    →  api.getbeam.fyi         (PROD)
```

Wrangler lab Worker: route chỉ `splittrip.nhantown.com/*`, `BEAM_API_BASE=https://beam-api.nhantown.com`,
`BEAM_SITE_ID=site_e3a2c56e01ed`.

Vercel Git: `julleycode/get-beam` auto-deploy `main`. Author `julleycode` → READY. Author
`nhantochi95` (kể cả `dev_nhantc2`) thường **BLOCKED** trên team `tranthaiwork-droid`.

## Decision

Tách lab vs PROD trong `process/context/all-context.md` + `docs/` để agent sau không coi Worker
splittrip là edge của `getbeam.fyi`. MCP CF “thấy” Worker ≠ Worker phục vụ PROD.

## Follow-up

- Pixel Worker `beam-pixel` (`pixel.getbeam.fyi`) không nằm trên CF MCP account đang login — chưa
  re-verify live script name trên đúng account.
- UAT Railway/Vercel riêng vẫn chưa wired (`docs/local-uat-prod.md`).
---
