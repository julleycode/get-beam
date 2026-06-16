import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SuppressionCreate(BaseModel):
    email: str
    scope: str = "all"
    reason: str | None = None


class SuppressionOut(BaseModel):
    """Suppression entry as stored — exposes the hash, never a plaintext email."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email_hash: str
    scope: str
    reason: str | None = None
    requested_by: str | None = None
    created_at: datetime | None = None
