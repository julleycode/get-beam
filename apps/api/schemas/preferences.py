"""Schemas for per-user dashboard preferences (widget layout)."""

from typing import List, Optional

from pydantic import BaseModel, Field


class WidgetLayoutResponse(BaseModel):
    surface: str
    # None = the user hasn't customised this surface → frontend uses its default.
    layout: Optional[List[str]] = None


class WidgetLayoutUpdate(BaseModel):
    surface: str = Field(default="visitors", max_length=50)
    # Ordered widget ids. Capped to keep the JSON small; ids are validated
    # against the registry on the client.
    layout: List[str] = Field(default_factory=list, max_length=50)
