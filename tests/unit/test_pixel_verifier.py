"""Pixel verifier site-id matching tests.

Regression cover for the Next.js App Router false-positive `wrong_site`: with
next/script the raw HTML never contains a plain `data-site="..."` attribute,
only an escaped RSC flight payload (`data-site\\":\\"site_abc\\"`).

Unit lane: the SSRF guard and the HTTP fetch are both monkeypatched, no network.
"""

import pytest

from apps.api.services import pixel_verifier

SITE_ID = "site_1944ab523384"


@pytest.fixture
def fake_fetch(monkeypatch):
    """Bypass the SSRF guard and serve canned HTML from safe_get."""

    def _install(html: str):
        async def _safe(url: str) -> bool:
            return True

        class _Resp:
            text = html

        async def _get(client, url):
            return _Resp()

        monkeypatch.setattr(pixel_verifier, "is_safe_public_url", _safe)
        monkeypatch.setattr(pixel_verifier, "safe_get", _get)

    return _install


async def _verify(fake_fetch, html: str, site_id: str = SITE_ID):
    fake_fetch(html)
    return await pixel_verifier.verify_pixel("https://example.com/", site_id)


# ─────────────────────────── matching shapes ───────────────────────────

async def test_plain_double_quote_attr(fake_fetch):
    html = f'<script src="https://api.getbeam.fyi/pixel/tracker.js" data-site="{SITE_ID}"></script>'
    res = await _verify(fake_fetch, html)
    assert res["status"] == "verified"
    assert res["verified"] is True


async def test_plain_single_quote_attr(fake_fetch):
    html = f"<script src='https://api.getbeam.fyi/pixel/tracker.js' data-site='{SITE_ID}'></script>"
    res = await _verify(fake_fetch, html)
    assert res["status"] == "verified"


async def test_query_param_only(fake_fetch):
    html = f'<script src="https://api.getbeam.fyi/pixel/tracker.js?site={SITE_ID}"></script>'
    res = await _verify(fake_fetch, html)
    assert res["status"] == "verified"


async def test_app_router_rsc_payload(fake_fetch):
    """The bravestep.ai regression shape: preload link + escaped RSC payload."""
    html = (
        '<link rel="preload" href="https://api.getbeam.fyi/pixel/tracker.js" as="script"/>'
        '<script>self.__next_f.push([1,"3:['
        '[\\"$\\",\\"$L2\\",null,{\\"src\\":\\"https://api.getbeam.fyi/pixel/tracker.js\\",'
        f'\\"data-site\\":\\"{SITE_ID}\\",\\"data-api\\":\\"https://api.getbeam.fyi\\"'
        '}]"])</script>'
    )
    assert '\\"data-site\\"' in html  # literal backslashes present in file bytes
    res = await _verify(fake_fetch, html)
    assert res["status"] == "verified"


async def test_pages_router_next_data_json(fake_fetch):
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        f'{{"src":"https://api.getbeam.fyi/pixel/tracker.js","data-site":"{SITE_ID}"}}'
        "</script>"
    )
    res = await _verify(fake_fetch, html)
    assert res["status"] == "verified"


# ─────────────────────────── non-matching ───────────────────────────

async def test_different_site_id_is_wrong_site(fake_fetch):
    html = '<script src="/tracker.js" data-site="site_ffffffffffff"></script>'
    res = await _verify(fake_fetch, html)
    assert res["status"] == "wrong_site"
    assert res["verified"] is False


async def test_prefix_collision_is_not_a_match(fake_fetch):
    html = f'<script src="/tracker.js" data-site="{SITE_ID}ff"></script>'
    res = await _verify(fake_fetch, html)
    assert res["status"] == "wrong_site"
    assert res["verified"] is False


async def test_no_tracker_is_not_found(fake_fetch):
    html = "<html><body>nothing here</body></html>"
    res = await _verify(fake_fetch, html)
    assert res["status"] == "not_found"
    assert res["verified"] is False
