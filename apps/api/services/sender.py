"""Sender service: posts approved drafts to the target platform."""

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.draft import Draft, DraftStatus
from apps.api.models.post import Post
from apps.api.models.social_account import SocialAccount
from apps.api.services.encryption import decrypt_token, encrypt_token
from apps.api.services.platforms import get_platform_service

logger = structlog.get_logger()


def _http_error_detail(exc: Exception) -> str:
    """Best-effort HTTP error detail string from an exception."""
    if hasattr(exc, "response"):
        try:
            return f"HTTP {exc.response.status_code}: {exc.response.text}"
        except Exception:
            pass
    return str(exc)


async def _refresh_if_expired(
    db: AsyncSession, account: SocialAccount
) -> str:
    """Check if the access token is expired and refresh if possible.

    Returns the (possibly refreshed) plaintext access token.
    """
    access_token = decrypt_token(account.access_token)

    now = datetime.now(timezone.utc)

    # If expiry is set and token is still valid (with 5-minute buffer), use it
    if account.token_expires_at and account.token_expires_at > now:
        return access_token

    # If no expiry is set, check if the account is old enough that the token
    # has likely expired (Twitter tokens last ~2 hours).
    if not account.token_expires_at:
        # If we don't know when it expires, proactively refresh if possible
        logger.info(
            "token_expiry_unknown_refreshing",
            account_id=str(account.id),
            platform=account.platform.value,
        )

    # Token is expired — try to refresh
    refresh_token = decrypt_token(account.refresh_token) if account.refresh_token else None
    if not refresh_token:
        logger.warning(
            "token_expired_no_refresh",
            account_id=str(account.id),
            platform=account.platform.value,
        )
        return access_token  # Return expired token, will fail at the API level

    service = get_platform_service(account.platform)
    try:
        new_tokens = await service.refresh_tokens(refresh_token)
        account.access_token = encrypt_token(new_tokens.access_token)
        if new_tokens.refresh_token:
            account.refresh_token = encrypt_token(new_tokens.refresh_token)
        account.token_expires_at = new_tokens.expires_at
        await db.commit()
        logger.info(
            "token_refreshed",
            account_id=str(account.id),
            platform=account.platform.value,
        )
        return new_tokens.access_token
    except Exception as exc:
        error_detail = _http_error_detail(exc)
        logger.exception(
            "token_refresh_failed",
            account_id=str(account.id),
            platform=account.platform.value,
            error_detail=error_detail,
        )
        return access_token  # Fall back to expired token


async def send_draft(db: AsyncSession, draft: Draft) -> bool:
    """Send an approved draft to the platform.

    Returns True if sent successfully, False otherwise.
    """
    if draft.status != DraftStatus.approved:
        logger.warning("send_draft_not_approved", draft_id=str(draft.id))
        return False

    # Get the content to send (user-edited takes priority)
    content = draft.edited_content or draft.ai_content

    # Get the associated post to find the platform post ID and account
    if draft.post_id:
        result = await db.execute(select(Post).where(Post.id == draft.post_id))
        post = result.scalar_one_or_none()
        if not post:
            logger.error("send_draft_post_not_found", draft_id=str(draft.id))
            draft.status = DraftStatus.failed
            await db.commit()
            return False

        # Get the social account for access token
        result = await db.execute(
            select(SocialAccount).where(
                SocialAccount.id == post.social_account_id
            )
        )
        account = result.scalar_one_or_none()
        if not account:
            logger.error("send_draft_account_not_found", draft_id=str(draft.id))
            draft.status = DraftStatus.failed
            await db.commit()
            return False

        # Refresh token if expired before attempting to send
        access_token = await _refresh_if_expired(db, account)

        service = get_platform_service(draft.platform)
        try:
            comment_id = await service.post_comment(
                access_token, post.platform_post_id, content
            )
            draft.status = DraftStatus.sent
            draft.sent_at = datetime.now(timezone.utc)
            post.commented = True
            await db.commit()
            logger.info(
                "draft_sent",
                draft_id=str(draft.id),
                platform=draft.platform.value,
                comment_id=comment_id,
            )
            return True
        except Exception as exc:
            # Log as much detail as possible for debugging
            error_detail = _http_error_detail(exc)
            logger.exception(
                "send_draft_failed",
                draft_id=str(draft.id),
                platform=draft.platform.value,
                error_detail=error_detail,
            )
            draft.status = DraftStatus.failed
            await db.commit()
            return False

    logger.warning("send_draft_no_target", draft_id=str(draft.id))
    draft.status = DraftStatus.failed
    await db.commit()
    return False
