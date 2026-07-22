"""Per-site hourly email send cap (CAN-SPAM / deliverability guardrail).

Backed by Redis so the cap holds across workers/replicas. Fails OPEN (allows
the send) if Redis is unreachable — beta volume is low and blocking all email on
a Redis blip is worse than briefly exceeding the cap. The limit is
``settings.max_emails_per_hour_per_site``.
"""

from datetime import datetime, timezone

import structlog

from apps.api.config import settings
from apps.api.services.redis_client import get_redis

logger = structlog.get_logger()


async def check_and_reserve_email(site_id: str) -> bool:
    """Reserve one email send for ``site_id`` in the current clock hour.

    Returns True (and reserves a slot) when within the hourly cap, False when the
    cap is already reached. Fails open (returns True) on any Redis error.
    """
    cap = settings.max_emails_per_hour_per_site
    try:
        redis = get_redis()
        hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        key = f"email_rate:{site_id}:{hour}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 3600)
        if count > cap:
            # Undo the reservation so the counter reflects only permitted sends.
            await redis.decr(key)
            return False
        return True
    except Exception as exc:
        logger.warning("email_rate_limiter_failed_open", site_id=site_id, error=str(exc))
        return True


async def release_email_reservation(site_id: str) -> None:
    """Give back a slot reserved by ``check_and_reserve_email`` when the send it
    was reserved for did not happen — the send failed, or the recipient lost the
    idempotency race and was skipped. Without this, every failed/skipped send
    permanently burns an hourly slot. Best-effort: a lost decrement only
    over-counts slightly, and the counter is clamped so it never goes negative."""
    try:
        redis = get_redis()
        hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        key = f"email_rate:{site_id}:{hour}"
        remaining = await redis.decr(key)
        if remaining < 0:
            # decr on an expired/absent key creates it at -1; drop it.
            await redis.delete(key)
    except Exception as exc:
        logger.warning("email_rate_limiter_release_failed", site_id=site_id, error=str(exc))
