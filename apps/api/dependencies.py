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
from apps.api.services.pii import mask_email

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


async def _fetch_clerk_email(clerk_user_id: str) -> Optional[str]:
    """Fetch a user's primary email from the Clerk Backend API.

    Clerk's default session JWT does NOT carry an email claim, so without this
    every Clerk login falls back to a fabricated ``{id}@clerk.user`` address.
    That breaks the link-existing-user-by-email path below and orphans data
    when an instance changes (e.g. dev -> prod) and re-issues user ids.

    Returns the primary email address, or None if it can't be resolved.
    """
    if not settings.clerk_secret_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://api.clerk.com/v1/users/{clerk_user_id}",
                headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
            )
        if resp.status_code != 200:
            return None
        data = resp.json()
        primary_id = data.get("primary_email_address_id")
        emails = data.get("email_addresses", []) or []
        for entry in emails:
            if entry.get("id") == primary_id and entry.get("email_address"):
                return entry["email_address"]
        # No primary flagged — fall back to the first verified address.
        for entry in emails:
            if entry.get("email_address"):
                return entry["email_address"]
        return None
    except Exception:
        logger.exception("clerk_email_fetch_failed", clerk_id=clerk_user_id)
        return None


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
                # Resolve the real email: prefer a JWT claim, then the Clerk
                # Backend API, and only fabricate as a last resort. Having the
                # real email is what lets us link to a pre-existing row instead
                # of spawning a duplicate when the user's id changes.
                email = payload.get("email") or payload.get("email_address")
                if not email:
                    email = await _fetch_clerk_email(clerk_user_id)
                if not email:
                    email = f"{clerk_user_id}@clerk.user"

                # Check if email already exists (registered before Clerk, or
                # under a previous Clerk instance with a different user id).
                result = await db.execute(select(User).where(User.email == email))
                user = result.scalar_one_or_none()
                if user:
                    # Link existing user to Clerk (re-points the row at the
                    # current id, restoring access to all of their data).
                    user.clerk_user_id = clerk_user_id
                    await db.commit()
                    logger.info(
                        "clerk_user_relinked",
                        clerk_id=clerk_user_id,
                        email=mask_email(email),
                    )
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
                        email=mask_email(email),
                    )
            elif user.email.endswith("@clerk.user"):
                # Self-heal: an existing row created before this fix still has a
                # fabricated email. Backfill the real one so future logins (and
                # email-based features) work. Tolerate a unique-constraint clash.
                real_email = await _fetch_clerk_email(clerk_user_id)
                if real_email and real_email != user.email:
                    user.email = real_email
                    try:
                        await db.commit()
                        logger.info(
                            "clerk_user_email_backfilled",
                            clerk_id=clerk_user_id,
                            email=mask_email(real_email),
                        )
                    except Exception:
                        await db.rollback()
                        logger.warning(
                            "clerk_user_email_backfill_conflict",
                            clerk_id=clerk_user_id,
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
            settings.app_secret_key,
            algorithms=["HS256"],
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


async def require_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Require the authenticated user to have admin privileges.

    Raises 403 if the user is authenticated but not an admin.
    """
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
