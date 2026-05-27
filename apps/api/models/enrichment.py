import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Float, Integer, Text, Index, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class EnrichmentProfile(Base):
    __tablename__ = "enrichment_profiles"
    __table_args__ = (
        Index("uq_enrichment_site_visitor", "site_id", "visitor_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    visitor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    site_id: Mapped[str] = mapped_column(String(50), nullable=False)

    # Professional
    job_title: Mapped[str | None] = mapped_column(String(200))
    company_name: Mapped[str | None] = mapped_column(String(200))
    company_size: Mapped[str | None] = mapped_column(String(50))
    industry: Mapped[str | None] = mapped_column(String(100))
    seniority_level: Mapped[str | None] = mapped_column(String(50))

    # Social
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    twitter_handle: Mapped[str | None] = mapped_column(String(100))
    facebook_url: Mapped[str | None] = mapped_column(String(500))
    github_url: Mapped[str | None] = mapped_column(String(500))
    personal_website: Mapped[str | None] = mapped_column(String(500))

    # LinkedIn details
    linkedin_headline: Mapped[str | None] = mapped_column(String(500))
    linkedin_summary: Mapped[str | None] = mapped_column(Text)
    linkedin_follower_count: Mapped[int | None] = mapped_column(Integer)

    # Twitter details
    twitter_bio: Mapped[str | None] = mapped_column(String(500))
    twitter_follower_count: Mapped[int | None] = mapped_column(Integer)
    twitter_recent_topics: Mapped[dict] = mapped_column(JSONB, default=list)

    # Computed
    enrichment_completeness: Mapped[float] = mapped_column(Float, default=0.0)
    enriched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
