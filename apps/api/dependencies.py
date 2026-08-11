"""Shared FastAPI dependencies -- authentication, rate limiting."""

import uuid
from typing import Optional

import httpx
import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.database import get_db
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.models.waitlist import WaitlistSignup
from apps.api.services.pii import mask_email
from apps.api.services.reengagement import record_user_activity

logger = structlog.get_logger()

_bearer = HTTPBearer(auto_error=False)

# Cache Clerk JWKS keys in memory
_clerk_jwks: Optional[dict] = None


async def verify_site_access(db: AsyncSession, site_id: str, user: User) -> Site:
    """Return the Site iff it exists AND belongs to ``user``; else 404.

    404 (not 403) so we never leak which site_ids exist. The single shared
    site-ownership check for every site-scoped router (was copy-pasted as
    per-router _verify_site_access / _owned_site helpers).
    """
    site = (
        await db.execute(
            select(Site).where(Site.site_id == site_id, Site.user_id == user.id)
        )
    ).scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


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


async def _fetch_clerk_profile(clerk_user_id: str) -> dict:
    """Fetch a user's profile (email, avatar, name) from the Clerk Backend API.

    Clerk's default session JWT does NOT carry an email claim, so without this
    every Clerk login falls back to a fabricated ``{id}@clerk.user`` address.
    That breaks the link-existing-user-by-email path below and orphans data
    when an instance changes (e.g. dev -> prod) and re-issues user ids.

    Returns {"email", "avatar_url", "full_name"} with None for anything that
    can't be resolved. avatar_url is set only when Clerk reports has_image=true
    (their generated gray fallback is skipped — our initials tiles look better).
    """
    profile: dict = {"email": None, "avatar_url": None, "full_name": None}
    if not settings.clerk_secret_key:
        return profile
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://api.clerk.com/v1/users/{clerk_user_id}",
                headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
            )
        if resp.status_code != 200:
            return profile
        data = resp.json()
        primary_id = data.get("primary_email_address_id")
        emails = data.get("email_addresses", []) or []
        for entry in emails:
            if entry.get("id") == primary_id and entry.get("email_address"):
                profile["email"] = entry["email_address"]
                break
        if not profile["email"]:
            # No primary flagged — fall back to the first verified address.
            for entry in emails:
                if entry.get("email_address"):
                    profile["email"] = entry["email_address"]
                    break
        if data.get("has_image") and data.get("image_url"):
            profile["avatar_url"] = data["image_url"]
        name = " ".join(
            p for p in [data.get("first_name"), data.get("last_name")] if p
        ).strip()
        profile["full_name"] = name or None
        return profile
    except Exception:
        logger.exception("clerk_profile_fetch_failed", clerk_id=clerk_user_id)
        return profile


async def _fetch_clerk_email(clerk_user_id: str) -> Optional[str]:
    """Back-compat shim: primary email only. See _fetch_clerk_profile."""
    return (await _fetch_clerk_profile(clerk_user_id))["email"]


async def _is_email_allowlisted(db: AsyncSession, email: str) -> bool:
    """True if the email has an approved/granted waitlist signup.

    Gates *new* account creation to invited users only. Existing users (matched
    earlier by clerk_user_id or by email) bypass this entirely — they are
    grandfathered in regardless of waitlist state.
    """
    result = await db.execute(
        select(WaitlistSignup.id).where(
            func.lower(WaitlistSignup.email) == email.lower(),
            WaitlistSignup.status.in_(["approved", "granted"]),
        )
    )
    return result.scalar_one_or_none() is not None


