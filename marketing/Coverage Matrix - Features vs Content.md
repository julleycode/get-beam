# Coverage Matrix — Features / Connectors / User Journeys vs 47 bài content

Ngày: 2026-07-17. Đối chiếu kho blog-drafts (47 bài) với product surface của Beam.

## 1. Features (từ homepage + product facts)

| Feature | Coverage | Bài | Gap |
|---|---|---|---|
| Live visitor feed (see them) | ✅ Đủ | pillar, identify-anonymous, real-time (bài cũ) | — |
| Social matching: LinkedIn | ✅ | is-linkedin-automation-safe, linkedin-retargeting | — |
| Social matching: X/Twitter | ✅ | twitter-outreach-for-founders | — |
| Social matching: Instagram | ⚠️ Một nửa | instagram-retargeting (ads only) | **Instagram DM outreach** chưa có |
| Social matching: Facebook, Slack, 10+ platforms | ❌ | — | Thiếu, priority thấp (Slack outreach hơi lạ, FB DM ít dùng B2B) |
| AI drafts outreach (charm them) | ✅ Đủ | ai-sales-outreach-tools, how-to-reach-out-to-prospects, founder-led-sales | — |
| Email alerts + 30 min first visitor | ✅ | nhúng trong mọi bài setup | — |
| Basic analytics | ➖ Bỏ qua | — | Không đáng viết riêng |
| CRM: HubSpot | ✅ | website-visitor-data-to-hubspot | — |
| CRM: Salesforce | ❌ | chỉ được nhắc | **Bài riêng chưa có** |
| CRM: Pipedrive | ❌ | chỉ được nhắc | **Bài riêng chưa có** |
| Webhook/CSV → Attio, Notion, Sheets, own DB | ⚠️ | API post (generic) | Long-tail "visitor data to notion / google sheets" chưa có, zero competition |
| Retargeting seeds: Meta / Google / LinkedIn / IG | ✅ Đủ bộ 4 | 4 bài + cookieless + lookalike + vs-remarketing | — |
| Free plan / pricing | ✅ | free post + mọi bài comparison | — |
| GDPR/CCPA, no-ban design | ✅ | legal post + linkedin-automation | — |

**Install platforms** (homepage liệt kê): WordPress ✅ Shopify ✅ Wix ✅ Webflow ✅ Framer ✅ · Squarespace ❌ Ghost ❌ Carrd ➖(bỏ, quá nhỏ) Bubble ❌ Next.js/React/Astro ❌

## 2. Connectors verdict

CRM: 1/3 có bài riêng (HubSpot). Salesforce và Pipedrive là 2 gap rõ — cùng template với bài HubSpot, viết nhanh. Webhook destinations (Notion, Sheets, Attio): gộp được 1 bài "send website visitor data to notion, sheets, anywhere" — long-tail thuần, không ai cạnh tranh.

## 3. User journey: Vibe coder (ICP số 1 theo homepage) — GAP LỚN NHẤT

Journey: build bằng AI tools (Cursor/Lovable/Bolt/v0) → deploy (Vercel/Netlify) → launch (X, Product Hunt) → traffic spike → không có user trả tiền → hoang mang.

| Stage | Coverage | Gap |
|---|---|---|
| Launch → traffic | ⚠️ | first-10-customers ✅, framer post ✅ nhưng KHÔNG bài nào nói ngôn ngữ "vibe coding" |
| Traffic → no users | ⚠️ | website-traffic-but-no-leads ✅ nhưng viết cho B2B chung |
| Deploy stack (Next.js/Vercel) | ❌ | Không có bài install cho dev stack |

Autocomplete confirmed (2026-07-17): "vibe coded apps making money", "vibe coded apps examples", "how to get users for your app". Homepage Beam mở đầu bằng "so you launched your vibe-coded product?" mà SEO không có bài nào chào đúng người đó. Đề xuất 3 bài:
1. **how-to-get-users-for-your-vibe-coded-app** — bài journey chính, ngôn ngữ ICP nguyên chất
2. **nextjs-visitor-identification** (cover luôn Vercel/React/Astro trong bài) — install post cho dev stack
3. **vibe-coded-apps-making-money** — keyword confirmed, angle: apps kiếm tiền được nhờ distribution chứ không phải code, case-style

## 4. User journey: B2B SaaS — cover ~90%

| Stage | Coverage |
|---|---|
| Awareness (what is X) | ✅ pillar, person-level, warm lead, intent data |
| Consideration (so sánh tool) | ✅✅ 15+ bài comparison/alternative/pricing |
| Objection (legal, accuracy) | ✅ legal, match-rate |
| Setup | ✅ setup guide, platform posts |
| Activation (workflows) | ✅ hubspot, sequences, follow-up x3 |
| Scale (ABM, ads) | ✅ abm, retargeting x6 |
| **PLG/trial signals** | ❌ Gap duy nhất: "product qualified leads", trial-user-is-evaluating angle — SaaS có trial muốn biết ai đang cân nhắc upgrade. Đề xuất 1 bài: **product-qualified-leads-from-website-signals** |

## 5. Đợt 3 đề xuất (9 bài, ranked)

1. how-to-get-users-for-your-vibe-coded-app (ICP chính, demand confirmed)
2. nextjs-visitor-identification (dev stack của ICP chính)
3. vibe-coded-apps-making-money (keyword confirmed)
4. salesforce-visitor-identification-sync (connector gap)
5. pipedrive-visitor-identification-sync (connector gap)
6. website-visitor-data-to-notion-sheets (webhook long-tail, zero competition)
7. instagram-dm-outreach (hoàn thiện social moat)
8. product-qualified-leads-from-website-signals (B2B SaaS gap cuối)
9. squarespace-visitor-identification (platform còn thiếu đáng viết nhất)

Ghost, Bubble, Facebook/Slack outreach: để backlog, chờ GSC signal.
