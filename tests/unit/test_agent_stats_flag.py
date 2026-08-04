"""Agent stats flag-awareness — GET /{site_id}/stats carries detection_enabled.

In-process ASGI test: the app is driven through httpx's ASGITransport with
``get_db`` and ``get_current_user`` overridden, so no PostgreSQL, Redis, or
network is touched. Unit lane. Auth-override pattern mirrors
``tests/unit/test_agent_profile.py``.
"""

import uuid

import pytest

# SQLAlchemy needs every model registered before any ORM object is constructed,
# and importing main is what registers them (see repo memory note).
import apps.api.main  # noqa: F401
from httpx import ASGITransport, AsyncClient

from apps.api.dependencies import get_current_user
from apps.api.main import app
from apps.api.models.database import get_db
from apps.api.models.user import User
from apps.api.routers import agents as agents_router

pytestmark = pytest.mark.unit

SITE_ID = "site_abc"


class _ScalarResult:
    """Stand-in for the total-visits query result."""

    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value


class FakeSession:
    """Minimal AsyncSession stand-in; ``responses`` consumed in call order."""

    def __init__(self, responses):
        self._responses = list(responses)

    async def execute(self, _stmt):
        return self._responses.pop(0)


def _client(session):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="owner@example.com"
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _get_stats(monkeypatch, flag: bool) -> dict:
    monkeypatch.setattr(agents_router.settings, "agent_detection_enabled", flag)

    async def _no_op_verify(_db, _site_id, _user):
        return None

    monkeypatch.setattr(agents_router, "_verify_site_access", _no_op_verify)

    # Call order in get_agent_stats: total-visits scalar, then by-vendor rows.
    session = FakeSession([_ScalarResult(0), iter([])])
    try:
        async with _client(session) as client:
            resp = await client.get(f"/api/v1/agents/{SITE_ID}/stats")
        assert resp.status_code == 200, resp.text
        return resp.json()
    finally:
        app.dependency_overrides.clear()


async def test_detection_enabled_true_reflects_settings(monkeypatch):
    body = await _get_stats(monkeypatch, True)
    assert body["detection_enabled"] is True


async def test_detection_enabled_false_reflects_settings(monkeypatch):
    body = await _get_stats(monkeypatch, False)
    assert body["detection_enabled"] is False
