"""Sender service: posts approved drafts to the target platform."""

import re
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.draft import Draft, DraftStatus
from apps.api.models.post import Post
from apps.api.models.site import Site
from apps.api.models.social_account import SocialAccount
# CHAR_LIMITS is imported as the module-level constant, never copied: a utm
# rewrite lengthens the raw string AFTER ai_reply already truncated to the cap at
# generation time, so both sides must agree on one number.
#
# CROSS-MODULE CONTRACT: `ai_reply.CHAR_LIMITS` now has a second consumer. It may
# not be changed unilaterally — a raised limit here would let the send path post
# past a platform cap. Import verified free of circular import: `ai_reply` pulls
# only `config` and `models.social_account`.
from apps.api.services.ai_reply import CHAR_LIMITS
from apps.api.services.detection_scanner import _host_of
from apps.api.services.encryption import decrypt_token, encrypt_token
from apps.api.services.engagement_tracker import EngagementTracker, make_utm_tag
from apps.api.services.platforms import get_platform_service

logger = structlog.get_logger()

# Deliberately permissive: we only ever ACT on a match whose host equals the
# site's, so over-matching costs nothing while under-matching would silently skip
# a legitimate mint.
_URL_RE = re.compile(r"https?://[^\s<>\"']+")


class SocialTokenExpiredError(Exception):
    """Raised when a social account's token is expired and cannot be refreshed.

    Distinct from a generic send failure: it means the user must RECONNECT the
    account (re-run OAuth) — retrying the send will never succeed. Callers should
    surface `str(self)` to the user as an actionable message rather than the
    vague "couldn't be sent" error.
    """

    def __init__(self, platform: str, username: str) -> None:
        self.platform = platform
        self.username = username
        super().__init__(
            f"Your {platform} session for @{username} has expired. "
            f"Reconnect the account in Social Accounts and try again."
        )


def _http_error_detail(exc: Exception) -> str:
    """Best-effort HTTP error detail string from an exception."""
    if hasattr(exc, "response"):
        try:
            return f"HTTP {exc.response.status_code}: {exc.response.text}"
        except Exception:
            pass
    return str(exc)


def _friendly_send_error(detail: str, platform: str) -> str:
    """Map a raw send error into a plain-language reason for the failed draft.

    Kept deliberately non-technical: the failed-draft card shows this to the
    user, so it names the likely cause and the fix rather than an HTTP status.
    """
    d = detail.lower()
    name = platform.capitalize()
    if "403" in d or "forbidden" in d:
        return (
            f"{name} wouldn't allow this reply — the post may restrict who can "
            "reply, or it was removed."
        )
    if "401" in d or "unauthor" in d:
        return (
            f"Your {platform} session was rejected. Reconnect the account in "
            "Social Accounts and try again."
        )
    if "429" in d or "rate" in d or "timeout" in d or "timed out" in d:
        return f"{name} is busy or rate-limited right now. Try again shortly."
    return f"Couldn't send to {platform}. Please try again in a moment."


