"""Edge-case corpus for the Beam pixel verifier's site-id matching regex.

TEST-ONLY phase: this file measures the CURRENT baseline failure rate of
pixel_verifier.verify_pixel() against realistic HTML shapes. It does NOT
patch the source. Failing tests are the deliverable, not a bug in the test.

Mirrors the mocking pattern in test_pixel_verifier.py (monkeypatch
is_safe_public_url + safe_get, no network).
"""

import pytest

from apps.api.services import pixel_verifier

SITE_ID = "site_1944ab523384"


@pytest.fixture
def fake_fetch(monkeypatch):
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


def _doc(body: str) -> str:
    return (
        "<!DOCTYPE html><html><head><title>Site</title></head>"
        f"<body>{body}</body></html>"
    )


# ─────────────────────────── INSTALLED_OK corpus ───────────────────────────
# (case_id, html, expected_status="verified")

INSTALLED_OK = [
    (
        "unquoted_attr",
        _doc(
            f'<script src="https://api.getbeam.fyi/pixel/tracker.js" data-site={SITE_ID} '
            'async></script>'
        ),
    ),
    (
        "whitespace_around_equals",
        _doc(
            '<script src="https://api.getbeam.fyi/pixel/tracker.js" '
            f'data-site = "{SITE_ID}"></script>'
        ),
    ),
    (
        "split_newline_2space_indent",
        _doc(
            "<script\n"
            '  src="https://api.getbeam.fyi/pixel/tracker.js"\n'
            f'  data-site="{SITE_ID}">\n'
            "</script>"
        ),
    ),
    (
        "split_newline_deep_indent_8plus",
        _doc(
            "<script\n"
            '        src="https://api.getbeam.fyi/pixel/tracker.js"\n'
            f'        data-site="{SITE_ID}">\n'
            "</script>"
        ),
    ),
    (
        "uppercase_attr_name",
        _doc(
            f'<script src="https://api.getbeam.fyi/pixel/tracker.js" DATA-SITE="{SITE_ID}">'
            "</script>"
        ),
    ),
    (
        "mixed_case_attr_name",
        _doc(
            f"<script src='https://api.getbeam.fyi/pixel/tracker.js' Data-Site='{SITE_ID}'>"
            "</script>"
        ),
    ),
    (
        "html_entity_quot",
        _doc(
            "<script src=&quot;https://api.getbeam.fyi/pixel/tracker.js&quot; "
            f"data-site=&quot;{SITE_ID}&quot;></script>"
        ),
    ),
    (
        "html_entity_numeric_34",
        _doc(
            "<script src=&#34;https://api.getbeam.fyi/pixel/tracker.js&#34; "
            f"data-site=&#34;{SITE_ID}&#34;></script>"
        ),
    ),
    (
        "rsc_single_escaped_varied_payload",
        _doc(
            '<link rel="preload" href="https://api.getbeam.fyi/pixel/tracker.js" as="script"/>'
            '<script>self.__next_f.push([1,"7:['
            '[\\"$\\",\\"$L9\\",null,{\\"id\\":\\"beam-pixel\\",\\"strategy\\":\\"afterInteractive\\",'
            '\\"src\\":\\"https://api.getbeam.fyi/pixel/tracker.js\\",'
            f'\\"data-site\\":\\"{SITE_ID}\\",\\"data-env\\":\\"prod\\"'
            '}]"])</script>'
        ),
    ),
    (
        "rsc_double_escaped_nested_json",
        _doc(
            '<script>window.__PAYLOAD__=\'{"flight":"3:[[\\\\"$\\\\",\\\\"$L2\\\\",null,'
            '{\\\\"src\\\\":\\\\"https://api.getbeam.fyi/pixel/tracker.js\\\\",'
            f'\\\\"data-site\\\\":\\\\"{SITE_ID}\\\\"}}]"}}\'</script>'
        ),
    ),
    (
        "pages_router_next_data_deep_props",
        _doc(
            '<script id="__NEXT_DATA__" type="application/json">'
            '{"props":{"pageProps":{"pixel":{"src":"https://api.getbeam.fyi/pixel/tracker.js",'
            f'"data-site":"{SITE_ID}"}}}},"page":"/"}}'
            "</script>"
        ),
    ),
    (
        "nuxt_window_nuxt_payload",
        _doc(
            "<script>window.__NUXT__="
            '{"data":{},"pixel":{"src":"https://api.getbeam.fyi/pixel/tracker.js",'
            f'"data-site":"{SITE_ID}"}}}}</script>'
        ),
    ),
    (
        "many_attrs_between_src_and_data_site",
        _doc(
            '<script src="https://api.getbeam.fyi/pixel/tracker.js" nonce="abc123" '
            f'defer async crossorigin="anonymous" data-site="{SITE_ID}"></script>'
        ),
    ),
    (
        "query_param_only_preload_link",
        _doc(
            f'<link rel="preload" href="https://api.getbeam.fyi/pixel/tracker.js?site={SITE_ID}" '
            'as="script">'
        ),
    ),
    (
        "query_param_with_trailing_params",
        _doc(
            '<script src="https://api.getbeam.fyi/pixel/tracker.js?'
            f'site={SITE_ID}&v=2"></script>'
        ),
    ),
    (
        "query_param_entity_amp_before_site",
        _doc(
            '<script src="https://api.getbeam.fyi/pixel/tracker.js?'
            f'v=2&amp;site={SITE_ID}"></script>'
        ),
    ),
    (
        "attr_value_trailing_whitespace",
        _doc(
            '<script src="https://api.getbeam.fyi/pixel/tracker.js" '
            f'data-site="{SITE_ID} "></script>'
        ),
    ),
    (
        "script_after_body_close",
        (
            "<!DOCTYPE html><html><head><title>Site</title></head><body>content</body>"
            '<script src="https://api.getbeam.fyi/pixel/tracker.js" '
            f'data-site="{SITE_ID}"></script></html>'
        ),
    ),
    (
        "minified_single_line_with_noise",
        _doc(
            '<div class="a b c" style="color:red">x</div>'
            '<script src="https://api.getbeam.fyi/pixel/tracker.js" id="beam" '
            'data-foo="1" data-bar="2" data-baz="3" data-qux="4" data-noise="'
            + ("z" * 150)
            + f'" data-site="{SITE_ID}" data-more="5"></script>'
        ),
    ),
    (
        "json_config_blob_pixel_object",
        _doc(
            "<script>window.__CONFIG__="
            '{"pixel":{"src":"https://api.getbeam.fyi/pixel/tracker.js",'
            f'"data-site":"{SITE_ID}"}}}}</script>'
        ),
    ),
    (
        "array_pair_hydration_shape",
        _doc(
            '<script>window.__PROPS__=[["src","https://api.getbeam.fyi/pixel/tracker.js"],'
            f'["data-site","{SITE_ID}"]]</script>'
        ),
    ),
    (
        "plain_attr_with_type_module",
        _doc(
            '<script type="module" src="https://api.getbeam.fyi/pixel/tracker.js" '
            f'data-site="{SITE_ID}"></script>'
        ),
    ),
    (
        "data_site_before_src_attr_order_swapped",
        _doc(
            f'<script data-site="{SITE_ID}" src="https://api.getbeam.fyi/pixel/tracker.js">'
            "</script>"
        ),
    ),
    (
        "gtm_custom_html_tag_wrapping_snippet",
        _doc(
            "<!-- Google Tag Manager Custom HTML Tag -->"
            '<script src="https://api.getbeam.fyi/pixel/tracker.js" '
            f'data-site="{SITE_ID}"></script>'
        ),
    ),
    (
        "wordpress_footer_php_echoed_snippet",
        _doc(
            "<!-- wp_footer() output -->\n"
            '<script src="https://api.getbeam.fyi/pixel/tracker.js" '
            f'data-site="{SITE_ID}" data-wp-injected="1"></script>\n'
        ),
    ),
]


