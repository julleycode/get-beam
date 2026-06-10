"""Pydantic schemas for waitlist endpoints."""

from pydantic import BaseModel, Field


class ConsumeInviteRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=255)
