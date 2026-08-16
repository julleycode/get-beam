import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
    # Identity co-op opt-in (identity-coop Phase 1). When True AND
    # settings.identity_coop_enabled is True, this site's successful graph writes
    # are counted as contributions and accrue spendable credits. Default OFF: the
    # cross-tenant graph is a data co-op only for sites that explicitly opted in,
    # and the flag cannot flip ON via the API without a validated terms_version
    # acceptance row (AC-10). READ access to the graph is UNCONDITIONAL and is NOT
    # gated on this flag — a non-contributing site still receives graph matches.
    contribution_enabled: Mapped[bool] = mapped_column(
        default=False, nullable=False, server_default="false"
    )
    # When True (default), email the owner the moment a high-intent US visitor is
    # identified — the "hot visitor" ping. Gated to US + intent >= 40 + once per
    # visitor; toggle off per site to silence.
    hot_alert_enabled: Mapped[bool] = mapped_column(
        default=True, nullable=False, server_default="true"
    )
    # When True, outlier/internal-traffic damping (sweep-detected + manual
    # override) is applied to this site's aggregates and resolution ordering.
    # Default OFF so a customer can see before/after, and so damping-OFF sites
    # keep byte-identical digest numbers and resolution ordering.
    # NOTE: the manual "this is me / my team" override endpoint is deliberately
    # NOT gated on this flag — a single-visitor manual call has zero blast radius
    # and must stay available to customers wary of the automatic scorer.
    internal_damping_enabled: Mapped[bool] = mapped_column(
        default=False, nullable=False, server_default="false"
    )
    # When False, the ingest endpoint silently drops events for this site — the
    # offboarding "pause" toggle. Pixel stays installed on the customer's page and
    # the plan/data are left untouched; flip back on to resume collection anytime.
    tracking_enabled: Mapped[bool] = mapped_column(
        default=True, nullable=False, server_default="true"
    )
    # Set (naive UTC) when the inactivity sweep paused this site; cleared on any
    # authed request by the owner (silent auto-resume) and on any explicit
    # owner write to `tracking_enabled`. This column is the ONLY thing that
    # distinguishes an auto-pause from a MANUAL pause: tracking_enabled=False
    # with auto_paused_at NULL is deliberate and is never auto-resumed.
    auto_paused_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
    # Throttle stamp for the daily activity digest email (naive UTC). NULL =
    # never sent; the daily job skips sites stamped within the last 20h. Kept
    # separate from last_outcome_digest_sent_at so the weekly forwardable digest
    # and this owner-only daily report never throttle each other.
    last_daily_digest_sent_at: Mapped[datetime | None] = mapped_column(
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
    # This site's own Leadpipe pixel, provisioned on first snippet fetch. A
    # Leadpipe pixel is bound 1-1 to a domain (the API 409s on duplicates), so a
    # shared id would load on every site and collect on none of them. NULL =
    # not provisioned yet (or Leadpipe not configured) → the snippet simply
    # omits the vendor tag.
    leadpipe_pixel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # ─── Site analysis (onboarding) — all five flag-gated on settings.site_analysis_enabled ───
    # Two-slot storage so a re-run can never destroy a confirmed profile.
    # The CONFIRMED profile the site actually uses. NULL = the owner has never
    # confirmed one. ONLY the PUT /sites/{id}/analysis endpoint writes this; the
    # background analysis task structurally never touches it.
    site_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # The un-reviewed output of the latest analysis run, awaiting the owner's
    # review. NULL = nothing pending review. ONLY the analysis task writes it;
    # PUT NULLs it (on promote AND on dismiss).
    site_profile_candidate: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # "pending" | "ready" | "failed". NULL = never analyzed (reported as "none").
    # NOT the whole truth on its own: a "pending" row whose started_at is older
    # than settings.site_analysis_stale_seconds is DERIVED as "failed" at read
    # time and the row is never mutated by that read.
    site_profile_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Naive UTC start stamp of the current run — the input to that stale
    # derivation. Never re-armed by a POST that hits the in-flight guard.
    site_profile_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Naive UTC completion time of the run that produced the candidate. Exactly
    # one writer: the analysis task. PUT never stamps it. NULL on a
    # user-authored profile with no analysis behind it.
    site_profile_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
