---
name: note:emailsender-no-mock-branch
description: "EmailSender.send POSTs to SendGrid unconditionally — MOCK_EXTERNAL_APIS is not honored on the send path"
date: 16-08-26
metadata:
  node_type: memory
  type: report
  feature: campaigns-outreach
  phase: phase-1
---

# `EmailSender` has no mock-mode branch (cross-cutting)

**Found by:** marketing-claims-gap Phase 1 PVL (M-1), confirmed at EXECUTE.

`apps/api/services/email_sender.py` contains **zero** `MOCK` references.
`EmailSender.send` POSTs to SendGrid unconditionally — there is no mock
short-circuit and no missing-key guard.

This breaks the repo-wide convention recorded in `process/context/all-context.md`:

> every external API must work with `MOCK_EXTERNAL_APIS=true` returning
> deterministic fakes

## Consequence for test authors

`MOCK_EXTERNAL_APIS=true` is a **no-op** on the campaign send path. A test that
relies on it captures nothing: the POST raises, is caught at
`campaign_sender.py` (the per-recipient try/except), `summary["failed"]`
increments and `summary["sent"]` stays 0 — a silently vacuous test.

Every send-path test must monkeypatch the class instead:

```python
monkeypatch.setattr(campaign_sender, "EmailSender", MagicMock(return_value=fake))
# ...and assert summary["sent"] == 1 BEFORE asserting on the captured body.
```

Prior art / templates:
- `tests/unit/test_gmail_sender_decoration_parity.py` (`_run_send`)
- `tests/unit/test_campaign_send_booking_link.py` (added by Phase 1)

## Candidate fix

Add a mock short-circuit at the top of `EmailSender.send` gated on
`settings.mock_external_apis`, returning a deterministic success without the
HTTP call — matching how the identity/enrichment providers already behave.
Cross-cutting: it would let every future send-path test drop the monkeypatch
scaffolding.
