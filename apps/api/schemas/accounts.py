from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from apps.api.models.social_account import Platform


class SocialAccountResponse(BaseModel):
    id: str
    platform: Platform
    username: str
    platform_user_id: str
    is_active: bool
    token_expires_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConnectResponse(BaseModel):
    auth_url: str


class DisconnectResponse(BaseModel):
    message: str
