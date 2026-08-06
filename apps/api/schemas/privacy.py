import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SuppressionCreate(BaseModel):
    email: str
    scope: str = "all"
    reason: str | None = None


class GraphIdentityLookupOut(BaseModel):
    """Operator answer to "is this person in the shared graph, and who put them
    there". Never carries an email, name, or ciphertext — only existence,
    counts, and the contributing site ids."""

    exists: bool
    row_count: int
    contributing_site_ids: list[str]
    erased_tombstone: bool
    matched_by: str


class ErasureQueueHealthOut(BaseModel):
    """Erasure queue counters. Counts and ages only — never a request row, a
    blind index, or a fingerprint."""

    pending: int
    processing: int
    done: int
    failed: int
    oldest_pending_age_hours: float | None = None
    oldest_failed_age_hours: float | None = None
    throttle_flagged_count: int


class SuppressionOut(BaseModel):
    """Suppression entry as stored — exposes the hash, never a plaintext email."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email_hash: str
    scope: str
    reason: str | None = None
    requested_by: str | None = None
    created_at: datetime | None = None
