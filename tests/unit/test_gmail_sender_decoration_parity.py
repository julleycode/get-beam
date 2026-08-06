"""Phase 3 — Gmail-Connect / SendGrid link-decoration parity (SPEC AC12).

The compose step in ``campaign_sender.send_campaign_emails`` decorates links
(``decorate_links`` → ``_bid`` token) and appends the open-tracking pixel BEFORE
the channel fork (``if gmail_sender is not None:``), so BOTH the Gmail-Connect
branch and the SendGrid branch receive the same decorated ``body_html``.

That parity is pre-existing production behavior with no test guarding it. These
tests are the regression/characterization proof: if anyone ever moves the
decoration or the pixel append inside the SendGrid branch, C1 goes red.

Known-gap (AC12 attribution-echo half) is asserted explicitly at the bottom so
the gap is visible in the suite rather than silently invisible.
"""

import re
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

import apps.api.main  # noqa: F401 — registers ALL ORM models before any is built.
from apps.api.services import campaign_sender
from apps.api.services import link_decorator
from apps.api.services.email_providers import gmail as gmail_client
from apps.api.services.email_providers import gmail_sender as gmail_sender_mod

pytestmark = pytest.mark.unit

# One key for the whole module: two sends in the same test must be decodable
# with the same key (Fernet ciphertext still differs per call — random IV).
_TEST_KEY = Fernet.generate_key().decode()
_SITE_URL = "https://site.example"
_BODY_TPL = '<a href="https://site.example/pricing">Pricing</a>'


def _emailable_iv():
    """A person-level, non-suppressed, non-agent-origin recipient (passes every gate)."""
    iv = MagicMock()
    iv.resolution_provider = "rb2b"
    iv.source_agent_visit_id = None
    iv.is_abuse_flagged = False
    iv.email = "lead@corp.com"
    iv.full_name = "Lead Person"
    iv.do_not_email = False
    return iv


async def _run_send(monkeypatch, *, gmail_connected: bool) -> str:
    """Drive one full send and return the body_html the chosen channel received."""
    monkeypatch.setattr(link_decorator.settings, "encryption_key", _TEST_KEY)

    captured: dict[str, str] = {}

    sendgrid_instance = MagicMock()

    async def _fake_sendgrid_send(**kwargs):
        captured["body"] = kwargs["body_html"]
        captured["custom_args"] = kwargs.get("custom_args")
        return True

    sendgrid_instance.send = AsyncMock(side_effect=_fake_sendgrid_send)
    monkeypatch.setattr(
        campaign_sender, "EmailSender", MagicMock(return_value=sendgrid_instance)
    )

    async def _fake_gmail_send(db, sender, **kwargs):
        captured["body"] = kwargs["body_html"]
        captured["gmail_kwargs"] = kwargs
        return {"id": "msg-1"}

    monkeypatch.setattr(campaign_sender, "send_via_gmail", AsyncMock(side_effect=_fake_gmail_send))
    monkeypatch.setattr(
        campaign_sender,
        "resolve_sender_for_site",
        AsyncMock(return_value=MagicMock() if gmail_connected else None),
    )
    monkeypatch.setattr(campaign_sender, "is_email_suppressed", AsyncMock(return_value=False))
    monkeypatch.setattr(campaign_sender, "check_and_reserve_email", AsyncMock(return_value=True))

    member_result = MagicMock()
    member_result.all.return_value = [("vid-1",)]
    site_result = MagicMock()
    site_result.first.return_value = (_SITE_URL, "Site", "Owner", "owner@site.example")
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
            existing_result,
            company_result,
            status_result,
        ]
    )
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()

    campaign = MagicMock()
    campaign.plan = {
        "touchpoints": [{"channel": "email", "subject": "s", "body": _BODY_TPL, "step": 1}]
    }
    campaign.segment_id = "seg-1"
    campaign.site_id = "site-1"

    summary = await campaign_sender.send_campaign_emails(db, campaign)
    assert summary["sent"] == 1, summary
    return captured


def _bid_tokens(html: str) -> list[str]:
    return re.findall(r"_bid=([^&\"'>]+)", html)


# ---------------------------------------------------------------------------
# C1 — link-decoration parity (Fully-Automated, AC12 link-decoration half)
# ---------------------------------------------------------------------------


