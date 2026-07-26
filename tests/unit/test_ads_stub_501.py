"""D5 — stub-provider defense in depth.

With ad_audiences_enabled=True but MOCK_EXTERNAL_APIS=False, a provider that is
still a stub raises NotImplementedError. The router must surface that as a clean
HTTP 501, never an unhandled 500.

Phase 2 note (26-07-26): `meta` is no longer a stub — its real Graph API path
landed, so it no longer raises NotImplementedError and is out of these
assertions.

Phase 3 note (26-07-26): `google` is no longer a stub either. No READY provider
raises NotImplementedError any more, so the router's 501 mapping is now proven
against a SYNTHETIC stub provider instead of a real one — the mapping itself is
still live code that must not regress. Both real providers' contract flips are
asserted rather than assumed below. The flag-off 501 path is unaffected and
still covered by test_ads_flag_off_501.py.

Pure unit test: the endpoint coroutine is called directly with the site-ownership
and OAuth-state seams stubbed, so no DB or Redis is touched.
"""

import uuid

import pytest
from fastapi import HTTPException

from apps.api.config import settings
from apps.api.routers import ads as ads_router

pytestmark = pytest.mark.unit


class _User:
    id = uuid.uuid4()


@pytest.fixture
def stubbed_seams(monkeypatch):
    async def _owned(db, site_id, user):
        return object()

    async def _store(state, packed):
        return None

    monkeypatch.setattr(ads_router, "_owned_site", _owned)
    monkeypatch.setattr(ads_router, "store_oauth_state", _store)
    # Flag ON, mock mode OFF, credentials configured — the exact pre-Phase-2 window.
    monkeypatch.setattr(settings, "ad_audiences_enabled", True)
    monkeypatch.setattr(settings, "mock_external_apis", False)
    monkeypatch.setattr(settings, "meta_ads_client_id", "cid")
    monkeypatch.setattr(settings, "meta_ads_client_secret", "secret")
    monkeypatch.setattr(settings, "google_ads_client_id", "cid")
    monkeypatch.setattr(settings, "google_ads_client_secret", "secret")


async def test_ads_stub_501_connect_returns_501_not_500(stubbed_seams, monkeypatch):
    """A provider that still raises NotImplementedError must surface as 501.

    Driven through a synthetic stub because every READY provider is now
    implemented — the router mapping is what is under test, not the provider.
    """
    class _StubProvider:
        async def get_oauth_url(self, state):
            raise NotImplementedError("stub")

    monkeypatch.setattr(ads_router, "get_provider", lambda name: _StubProvider())

    with pytest.raises(HTTPException) as exc:
        await ads_router.connect_oauth("site_x", "google", user=_User(), db=None)
    assert exc.value.status_code == 501
    assert exc.value.detail == "Provider not yet implemented"


async def test_implemented_providers_no_longer_raise_not_implemented(stubbed_seams):
    """Contract flips asserted, not assumed. If either starts raising again,
    that provider has regressed back to a stub."""
    from apps.api.services.ads.factory import get_provider

    # Phase 2 flip.
    assert (await get_provider("meta").get_oauth_url("state")).startswith(
        "https://www.facebook.com/"
    )
    # Phase 3 flip.
    assert (await get_provider("google").get_oauth_url("state")).startswith(
        "https://accounts.google.com/"
    )


async def test_ads_stub_501_mock_mode_still_works(monkeypatch, stubbed_seams):
    """Sanity: with mock mode ON the same call succeeds — the 501 is specific to
    the non-mock stub path, not a blanket failure."""
    monkeypatch.setattr(settings, "mock_external_apis", True)
    resp = await ads_router.connect_oauth("site_x", "meta", user=_User(), db=None)
    assert resp.auth_url.startswith("https://mock.meta.test/")
