import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.models.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    # Clerk-hosted profile image (img.clerk.com), set only when Clerk reports
    # has_image=true. Shown publicly on the landing founders wall.
    avatar_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    clerk_user_id: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    tone_preference: Mapped[str] = mapped_column(String(50), default="casual")
    is_active: Mapped[bool] = mapped_column(default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # ─── Billing fields ───
    # Billing provider is Gumroad. The historical stripe_* columns below are
    # reused to store external billing ids to avoid a migration.
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    plan: Mapped[str] = mapped_column(String(20), default="free", nullable=False, server_default="free")
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    subscription_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    monthly_identified_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    billing_cycle_reset_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # ─── Referral program ───
    # No separate referrals table: status is a single one-way transition
    # (pending → rewarded), so referral_activated_at IS the status column and
    # a conditional UPDATE on it is the race-proof idempotency gate.
    referral_code: Mapped[Optional[str]] = mapped_column(
        String(16), unique=True, index=True, nullable=True
    )  # generated lazily on first GET /referrals/me
    referred_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    referral_activated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # NULL = pending; set = referee activated and both sides were rewarded
    # Extra identified-visitors added to the monthly plan limit, earned via
    # referrals (+10 per activation, capped — see services/billing.py).
    bonus_monthly_quota: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )

    # ─── Inactivity lifecycle (re-engagement reminder + auto-pause) ───
    # Refreshed at most once an hour from get_current_user (see
    # services/reengagement.record_user_activity). NOT NULL with a now()
    # server_default: at migration time every existing user is seeded active, so
    # the earliest possible auto-pause is migration+14d with a reminder forced in
    # between — a day-one mass-pause is impossible by construction.
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # When the re-engagement reminder was last sent. NULL = never. Deliberately
    # never cleared: "a reminder is outstanding" is expressed as
    # `last_reengagement_sent_at > last_active_at`, so a login (which moves
    # last_active_at) self-invalidates it with no extra hot-path write.
    last_reengagement_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Stamped once when the "you never installed the pixel" nudge is sent.
    # NULL = never nudged; the nudge never repeats.
    install_nudge_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ─── Dashboard prefs ───
    # Per-surface widget layout, e.g. {"visitors": ["funnel", "traffic_fit"]}.
    # Nullable: a NULL/absent surface means "use the default layout".
    dashboard_layout: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # EasyEngage relationships
    social_accounts = relationship("SocialAccount", back_populates="user", cascade="all, delete-orphan")
    drafts = relationship("Draft", back_populates="user", cascade="all, delete-orphan")
    voice_examples = relationship("VoiceExample", back_populates="user", cascade="all, delete-orphan")
