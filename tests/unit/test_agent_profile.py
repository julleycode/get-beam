"""Agent-gateway Phase 1 — authed AgentProfile CRUD (AC1, AC2, AC3, AC5).

In-process ASGI tests: the app is driven through httpx's ASGITransport with
``get_db`` and ``get_current_user`` overridden, so no PostgreSQL, Redis, or
network is touched. Unit lane.
"""

import uuid
from datetime import datetime, timezone

import pytest

# SQLAlchemy needs every model registered before any ORM object is constructed,
# and importing main is what registers them (see repo memory note).
import apps.api.main  # noqa: F401
from httpx import ASGITransport, AsyncClient

from apps.api.dependencies import get_current_user, verify_site_access
from apps.api.main import app
from apps.api.models.agent_profile import AgentProfile
from apps.api.models.database import get_db
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.schemas.sites import SiteUpdate

pytestmark = pytest.mark.unit


def _stamp(obj):
    """Populate the server_default timestamps a real flush would set."""
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)
    if getattr(obj, "created_at", None) is None:
        obj.created_at = now
    if getattr(obj, "updated_at", None) is None:
        obj.updated_at = now
    return obj


class _Result:
    """Stand-in for a SQLAlchemy Result."""

    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def first(self):
        return self._value


class FakeSession:
    """Minimal AsyncSession stand-in.

    ``responses`` is consumed in order, one entry per ``execute`` call.
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self.added = []
        self.commits = 0

    async def execute(self, _stmt):
        return _Result(self._responses.pop(0) if self._responses else None)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        # created_at/updated_at are server_default columns: a real DB populates
        # them on flush, so stand in for that here.
        _stamp(obj)


def _site(site_id="site_abc", user_id=None):
    return Site(
        id=uuid.uuid4(),
        site_id=site_id,
        user_id=user_id or uuid.uuid4(),
        name="Acme",
        url="https://acme.example",
        description="We sell widgets",
    )


def _user():
    return User(id=uuid.uuid4(), email="owner@example.com")


def _profile(site_id="site_abc", **kw):
    defaults = dict(
        id=uuid.uuid4(),
        site_id=site_id,
        enabled=False,
        tagline="Widgets, fast",
        long_description="Long form copy.",
        offers=[{"name": "Pro", "price": "49", "currency": "USD"}],
        capabilities=["request_demo"],
        primary_cta="Book a demo",
        privacy_policy_url=None,
        tos_url=None,
        contact_email=None,
    )
    defaults.update(kw)
    return _stamp(AgentProfile(**defaults))


def _client(session, user=None):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user or _user()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _reset():
    app.dependency_overrides.clear()


# ── AC2: ownership isolation — 404, never 403 ─────────────────────────


async def test_verify_site_access_raises_404_not_403_for_foreign_site():
    """The shared ownership check must never leak site existence via 403."""
    from fastapi import HTTPException

    session = FakeSession([None])  # no row matched site_id AND user_id
    with pytest.raises(HTTPException) as exc:
        await verify_site_access(session, "site_someone_elses", _user())
    assert exc.value.status_code == 404
    assert exc.value.status_code != 403


async def test_foreign_site_404_on_get():
    # First execute() = verify_site_access lookup, returns None => 404.
    session = FakeSession([None])
    try:
        async with _client(session) as client:
            resp = await client.get("/api/v1/agent-profile/site_not_yours")
        assert resp.status_code == 404
    finally:
        _reset()


async def test_foreign_site_404_on_put():
    session = FakeSession([None])
    try:
        async with _client(session) as client:
            resp = await client.put(
                "/api/v1/agent-profile/site_not_yours", json={"tagline": "x"}
            )
        assert resp.status_code == 404
    finally:
        _reset()


# ── AC1: CRUD round-trip ──────────────────────────────────────────────


async def test_get_returns_404_before_any_put():
    """E7: a bare read never auto-creates a profile row."""
    session = FakeSession([_site(), None])  # site owned, but no profile yet
    try:
        async with _client(session) as client:
            resp = await client.get("/api/v1/agent-profile/site_abc")
        assert resp.status_code == 404
        assert session.added == []
        assert session.commits == 0
    finally:
        _reset()


async def test_get_returns_profile_without_internal_fields():
    session = FakeSession([_site(), _profile()])
    try:
        async with _client(session) as client:
            resp = await client.get("/api/v1/agent-profile/site_abc")
        assert resp.status_code == 200
        body = resp.json()
        assert body["site_id"] == "site_abc"
        assert body["tagline"] == "Widgets, fast"
        assert body["enabled"] is False
        # Never expose internal identifiers on any agent-profile response.
        for leak in ("id", "user_id"):
            assert leak not in body
    finally:
        _reset()


async def test_put_creates_profile_on_first_write():
    session = FakeSession([_site(), None])
    try:
        async with _client(session) as client:
            resp = await client.put(
                "/api/v1/agent-profile/site_abc",
                json={
                    "tagline": "Widgets, fast",
                    "capabilities": ["request_demo", "get_quote"],
                    "offers": [{"name": "Pro", "price": "49", "currency": "USD"}],
                },
            )
        assert resp.status_code == 200
        assert len(session.added) == 1
        created = session.added[0]
        assert created.site_id == "site_abc"
        assert created.tagline == "Widgets, fast"
        assert created.capabilities == ["request_demo", "get_quote"]
        assert created.offers[0]["name"] == "Pro"
        # Default-OFF is preserved: an upsert that doesn't set `enabled`
        # must not silently publish the site's content.
        assert created.enabled is False
    finally:
        _reset()


async def test_put_patches_existing_profile():
    existing = _profile()
    session = FakeSession([_site(), existing])
    try:
        async with _client(session) as client:
            resp = await client.put(
                "/api/v1/agent-profile/site_abc", json={"tagline": "New tagline"}
            )
        assert resp.status_code == 200
        assert session.added == []  # patched, not re-created
        assert existing.tagline == "New tagline"
        assert existing.long_description == "Long form copy."  # untouched
    finally:
        _reset()


async def test_put_rejects_unknown_capability():
    session = FakeSession([_site(), None])
    try:
        async with _client(session) as client:
            resp = await client.put(
                "/api/v1/agent-profile/site_abc",
                json={"capabilities": ["exfiltrate_emails"]},
            )
        assert resp.status_code == 422
        assert session.added == []
    finally:
        _reset()


# ── AC3: SiteUpdate latent-bug fix ────────────────────────────────────


def test_site_update_accepts_description_and_category():
    """Both columns exist on Site and are settable at create time; SiteUpdate
    previously could not edit either, making them write-once."""
    body = SiteUpdate(description="We sell widgets", category="saas")
    assert body.description == "We sell widgets"
    assert body.category == "saas"


def test_site_update_fields_stay_optional():
    """Additive change: an existing caller sending only a toggle is unaffected."""
    body = SiteUpdate(auto_identify_enabled=True)
    assert body.description is None
    assert body.category is None
    assert body.model_dump(exclude_unset=True) == {"auto_identify_enabled": True}


def test_site_update_applies_description_in_router():
    """The schema change is useless if the router ignores it — assert the wiring
    exists rather than trusting the schema alone."""
    import inspect

    from apps.api.routers import sites as sites_router

    src = inspect.getsource(sites_router)
    assert "site.description = body.description" in src
    assert "site.category = body.category" in src


# ── AC5: no public route introduced in Phase 1 ────────────────────────


def test_every_agent_profile_route_is_ownership_checked():
    import inspect

    from apps.api.routers import agent_profile as profile_router

    src = inspect.getsource(profile_router)
    # One verify_site_access call per route handler (GET + PUT), plus the import.
    assert src.count("await verify_site_access(") == 2
    assert "get_current_user" in src


def test_agent_profile_routes_require_auth():
    """Every /api/v1/agent-profile route depends on get_current_user."""
    paths = [
        route
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v1/agent-profile")
    ]
    assert paths, "agent-profile router is not mounted"
    for route in paths:
        names = {d.call.__name__ for d in route.dependant.dependencies}
        assert "get_current_user" in names, f"{route.path} is unauthenticated"