@pytest.mark.parametrize("case_id,html", INSTALLED_OK, ids=[c[0] for c in INSTALLED_OK])
async def test_installed_ok(fake_fetch, case_id, html):
    res = await _verify(fake_fetch, html)
    assert res["status"] == "verified", (
        f"[{case_id}] expected verified, got {res['status']}"
    )


# ─────────────────────────── MUST_REJECT corpus ───────────────────────────
# (case_id, html, expected_status)

MUST_REJECT = [
    (
        "different_site_id_throughout",
        _doc(
            '<script src="https://api.getbeam.fyi/pixel/tracker.js" '
            'data-site="site_ffffffffffff"></script>'
        ),
        "wrong_site",
    ),
    (
        "prefix_collision_extra_suffix",
        _doc(
            '<script src="https://api.getbeam.fyi/pixel/tracker.js" '
            f'data-site="{SITE_ID}ff"></script>'
        ),
        "wrong_site",
    ),
    (
        "suffix_collision_prefixed_id",
        _doc(
            '<script src="https://api.getbeam.fyi/pixel/tracker.js" '
            f'data-site="x_{SITE_ID}"></script>'
        ),
        "wrong_site",
    ),
    (
        "empty_spa_shell_no_tracker",
        _doc('<div id="root"></div><script src="/static/js/main.abc123.js"></script>'),
        "not_found",
    ),
    (
        "gtm_only_no_tracker_string",
        _doc(
            "<script>(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':"
            "new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],"
            "j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;"
            "j.src='https://www.googletagmanager.com/gtm.js?id='+i+dl;"
            "f.parentNode.insertBefore(j,f);})(window,document,'script','dataLayer','GTM-ABCDEF');"
            "</script>"
        ),
        "not_found",
    ),
    (
        "cloudflare_challenge_interstitial",
        (
            "<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
            '<body class="no-js"><div id="cf-wrapper">'
            '<div class="cf-alert cf-alert-error cf-cookie-error" id="cookie-alert">'
            "Please enable cookies.</div>"
            '<div id="challenge-stage"></div></div></body></html>'
        ),
        "not_found",
    ),
]


