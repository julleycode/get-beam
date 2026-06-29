"""Legacy auth router — kept for backward compatibility.

New code should use apps.api.dependencies.get_current_user which
supports both Clerk (RS256) and legacy HS256 tokens.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.database import get_db
from apps.api.models.user import User
from apps.api.schemas.auth import LoginRequest, Token, UserCreate, UserOut
from apps.api.schemas.preferences import WidgetLayoutResponse, WidgetLayoutUpdate
from apps.api.services.auth import (
    authenticate_user,
    create_access_token,
    get_user_by_email,
    hash_password,
)
from apps.api.dependencies import get_current_user

router = APIRouter()


@router.post("/signup", response_model=Token)
async def signup(body: UserCreate, db: AsyncSession = Depends(get_db)) -> Token:
    # Legacy email/password signup is a dev/test-only convenience. In production
    # Clerk is the sole signup path; this endpoint bypassed the invite gate and
    # created accounts orphaned from Clerk, so it is disabled there.
    if settings.app_env == "production":
        raise HTTPException(status_code=404, detail="Not found")

    existing = await get_user_by_email(db, body.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    return Token(access_token=token)


@router.post("/login", response_model=Token)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> Token:
    user = await authenticate_user(db, body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(user.id)
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
async def get_me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.get("/widget-layout", response_model=WidgetLayoutResponse)
async def get_widget_layout(
    surface: str = Query("visitors", max_length=50),
    user: User = Depends(get_current_user),
) -> WidgetLayoutResponse:
    """The caller's saved widget order for a dashboard surface (None = default)."""
    layouts = user.dashboard_layout or {}
    return WidgetLayoutResponse(surface=surface, layout=layouts.get(surface))


@router.put("/widget-layout", response_model=WidgetLayoutResponse)
async def put_widget_layout(
    body: WidgetLayoutUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WidgetLayoutResponse:
    """Persist the caller's widget order for one surface. Merges into the JSONB
    map so other surfaces are untouched; written via UPDATE so it doesn't depend
    on the user being attached to this request's session."""
    layouts = dict(user.dashboard_layout or {})
    layouts[body.surface] = body.layout
    await db.execute(
        update(User).where(User.id == user.id).values(dashboard_layout=layouts)
    )
    await db.commit()
    return WidgetLayoutResponse(surface=body.surface, layout=body.layout)
