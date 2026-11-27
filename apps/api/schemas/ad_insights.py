"""Pydantic schemas for /api/v1/ad-insights (ad-insights-seo-aeo_27-11-26)."""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class TopAdOut(BaseModel):
    rank: int
    platform_ad_id: str
    provider: str
    headline: str = ""
    landing_url: str = ""
    campaign_name: str = ""
    impressions: int
    clicks: int
    conversions: float
    ctr: float
    conv_rate: float
    angles: list[str] = Field(default_factory=list)


class TopAdsResponse(BaseModel):
    min_impressions: int
    min_qualifying_ads: int
    enough_data: bool
    ads: list[TopAdOut]


class ContentOpportunityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    title: str
    body: str
    rationale: Optional[str] = None
    source_ad_ids: list[str] = Field(default_factory=list)
    signals: dict = Field(default_factory=dict)
    status: str
    generated_on: date
    created_at: Optional[datetime] = None


class OpportunityStatusIn(BaseModel):
    status: Literal["new", "dismissed", "copied"]


class RefreshResponse(BaseModel):
    scheduled: bool
