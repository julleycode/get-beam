from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text, JSON,
    ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
import uuid

Base = declarative_base()


def gen_uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    name = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    sites = relationship("Site", back_populates="user")


class Site(Base):
    __tablename__ = "sites"
    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    domain = Column(String, nullable=False)
    pixel_id = Column(String, unique=True, default=gen_uuid, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    user = relationship("User", back_populates="sites")
    visitors = relationship("Visitor", back_populates="site")
    segments = relationship("Segment", back_populates="site")
    campaigns = relationship("Campaign", back_populates="site")


class Visitor(Base):
    __tablename__ = "visitors"
    id = Column(String, primary_key=True, default=gen_uuid)
    site_id = Column(String, ForeignKey("sites.id"), nullable=False)
    anonymous_id = Column(String, nullable=False, index=True)
    ip_address = Column(String)
    user_agent = Column(String)
    country = Column(String)
    city = Column(String)
    first_seen = Column(DateTime(timezone=True), server_default=func.now())
    last_seen = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    page_views = Column(Integer, default=0)
    total_time_seconds = Column(Integer, default=0)
    intent_score = Column(Float, default=0.0)
    top_pages = Column(JSON, default=list)
    is_identified = Column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("site_id", "anonymous_id"),)
    site = relationship("Site", back_populates="visitors")
    identity = relationship("IdentifiedVisitor", back_populates="visitor", uselist=False)
    enrichment = relationship("EnrichmentProfile", back_populates="visitor", uselist=False)


class IdentifiedVisitor(Base):
    __tablename__ = "identified_visitors"
    id = Column(String, primary_key=True, default=gen_uuid)
    visitor_id = Column(String, ForeignKey("visitors.id"), unique=True, nullable=False)
    email = Column(String, index=True)
    full_name = Column(String)
    company = Column(String)
    title = Column(String)
    linkedin_url = Column(String)
    confidence_score = Column(Float, default=0.0)
    resolution_method = Column(String)
    resolved_at = Column(DateTime(timezone=True), server_default=func.now())
    visitor = relationship("Visitor", back_populates="identity")


class EnrichmentProfile(Base):
    __tablename__ = "enrichment_profiles"
    id = Column(String, primary_key=True, default=gen_uuid)
    visitor_id = Column(String, ForeignKey("visitors.id"), unique=True, nullable=False)
    company_size = Column(String)
    industry = Column(String)
    funding_stage = Column(String)
    revenue_range = Column(String)
    tech_stack = Column(JSON, default=list)
    seniority = Column(String)
    department = Column(String)
    social_profiles = Column(JSON, default=dict)
    enriched_at = Column(DateTime(timezone=True), server_default=func.now())
    visitor = relationship("Visitor", back_populates="enrichment")


class Segment(Base):
    __tablename__ = "segments"
    id = Column(String, primary_key=True, default=gen_uuid)
    site_id = Column(String, ForeignKey("sites.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    criteria = Column(JSON, default=dict)
    ai_reasoning = Column(Text)
    member_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_run_at = Column(DateTime(timezone=True))
    site = relationship("Site", back_populates="segments")
    members = relationship("SegmentMember", back_populates="segment")


class SegmentMember(Base):
    __tablename__ = "segment_members"
    id = Column(String, primary_key=True, default=gen_uuid)
    segment_id = Column(String, ForeignKey("segments.id"), nullable=False)
    visitor_id = Column(String, ForeignKey("visitors.id"), nullable=False)
    added_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("segment_id", "visitor_id"),)
    segment = relationship("Segment", back_populates="members")


class Campaign(Base):
    __tablename__ = "campaigns"
    id = Column(String, primary_key=True, default=gen_uuid)
    site_id = Column(String, ForeignKey("sites.id"), nullable=False)
    segment_id = Column(String, ForeignKey("segments.id"))
    name = Column(String, nullable=False)
    status = Column(String, default="draft")  # draft, approved, active, paused, completed
    channels = Column(JSON, default=list)
    plan = Column(JSON, default=dict)
    ai_reasoning = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    site = relationship("Site", back_populates="campaigns")
    touchpoints = relationship("CampaignTouchpoint", back_populates="campaign")


class CampaignTouchpoint(Base):
    __tablename__ = "campaign_touchpoints"
    id = Column(String, primary_key=True, default=gen_uuid)
    campaign_id = Column(String, ForeignKey("campaigns.id"), nullable=False)
    visitor_id = Column(String, ForeignKey("visitors.id"))
    channel = Column(String)
    status = Column(String, default="pending")
    sent_at = Column(DateTime(timezone=True))
    opened_at = Column(DateTime(timezone=True))
    clicked_at = Column(DateTime(timezone=True))
    campaign = relationship("Campaign", back_populates="touchpoints")
