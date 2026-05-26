"""Shared FastAPI dependencies -- authentication, rate limiting."""

import uuid
from typing import Optional

import httpx
import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.database import get_db
from apps.api.models.user import User

logger = structlog.get_logger()

_bearer = HTTPBearer(auto_error=False)

# Cache Clerk JWKS keys in memory
_clerk_jwks: Optional[dict] = None


async def _get_clerk_jwks() -> dict:
    """Fetch Clerk's JWKS (JSON Web Key Set) for verifying tokens."""
    global _clerk_jwks
    if _clerk_jwks is not None:
        return _clerk_jwks

    pk = settings.clerk_publishable_key
    if pk.startswith("pk_test_") or pk.startswith("pk_live_"):
        import base64

        prefix = "pk_test_" if pk.startswith("pk_test_") else "pk_live_"
        encoded = pk.replace(prefix, "").rstrip(".")
        # Add padding
        encoded += "=" * (4 - len(encoded) % 4) if len(encoded) % 4 else ""
        frontend_api = base64.b64decode(encoded).decode("utf-8").rstrip("$")
    else:
        raise ValueError("Invalid Clerk publishable key format")

    jwks_url = f"https://{frontend_api}/.well-known/jwks.json"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(jwks_url)
        resp.raise_for_status()
        _clerk_jwks = resp.json()
        return _clerk_jwks


async def _verify_clerk_token(token: str) -> dict:
    """Verify a Clerk JWT and return its claims."""
    jwks = await _get_clerk_jwks()
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")

        rsa_key = None
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                rsa_key = key
                break

        if rsa_key is None:
            # JWKS might be stale, clear cache and retry once
            global _clerk_jwks
            _clerk_jwks = None
            jwks = await _get_clerk_jwks()
            for key in jwks.get("keys", []):
                if key.get("kid") == kid:
                    rsa_key = key
                    break

        if rsa_key is None:
            raise JWTError("No matching key found in Clerk JWKS")

        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
        return payload
    except JWTError:
        raise


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Decode JWT from Authorization header and return the authenticated User.

    Supports both Clerk JWTs (RS256) and legacy self-issued JWTs (HS256).
    Raises 401 if the token is missing, expired, or the user no longer exists.
    """
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = creds.credentials

    # Try Clerk verification first (if Clerk is configured)
    if settings.clerk_secret_key:
        try:
            payload = await _verify_clerk_token(token)
            clerk_user_id = payload.get("sub")
            if not clerk_user_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid Clerk token: no sub claim",
                )

            result = await db.execute(
                select(User).where(User.clerk_user_id == clerk_user_id)
            )
            user = result.scalar_one_or_none()

            if user is None:
                # Auto-create user on first Clerk API call
                email = payload.get(
                    "email",
                    payload.get("email_address", f"{clerk_user_id}@clerk.user"),
                )
                # Check if email already exists (user registered before Clerk)
                result = await db.execute(select(User).where(User.email == email))
                user = result.scalar_one_or_none()
                if user:
                    # Link existing user to Clerk
                    user.clerk_user_id = clerk_user_id
                    await db.commit()
                else:
                    user = User(
                        id=uuid.uuid4(),
                        email=email,
                        clerk_user_id=clerk_user_id,
                        tone_preference="casual",
                    )
                    db.add(user)
                    await db.commit()
                    logger.info(
                        "clerk_user_auto_created",
                        clerk_id=clerk_user_id,
                        email=email,
                    )

            return user

        except JWTError:
            # Check if the token was intended for Clerk (RS256 header).
            # If so, don't fall through to legacy HS256 — it's a bad Clerk token.
            try:
                header = jwt.get_unverified_header(token)
                if header.get("alg") == "RS256":
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid or expired Clerk token",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
            except JWTError:
                pass  # Can't parse header — fall through to legacy
        except HTTPException:
            raise
        except Exception:
            logger.exception("clerk_token_verification_failed")
            # Fall through to legacy verification

    # Legacy JWT verification (self-issued HS256 tokens)
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        user_id: Optional[str] = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user
