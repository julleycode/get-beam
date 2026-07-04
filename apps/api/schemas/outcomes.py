"""Request/response schemas for conversion goals + outcomes reporting."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

GOAL_TYPES = {"url_match"}  # P3 adds "js_event"
MATCH_TYPES = {"exact", "prefix", "contains"}


def validate_goal_pattern(match_type: str, pattern: str) -> str:
    """Normalize + validate a goal pattern against its match type.

    Raises ValueError with a user-facing message on invalid input; returns the
    normalized (trimmed, lowercased) pattern otherwise. Shared by create and
    update paths so both enforce identical rules.
    """
    normalized = pattern.strip().lower()
    if not normalized:
        raise ValueError("Pattern must not be empty")
    if match_type in ("exact", "prefix"):
        if not normalized.startswith("/"):
            raise ValueError("exact/prefix patterns must start with '/'")
        if len(normalized) > 1:
            normalized = normalized.rstrip("/") or "/"
    elif match_type == "contains":
        # Blocks pathological single-char substrings that match every page.
        if len(normalized) < 3:
            raise ValueError("contains patterns need at least 3 characters")
    return normalized


class GoalCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    goal_type: str = "url_match"
    match_type: str = "contains"
    pattern: str = Field(..., min_length=1, max_length=500)
    value_cents: int | None = Field(None, ge=0, le=100_000_000)
    repeatable: bool = False

    @model_validator(mode="after")
    def _validate(self) -> "GoalCreate":
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Name must not be empty")
        if self.goal_type not in GOAL_TYPES:
            raise ValueError(f"goal_type must be one of {sorted(GOAL_TYPES)}")
        if self.match_type not in MATCH_TYPES:
            raise ValueError(f"match_type must be one of {sorted(MATCH_TYPES)}")
        self.pattern = validate_goal_pattern(self.match_type, self.pattern)
        return self


class GoalUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    match_type: str | None = None
    pattern: str | None = Field(None, min_length=1, max_length=500)
    value_cents: int | None = Field(None, ge=0, le=100_000_000)
    repeatable: bool | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def _validate(self) -> "GoalUpdate":
        if self.name is not None:
            self.name = self.name.strip()
            if not self.name:
                raise ValueError("Name must not be empty")
        if self.match_type is not None and self.match_type not in MATCH_TYPES:
            raise ValueError(f"match_type must be one of {sorted(MATCH_TYPES)}")
        # Pattern is re-validated against the FINAL match_type in the router
        # (the other half of the pair may come from the stored row).
        return self


class GoalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    goal_type: str
    match_type: str
    pattern: str
    value_cents: int | None
    repeatable: bool
    enabled: bool
    created_at: datetime


class GoalListResponse(BaseModel):
    goals: list[GoalOut]
    total: int


class OutcomeTotals(BaseModel):
    conversions: int
    attributed: int
    organic: int
    revenue_cents: int
    attributed_revenue_cents: int


class CampaignOutcomeRow(BaseModel):
    campaign_id: uuid.UUID
    name: str
    sent: int
    opened: int
    clicked: int
    converted: int
    conversion_rate: float
    revenue_cents: int


class GoalOutcomeRow(BaseModel):
    goal_id: uuid.UUID
    name: str
    goal_type: str
    enabled: bool
    conversions: int
    attributed: int
    revenue_cents: int


class OutcomesReportResponse(BaseModel):
    days: int
    totals: OutcomeTotals
    campaigns: list[CampaignOutcomeRow]
    goals: list[GoalOutcomeRow]
