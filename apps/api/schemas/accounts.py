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


class LinkedInOutreachConnectRequest(BaseModel):
    """Paste-a-cookie request to register a LinkedIn session with phantommm.

    The session_cookie / user_agent are SECRETS — they are forwarded to
    phantommm (which stores the cookie encrypted) and are NEVER stored in Beam,
    logged, or returned in any response.
    """

    session_cookie: str
    user_agent: str
    label: Optional[str] = None


class LinkedInOutreachConnectResponse(BaseModel):
    """Result of registering a LinkedIn session. Never echoes the cookie."""

    connected: bool
    name: Optional[str] = None
    connection_id_present: bool


class LinkedInOutreachStatusResponse(BaseModel):
    """Whether the caller has a usable LinkedIn outreach connection."""

    outreach_connected: bool
    configured: bool
