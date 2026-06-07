from datetime import datetime

from pydantic import BaseModel, Field


ALLOWED_PROVIDERS = {
    # AI
    "anthropic",
    "openrouter",
    # Identity resolution
    "rb2b",
    "leadpipe",
    "capturify",
    "customers_ai",
    # Enrichment
    "proxycurl",
    "hunter",
    "apollo",
    "ipinfo",
    "people_data_labs",
    # Social
    "twitter",
    "facebook",
    "linkedin",
    "tiktok",
    "instagram",
}


class ApiKeyCreate(BaseModel):
    provider: str = Field(..., description="API provider: 'proxycurl', 'twitter', or 'openrouter'")
    api_key: str = Field(..., min_length=1, description="The API key value")


class ApiKeyOut(BaseModel):
    provider: str
    key_hint: str
    is_valid: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyTestResult(BaseModel):
    provider: str
    is_valid: bool
    message: str
