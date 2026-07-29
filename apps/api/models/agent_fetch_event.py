"""Append-only per-hit AI-agent fetch event (Handoff Detection H1).

One row per recognized AI-agent hit — distinct from the ``agent_visits`` rollup
upsert. This is the raw, timestamped, tier-tagged event stream every downstream
handoff phase (H2 fetch↔click correlation, H3 live alerts, optional daily
timeseries) reads from.

Structurally separate from Visitor/Event (SPEC D1) — agent traffic never touches
human visitor data. Logically append-only (no upsert), though the shared ``Base``
provides an ``updated_at`` column; that is accepted, not fought.
"""

from sqlalchemy import String, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class AgentFetchEvent(Base):
    """One append-only per-hit agent fetch event, tagged on-demand vs index.

    ``id``/``created_at``/``updated_at`` are provided by ``Base``. No
    ``ForeignKey()`` is declared on ``site_id`` — the model-family house
    convention (see ``AgentVisit.resolved_company_id``) keeps cross-table FKs at
    the DB layer, not the ORM layer.
    """

    __tablename__ = "agent_fetch_events"
    __table_args__ = (
        Index("idx_agent_fetch_events_site_created", "site_id", "created_at"),
        Index(
            "idx_agent_fetch_events_site_path_tier_created",
            "site_id", "page_path", "tier", "created_at",
        ),
        # Replay guard. PARTIAL on purpose: only rows that carry a dedup identity
        # participate, and in Postgres NULLs never conflict with each other. That
        # is what lets this index be created on a live table with no cleanup and
        # no backfill -- every pre-existing row has a NULL key and so cannot
        # violate it, and the write paths that have no natural key keep inserting
        # freely.
        #
        # A composite key over the existing columns would NOT work here: this
        # table's ``created_at`` defaults to ``now()`` at microsecond resolution,
        # so a replayed write lands on a different timestamp and slips past any
        # constraint that includes it, while two genuinely distinct rapid fetches
        # would be the ones at risk of collapsing. The identity has to come from
        # the caller's own retry-stable token instead.
        Index(
            "uq_agent_fetch_events_dedup_key",
            "dedup_key",
            unique=True,
            postgresql_where=text("dedup_key IS NOT NULL"),
        ),
    )

    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    vendor: Mapped[str] = mapped_column(String(30), nullable=False)
    raw_ua_token: Mapped[str] = mapped_column(String(50), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    page_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    verification_method: Mapped[str] = mapped_column(String(20), nullable=False, default="ua-only")
    # sha256 hex of the writing path's retry-stable identity, or NULL when that
    # path has none. NULL means "this row makes no dedup claim", never "this row
    # is unique" -- see ``build_dedup_key`` for what goes into the digest.
    dedup_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
