import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

CONSENT_MODES = {"off", "eu", "all", "cmp"}


class SiteCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    url: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    category: str | None = None


class SiteOut(BaseModel):
    id: uuid.UUID
    site_id: str
    name: str
    url: str
    description: str | None
    category: str | None
    detected_platform: str | None
    pixel_verified: bool
    daily_resolution_budget: int
    auto_identify_enabled: bool
    hot_alert_enabled: bool
    tracking_enabled: bool
    consent_mode: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SiteUpdate(BaseModel):
    """Partial site update. Only set fields are applied."""

    auto_identify_enabled: bool | None = None
    hot_alert_enabled: bool | None = None
    tracking_enabled: bool | None = None
    consent_mode: str | None = None

    @field_validator("consent_mode")
    @classmethod
    def _valid_consent_mode(cls, v: str | None) -> str | None:
        if v is not None and v not in CONSENT_MODES:
            raise ValueError(f"consent_mode must be one of {sorted(CONSENT_MODES)}")
        return v


class SitePixelSnippet(BaseModel):
    site_id: str
    snippet: str


class PlatformDetectRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=500)


class PlatformDetectResponse(BaseModel):
    platform: str
    confidence: float
    has_gtm: bool
    gtm_id: str | None = None


class PixelVerifyResponse(BaseModel):
    site_id: str
    status: str
    verified: bool
    message: str


class ShopifyConnectRequest(BaseModel):
    shop_domain: str = Field(..., min_length=1, max_length=200)
