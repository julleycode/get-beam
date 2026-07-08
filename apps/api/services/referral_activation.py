"""Referral activation sweep: reward referrals once the referee is real.

A claim only LINKS accounts; the reward waits until the referee's pixel has
recorded actual ingested events (already bot-filtered) — the anti-fraud bar
that separates "signed up to farm quota" from "actually tried Beam". Runs as
an hourly scheduled job (never in the ingest hot path); up to an hour of
award latency is fine for a reward.

Idempotency is a single conditional UPDATE on referral_activated_at — rowcount
0 means another run already rewarded this referee, so the referrer is never
paid twice. Trigger-agnostic: owns its session and takes an advisory lock, so
it can move to a Railway cron unchanged.
"""

from datetime import datetime, timezone
from html import escape

import structlog
from sqlalchemy import exists, func, select, text, update

from apps.api.config import settings
from apps.api.models.database import async_session
from apps.api.models.event import Event
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.services.billing import (
    REFERRAL_BONUS_CAP,
    REFERRAL_BONUS_PER_ACTIVATION,
)
from apps.api.services.email_sender import EmailSender
from apps.api.services.pii import mask_email

logger = structlog.get_logger()

_LOCK_KEY = "beam_referral_activation"


def build_reward_email(referrer_bonus: int) -> tuple[str, str]:
    """Build (subject, html) for the referrer's reward notification. Pure."""
    referrals_url = f"{settings.frontend_url}/dashboard/referrals"
    subject = (
        f"You earned +{REFERRAL_BONUS_PER_ACTIVATION} identified visitors/month"
    )
    html = (
        f"<p>Hi,</p>"
        f"<p>Someone you referred just went live on Beam — their pixel is "
        f"recording real visitors. That earns you "
        f"<strong>+{REFERRAL_BONUS_PER_ACTIVATION} identified visitors/month, "
        f"permanently</strong>.</p>"
        f"<p>Your referral bonus is now <strong>+{referrer_bonus}/mo</strong> "
        f"(of +{REFERRAL_BONUS_CAP} max).</p>"
        f'<p><a href="{escape(referrals_url, quote=True)}">'
        f"Share your link again &rarr;</a></p>"
        f"<p>&mdash; Beam</p>"
    )
    return subject, html


async def _try_acquire_lock(db) -> bool | None:
    """True = acquired, False = held elsewhere, None = unsupported (SQLite)."""
    try:
        result = await db.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": _LOCK_KEY}
        )
        return bool(result.scalar())
    except Exception as exc:
        logger.warning("referral_activation_lock_unavailable", error=str(exc))
        return None


async def _release_lock(db) -> None:
    try:
        await db.execute(
            text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": _LOCK_KEY}
        )
    except Exception:
        pass


async def _referee_has_real_events(db, referee_id) -> bool:
    """Any ingested event on any of the referee's sites (ingest is bot-filtered)."""
    return bool(
        (
            await db.execute(
                select(
                    exists(
                        select(Event.id)
                        .join(Site, Site.site_id == Event.site_id)
                        .where(Site.user_id == referee_id)
                    )
                )
            )
        ).scalar()
    )


async def activate_pending_referrals() -> int:
    """Reward every pending referral whose referee now has real events.

    Returns the number of referrals activated. Per-row failures are isolated.
    """
    activated = 0
    async with async_session() as db:
        got = await _try_acquire_lock(db)
        if got is False:
            logger.info("referral_activation_locked_elsewhere")
            return 0
        try:
            pending = (
                await db.execute(
                    select(User.id, User.referred_by_user_id).where(
                        User.referred_by_user_id.is_not(None),
                        User.referral_activated_at.is_(None),
                    )
                )
            ).all()

            for referee_id, referrer_id in pending:
                try:
                    if not await _referee_has_real_events(db, referee_id):
                        continue
                    # Idempotency gate: only the run that flips
                    # referral_activated_at from NULL pays out.
                    result = await db.execute(
                        update(User)
                        .where(
                            User.id == referee_id,
                            User.referral_activated_at.is_(None),
                        )
                        .values(
                            referral_activated_at=datetime.now(timezone.utc),
                            bonus_monthly_quota=func.least(
                                User.bonus_monthly_quota
                                + REFERRAL_BONUS_PER_ACTIVATION,
                                REFERRAL_BONUS_CAP,
                            ),
                        )
                    )
                    if result.rowcount == 0:
                        continue  # another run got here first
                    await db.execute(
                        update(User)
                        .where(User.id == referrer_id)
                        .values(
                            bonus_monthly_quota=func.least(
                                User.bonus_monthly_quota
                                + REFERRAL_BONUS_PER_ACTIVATION,
                                REFERRAL_BONUS_CAP,
                            )
                        )
                    )
                    await db.commit()
                    activated += 1
                    logger.info(
                        "referral_activated",
                        referee_id=str(referee_id),
                        referrer_id=str(referrer_id),
                    )
                    # Best-effort reward email — a failed send must never roll
                    # back or re-run an already-committed award.
                    try:
                        referrer = (
                            await db.execute(
                                select(User).where(User.id == referrer_id)
                            )
                        ).scalar_one_or_none()
                        if referrer is not None and referrer.email:
                            subject, html = build_reward_email(
                                referrer.bonus_monthly_quota
                            )
                            await EmailSender().send(
                                to_email=referrer.email,
                                subject=subject,
                                body_html=html,
                                db=db,
                                branding=True,
                            )
                    except Exception as exc:
                        logger.warning(
                            "referral_reward_email_failed",
                            referrer_id=str(referrer_id),
                            email=mask_email(getattr(referrer, "email", None)),
                            error=str(exc),
                        )
                except Exception:
                    logger.exception(
                        "referral_activation_failed", referee_id=str(referee_id)
                    )
                    await db.rollback()
        finally:
            if got:
                await _release_lock(db)

    if activated:
        logger.info("referrals_activated", count=activated)
    return activated