@pytest.mark.parametrize(
    "case_id,html,expected", MUST_REJECT, ids=[c[0] for c in MUST_REJECT]
)
async def test_must_reject(fake_fetch, case_id, html, expected):
    res = await _verify(fake_fetch, html)
    assert res["status"] == expected, (
        f"[{case_id}] expected {expected}, got {res['status']}"
    )
    assert res["verified"] is False


# ─────────────── ACCEPTED false positive (documented tradeoff) ───────────────
#
# An entity-escaped snippet inside a <pre><code> block now MATCHES and returns
# verified. This is a KNOWN, ACCEPTED false positive, not an oversight:
#
#   * The HTML-entity window in the site-id regex is what makes the real
#     `html_entity_quot` / `html_entity_numeric_34` installs verify at all.
#   * The exact same byte shape is ALSO a real working install: Webflow and
#     Squarespace embed builders store custom code entity-escaped inside an
#     attribute and inject it via innerHTML at runtime. Statically, a doc page
#     and a builder-injected install are indistinguishable.
#   * Rejecting this shape would re-break the genuine entity installs, which
#     are far more common than a customer hosting our own snippet as prose on
#     the page we are asked to verify.
#
# Net: we accept one rare over-verify to fix a whole class of under-verifies.
# Distinguishing the two would need structural HTML parsing (match only inside
# real <script>/<link> tags), which is out of scope for the regex layer.


async def test_escaped_snippet_in_code_block_verifies_accepted_tradeoff(fake_fetch):
    html = _doc(
        "<p>Paste this snippet on your site:</p>"
        "<pre><code>&lt;script src=&quot;https://api.getbeam.fyi/pixel/tracker.js&quot; "
        f"data-site=&quot;{SITE_ID}&quot;&gt;&lt;/script&gt;</code></pre>"
    )
    res = await _verify(fake_fetch, html)
    # Documented accepted false positive — see the comment block above.
    assert res["status"] == "verified"
    assert res["verified"] is True


# ─────────────────────── event-based verification fallback ───────────────────────
# Static regex cannot see GTM Custom HTML installs, JS-only SPA injection, or
# any site behind a bot challenge. When the static check fails but the site is
# demonstrably sending us events, we verify on live traffic instead.


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeDB:
    """Minimal AsyncSession stand-in: records calls, no Postgres."""

    def __init__(self, row=None, raises: bool = False):
        self._row = row
        self._raises = raises
        self.execute_calls = 0

    async def execute(self, stmt):
        self.execute_calls += 1
        if self._raises:
            raise RuntimeError("db down")
        return _FakeResult(self._row)


NO_PIXEL_HTML = _doc('<div id="root"></div>')
GTM_ONLY_HTML = _doc(
    "<script>(function(w,d,s,l,i){j.src='https://www.googletagmanager.com/gtm.js';"
    "})(window,document,'script','dataLayer','GTM-ABCDEF');</script>"
)
INSTALLED_HTML = _doc(
    '<script src="https://api.getbeam.fyi/pixel/tracker.js" '
    f'data-site="{SITE_ID}"></script>'
)


async def test_event_fallback_verifies_when_static_not_found(fake_fetch):
    fake_fetch(GTM_ONLY_HTML)
    db = _FakeDB(row="evt_1")
    res = await pixel_verifier.verify_pixel("https://example.com/", SITE_ID, db=db)
    assert res["status"] == "verified"
    assert res["verified"] is True
    assert "traffic" in res["message"].lower()
    assert db.execute_calls == 1


async def test_event_fallback_no_events_stays_not_found(fake_fetch):
    fake_fetch(NO_PIXEL_HTML)
    db = _FakeDB(row=None)
    res = await pixel_verifier.verify_pixel("https://example.com/", SITE_ID, db=db)
    assert res["status"] == "not_found"
    assert res["verified"] is False
    assert db.execute_calls == 1


async def test_event_fallback_applies_on_fetch_error(monkeypatch):
    async def _unsafe(url: str) -> bool:
        return False  # forces the fetch_error branch without any network

    monkeypatch.setattr(pixel_verifier, "is_safe_public_url", _unsafe)
    db = _FakeDB(row="evt_1")
    res = await pixel_verifier.verify_pixel("https://example.com/", SITE_ID, db=db)
    assert res["status"] == "verified"
    assert res["verified"] is True


async def test_static_verified_skips_db_fast_path(fake_fetch):
    fake_fetch(INSTALLED_HTML)
    db = _FakeDB(row="evt_1")
    res = await pixel_verifier.verify_pixel("https://example.com/", SITE_ID, db=db)
    assert res["status"] == "verified"
    assert db.execute_calls == 0, "static match must not hit the DB"


async def test_legacy_signature_without_db_is_static_only(fake_fetch):
    fake_fetch(GTM_ONLY_HTML)
    res = await pixel_verifier.verify_pixel("https://example.com/", SITE_ID)
    assert res["status"] == "not_found"
    assert res["verified"] is False


async def test_event_fallback_db_error_returns_static_result(fake_fetch):
    fake_fetch(GTM_ONLY_HTML)
    db = _FakeDB(raises=True)
    res = await pixel_verifier.verify_pixel("https://example.com/", SITE_ID, db=db)
    assert res["status"] == "not_found"
    assert res["verified"] is False