async def _refresh_if_expired(
    db: AsyncSession, account: SocialAccount
) -> str:
    """Return a usable plaintext access token, refreshing if needed.

    Raises SocialTokenExpiredError when the token is known-expired and cannot be
    refreshed (no refresh token, or the refresh call failed). Previously this
    swallowed refresh failures and returned the *expired* token, which then 401s
    at the platform API and records the draft as a vague `failed` — hiding the
    real fix (reconnect the account). See the 2026-07-03 incident writeup.

    Note on concurrency: callers MUST load `account` with `SELECT ... FOR UPDATE`
    so two simultaneous sends for the same account serialize here. Platform
    refresh tokens (e.g. Twitter/X) are single-use and rotate on every refresh;
    without the row lock, two sends read the same refresh token, both refresh,
    only one rotation persists, and the loser's stored refresh token goes stale.
    """
    access_token = decrypt_token(account.access_token)
    now = datetime.now(timezone.utc)

    # Token has a known expiry that's still in the future — use it as-is.
    if account.token_expires_at and account.token_expires_at > now:
        return access_token

    # `is_expired` = we are CONFIDENT the token is dead (expiry set and in the
    # past). A null expiry means "unknown" — we still try to refresh, but we do
    # NOT hard-fail on it, so accounts with valid-but-undated tokens keep working.
    is_expired = account.token_expires_at is not None and account.token_expires_at <= now

    if not account.token_expires_at:
        logger.info(
            "token_expiry_unknown_refreshing",
            account_id=str(account.id),
            platform=account.platform.value,
        )

    refresh_token = decrypt_token(account.refresh_token) if account.refresh_token else None
    if not refresh_token:
        if is_expired:
            logger.warning(
                "token_expired_no_refresh",
                account_id=str(account.id),
                platform=account.platform.value,
            )
            raise SocialTokenExpiredError(account.platform.value, account.username)
        # Unknown expiry, no refresh token — let the API decide.
        return access_token

    service = get_platform_service(account.platform)
    try:
        new_tokens = await service.refresh_tokens(refresh_token)
    except Exception as exc:
        error_detail = _http_error_detail(exc)
        logger.exception(
            "token_refresh_failed",
            account_id=str(account.id),
            platform=account.platform.value,
            error_detail=error_detail,
        )
        if is_expired:
            raise SocialTokenExpiredError(account.platform.value, account.username) from exc
        # Unknown expiry and refresh failed — fall back to the existing token.
        return access_token

    # Persist the rotated tokens, then commit — which also releases the row's
    # FOR UPDATE lock. A concurrent send that was BLOCKED on its own
    # `SELECT ... FOR UPDATE` for this account now unblocks and RE-READS the row
    # (READ COMMITTED), so it sees the freshly-rotated refresh token and the new
    # future expiry. Its expiry check (which always runs after the locked read)
    # then returns early without a second refresh — so the single-use refresh
    # token is never consumed twice. Correctness relies on expiry being
    # evaluated only after the FOR UPDATE read; keep it that way.
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


def mint_attribution_tag(content: str, site: Site) -> tuple[str, str | None, str]:
    """Rewrite a SITE-OWNED link in `content` with a fresh attribution tag.

    Returns `(content, tag_or_None, reason)` where reason is `minted` or `none`.
    Pure apart from the random tag: no DB, no network.

    Two hard rules:

    - **A link is NEVER appended.** If the approved text contains no site-owned
      link there is nothing to tag, so the content comes back byte-identical with
      `("none")`. Adding a link would change what a human approved into something
      they never saw.
    - **Ownership is HOST EQUALITY, never a substring match.** `_host_of` (shared
      with the detection scanner) normalizes and strips `www.`; a substring test
      would tag `evil-example.com.attacker.net` as belonging to `example.com`.

    Only the FIRST site-owned link is rewritten — one tag per posted reply is
    what the attribution row models, and tagging several would make the ROI read
    ambiguous.
    """
    site_host = _host_of(site.url or "")
    if not site_host:
        return content, None, "none"

    for match in _URL_RE.finditer(content):
        # Trailing sentence punctuation is not part of the URL.
        raw = match.group(0).rstrip(".,;:!?)]}\"'")
        if _host_of(raw) != site_host:
            continue
        tag = make_utm_tag()
        sep = "&" if "?" in raw else "?"
        tagged = f"{raw}{sep}utm_source={tag}"
        return content.replace(raw, tagged, 1), tag, "minted"

    return content, None, "none"


