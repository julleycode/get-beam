"""Per-site hourly cap on ad-audience push operations.

Structural mirror of services/crm_rate_limiter.py: Redis-backed so the cap
holds across workers/replicas, and fails OPEN (allows the push) if Redis is
unreachable. Counter is INDEPENDENT of the CRM limiter — a site's ad pushes
and CRM pushes do not share one budget. The limit is
``settings.max_ads_pushes_per_hour_per_site`` push operations (one push of a
whole segment counts as one), not per-contact.
"""

from datetime import datetime, timezone

import structlog

from apps.api.config import settings
from apps.api.services.redis_client import get_redis

logger = structlog.get_logger()


async def check_and_reserve_push(site_id: str) -> bool:
    """Reserve one ad push for ``site_id`` in the current clock hour.

    Returns True (and reserves a slot) when within the hourly cap, False when
    the cap is already reached. Fails open (returns True) on any Redis error.
    """
    cap = settings.max_ads_pushes_per_hour_per_site
    try:
        redis = get_redis()
        hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        key = f"ads_push_rate:{site_id}:{hour}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 3600)
        if count > cap:
            await redis.decr(key)  # undo so the counter reflects only permitted pushes
            return False
        return True
    except Exception as exc:
        logger.warning("ads_push_rate_limiter_failed_open", site_id=site_id, error=str(exc))
        return True
