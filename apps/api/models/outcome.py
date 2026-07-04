"""Conversion outcomes: goals, click links, and recorded conversions.

The chain that proves "Beam drove N conversions":

1. A campaign email link carries ``_tp=<touchpoint uuid>`` (link_decorator).
2. The recipient lands on the customer's site; the pixel posts the landing URL
   and the ingest path stores a ``CampaignClick`` row linking the touchpoint to
   the LANDING browser's visitor_id (which may differ from the visitor Beam
   originally emailed — new device, wiped cookies).
3. When any visitor later triggers a ``ConversionGoal`` (URL match today;
   JS event / webhook later), conversion_tracker attributes it to the last
   click within the attribution window and inserts a ``Conversion`` row.

Conversions live in their own table (not ``events``) so they survive the raw
event retention purge — outcome reporting must not decay with event TTLs.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class ConversionGoal(Base):
    __tablename__ = "conversion_goals"
    __table_args__ = (
        UniqueConstraint("site_id", "name", name="uq_conversion_goals_site_name"),
        Index("idx_conversion_goals_site_enabled", "site_id", "enabled"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # url_match today; js_event arrives with the beamConvert() pixel API.
    goal_type: Mapped[str] = mapped_column(String(20), nullable=False, default="url_match")
    # exact | prefix | contains — compared against the normalized landing path.
    match_type: Mapped[str] = mapped_column(String(20), nullable=False, default="contains")
    pattern: Mapped[str] = mapped_column(String(500), nullable=False)
    # Default $ value credited per conversion (overridable per event in P3).
    value_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # False: once per visitor forever. True: at most once per visitor per UTC day
    # (or per caller-supplied event_id for js_event/webhook sources).
    repeatable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class CampaignClick(Base):
    """Touchpoint ↔ landing-visitor link, recorded when a ``_tp`` URL lands.

    A link table (not a column on campaign_touchpoints) because one recipient
    can click from several browsers/devices — each landing vid gets its own
    row, first click per (touchpoint, visitor) wins. site_id + campaign_id are
    denormalized so attribution and reporting never join through touchpoints.
    """

    __tablename__ = "campaign_clicks"
    __table_args__ = (
        UniqueConstraint("touchpoint_id", "visitor_id", name="uq_campaign_clicks_tp_visitor"),
        Index("idx_campaign_clicks_site_visitor_time", "site_id", "visitor_id", "clicked_at"),
        Index("idx_campaign_clicks_campaign", "campaign_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    touchpoint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign_touchpoints.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    visitor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    clicked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Conversion(Base):
    __tablename__ = "conversions"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_conversions_dedupe_key"),
        Index("idx_conversions_site_time", "site_id", "occurred_at"),
        Index("idx_conversions_goal", "goal_id"),
        Index("idx_conversions_campaign", "campaign_id"),
        Index("idx_conversions_site_visitor", "site_id", "visitor_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversion_goals.id", ondelete="CASCADE"), nullable=False
    )
    visitor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # SET NULL: a deleted campaign keeps its historical conversions countable
    # in site totals (attribution string survives) without dangling FKs.
    touchpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign_touchpoints.id", ondelete="SET NULL"), nullable=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )
    channel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # campaign (a Beam touch qualified within the window) | organic (baseline).
    attribution: Mapped[str] = mapped_column(String(20), nullable=False, default="organic")
    # How the campaign was matched: click_link (campaign_clicks row, works
    # cross-device) | same_visitor (fallback: the emailed visitor converted in
    # the same browser). NULL for organic. Kept for auditability.
    matched_by: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="url_match")
    value_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    url: Mapped[str] = mapped_column(Text, default="")
    # Uniqueness carrier for all dedupe modes; max real length 202 (goal uuid 36
    # + ':' + visitor 100 + ':' + event_id 64), column padded to 250.
    dedupe_key: Mapped[str] = mapped_column(String(250), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
