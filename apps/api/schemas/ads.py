from datetime import datetime

from pydantic import BaseModel, Field

# Every ad provider the connectors layer knows about.
ALLOWED_AD_PROVIDERS = {"meta", "google", "linkedin"}
# Providers that use an OAuth connect/callback (all three, structurally).
OAUTH_AD_PROVIDERS = {"meta", "google", "linkedin"}


class AdConnectionOut(BaseModel):
    """Safe public view of a connection — never exposes tokens."""

    provider: str
    auth_type: str
    status: str
    external_account_label: str | None = None
    ad_account_id: str | None = None
    business_id: str | None = None
    is_valid: bool
    last_pushed_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdConnectResponse(BaseModel):
    auth_url: str


class AdTestResult(BaseModel):
    provider: str
    is_valid: bool
    message: str


class PushAdSegmentRequest(BaseModel):
    segment_id: str


class PushAdSegmentResult(BaseModel):
    provider: str
    segment_id: str
    pushed: int
    failed: int
    skipped: int  # segment members filtered out by the safety chain
    platform_audience_id: str = ""
    # Non-empty when the matched audience is below the platform minimum
    # (AC7). Advisory only — the push still happened.
    warning: str = ""
    # Structured companions to `warning` (AC7) so the UI renders the real
    # threshold instead of a hardcoded number. Additive — advisory only.
    below_minimum: bool = False
    minimum_threshold: int = 0
    errors: list[str] = Field(default_factory=list)
    queued: bool = False  # true when the push was offloaded to a background worker
