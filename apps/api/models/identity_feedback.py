"""User-reported precision signal for the onboarding location reveal.

The legacy static funnel built four checkboxes and a textarea and then read the
DOM zero times — the handler advanced the chat and discarded everything. This
table is where that answer now lands.

It is a QUALITY SIGNAL, not identity data: it stores what Beam *rendered*
(city/region/country/org/kind and a ROUNDED lat-lng), never the raw IP, never an
email, never a person name. Rounding the coordinates is deliberate — a full
precision pair per user is a household-adjacent datum that buys nothing here.

First precision feedback loop for the identity waterfall: `wrong_city` reports
grade IP geo, and `vpn_or_proxy` reports cross-checked against `check_ip_privacy`
give a cheap accuracy metric without paying a provider.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base

# Surfaces that can submit feedback. `public_onboarding_canary` is the unauthed
# twin used by the static funnel at /beam/onboarding.html — exactly the "later
# surface" this column was added for, so no migration was needed.
FEEDBACK_SURFACES: frozenset[str] = frozenset(
    {"onboarding_canary", "public_onboarding_canary"}
)

# `user_id` is NOT NULL and the public funnel runs before any account exists, so
# anonymous submissions carry this documented sentinel rather than a fabricated
# id. Filter it out of any per-user analysis; `surface` is the better predicate.
# (Chosen over widening the column to NULL: that is a migration whose nullability
# change is invisible to the integration suite, which builds schema from these
# models via create_all rather than by running migrations.)
ANONYMOUS_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")

# Rewritten for what is actually on screen at this beat. The legacy set (wrong
# name / wrong company / wrong socials) described a text profile card that the
# map reveal replaced. Validated against this frozenset at the router: an
# unknown reason is dropped, not stored, so the counts stay analysable.
FEEDBACK_REASONS: frozenset[str] = frozenset(
    {"wrong_city", "wrong_network", "vpn_or_proxy", "not_me"}
)

NOTE_MAX_CHARS = 500
# Ground truth: the city the user says they are ACTUALLY in, asked for only when
# they tick `wrong_city`. This is the one field that turns the reveal's error
# rate from a count into a measurement — `wrong_city` alone says "we were wrong",
# this says BY HOW MUCH and IN WHICH DIRECTION, which is what decides whether a
# provider swap (GeoLite2-City, a paid feed) is worth paying for.
#
# Kept OUT of `note`: `note` is free text whose content is deliberately never
# returned by the stats endpoint, so a city buried in it is unanalysable.
ACTUAL_CITY_MAX_CHARS = 120


class IdentityFeedback(Base):
    """One "not quite" submission from the onboarding reveal."""

    __tablename__ = "identity_feedback"
    __table_args__ = (
        Index("idx_identity_feedback_surface_created", "surface", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Nullable: the canary runs BEFORE site creation, so most rows have no site.
    site_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(100), nullable=True)
    surface: Mapped[str] = mapped_column(String(40), nullable=False)
    # Exactly what was rendered: city/region/country/org/kind + rounded lat-lng.
    # Without it a "wrong city" report is unactionable — we would not know which
    # city we claimed.
    shown: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    reasons: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), nullable=False, default=list
    )
    # A place NAME the user typed, never a coordinate and never geocoded — the
    # point is to compare it against `shown["city"]`, not to locate anybody more
    # precisely than the IP already did.
    actual_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
