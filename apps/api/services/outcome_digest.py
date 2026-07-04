"""Weekly outcomes digest: email each site owner what Beam drove this week.

"Beam this week: X emails sent, Y clicks, Z conversions ($R attributed)" —
the recurring proof-of-outcome growth buyers keep. Sites with zero sends AND
zero conversions in the window are skipped (no noise), and each site is
throttled via ``sites.last_outcome_digest_sent_at`` so overlapping triggers
can't double-send.

Trigger-agnostic: the APScheduler job calls ``send_weekly_outcome_digests()``,
but it manages its own session and takes a Postgres advisory lock, so it can
move to a Railway cron (or run alongside replicas) unchanged.
"""

from datetime import datetime, timedelta, timezone
from html import escape
from typing import NamedTuple

import structlog
from sqlalchemy import func, or_, select, text, update

from apps.api.config import settings
from apps.api.models.campaign import Campaign, CampaignTouchpoint
from apps.api.models.database import async_session
from apps.api.models.outcome import Conversion
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.services.email_sender import EmailSender

logger = structlog.get_logger()

_LOCK_KEY = "beam_outcome_digest"
# Stats window per digest.
_WINDOW = timedelta(days=7)
# Don't email the same site more often than this (6d so a weekly cron that
# drifts a few hours early never skips a week).
_THROTTLE = timedelta(days=6)


class DigestStats(NamedTuple):
    sent: int
    clicked: int
    conversions: int
    attributed: int
    attributed_revenue_cents: int


def build_digest_email(site_name: str, stats: DigestStats) -> tuple[str, str]:
    """Build (subject, html). Pure — unit-testable without a DB."""
    subject = (
        f"Beam this week: {stats.conversions} conversion"
        f"{'s' if stats.conversions != 1 else ''} for {site_name}"
    )
    revenue = (
        f" (${stats.attributed_revenue_cents / 100:,.2f} attributed)"
        if stats.attributed_revenue_cents
        else ""
    )
    outcomes_url = f"{settings.frontend_url}/dashboard/outcomes"
    html = (
        f"<p>Hi,</p>"
        f"<p>Your Beam week for <strong>{escape(site_name)}</strong>:</p>"
        f"<ul>"
        f"<li><strong>{stats.sent}</strong> campaign emails sent</li>"
        f"<li><strong>{stats.clicked}</strong> clicks back to your site</li>"
        f"<li><strong>{stats.conversions}</strong> conversions — "
        f"<strong>{stats.attributed}</strong> driven by Beam campaigns{escape(revenue)}</li>"
        f"</ul>"
        f'<p><a href="{escape(outcomes_url, quote=True)}">See the full outcomes report &rarr;</a></p>'
        f"<p>&mdash; Beam</p>"
    )
    return subject, html


async def _site_week_stats(db, site_id: str, cutoff: datetime) -> DigestStats:
    tp_row = (
        await db.execute(
            select(
                func.count().filter(
                    CampaignTouchpoint.status == "sent",
                    CampaignTouchpoint.sent_at >= cutoff,
                ),
                func.count().filter(
                    CampaignTouchpoint.clicked_at.is_not(None),
                    CampaignTouchpoint.sent_at >= cutoff,
                ),
            )
            .select_from(CampaignTouchpoint)
            .join(Campaign, Campaign.id == CampaignTouchpoint.campaign_id)
            .where(Campaign.site_id == site_id)
        )
    ).one()
    conv_row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Conversion.attribution == "campaign"),
                func.coalesce(
                    func.sum(Conversion.value_cents).filter(
                        Conversion.attribution == "campaign"
                    ),
                    0,
                ),
            ).where(Conversion.site_id == site_id, Conversion.occurred_at >= cutoff)
        )
    ).one()
    return DigestStats(
        sent=int(tp_row[0] or 0),
        clicked=int(tp_row[1] or 0),
        conversions=int(conv_row[0] or 0),
        attributed=int(conv_row[1] or 0),
        attributed_revenue_cents=int(conv_row[2] or 0),
    )


async def _try_acquire_lock(db) -> bool | None:
    """True = acquired, False = held elsewhere, None = unsupported (SQLite)."""
    try:
        result = await db.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": _LOCK_KEY}
        )
        return bool(result.scalar())
    except Exception as exc:
        logger.warning("outcome_digest_lock_unavailable", error=str(exc))
        return None


async def _release_lock(db) -> None:
    try:
        await db.execute(
            text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": _LOCK_KEY}
        )
    except Exception:
        pass


async def send_weekly_outcome_digests() -> int:
    """Send the weekly digest to owners of active sites. Returns sends made.

    Per-site failures are isolated; the throttle stamp is written via a core
    UPDATE (no ORM expiry games after a rollback).
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - _WINDOW
    throttle_cutoff = now - _THROTTLE
    sent_count = 0

    async with async_session() as db:
        got = await _try_acquire_lock(db)
        if got is False:
            logger.info("outcome_digest_locked_elsewhere")
            return 0
        try:
            rows = (
                await db.execute(
                    select(Site.site_id, Site.name, User.email)
                    .join(User, User.id == Site.user_id)
                    .where(
                        or_(
                            Site.last_outcome_digest_sent_at.is_(None),
                            Site.last_outcome_digest_sent_at < throttle_cutoff,
                        )
                    )
                    .order_by(Site.created_at)
                )
            ).all()

            sender = EmailSender()
            for site_id, site_name, owner_email in rows:
                if not owner_email:
                    continue
                try:
                    stats = await _site_week_stats(db, site_id, cutoff)
                    if stats.sent == 0 and stats.conversions == 0:
                        # Nothing happened — no email, and no stamp so the site
                        # is re-evaluated on the next run.
                        continue
                    subject, html = build_digest_email(site_name, stats)
                    # Pass db so recipient opt-out (unsubscribe/bounce) is honored.
                    await sender.send(
                        to_email=owner_email, subject=subject, body_html=html, db=db
                    )
                    await db.execute(
                        update(Site)
                        .where(Site.site_id == site_id)
                        .values(last_outcome_digest_sent_at=now)
                    )
                    await db.commit()
                    sent_count += 1
                except Exception:
                    logger.exception("outcome_digest_failed", site_id=site_id)
                    await db.rollback()
        finally:
            if got:
                await _release_lock(db)

    if sent_count:
        logger.info("outcome_digests_sent", count=sent_count)
    return sent_count
