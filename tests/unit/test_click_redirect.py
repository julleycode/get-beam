"""Own-data P7c: email click-tracking redirect — pure-helper unit tests.

The redirect must be PII-safe (email rides as an opaque token, never plaintext)
and open-redirect-safe (only ever redirects to the site's own host).
"""
from urllib.parse import parse_qs, urlsplit

from apps.api.routers.click import build_click_url, safe_dest, svid_cookie_name
from apps.api.services.link_decorator import decode_bid


class TestSafeDest:
    def test_own_host(self):
        assert safe_dest("https://acme.com/x", "https://acme.com") == "https://acme.com/x"

    def test_subdomain_allowed(self):
        assert safe_dest("https://shop.acme.com/x", "https://acme.com") == "https://shop.acme.com/x"

    def test_www_allowed(self):
        assert safe_dest("https://www.acme.com/x", "https://acme.com") == "https://www.acme.com/x"

    def test_foreign_host_falls_back_to_homepage(self):
        assert safe_dest("https://evil.com/phish", "https://acme.com") == "https://acme.com"

    def test_non_http_scheme_falls_back(self):
        assert safe_dest("javascript:alert(1)", "https://acme.com") == "https://acme.com"
        assert safe_dest("", "https://acme.com") == "https://acme.com"

    def test_lookalike_and_suffix_hosts_blocked(self):
        assert safe_dest("https://notacme.com/x", "https://acme.com") == "https://acme.com"
        assert safe_dest("https://acme.com.evil.com/x", "https://acme.com") == "https://acme.com"
        assert safe_dest("https://acme-com.evil.com/x", "https://acme.com") == "https://acme.com"

    def test_userinfo_tricks(self):
        # Real host is after the @ — acme.com@evil.com resolves to evil.com (blocked);
        # evil.com@acme.com resolves to acme.com (allowed).
        assert safe_dest("https://acme.com@evil.com/x", "https://acme.com") == "https://acme.com"
        assert safe_dest("https://evil.com@acme.com/x", "https://acme.com") == "https://evil.com@acme.com/x"

    def test_backslash_and_whitespace_parser_differential_blocked(self):
        # Browsers treat \ as / in the authority; urlsplit does not. Reject outright.
        for bad in (
            "https://evil.com\\.acme.com/x",
            "https://evil.com\t.acme.com/x",
            "https://evil.com\n.acme.com/x",
            "https://acme.com /x",
        ):
            assert safe_dest(bad, "https://acme.com") == "https://acme.com"

    def test_protocol_relative_blocked(self):
        assert safe_dest("//evil.com/x", "https://acme.com") == "https://acme.com"


class TestBuildClickUrl:
    def test_builds_and_token_roundtrips(self):
        url = build_click_url("https://api.beam.fyi", "site_x", "https://acme.com/p", "cto@buyer.com")
        assert url.startswith("https://api.beam.fyi/c/site_x?t=")
        q = parse_qs(urlsplit(url).query)
        assert decode_bid(q["t"][0]) == "cto@buyer.com"
        assert q["u"][0] == "https://acme.com/p"

    def test_no_plaintext_email_in_url(self):
        url = build_click_url("https://api.beam.fyi", "s", "https://acme.com", "cto@buyer.com")
        assert "cto@buyer.com" not in url
        assert "cto%40buyer.com" not in url


class TestBuildClickUrlCtaParams:
    def test_new_kwargs_none_is_byte_identical_shape(self):
        url = build_click_url("https://api.beam.fyi", "s", "https://acme.com/p", "a@b.com")
        assert set(parse_qs(urlsplit(url).query)) == {"t", "u"}

    def test_emits_ct_cid_tp(self):
        url = build_click_url(
            "https://api.beam.fyi", "s", "https://acme.com/p", "a@b.com",
            cta_type="free_trial", campaign_id="c1", touchpoint_id="t1",
        )
        q = parse_qs(urlsplit(url).query)
        assert q["ct"] == ["free_trial"] and q["cid"] == ["c1"] and q["tp"] == ["t1"]


# ─── /c/ ct handling (signal-creative-cta, AC5-unit) ─────────────────────────

import uuid as _uuid  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

_SITE = "https://acme.com"
_CFG = {"types": {"free_trial": {"url": "https://acme.com/trial"},
                  "resource": {"url": "https://evil.com/guide"}}}


class _FakeDb:
    """Records every execute; answers Site.url, then (cta_config, booking_url),
    then the touchpoint tenant check."""

    def __init__(self, cta_row=(_CFG, "https://cal.com/acme"), tp_found=False):
        self.calls: list[str] = []
        self.added: list = []
        self._cta_row = cta_row
        self._tp_found = tp_found

    async def execute(self, stmt):
        sql = str(stmt)
        self.calls.append(sql)
        r = MagicMock()
        if "cta_config" in sql:
            r.first.return_value = self._cta_row
        elif "campaign_touchpoints" in sql and sql.lstrip().upper().startswith("SELECT"):
            r.scalar_one_or_none.return_value = _uuid.uuid4() if self._tp_found else None
        else:
            r.scalar_one_or_none.return_value = _SITE
        return r

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def rollback(self):
        pass


