"""D5 — stub-provider defense in depth.

With ad_audiences_enabled=True but MOCK_EXTERNAL_APIS=False, a provider that is
still a stub raises NotImplementedError. The router must surface that as a clean
HTTP 501, never an unhandled 500.

Phase 2 note (26-07-26): `meta` is no longer a stub — its real Graph API path
landed, so it no longer raises NotImplementedError and is out of these
assertions. `google` remains the stub until Phase 3 wires it, and keeps proving
the router's 501 mapping. The meta 501-on-flag-off path is unaffected and still
covered by test_ads_flag_off_501.py.

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


@pytest.mark.parametrize("provider", ["google"])  # meta is implemented (Phase 2)
async def test_ads_stub_501_connect_returns_501_not_500(stubbed_seams, provider):
    with pytest.raises(HTTPException) as exc:
        await ads_router.connect_oauth("site_x", provider, user=_User(), db=None)
    assert exc.value.status_code == 501
    assert exc.value.detail == "Provider not yet implemented"


async def test_ads_stub_501_provider_really_raises_not_implemented(stubbed_seams):
    """Guards against a vacuous pass: the 501 above must come from the stub
    raising, not from the provider quietly succeeding."""
    from apps.api.services.ads.factory import get_provider

    with pytest.raises(NotImplementedError):
        await get_provider("google").get_oauth_url("state")

    # Phase 2 contract flip, asserted rather than assumed: meta no longer
    # raises here. If this ever starts raising again, the Meta provider has
    # regressed back to a stub.
    assert (await get_provider("meta").get_oauth_url("state")).startswith(
        "https://www.facebook.com/"
    )


async def test_ads_stub_501_mock_mode_still_works(monkeypatch, stubbed_seams):
    """Sanity: with mock mode ON the same call succeeds — the 501 is specific to
    the non-mock stub path, not a blanket failure."""
    monkeypatch.setattr(settings, "mock_external_apis", True)
    resp = await ads_router.connect_oauth("site_x", "meta", user=_User(), db=None)
    assert resp.auth_url.startswith("https://mock.meta.test/")
