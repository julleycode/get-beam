"""Referral program — "give quota, get quota".

An existing customer shares their referral link; when the referred company
signs up AND their pixel records real events (the anti-fraud activation bar,
checked by services/referral_activation), BOTH sides earn a permanent
+REFERRAL_BONUS_PER_ACTIVATION identified-visitors/month, capped at
REFERRAL_BONUS_CAP. No cash rewards — quota only, so the program attracts
users, not bounty farmers.

Anti-enumeration: claim failures (unknown code, self-referral, already
referred elsewhere, stale account) all return the same generic 404, mirroring
the waitlist consume-invite contract.
"""

import secrets
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.dependencies import get_current_user
from apps.api.models.database import get_db
from apps.api.models.user import User
from apps.api.schemas.referrals import (
    ClaimReferralRequest,
    ClaimReferralResponse,
    ReferralEntry,
    ReferralInfoResponse,
    ValidateReferralResponse,
)
from apps.api.services.billing import (
    REFERRAL_BONUS_CAP,
    REFERRAL_BONUS_PER_ACTIVATION,
)
from apps.api.services.pii import mask_email

logger = structlog.get_logger()

router = APIRouter()

# A claim must come from a genuinely NEW account: an old account "claiming" a
# code is quota farming, not a referral. Window matches "signed up via the link
# and got around to the dashboard".
CLAIM_WINDOW_DAYS = 7

# Unambiguous lowercase alphabet (no 0/o/1/l/i) — the code is read aloud and
# retyped, not just clicked.
_CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_CODE_LENGTH = 8


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


async def _ensure_referral_code(db: AsyncSession, user: User) -> str:
    """Return the user's referral code, generating it on first use.

    The unique index is the real guard; on the (astronomically rare) collision
    we retry with a fresh code.
    """
    if user.referral_code:
        return user.referral_code
    for _ in range(3):
        user.referral_code = _generate_code()
        try:
            await db.commit()
            return user.referral_code
        except IntegrityError:
            await db.rollback()
            # Refresh the row we're mutating after rollback expired it.
            user = (
                await db.execute(select(User).where(User.id == user.id))
            ).scalar_one()
            if user.referral_code:  # lost a race against ourselves — fine
                return user.referral_code
    raise HTTPException(status_code=500, detail="Could not generate referral code")


@router.get("/me", response_model=ReferralInfoResponse)
async def get_my_referral_info(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReferralInfoResponse:
    """The caller's referral code, share link, earned bonus, and referral list."""
    code = await _ensure_referral_code(db, user)

    referred = (
        (
            await db.execute(
                select(User)
                .where(User.referred_by_user_id == user.id)
                .order_by(User.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    entries = [
        ReferralEntry(
            email_masked=mask_email(r.email) or "",
            status="activated" if r.referral_activated_at else "pending",
            signed_up_at=r.created_at,
            activated_at=r.referral_activated_at,
        )
        for r in referred
    ]
    return ReferralInfoResponse(
        code=code,
        link=f"{settings.frontend_url}/signup?ref={code}",
        bonus_monthly_quota=min(user.bonus_monthly_quota, REFERRAL_BONUS_CAP),
        bonus_cap=REFERRAL_BONUS_CAP,
        bonus_per_activation=REFERRAL_BONUS_PER_ACTIVATION,
        referred_count=len(entries),
        activated_count=sum(1 for e in entries if e.status == "activated"),
        referrals=entries,
    )


@router.get("/validate", response_model=ValidateReferralResponse)
async def validate_referral(
    code: str = "",
    db: AsyncSession = Depends(get_db),
) -> ValidateReferralResponse:
    """Public: check a referral code for the signup-page banner. No auth (runs
    before the account exists); returns only the referrer's display name, never
    their email."""
    code = code.strip().lower()
    if not code:
        return ValidateReferralResponse(valid=False)
    referrer = (
        await db.execute(select(User).where(User.referral_code == code))
    ).scalar_one_or_none()
    if referrer is None or not referrer.is_active:
        return ValidateReferralResponse(valid=False)
    return ValidateReferralResponse(
        valid=True, referrer_name=referrer.full_name or "A Beam user"
    )


@router.post("/claim", response_model=ClaimReferralResponse)
async def claim_referral(
    body: ClaimReferralRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClaimReferralResponse:
    """Link the (new) authenticated account to its referrer.

    Called from the dashboard right after signup. Idempotent for retries with
    the same code. The reward itself lands later, when the activation job sees
    real pixel events for this account.
    """
    not_found = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Referral not found"
    )
    code = body.code.strip().lower()
    if not code:
        raise not_found

    referrer = (
        await db.execute(select(User).where(User.referral_code == code))
    ).scalar_one_or_none()
    if referrer is None:
        raise not_found
    if referrer.id == user.id:
        logger.info("referral_self_claim_blocked", user_id=str(user.id))
        raise not_found

    if user.referred_by_user_id is not None:
        if user.referred_by_user_id == referrer.id:
            return ClaimReferralResponse(claimed=True)  # retry — idempotent
        logger.info("referral_reclaim_blocked", user_id=str(user.id))
        raise not_found

    created_at = user.created_at
    if created_at is not None and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if created_at is not None and datetime.now(timezone.utc) - created_at > timedelta(
        days=CLAIM_WINDOW_DAYS
    ):
        logger.info("referral_stale_account_blocked", user_id=str(user.id))
        raise not_found

    user.referred_by_user_id = referrer.id
    await db.commit()
    logger.info(
        "referral_claimed",
        referee_id=str(user.id),
        referrer_id=str(referrer.id),
    )
    return ClaimReferralResponse(claimed=True)
