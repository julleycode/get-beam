"""Billing service — plan limits, usage metering, and monthly reset."""

from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.user import User

logger = structlog.get_logger()

# Plan limits: None = unlimited
PLAN_LIMITS: dict[str, Optional[int]] = {
    "free": 10,
    "pro": 50,
    "max": None,
}


def get_plan_limits(plan: str) -> Optional[int]:
    """Return monthly identified-visitor limit for a plan. None = unlimited."""
    return PLAN_LIMITS.get(plan, 10)


async def check_usage_allowed(db: AsyncSession, user_id: str) -> bool:
    """Return True if the user is under their plan's monthly visitor limit.

    Also performs the lazy monthly reset: there is no scheduler in this
    deployment, so the counter rolls over the first time it's checked in a
    new calendar month (anchored on billing_cycle_reset_at).
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user: Optional[User] = result.scalar_one_or_none()
    if user is None:
        logger.warning("billing_check_user_not_found", user_id=str(user_id))
        return False

    limit = get_plan_limits(user.plan)
    if limit is None:
        return True  # Unlimited plan

    now = datetime.now(timezone.utc)
    anchor = user.billing_cycle_reset_at
    if anchor is not None and anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    if anchor is None:
        user.billing_cycle_reset_at = now
        await db.commit()
    elif (now.year, now.month) != (anchor.year, anchor.month):
        logger.info(
            "billing_monthly_reset",
            user_id=str(user.id),
            previous_count=user.monthly_identified_count,
        )
        await reset_monthly_usage(db, user_id)
        user.monthly_identified_count = 0

    allowed = user.monthly_identified_count < limit
    if not allowed:
        logger.info(
            "billing_usage_limit_reached",
            user_id=str(user.id),
            plan=user.plan,
            count=user.monthly_identified_count,
            limit=limit,
        )
    return allowed


async def increment_usage(db: AsyncSession, user_id: str) -> None:
    """Increment the monthly identified-visitor counter for a user."""
    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(monthly_identified_count=User.monthly_identified_count + 1)
    )
    await db.commit()
    logger.debug("billing_usage_incremented", user_id=str(user_id))


async def reset_monthly_usage(db: AsyncSession, user_id: str) -> None:
    """Reset the monthly counter and update billing_cycle_reset_at."""
    now = datetime.now(timezone.utc)
    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(monthly_identified_count=0, billing_cycle_reset_at=now)
    )
    await db.commit()
    logger.info("billing_monthly_usage_reset", user_id=str(user_id))
