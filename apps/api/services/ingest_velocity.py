"""Write-time ingest velocity detection (P4).

Detects the shape of a rotating-IP flood at insert time, on the same hot path as
the existing bot / datacenter / proxy-VPN checks — not deferred to a background
job, so a flagged event is marked in the SAME row that stores it.

Signal design: a rotating-IP flood has HIGH IP entropy by construction (that is
the whole point of the attack), which makes IP entropy useless as the detector.
What the attacker cannot cheaply fake is *browser* diversity — a flood mints many
distinct ``visitor_id`` values that share very few distinct fingerprints. So the
flag requires BOTH conditions:

    distinct_visitors >= ingest_velocity_visitor_threshold
    AND (distinct_fingerprints / distinct_visitors) < ingest_velocity_min_fingerprint_diversity

Requiring high visitor count as a PRECONDITION is what keeps a legitimate
low-diversity burst (a site replaying old events for the same small visitor set)
from being flagged, and requiring low diversity is what keeps an organic viral
spike (many visitors, many real fingerprints) from being flagged.

Every Redis key carries an explicit TTL refreshed on each write — an untracked,
unbounded key per site would be a self-inflicted DoS.

Fail-open everywhere: any Redis error returns False (never flag, never block),
matching the datacenter-IP and proxy/VPN checks on the same path.
"""

import structlog

logger = structlog.get_logger()

_VISITOR_KEY = "ingest_velocity:visitors:{site_id}"
_FINGERPRINT_KEY = "ingest_velocity:fingerprints:{site_id}"

# Stand-in bucket for a request that carried no usable fingerprint. Counted as
# its OWN diversity bucket rather than dropped: silently excluding it from the
# denominator would let an attacker suppress the whole signal just by omitting
# the fingerprint field.
_MISSING_FINGERPRINT = "__missing__"


def evaluate_velocity(
    visitor_count: int,
    fingerprint_count: int,
    visitor_threshold: int,
    min_fingerprint_diversity: float,
) -> bool:
    """Pure decision function — True when this window looks like a flood."""
    if visitor_count < visitor_threshold:
        return False
    if visitor_count <= 0:
        return False
    diversity = fingerprint_count / visitor_count
    return diversity < min_fingerprint_diversity


async def check_velocity(
    redis,
    site_id: str,
    visitor_id: str,
    fingerprint: str | None,
) -> bool:
    """Record this arrival and report whether the site's window looks like a flood.

    ``redis`` is an async Redis client (or None — then this is a no-op).
    """
    from apps.api.config import settings

    if not settings.ingest_velocity_enabled:
        return False
    if redis is None or not site_id or not visitor_id:
        return False

    try:
        window = settings.ingest_velocity_window_seconds
        visitor_key = _VISITOR_KEY.format(site_id=site_id)
        fingerprint_key = _FINGERPRINT_KEY.format(site_id=site_id)

        await redis.sadd(visitor_key, visitor_id)
        await redis.expire(visitor_key, window)

        await redis.sadd(fingerprint_key, fingerprint or _MISSING_FINGERPRINT)
        await redis.expire(fingerprint_key, window)

        visitor_count = int(await redis.scard(visitor_key) or 0)
        fingerprint_count = int(await redis.scard(fingerprint_key) or 0)

        flagged = evaluate_velocity(
            visitor_count,
            fingerprint_count,
            settings.ingest_velocity_visitor_threshold,
            settings.ingest_velocity_min_fingerprint_diversity,
        )
        if flagged:
            # Counts and ids only — never visitor PII (AC-9).
            logger.warning(
                "ingest_velocity_flagged",
                site_id=site_id,
                distinct_visitors=visitor_count,
                distinct_fingerprints=fingerprint_count,
                window_seconds=window,
            )
        return flagged
    except Exception as exc:
        # Fail-open: a Redis blip must never flag or block a real visitor.
        logger.warning("ingest_velocity_check_failed", site_id=site_id, error=str(exc))
        return False
