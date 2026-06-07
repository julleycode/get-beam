"""Auth router: register, login, OAuth callbacks for each platform."""

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from jose import jwt
from passlib.context import CryptContext
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.dependencies import get_current_user
from apps.api.models.database import get_db
from apps.api.models.social_account import Platform, SocialAccount
from apps.api.models.user import User
from apps.api.schemas.accounts import ConnectResponse
from apps.api.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from apps.api.services.encryption import encrypt_token
from apps.api.services.oauth_state import store_oauth_state, validate_oauth_state
from apps.api.services.platforms import get_platform_service

logger = structlog.get_logger()

router = APIRouter(tags=["social-auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

from apps.api.services.rate_limiter import limiter


def _create_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


# ── Register / Login ─────────────────────────────────────

@router.post("/register", response_model=TokenResponse)
@limiter.limit("5/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    # Check for existing email explicitly to return 409 instead of 500
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        id=uuid.uuid4(),
        email=body.email,
        password_hash=pwd_context.hash(body.password),
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    return TokenResponse(access_token=_create_token(str(user.id)))


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not pwd_context.verify(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return TokenResponse(access_token=_create_token(str(user.id)))


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the current authenticated user."""
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        tone_preference=current_user.tone_preference,
    )


# ── OAuth: initiate connection ───────────────────────────

# Map platforms to the required config fields
_PLATFORM_CREDENTIALS = {
    Platform.twitter: ("twitter_client_id", "twitter_client_secret"),
    Platform.facebook: ("facebook_app_id", "facebook_app_secret"),
    Platform.instagram: ("facebook_app_id", "facebook_app_secret"),  # IG uses FB app
    Platform.linkedin: ("linkedin_client_id", "linkedin_client_secret"),
    Platform.tiktok: ("tiktok_client_key", "tiktok_client_secret"),
}


@router.get("/connect/{platform}", response_model=ConnectResponse)
async def connect_platform(
    platform: Platform,
    current_user: User = Depends(get_current_user),
):
    # Validate credentials are configured before sending user to OAuth
    if not settings.mock_social_oauth:
        required_fields = _PLATFORM_CREDENTIALS.get(platform, ())
        missing = [f for f in required_fields if not getattr(settings, f, "")]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot connect to {platform.value}: missing credentials "
                    f"({', '.join(missing)}). Add them to your .env file."
                ),
            )

    service = get_platform_service(platform)
    state = uuid.uuid4().hex

    # Store state with user_id for CSRF validation on callback
    await store_oauth_state(state, str(current_user.id))

    auth_url = await service.get_auth_url(state)
    return ConnectResponse(auth_url=auth_url)


# ── OAuth: callbacks ─────────────────────────────────────

@router.get("/callback/{platform}")
async def oauth_callback(
    platform: Platform,
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
    db: AsyncSession = Depends(get_db),
):
    frontend_url = settings.frontend_url

    # Handle OAuth denial / errors from provider
    if error:
        params = urlencode({"error": error_description or error, "platform": platform.value})
        return RedirectResponse(f"{frontend_url}/dashboard/social-accounts/callback?{params}")

    if not code:
        params = urlencode({"error": "No authorization code received", "platform": platform.value})
        return RedirectResponse(f"{frontend_url}/dashboard/social-accounts/callback?{params}")

    # Validate OAuth state (CSRF protection) and retrieve the user who started the flow
    user_id_str = await validate_oauth_state(state)
    if not user_id_str:
        logger.warning("oauth_state_invalid", platform=platform.value, state=state)
        params = urlencode({
            "error": "Invalid or expired OAuth state. Please try connecting again.",
            "platform": platform.value,
        })
        return RedirectResponse(f"{frontend_url}/dashboard/social-accounts/callback?{params}")

    # Look up the user who initiated this OAuth flow
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id_str)))
    user = result.scalar_one_or_none()
    if not user:
        params = urlencode({"error": "User not found. Please log in again.", "platform": platform.value})
        return RedirectResponse(f"{frontend_url}/dashboard/social-accounts/callback?{params}")

    service = get_platform_service(platform)
    try:
        tokens = await service.exchange_code(code, state=state)
    except Exception as e:
        logger.exception("oauth_exchange_failed", platform=platform.value, error=str(e))
        params = urlencode({
            "error": f"Failed to connect {platform.value}. Please try again.",
            "platform": platform.value,
        })
        return RedirectResponse(f"{frontend_url}/dashboard/social-accounts/callback?{params}")

    # Encrypt tokens before storing
    encrypted_access = encrypt_token(tokens.access_token)
    encrypted_refresh = encrypt_token(tokens.refresh_token) if tokens.refresh_token else None

    # Check if this account is already connected
    existing = await db.execute(
        select(SocialAccount).where(
            SocialAccount.platform == platform,
            SocialAccount.platform_user_id == tokens.platform_user_id,
            SocialAccount.user_id == user.id,
        )
    )
    account = existing.scalar_one_or_none()

    if account:
        # Update tokens
        account.access_token = encrypted_access
        account.refresh_token = encrypted_refresh
        account.token_expires_at = tokens.expires_at
        account.is_active = True
    else:
        account = SocialAccount(
            id=uuid.uuid4(),
            user_id=user.id,
            platform=platform,
            platform_user_id=tokens.platform_user_id,
            username=tokens.username,
            access_token=encrypted_access,
            refresh_token=encrypted_refresh,
            token_expires_at=tokens.expires_at,
            scopes=tokens.scopes,
        )
        db.add(account)

    await db.commit()

    # Redirect to frontend with success
    params = urlencode({
        "success": "true",
        "platform": platform.value,
        "username": tokens.username,
    })
    return RedirectResponse(f"{frontend_url}/dashboard/social-accounts/callback?{params}")
