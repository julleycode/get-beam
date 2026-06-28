import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class CrmConnection(Base):
    """A site's outbound CRM connection — pushes identified visitors into an
    external CRM (HubSpot, Pipedrive, Salesforce) or any tool via a signed
    webhook.

    One row per (site_id, provider). OAuth providers store encrypted tokens
    (see services/encryption.py — graceful, same as social_accounts). The
    generic webhook stores its URL plus an encrypted HMAC signing secret
    (see services/key_vault.py — strict, same as BYOK keys). Secrets are never
    returned to the client; only a `secret_hint` is exposed.
    """

    __tablename__ = "crm_connections"
    __table_args__ = (
        UniqueConstraint("site_id", "provider", name="uq_crm_site_provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)  # "generic_webhook" | "hubspot" | ...
    auth_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "oauth" | "webhook"
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending|connected|error|disconnected
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="out")

    # OAuth providers (encrypted via services/encryption.py)
    access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String), nullable=True)
    external_account_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    external_account_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Generic-webhook provider (secret encrypted via services/key_vault.py)
    webhook_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    encrypted_secret: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    secret_hint: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # {crm_attr: visitor_field} overrides; empty = provider default mapping.
    field_mapping: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    last_pushed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # sanitized — never PII
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
