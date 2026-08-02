# Research + Ask: Cookie/Fingerprint → identity provider “tốt hơn RB2B”?

**Date:** 2026-08-02 · **Scope:** local Beam Lab · **Modes:** ask + brainstorm + research  
**Anchor visitor:** `407a701d-ade4-4593-9078-5b665d48ba80` (`site_16c46453546f`)

## Executive Summary

**Không có API commodity kiểu “POST Beam `_rta_svid` + `fp2_*` → nhận email B2B tốt hơn RB2B”.**

Cookie + fingerprint của Beam là **ID nội bộ first-party**. Vendor (RB2B Pixel / Vector / Warmly…) chỉ match được khi **JS pixel của họ** thu tín hiệu trong **identity graph của họ**. Gửi chuỗi FP Beam sang API IP-only (RB2B Identification API) **không** nâng accuracy.

Visitor test đã identify bằng **IP → RB2B API** sau khi credit/API/parser OK — **không** nhờ cookie/FP. `server_visitor_id` trống; FP chỉ có trên 1 visitor (không reuse).

## Case study — visitor bạn bè test

| Field | Value |
|---|---|
| visitor_id | `407a701d-ade4-4593-9078-5b665d48ba80` |
| identity_status | `identified` |
| provider | `rb2b` |
| name / email | Janet Valla / `danica_naluz@sftoyota.com` (name≠local-part — graph noise) |
| fingerprint | `fp2_1e3i2ll18vntmr1w59y21tft0gf` |
| server_visitor_id (`_rta_svid`) | **NULL** |
| canonical_visitor_id | NULL |
| IP (visitor) | `2a09:bac3:627a:3050::4d0:11` (CF IPv6) |
| events UA | Safari Mac; 2 IP CF khác nhau trên cùng visitor |
| FP shared với visitor khác? | **Không** (1 row only) |
| events.fingerprint column? | **Không** — FP chỉ persist trên `visitors` |

**Kết luận case:** Cookie/FP **không tham gia** cold identify lần này. Free path (`svid_reconcile` / `fingerprint_match`) **không fire** vì chưa có prior identified cùng svid/FP.

## Research findings (ngành)

### Hai sản phẩm khác nhau

| Product type | Input | Cookie/FP role | Example |
|---|---|---|---|
| **Identification API (server)** | IP (+ optional UA) | **Không nhận** Beam FP/svid | RB2B APIs V2 `ip_to_hem` |
| **Vendor pixel + graph** | Browser session qua **JS của họ** | FP/cookie **của họ** trong graph họ | RB2B Pixel, Vector pixel, Warmly pixel |

Nguồn: RB2B API docs (ip + user_agent); Vector “How does the pixel work?” (device fingerprint → their graph); Warmly (first-party pixel + IP + cookie match in their graph); industry guides (Leadpipe/Cursive — signal hierarchy: auth email > cookie+FP in graph > IP alone).

### “Tốt hơn RB2B” nghĩa là gì?

| Ý muốn | Thực tế |
|---|---|
| Gửi FP Beam → API khác match cao hơn | **Không khả thi** — FP không portable giữa graph |
| Match rate cold visitor cao hơn | Cần **pixel + graph lớn** (Vector/Warmly/RB2B Pixel ~20–40% US claim) — **không** phải đổi field API |
| Free identify return visitor | Đúng chỗ của **Beam svid/FP** — không cần vendor |

Ad-tech (UID2 / LiveIntent) = publisher addressability, **không** drop-in B2B lead email API cho SaaS Beam.

## Problem-first (brainstorm)

1. **Solution-jumping:** “Cookie+FP Beam → provider tốt hơn RB2B”
2. **Underlying problem:** Cold identify phụ thuộc IP-API; first-party sticky gần như không chạy trên Lab; kỳ vọng nhầm FP portable
3. **Assumptions to kill:** (a) FP Beam = tín hiệu vendor hiểu · (b) có REST nhận arbitrary FP · (c) visitor fail tối qua vì thiếu gửi FP
4. **Evidence:** Strong trên case local; Medium trên vendor marketing claims

## Architecture recommendation

```
Lớp A (Beam, free):  _rta_svid + fp2_*  → reuse identity đã biết
Lớp B (paid API):    IP (+UA)            → RB2B/PDL cold start  [đang dùng]
Lớp C (optional):    Vendor JS pixel     → graph họ (FP/cookie họ) — sản phẩm khác
```

**Không recommend:** forward Beam FP/svid vào RB2B API.  
**Recommend nếu muốn “như đối thủ FP”:** PoC **một** vendor pixel trên Lab UAT (RB2B Pixel *hoặc* Vector/Warmly) — so match vs IP-API trên cùng traffic; hoặc harden Lớp A trước (rẻ hơn).

## Next actions

1. Chốt: PoC vendor pixel (C) vs harden Beam cookie/FP (A) vs provider status honesty (B) — roadmap P0–P3 đã đề xuất.
2. Không plan “API nhận Beam FP” trừ khi vendor có documented endpoint (hiện chưa thấy cho B2B lead gen).
3. Optional: audit name/email mismatch RB2B (Janet vs danica) — data quality, không phải cookie.

## Sources

- https://docs.sim.ai/integrations/rb2b  
- https://learn.vector.co/articles/2756887260-how-does-the-pixel-work  
- https://www.warmly.ai/p/solutions/use-cases/website-visitor-identification  
- https://www.leadpipe.com/blog/identity-graph-api-how-they-work/  
- https://www.meetcursive.com/blog/website-visitor-identification-guide  
- Local DB: visitors/events/identified_visitors cho visitor trên
