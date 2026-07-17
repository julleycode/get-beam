"""Connection-expiry nudge detector: who gets emailed, who doesn't.

Only active, non-outreach accounts whose token expires within the warn window
(or already expired) and haven't been nudged within the throttle window get an
email; the throttle timestamp is stamped so they aren't nudged again next run.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

import apps.api.main  # noqa: F401 — registers every ORM model
from apps.api.models.social_account import Platform, SocialAccount
from apps.api.models.user import User
from apps.api.services import connection_nudge

pytestmark = pytest.mark.integration


def _now():
    return datetime.now(timezone.utc)


async def _account(
    test_db, user_id, *, expires_delta, tag, outreach=False, last_alert=None, refresh_token=None
):
    acct = SocialAccount(
        id=uuid.uuid4(),
        user_id=user_id,
        platform=Platform.twitter,
        platform_user_id=f"pu-{tag}",
        username=f"acct_{tag}",
        access_token="x",
        refresh_token=refresh_token,
        token_expires_at=(_now() + expires_delta) if expires_delta is not None else None,
        is_active=True,
        outreach_connection_id="conn-1" if outreach else None,
        last_expiry_alert_sent_at=last_alert,
    )
    test_db.add(acct)
    await test_db.flush()
    return acct


async def test_nudges_only_the_right_accounts(test_db, monkeypatch):
    user = User(id=uuid.uuid4(), email=f"nudge-{uuid.uuid4().hex[:8]}@test.com")
    test_db.add(user)
    await test_db.flush()

    expiring = await _account(test_db, user.id, expires_delta=timedelta(days=2), tag="expiring")
    expired = await _account(test_db, user.id, expires_delta=timedelta(days=-1), tag="expired")
    healthy = await _account(test_db, user.id, expires_delta=timedelta(days=30), tag="healthy")
    outreach = await _account(test_db, user.id, expires_delta=timedelta(days=1), tag="outreach", outreach=True)
    # Auto-renews at send time (e.g. Twitter's 2h tokens) — never nudged.
    refreshable = await _account(
        test_db, user.id, expires_delta=timedelta(hours=1), tag="refreshable",
        refresh_token="enc-refresh",
    )
    throttled = await _account(
        test_db, user.id, expires_delta=timedelta(days=1), tag="throttled",
        last_alert=_now() - timedelta(hours=1),  # nudged 1h ago → within throttle
    )
    await test_db.commit()

    sent_to: list[str] = []

    async def _fake_send(self, **kwargs):
        sent_to.append(kwargs["to_email"])
        return {"id": "x"}

    # Patch the class method so the detector's own EmailSender() instance uses it.
    monkeypatch.setattr(
        "apps.api.services.email_sender.EmailSender.send", _fake_send
    )

    count = await connection_nudge.check_expiring_connections()

    # expiring + expired only; healthy (>7d), outreach, refreshable (auto-renews),
    # and throttled excluded.
    assert count == 2
    assert sent_to.count(user.email) == 2

    # Throttle timestamps stamped on the two nudged accounts, untouched elsewhere.
    for acct in (expiring, expired):
        await test_db.refresh(acct)
        assert acct.last_expiry_alert_sent_at is not None
    for acct in (healthy, outreach, refreshable):
        await test_db.refresh(acct)
        assert acct.last_expiry_alert_sent_at is None
