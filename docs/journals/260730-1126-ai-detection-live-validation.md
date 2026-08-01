---
title: AI detection live validation — local probes + real ChatGPT
date: 2026-07-30 11:26
severity: high
component: agent detection, attribution, resolution waterfall
status: ongoing — AI priority shipped 7b1ed33
---

## Context

Phiên validate live: Beam có detect traffic AI và "ai đứng sau AI" không? Stack local + probe thật từ ChatGPT; một session Claude trước bị dừng giữa chừng — entry này gom kết luận đã có.

Mục tiêu thực tế: không phải named individual mà company-level attribution qua handoff marker và resolution sau đó.

## What worked

**Local probe chain (17/17):** Gateway surfaces ổn; F2 `?_bam=` mint→click→`agent_handoff_links` method=marker confidence cao; cache posture đúng; cross-tenant replay bị chặn; F4/F12/F13 và multi-tenant security pass.

**Real ChatGPT-User on-demand:** Ba visit thật tới `/`, `/llms.txt`, `/` — chứng minh ChatGPT đọc `llms.txt` khi crawl site (không chỉ homepage).

**Harness đã land trên main:**
- `53fc573` — pin `AGENT_*` env cho probe harness
- `486b47a` — UTF-8 fix cho Windows probe scripts
- `b5f4311` — IP ranges chuyển sang `runtime/` (không còn path cứng trong harness)

**AI priority shipped (7b1ed33):** `resolution_runner` nay ưu tiên `ai_attributable_human.desc()` (visitor có `ai_source` OR same-site `AgentHandoffLink`) trước `intent_score.desc()`. Ranking: AI-attributed queue first. Không thay đổi emailability separation; marker vẫn không gọi write path.

## What did NOT work / limits

**Named individual: không.** Marker ships company-level attribution. Resolution queue prioritizes AI-attributed visitors (landed 7b1ed33), but **provider keys trống → resolution trả company, không cá nhân**. Ops: fill PDL/Proxycurl keys để ra "John Smith".

**No click → no handoff.** User đọc answer trong app ChatGPT, không follow link → không có `agent_handoff_links` row.

**Beacon không IP → ua-only mãi** trên path đó; không đủ để resolve company.

**Chưa verify wild:** ChatGPT có preserve `?_bam=` qua redirect/rewrite ngoài lab chưa biết.

**F14 Web Bot Auth** chưa build.

**Sweep gap:** `agent_fetch_events.verification_method` không được update bởi sweep — chỉ `agent_visits` được cập nhật.

## The brutal truth

Detect AI traffic: có, local và một phần real-world. "Who behind the AI" như tên người: company-level ✓ (now prioritized), named individual: chỉ khi ops fill provider keys. AI resolution priority: **SHIPPED** (7b1ed33); named-person layer: remains ops gate.

## Decisions / expectations (UPDATED 30-07 eve)

"Ai đứng sau AI" trong Beam = **company-level attribution + prioritized queue** (handoff marker + resolution prioritizes AI-sourced). Named individual: ops-gated (needs provider keys).

**Completed:**
- 0. Harness fixes — **done** (`53fc573`, `486b47a`, `b5f4311`)
- 1.5 Resolution — **AI priority queuing done** (7b1ed33); ops: fill provider keys

**Remaining:**
1. Wild marker survival — test `?_bam=` qua ChatGPT link thật ngoài lab
2. F14 Web Bot Auth — sau khi (1) có kết quả
3. Sweep sync: `agent_fetch_events.verification_method`

## Next steps

**Operators:**
- Chạy wild test: publish link có `?_bam=` qua ChatGPT answer, verify click log + handoff row trên prod/staging tunnel
- Probe ChatGPT với page có CTA click rõ — in-app read không tạo handoff
- Populate provider keys (PDL/Proxycurl/FullContact) để ra individual names
- Monitor `identified_visitors` — expect company-level now, individual only post-ops-keys

**Devs:**
- F14 spec/implement sau wild marker test
- Sweep: update `agent_fetch_events.verification_method` đồng bộ với `agent_visits`
- (Optional) Beacon edge IP logging cho ChatGPT-User trên public site

**Status:** Detection validated locally + partial real; AI resolution priority shipped (7b1ed33); named-person gate: ops (provider keys).