async def send_draft(db: AsyncSession, draft: Draft) -> bool:
    """Send an approved draft to the platform.

    Returns True if sent successfully, False on an ordinary send failure.
    Raises SocialTokenExpiredError when the account must be reconnected — the
    draft is marked `failed` first, then the error propagates so the caller can
    show the user an actionable "reconnect" message.
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
            draft.failure_reason = "The original post is no longer available."
            await db.commit()
            return False

        # Load the social account FOR UPDATE so concurrent sends for the same
        # account serialize through the token refresh below (single-use refresh
        # token race — see _refresh_if_expired). On SQLite the clause is a no-op.
        result = await db.execute(
            select(SocialAccount)
            .where(SocialAccount.id == post.social_account_id)
            .with_for_update()
        )
        account = result.scalar_one_or_none()
        if not account:
            logger.error("send_draft_account_not_found", draft_id=str(draft.id))
            draft.status = DraftStatus.failed
            draft.failure_reason = (
                f"Your {draft.platform.value} account is no longer connected. "
                "Reconnect it in Social Accounts."
            )
            await db.commit()
            return False

        # Refresh token if expired before attempting to send. A dead-token
        # situation raises SocialTokenExpiredError: mark the draft failed, then
        # re-raise so the caller surfaces a "reconnect" message.
        try:
            access_token = await _refresh_if_expired(db, account)
        except SocialTokenExpiredError as exc:
            draft.status = DraftStatus.failed
            draft.failure_reason = str(exc)
            await db.commit()
            raise

        # ─── Server-side attribution mint (Phase 1, Step C) ───
        # Runs BEFORE post_comment because the tag has to be inside the posted
        # text. The attribution row is only STAGED here; it commits below in the
        # same transaction as status=sent, so a failed post leaves no orphan row.
        #
        # FAIL-CLOSED on a NULL site_id: with no site key there is no
        # EngagementAttribution.site_id to write (the column is NOT NULL) and no
        # way to know whose site a link belongs to, so the mint is skipped
        # entirely rather than guessed.
        attribution_reason = "no_site"
        if draft.site_id:
            site = (
                await db.execute(select(Site).where(Site.site_id == draft.site_id))
            ).scalar_one_or_none()
            if site is None:
                attribution_reason = "no_site"
            else:
                new_content, utm_tag, attribution_reason = mint_attribution_tag(
                    content, site
                )
                if utm_tag:
                    # Post-rewrite length re-validation. ai_reply truncates to the
                    # cap at GENERATION time using raw len(); the utm parameter
                    # makes the string longer, and sender posts verbatim. Over the
                    # cap we send the ORIGINAL rather than mutate past it — never
                    # truncate a human-approved reply, never fail the send.
                    limit = CHAR_LIMITS.get(draft.platform)
                    if limit is not None and len(new_content) > limit:
                        attribution_reason = "skipped_length"
                    else:
                        content = new_content
                        EngagementTracker(db).stage_engagement(
                            user_id=draft.user_id,
                            site_id=draft.site_id,
                            platform=draft.platform.value,
                            engagement_type="comment",
                            utm_tag=utm_tag,
                            post_url=post.post_url,
                            draft_id=draft.id,
                        )
        # The posted text may now differ from the human-approved text. That is a
        # real (declared) contract change, so it is never silent.
        logger.info(
            "attribution_link_rewritten",
            draft_id=str(draft.id),
            reason=attribution_reason,
        )

        service = get_platform_service(draft.platform)
        try:
            comment_id = await service.post_comment(
                access_token, post.platform_post_id, content
            )
            draft.status = DraftStatus.sent
            draft.sent_at = datetime.now(timezone.utc)
            draft.failure_reason = None  # clear any reason from a prior failed try
            post.commented = True
            # Persist the platform's id for this reply in the SAME transaction as
            # status=sent — the join key every downstream outcome depends on.
            # A falsy id leaves the column NULL and logs: telemetry must never
            # fail a post that actually succeeded.
            if comment_id:
                draft.platform_comment_id = str(comment_id)[:64]
            else:
                logger.warning(
                    "draft_sent_without_comment_id", draft_id=str(draft.id)
                )
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
            draft.failure_reason = _friendly_send_error(
                error_detail, draft.platform.value
            )
            await db.commit()
            return False

    logger.warning("send_draft_no_target", draft_id=str(draft.id))
    draft.status = DraftStatus.failed
    draft.failure_reason = "This draft has nothing to reply to."
    await db.commit()
    return False
