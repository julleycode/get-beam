"""Changelog entry model.

Backs the "what's new" pill on the getbeam.fyi landing page. Each entry is a
short product update (a single line of copy), published from the dashboard and
read publicly by the static landing page. Intentionally simpler than BlogPost —
no slug, markdown, or SEO fields.
"""

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base

# Lifecycle: only `published` entries surface on the landing page.
CHANGELOG_STATUSES = ("draft", "published")
# Visual category — drives the timeline dot colour (new / improved / fixed).
CHANGELOG_CATEGORIES = ("new", "improved", "fixed")


class ChangelogEntry(Base):
    """A single product update. Inherits id / created_at / updated_at from Base."""

    __tablename__ = "changelog_entries"

    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")

    category: Mapped[str] = mapped_column(String(20), default="new")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)

    # Provenance for the GitHub auto-generator: "pr-<number>". NULL = entered by
    # hand. Unique (partial index) so re-running the sync never duplicates a PR.
    source_ref: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True)

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
