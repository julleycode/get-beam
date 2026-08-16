"""Daily usage caps and BYOK gating.

Free tier:  50 visitor identifications/day per site (Site.daily_resolution_budget)
            + 3 deep research enrichments/day (system keys).
BYOK tier:  Unlimited — user provides their own keys for ALL required APIs.
"""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.api_key import UserApiKey
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.site import Site
from apps.api.models.visitor import IdentifiedVisitor, ResolutionLog
from apps.api.services.redis_client import get_redis

logger = structlog.get_logger()

BYOK_REQUIRED_PROVIDERS: set[str] = {
    "anthropic",
    "openrouter",
    "rb2b",
    "proxycurl",
    "twitter",
    "facebook",
}


async def _today_start() -> datetime:
    # Naive UTC: DB columns are TIMESTAMP WITHOUT TIME ZONE — asyncpg rejects
    # tz-aware params against them (same convention as identity_resolver).
    return datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )


async def is_full_byok(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Check if user has valid BYOK keys for ALL required providers."""
    result = await db.execute(
        select(UserApiKey.provider).where(
            UserApiKey.user_id == user_id,
            UserApiKey.is_valid == True,  # noqa: E712
            UserApiKey.provider.in_(BYOK_REQUIRED_PROVIDERS),
        )
    )
    user_providers = {row[0] for row in result.all()}
    return BYOK_REQUIRED_PROVIDERS.issubset(user_providers)


async def get_site_daily_budget(db: AsyncSession, site_id: str) -> int:
    """Per-site daily resolution budget, falling back to the global default.

    Single source of truth for the cap — used by both the attempt meter
    (IdentityResolver.check_daily_budget) and the success meter
    (check_identify_budget) so the two can never disagree.
    """
    result = await db.execute(
        select(Site.daily_resolution_budget).where(Site.site_id == site_id)
    )
    budget = result.scalar_one_or_none()
    return budget if budget is not None else settings.default_daily_resolution_budget


async def get_resolution_attempts_today(db: AsyncSession, site_id: str) -> int:
    """Count DISTINCT visitors with resolution attempts today.

    One visitor's resolve() writes one ResolutionLog row per provider tried
    (2-8 rows), so counting rows would burn the daily budget 2-8x too fast.
    The budget is "visitor lookups per day", not "provider calls per day".
    """
    today = await _today_start()
    result = await db.execute(
        select(func.count(func.distinct(ResolutionLog.visitor_id))).where(
            ResolutionLog.site_id == site_id,
            ResolutionLog.created_at >= today,
        )
    )
    return result.scalar() or 0


async def check_resolution_attempt_budget(db: AsyncSession, site_id: str) -> bool:
    """True while the site still has daily resolution-attempt budget left."""
    used = await get_resolution_attempts_today(db, site_id)
    return used < await get_site_daily_budget(db, site_id)


async def get_identify_usage(db: AsyncSession, site_id: str) -> int:
    """Count identifications performed today for a site."""
    today = await _today_start()
    result = await db.execute(
        select(func.count()).select_from(IdentifiedVisitor).where(
            IdentifiedVisitor.site_id == site_id,
            IdentifiedVisitor.resolved_at >= today,
        )
    )
    return result.scalar() or 0


async def get_enrich_usage(db: AsyncSession, site_id: str) -> int:
    """Count deep research enrichments performed today for a site."""
    today = await _today_start()
    result = await db.execute(
        select(func.count()).select_from(EnrichmentProfile).where(
            EnrichmentProfile.site_id == site_id,
            EnrichmentProfile.social_context_updated_at >= today,
        )
    )
    return result.scalar() or 0


def _budget_result(used: int, limit: int | None, byok: bool) -> dict:
    """Assemble the standard budget-meter response. BYOK users are uncapped."""
    if byok:
        return {"allowed": True, "used": used, "limit": None, "is_byok": True}
    return {
        "allowed": used < limit,
        "used": used,
        "limit": limit,
        "is_byok": False,
    }


async def check_identify_budget(
    db: AsyncSession, site_id: str, user_id: uuid.UUID
) -> dict:
    """Check if site can perform more identifications today.

    Returns {"allowed": bool, "used": int, "limit": int, "is_byok": bool}.
    """
    byok = await is_full_byok(db, user_id)
    used = await get_identify_usage(db, site_id)
    limit = await get_site_daily_budget(db, site_id)
    return _budget_result(used, limit, byok)


async def check_enrich_budget(
    db: AsyncSession, site_id: str, user_id: uuid.UUID
) -> dict:
    """Check if site can perform more deep research enrichments today.

    Returns {"allowed": bool, "used": int, "limit": int, "is_byok": bool}.
    """
    byok = await is_full_byok(db, user_id)
    used = await get_enrich_usage(db, site_id)
    limit = settings.default_daily_enrichment_budget
    return _budget_result(used, limit, byok)


def missing_byok_providers(user_providers: set[str]) -> set[str]:
    """Return which BYOK providers the user is still missing."""
    return BYOK_REQUIRED_PROVIDERS - user_providers


# ─────────────────── OSINT account-scan daily budget ───────────────────
# OSINT scans are free (no paid provider) but slow + IP-block-prone, so we cap
# them per site/day via a Redis counter rather than a DB table (no migration).


def _osint_count_key(site_id: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"osint:count:{site_id}:{day}"


async def get_osint_usage(site_id: str) -> int:
    """OSINT scans started today for a site (Redis counter). Fail-open to 0."""
    try:
        raw = await get_redis().get(_osint_count_key(site_id))
        return int(raw or 0)
    except Exception:
        return 0


async def increment_osint_usage(site_id: str) -> None:
    """Bump today's OSINT scan counter (2-day TTL so it self-expires)."""
    try:
        redis = get_redis()
        key = _osint_count_key(site_id)
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 2 * 86400)
    except Exception:
        logger.debug("osint_usage_increment_failed", site_id=site_id)


