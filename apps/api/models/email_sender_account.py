"""Connected outbound email identity (Connect-Gmail).

A site owner can connect their own Gmail so campaign emails go out FROM their
address instead of Beam's shared SendGrid from-address (which makes Gmail show
"via sendgrid.info"). Sending through the owner's Gmail removes the "via" and
lands the mail as genuinely from them.

Scoped to the User (the site owner): one row per (user, provider). Only campaign
sends consult this — system mail (waitlist, alerts) always stays on SendGrid.
The OAuth tokens are Fernet-encrypted at rest (services/encryption.py), same as
SocialAccount. ``provider`` is future-proofing for Outlook later; today only
"google" is written.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class EmailSenderAccount(Base):
    __tablename__ = "email_senders"
    __table_args__ = (
        # One connected sender per provider per user.
        Index("uq_email_sender_user_provider", "user_id", "provider", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="google")
    # The connected address — used as the From on campaign sends.
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    # Fernet-encrypted at rest.
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scopes: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String), nullable=True)
    # Cleared to False when a token refresh fails (revoked / password change) so
    # the send path falls back to Beam and the UI can prompt a reconnect.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