async def test_gmail_branch_receives_decorated_body_with_bid(monkeypatch):
    captured = await _run_send(monkeypatch, gmail_connected=True)
    body = captured["body"]
    tokens = _bid_tokens(body)
    assert tokens, f"Gmail-Connect body carries no _bid token: {body!r}"
    # The token decrypts back to the recipient — this is the deterministic
    # click→identity mechanism Phase H's promotion sweep depends on.
    assert link_decorator.decode_bid(tokens[0]) == "lead@corp.com"
    # Open-tracking pixel is shared too (appended before the fork).
    assert "/o/" in body and 'width="1"' in body


async def test_gmail_and_sendgrid_receive_identical_decorated_body(monkeypatch):
    gmail_body = (await _run_send(monkeypatch, gmail_connected=True))["body"]
    sendgrid_body = (await _run_send(monkeypatch, gmail_connected=False))["body"]

    # Fernet ciphertext is nondeterministic (random IV), so the raw _bid/unsub
    # tokens differ per call even for the same email — normalize them away and
    # compare the structure that must match.
    norm = lambda h: re.sub(r"(_bid=|\?t=)[^&\"'>]+", r"\1<TOKEN>", h)  # noqa: E731

    # The Gmail branch appends the unsubscribe footer on top of the shared
    # composed body; everything before that must be identical.
    assert norm(gmail_body).startswith(norm(sendgrid_body)), (
        "Gmail-Connect body diverges from the SendGrid body before the unsubscribe "
        "footer — the shared compose step (decorate_links + open pixel running "
        "before the channel fork) has been broken.\n"
        f"gmail:    {gmail_body!r}\nsendgrid: {sendgrid_body!r}"
    )
    # Both carry a decodable _bid for the same recipient (tokens differ: Fernet
    # is nondeterministic), and both carry the open pixel.
    for body in (gmail_body, sendgrid_body):
        tokens = _bid_tokens(body)
        assert tokens
        assert link_decorator.decode_bid(tokens[0]) == "lead@corp.com"
        assert "/o/" in body


async def test_gmail_branch_still_gets_unsubscribe_url(monkeypatch):
    captured = await _run_send(monkeypatch, gmail_connected=True)
    assert captured["gmail_kwargs"]["unsubscribe_url"]


# ---------------------------------------------------------------------------
# C3 — SendGrid regression guard (custom_args unchanged by this phase)
# ---------------------------------------------------------------------------


async def test_sendgrid_branch_custom_args_unchanged(monkeypatch):
    captured = await _run_send(monkeypatch, gmail_connected=False)
    assert captured["custom_args"] == {"site_id": "site-1", "visitor_id": "vid-1"}


# ---------------------------------------------------------------------------
# C2 — attribution-echo KNOWN GAP (AC12 attribution-echo half)
# ---------------------------------------------------------------------------


def test_known_gap_gmail_has_no_custom_args_equivalent():
    """KNOWN GAP (Phase 3, Step A finding) — documented, not a defect.

    SendGrid's ``custom_args`` exists so its open/click WEBHOOK can echo
    (site_id, visitor_id) back into ``IdentitySignal`` (owned-data-layer).
    The Gmail API has NO equivalent: ``users.messages.send`` accepts only a raw
    RFC-822 message, and Gmail emits no open/click event stream at all, so there
    is nothing to echo metadata back to. A custom MIME header could technically
    be added in ``gmail._build_raw_message`` but no Beam-side consumer exists
    (building a Gmail webhook is out of program scope — no new runtime surfaces),
    so it would be dead code.

    Beam's OWN first-party attribution (the ``/o/{touchpoint_id}`` open pixel and
    the ``_bid`` / ``_tp`` decorated links) IS already shared across both channels
    and is unaffected by this gap — see the C1 tests above.

    This test asserts the gap's shape so it fails loudly the day a
    ``custom_args``-equivalent parameter IS added and this note goes stale.
    """
    import inspect

    gmail_params = set(inspect.signature(gmail_sender_mod.send_via_gmail).parameters)
    assert "custom_args" not in gmail_params
    assert set(gmail_params) == {
        "db",
        "sender",
        "to_email",
        "subject",
        "body_html",
        "unsubscribe_url",
    }
    assert "custom_args" not in set(inspect.signature(gmail_client.send_message).parameters)
