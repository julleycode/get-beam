"""AC-2b — send_campaign_emails itself delivers the site's booking_url.

This is the ONLY gate that fails if the ``_compose_for_recipient`` call inside
``send_campaign_emails`` was never passed the ``booking_url`` read from the site
select. Every AC-2a gate passes ``booking_url`` explicitly, so all of them can be
green while the shipped product renders nothing.

Mechanism note: ``MOCK_EXTERNAL_APIS=true`` is a NO-OP here —
``apps/api/services/email_sender.py`` has no mock branch and ``EmailSender.send``
POSTs to SendGrid unconditionally. The outbound body is captured by
monkeypatching ``campaign_sender.EmailSender``, mirroring the proven harness in
``tests/unit/test_gmail_sender_decoration_parity.py``.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

import apps.api.main  # noqa: F401 — registers ALL ORM models before any is built.
from apps.api.services import campaign_sender
from apps.api.services import link_decorator

pytestmark = pytest.mark.unit

_TEST_KEY = Fernet.generate_key().decode()
_SITE_URL = "https://site.example"
_BOOKING_URL = "https://cal.com/acme/demo"
_BODY_TPL = "Grab a slot: {{booking_link}}"


def _emailable_iv():
    iv = MagicMock()
    iv.resolution_provider = "rb2b"
    iv.source_agent_visit_id = None
    iv.is_abuse_flagged = False
    iv.email = "lead@corp.com"
    iv.full_name = "Lead Person"
    iv.do_not_email = False
    return iv


async def _run_send(monkeypatch, *, booking_url: str | None) -> dict:
    """Drive one full send; return the captured outbound kwargs + summary."""
    monkeypatch.setattr(link_decorator.settings, "encryption_key", _TEST_KEY)

    captured: dict = {}
    sendgrid_instance = MagicMock()

    async def _fake_sendgrid_send(**kwargs):
        captured["body"] = kwargs["body_html"]
        return True

    sendgrid_instance.send = AsyncMock(side_effect=_fake_sendgrid_send)
    monkeypatch.setattr(
        campaign_sender, "EmailSender", MagicMock(return_value=sendgrid_instance)
    )
    monkeypatch.setattr(campaign_sender, "send_via_gmail", AsyncMock())
    monkeypatch.setattr(
        campaign_sender, "resolve_sender_for_site", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        campaign_sender, "is_email_suppressed", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        campaign_sender, "check_and_reserve_email", AsyncMock(return_value=True)
    )

    member_result = MagicMock()
    member_result.all.return_value = [("vid-1",)]
    site_result = MagicMock()
    # (Site.url, Site.name, User.full_name, User.email, Site.booking_url)
    site_result.first.return_value = (
        _SITE_URL,
        "Site",
        "Owner",
        "owner@site.example",
        booking_url,
    )
    iv_result = MagicMock()
    iv_result.scalar_one_or_none.return_value = _emailable_iv()
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = None
    company_result = MagicMock()
    company_result.scalar_one_or_none.return_value = "Corp"
    status_result = MagicMock()
    status_result.scalar_one_or_none.return_value = "identified"

    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            member_result,
            site_result,
            iv_result,
            status_result,
            existing_result,
            company_result,
        ]
    )
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()

    campaign = MagicMock()
    campaign.plan = {
        "touchpoints": [
            {"channel": "email", "subject": "s", "body": _BODY_TPL, "step": 1}
        ]
    }
    campaign.segment_id = "seg-1"
    campaign.site_id = "site-1"

    summary = await campaign_sender.send_campaign_emails(db, campaign)
    captured["summary"] = summary
    return captured


@pytest.mark.asyncio
async def test_send_delivers_booking_url_into_outbound_body(monkeypatch):
    captured = await _run_send(monkeypatch, booking_url=_BOOKING_URL)
    # Non-vacuity guard FIRST: a failed send yields an empty capture and would
    # otherwise produce a misleading red (or a vacuous pass).
    assert captured["summary"]["sent"] == 1, captured["summary"]
    assert _BOOKING_URL in captured["body"]


@pytest.mark.asyncio
async def test_send_with_no_booking_url_renders_empty_never_none(monkeypatch):
    captured = await _run_send(monkeypatch, booking_url=None)
    assert captured["summary"]["sent"] == 1, captured["summary"]
    # Scope the assertion to the token's own line: the body also carries the
    # open-tracking pixel URL, which legitimately contains "None" for this
    # mock's unsaved email id — an unscoped "None" check would fail on it.
    slot_line = captured["body"].split("<br/>")[0].split("<img")[0]
    assert "Grab a slot:" in slot_line
    assert "None" not in slot_line
    assert "booking_link" not in slot_line
