"""Agent-gateway Phase 2 — public read surface (AC6, AC7, AC8).

The load-bearing property here is the tenant-exposure posture: flag off,
unknown site, missing profile and disabled profile must be INDISTINGUISHABLE —
one identical 404, never a 403, never a different status per case.

In-process ASGI tests with ``get_db`` overridden. No PostgreSQL, no Redis, no
network. Unit lane.
"""

import uuid
from datetime import datetime, timezone

import pytest

import apps.api.main  # noqa: F401 — registers every ORM model
from httpx import ASGITransport, AsyncClient

from apps.api.config import settings
from apps.api.main import app
from apps.api.models.agent_profile import AgentProfile
from apps.api.models.database import get_db
from apps.api.models.site import Site
from apps.api.services.agent_gateway import (
    AGENT_CACHE_CONTROL,
    build_llms_txt,
    build_manifest,
    build_offers,
    resolve_public_profile,
)

pytestmark = pytest.mark.unit


class _Result:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value


class FakeSession:
    def __init__(self, row):
        self._row = row

    async def execute(self, _stmt):
        return _Result(self._row)


def _site():
    return Site(
        id=uuid.uuid4(),
        site_id="site_abc",
        user_id=uuid.uuid4(),
        name="Acme",
        url="https://acme.example",
        description="Site-level description",
    )


def _profile(enabled=True, **kw):
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        site_id="site_abc",
        enabled=enabled,
        tagline="Widgets, fast",
        long_description="We make widgets.",
        offers=[
            {
                "name": "Pro",
                "price": "49",
                "currency": "USD",
                "billing_period": "month",
                "availability": "in_stock",
                "url": "https://acme.example/pro",
            }
        ],
        capabilities=["request_demo", "get_quote"],
        primary_cta="Book a demo",
        privacy_policy_url="https://acme.example/privacy",
        tos_url=None,
        contact_email="sales@acme.example",
        created_at=now,
        updated_at=now,
    )
    defaults.update(kw)
    return AgentProfile(**defaults)


def _client(row):
    app.dependency_overrides[get_db] = lambda: FakeSession(row)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _reset():
    app.dependency_overrides.clear()


PUBLIC_PATHS = [
    "/api/v1/agent/site_abc/manifest.json",
    "/api/v1/agent/site_abc/offers.json",
    "/api/v1/agent/site_abc/llms.txt",
]


@pytest.fixture
def gateway_on(monkeypatch):
    monkeypatch.setattr(settings, "agent_gateway_enabled", True)


@pytest.fixture
def gateway_off(monkeypatch):
    monkeypatch.setattr(settings, "agent_gateway_enabled", False)


# ── AC6: both flags gate every endpoint ───────────────────────────────


@pytest.mark.parametrize("path", PUBLIC_PATHS)
async def test_404_when_global_flag_off(gateway_off, path):
    """Even for a valid, enabled site: the global flag alone closes the door."""
    try:
        async with _client((_site(), _profile(enabled=True))) as client:
            resp = await client.get(path)
        assert resp.status_code == 404
    finally:
        _reset()


@pytest.mark.parametrize("path", PUBLIC_PATHS)
async def test_404_when_site_profile_disabled(gateway_on, path):
    """Global flag on, per-site switch off => still 404."""
    try:
        async with _client((_site(), _profile(enabled=False))) as client:
            resp = await client.get(path)
        assert resp.status_code == 404
    finally:
        _reset()


async def test_default_flag_is_off():
    """agent_gateway_enabled must ship OFF — enabling is an operator action."""
    from apps.api.config import Settings

    assert Settings.model_fields["agent_gateway_enabled"].default is False


async def test_agent_profile_enabled_defaults_off():
    column = AgentProfile.__table__.c.enabled
    assert column.default.arg is False
    assert str(column.server_default.arg) == "false"


# ── AC8: unknown site => 404, never 403 ───────────────────────────────


@pytest.mark.parametrize("path", PUBLIC_PATHS)
async def test_unknown_site_returns_404_never_403(gateway_on, path):
    try:
        async with _client(None) as client:  # join matched nothing
            resp = await client.get(path)
        assert resp.status_code == 404
        assert resp.status_code != 403
    finally:
        _reset()


async def test_all_negative_cases_are_indistinguishable(gateway_on, monkeypatch):
    """Flag-off / unknown-site / disabled-profile must yield the same response,
    or the endpoint becomes a site_id existence oracle."""
    bodies = []
    try:
        # unknown site
        async with _client(None) as client:
            bodies.append((await client.get(PUBLIC_PATHS[0])).status_code)
        # disabled profile
        async with _client((_site(), _profile(enabled=False))) as client:
            bodies.append((await client.get(PUBLIC_PATHS[0])).status_code)
        # global flag off
        monkeypatch.setattr(settings, "agent_gateway_enabled", False)
        async with _client((_site(), _profile(enabled=True))) as client:
            bodies.append((await client.get(PUBLIC_PATHS[0])).status_code)
    finally:
        _reset()
    assert bodies == [404, 404, 404]


