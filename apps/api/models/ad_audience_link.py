import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class AdAudienceLink(Base):
    """Binds one Beam segment to one platform-side audience object.

    One row per (connection_id, segment_id) — the unique constraint IS the
    update-not-duplicate mechanism: the first push creates a platform audience
    and records its id here; every repeat push reuses that
    ``platform_audience_id`` instead of creating a second audience. Writes go
    through a Postgres ``ON CONFLICT (connection_id, segment_id) DO UPDATE``
    upsert so two simultaneous pushes cannot create two rows.
    """

    __tablename__ = "ad_audience_links"
    __table_args__ = (
        UniqueConstraint("connection_id", "segment_id", name="uq_ad_audience_link"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ad_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    segment_id: Mapped[str] = mapped_column(String(50), nullable=False)
    platform_audience_id: Mapped[str] = mapped_column(String(255), nullable=False)

    last_pushed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_push_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
