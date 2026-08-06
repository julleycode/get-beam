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


# ──────────────────── wrong_site found-id surfacing (AC4/AC5) ────────────────────
#
# `_verify` calls verify_pixel WITHOUT a db session (E2): passing one would route
# through _verify_via_events, which can override a wrong_site verdict with
# `verified` when the CURRENT site_id has recent traffic — masking the static
# result these tests are about.


async def test_wrong_site_returns_found_id(fake_fetch):
    html = '<script src="/tracker.js" data-site="site_ffffffffffff"></script>'
    res = await _verify(fake_fetch, html)
    assert res["status"] == "wrong_site"
    assert res["found_site_id"] == "site_ffffffffffff"
    assert "site_ffffffffffff" in res["message"]


async def test_wrong_site_found_id_escaped_rsc_shape(fake_fetch):
    html = (
        '<script src="/tracker.js"></script>'
        '<script>self.__next_f.push([1,"data-site\\":\\"site_ffffffffffff\\""])</script>'
    )
    res = await _verify(fake_fetch, html)
    assert res["status"] == "wrong_site"
    assert res["found_site_id"] == "site_ffffffffffff"


async def test_wrong_site_found_id_entity_escaped_shape(fake_fetch):
    html = (
        '<script src="/tracker.js"></script>'
        "&lt;script data-site=&quot;site_ffffffffffff&quot;&gt;"
    )
    res = await _verify(fake_fetch, html)
    assert res["status"] == "wrong_site"
    assert res["found_site_id"] == "site_ffffffffffff"


async def test_wrong_site_found_id_query_param_shape(fake_fetch):
    html = '<script src="/tracker.js?site=site_ffffffffffff"></script>'
    res = await _verify(fake_fetch, html)
    assert res["status"] == "wrong_site"
    assert res["found_site_id"] == "site_ffffffffffff"


async def test_wrong_site_without_extractable_id_falls_back(fake_fetch):
    html = '<script src="/tracker.js"></script>'
    res = await _verify(fake_fetch, html)
    assert res["status"] == "wrong_site"
    assert res["found_site_id"] is None
    assert "does not match" in res["message"]


async def test_found_site_id_is_none_for_other_statuses(fake_fetch):
    verified = await _verify(
        fake_fetch, f'<script src="/tracker.js" data-site="{SITE_ID}"></script>'
    )
    assert verified["status"] == "verified"
    assert verified["found_site_id"] is None

    missing = await _verify(fake_fetch, "<html><body>nothing</body></html>")
    assert missing["status"] == "not_found"
    assert missing["found_site_id"] is None


async def test_wrong_site_never_resolves_foreign_owner(fake_fetch):
    """AC5 — the found id is a bare public string, never resolved to a tenant."""
    html = '<script src="/tracker.js" data-site="site_ffffffffffff"></script>'
    res = await _verify(fake_fetch, html)

    assert set(res) == {"status", "verified", "message", "found_site_id"}
    assert res["found_site_id"] == "site_ffffffffffff"
    blob = repr(res).lower()
    for leak in ("user_id", "owner", "email", "site_name", "tenant"):
        assert leak not in blob

    import inspect

    source = inspect.getsource(pixel_verifier)
    assert "models.site import" not in source
    assert "select(Site" not in source
