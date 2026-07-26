"""Billing service — plan limits, usage metering, and monthly reset."""

from datetime import datetime, timedelta, timezone
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

# Per-plan website (Site) count limits: None = unlimited.
# MUST stay in sync with the pricing page copy at
# apps/web/src/app/pricing/page.tsx ("1 website" / "3 websites" /
# "Unlimited websites"). There is no shared Python↔TS constant; this comment
# plus the drift-guard test in tests/unit/test_site_limit.py is the guard.
PLAN_SITE_LIMITS: dict[str, Optional[int]] = {
    "free": 1,
    "pro": 3,
    "max": None,
}

# Referral program: each activated referral permanently adds this many
# identified visitors to the monthly limit, up to the cap. The cap is enforced
# at award time (LEAST in SQL — see referral_activation) and again defensively
# here at read time.
REFERRAL_BONUS_PER_ACTIVATION = 10
REFERRAL_BONUS_CAP = 50

# Slack beyond current_period_end before a lapsed paid plan drops to free.
# A paying subscription's recurring-charge ping pushes current_period_end forward
# ~a day early (see _GUMROAD_PERIOD_DAYS), so this grace only ever forgives a
# late-delivered renewal ping — never keeps a genuinely cancelled plan alive.
ENTITLEMENT_GRACE = timedelta(days=1)


def get_plan_limits(plan: str) -> Optional[int]:
    """Return monthly identified-visitor limit for a plan. None = unlimited."""
    return PLAN_LIMITS.get(plan, 10)


def get_site_limit(plan: str) -> Optional[int]:
    """Return the max number of websites a plan may create. None = unlimited.

    An unknown plan key falls back to the most restrictive tier (free), mirroring
    get_plan_limits' fallback-to-free posture: never grant more than we sold.
    """
    return PLAN_SITE_LIMITS.get(plan, PLAN_SITE_LIMITS["free"])


def get_effective_limit(plan: str, bonus_monthly_quota: int | None) -> Optional[int]:
    """Plan limit plus earned referral bonus. None = unlimited (bonus moot)."""
    limit = get_plan_limits(plan)
    if limit is None:
        return None
    return limit + min(bonus_monthly_quota or 0, REFERRAL_BONUS_CAP)


def get_effective_plan(
    plan: str,
    current_period_end: Optional[datetime],
    now: Optional[datetime] = None,
) -> str:
    """Return the plan actually in force right now, lapsing expired paid plans.

    A paid subscription pushes current_period_end forward on every recurring
    charge. Once payments stop — the buyer cancels, a renewal fails, or a
    cancellation/subscription_ended ping was never registered at Gumroad — the
    date goes stale and access falls back to free. This is the single enforcement
    point for entitlement expiry: nothing else in the app reads current_period_end
    to gate access, so without this a cancelled plan would keep its tier forever.

    A NULL date means no billing period is on record (e.g. a comp/admin-granted
    plan), so the stored plan is honored as-is rather than downgraded.
    """
    if plan == "free" or current_period_end is None:
        return plan
    end = current_period_end
    if end.tzinfo is None:  # tolerate naive timestamps (SQLite / legacy rows)
        end = end.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return plan if now <= end + ENTITLEMENT_GRACE else "free"


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

    effective_plan = get_effective_plan(user.plan, user.current_period_end)
    limit = get_effective_limit(effective_plan, user.bonus_monthly_quota)
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
