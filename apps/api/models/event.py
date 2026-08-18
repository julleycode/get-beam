"""PostgreSQL event storage — replaces ClickHouse for MVP scale."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from apps.api.models.database import Base


class Event(Base):
    __tablename__ = "events"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    # Client-generated idempotency key (pixel UUID). Unique per site when
    # present; still nullable this phase so pre-backfill rows can exist until
    # the additive migration fills NULLs. Ingest now requires the field;
    # NOT NULL on the column waits until 24h of zero null inserts.
    event_id: str = Column(String(64), nullable=True)
    site_id: str = Column(String(50), nullable=False)
    visitor_id: str = Column(String(100), nullable=False)
    event_type: str = Column(String(30), nullable=False)
    url: str = Column(Text, default="")
    referrer: str = Column(Text, default="")
    utm_source: str = Column(String(200), default="")
    utm_medium: str = Column(String(200), default="")
    utm_campaign: str = Column(String(200), default="")
    country_code: str = Column(String(5), default="")
    region: str = Column(String(100), default="")
    device_type: str = Column(String(20), default="")
    browser_lang: str = Column(String(20), default="")
    scroll_depth: int = Column(Integer, default=0)
    time_on_page: int = Column(Integer, default=0)
    element_text: str = Column(String(500), default="")
    element_href: str = Column(Text, default="")
    ip_address: str = Column(String(45), default="")
    user_agent: str = Column(String(500), default="")
    page_title: str = Column(String(500), default="")
    page_path: str = Column(String(2000), default="")
    # Privacy opt-out signal from the browser (GPC or DNT) on this event.
    # Aggregated per visitor (BOOL_OR) into visitors.do_not_resolve.
    optout: bool = Column(Boolean, default=False, server_default="false", nullable=False)
    # Farbled-browser marker (WS2 Detector B): the pixel's navigator.brave probe
    # resolved true. Aggregated per visitor (BOOL_OR) into
    # visitors.has_unstable_fingerprint, exactly like optout -> do_not_resolve.
    # Not indexed: it is never a query predicate, only a rollup input.
    farbled: bool = Column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # Ingest abuse marker. Site-ceiling (P3) is a hard 429 with 0 INSERT — it
    # never writes this flag. The column is for velocity (P4) and other abuse
    # marks that still flag-but-store: those rows are kept for forensics but
    # excluded from the visitor rollup (aggregate_visitors_for_site) and,
    # transitively, from outreach eligibility. Aggregated per visitor (BOOL_OR)
    # into visitors.is_abuse_flagged, exactly like optout -> do_not_resolve.
    is_flagged_abuse: bool = Column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # Edge-minted AI-fetch link marker (``?_bfm=``) extracted from ``url`` at
    # ingest. Denormalised on purpose: matching it against
    # AgentFetchEvent.link_marker is how a human click is tied to the exact agent
    # fetch whose answer produced it, and doing that with LIKE over ``url`` is a
    # sequential scan of the largest table in the schema. One extracted column
    # turns that join into two index lookups.
    #
    # NULL for the overwhelming majority of events — most visitors arrive with no
    # marker, and every event before this column existed has none.
    link_marker: str | None = Column(String(32), nullable=True)
    # WS2 agent-operated session signals as collected by the pixel (abbreviated
    # keys: w/h/p/d/c — see schemas/events.py). Read ONLY by the batch sweep
    # ws2_session_classifier_sweep; never on the ingest hot path, never by
    # is_emailable_identity(), never by any drop/block decision.
    #
    # NULL for every event written before this column existed and for every older
    # pixel build — the sweep fails safe (flags nobody) when it is absent.
    agent_sig: dict | None = Column(JSONB, nullable=True)
    created_at: datetime = Column(DateTime, default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("site_id", "event_id", name="uq_events_site_event_id"),
        Index("ix_events_site_visitor", "site_id", "visitor_id"),
        Index("ix_events_site_created", "site_id", "created_at"),
        Index("ix_events_created", "created_at"),
        # Supports the aggregator's exclusion filter and the P5 health query.
        Index("ix_events_site_flagged", "site_id", "is_flagged_abuse"),
        # PARTIAL: only marked events are indexed. This table takes every
        # pageview/scroll/time_on_page on every customer site, so indexing the
        # NULLs would cost write throughput on the hottest path in the API for
        # rows that can never satisfy the join.
        Index(
            "ix_events_link_marker",
            "link_marker",
            postgresql_where=text("link_marker IS NOT NULL"),
        ),
    )
