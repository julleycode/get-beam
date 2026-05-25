from datetime import datetime

from pydantic import BaseModel, Field


ALLOWED_PROVIDERS = {"proxycurl", "twitter"}


class ApiKeyCreate(BaseModel):
    provider: str = Field(..., description="API provider: 'proxycurl' or 'twitter'")
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
