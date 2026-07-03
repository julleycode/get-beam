"""Connect-Gmail OAuth router (send campaign email from the owner's Gmail).

Mirrors the social OAuth flow (routers/social_auth.py): /connect starts consent,
/callback stores the encrypted tokens on an EmailSenderAccount, plus /status and
/disconnect for the dashboard. Mounted at /api/v1/email.
"""

import uuid
from urllib.parse import urlencode

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.dependencies import get_current_user
from apps.api.models.database import get_db
from apps.api.models.email_sender_account import EmailSenderAccount
from apps.api.models.user import User
from apps.api.schemas.accounts import ConnectResponse
from apps.api.services.email_providers import gmail
from apps.api.services.encryption import encrypt_token
from apps.api.services.oauth_state import store_oauth_state, validate_oauth_state

logger = structlog.get_logger()

router = APIRouter(tags=["email-sender"])

# Where the callback bounces the browser back to (the Connect card lives on the
# campaigns page).
_RETURN_PATH = "/dashboard/campaigns"


@router.get("/status")
async def sender_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Whether the caller has a connected Gmail, and which address."""
    sender = (
        await db.execute(
            select(EmailSenderAccount).where(
                EmailSenderAccount.user_id == user.id,
                EmailSenderAccount.provider == "google",
                EmailSenderAccount.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    return {
        "connected": sender is not None,
        "email": sender.email if sender else None,
        "configured": gmail.is_configured(),
    }


@router.get("/connect/google", response_model=ConnectResponse)
async def connect_google(
    user: User = Depends(get_current_user),
) -> ConnectResponse:
    if not gmail.is_configured():
        raise HTTPException(
            status_code=400,
            detail=(
                "Gmail sending is not configured on this server "
                "(GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET missing)."
            ),
        )
    state = uuid.uuid4().hex
    await store_oauth_state(state, str(user.id))
    return ConnectResponse(auth_url=gmail.build_auth_url(state))


@router.get("/callback/google")
async def google_callback(
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
    db: AsyncSession = Depends(get_db),
):
    frontend_url = settings.frontend_url

    def _redirect(**params: str) -> RedirectResponse:
        return RedirectResponse(f"{frontend_url}{_RETURN_PATH}?{urlencode(params)}")

    if error:
        return _redirect(gmail_error=error_description or error)
    if not code:
        return _redirect(gmail_error="No authorization code received")

    user_id_str = await validate_oauth_state(state)
    if not user_id_str:
        logger.warning("gmail_oauth_state_invalid", state=state)
        return _redirect(gmail_error="Invalid or expired state. Please try again.")

    user = (
        await db.execute(select(User).where(User.id == uuid.UUID(user_id_str)))
    ).scalar_one_or_none()
    if not user:
        return _redirect(gmail_error="User not found. Please log in again.")

    try:
        tokens = await gmail.exchange_code(code)
    except gmail.GmailOAuthError as exc:
        logger.exception("gmail_oauth_exchange_failed", error=str(exc))
        return _redirect(gmail_error="Failed to connect Gmail. Please try again.")

    if not tokens.email:
        return _redirect(gmail_error="Could not read the Gmail address. Please try again.")

    encrypted_access = encrypt_token(tokens.access_token)
    encrypted_refresh = encrypt_token(tokens.refresh_token) if tokens.refresh_token else None

    existing = (
        await db.execute(
            select(EmailSenderAccount).where(
                EmailSenderAccount.user_id == user.id,
                EmailSenderAccount.provider == "google",
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.email = tokens.email
        existing.access_token = encrypted_access
        # A refresh token only comes back on first consent — keep the old one if
        # Google omitted it this time.
        if encrypted_refresh:
            existing.refresh_token = encrypted_refresh
        existing.token_expires_at = tokens.expires_at
        existing.scopes = tokens.scopes
        existing.is_active = True
    else:
        db.add(
            EmailSenderAccount(
                id=uuid.uuid4(),
                user_id=user.id,
                provider="google",
                email=tokens.email,
                access_token=encrypted_access,
                refresh_token=encrypted_refresh,
                token_expires_at=tokens.expires_at,
                scopes=tokens.scopes,
                is_active=True,
            )
        )

    await db.commit()
    return _redirect(gmail_connected=tokens.email)


@router.post("/disconnect")
async def disconnect_google(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    sender = (
        await db.execute(
            select(EmailSenderAccount).where(
                EmailSenderAccount.user_id == user.id,
                EmailSenderAccount.provider == "google",
            )
        )
    ).scalar_one_or_none()
    if sender is not None:
        sender.is_active = False
        await db.commit()
    return {"disconnected": True}
