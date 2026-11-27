"""Public on-site greeting endpoint — GET /api/v1/greeting.

Unauthenticated (called by ``greeting.js`` from customer pages). Always 200
``{"show": false}`` unless every gate in ``services.greeting`` passes; the only
other status is 429 (rate limit). Never cached by browsers/CDNs. Logs carry
site_id + show + reason code only — never IP, company, domain or visitor id.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.database import get_db
from apps.api.services import greeting as greeting_service
from apps.api.services.ip_resolution import resolve_client_ip
from apps.api.services.rate_limiter import limiter, site_limiter
from apps.api.services.redis_client import get_redis

logger = structlog.get_logger()

router = APIRouter()

GREETING_SITE_LIMIT_PER_MINUTE = 600
_NO_STORE = {"Cache-Control": "no-store"}


def _site_over_limit(site_id: str) -> bool:
    """Per-site bucket with its OWN scope (not ingest's; not flag-gated). Fail-open."""
    try:
        from limits import RateLimitItemPerMinute

        item = RateLimitItemPerMinute(GREETING_SITE_LIMIT_PER_MINUTE)
        return not site_limiter.limiter.hit(item, "site_greeting", site_id)
    except Exception as exc:
        logger.warning("greeting_site_limit_check_failed", error=type(exc).__name__)
        return False


@router.get("")
@limiter.limit("30/minute")
async def get_greeting(
    request: Request,
    site_id: str | None = None,
    v: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    # Flag OFF: no DB, no Redis, no limiter buckets touched.
    if not settings.onsite_greeting_enabled:
        return JSONResponse({"show": False}, headers=_NO_STORE)

    if site_id and len(site_id) <= 50 and limiter.enabled and _site_over_limit(site_id):
        raise HTTPException(status_code=429, detail="rate limited", headers=_NO_STORE)

    try:
        redis = get_redis()
    except Exception:
        redis = None

    try:
        show, reason, payload = await greeting_service.decide_greeting(
            db,
            redis,
            site_id,
            resolve_client_ip(request),
            request.headers.get("origin"),
            v,
        )
    except Exception as exc:
        # Fail closed: any unexpected error renders nothing.
        logger.warning("greeting_failed", error=type(exc).__name__)
        show, reason, payload = False, "error", greeting_service.hidden()

    logger.info(
        "greeting_decided",
        site_id=(site_id or "")[:50],
        show=show,
        reason=reason,
    )
    return JSONResponse(payload, headers=_NO_STORE)
