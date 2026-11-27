"""AC3-send — send_campaign_emails itself delivers the /c/ ct-wrapped CTA link.

Mirrors tests/unit/test_campaign_send_booking_link.py: drives the REAL send loop
with a mocked db and a monkeypatched EmailSender, and asserts on the captured
outbound body. ``db.flush`` is mocked, so ``tp`` can only be a real UUID if the
touchpoint id is pre-assigned before compose (C1).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.fernet import Fernet

import apps.api.main  # noqa: F401 — registers ALL ORM models before any is built.
from apps.api.models.campaign import CampaignTouchpoint
from apps.api.services import campaign_sender, link_decorator

pytestmark = pytest.mark.unit

_TEST_KEY = Fernet.generate_key().decode()
_SITE_URL = "https://site.example"
_TRIAL_URL = "https://site.example/trial"
_BODY_TPL = "Start here: {{cta_link}} or {cta_link}"
_CFG = {"default": "free_trial", "types": {"free_trial": {"url": _TRIAL_URL}}}


def _emailable_iv():
    iv = MagicMock()
    iv.resolution_provider = "rb2b"
    iv.source_agent_visit_id = None
    iv.is_abuse_flagged = False
    iv.email = "lead@corp.com"
    iv.full_name = "Lead Person"
    iv.do_not_email = False
    return iv


async def _run_send(monkeypatch, *, flag: bool, cta_config) -> dict:
    monkeypatch.setattr(link_decorator.settings, "encryption_key", _TEST_KEY)
    monkeypatch.setattr(campaign_sender.settings, "cta_types_enabled", flag)
    monkeypatch.setattr(campaign_sender.settings, "api_base_url", "https://api.example")

    captured: dict = {}
    sendgrid_instance = MagicMock()

    async def _fake_send(**kwargs):
        captured["body"] = kwargs["body_html"]
        return True

    sendgrid_instance.send = AsyncMock(side_effect=_fake_send)
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

    def _r(**attrs):
        m = MagicMock()
        for k, v in attrs.items():
            getattr(m, k).return_value = v
        return m

    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _r(all=[("vid-1",)]),
            _r(first=(_SITE_URL, "Site", "Owner", "o@site.example", None, cta_config)),
            _r(scalar_one_or_none=_emailable_iv()),
            _r(scalar_one_or_none="identified"),
            _r(scalar_one_or_none=None),
            _r(scalar_one_or_none="Corp"),
        ]
    )
    added: list = []
    db.add = MagicMock(side_effect=added.append)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()

    campaign = MagicMock()
    campaign.id = uuid.uuid4()
    campaign.plan = {
        "touchpoints": [
            {"channel": "email", "subject": "s", "body": _BODY_TPL, "step": 1,
             "cta_type": "free_trial"}
        ]
    }
    campaign.segment_id = "seg-1"
    campaign.site_id = "site-1"

    captured["summary"] = await campaign_sender.send_campaign_emails(db, campaign)
    captured["touchpoints"] = [a for a in added if isinstance(a, CampaignTouchpoint)]
    captured["campaign_id"] = str(campaign.id)
    return captured


@pytest.mark.asyncio
async def test_flag_on_delivers_ct_wrapped_link_with_preassigned_tp(monkeypatch):
    c = await _run_send(monkeypatch, flag=True, cta_config=_CFG)
    assert c["summary"]["sent"] == 1, c["summary"]
    line = c["body"].split("<img")[0]
    links = [w for w in line.split() if w.startswith("https://api.example/c/site-1?")]
    assert len(links) == 2  # both brace forms
    q = parse_qs(urlsplit(links[0]).query)
    assert q["ct"] == ["free_trial"]
    assert q["u"] == [_TRIAL_URL]
    assert q["cid"] == [c["campaign_id"]]
    tp = q["tp"][0]
    assert uuid.UUID(tp)  # a real UUID, never "None"
    assert len(c["touchpoints"]) == 1
    assert str(c["touchpoints"][0].id) == tp
    assert link_decorator.decode_bid(q["t"][0]) == "lead@corp.com"
    # The /c/ link is on the API host, so decorate_links never stamped it.
    assert "_bid=" not in links[0]


@pytest.mark.asyncio
async def test_flag_off_body_unchanged_and_link_empty(monkeypatch):
    c = await _run_send(monkeypatch, flag=False, cta_config=_CFG)
    assert c["summary"]["sent"] == 1, c["summary"]
    line = c["body"].split("<img")[0]
    # Both tokens resolve to "" (never literal text); _tidy collapses spacing.
    assert line.strip() == "Start here: or"
    assert "/c/" not in c["body"]


@pytest.mark.asyncio
async def test_flag_on_no_stored_url_renders_empty(monkeypatch):
    c = await _run_send(monkeypatch, flag=True, cta_config=None)
    assert c["summary"]["sent"] == 1, c["summary"]
    assert "/c/" not in c["body"]
    assert "cta_link" not in c["body"]
