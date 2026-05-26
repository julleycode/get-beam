"""Legacy auth router — kept for backward compatibility.

New code should use apps.api.dependencies.get_current_user which
supports both Clerk (RS256) and legacy HS256 tokens.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.database import get_db
from apps.api.models.user import User
from apps.api.schemas.auth import LoginRequest, Token, UserCreate, UserOut
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
