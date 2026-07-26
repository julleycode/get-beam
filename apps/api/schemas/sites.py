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
    # Outlier / internal-traffic damping opt-in. Default OFF; when on, visitors
    # flagged as unusually high-activity are excluded from this site's
    # cross-visitor aggregates and sorted last for identity resolution.
    internal_damping_enabled: bool = False
    consent_mode: str
    created_at: datetime

    @field_validator("internal_damping_enabled", mode="before")
    @classmethod
    def _damping_defaults_off(cls, v):
        """None -> False. Fails SAFE for any Site object predating the column."""
        return False if v is None else v

    model_config = {"from_attributes": True}


class SiteUpdate(BaseModel):
    """Partial site update. Only set fields are applied.

    ``description`` / ``category`` were missing here even though both columns
    exist on ``Site`` and are settable at create time via ``SiteCreate`` — a
    latent bug that made them write-once. Added by agent-gateway Phase 1
    (the agent profile leans on a real site description). Additive/optional, so
    no existing caller changes behavior.
    """

    description: str | None = None
    category: str | None = None
    auto_identify_enabled: bool | None = None
    hot_alert_enabled: bool | None = None
    tracking_enabled: bool | None = None
    internal_damping_enabled: bool | None = None
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
