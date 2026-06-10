from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    model_config = ConfigDict(populate_by_name=True)

    type: str = Field(..., pattern="^(pageview|scroll|time_on_page|click|visibility|form_email_capture|utm_identify)$")
    # Client-generated idempotency key; duplicates are dropped at insert.
    event_id: str | None = Field(None, max_length=64)
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
    user_agent: str | None = None
    page_title: str | None = None
    page_path: str | None = None
    ts: datetime
    # Form email capture
    email: str | None = None
    # UTM link decoration
    bid: str | None = None
    # Browser fingerprint (sent on every event by the pixel as _fp field)
    fp: str | None = Field(None, alias="_fp")


class EventBatch(BaseModel):
    site_id: str = Field(..., min_length=1, max_length=50)
    visitor_id: str = Field(..., min_length=1, max_length=100)
    events: list[Event] = Field(..., min_length=1, max_length=100)
