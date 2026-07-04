"""Invite gate toggle — verifies the INVITE_ONLY behavior in get_current_user.

Exercises the exact branch changed when the private beta ended: a brand-new
Clerk user whose email is NOT on the waitlist.

  - invite_only=False (default, open) -> account is created, no block.
  - invite_only=True                  -> 403 invite-only.

No DB/network: the Clerk verify, email fetch, welcome email, and the DB
session are mocked, so this isolates the gate decision itself.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import apps.api.dependencies as deps
import apps.api.main  # noqa: F401 — registers every ORM model so User() can map


def _mock_db_new_user() -> MagicMock:
    """A DB session that reports 'no existing user' for every lookup."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


def _patch_clerk(monkeypatch, *, invite_only: bool, allowlisted: bool) -> None:
    monkeypatch.setattr(deps.settings, "clerk_secret_key", "sk_test_selfcheck")
    monkeypatch.setattr(deps.settings, "invite_only", invite_only)
    monkeypatch.setattr(
        deps, "_verify_clerk_token", AsyncMock(return_value={"sub": "user_selfcheck_new"})
    )
    monkeypatch.setattr(
        deps,
        "_fetch_clerk_profile",
        AsyncMock(
            return_value={
                "email": "selfcheck-newacct@example.com",
                "avatar_url": "https://img.clerk.com/selfcheck",
                "full_name": "Self Check",
            }
        ),
    )
    monkeypatch.setattr(deps, "_send_welcome_email", AsyncMock())
    monkeypatch.setattr(deps, "_is_email_allowlisted", AsyncMock(return_value=allowlisted))


_CREDS = HTTPAuthorizationCredentials(scheme="Bearer", credentials="fake.clerk.jwt")


@pytest.mark.asyncio
async def test_open_signup_creates_new_account(monkeypatch):
    """invite_only=False: a non-allowlisted new user gets an account, not a 403."""
    _patch_clerk(monkeypatch, invite_only=False, allowlisted=False)
    db = _mock_db_new_user()

    user = await deps.get_current_user(creds=_CREDS, db=db)

    assert user.email == "selfcheck-newacct@example.com"
    assert user.clerk_user_id == "user_selfcheck_new"
    db.add.assert_called_once()  # row was created
    deps._send_welcome_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_invite_only_blocks_non_allowlisted(monkeypatch):
    """invite_only=True: the old gate still 403s a non-allowlisted new user."""
    _patch_clerk(monkeypatch, invite_only=True, allowlisted=False)
    db = _mock_db_new_user()

    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user(creds=_CREDS, db=db)

    assert exc.value.status_code == 403
    db.add.assert_not_called()  # no account created
