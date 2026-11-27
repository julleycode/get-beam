"""Gemini-drafted SEO/AEO content suggestions (ad-insights-seo-aeo_27-11-26).

Suggestions ONLY: a human copies them. There is deliberately no write path from
this table to AgentProfile / llms.txt / the blog. ``status`` is
``new | dismissed | copied`` (DB check constraint).
"""

from datetime import date
from typing import Optional

from sqlalchemy import CheckConstraint, Date, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base

OPPORTUNITY_KINDS = ("page_title", "faq", "llms_txt")
OPPORTUNITY_STATUSES = ("new", "dismissed", "copied")


class ContentOpportunity(Base):
    __tablename__ = "content_opportunities"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('page_title', 'faq', 'llms_txt')", name="ck_content_opp_kind"
        ),
        CheckConstraint(
            "status IN ('new', 'dismissed', 'copied')", name="ck_content_opp_status"
        ),
        Index("idx_content_opp_site_status", "site_id", "status"),
    )

    site_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_ad_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    signals: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    generated_on: Mapped[date] = mapped_column(Date, nullable=False)
