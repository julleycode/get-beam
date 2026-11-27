---
name: note:conversion-apis-reply-crm-stage
description: "Deferred (D1) — reply and crm_stage conversion triggers for conversion-apis v2"
date: 27-11-26
feature: ads-audiences
---
# Deferred: reply + crm_stage conversion triggers (conversion-apis D1)

v1 (conversion-apis_27-11-26) ships `lead` + generic `goal` only — user decision D1, confirmed 27-11-26.

Deferred to a follow-up plan:
- `reply` — a prospect replying to a Beam outreach email, as a conversion signal.
- `crm_stage` — a CRM deal moving to a configured stage (SQL / closed-won), as an offline conversion.

Notes for the follow-up:
- Reuse the outbox (`ad_conversion_deliveries`) and the send-time gate recheck in `apps/api/services/ad_conversions.py`; add one discovery leg per trigger with its own watermark column.
- Dedup ids must be stable row ids (reply message id / CRM stage-change event id), mirroring E11.
- crm_stage overlaps the sibling `closed-won-lookalikes` plan's CRM read path — sequence after it.
- Keep the D2 first-party allow-list unchanged unless the user widens it.
