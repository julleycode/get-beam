from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


# Every CRM provider the connectors layer knows about.
ALLOWED_CRM_PROVIDERS = {"generic_webhook", "hubspot", "pipedrive", "salesforce"}
# Providers that use an OAuth connect/callback (the rest are webhook/manual).
OAUTH_CRM_PROVIDERS = {"hubspot", "pipedrive", "salesforce"}


class CrmConnectionOut(BaseModel):
    """Safe public view of a connection — never exposes tokens or the secret."""

    provider: str
    auth_type: str
    status: str
    direction: str
    external_account_label: str | None = None
    webhook_url: str | None = None
    secret_hint: str | None = None
    field_mapping: dict = Field(default_factory=dict)
    is_valid: bool
    last_pushed_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class GenericWebhookCreate(BaseModel):
    webhook_url: HttpUrl
    secret: str = Field(..., min_length=8, description="HMAC signing secret (stored encrypted)")


class FieldMappingUpdate(BaseModel):
    field_mapping: dict[str, str]


class CrmConnectResponse(BaseModel):
    auth_url: str


class CrmTestResult(BaseModel):
    provider: str
    is_valid: bool
    message: str


class PushSegmentRequest(BaseModel):
    segment_id: str


class PushSegmentResult(BaseModel):
    provider: str
    segment_id: str
    pushed: int
    failed: int
    skipped: int  # segment members with no email / on the suppression list
    errors: list[str] = Field(default_factory=list)
    queued: bool = False  # true when the push was offloaded to a background worker
