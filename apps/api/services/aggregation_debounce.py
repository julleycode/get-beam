"""Cross-container coordination keys for visitor aggregation.

Capacity-hardening plan Phase 3 (W1), decision D3 + instructions E16/E17.
Phase 1 scale-ready (F8): the debounce key is a mutex held until ``release``
in ``finally``, not a fire-and-forget 60s cooldown. A lock token means only
the holder can delete or convert the key to leftover cooldown; a refresh loop
extends TTL so a full recompute longer than the cooldown cannot lose the lock.

Three key namespaces, all in Redis so they are shared across containers (the
previous in-memory `_aggregating` set in `routers/events.py` deduplicated only
within one process, so N containers ran N concurrent aggregations of one site):

* ``agg:debounce:{site_id}``      — per-site run mutex / leftover cooldown.
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
the 204) when the incremental flag is off, and SKIPS aggregation when the flag
is on (F7). The repair sweep fails CLOSED when the incremental flag is on.
"""

from __future__ import annotations

import asyncio
import math
import secrets
import time

import structlog

logger = structlog.get_logger()

DEBOUNCE_KEY = "agg:debounce:{site_id}"
SWEEP_PENDING_KEY = "agg:sweep_pending:{site_id}"
RESOLVE_LOCK_KEY = "agg:resolve:{site_id}"

# The yield marker outlives one debounce TTL by a wide margin so a single
# unlucky expiry race cannot drop it while the sweep is still waiting.
SWEEP_PENDING_TTL_MULTIPLIER = 3

# Lua: only the holder may delete, or convert the mutex into leftover cooldown
# (value "1") so sequential triggers inside aggregation_min_interval_seconds
# stay debounced after the run ends — matching the flag-OFF contract.
_RELEASE_LUA = """
local current = redis.call('get', KEYS[1])
if current ~= ARGV[1] then
  return 0
end
local cd = tonumber(ARGV[2])
if cd ~= nil and cd > 0 then
  redis.call('set', KEYS[1], '1', 'EX', cd)
  return 1
end
return redis.call('del', KEYS[1])
"""

_EXTEND_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], tonumber(ARGV[2]))
end
return 0
"""


async def try_acquire(key: str, ttl_seconds: int, token: str = "1") -> bool | None:
    """``SET NX EX`` — True acquired, False already held, None Redis degraded.

    ``token`` is stored as the value so ``release`` / ``extend`` can prove
    ownership. Yield markers keep the default ``"1"``.
    """
    try:
        from apps.api.services.redis_client import get_redis

        acquired = await get_redis().set(
            key, token, nx=True, ex=max(ttl_seconds, 1)
        )
        return bool(acquired)
    except Exception as exc:
        logger.warning("aggregation_redis_unavailable", key=key, error=str(exc))
        return None


async def extend(key: str, token: str, ttl_seconds: int) -> bool | None:
    """Refresh TTL only if ``token`` still owns the key. None if Redis is down."""
    try:
        from apps.api.services.redis_client import get_redis

        result = await get_redis().eval(
            _EXTEND_LUA, 1, key, token, max(int(ttl_seconds), 1)
        )
        return bool(result)
    except Exception as exc:
        logger.warning("aggregation_redis_extend_failed", key=key, error=str(exc))
        return None


async def release(
    key: str,
    token: str | None = None,
    *,
    cooldown_seconds: int = 0,
) -> None:
    """Best-effort delete (or leftover-cooldown SET) of ``key``.

    Without a token this is a plain DELETE (yield markers). With a token only
    the holder can mutate the key; ``cooldown_seconds > 0`` converts the mutex
    into the remaining min-interval cooldown so flag-OFF debounce tests still
    pass. A failure is harmless — the TTL still expires.
    """
    try:
        from apps.api.services.redis_client import get_redis

        redis = get_redis()
        if token:
            await redis.eval(
                _RELEASE_LUA, 1, key, token, max(int(cooldown_seconds), 0)
            )
        else:
            await redis.delete(key)
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


async def _refresh_loop(
    key: str,
    token: str,
    ttl_seconds: int,
    stop: asyncio.Event,
) -> None:
    interval = max(ttl_seconds / 2, 0.25)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            await extend(key, token, ttl_seconds)
        except asyncio.CancelledError:
            raise


class RunLock:
    """Per-site debounce mutex held until ``release``, then leftover cooldown.

    Ingest ``_background_aggregate`` and sweep ``_sweep_one_site`` share
    ``debounce_key(site_id)`` through this lock (F8).
    """

    def __init__(self, site_id: str, ttl_seconds: int):
        self.key = debounce_key(site_id)
        self.ttl_seconds = max(int(ttl_seconds), 1)
        self.token = secrets.token_hex(16)
        self._held = False
        self._started = 0.0
        self._stop: asyncio.Event | None = None
        self._refresh_task: asyncio.Task | None = None

    async def acquire(self) -> bool | None:
        """True acquired, False already held, None Redis degraded."""
        result = await try_acquire(self.key, self.ttl_seconds, token=self.token)
        if result is True:
            self._held = True
            self._started = time.monotonic()
            self._stop = asyncio.Event()
            self._refresh_task = asyncio.create_task(
                _refresh_loop(self.key, self.token, self.ttl_seconds, self._stop)
            )
        return result

    async def release(self) -> None:
        """Stop refresh and drop (or cooldown) the mutex. No-op if not held."""
        if not self._held:
            return
        if self._stop is not None:
            self._stop.set()
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
            self._refresh_task = None
        remaining = self.ttl_seconds - (time.monotonic() - self._started)
        cooldown = max(1, math.ceil(remaining)) if remaining > 0 else 0
        await release(self.key, token=self.token, cooldown_seconds=cooldown)
        self._held = False
