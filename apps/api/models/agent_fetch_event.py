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
        # Lookup index for the click-side join: given a ``_bfm`` seen in a landing
        # URL, find the fetch that minted it. PARTIAL because the overwhelming
        # majority of rows carry no marker and indexing their NULLs would cost
        # write throughput on the ingest path for nothing. Deliberately NOT
        # unique: the edge mints per fetch with no coordination, so uniqueness is
        # a property to observe, not one to enforce -- a collision should show up
        # as two candidate rows to disambiguate, never as a rejected insert that
        # loses an agent visit.
        Index(
            "idx_agent_fetch_events_link_marker",
            "link_marker",
            postgresql_where=text("link_marker IS NOT NULL"),
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
    # Opaque per-fetch token the EDGE stamped onto every same-host link in the
    # HTML it served for this fetch. A human who later clicks one of those links
    # arrives carrying it in the landing URL, which the pixel already reports --
    # so joining ``events.url`` back to this row names the exact fetch whose
    # answer produced the click. That is the deterministic replacement for the
    # vendor+page+30-minute guess in ``agent_handoff_correlation``.
    #
    # NOT the same token as ``agent_marker.py``'s ``_bam``: that one is this
    # row's id encrypted by the API, minted only for offers.json. This column
    # stores a marker the edge minted on its own, because a Pages middleware has
    # neither the row nor the key at the time it must stamp the links.
    #
    # Nullable and unconstrained on purpose: every pre-existing row has none,
    # every non-edge write path still has none, and a forged value can at worst
    # attach a bogus attribution to an agent-only row -- it reaches no identity
    # or emailability path.
    link_marker: Mapped[str | None] = mapped_column(String(32), nullable=True)