async def _send_welcome_email(email: str) -> None:
    """Greet a brand-new user the moment their Beam account is created.

    Fired once, from the genuinely-new-account branch of get_current_user, so
    each user gets exactly one welcome. Best-effort: any failure is logged and
    swallowed so a flaky SendGrid never blocks first login.
    """
    # ponytail: inline send blocks this one request until SendGrid replies
    # (~0.5s typical, 10s ceiling). Runs once per user lifetime, so the cost is
    # negligible. Move to BackgroundTasks if first-load latency ever matters.
    try:
        from apps.api.services.email_sender import EmailSender

        await EmailSender().send(
            to_email=email,
            subject="welcome to beam — here's step one",
            body_html="""
<div style="font-family: 'Inter', -apple-system, sans-serif; max-width: 520px; margin: 0 auto; color: #2b2530;">
  <p style="font-size: 16px; line-height: 1.7; color: #4a3f50;">hey,</p>
  <p style="font-size: 16px; line-height: 1.7; color: #4a3f50;">
    you're all set — your beam account is live. welcome aboard.
  </p>
  <p style="font-size: 16px; line-height: 1.7; color: #4a3f50;">
    one thing to do first: drop the beam pixel on your site. that's what lets us
    show you who's actually visiting — real people, real profiles, not just numbers.
  </p>
  <p style="margin: 28px 0;">
    <a href="https://getbeam.fyi/dashboard"
       style="display: inline-block; padding: 14px 28px; background: #FF3366; color: white;
              text-decoration: none; border-radius: 10px; font-weight: 500; font-size: 15px;">
      install the pixel &rarr;
    </a>
  </p>
  <p style="font-size: 16px; line-height: 1.7; color: #4a3f50;">
    once it's live, your visitors start showing up on the dashboard within minutes.
  </p>
  <p style="font-size: 16px; line-height: 1.7; color: #4a3f50;">
    stuck on anything? just reply to this email — i read every one.
  </p>
  <p style="font-size: 15px; line-height: 1.7; color: #FF3366; font-style: italic; margin-top: 24px;">
    &mdash; julley, beam
  </p>
</div>
""",
            from_name="Beam",
            from_email="hello@getbeam.fyi",
            branding=True,
        )
        logger.info("welcome_email_sent", email=mask_email(email))
    except Exception as e:
        logger.warning("welcome_email_failed", email=mask_email(email), error=str(e))


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
                # One-time Clerk API fetch: real email (prefer a JWT claim,
                # fabricate only as a last resort — the real email is what lets
                # us link to a pre-existing row instead of spawning a duplicate
                # when the user's id changes) plus avatar + display name.
                profile = await _fetch_clerk_profile(clerk_user_id)
                email = (
                    payload.get("email")
                    or payload.get("email_address")
                    or profile["email"]
                )
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
                    if profile["avatar_url"] and not user.avatar_url:
                        user.avatar_url = profile["avatar_url"]
                    if profile["full_name"] and not user.full_name:
                        user.full_name = profile["full_name"]
                    await db.commit()
                    logger.info(
                        "clerk_user_relinked",
                        clerk_id=clerk_user_id,
                        email=mask_email(email),
                    )
                else:
                    # Genuinely new account — enforce invite-only access when
                    # enabled. (Existing users were matched above and never
                    # reach here, so all current users are grandfathered in.)
                    if settings.invite_only and not await _is_email_allowlisted(
                        db, email
                    ):
                        logger.warning(
                            "clerk_signup_blocked_not_allowlisted",
                            clerk_id=clerk_user_id,
                            email=mask_email(email),
                        )
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Access is invite-only. Join the waitlist to request access.",
                        )
                    user = User(
                        id=uuid.uuid4(),
                        email=email,
                        clerk_user_id=clerk_user_id,
                        tone_preference="casual",
                        avatar_url=profile["avatar_url"],
                        full_name=profile["full_name"],
                    )
                    db.add(user)
                    await db.commit()
                    logger.info(
                        "clerk_user_auto_created",
                        clerk_id=clerk_user_id,
                        email=mask_email(email),
                    )
                    await _send_welcome_email(email)
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
                        # A rollback EXPIRES every attribute on `user`. Returning
                        # it as-is makes the downstream `user.id` / `user.is_admin`
                        # access trigger a *synchronous* lazy reload inside the
                        # async session -> sqlalchemy MissingGreenlet -> HTTP 500
                        # (which, being unhandled, also loses its CORS header and
                        # surfaces in the browser as "Failed to fetch"). Refresh
                        # repopulates the object via the async path.
                        await db.refresh(user)
                        logger.warning(
                            "clerk_user_email_backfill_conflict",
                            clerk_id=clerk_user_id,
                        )

            # Inactivity lifecycle: refresh last_active_at (hourly at most) and
            # silently resume anything the sweep auto-paused. Never raises, and
            # never uses this request's session.
            await record_user_activity(user)
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
    # Same activity touch on the legacy HS256 path (see the Clerk branch above).
    await record_user_activity(user)
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
