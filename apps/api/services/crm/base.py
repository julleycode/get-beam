"""Abstract base + shared types for outbound CRM connectors.

A connector pushes normalized `CRMContact` rows into one external CRM. OAuth
providers also implement the connect/exchange/refresh methods; webhook-style
providers leave those raising NotImplementedError.

Every outbound HTTP call uses a 10s timeout and the shared `_http_retry`
decorator (3 attempts, exponential backoff, transient errors only) — same
policy as services/enricher.py, per CLAUDE.md.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

HTTP_TIMEOUT = 10.0

# Max in-flight per-contact requests for providers without a batch endpoint
# (Pipedrive, Salesforce). Bounds load on the CRM and on our own worker while
# still beating fully-sequential pushes.
PUSH_CONCURRENCY = 8

_TRANSIENT_HTTP_STATUSES = {429, 500, 502, 503, 504}


def _is_transient_http_error(exc: BaseException) -> bool:
    """Return True for retryable httpx errors (timeouts, connection errors, 5xx/429)."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.ConnectError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _TRANSIENT_HTTP_STATUSES
    return False


# 3 attempts, exponential backoff 1→2→8s, transient errors only.
_http_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception(_is_transient_http_error),
    reraise=True,
)


@dataclass
class CRMContact:
    """Provider-agnostic contact. Each connector maps this to its own API."""

    email: str
    first_name: str = ""
    last_name: str = ""
    phone: str = ""
    company_name: str = ""
    job_title: str = ""
    city: str = ""
    region: str = ""
    country: str = ""


@dataclass
class CrmOAuthTokens:
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    scopes: list[str] = field(default_factory=list)
    external_account_id: str = ""
    external_account_label: str = ""


@dataclass
class PushResult:
    pushed: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def sanitize_error(exc: BaseException, fallback: str = "Request failed") -> str:
    """Short, PII-free error string safe to persist in `last_error` / return.

    Provider error bodies can echo contact emails/names — never surface those.
    We keep only the status code (for HTTP errors) or the exception type.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Provider returned HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "Provider request timed out"
    if isinstance(exc, httpx.HTTPError):
        return "Provider connection error"
    return fallback


class CRMConnector(ABC):
    provider: str = ""
    auth_type: str = ""  # "oauth" | "webhook"

    # ── OAuth (no-ops for webhook providers) ──────────────
    async def get_auth_url(self, state: str) -> str:
        raise NotImplementedError(f"{self.provider} is not an OAuth connector")

    async def exchange_code(self, code: str, state: str = "") -> CrmOAuthTokens:
        raise NotImplementedError(f"{self.provider} is not an OAuth connector")

    async def refresh_tokens(self, refresh_token: str) -> CrmOAuthTokens:
        raise NotImplementedError(f"{self.provider} is not an OAuth connector")

    # ── Test + push (every connector implements these) ────
    @abstractmethod
    async def test_connection(
        self,
        *,
        access_token: str = "",
        webhook_url: str = "",
        secret: str = "",
        instance_url: str = "",
    ) -> bool:
        ...

    @abstractmethod
    async def upsert_contacts(
        self,
        contacts: list[CRMContact],
        *,
        access_token: str = "",
        webhook_url: str = "",
        secret: str = "",
        instance_url: str = "",
    ) -> PushResult:
        ...
