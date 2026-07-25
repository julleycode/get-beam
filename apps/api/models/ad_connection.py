import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class AdConnection(Base):
    """A site's outbound ad-platform connection — pushes a segment's hashed
    contacts into an ad platform's custom-audience surface (Meta Custom
    Audiences, Google Customer Match, LinkedIn Matched Audiences).

    Mirrors ``CrmConnection`` field-for-field (same OAuth token storage, same
    status bookkeeping) plus the two ad-specific identifiers an ad platform
    needs to address the right account. One row per (site_id, provider).

    Tokens are encrypted via services/encryption.py and never returned to the
    client — only ``external_account_label`` is exposed.
    """

    __tablename__ = "ad_connections"
    __table_args__ = (
        UniqueConstraint("site_id", "provider", name="uq_ad_site_provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)  # "meta" | "google" | "linkedin"
    auth_type: Mapped[str] = mapped_column(String(20), nullable=False, default="oauth")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending|connected|error|disconnected

    # OAuth (encrypted via services/encryption.py)
    access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String), nullable=True)
    external_account_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    external_account_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Ad-specific: which ad account / business the audience is created under.
    ad_account_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    business_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    last_pushed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # sanitized — never PII
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
