"""PostgreSQL event storage — replaces ClickHouse for MVP scale."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.sql import func

from apps.api.models.database import Base


class Event(Base):
    __tablename__ = "events"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
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
    created_at: datetime = Column(DateTime, default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_events_site_visitor", "site_id", "visitor_id"),
        Index("ix_events_site_created", "site_id", "created_at"),
        Index("ix_events_created", "created_at"),
    )
