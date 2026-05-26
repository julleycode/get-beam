"""Accounts router: list and manage connected social media accounts."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_current_user
from apps.api.models.database import get_db
from apps.api.models.social_account import SocialAccount
from apps.api.models.user import User
from apps.api.schemas.accounts import DisconnectResponse, SocialAccountResponse

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
