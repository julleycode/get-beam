---
name: note:reply-tracking
description: "Reply tracking is unbuilt and deliberately out of scope of the Phase 3 learning loop — what a v1 would need"
date: 16-08-26
metadata:
  node_type: memory
  type: report
  feature: campaigns-outreach
---

# Reply tracking — out of scope, not forgotten

**TL;DR:** Beam measures sends, opens, clicks and conversions. It measures **no replies at all**,
and there is no reply model anywhere in the repo. Phase 3's learning loop therefore feeds the
planner opens/clicks/conversions only. Building reply tracking is its own phase.

Recorded by marketing-claims-gap Phase 3 (decision D8, checklist E3).

## Why it was excluded

- **Nothing exists to extend.** `grep` finds no reply model, no reply column, and no inbound-mail
  handler. `CampaignTouchpoint` has `sent_at` / `opened_at` / `clicked_at` and no reply field.
- **SendGrid does not report it on this integration.** The webhook handler in
  `apps/api/routers/webhooks.py` receives delivery/engagement events (bounce, dropped, spamreport,
  open, click). Inbound replies are a different SendGrid product (Inbound Parse) with its own MX
  configuration — not a field on the events Beam already receives.
- Inferring replies from existing events would be a fabricated metric. A learning loop that feeds
  the planner an invented number is worse than one that omits it.

## What a v1 would need

1. **An inbound channel.** Either SendGrid Inbound Parse (needs an MX record on a Beam-controlled
   subdomain and a new public webhook endpoint, which is a new unauthenticated write surface with
   the usual body-size/rate/idempotency hardening), or IMAP polling of the owner's connected Gmail
   (the Connect-Gmail OAuth path already exists for sending).
2. **Correlation back to a touchpoint.** Reply-To with a per-touchpoint tagged address, or
   `In-Reply-To` / `References` header matching against the outbound `Message-ID`. Header matching
   is more fragile; tagged addresses need the MX above.
3. **A `replied_at` column on `CampaignTouchpoint`** plus a migration — additive-nullable, the same
   shape as the existing three stamps.
4. **PII handling.** Reply BODIES are personal data from a third party who never consented to Beam
   storing them. Strong default: store the fact and timestamp of a reply, never the body. If a body
   is ever stored, it must go through `pii_crypto` and be swept by `services/graph_erasure.py`.
5. **Prompt-injection defense.** A reply body is hostile input by definition. Anything reaching a
   prompt must pass `agents/prompt_safety.clean_text` / `wrap_untrusted`.

## What must NOT happen

Adding reply tracking must not become a reason to auto-send or auto-adjust a live campaign. Drafts
go through human approval; that is a brand guarantee, not an implementation detail.
