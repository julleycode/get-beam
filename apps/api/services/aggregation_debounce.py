"""Cross-container coordination keys for visitor aggregation.

Capacity-hardening plan Phase 3 (W1), decision D3 + instructions E16/E17.

Three key namespaces, all in Redis so they are shared across containers (the
previous in-memory `_aggregating` set in `routers/events.py` deduplicated only
within one process, so N containers ran N concurrent aggregations of one site):

* ``agg:debounce:{site_id}``      — per-site run lock / min-interval debounce.
* ``agg:sweep_pending:{site_id}`` — the repair sweep's YIELD MARKER (E16). While
  it is set, per-ingest triggers stand down so the sweep can win the debounce key
  within one TTL. Without it a continuously-ingesting site re-takes the debounce
  key the instant it expires and the sweep is starved forever — on exactly the
  hot sites the 60-minute freshness contract exists for.
* ``agg:resolve:{site_id}``       — single-flight for company resolution, so a
  dispatched resolution can never race a second one (``_upsert_company`` merges
  with unconditional ``+ 1`` increments, which would inflate company counters).

Every helper degrades explicitly rather than raising: a Redis failure returns
``None`` ("unknown"), and each caller decides its own fail direction. The
directions are NOT the same — see E17: the per-ingest path fails OPEN (never fail
the 204), the repair sweep fails CLOSED when the incremental flag is on.
"""

import structlog

logger = structlog.get_logger()

DEBOUNCE_KEY = "agg:debounce:{site_id}"
SWEEP_PENDING_KEY = "agg:sweep_pending:{site_id}"
RESOLVE_LOCK_KEY = "agg:resolve:{site_id}"

# The yield marker outlives one debounce TTL by a wide margin so a single
# unlucky expiry race cannot drop it while the sweep is still waiting.
SWEEP_PENDING_TTL_MULTIPLIER = 3


async def try_acquire(key: str, ttl_seconds: int) -> bool | None:
    """``SET NX EX`` — True acquired, False already held, None Redis degraded."""
    try:
        from apps.api.services.redis_client import get_redis

        acquired = await get_redis().set(key, "1", nx=True, ex=max(ttl_seconds, 1))
        return bool(acquired)
    except Exception as exc:
        logger.warning("aggregation_redis_unavailable", key=key, error=str(exc))
        return None


async def release(key: str) -> None:
    """Best-effort delete. A failure is harmless — the TTL still expires."""
    try:
        from apps.api.services.redis_client import get_redis

        await get_redis().delete(key)
    except Exception as exc:
        logger.warning("aggregation_redis_release_failed", key=key, error=str(exc))


async def exists(key: str) -> bool | None:
    """True/False, or None when Redis is degraded."""
    try:
        from apps.api.services.redis_client import get_redis

        return bool(await get_redis().exists(key))
    except Exception as exc:
        logger.warning("aggregation_redis_unavailable", key=key, error=str(exc))
        return None


def debounce_key(site_id: str) -> str:
    return DEBOUNCE_KEY.format(site_id=site_id)


def sweep_pending_key(site_id: str) -> str:
    return SWEEP_PENDING_KEY.format(site_id=site_id)


def resolve_lock_key(site_id: str) -> str:
    return RESOLVE_LOCK_KEY.format(site_id=site_id)
