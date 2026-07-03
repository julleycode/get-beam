"""Accounts router: list and manage connected social media accounts."""

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_current_user
from apps.api.models.database import get_db
from apps.api.models.social_account import Platform, SocialAccount
from apps.api.models.user import User
from apps.api.schemas.accounts import (
    DisconnectResponse,
    LinkedInOutreachConnectRequest,
    LinkedInOutreachConnectResponse,
    LinkedInOutreachStatusResponse,
    SocialAccountResponse,
)
from apps.api.services.phantommm_client import (
    PhantommmClient,
    PhantommmError,
    PhantommmNotConfigured,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("/", response_model=list[SocialAccountResponse])
async def list_accounts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List connected social media accounts for the authenticated user."""
    result = await db.execute(
        select(SocialAccount).where(
            SocialAccount.user_id == current_user.id,
            SocialAccount.is_active.is_(True),
        )
    )
    accounts = result.scalars().all()
    return [
        SocialAccountResponse(
            id=str(a.id),
            platform=a.platform,
            username=a.username,
            platform_user_id=a.platform_user_id,
            is_active=a.is_active,
            token_expires_at=a.token_expires_at,
            created_at=a.created_at,
            is_outreach=a.outreach_connection_id is not None,
        )
        for a in accounts
    ]


@router.delete("/{account_id}", response_model=DisconnectResponse)
async def disconnect_account(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Disconnect (deactivate) a social media account. Only the owner can disconnect."""
    result = await db.execute(
        select(SocialAccount).where(
            SocialAccount.id == account_id,
            SocialAccount.user_id == current_user.id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    account.is_active = False
    await db.commit()
    return DisconnectResponse(message=f"Disconnected {account.platform.value} account")


@router.post("/twitter/browser-login")
async def setup_twitter_browser_login(
    current_user: User = Depends(get_current_user),
):
    """Launch a headed browser for the user to log into Twitter.

    This saves session cookies so the app can post replies via browser
    automation (bypassing Free-tier API limitations on replies).
    """
    from apps.api.services.platforms.twitter_browser import (
        TwitterBrowserPoster,
        TwitterBrowserError,
    )

    poster = TwitterBrowserPoster()
    try:
        await poster.setup_login()
        return {"message": "Twitter browser session saved successfully"}
    except TwitterBrowserError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


async def _get_linkedin_outreach_account(
    db: AsyncSession, user_id
) -> SocialAccount | None:
    """Return the caller's active LinkedIn SocialAccount, if any."""
    result = await db.execute(
        select(SocialAccount).where(
            SocialAccount.user_id == user_id,
            SocialAccount.platform == Platform.linkedin,
            SocialAccount.is_active.is_(True),
        )
    )
    return result.scalars().first()


@router.post(
    "/linkedin/outreach-connect",
    response_model=LinkedInOutreachConnectResponse,
)
async def connect_linkedin_outreach(
    body: LinkedInOutreachConnectRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LinkedInOutreachConnectResponse:
    """Register a LinkedIn session cookie with the phantommm sidecar.

    Beam NEVER stores the raw LinkedIn cookie — it is POSTed to phantommm (which
    stores it encrypted) and Beam keeps only the opaque connection id. The cookie
    / user agent are secrets and are never logged or returned.
    """
    try:
        client = PhantommmClient()
    except PhantommmNotConfigured:
        raise HTTPException(
            status_code=503, detail="LinkedIn outreach not configured"
        )

    try:
        connection = await client.register_linkedin_connection(
            session_cookie=body.session_cookie,
            user_agent=body.user_agent,
            label=body.label,
        )
    except PhantommmError:
        # Do not surface phantommm internals (may echo cookie/UA context).
        raise HTTPException(
            status_code=502,
            detail="Could not register your LinkedIn session — check the cookie and try again",
        )

    connection_id = str(connection["id"])

    # Optionally verify so we can show the account owner's name.
    verified_name: str | None = None
    try:
        result = await client.verify_connection(connection_id)
        if result.get("valid"):
            verified_name = result.get("name") or None
    except PhantommmError:
        # Verification is best-effort; the connection is still stored.
        logger.info("linkedin_outreach_verify_skipped", user_id=str(current_user.id))

    # Upsert the caller's LinkedIn SocialAccount row, storing ONLY the opaque id.
    account = await _get_linkedin_outreach_account(db, current_user.id)
    if account is None:
        account = SocialAccount(
            user_id=current_user.id,
            platform=Platform.linkedin,
            # No OAuth identity for a cookie-registered outreach session — use the
            # phantommm connection id as the stable platform_user_id, and a
            # readable username (never the cookie).
            platform_user_id=f"outreach:{connection_id}",
            username=verified_name or body.label or "LinkedIn outreach",
            # access_token is NOT NULL; there is no OAuth token for this flow.
            access_token="",
            outreach_connection_id=connection_id,
        )
        db.add(account)
    else:
        account.outreach_connection_id = connection_id
        if verified_name:
            account.username = verified_name
    await db.commit()

    logger.info(
        "linkedin_outreach_connected",
        user_id=str(current_user.id),
        connection_id_present=True,
    )
    return LinkedInOutreachConnectResponse(
        connected=True,
        name=verified_name,
        connection_id_present=True,
    )


@router.get(
    "/linkedin/outreach-status",
    response_model=LinkedInOutreachStatusResponse,
)
async def linkedin_outreach_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LinkedInOutreachStatusResponse:
    """Report whether the caller has a usable LinkedIn outreach connection."""
    from apps.api.config import settings

    configured = bool(settings.phantommm_base_url and settings.phantommm_api_key)
    account = await _get_linkedin_outreach_account(db, current_user.id)
    return LinkedInOutreachStatusResponse(
        outreach_connected=bool(account and account.outreach_connection_id),
        configured=configured,
    )
