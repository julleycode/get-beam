"""G2 — GET /api/v1/greeting against real Postgres + Redis.

Flag-ON runs set BOTH ``onsite_greeting_enabled`` AND ``ip_org_lookup_enabled``
(else ``lookup_ip_org`` no-ops and every show:true assertion would be vacuous),
force ``mock_external_apis`` False, seed a real ``ip_org_prefixes`` row and
inject a PUBLIC client IP (ASGITransport's default client is 127.0.0.1).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.config import settings
from apps.api.models.site import Site
from apps.api.models.visitor import Visitor

pytestmark = pytest.mark.integration

SITE = "site_greet_it"
ORIGIN = "https://www.customer-it.com"
CLIENT_IP = "203.0.113.5"
EYEBALL_IP = "198.51.100.9"
ALLOWED = {"show", "template_id", "text", "cta_url"}


async def _seed(test_engine, *, greeting_enabled=True, templates=None, visitors=()):
    sf = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with sf() as s:
        s.add(
            Site(
                site_id=SITE,
                user_id=uuid.uuid4(),
                name="Customer",
                url="customer-it.com",  # schemeless on purpose
                greeting_enabled=greeting_enabled,
                greeting_templates=templates,
            )
        )
        for vid, dnr in visitors:
            now = datetime.utcnow()
            s.add(Visitor(site_id=SITE, visitor_id=vid, do_not_resolve=dnr, first_seen=now, last_seen=now))
        for prefix, name, kind in (
            ("203.0.113.0/24", "Globex Corp", "org"),
            ("198.51.100.0/24", "Comcast Cable", "eyeball"),
        ):
            await s.execute(
                text(
                    "INSERT INTO ip_org_prefixes (id, prefix, asn, org_name, org_kind, source) "
                    "VALUES (gen_random_uuid(), CAST(:p AS cidr), 64500, :n, :k, 'test')"
                ),
                {"p": prefix, "n": name, "k": kind},
            )
        await s.commit()


@pytest.fixture
async def flags_on(monkeypatch):
    monkeypatch.setattr(settings, "onsite_greeting_enabled", True)
    monkeypatch.setattr(settings, "ip_org_lookup_enabled", True)
    monkeypatch.setattr(settings, "mock_external_apis", False)
    # Fresh Redis client per test loop + no stale per-IP company cache.
    import apps.api.services.redis_client as rc

    rc._client = None
    r = rc.get_redis()
    try:
        keys = await r.keys("greeting_company:*")
        if keys:
            await r.delete(*keys)
    except Exception:
        pass
    yield
    try:
        await r.aclose()
    except Exception:
        pass
    rc._client = None


def _client(ip: str) -> AsyncClient:
    from apps.api.main import app

    return AsyncClient(transport=ASGITransport(app=app, client=(ip, 1234)), base_url="http://test")


async def _get(ip=CLIENT_IP, origin=ORIGIN, **params):
    params.setdefault("site_id", SITE)
    headers = {"origin": origin} if origin is not None else {}
    async with _client(ip) as c:
        return await c.get("/api/v1/greeting", params=params, headers=headers)


async def test_flag_on_shows_company_with_allow_list_and_no_store(test_client, test_engine, flags_on):
    await _seed(
        test_engine,
        templates={"default": {"text": "Hi {company}!", "cta_url": "https://customer-it.com/demo"}},
    )
    r = await _get()
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "show": True,
        "template_id": "default",
        "text": "Hi Globex Corp!",
        "cta_url": "https://customer-it.com/demo",
    }
    assert set(body) <= ALLOWED
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in r.headers
    for leak in (CLIENT_IP, "64500", "globex.com"):
        assert leak not in r.text


async def test_flag_off_hidden(test_client, test_engine, flags_on, monkeypatch):
    await _seed(test_engine)
    monkeypatch.setattr(settings, "onsite_greeting_enabled", False)
    r = await _get()
    assert r.status_code == 200 and r.json() == {"show": False}
    assert r.headers["cache-control"] == "no-store"


async def test_site_flag_off_hidden(test_client, test_engine, flags_on):
    await _seed(test_engine, greeting_enabled=False)
    assert (await _get()).json() == {"show": False}


@pytest.mark.parametrize("origin", [None, "null", "https://evil.com", "https://shop.customer-it.com"])
async def test_origin_missing_null_or_mismatch_hidden(test_client, test_engine, flags_on, origin):
    await _seed(test_engine)
    r = await _get(origin=origin)
    assert r.status_code == 200 and r.json() == {"show": False}


async def test_unknown_site_hidden(test_client, test_engine, flags_on):
    await _seed(test_engine)
    r = await _get(site_id="site_nope")
    assert r.status_code == 200 and r.json() == {"show": False}


async def test_eyeball_isp_hidden(test_client, test_engine, flags_on):
    await _seed(test_engine)
    assert (await _get(ip=EYEBALL_IP)).json() == {"show": False}


async def test_do_not_resolve_visitor_hidden_same_ip(test_client, test_engine, flags_on):
    await _seed(test_engine, visitors=[("vA", False), ("vB", True)])
    assert (await _get(v="vA")).json()["show"] is True
    assert (await _get(v="vB")).json() == {"show": False}
    assert (await _get(v="x" * 101)).json() == {"show": False}


async def test_rate_limit_429_only(test_client, test_engine, flags_on):
    from apps.api.services.rate_limiter import limiter, site_limiter

    await _seed(test_engine)
    limiter.enabled = True
    try:
        for lim in (limiter, site_limiter):
            try:
                lim.reset()
            except Exception:
                pass
        codes = []
        for _ in range(32):
            codes.append((await _get()).status_code)
        assert set(codes) <= {200, 429}
        assert codes[:30] == [200] * 30
        assert 429 in codes[30:]
    finally:
        for lim in (limiter, site_limiter):
            try:
                lim.reset()
            except Exception:
                pass
        limiter.enabled = False


async def test_logs_carry_no_pii(test_client, test_engine, flags_on, monkeypatch):
    import apps.api.routers.greeting as router_mod

    captured = []

    class _Log:
        def info(self, event, **kw):
            captured.append((event, kw))

        warning = info

    monkeypatch.setattr(router_mod, "logger", _Log())
    await _seed(test_engine)
    assert (await _get(v="vid-xyz")).json()["show"] is True
    assert captured == [("greeting_decided", {"site_id": SITE, "show": True, "reason": "shown"})]
    blob = repr(captured)
    for pii in (CLIENT_IP, "Globex", "vid-xyz", "customer-it"):
        assert pii not in blob


async def test_greeting_js_served(test_client):
    r = await test_client.get("/pixel/greeting.js")
    assert r.status_code == 200
    assert "/api/v1/greeting" in r.text
    assert r.headers["access-control-allow-origin"] == "*"