async def _hit(monkeypatch, db, params, flag=True):
    from apps.api.config import settings
    from apps.api.main import app
    from apps.api.models.database import get_db

    monkeypatch.setattr(settings, "cta_types_enabled", flag)
    app.dependency_overrides[get_db] = lambda: db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            return await c.get("/c/site1", params=params, follow_redirects=False)
    finally:
        app.dependency_overrides.pop(get_db, None)


class TestCtaRedirect:
    @pytest.mark.asyncio
    async def test_flag_off_ignores_ct_and_is_legacy(self, monkeypatch):
        db = _FakeDb()
        r = await _hit(monkeypatch, db, {"ct": "free_trial", "u": "https://acme.com/x"}, flag=False)
        assert r.headers["location"] == "https://acme.com/x"
        assert len(db.calls) == 1 and not db.added  # query sequence unchanged

    @pytest.mark.asyncio
    async def test_valid_ct_redirects_to_stored_url_and_records(self, monkeypatch):
        db = _FakeDb()
        r = await _hit(monkeypatch, db, {"ct": "free_trial", "u": "https://acme.com/other"})
        assert r.headers["location"] == "https://acme.com/trial"
        assert [e.cta_type for e in db.added] == ["free_trial"]
        assert db.added[0].campaign_id is None

    @pytest.mark.asyncio
    async def test_book_demo_uses_booking_url_cross_domain(self, monkeypatch):
        db = _FakeDb()
        r = await _hit(monkeypatch, db, {"ct": "book_demo", "u": "https://evil.com/p"})
        assert r.headers["location"] == "https://cal.com/acme"

    @pytest.mark.asyncio
    async def test_foreign_u_never_used(self, monkeypatch):
        db = _FakeDb(cta_row=(None, None))
        r = await _hit(monkeypatch, db, {"ct": "free_trial", "u": "https://evil.com/p"})
        assert r.headers["location"] == _SITE

    @pytest.mark.asyncio
    async def test_reply_and_unknown_fall_back_to_safe_dest(self, monkeypatch):
        db = _FakeDb()
        r = await _hit(monkeypatch, db, {"ct": "reply", "u": "https://acme.com/x"})
        assert r.headers["location"] == "https://acme.com/x"
        assert [e.cta_type for e in db.added] == ["reply"]
        db2 = _FakeDb()
        r = await _hit(monkeypatch, db2, {"ct": "bogus", "u": "https://acme.com/x"})
        assert r.headers["location"] == "https://acme.com/x"
        assert len(db2.calls) == 1 and not db2.added

    @pytest.mark.asyncio
    async def test_site_host_type_rechecked_at_redirect(self, monkeypatch):
        db = _FakeDb()
        r = await _hit(monkeypatch, db, {"ct": "resource", "u": "https://acme.com/x"})
        assert r.headers["location"] == "https://acme.com/x"  # stored foreign URL refused

    @pytest.mark.asyncio
    async def test_invalid_cid_and_tp_dropped(self, monkeypatch):
        db = _FakeDb()
        r = await _hit(monkeypatch, db, {"ct": "free_trial", "cid": "nope", "tp": "nope"})
        assert r.headers["location"] == "https://acme.com/trial"
        assert db.added[0].campaign_id is None
        assert not any("campaign_touchpoints" in c for c in db.calls)

    @pytest.mark.asyncio
    async def test_valid_cid_stored(self, monkeypatch):
        db = _FakeDb()
        cid = _uuid.uuid4()
        await _hit(monkeypatch, db, {"ct": "free_trial", "cid": str(cid)})
        assert db.added[0].campaign_id == cid

    @pytest.mark.asyncio
    async def test_tenant_valid_tp_appends_tp_param(self, monkeypatch):
        tp = str(_uuid.uuid4())
        db = _FakeDb(tp_found=True)
        r = await _hit(monkeypatch, db, {"ct": "free_trial", "tp": tp})
        assert r.headers["location"] == f"https://acme.com/trial?_tp={tp}"

    @pytest.mark.asyncio
    async def test_foreign_tp_ignored(self, monkeypatch):
        db = _FakeDb(tp_found=False)
        r = await _hit(monkeypatch, db, {"ct": "free_trial", "tp": str(_uuid.uuid4())})
        assert r.headers["location"] == "https://acme.com/trial"


def test_svid_cookie_name_matches_events_scheme():
    assert svid_cookie_name("beam_getbeam_fyi") == "_rta_svid_beam_getbeam_fyi"
    assert svid_cookie_name("a-b.c") == "_rta_svid_abc"  # non-alnum stripped, same as events.py
