---
name: note:marketing-copy-reconciliation
description: "Deferred P4 from the archived marketing-claims-gap program — reword auto-send-implying marketing copy to draft-and-approve language; copy edit only, no code change"
date: 17-08-26
status: RESOLVED 17-08-26
metadata:
  node_type: memory
  type: note
  feature: campaigns-outreach
---

# Marketing Copy Reconciliation Pass (deferred P4)

**Priority:** LOW — copy edit only, no code risk.

**Origin:** umbrella checklist item P4 of the `marketing-claims-gap_16-08-26` program
(archived to `completed/` 17-08-26 with all 3 code phases VERIFIED). P4 was the only open
checklist item at archival.

**Problem:** marketing copy implies outreach is "coordinated automatically". Auto-send is
PERMANENTLY out of scope (charter hard constraint: never auto-send; human approval gate on
`campaign_sender.send_campaign_emails`). The copy must be reworded to draft-and-approve
language, not implemented.

**Fix:** reword any auto-send implication in:
- `apps/web/public/beam/index.html` (static landing — served at `/` via rewrite)
- `PRODUCT_ROADMAP.md`
- landing/pricing copy

**Reference:** charter + P4 in
`process/features/campaigns-outreach/completed/marketing-claims-gap_16-08-26/marketing-claims-gap-umbrella_PLAN_16-08-26.md`.

## Resolution (17-08-26)

Sweep result: index.html, pricing/page.tsx, README.md were already draft-and-approve compliant. Only violation was PRODUCT_ROADMAP.md line 4 vision sentence ("automatically plans + executes") — reworded to "automatically plans + drafts ... you approve every send". Screenshot landing copy ("coordinated automatically" / "adjusts automatically") is NOT in this repo — it is an external draft; reword guidance handed to user in chat.
