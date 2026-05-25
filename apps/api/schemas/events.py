from datetime import datetime

from pydantic import BaseModel, Field


class UTMParams(BaseModel):
    source: str | None = None
    medium: str | None = None
    campaign: str | None = None
    term: str | None = None
    content: str | None = None


class Viewport(BaseModel):
    w: int
    h: int


class Event(BaseModel):
    type: str = Field(..., pattern="^(pageview|scroll|time_on_page|click|visibility)$")
    url: str | None = None
    referrer: str | None = None
    utm: UTMParams | None = None
    viewport: Viewport | None = None
    device: str | None = None
    lang: str | None = None
    depth: int | None = None
    seconds: int | None = None
    element_text: str | None = None
    element_href: str | None = None
    visible: bool | None = None
    ts: datetime


class EventBatch(BaseModel):
    site_id: str = Field(..., min_length=1, max_length=50)
    visitor_id: str = Field(..., min_length=1, max_length=100)
    events: list[Event] = Field(..., min_length=1, max_length=100)
