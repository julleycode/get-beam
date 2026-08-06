"""Provisioning a Leadpipe pixel must be idempotent and must never break install.

The 409 path is the one that carries real risk: the API says "Pixel already
exists for this domain" but the error body does NOT include the existing id
(verified against a live org 06-08-26), so the id can only come from a list
lookup. Guessing, or falling through to a shared id, would embed a pixel that
collects into a different domain's bucket.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

pytestmark = pytest.mark.unit

DOMAIN = "example.com"


def _client(*responses):
    """AsyncClient stub whose post/get pop from the given response sequence."""
    seq = list(responses)
    client = AsyncMock()
    client.post = AsyncMock(side_effect=lambda *a, **k: seq.pop(0))
    client.get = AsyncMock(side_effect=lambda *a, **k: seq.pop(0))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, client


def _resp(status, payload):
    return httpx.Response(
        status, json=payload, request=httpx.Request("POST", "https://x.test")
    )


async def _ensure(cm, **setting_overrides):
    from apps.api.services import leadpipe_pixels

    with patch.object(leadpipe_pixels, "settings") as s, \
         patch("httpx.AsyncClient", return_value=cm):
        s.leadpipe_api_key = "k"
        s.leadpipe_enabled = True
        s.leadpipe_pixel_autoprovision_enabled = True
        s.mock_external_apis = False
        for k, v in setting_overrides.items():
            setattr(s, k, v)
        return await leadpipe_pixels.ensure_pixel_for_domain(DOMAIN)


@pytest.mark.asyncio
async def test_created_pixel_returns_its_id():
    cm, _ = _client(_resp(201, {"data": {"id": "new-id", "domain": DOMAIN}}))
    assert await _ensure(cm) == "new-id"


@pytest.mark.asyncio
async def test_409_falls_back_to_list_lookup_because_the_body_omits_the_id():
    cm, client = _client(
        _resp(409, {"error": {"message": "Pixel already exists for this domain"}}),
        _resp(
            200,
            {
                "data": [
                    {"id": "other-id", "domain": "someone-else.com", "status": "active"},
                    {"id": "existing-id", "domain": DOMAIN, "status": "active"},
                ]
            },
        ),
    )
    assert await _ensure(cm) == "existing-id"
    client.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_409_with_domain_absent_from_list_returns_none_not_a_guess():
    """409 says it exists, the list says it does not — another org owns it.
    Returning any id here would embed a pixel collecting into that other org."""
    cm, _ = _client(
        _resp(409, {"error": {"message": "Pixel already exists for this domain"}}),
        _resp(200, {"data": [{"id": "x", "domain": "unrelated.com", "status": "active"}]}),
    )
    assert await _ensure(cm) is None


@pytest.mark.asyncio
async def test_expired_org_returns_none_instead_of_raising():
    """403 must degrade to "no vendor tag", never to a failed snippet fetch."""
    cm, _ = _client(_resp(403, {"error": {"message": "Organization is expired"}}))
    assert await _ensure(cm) is None


@pytest.mark.asyncio
async def test_network_failure_returns_none_instead_of_raising():
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(side_effect=httpx.ConnectError("boom"))
    cm.__aexit__ = AsyncMock(return_value=False)
    assert await _ensure(cm) is None


@pytest.mark.asyncio
async def test_no_key_short_circuits_before_any_http_call():
    cm, client = _client()
    assert await _ensure(cm, leadpipe_api_key="") is None
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_provider_short_circuits():
    cm, client = _client()
    assert await _ensure(cm, leadpipe_enabled=False) is None
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_autoprovision_off_by_default_makes_no_vendor_write():
    """The flag is the guard against a snippet fetch mutating vendor state —
    including from any test that happens to request an install snippet while a
    real LEADPIPE_API_KEY is present in the environment."""
    cm, client = _client()
    assert await _ensure(cm, leadpipe_pixel_autoprovision_enabled=False) is None
    client.post.assert_not_awaited()
    client.get.assert_not_awaited()


def test_autoprovision_defaults_off_in_real_settings():
    from apps.api.config import Settings

    assert Settings().leadpipe_pixel_autoprovision_enabled is False


@pytest.mark.asyncio
async def test_mock_mode_is_deterministic_and_keyless():
    """CLAUDE.md: every external API works under MOCK_EXTERNAL_APIS. Two calls
    for one domain must agree, exactly as the real 201/409 pair does."""
    cm, client = _client()
    first = await _ensure(cm, mock_external_apis=True)
    second = await _ensure(cm, mock_external_apis=True)
    assert first == second
    assert DOMAIN.replace(".", "-") in first
    client.post.assert_not_awaited()
