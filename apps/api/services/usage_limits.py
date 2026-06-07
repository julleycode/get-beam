"""Daily usage caps and BYOK gating.

Free tier:  20 identifications/day + 3 deep research enrichments/day (system keys).
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
from apps.api.models.visitor import IdentifiedVisitor

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
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


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


async def check_identify_budget(
    db: AsyncSession, site_id: str, user_id: uuid.UUID
) -> dict:
    """Check if site can perform more identifications today.

    Returns {"allowed": bool, "used": int, "limit": int, "is_byok": bool}.
    """
    byok = await is_full_byok(db, user_id)
    used = await get_identify_usage(db, site_id)
    limit = settings.default_daily_resolution_budget

    if byok:
        return {"allowed": True, "used": used, "limit": None, "is_byok": True}

    return {
        "allowed": used < limit,
        "used": used,
        "limit": limit,
        "is_byok": False,
    }


async def check_enrich_budget(
    db: AsyncSession, site_id: str, user_id: uuid.UUID
) -> dict:
    """Check if site can perform more deep research enrichments today.

    Returns {"allowed": bool, "used": int, "limit": int, "is_byok": bool}.
    """
    byok = await is_full_byok(db, user_id)
    used = await get_enrich_usage(db, site_id)
    limit = settings.default_daily_enrichment_budget

    if byok:
        return {"allowed": True, "used": used, "limit": None, "is_byok": True}

    return {
        "allowed": used < limit,
        "used": used,
        "limit": limit,
        "is_byok": False,
    }


def missing_byok_providers(user_providers: set[str]) -> set[str]:
    """Return which BYOK providers the user is still missing."""
    return BYOK_REQUIRED_PROVIDERS - user_providers
