"""Phase 6: legacy /auth/signup must be disabled in production.

The legacy email/password signup bypassed the invite gate and created accounts
orphaned from Clerk. It stays available in dev/test (used by integration
fixtures) but must hard-404 when app_env == production.
"""

import pytest
from fastapi import HTTPException

from apps.api.config import settings
from apps.api.routers import auth as auth_router
from apps.api.schemas.auth import UserCreate


async def test_signup_404_in_production(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    # Gate raises BEFORE touching the db, so db=None is never dereferenced.
    with pytest.raises(HTTPException) as exc:
        await auth_router.signup(
            UserCreate(email="x@example.com", password="password123", full_name="X"),
            db=None,
        )
    assert exc.value.status_code == 404


async def test_signup_passes_gate_outside_production(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    # Past the gate it reaches the db path; with db=None that fails with an
    # AttributeError — NOT the 404 gate. Proves the gate is dev/test-permissive.
    with pytest.raises(Exception) as exc:
        await auth_router.signup(
            UserCreate(email="y@example.com", password="password123", full_name="Y"),
            db=None,
        )
    assert not (isinstance(exc.value, HTTPException) and exc.value.status_code == 404)
