"""Best-effort recorder for the api_usage_logs cost ledger.

GOLDEN RULE: a logging failure must NEVER break the API call being recorded.
Every path is wrapped and swallowed — callers should `await log_api_call(...)`
without try/except of their own.

Pass `db` (the caller's AsyncSession) whenever one is in scope so the cost row
commits in the same transaction as the work it records. Without `db`, a short
own session is opened and committed independently.
"""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.api_usage import ApiUsageLog
from apps.api.models.database import async_session
from apps.api.services.api_pricing import price_for

logger = structlog.get_logger()


async def log_api_call(
    *,
    provider: str,
    category: str,
    success: bool,
    operation: str | None = None,
    cost_usd: float | None = None,
    units: int | None = None,
    site_id: str | None = None,
    visitor_id: str | None = None,
    response_time_ms: int | None = None,
    meta: dict | None = None,
    db: AsyncSession | None = None,
) -> None:
    """Record one billable API call. cost_usd is derived from api_pricing when
    not given. Never raises."""
    try:
        if cost_usd is None:
            cost_usd = price_for(provider, operation, units, success=success)
        row = ApiUsageLog(
            site_id=site_id,
            visitor_id=visitor_id,
            provider=provider,
            category=category,
            operation=operation,
            success=success,
            cost_usd=float(cost_usd or 0.0),
            units=units,
            response_time_ms=response_time_ms,
            meta=meta,
        )
        if db is not None:
            # Same transaction as the caller's work; the caller commits.
            db.add(row)
            await db.flush()
        else:
            async with async_session() as session:
                session.add(row)
                await session.commit()
    except Exception as exc:  # never let cost-logging break the real call path
        logger.warning(
            "api_usage_log_failed",
            provider=provider,
            category=category,
            error=str(exc),
        )
