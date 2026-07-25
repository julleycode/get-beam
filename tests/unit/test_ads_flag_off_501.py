"""D6 — ad_audiences_enabled=False returns HTTP 501.

One explicit, documented status for the flag-off case, matching the
_OAUTH_CREDENTIALS-missing 501 precedent in routers/crm.py (route reachable,
feature structurally unavailable server-side).

Pure unit test: the flag guard runs before any DB access, so db=None is safe.
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
def flag_off(monkeypatch):
    monkeypatch.setattr(settings, "ad_audiences_enabled", False)
    # Mock mode on, so nothing but the flag can be responsible for the failure.
    monkeypatch.setattr(settings, "mock_external_apis", True)


@pytest.mark.parametrize("provider", ["meta", "google", "linkedin"])
async def test_ads_flag_off_501_connect(flag_off, provider):
    with pytest.raises(HTTPException) as exc:
        await ads_router.connect_oauth("site_x", provider, user=_User(), db=None)
    assert exc.value.status_code == 501
    assert "not enabled" in exc.value.detail


async def test_ads_flag_off_501_beats_the_not_ready_400(flag_off):
    """LinkedIn is also not ready (400). With the flag off, the flag guard wins —
    so the status code is deterministic regardless of provider readiness."""
    with pytest.raises(HTTPException) as exc:
        await ads_router.connect_oauth("site_x", "linkedin", user=_User(), db=None)
    assert exc.value.status_code == 501


async def test_ads_flag_off_501_unknown_provider_still_404(flag_off):
    """Unknown ids must not leak through the flag guard as 501."""
    with pytest.raises(HTTPException) as exc:
        await ads_router.connect_oauth("site_x", "tiktok", user=_User(), db=None)
    assert exc.value.status_code == 404