async def test_resolve_public_profile_returns_none_for_every_closed_case(
    gateway_on, monkeypatch
):
    assert await resolve_public_profile(FakeSession(None), "site_abc") is None
    assert (
        await resolve_public_profile(
            FakeSession((_site(), _profile(enabled=False))), "site_abc"
        )
        is None
    )
    monkeypatch.setattr(settings, "agent_gateway_enabled", False)
    assert (
        await resolve_public_profile(
            FakeSession((_site(), _profile(enabled=True))), "site_abc"
        )
        is None
    )


# ── AC7: flag-on content + cache headers ──────────────────────────────


async def test_manifest_content_and_cache_header(gateway_on):
    try:
        async with _client((_site(), _profile())) as client:
            resp = await client.get("/api/v1/agent/site_abc/manifest.json")
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == AGENT_CACHE_CONTROL
        body = resp.json()
        assert body["site_id"] == "site_abc"
        assert body["seller"]["name"] == "Acme"
        assert body["seller"]["description"] == "We make widgets."
        names = [c["name"] for c in body["capabilities"]]
        assert names == [
            "fyi.getbeam.agent.request_demo",
            "fyi.getbeam.agent.get_quote",
        ]
        # Phase 1+2 publish declarations only — no callable action URL yet.
        assert all(c["endpoint"] is None for c in body["capabilities"])
    finally:
        _reset()


async def test_offers_content_and_cache_header(gateway_on):
    try:
        async with _client((_site(), _profile())) as client:
            resp = await client.get("/api/v1/agent/site_abc/offers.json")
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == AGENT_CACHE_CONTROL
        body = resp.json()
        assert len(body["offers"]) == 1
        offer = body["offers"][0]
        assert offer["title"] == "Pro"
        assert offer["price"] == "49"
        assert offer["currency"] == "USD"
        assert offer["availability"] == "in_stock"
        assert offer["seller_name"] == "Acme"
    finally:
        _reset()


async def test_llms_txt_content_and_cache_header(gateway_on):
    try:
        async with _client((_site(), _profile())) as client:
            resp = await client.get("/api/v1/agent/site_abc/llms.txt")
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == AGENT_CACHE_CONTROL
        assert resp.headers["content-type"].startswith("text/plain")
        text = resp.text
        assert "# Acme" in text
        assert "Widgets, fast" in text
        assert "Pro" in text
        assert "Book a demo" in text
    finally:
        _reset()


# ── No internal/PII leakage on the public surface ─────────────────────


LEAKY_FIELDS = [
    "user_id",
    "daily_resolution_budget",
    "auto_identify_enabled",
    "hot_alert_enabled",
    "tracking_enabled",
    "consent_mode",
    "pixel_verified",
    "outcomes_webhook_secret_ciphertext",
    "last_aggregated_at",
    "detected_platform",
]


async def test_public_responses_contain_no_internal_fields(gateway_on):
    try:
        async with _client((_site(), _profile())) as client:
            for path in PUBLIC_PATHS:
                raw = (await client.get(path)).text
                for field in LEAKY_FIELDS:
                    assert field not in raw, f"{field} leaked on {path}"
                # No internal UUID primary keys either.
                assert str(_site().id) not in raw
    finally:
        _reset()


def test_builders_never_read_operational_site_columns():
    """Assembly reads only public/customer-authored fields."""
    import inspect

    from apps.api.services import agent_gateway as svc

    src = inspect.getsource(svc)
    for field in LEAKY_FIELDS:
        assert f"site.{field}" not in src, f"assembly reads site.{field}"


# ── Malformed stored data must not 500 a public read ──────────────────


async def test_malformed_offers_row_does_not_500(gateway_on):
    profile = _profile(offers=["not-a-dict", {"no_name": 1}, {"name": "Ok"}])
    try:
        async with _client((_site(), profile)) as client:
            resp = await client.get("/api/v1/agent/site_abc/offers.json")
        assert resp.status_code == 200
        assert [o["title"] for o in resp.json()["offers"]] == ["Ok"]
    finally:
        _reset()


async def test_empty_profile_renders_without_error(gateway_on):
    profile = _profile(
        tagline=None,
        long_description=None,
        offers=[],
        capabilities=[],
        primary_cta=None,
        privacy_policy_url=None,
        contact_email=None,
    )
    site = _site()
    assert build_manifest(site, profile).capabilities == []
    assert build_offers(site, profile).offers == []
    assert "# Acme" in build_llms_txt(site, profile)
