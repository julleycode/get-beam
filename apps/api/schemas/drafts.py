from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from apps.api.models.draft import DraftStatus, DraftType
from apps.api.models.social_account import Platform


class DraftResponse(BaseModel):
    id: str
    type: DraftType
    platform: Platform
    ai_content: str
    edited_content: Optional[str] = None
    status: DraftStatus
    strategy: Optional[str] = None
    strategy_label: Optional[str] = None
    sent_at: Optional[datetime] = None
    created_at: datetime

    # Inline context so the user knows what this draft is for
    original_content: Optional[str] = None
    original_author: Optional[str] = None

    model_config = {"from_attributes": True}


class DraftListResponse(BaseModel):
    drafts: list[DraftResponse]
    total: int


class DraftEditRequest(BaseModel):
    edited_content: str


class DraftActionResponse(BaseModel):
    id: str
    status: DraftStatus
    message: str


class GenerateDraftRequest(BaseModel):
    post_id: Optional[str] = None
    message_id: Optional[str] = None


class GenerateMultiDraftResponse(BaseModel):
    """Response for multi-draft generation with mode info."""
    mode: str  # "learning" or "confident"
    drafts: list[DraftResponse]
    voice_example_count: int  # How many examples GBrain has for this platform
