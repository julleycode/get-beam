"""Abstract base + shared types for outbound ad-audience providers.

Mirrors services/crm/base.py's shape: one provider class per ad platform,
OAuth connect/exchange plus a create-or-update-audience push. Every payload
that leaves this layer carries SHA256-hashed identifiers only — the plaintext
email never reaches a provider module.

Phase 1 ships stubs only: real HTTP wiring lands in Phase 2 (Meta) and
Phase 3 (Google). LinkedIn stays permanently unready.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

HTTP_TIMEOUT = 10.0

# Providers whose live path is implemented. Enforced server-side at connect
# time (routers/ads.py) so an unready provider can never start an OAuth flow,
# mirroring the frontend `ready` flag in ad-connect-panel.tsx.
READY: dict[str, bool] = {"meta": True, "google": True, "linkedin": False}


@dataclass
class HashedContact:
    """One audience member, hashed. Never holds a plaintext identifier."""

    email_sha256: str
    phone_sha256: str = ""
    first_name_sha256: str = ""
    last_name_sha256: str = ""
    city_sha256: str = ""
    region_sha256: str = ""
    country_sha256: str = ""


@dataclass
class AdOAuthTokens:
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    scopes: list[str] = field(default_factory=list)
    external_account_id: str = ""
    external_account_label: str = ""
    ad_account_id: str = ""
    business_id: str = ""


@dataclass
class AdTestOutcome:
    is_valid: bool
    message: str = ""


@dataclass
class AudienceResult:
    """Outcome of a create-or-update-audience call."""

    platform_audience_id: str
    pushed: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class ConversionEvent:
    """One server-side conversion, hashed. Never holds a plaintext identifier.

    ``dedup_id`` is the platform dedup key (Meta ``event_id`` / Google
    ``transactionId``): IdentifiedVisitor.id for leads, Conversion.id for goals.
    """

    delivery_id: str
    dedup_id: str
    conversion_type: str
    event_name: str  # Meta event name / Google conversion label (from goal_event_map)
    event_time: datetime
    email_sha256: str = ""
    phone_sha256: str = ""
    click_ids: dict = field(default_factory=dict)
    user_agent: str = ""
    event_source_url: str = ""


@dataclass
class ConversionResult:
    """Per-event outcome of ``send_conversions``."""

    delivery_id: str
    ok: bool
    # Sanitized reason code — never provider body text, never PII.
    error: str = ""
    transient: bool = False


def sanitize_error(exc: BaseException, fallback: str = "Request failed") -> str:
    """Short, PII-free error string safe to persist in ``last_error``.

    Provider error bodies can echo contact data — never surface those.
    """
    import httpx

    if isinstance(exc, httpx.HTTPStatusError):
        return f"Provider returned HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "Provider request timed out"
    if isinstance(exc, httpx.HTTPError):
        return "Provider connection error"
    return fallback


class AdsProvider(ABC):
    provider: str = ""

    @abstractmethod
    async def get_oauth_url(self, state: str) -> str:
        ...

    @abstractmethod
    async def exchange_code(self, code: str, state: str = "") -> AdOAuthTokens:
        ...

    @abstractmethod
    async def test_connection(self, connection) -> AdTestOutcome:
        ...

    @abstractmethod
    async def create_or_update_audience(
        self,
        connection,
        link,
        hashed_contacts: list[HashedContact],
    ) -> AudienceResult:
        ...

    # conversion-apis: NON-abstract on purpose (additive base edit, E5) so every
    # existing provider keeps instantiating; providers that support server-side
    # conversions override it.
    async def send_conversions(
        self,
        connection,
        config,
        events: list[ConversionEvent],
    ) -> list[ConversionResult]:
        raise NotImplementedError(f"{self.provider or 'provider'} does not support conversions")
