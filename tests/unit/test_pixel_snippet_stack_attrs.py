"""Pixel snippet must emit data-stack attrs tracker.js understands (Phase 1)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_pixel_snippet_emits_leadpipe_stack_attrs():
    from apps.api.routers import sites as sites_mod

    site = SimpleNamespace(
        site_id="site_test123",
        consent_mode="off",
    )
    user = SimpleNamespace(id="u1")
    db = MagicMock()

    with (
        patch.object(sites_mod, "verify_site_access", AsyncMock(return_value=site)),
        patch.object(sites_mod.settings, "api_base_url", "https://api.example.com"),
        patch.object(
            sites_mod.settings, "leadpipe_default_pixel_id", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        ),
        patch.object(sites_mod.settings, "capturify_pixel_id", ""),
        patch.object(sites_mod.settings, "fullcontact_pixel_id", ""),
        patch.object(sites_mod.settings, "customers_ai_pixel_id", ""),
    ):
        out = await sites_mod.get_pixel_snippet("site_test123", user, db)

    html = out.snippet
    assert 'data-stack="1"' in html
    assert 'data-stack-leadpipe="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"' in html
    assert "data-identity-providers" not in html


@pytest.mark.asyncio
async def test_pixel_snippet_no_stack_when_no_vendor_ids():
    from apps.api.routers import sites as sites_mod

    site = SimpleNamespace(
        site_id="site_empty",
        consent_mode="off",
    )
    user = SimpleNamespace(id="u1")
    db = MagicMock()

    with (
        patch.object(sites_mod, "verify_site_access", AsyncMock(return_value=site)),
        patch.object(sites_mod.settings, "api_base_url", "https://api.example.com"),
        patch.object(sites_mod.settings, "leadpipe_default_pixel_id", ""),
        patch.object(sites_mod.settings, "capturify_pixel_id", ""),
        patch.object(sites_mod.settings, "fullcontact_pixel_id", ""),
        patch.object(sites_mod.settings, "customers_ai_pixel_id", ""),
    ):
        out = await sites_mod.get_pixel_snippet("site_empty", user, db)

    assert "data-stack" not in out.snippet
