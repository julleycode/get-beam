import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

CONSENT_MODES = {"off", "eu", "all", "cmp"}

# Characters that must never appear in a stored booking_url. Two distinct
# reasons, deliberately merged into ONE reject set:
#   * ``< > " '`` — the value is substituted UNESCAPED into outbound HTML email
#     by campaign_sender._personalize, so these are an HTML-injection surface.
#   * ``)`` and whitespace — link_decorator._URL_RE is
#     ``https?://[^\s"\'<>)]+``, which TERMINATES a URL at any of these. A
#     stored URL containing one would be silently truncated mid-link by click
#     decoration, shipping a broken link. The reject set therefore MATCHES the
#     decorator's terminator set exactly.
_BOOKING_URL_FORBIDDEN = ('<', '>', '"', "'", ')')


def validate_booking_url(v: str | None) -> str | None:
    """Validate an owner-supplied booking URL, or return None for blank/unset.

    This validator IS the security contract for ``booking_url``: nothing
    downstream escapes the value before it reaches outbound HTML.
    """
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if len(v) > 500:
        raise ValueError("booking_url must be at most 500 characters")
    # Absolute http(s) only — blocks javascript:, data:, and scheme-less values.
    if not (v.startswith("http://") or v.startswith("https://")):
        raise ValueError("booking_url must be an absolute http(s) URL")
    if any(c in v for c in _BOOKING_URL_FORBIDDEN):
        raise ValueError("booking_url must not contain any of < > \" ' )")
    if any(c.isspace() for c in v):
        raise ValueError("booking_url must not contain whitespace")
    return v


class SiteCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    url: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    category: str | None = None


class SiteOut(BaseModel):
    id: uuid.UUID
    site_id: str
    name: str
    url: str
    description: str | None
    category: str | None
    detected_platform: str | None
    pixel_verified: bool
    daily_resolution_budget: int
    auto_identify_enabled: bool
    hot_alert_enabled: bool
    tracking_enabled: bool
    # Outlier / internal-traffic damping opt-in. Default OFF; when on, visitors
    # flagged as unusually high-activity are excluded from this site's
    # cross-visitor aggregates and sorted last for identity resolution.
    internal_damping_enabled: bool = False
    # Identity co-op opt-in (identity-coop Phase 1). Default OFF; graph READ
    # access is never gated on it.
    contribution_enabled: bool = False
    # Campaign-benchmark opt-in (marketing-claims-gap Phase 3). Default OFF.
    # A SEPARATE consent basis from contribution_enabled above — zero-PII
    # k-anonymous aggregates, not identity sharing.
    benchmark_contribution_enabled: bool = False
    # Owner's demo/meeting booking link, rendered into drafts via
    # {{booking_link}}. Additive + optional; None = not configured.
    booking_url: str | None = None
    consent_mode: str
    created_at: datetime

    @field_validator(
        "internal_damping_enabled",
        "contribution_enabled",
        "benchmark_contribution_enabled",
        mode="before",
    )
    @classmethod
    def _damping_defaults_off(cls, v):
        """None -> False. Fails SAFE for any Site object predating the column."""
        return False if v is None else v

    model_config = {"from_attributes": True}


class SiteUpdate(BaseModel):
    """Partial site update. Only set fields are applied.

    ``description`` / ``category`` were missing here even though both columns
    exist on ``Site`` and are settable at create time via ``SiteCreate`` — a
    latent bug that made them write-once. Added by agent-gateway Phase 1
    (the agent profile leans on a real site description). Additive/optional, so
    no existing caller changes behavior.
    """

    description: str | None = None
    category: str | None = None
    auto_identify_enabled: bool | None = None
    hot_alert_enabled: bool | None = None
    tracking_enabled: bool | None = None
    internal_damping_enabled: bool | None = None
    consent_mode: str | None = None
    # Identity co-op opt-in. Setting this True REQUIRES ``terms_version`` to be the
    # currently-pinned ``settings.coop_terms_version`` (E4); the router 422s
    # otherwise and writes the AC-10 acceptance row in the same transaction.
    # Setting it False needs no acceptance — opting out is always unconditional.
    contribution_enabled: bool | None = None
    # Accompanies contribution_enabled=True only. A 64-char lowercase hex digest
    # of the exact accepted policy text — never a free-form label.
    terms_version: str | None = None
    # Campaign-benchmark opt-in. Unconditional in BOTH directions — no
    # terms_version, no acceptance row: the pooled data is zero-PII and
    # k-anonymous, so a structlog audit line is the proportionate artifact.
    # Setting this NEVER reads or writes contribution_enabled (purpose limitation).
    benchmark_contribution_enabled: bool | None = None
    # Demo/meeting booking link. Validated below — see validate_booking_url.
    booking_url: str | None = None

    @field_validator("booking_url")
    @classmethod
    def _valid_booking_url(cls, v: str | None) -> str | None:
        return validate_booking_url(v)

    @field_validator("consent_mode")
    @classmethod
    def _valid_consent_mode(cls, v: str | None) -> str | None:
        if v is not None and v not in CONSENT_MODES:
            raise ValueError(f"consent_mode must be one of {sorted(CONSENT_MODES)}")
        return v


class SitePixelSnippet(BaseModel):
    site_id: str
    snippet: str


class PlatformDetectRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=500)


class PlatformDetectResponse(BaseModel):
    platform: str
    confidence: float
    has_gtm: bool
    gtm_id: str | None = None


class PixelVerifyResponse(BaseModel):
    site_id: str
    status: str
    verified: bool
    message: str
    # The foreign Beam site id found installed on the page — populated only when
    # status == "wrong_site", None otherwise. Additive + optional: existing
    # clients that ignore it are unaffected. A bare string already public in the
    # page's HTML; never resolved to an owner (see pixel_verifier).
    found_site_id: str | None = None


class ShopifyConnectRequest(BaseModel):
    shop_domain: str = Field(..., min_length=1, max_length=200)
