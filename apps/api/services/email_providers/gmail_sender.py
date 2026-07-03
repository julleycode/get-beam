"""Send campaign email through a connected Gmail, with token refresh + fallback.

Sits between the campaign send path and the raw Gmail HTTP client (gmail.py):
resolves the site's connected sender, keeps its access token fresh, and turns a
revoked grant into a clean signal so the caller can fall back to SendGrid.
"""

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.email_sender_account import EmailSenderAccount
from apps.api.models.site import Site
from apps.api.services.email_providers import gmail
from apps.api.services.encryption import decrypt_token, encrypt_token

logger = structlog.get_logger()

# Refresh a little before the token actually expires to avoid a mid-send 401.
_REFRESH_SKEW = timedelta(seconds=120)


async def resolve_sender_for_site(db: AsyncSession, site_id: str) -> EmailSenderAccount | None:
    """The active Google sender for the site's owner, or None (→ send via SendGrid).

    One connected Gmail per site owner drives every campaign for their sites.
    """
    owner_id = (
        await db.execute(select(Site.user_id).where(Site.site_id == site_id))
    ).scalar_one_or_none()
    if owner_id is None:
        return None
    return (
        await db.execute(
            select(EmailSenderAccount).where(
                EmailSenderAccount.user_id == owner_id,
                EmailSenderAccount.provider == "google",
                EmailSenderAccount.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()


async def _ensure_fresh_access_token(db: AsyncSession, sender: EmailSenderAccount) -> str:
    """Return a usable plaintext access token, refreshing + persisting if needed.

    On a revoked/expired grant, deactivates the sender (so future sends fall back
    to SendGrid and the UI prompts a reconnect) and re-raises GmailOAuthError.
    """
    expires_at = sender.token_expires_at
    now = datetime.now(timezone.utc)
    # token_expires_at is a tz-aware column; guard against a naive value just in case.
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at is not None and expires_at - _REFRESH_SKEW > now:
        return decrypt_token(sender.access_token)

    if not sender.refresh_token:
        # No refresh token and the access token is stale — cannot recover.
        sender.is_active = False
        await db.commit()
        raise gmail.GmailOAuthError("no refresh token; sender needs reconnect", invalid_grant=True)

    try:
        tokens = await gmail.refresh_access_token(decrypt_token(sender.refresh_token))
    except gmail.GmailOAuthError as exc:
        if exc.invalid_grant:
            sender.is_active = False
            await db.commit()
        raise

    sender.access_token = encrypt_token(tokens.access_token)
    if tokens.refresh_token:
        sender.refresh_token = encrypt_token(tokens.refresh_token)
    sender.token_expires_at = tokens.expires_at
    await db.commit()
    return tokens.access_token


async def send_via_gmail(
    db: AsyncSession,
    sender: EmailSenderAccount,
    *,
    to_email: str,
    subject: str,
    body_html: str,
    unsubscribe_url: str | None = None,
) -> dict:
    """Send one campaign email as the connected Gmail account.

    Raises gmail.GmailOAuthError (invalid_grant) when the grant is dead, or
    RuntimeError on other send errors — the caller falls back to SendGrid either
    way. On success returns the Gmail API response.
    """
    access_token = await _ensure_fresh_access_token(db, sender)
    return await gmail.send_message(
        access_token=access_token,
        from_email=sender.email,
        to_email=to_email,
        subject=subject,
        body_html=body_html,
        unsubscribe_url=unsubscribe_url,
    )
