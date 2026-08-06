"""Orphan-ingest counters — how much traffic is hitting /ingest with a site_id
that does not exist (never created, or deleted).

WHAT IT COUNTS
    One increment per rejected (403) unknown-site ingest request. This is the
    signal that a live tracking snippet has been orphaned by a site delete: the
    pixel is still installed and still firing, but its id no longer resolves.

KEY SHAPE (Redis)
    beam:orphan_ingest:{YYYYMMDDHH}            -- global hourly bucket
    beam:orphan_ingest:{YYYYMMDDHH}:{site_id}  -- per-id hourly bucket
    Both INCR'd and EXPIRE'd to 7 days, so the keyspace is self-pruning and no
    cron or table is introduced. Buckets are UTC hours.

FAIL-OPEN (hard rule)
    ``record_orphan_ingest`` is called from the ingest hot path, after the 403
    Response object is fully built. It must NEVER raise: any Redis error is
    swallowed and logged at debug. A counter must not be able to turn an ingest
    403 into a 500, and must not change the response by even one byte.

OPERATOR QUERY RECIPE
    Production (Railway):
        railway run -s retarget-agent .venv/bin/python3.11 -c "\\
        import asyncio; from apps.api.services.orphan_ingest_metrics import \\
        orphan_ingest_summary; print(asyncio.run(orphan_ingest_summary(24)))"
    Or straight from redis-cli:
        redis-cli --scan --pattern 'beam:orphan_ingest:*'
    ``orphan_ingest_summary(window_hours)`` returns
        {"window_hours": n, "total": int, "by_site_id": {site_id: count}}
    A site_id with a large sustained count is almost always an orphaned pixel —
    check whether that id was recently deleted and, if so, whether the owner
    re-created the site (which now reclaims the id automatically).
"""

from datetime import datetime, timedelta, timezone

import structlog

from apps.api.services.redis_client import get_redis

logger = structlog.get_logger()

_KEY_PREFIX = "beam:orphan_ingest"
_TTL_SECONDS = 7 * 24 * 3600


def _bucket(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H")


async def record_orphan_ingest(site_id: str) -> None:
    """Count one unknown-site ingest rejection. Never raises."""
    try:
        now = datetime.now(timezone.utc)
        bucket = _bucket(now)
        redis = get_redis()
        for key in (
            f"{_KEY_PREFIX}:{bucket}",
            f"{_KEY_PREFIX}:{bucket}:{site_id}",
        ):
            await redis.incr(key)
            await redis.expire(key, _TTL_SECONDS)
    except Exception as exc:  # fail-open: telemetry must never break ingest
        logger.debug("orphan_ingest_counter_failed", error=str(exc))


async def orphan_ingest_summary(window_hours: int = 24) -> dict:
    """Sum the last `window_hours` hourly buckets.

    Returns {"window_hours": n, "total": int, "by_site_id": {id: count}}.
    Returns zeros (never raises) when Redis is unavailable.
    """
    window_hours = max(1, window_hours)
    total = 0
    by_site_id: dict[str, int] = {}
    try:
        redis = get_redis()
        now = datetime.now(timezone.utc)
        for offset in range(window_hours):
            bucket = _bucket(now - timedelta(hours=offset))
            raw_total = await redis.get(f"{_KEY_PREFIX}:{bucket}")
            if raw_total:
                total += int(raw_total)
            async for key in redis.scan_iter(match=f"{_KEY_PREFIX}:{bucket}:*"):
                key_str = key.decode() if isinstance(key, bytes) else key
                site_id = key_str.split(":", 3)[-1]
                raw = await redis.get(key_str)
                if raw:
                    by_site_id[site_id] = by_site_id.get(site_id, 0) + int(raw)
    except Exception as exc:
        logger.debug("orphan_ingest_summary_failed", error=str(exc))
        return {"window_hours": window_hours, "total": 0, "by_site_id": {}}

    return {"window_hours": window_hours, "total": total, "by_site_id": by_site_id}