async def check_osint_budget(
    db: AsyncSession, site_id: str, user_id: uuid.UUID
) -> dict:
    """Check if a site can run another OSINT scan today.

    Returns {"allowed": bool, "used": int, "limit": int | None, "is_byok": bool}.
    BYOK users are uncapped (consistent with the other meters).
    """
    byok = await is_full_byok(db, user_id)
    used = await get_osint_usage(site_id)
    limit = settings.osint_scan_daily_budget
    return _budget_result(used, limit, byok)


# ─────────────── Paid OSINT (OSINT Industries) daily credit guard ───────────────
# Hard cap on billable paid lookups/site/day — protects against runaway credit
# burn even when the pipeline auto-triggers the paid fallback. NOT BYOK-exempt:
# the paid key is a SYSTEM key (operator pays), so the cap always applies.


def _osint_paid_count_key(site_id: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"osint:paid:count:{site_id}:{day}"


async def get_osint_paid_usage(site_id: str) -> int:
    try:
        raw = await get_redis().get(_osint_paid_count_key(site_id))
        return int(raw or 0)
    except Exception:
        # Redis down → fail CLOSED for the paid path (don't risk burning credits).
        return settings.osint_paid_daily_budget


async def increment_osint_paid_usage(site_id: str) -> None:
    try:
        redis = get_redis()
        key = _osint_paid_count_key(site_id)
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 2 * 86400)
    except Exception:
        logger.debug("osint_paid_usage_increment_failed", site_id=site_id)


async def osint_paid_budget_left(site_id: str) -> bool:
    """True while the site still has paid-lookup budget today."""
    return await get_osint_paid_usage(site_id) < settings.osint_paid_daily_budget


# ─────────────── Site analysis (onboarding) daily budget ───────────────
# Caps grounded company-profile ANALYSES per site/day (one run = one unit, never
# one unit per Gemini call — a run makes two). Redis counter, no migration.
#
# NOT BYOK-exempt: the analysis burns the SYSTEM Gemini key (the operator pays),
# so the correct posture precedent is the paid-OSINT block above, not the free
# OSINT one. Copying check_osint_budget's BYOK-uncapped shape would hand any BYOK
# user unlimited grounded runs on the operator's key.
#
# Deliberately no `db`/`user_id` parameters: is_full_byok is never called here, so
# they would be dead params that both re-invite a BYOK exemption and add a DB
# round-trip to GET /sites/{id}/analysis, which the panel polls every 4 s.


def _site_analysis_count_key(site_id: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"site_analysis:count:{site_id}:{day}"


async def get_site_analysis_usage(site_id: str) -> int:
    """Analyses started today for a site (Redis counter). Fail-open to 0.

    Fails OPEN (unlike the paid-OSINT meter, which fails closed) because this
    guards a free-tier system-key call, not billable credits — a Redis outage
    must not block onboarding.
    """
    try:
        raw = await get_redis().get(_site_analysis_count_key(site_id))
        return int(raw or 0)
    except Exception:
        return 0


async def increment_site_analysis_usage(site_id: str) -> None:
    """Bump today's analysis counter (2-day TTL so it self-expires)."""
    try:
        redis = get_redis()
        key = _site_analysis_count_key(site_id)
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 2 * 86400)
    except Exception:
        logger.debug("site_analysis_usage_increment_failed", site_id=site_id)


async def check_site_analysis_budget(site_id: str) -> dict:
    """Check if a site can run another analysis today.

    Returns the standard meter dict; the API projects exactly `used`, `limit` and
    `allowed` into SiteAnalysisOut.budget and DROPS `is_byok` at that boundary —
    it is permanently False here and would invite a future reader to reintroduce
    an exemption.
    """
    used = await get_site_analysis_usage(site_id)
    return _budget_result(used, settings.site_analysis_daily_budget, False)
