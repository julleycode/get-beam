from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

    type: str = Field(..., pattern="^(pageview|scroll|time_on_page|click|visibility|form_email_capture|utm_identify|conversion)$")
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
    # Where the email was captured: form / input / login / checkout / newsletter
    # / identify (window.beamIdentify). Free label, capped to the column width.
    source: str | None = Field(None, max_length=20)
    # UTM link decoration
    bid: str | None = None
    # Conversion events (window.beamConvert): goal name + optional $ value.
    # Consumed by services/conversion_tracker — NOT persisted to the events
    # table (the row still lands generically with event_type="conversion").
    goal: str | None = Field(None, max_length=100)
    value: float | None = None
    # Browser fingerprint (sent on every event by the pixel as _fp field)
    fp: str | None = Field(None, alias="_fp")
    # fp3: the same base signals plus the installed-font probe and the offline
    # audio render. Async on the client, so early events in a session may carry
    # _fp without _fp3. Older pixel builds never send it.
    fp3: str | None = Field(None, alias="_fp3")
    # WS2 agent-operated session signals, collected by the pixel strictly after
    # the consent gate. Abbreviated wire keys keep the pixel inside its <6KB gzip
    # budget: w=webdriver, h=UA-CH Headless brand, p=pointer-entropy proxy,
    # d=dead-centre click delta for THIS event, c=cumulative click count.
    # Optional — older pixel builds never send it, and the batch sweep fails safe
    # (never flags) when it is absent. Visibility-only: never read by
    # is_emailable_identity() or any drop/block path.
    agent_sig: dict | None = Field(None, alias="_asig")
    # Privacy opt-out: pixel sets true when navigator.globalPrivacyControl (GPC)
    # or doNotTrack (DNT) is on. Defaults False for older pixel builds.
    optout: bool = False

    # mode="before" is load-bearing, not stylistic: with the default "after" mode
    # a non-dict _asig raises a ValidationError and 422s the WHOLE batch, so one
    # malformed optional signal would drop a page's worth of legitimate events.
    # SPEC AC-7 forbids classification ever causing a drop — this field must
    # degrade to None, never reject.
    @field_validator("agent_sig", mode="before")
    @classmethod
    def _sanitize_agent_sig(cls, v: object) -> dict | None:
        """Whitelist + bound the agent_sig object before it is ever persisted.

        /ingest is public and unauthenticated, so this dict is attacker-supplied.
        Storing it raw would let anyone write unbounded JSONB into the largest
        table in the schema. Only the five known keys survive, each coerced to a
        bounded scalar; anything else is dropped. An object with no usable key
        normalises to None so the sweep sees "absent" and fails safe.
        """
        if not isinstance(v, dict):
            return None
        out: dict = {}
        for key in ("w", "h"):
            if key in v:
                out[key] = bool(v[key])
        if "p" in v:
            try:
                p = float(v["p"])
            except (TypeError, ValueError):
                p = None
            if p is not None:
                out["p"] = min(max(p, 0.0), 1.0)
        for key in ("d", "c"):
            if key in v:
                try:
                    out[key] = min(max(int(v[key]), 0), 10_000)
                except (TypeError, ValueError):
                    pass
        return out or None


class EventBatch(BaseModel):
    site_id: str = Field(..., min_length=1, max_length=50)
    visitor_id: str = Field(..., min_length=1, max_length=100)
    events: list[Event] = Field(..., min_length=1, max_length=100)
