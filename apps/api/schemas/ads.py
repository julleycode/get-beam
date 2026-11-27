from datetime import datetime

from pydantic import BaseModel, Field

# Every ad provider the connectors layer knows about.
ALLOWED_AD_PROVIDERS = {"meta", "google", "linkedin"}
# Providers that use an OAuth connect/callback (all three, structurally).
OAUTH_AD_PROVIDERS = {"meta", "google", "linkedin"}


class AdConnectionOut(BaseModel):
    """Safe public view of a connection — never exposes tokens."""

    provider: str
    auth_type: str
    status: str
    external_account_label: str | None = None
    ad_account_id: str | None = None
    business_id: str | None = None
    is_valid: bool
    last_pushed_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdConnectResponse(BaseModel):
    auth_url: str


class AdTestResult(BaseModel):
    provider: str
    is_valid: bool
    message: str


class PushAdSegmentRequest(BaseModel):
    segment_id: str


class PushAdSegmentResult(BaseModel):
    provider: str
    segment_id: str
    pushed: int
    failed: int
    skipped: int  # segment members filtered out by the safety chain
    platform_audience_id: str = ""
    # Non-empty when the matched audience is below the platform minimum
    # (AC7). Advisory only — the push still happened.
    warning: str = ""
    # Structured companions to `warning` (AC7) so the UI renders the real
    # threshold instead of a hardcoded number. Additive — advisory only.
    below_minimum: bool = False
    minimum_threshold: int = 0
    errors: list[str] = Field(default_factory=list)
    queued: bool = False  # true when the push was offloaded to a background worker


# ── closed-won-lookalikes ────────────────────────────────

# 10k rows x ~100 bytes; the route also caps raw bytes.
CLOSED_WON_CSV_MAX_CHARS = 2_000_000


class ClosedWonCsvUpload(BaseModel):
    csv: str = Field(..., max_length=CLOSED_WON_CSV_MAX_CHARS)


class ClosedWonCsvResult(BaseModel):
    upserted: int
    skipped_erased: int
    skipped_invalid: int


class ClosedWonSeedSummary(BaseModel):
    total: int  # distinct closed-won emails
    matched: int  # of those, matched to an identified visitor on this site
    eligible: int  # after exclusions
    excluded: int
    needs_reconnect: bool = False


class ClosedWonLookalikeRequest(BaseModel):
    provider: str
    country: str = Field(..., min_length=2, max_length=2)
    ratio: str | None = Field(default=None, max_length=5)  # Meta
    expansion: str | None = Field(default=None, max_length=10)  # Google
    push_seed: bool = False  # re-push the seed before creating


class ClosedWonLookalikeResult(BaseModel):
    provider: str
    seed_audience_id: str = ""
    seed_pushed: int | None = None
    lookalike_audience_id: str = ""
    status: str = ""
    reused: bool = False
    previous_lookalike_id: str | None = None
    warning: str = ""
    error: str = ""
