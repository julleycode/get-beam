---
title: AI detection live validation — local probes + real ChatGPT
date: 2026-07-30 11:26
severity: high
component: agent detection, attribution, resolution waterfall
status: ongoing
---

## Context

Phiên validate live: Beam có detect traffic AI và “ai đứng sau AI” không? Stack local + probe thật từ ChatGPT; một session Claude trước bị dừng giữa chừng — entry này gom kết luận đã có.

Mục tiêu thực tế: không phải named individual mà company-level attribution qua handoff marker và resolution sau đó.

## What worked

**Local probe chain (17/17):** Gateway surfaces ổn; F2 `?_bam=` mint→click→`agent_handoff_links` method=marker confidence cao; cache posture đúng; cross-tenant replay bị chặn; F4/F12/F13 và multi-tenant security pass.

**Real ChatGPT-User on-demand:** Ba visit thật tới `/`, `/llms.txt`, `/` — chứng minh ChatGPT đọc `llms.txt` khi crawl site (không chỉ homepage).

**Harness đã land trên main:**
- `53fc573` — pin `AGENT_*` env cho probe harness
- `486b47a` — UTF-8 fix cho Windows probe scripts
- `b5f4311` — IP ranges chuyển sang `runtime/` (không còn path cứng trong harness)

## What did NOT work / limits

**`identified_visitors=0` — attribution ≠ identity resolution.** Marker chạy tới handoff rồi dừng. Resolution waterfall không ưu tiên `ai_source`/`handoff`; provider keys trống → không có “named visitor” dù detect AI đúng.

**No click → no handoff.** User đọc answer trong app ChatGPT, không follow link → không có `agent_handoff_links` row.

**Beacon không IP → ua-only mãi** trên path đó; không đủ để resolve company.

**Chưa verify wild:** ChatGPT có preserve `?_bam=` qua redirect/rewrite ngoài lab chưa biết.

**F14 Web Bot Auth** chưa build.

**Sweep gap:** `agent_fetch_events.verification_method` không được update bởi sweep — chỉ `agent_visits` được cập nhật.

## The brutal truth

Detect AI traffic: có, local và một phần real-world. “Who behind the AI” như tên người: không — và đó không phải bug một dòng mà gap thiết kế giữa detection, handoff, và resolution. Session Claude cắt giữa chừng khiến cảm giác “gần xong” nhưng thực tế identity layer chưa có.

## Decisions / expectations

“Ai đứng sau AI” trong Beam = **company-level attribution** (handoff marker + resolution sau), không phải cá nhân có tên.

**Priority order:**
0. Harness fixes — **done** (`53fc573`, `486b47a`, `b5f4311`)
1. Wild marker survival — test `?_bam=` qua ChatGPT link thật ngoài lab
2. Resolution — ưu tiên visitor có `ai_source`/handoff; fill provider keys
3. F14 Web Bot Auth — sau khi (1) có kết quả

## Next steps

**Operators:**
- Chạy wild test: publish link có `?_bam=` qua ChatGPT answer, verify click log + handoff row trên prod/staging tunnel
- Probe ChatGPT với page có CTA click rõ — in-app read không tạo handoff
- Theo dõi `identified_visitors` sau bước resolution, không kỳ vọng >0 trước (2)

**Devs:**
- Resolution waterfall: priority cho AI-sourced / handoff visitors
- Populate provider keys từ IP range + UA signals đã có trong `runtime/`
- Sweep: update `agent_fetch_events.verification_method` đồng bộ với `agent_visits`
- F14 spec/implement sau wild marker test

**Status:** Detection validated locally + partial real; identity resolution blocked — không phải harness regression.
