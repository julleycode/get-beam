"""Unit tests: EmailSender branding injection polarity.

The default-case test is the permanent regression guard for campaign sends —
a customer's outreach to THEIR prospects goes through EmailSender without the
branding flag and must NEVER carry "Powered by Beam".
"""

import httpx
import pytest

from apps.api.services.email_sender import EmailSender


class _FakeResponse:
    status_code = 202
    headers: dict = {}
    text = ""


@pytest.fixture
def captured_payloads(monkeypatch):
    payloads: list[dict] = []

    async def _fake_post(self, url, json=None, headers=None):
        payloads.append(json)
        return _FakeResponse()

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    return payloads


def _sent_html(payloads: list[dict]) -> str:
    assert len(payloads) == 1
    return payloads[0]["content"][0]["value"]


class TestBrandingInjection:
    @pytest.mark.asyncio
    async def test_default_send_has_no_beam_branding(self, captured_payloads):
        """Guard for the campaign path: no flag → no footer, ever."""
        await EmailSender().send(
            to_email="prospect@example.com",
            subject="hello",
            body_html="<p>outreach body</p>",
            unsubscribe_url="https://api.example.com/unsubscribe?t=x",
        )
        html = _sent_html(captured_payloads)
        assert "Powered by" not in html
        assert "utm_campaign=powered_by" not in html
        assert "Unsubscribe" in html  # existing footer untouched

    @pytest.mark.asyncio
    async def test_branding_true_inserts_footer_above_unsubscribe(self, captured_payloads):
        await EmailSender().send(
            to_email="owner@example.com",
            subject="your beam week",
            body_html="<p>digest body</p>",
            unsubscribe_url="https://api.example.com/unsubscribe?t=x",
            branding=True,
        )
        html = _sent_html(captured_payloads)
        assert "Powered by" in html
        assert "utm_campaign=powered_by" in html
        assert html.index("digest body") < html.index("Powered by") < html.index("Unsubscribe")


class TestCustomArgsAndTracking:
    """Owned-data-layer Phase 2: custom_args + tracking_settings forwarding."""

    @pytest.mark.asyncio
    async def test_custom_args_and_tracking_settings_forwarded(self, captured_payloads):
        await EmailSender().send(
            to_email="prospect@example.com",
            subject="hello",
            body_html="<p>body</p>",
            unsubscribe_url="https://api.example.com/unsubscribe?t=x",
            custom_args={"site_id": "s1", "visitor_id": "v1"},
        )
        payload = captured_payloads[0]
        assert payload["custom_args"] == {"site_id": "s1", "visitor_id": "v1"}
        assert payload["tracking_settings"]["click_tracking"]["enable"] is True
        assert payload["tracking_settings"]["open_tracking"]["enable"] is True

    @pytest.mark.asyncio
    async def test_no_custom_args_omits_key_but_keeps_tracking(self, captured_payloads):
        """Backward compatible: omitting custom_args leaves the key absent;
        tracking_settings is always set explicitly regardless."""
        await EmailSender().send(
            to_email="prospect@example.com",
            subject="hello",
            body_html="<p>body</p>",
            unsubscribe_url="https://api.example.com/unsubscribe?t=x",
        )
        payload = captured_payloads[0]
        assert "custom_args" not in payload
        assert payload["tracking_settings"]["open_tracking"]["enable"] is True
