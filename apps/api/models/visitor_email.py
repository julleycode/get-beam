import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base

# Canonical `source` value space for visitor_emails. Formalizes the drift where
# the column docstring listed only form/utm/manual while the pixel + click-bind
# path already emitted login/checkout/newsletter/input/identify/email_click.
# MUST be a superset of every value any live write path emits (a missing value
# would be silently rewritten to "other" and would break the CHECK constraint on
# existing rows). Column stays String(20); this constrains the value space, not
# the column shape.
VISITOR_EMAIL_SOURCES: frozenset[str] = frozenset({
    "form",          # form submit, email-named field (pixel)
    "utm",           # _bid= decoded param (pixel + events.py)
    "manual",        # linked by the site operator
    "email_click",   # ESP click bind (routers/click.py)
    "login",         # emailSource() login classifier (pixel)
    "checkout",      # emailSource() checkout classifier (pixel)
    "newsletter",    # emailSource() newsletter classifier (pixel)
    "input",         # emailSource() default (pixel)
    "identify",      # window.beamIdentify() (pixel)
    "mailto_click",  # mailto: link click (pixel — first-party-capture Phase 1)
    "url_param",     # ?email= URL param (pixel — first-party-capture Phase 1)
    "other",         # normalization fallback for any unrecognized value
})


def normalize_source(raw: str | None) -> str:
    """Sanitize + validate a capture ``source`` (SPEC AC13).

    Trims, lowercases, caps to the column width, and normalizes any value NOT in
    ``VISITOR_EMAIL_SOURCES`` to ``"other"`` — so a source is never stored as
    arbitrary free text. Pure (no DB): unit-testable in the fast lane.
    """
    src = (raw or "form").strip().lower()[:20] or "form"
    return src if src in VISITOR_EMAIL_SOURCES else "other"


class VisitorEmail(Base):
    """Maps a captured email address to a visitor cookie ID.

    ``source`` is one of ``VISITOR_EMAIL_SOURCES`` (validated/normalized via
    ``normalize_source``): form / utm / manual / email_click / login / checkout /
    newsletter / input / identify / mailto_click / url_param / other.
    """

    __tablename__ = "visitor_emails"
    __table_args__ = (
        UniqueConstraint("site_id", "visitor_id", "email", name="uq_visitor_email_site_vid_email"),
        Index("idx_visitor_emails_site_visitor", "site_id", "visitor_id"),
        Index("idx_visitor_emails_email", "email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    visitor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="form")
    # Phase 05 (encrypt PII at rest) — added nullable, not yet read/written.
    # email_ciphertext holds the Fernet-encrypted address; email_bidx is the
    # HMAC blind index used for equality/uniqueness lookups once we cut over.
    email_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_bidx: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
