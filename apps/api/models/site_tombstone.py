import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class SiteTombstone(Base):
    """Record of a deleted site's identity, so a re-create for the same domain
    by the same owner can reuse the original `site_id` and keep the already
    installed tracking snippet working.

    Stores id + url + owner + timestamp ONLY — never event, visitor, or
    identity data. Rows are never deleted by a background job; *reuse
    eligibility* expires at read time after `site_id_reclaim_window_days`
    (mirrors the `company_graph_staleness_days` read-time-revalidation
    precedent).

    Deliberately NO unique constraint on `site_id`: a domain can be
    deleted/re-created repeatedly, so the lookup orders by `deleted_at DESC`
    and takes the newest row.
    """

    __tablename__ = "site_tombstones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(500), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Exact shape of the create_site reuse lookup:
    #   WHERE user_id = :uid AND normalized_url IN :variants
    #   AND deleted_at >= now() - window ORDER BY deleted_at DESC
    __table_args__ = (
        Index(
            "ix_site_tombstones_user_url",
            "user_id",
            "normalized_url",
            "deleted_at",
        ),
    )
