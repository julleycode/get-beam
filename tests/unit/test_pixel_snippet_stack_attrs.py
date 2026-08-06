"""Pixel snippet must emit data-stack attrs tracker.js understands (Phase 1).

Leadpipe is now per-site: a Leadpipe pixel is bound 1-1 to a domain (the API
answers 409 "Pixel already exists for this domain"), so the snippet carries the
site's OWN `Site.leadpipe_pixel_id`, provisioned on first fetch. The previous
shared `LEADPIPE_DEFAULT_PIXEL_ID` loaded on every site and collected on none.
"""

from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def _site(**kw):
    base = dict(
        site_id="site_test123",
        url="https://www.lab.example.com",
        consent_mode="off",
        leadpipe_pixel_id=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


@contextmanager
def _snippet_env(sites_mod, site, provision):
    """Only Leadpipe in play: other vendors blank, verify + provision stubbed."""
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(sites_mod, "verify_site_access", AsyncMock(return_value=site))
        )
        stack.enter_context(patch.object(sites_mod, "ensure_pixel_for_domain", provision))
        stack.enter_context(
            patch.object(sites_mod.settings, "api_base_url", "https://api.example.com")
        )
        for attr in ("capturify_pixel_id", "fullcontact_pixel_id", "customers_ai_pixel_id"):
            stack.enter_context(patch.object(sites_mod.settings, attr, ""))
        yield


@pytest.mark.asyncio
async def test_pixel_snippet_emits_stored_leadpipe_pixel_id():
    from apps.api.routers import sites as sites_mod

    site = _site(leadpipe_pixel_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    db = MagicMock()
    provision = AsyncMock()

    with _snippet_env(sites_mod, site, provision):
        out = await sites_mod.get_pixel_snippet(
            "site_test123", SimpleNamespace(id="u1"), db
        )

    html = out.snippet
    assert 'data-stack="1"' in html
    assert 'data-stack-leadpipe="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"' in html
    assert "data-identity-providers" not in html
    # An already-provisioned site must not re-hit the vendor on every fetch.
    provision.assert_not_awaited()


@pytest.mark.asyncio
async def test_pixel_snippet_provisions_on_first_fetch_and_stores_the_id():
    """First snippet fetch is the one moment we know an install is imminent —
    early enough to reach the pasted HTML, late enough not to burn a pixel slot
    on a site that was created and abandoned."""
    from apps.api.routers import sites as sites_mod

    site = _site(site_id="site_fresh", url="https://fresh.example.com")
    db = MagicMock()
    db.commit = AsyncMock()
    provision = AsyncMock(return_value="11111111-2222-3333-4444-555555555555")

    with _snippet_env(sites_mod, site, provision):
        out = await sites_mod.get_pixel_snippet(
            "site_fresh", SimpleNamespace(id="u1"), db
        )

    provision.assert_awaited_once_with("fresh.example.com")
    assert site.leadpipe_pixel_id == "11111111-2222-3333-4444-555555555555"
    db.commit.assert_awaited_once()
    assert 'data-stack-leadpipe="11111111-2222-3333-4444-555555555555"' in out.snippet


@pytest.mark.asyncio
async def test_snippet_still_returned_when_leadpipe_cannot_provision():
    """A Leadpipe outage must not break the install flow — the customer still
    needs Beam's own tracker. Degrade to a snippet without the vendor tag."""
    from apps.api.routers import sites as sites_mod

    site = _site(site_id="site_degraded")
    db = MagicMock()
    db.commit = AsyncMock()

    with _snippet_env(sites_mod, site, AsyncMock(return_value=None)):
        out = await sites_mod.get_pixel_snippet(
            "site_degraded", SimpleNamespace(id="u1"), db
        )

    assert "tracker.js" in out.snippet
    assert 'data-site="site_degraded"' in out.snippet
    assert "leadpipe" not in out.snippet
    assert "data-stack" not in out.snippet
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_pixel_snippet_no_stack_when_no_vendor_ids():
    from apps.api.routers import sites as sites_mod

    site = _site(site_id="site_empty")
    db = MagicMock()

    with _snippet_env(sites_mod, site, AsyncMock(return_value=None)):
        out = await sites_mod.get_pixel_snippet(
            "site_empty", SimpleNamespace(id="u1"), db
        )

    assert "data-stack" not in out.snippet
