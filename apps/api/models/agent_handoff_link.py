"""Fetch↔click handoff correlation link (Handoff Detection H2).

One row links a single on-demand ``agent_fetch_events`` row (an AI agent fetched
page X for vendor V at time T) to the human ``Visitor`` whose AI-referral click
(``ai_source``/``first_touch_referrer``) landed on the same page from the same
vendor family within a bounded window after T. This is Beam's headline
"who is the human behind the agent" signal, surfaced as a confidence-qualified,
never-certain dashboard badge.

Structurally separate from the emailability guardrail (SPEC Constraint 1 / AC-H2-3):
this table NEVER declares, writes, or references the agent-origin emailability
marker, and never calls the emailability guard used to exclude agent-origin records
from outreach. A handoff link's existence is invisible to emailability in both
directions: it never makes an agent-fetch record contactable, and it never changes
a linked human's emailable status. An absence-tripwire in
``tests/unit/test_handoff_emailability_separation.py`` enforces this structurally.

WRITE POLICY (deliberate precision-over-recall for a v1 differentiator badge):
the ``confidence`` column keeps all three tiers (``high``/``medium``/``low``) in the
schema, but the correlation sweep only ever INSERTs ``high`` and ``medium`` links —
``low``-confidence candidate matches are discarded, never written. The ``low`` value
stays in the schema so a future phase can loosen the write policy without a migration.

No ``ForeignKey()`` on any column — the model-family house convention (see
``AgentFetchEvent`` / ``AgentVisit.resolved_company_id``) keeps cross-table FKs at
the DB layer, not the ORM layer. ``site_id``/``visitor_id`` are plain natural keys;
``agent_fetch_event_id`` references ``agent_fetch_events.id`` (unique — one link per
fetch event) with no constraint declared, kept consistent across the join.
"""

import uuid

from sqlalchemy import Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class AgentHandoffLink(Base):
    """One fetch↔click handoff correlation link. ``id``/``created_at``/``updated_at`` from ``Base``."""

    __tablename__ = "agent_handoff_links"
    __table_args__ = (
        UniqueConstraint("agent_fetch_event_id", name="uq_agent_handoff_links_fetch_event"),
        Index("idx_agent_handoff_links_site_visitor", "site_id", "visitor_id"),
        Index("idx_agent_handoff_links_site_created", "site_id", "created_at"),
    )

    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    visitor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_fetch_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    # Schema keeps high/medium/low; the sweep only ever writes high/medium (see
    # module docstring WRITE POLICY).
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    method: Mapped[str] = mapped_column(
        String(30), nullable=False, default="temporal-page-match"
    )
    delta_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    matched_page: Mapped[str | None] = mapped_column(String(500), nullable=True)
