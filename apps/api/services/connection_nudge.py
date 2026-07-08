"""Connection-expiry nudge: email account owners before a social token dies.

A social OAuth token expiring silently is the #1 cause of "my replies stopped
sending". This scans for tokens expiring within a window (or already expired)
and emails the owner a reconnect nudge, throttled per account via
`last_expiry_alert_sent_at` so nobody is spammed.

Trigger-agnostic: the scheduler calls `check_expiring_connections()`; it manages
its own session and isolates per-account failures.
"""

from datetime import datetime, timedelta, timezone
from html import escape

import structlog
from sqlalchemy import or_, select

from apps.api.config import settings
from apps.api.models.database import async_session
from apps.api.models.social_account import SocialAccount
from apps.api.models.user import User
from apps.api.services.email_sender import EmailSender

logger = structlog.get_logger()

# Don't nudge the same account more than once per this window.
_THROTTLE = timedelta(hours=24)


def _nudge_email(account: SocialAccount, expired: bool) -> tuple[str, str]:
    """Build (subject, html) for the reconnect nudge."""
    platform = account.platform.value.capitalize()
    action_url = f"{settings.frontend_url}/dashboard/social-accounts"
    state = "has expired" if expired else "expires soon"
    subject = f"Action needed: reconnect your {platform} account on Beam"
    html = (
        f"<p>Hi,</p>"
        f"<p>Your <strong>{platform}</strong> connection for "
        f"@{escape(account.username)} {state}. Until you reconnect it, Beam "
        f"can't send replies from this account.</p>"
        f'<p><a href="{escape(action_url, quote=True)}">'
        f"Reconnect {platform} &rarr;</a></p>"
        f"<p>&mdash; Beam</p>"
    )
    return subject, html


async def check_expiring_connections() -> int:
    """Email owners of social accounts whose token expires within the warn
    window (or is already expired). Returns the number of nudges sent.

    Excludes cookie-based LinkedIn outreach accounts (no OAuth token), accounts
    holding a refresh token (access is renewed automatically at send time —
    e.g. Twitter's 2h tokens would otherwise nudge on every run), and rows
    nudged within the throttle window. Per-account failures are logged and
    skipped so one bad send doesn't abort the whole run.
    """
    now = datetime.now(timezone.utc)
    warn_before = now + timedelta(days=settings.connection_nudge_warn_days)
    throttle_cutoff = now - _THROTTLE
    sent = 0

    async with async_session() as db:
        result = await db.execute(
            select(SocialAccount, User)
            .join(User, User.id == SocialAccount.user_id)
            .where(
                SocialAccount.is_active.is_(True),
                SocialAccount.outreach_connection_id.is_(None),
                SocialAccount.refresh_token.is_(None),
                SocialAccount.token_expires_at.is_not(None),
                SocialAccount.token_expires_at <= warn_before,
                or_(
                    SocialAccount.last_expiry_alert_sent_at.is_(None),
                    SocialAccount.last_expiry_alert_sent_at < throttle_cutoff,
                ),
            )
        )
        rows = result.all()

        sender = EmailSender()
        for account, user in rows:
            if not user.email:
                continue
            try:
                expired = account.token_expires_at <= now
                subject, html = _nudge_email(account, expired)
                # Pass db so the recipient's opt-out (unsubscribe/bounce) is honored.
                await sender.send(
                    to_email=user.email,
                    subject=subject,
                    body_html=html,
                    db=db,
                    branding=True,
                )
                account.last_expiry_alert_sent_at = now
                await db.commit()
                sent += 1
            except Exception:
                logger.exception(
                    "connection_nudge_failed", account_id=str(account.id)
                )
                await db.rollback()

    if sent:
        logger.info("connection_nudges_sent", count=sent)
    return sent
