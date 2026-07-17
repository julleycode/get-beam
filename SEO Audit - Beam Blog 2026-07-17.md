# SEO Audit — Beam Blog (getbeam.fyi/blog)

Ngày audit: 2026-07-17. Phạm vi: 5 bài blog hiện có + robots.txt + sitemap. Chưa có ranking data nên audit này là on page + technical.

## Executive Summary

Nền content tốt: 5 bài đều dài (~1.500 đến 2.000 từ), đúng tone, có số liệu, cấu trúc H2/H3 sạch, title và meta cơ bản ổn. Nhưng có 2 vấn đề site level và 1 mâu thuẫn data:

1. **robots.txt chặn AI crawlers (GPTBot, ClaudeBot, Google-Extended, CCBot...)** — mâu thuẫn trực tiếp với chiến lược AEO. Là Cloudflare managed setting. [ĐÃ SỬA theo xác nhận của founder 2026-07-17]
2. **sitemap.xml trống** — Google phải tự mò 5 bài blog qua internal link, mà 4/5 bài không có internal link. [ĐÃ SỬA theo xác nhận của founder]
3. **Mâu thuẫn match rate**: homepage FAQ nói 60 tới 80%; bài setup guide nói company level 40 tới 70% và person level 20 tới 40%. Đối thủ chỉ cần quote chính blog của Beam để đánh claim. [CHƯA SỬA]

## Findings site level

| Check | Status | Chi tiết |
|---|---|---|
| robots.txt cho search | Pass | search=yes, Allow: / |
| robots.txt cho AI | Đã sửa | Trước đây chặn GPTBot, ClaudeBot, Google-Extended, CCBot, Amazonbot, Applebot-Extended, Bytespider, meta-externalagent; Content-Signal ai-train=no |
| sitemap.xml | Đã sửa | Trước đây trả về rỗng |
| HTTPS, canonical | Pass | Canonical đúng self trên cả 5 bài |
| Structured data | Warning | Không thấy JSON-LD Article/FAQPage (verify bằng view-source) |
| Author entity | Warning | Author = "Beam" → yếu E-E-A-T. Nên để Julley làm author + author page |
| Publish dates | Note | Cả 5 bài cùng ngày 13/06/2026. Bài sau nên rải lịch |

## Findings per bài (theo checklist CMS)

### Bài 1 — Website Visitor Identification: Turn Traffic Into Leads (pillar, kw vol 120)

Bài tốt nhất. Keyword đủ vị trí, meta chuẩn, internal links 3.

| Issue | Severity | Fix |
|---|---|---|
| Link "GDPR requires a lawful basis" trỏ nhầm sang trang CCPA của oag.ca.gov | High | Trỏ về nguồn GDPR chính thức |
| Thiếu khoảng trắng trước link ("script.[GDPR...") | Low | Sửa typo |
| Title tag 68 ký tự tính suffix "— Beam Blog" | Medium | Rút dưới 60 |
| Không có FAQ section | Medium | Thêm 3 tới 5 câu PAA + FAQPage schema |
| Không nhắc claim 60 tới 80% khi bàn match rates | Medium | Thêm 1 câu Beam-specific |

### Bài 2 — Get Started With Visitor Identification: B2B Setup Guide

| Issue | Severity | Fix |
|---|---|---|
| 0 internal link trong body | Critical | Thêm link về pillar + sequences |
| Match rate 40–70% / 20–40% mâu thuẫn homepage (60–80%) | Critical | Chốt bộ số canonical: giữ range ngành làm context, thêm "Beam averages 60–80% with LLM fallback enrichment" |
| Thiếu og:image | High | Thêm (twitter card đang summary_large_image không ảnh) |
| Meta description ~176 ký tự | Medium | Rút 150–160 |
| Không có FAQ | Medium | Thêm |

### Bài 3 — Follow Up With Website Visitors: 5 Sequences That Convert

| Issue | Severity | Fix |
|---|---|---|
| 0 internal link trong body | Critical | Bài 1 link tới bài này nhưng không có chiều ngược. Thêm 3 link |
| Thiếu og:image | High | Thêm |
| "Marketo's benchmark data" không link nguồn | Medium | Link hoặc thay nguồn linkable |
| Không có FAQ | Medium | Thêm |

### Bài 4 — How to Follow Up With Warm Leads and Close More Deals

| Issue | Severity | Fix |
|---|---|---|
| 0 internal link | Critical | Thêm |
| Cannibalization với bài 5 | High | Xem mục dưới |
| Meta description ~177 ký tự | Medium | Rút 150–160 |
| Thiếu og:image | High | Thêm |
| "80% of sales require five follow-ups" không nguồn | Medium | Link hoặc bỏ |
| Không có FAQ | Medium | Thêm |

### Bài 5 — How to Follow Up With Warm Website Visitors and Convert

| Issue | Severity | Fix |
|---|---|---|
| 0 internal link | Critical | Thêm |
| Cannibalization với bài 4 | High | Xem dưới |
| Số liệu không nguồn (13% call-to-meeting, 10% LinkedIn DM reply, 7 từ subject) | Medium | Link nguồn từng số |
| Thiếu og:image | High | Thêm |
| Không có FAQ | Medium | Thêm |

## Cannibalization: bài 4 vs bài 5 (và một phần bài 3)

Ba bài cùng intent "follow up warm leads/visitors", publish cùng ngày, title gần trùng. Đề xuất tách intent:

- Bài 3 giữ nguyên: sequences/cadence templates (kw: follow up website visitors)
- Bài 4 re-target: sales process sau khi có contact (kw: sales follow up warm leads)
- Bài 5 re-target: first touch từ visitor signal (kw: outreach after site visit, how should i follow up with someone who visited my website)
- Cập nhật title + H1 + intro bài 4 và 5, 3 bài link chéo với anchor đúng vai

## Action plan

### Quick wins (tuần này, ~1 ngày công)

1. ~~Cloudflare: gỡ block AI crawlers~~ ĐÃ XONG
2. ~~Generate + submit sitemap.xml~~ ĐÃ XONG — verify trong GSC
3. Thêm internal links cho bài 2, 3, 4, 5 (mỗi bài: 1 về pillar, 1 sang bài liên quan, 1 về onboarding)
4. Thêm og:image cho bài 2 tới 5
5. Sửa 2 meta description quá dài (bài 2, 4)
6. Sửa link GDPR sai trong bài 1
7. Chốt bộ số match rate canonical, sửa bài 2 khớp homepage

### Strategic (quý này)

8. Giải cannibalization bài 4/5
9. FAQ section + FAQPage JSON-LD cho cả 5 bài
10. Đổi author từ "Beam" sang Julley + author page (E-E-A-T)
11. Publish kho 56 bài theo attack order
12. Connect GSC (+ Ahrefs webmaster tools free) để có ranking data

## Notes

- Footer blog ghi "made for indie makers" nhưng 5 bài viết cho "B2B reps, SDR teams" — lệch ICP. Bài mới đã theo luật dịch về ngôn ngữ founder trong skill.
- Word count, H2/H3, keyword placement: cả 5 bài pass. Vấn đề tập trung ở internal links (4/5 fail), og:image (4/5 thiếu), meta length (2/5 fail) và tầng site.
