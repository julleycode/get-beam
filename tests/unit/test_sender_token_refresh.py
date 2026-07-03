"""Token-refresh hardening for draft sending (2026-07-03 incident).

Covers:
- Expired token that cannot be refreshed raises SocialTokenExpiredError instead
  of silently sending a dead token (which 401s and records a vague `failed`).
- Successful refresh persists the ROTATED refresh token (single-use rotation).
- Null-expiry ("unknown") tokens do NOT hard-fail — they fall back gracefully.
- send_draft marks the draft `failed` and re-raises so the caller can show a
  "reconnect" message.

Requires PostgreSQL (conftest test_db uses settings.database_url).
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import apps.api.main  # noqa: F401 — registers every ORM model
from apps.api.models.draft import Draft, DraftStatus, DraftType
from apps.api.models.post import Post
from apps.api.models.social_account import Platform, SocialAccount
from apps.api.models.user import User
from apps.api.services import sender as sender_mod
from apps.api.services.encryption import decrypt_token, encrypt_token
from apps.api.services.platforms.base import OAuthTokens
from apps.api.services.sender import (
    SocialTokenExpiredError,
    _friendly_send_error,
    _refresh_if_expired,
    send_draft,
)

pytestmark = pytest.mark.asyncio


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _make_account(
    test_db,
    *,
    expires_at,
    refresh_token: str | None = "refresh-old",
    access_token: str = "access-old",
) -> SocialAccount:
    user = User(id=uuid.uuid4(), email=f"sender-{uuid.uuid4().hex[:8]}@test.com")
    test_db.add(user)
    await test_db.flush()

    account = SocialAccount(
        id=uuid.uuid4(),
        user_id=user.id,
        platform=Platform.twitter,
        platform_user_id="123",
        username="julleybuilds",
        access_token=encrypt_token(access_token),
        refresh_token=encrypt_token(refresh_token) if refresh_token else None,
        token_expires_at=expires_at,
        is_active=True,
    )
    test_db.add(account)
    await test_db.commit()
    return account


class _FakeService:
    """Stand-in for a PlatformService with controllable refresh/post behavior."""

    def __init__(self, *, refresh=None, refresh_exc=None, comment_id="c1", post_exc=None):
        self._refresh = refresh
        self._refresh_exc = refresh_exc
        self._comment_id = comment_id
        self._post_exc = post_exc
        self.refresh_called = 0

    async def refresh_tokens(self, refresh_token: str) -> OAuthTokens:
        self.refresh_called += 1
        if self._refresh_exc:
            raise self._refresh_exc
        return self._refresh

    async def post_comment(self, access_token, platform_post_id, text) -> str:
        if self._post_exc:
            raise self._post_exc
        return self._comment_id


def _patch_service(monkeypatch, service: _FakeService) -> None:
    monkeypatch.setattr(sender_mod, "get_platform_service", lambda platform: service)


async def test_valid_token_is_not_refreshed(test_db, monkeypatch):
    account = await _make_account(test_db, expires_at=_now() + timedelta(hours=1))
    svc = _FakeService(refresh_exc=AssertionError("must not refresh a valid token"))
    _patch_service(monkeypatch, svc)

    token = await _refresh_if_expired(test_db, account)

    assert token == "access-old"
    assert svc.refresh_called == 0


async def test_expired_without_refresh_token_raises(test_db, monkeypatch):
    account = await _make_account(
        test_db, expires_at=_now() - timedelta(minutes=1), refresh_token=None
    )
    _patch_service(monkeypatch, _FakeService())

    with pytest.raises(SocialTokenExpiredError) as exc:
        await _refresh_if_expired(test_db, account)
    assert exc.value.username == "julleybuilds"
    assert "reconnect" in str(exc.value).lower()


async def test_expired_refresh_failure_raises(test_db, monkeypatch):
    account = await _make_account(test_db, expires_at=_now() - timedelta(minutes=1))
    svc = _FakeService(refresh_exc=RuntimeError("400 invalid_grant"))
    _patch_service(monkeypatch, svc)

    with pytest.raises(SocialTokenExpiredError):
        await _refresh_if_expired(test_db, account)
    assert svc.refresh_called == 1


async def test_successful_refresh_persists_rotated_tokens(test_db, monkeypatch):
    account = await _make_account(test_db, expires_at=_now() - timedelta(minutes=1))
    new_expiry = _now() + timedelta(hours=2)
    svc = _FakeService(
        refresh=OAuthTokens(
            access_token="access-NEW",
            refresh_token="refresh-NEW",
            expires_at=new_expiry,
        )
    )
    _patch_service(monkeypatch, svc)

    token = await _refresh_if_expired(test_db, account)

    assert token == "access-NEW"
    await test_db.refresh(account)
    assert decrypt_token(account.access_token) == "access-NEW"
    # Rotated (single-use) refresh token must be persisted, not the old one.
    assert decrypt_token(account.refresh_token) == "refresh-NEW"
    assert account.token_expires_at == new_expiry


async def test_unknown_expiry_refresh_failure_falls_back(test_db, monkeypatch):
    # Null expiry = "unknown" — a failed refresh must NOT hard-fail; the existing
    # (possibly still-valid) token is returned so undated accounts keep working.
    account = await _make_account(test_db, expires_at=None)
    svc = _FakeService(refresh_exc=RuntimeError("network blip"))
    _patch_service(monkeypatch, svc)

    token = await _refresh_if_expired(test_db, account)

    assert token == "access-old"
    assert svc.refresh_called == 1


async def test_send_draft_marks_failed_and_raises_on_expiry(test_db, monkeypatch):
    account = await _make_account(
        test_db, expires_at=_now() - timedelta(minutes=1), refresh_token=None
    )
    post = Post(
        id=uuid.uuid4(),
        social_account_id=account.id,
        platform=Platform.twitter,
        platform_post_id="tweet-1",
        author_name="Weave Robotics",
        author_username="weaverobotics",
        content="original",
        posted_at=_now(),
    )
    test_db.add(post)
    draft = Draft(
        id=uuid.uuid4(),
        user_id=account.user_id,
        type=DraftType.comment,
        post_id=post.id,
        platform=Platform.twitter,
        ai_content="my reply",
        status=DraftStatus.approved,
    )
    test_db.add(draft)
    await test_db.commit()

    _patch_service(monkeypatch, _FakeService())

    with pytest.raises(SocialTokenExpiredError):
        await send_draft(test_db, draft)

    await test_db.refresh(draft)
    assert draft.status == DraftStatus.failed
    # The failed draft carries the actionable reason for the UI.
    assert draft.failure_reason and "reconnect" in draft.failure_reason.lower()


async def test_concurrent_sends_same_account_refresh_only_once(test_engine, monkeypatch):
    """Two drafts on the SAME expired account, sent concurrently, must trigger
    exactly ONE token refresh — the FOR UPDATE row lock + re-read serializes
    them so the single-use refresh token is never consumed twice.
    """
    Session = async_sessionmaker(test_engine, expire_on_commit=False)

    # Seed one expired account + two approved drafts (each on its own post).
    async with Session() as seed:
        account = await _make_account(seed, expires_at=_now() - timedelta(minutes=1))
        draft_ids = []
        for i in range(2):
            post = Post(
                id=uuid.uuid4(),
                social_account_id=account.id,
                platform=Platform.twitter,
                platform_post_id=f"tweet-{i}",
                author_name="Author",
                author_username=f"author{i}",
                content="original",
                posted_at=_now(),
            )
            seed.add(post)
            draft = Draft(
                id=uuid.uuid4(),
                user_id=account.user_id,
                type=DraftType.comment,
                post_id=post.id,
                platform=Platform.twitter,
                ai_content=f"reply {i}",
                status=DraftStatus.approved,
            )
            seed.add(draft)
            draft_ids.append(draft.id)
        await seed.commit()
        account_id = account.id

    # Shared fake service: refresh sleeps while holding the lock so the second
    # send is guaranteed to block on its FOR UPDATE read; it returns a rotated
    # token with a FUTURE expiry so the unblocked send skips re-refreshing.
    svc = _FakeService(
        refresh=OAuthTokens(
            access_token="access-NEW",
            refresh_token="refresh-NEW",
            expires_at=_now() + timedelta(hours=2),
        )
    )
    orig_refresh = svc.refresh_tokens

    async def slow_refresh(refresh_token):
        await asyncio.sleep(0.2)
        return await orig_refresh(refresh_token)

    svc.refresh_tokens = slow_refresh
    _patch_service(monkeypatch, svc)

    async def _send(draft_id):
        async with Session() as s:
            draft = await s.get(Draft, draft_id)
            return await send_draft(s, draft)

    results = await asyncio.gather(*[_send(d) for d in draft_ids])

    assert all(results), "both drafts should send"
    assert svc.refresh_called == 1, (
        f"expected exactly 1 refresh, got {svc.refresh_called} — FOR UPDATE "
        "serialization failed and the single-use refresh token was consumed twice"
    )

    async with Session() as check:
        acct = await check.get(SocialAccount, account_id)
        assert decrypt_token(acct.access_token) == "access-NEW"
        assert decrypt_token(acct.refresh_token) == "refresh-NEW"


async def test_send_draft_success_posts_and_marks_sent(test_db, monkeypatch):
    account = await _make_account(test_db, expires_at=_now() + timedelta(hours=1))
    post = Post(
        id=uuid.uuid4(),
        social_account_id=account.id,
        platform=Platform.twitter,
        platform_post_id="tweet-2",
        author_name="REK",
        author_username="rek",
        content="original",
        posted_at=_now(),
    )
    test_db.add(post)
    draft = Draft(
        id=uuid.uuid4(),
        user_id=account.user_id,
        type=DraftType.comment,
        post_id=post.id,
        platform=Platform.twitter,
        ai_content="nice build",
        status=DraftStatus.approved,
    )
    test_db.add(draft)
    await test_db.commit()

    _patch_service(monkeypatch, _FakeService(comment_id="posted-123"))

    ok = await send_draft(test_db, draft)

    assert ok is True
    await test_db.refresh(draft)
    assert draft.status == DraftStatus.sent
    assert draft.sent_at is not None


async def test_friendly_send_error_classifies():
    assert "restrict" in _friendly_send_error("HTTP 403: Forbidden", "twitter").lower()
    assert "reconnect" in _friendly_send_error("HTTP 401: Unauthorized", "twitter").lower()
    assert "busy" in _friendly_send_error("HTTP 429: Too Many Requests", "twitter").lower()
    assert "busy" in _friendly_send_error("Read timed out", "twitter").lower()
    # Unknown → generic, still names the platform.
    assert "linkedin" in _friendly_send_error("some odd error", "linkedin").lower()


async def test_send_failure_sets_friendly_reason(test_db, monkeypatch):
    account = await _make_account(test_db, expires_at=_now() + timedelta(hours=1))
    post = Post(
        id=uuid.uuid4(),
        social_account_id=account.id,
        platform=Platform.twitter,
        platform_post_id="tweet-3",
        author_name="A",
        author_username="a",
        content="original",
        posted_at=_now(),
    )
    test_db.add(post)
    draft = Draft(
        id=uuid.uuid4(),
        user_id=account.user_id,
        type=DraftType.comment,
        post_id=post.id,
        platform=Platform.twitter,
        ai_content="reply",
        status=DraftStatus.approved,
    )
    test_db.add(draft)
    await test_db.commit()

    # post_comment raises a 403-ish error → friendly reply-forbidden reason.
    _patch_service(
        monkeypatch, _FakeService(post_exc=RuntimeError("HTTP 403: Forbidden"))
    )

    ok = await send_draft(test_db, draft)

    assert ok is False
    await test_db.refresh(draft)
    assert draft.status == DraftStatus.failed
    assert draft.failure_reason and "restrict" in draft.failure_reason.lower()


async def test_successful_send_clears_prior_failure_reason(test_db, monkeypatch):
    account = await _make_account(test_db, expires_at=_now() + timedelta(hours=1))
    post = Post(
        id=uuid.uuid4(),
        social_account_id=account.id,
        platform=Platform.twitter,
        platform_post_id="tweet-4",
        author_name="A",
        author_username="a",
        content="original",
        posted_at=_now(),
    )
    test_db.add(post)
    draft = Draft(
        id=uuid.uuid4(),
        user_id=account.user_id,
        type=DraftType.comment,
        post_id=post.id,
        platform=Platform.twitter,
        ai_content="reply",
        status=DraftStatus.approved,
        failure_reason="an old failure from a previous attempt",
    )
    test_db.add(draft)
    await test_db.commit()

    _patch_service(monkeypatch, _FakeService(comment_id="ok"))

    ok = await send_draft(test_db, draft)

    assert ok is True
    await test_db.refresh(draft)
    assert draft.status == DraftStatus.sent
    assert draft.failure_reason is None
