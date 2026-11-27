"""Per-site company/domain exclusion list (customers, competitors, other).

A visitor whose email domain or resolved ``Visitor.company_domain`` matches an
entry (after a parent-domain walk) is kept visible in the dashboard (badged) but
is never sent outreach, exported, pushed to ad audiences, or segmented — only
when ``settings.company_exclusion_enabled`` is on. See
``services/company_exclusion.py``.

Contains only owner-authored company domains, never visitor PII.
"""

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base

EXCLUSION_REASONS: tuple[str, ...] = ("customer", "competitor", "other")


class SiteExclusion(Base):
    __tablename__ = "site_exclusions"
    __table_args__ = (
        Index("uq_site_exclusions_site_domain", "site_id", "domain", unique=True),
    )

    site_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("sites.site_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    domain: Mapped[str] = mapped_column(String(253), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reason: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
