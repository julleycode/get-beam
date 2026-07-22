"""Slot-release for the per-site hourly email rate limiter (double-send fix).

A reserved slot must be handed back when the send it was reserved for did not
happen (send failed, or the recipient lost the idempotency race), otherwise
every failure permanently burns an hourly slot and the cap ratchets down.
"""

import fakeredis.aioredis
import pytest

from apps.api.services import email_rate_limiter as rl


@pytest.fixture
def fake_redis(monkeypatch):
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(rl, "get_redis", lambda: r)
    return r


async def test_release_returns_a_slot(fake_redis, monkeypatch):
    monkeypatch.setattr(rl.settings, "max_emails_per_hour_per_site", 2)
    site = "site_release"

    assert await rl.check_and_reserve_email(site) is True   # 1/2
    assert await rl.check_and_reserve_email(site) is True   # 2/2
    assert await rl.check_and_reserve_email(site) is False  # cap reached

    await rl.release_email_reservation(site)                # hand one back
    assert await rl.check_and_reserve_email(site) is True   # slot freed


async def test_release_never_goes_negative(fake_redis, monkeypatch):
    monkeypatch.setattr(rl.settings, "max_emails_per_hour_per_site", 5)
    site = "site_clamp"

    # Releasing with no prior reservation must not leave a negative counter that
    # would let sends exceed the cap later.
    await rl.release_email_reservation(site)
    await rl.release_email_reservation(site)

    assert await rl.check_and_reserve_email(site) is True  # counter sane, reserve works
