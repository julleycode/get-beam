"""Draft rejection_reason: distinguish user-rejected from auto-rejected siblings.

When a user approves one draft, the other pending drafts for the SAME post are
auto-rejected — they must be tagged `auto_rejected_sibling` (so the UI relabels
them "Not used"), and only drafts for that post, not unrelated ones.
"""

import uuid
from datetime import datetime, timezone

import pytest

import apps.api.main  # noqa: F401 — registers every ORM model
from apps.api.models.draft import Draft, DraftStatus, DraftType
from apps.api.models.post import Post
from apps.api.models.social_account import Platform, SocialAccount
from apps.api.models.user import User
from apps.api.routers.drafts import (
    REJECTION_AUTO_SIBLING,
    _auto_reject_siblings,
)

pytestmark = pytest.mark.integration


def _now():
    return datetime.now(timezone.utc)


async def _seed_post(test_db, user_id, *, tag: str) -> Post:
    account = SocialAccount(
        id=uuid.uuid4(),
        user_id=user_id,
        platform=Platform.twitter,
        platform_user_id=f"pu-{tag}",
        username="acct",
        access_token="x",
    )
    test_db.add(account)
    await test_db.flush()
    post = Post(
        id=uuid.uuid4(),
        social_account_id=account.id,
        platform=Platform.twitter,
        platform_post_id=f"tw-{tag}",
        author_name="A",
        author_username="a",
        content="c",
        posted_at=_now(),
    )
    test_db.add(post)
    await test_db.flush()
    return post


def _draft(user_id, post_id, status=DraftStatus.pending) -> Draft:
    return Draft(
        id=uuid.uuid4(),
        user_id=user_id,
        type=DraftType.comment,
        post_id=post_id,
        platform=Platform.twitter,
        ai_content="reply",
        status=status,
    )


async def test_auto_reject_tags_siblings_only(test_db):
    user = User(id=uuid.uuid4(), email=f"rej-{uuid.uuid4().hex[:8]}@test.com")
    test_db.add(user)
    await test_db.flush()

    post = await _seed_post(test_db, user.id, tag="main")
    other_post = await _seed_post(test_db, user.id, tag="other")

    approved = _draft(user.id, post.id, status=DraftStatus.approved)
    sib1 = _draft(user.id, post.id)
    sib2 = _draft(user.id, post.id)
    unrelated = _draft(user.id, other_post.id)  # different post — must be untouched
    test_db.add_all([approved, sib1, sib2, unrelated])
    await test_db.commit()

    await _auto_reject_siblings(test_db, approved)

    for s in (sib1, sib2):
        await test_db.refresh(s)
        assert s.status == DraftStatus.rejected
        assert s.rejection_reason == REJECTION_AUTO_SIBLING

    await test_db.refresh(unrelated)
    assert unrelated.status == DraftStatus.pending
    assert unrelated.rejection_reason is None

    await test_db.refresh(approved)
    assert approved.status == DraftStatus.approved  # the approved one is left alone
