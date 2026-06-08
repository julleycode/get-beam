"""Admin waitlist management endpoints."""

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_current_user
from apps.api.models.database import get_db
from apps.api.models.user import User
from apps.api.models.waitlist import WaitlistSignup
from apps.api.services.link_decorator import generate_bid
from apps.api.services.email_sender import EmailSender

logger = structlog.get_logger()

router = APIRouter(tags=["waitlist"])


@router.get("/")
async def list_waitlist(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List all waitlist signups (newest first)."""
    result = await db.execute(
        select(WaitlistSignup).order_by(WaitlistSignup.created_at.desc())
    )
    signups = result.scalars().all()

    # Counts by status
    count_result = await db.execute(
        select(
            WaitlistSignup.status,
            sa_func.count(WaitlistSignup.id),
        ).group_by(WaitlistSignup.status)
    )
    counts = {row[0]: row[1] for row in count_result.all()}

    return {
        "signups": [
            {
                "id": str(s.id),
                "email": s.email,
                "site_url": s.site_url,
                "status": s.status,
                "invite_token": s.invite_token,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "approved_at": s.approved_at.isoformat() if s.approved_at else None,
            }
            for s in signups
        ],
        "counts": {
            "pending": counts.get("pending", 0),
            "approved": counts.get("approved", 0),
            "granted": counts.get("granted", 0),
            "rejected": counts.get("rejected", 0),
        },
    }


@router.patch("/{signup_id}/approve")
async def approve_waitlist(
    signup_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Approve a waitlist signup — generates invite token and sends invite email."""
    result = await db.execute(
        select(WaitlistSignup).where(WaitlistSignup.id == signup_id)
    )
    signup = result.scalar_one_or_none()
    if not signup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signup not found")

    if signup.status == "approved":
        return {"status": "already_approved", "id": str(signup.id)}

    # Generate invite token using link_decorator
    try:
        invite_token = generate_bid(signup.email)
    except RuntimeError:
        # Fallback: use a UUID-based token if encryption key is not configured
        invite_token = str(uuid.uuid4())
        logger.warning("waitlist_approve_no_encryption_key", email=signup.email)

    signup.status = "approved"
    signup.invite_token = invite_token
    signup.approved_at = datetime.now(timezone.utc)
    await db.commit()

    # Send invite email
    try:
        sender = EmailSender()
        invite_url = f"https://getbeam.fyi/signup?invite={invite_token}"
        await sender.send(
            to_email=signup.email,
            subject="you're in — beam is ready for you",
            body_html=f"""
<div style="font-family: 'Inter', -apple-system, sans-serif; max-width: 520px; margin: 0 auto; color: #2b2530;">
  <p style="font-size: 16px; line-height: 1.7; color: #4a3f50;">hey there,</p>
  <p style="font-size: 16px; line-height: 1.7; color: #4a3f50;">
    you're in. your beam account is ready.
  </p>
  <p style="font-size: 16px; line-height: 1.7; color: #4a3f50;">
    click below to create your account and start seeing who's visiting your site.
  </p>
  <p style="margin: 28px 0;">
    <a href="{invite_url}"
       style="display: inline-block; padding: 14px 28px; background: #FF3366; color: white;
              text-decoration: none; border-radius: 10px; font-weight: 500; font-size: 15px;">
      set up your account &rarr;
    </a>
  </p>
  <p style="font-size: 14px; color: #b8a0a8;">
    this link is unique to you. don't share it.
  </p>
  <p style="font-size: 15px; line-height: 1.7; color: #FF3366; font-style: italic; margin-top: 24px;">
    &mdash; julley, beam
  </p>
</div>
""",
            from_name="Beam",
            from_email="hello@getbeam.fyi",
        )
        logger.info("waitlist_invite_sent", email=signup.email)
    except Exception as e:
        logger.warning("waitlist_invite_email_failed", email=signup.email, error=str(e))

    return {"status": "approved", "id": str(signup.id)}


@router.patch("/{signup_id}/grant")
async def grant_waitlist(
    signup_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Grant a beta slot — decrements the public slot counter.

    Does NOT send any email or invite to the user. Purely controls
    the landing page "X spots left" counter.
    """
    result = await db.execute(
        select(WaitlistSignup).where(WaitlistSignup.id == signup_id)
    )
    signup = result.scalar_one_or_none()
    if not signup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signup not found")

    if signup.status == "granted":
        return {"status": "already_granted", "id": str(signup.id)}

    signup.status = "granted"
    await db.commit()

    logger.info("waitlist_granted", email=signup.email)
    return {"status": "granted", "id": str(signup.id)}


@router.patch("/{signup_id}/reject")
async def reject_waitlist(
    signup_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reject a waitlist signup."""
    result = await db.execute(
        select(WaitlistSignup).where(WaitlistSignup.id == signup_id)
    )
    signup = result.scalar_one_or_none()
    if not signup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signup not found")

    signup.status = "rejected"
    await db.commit()

    logger.info("waitlist_rejected", email=signup.email)
    return {"status": "rejected", "id": str(signup.id)}


@router.delete("/{signup_id}")
async def delete_waitlist(
    signup_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Permanently delete a waitlist entry (for cleaning up test data)."""
    result = await db.execute(
        select(WaitlistSignup).where(WaitlistSignup.id == signup_id)
    )
    signup = result.scalar_one_or_none()
    if not signup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signup not found")

    email = signup.email
    await db.delete(signup)
    await db.commit()

    logger.info("waitlist_deleted", email=email)
    return {"status": "deleted", "id": str(signup_id)}
