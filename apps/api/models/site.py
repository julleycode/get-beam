import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    category: Mapped[str | None] = mapped_column(String(100))
    detected_platform: Mapped[str | None] = mapped_column(String(50))
    pixel_verified: Mapped[bool] = mapped_column(default=False)
    daily_resolution_budget: Mapped[int] = mapped_column(default=50)
    # When False (default), the auto resolution sweep skips this site — the owner
    # identifies visitors one at a time via the per-row Identify button. When True,
    # the sweep auto-resolves anonymous visitors with intent >= 40.
    auto_identify_enabled: Mapped[bool] = mapped_column(
        default=False, nullable=False, server_default="false"
    )
    # When True (default), email the owner the moment a high-intent US visitor is
    # identified — the "hot visitor" ping. Gated to US + intent >= 40 + once per
    # visitor; toggle off per site to silence.
    hot_alert_enabled: Mapped[bool] = mapped_column(
        default=True, nullable=False, server_default="true"
    )
    # When False, the ingest endpoint silently drops events for this site — the
    # offboarding "pause" toggle. Pixel stays installed on the customer's page and
    # the plan/data are left untouched; flip back on to resume collection anytime.
    tracking_enabled: Mapped[bool] = mapped_column(
        default=True, nullable=False, server_default="true"
    )
    # Cookie-consent mode emitted into the pixel snippet as data-consent.
    #   "off" (default) — no banner; today's behavior (GPC/DNT opt-out still honored).
    #   "eu"  — Beam shows an opt-in banner + holds events for EU/EEA visitors only.
    #   "all" — banner for every visitor.
    #   "cmp" — no Beam banner; the site's own consent tool calls window.beamConsent().
    consent_mode: Mapped[str] = mapped_column(
        String(10), default="off", nullable=False, server_default="off"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
