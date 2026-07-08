"""Pydantic schemas for the referral program."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ReferralEntry(BaseModel):
    """One referred account, as shown to the referrer. Email is masked —
    the referrer never sees the full address of someone else's account."""

    email_masked: str
    status: str  # "pending" | "activated"
    signed_up_at: Optional[datetime]
    activated_at: Optional[datetime]


class ReferralInfoResponse(BaseModel):
    code: str
    link: str
    bonus_monthly_quota: int
    bonus_cap: int
    bonus_per_activation: int
    referred_count: int
    activated_count: int
    referrals: list[ReferralEntry]


class ClaimReferralRequest(BaseModel):
    code: str


class ClaimReferralResponse(BaseModel):
    claimed: bool


class ValidateReferralResponse(BaseModel):
    valid: bool
    referrer_name: Optional[str] = None
