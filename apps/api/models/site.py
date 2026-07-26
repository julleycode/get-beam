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
    # the sweep auto-resolves anonymous visitors that clear the resolution
    # intent gate (RESOLUTION_MIN_INTENT, waived inside the first-win boost window).
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
    # Server-side conversion webhook (outcomes P3). The signing secret is
    # Fernet-encrypted at rest; only the display hint ("...abcd") is readable.
    # NULL = webhook not configured (endpoint answers 503).
    outcomes_webhook_secret_ciphertext: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    outcomes_webhook_secret_hint: Mapped[str | None] = mapped_column(
        String(12), nullable=True
    )
    # Throttle stamp for the weekly outcomes digest email (naive UTC). NULL =
    # never sent; the digest job skips sites stamped within the last 6 days.
    last_outcome_digest_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    # Watermark for the incremental aggregation path (capacity-hardening Phase 3,
    # decision D2). NULL = never aggregated incrementally → the next run does a
    # full recompute and then stamps this. Advanced ONLY after a successful
    # commit of that run's upserts, and the window is half-open
    # (created_at > last_aggregated_at) so no event is ever merged twice.
    last_aggregated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
