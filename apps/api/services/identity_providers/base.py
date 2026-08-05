"""Shared HTTP utilities for identity providers.

Holds the transient-error classifier, the tenacity retry decorator, the
bare-hostname helper, and the Redis cache constants — all formerly defined at
module level in identity_resolver.py. `identity_resolver` re-imports these names
so existing imports (e.g. ``from ...identity_resolver import _url_to_host``) and
patch targets keep working.
"""

import socket
from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

REDIS_RESOLUTION_PREFIX = "resolution:"
RESOLUTION_CACHE_TTL = 30 * 86400  # 30 days

# What a resolution attempt actually concluded. The distinction that matters is
# "the provider answered and nobody matched" vs "the provider never answered":
# only the former is an attempt worth remembering, because only the former tells
# us anything about the visitor. See `IdentityResolver._log_resolution`.
RESOLUTION_OUTCOME_MATCH = "match"
RESOLUTION_OUTCOME_NO_MATCH = "no_match"
RESOLUTION_OUTCOME_PROVIDER_UNAVAILABLE = "provider_unavailable"

RESOLUTION_OUTCOMES = frozenset(
    {
        RESOLUTION_OUTCOME_MATCH,
        RESOLUTION_OUTCOME_NO_MATCH,
        RESOLUTION_OUTCOME_PROVIDER_UNAVAILABLE,
    }
)


class ProviderUnavailableError(Exception):
    """The provider could not answer — infrastructure failure, not a verdict.

    Provider mixins return ``None`` for "answered, nobody matched". That leaves no
    way to express "never answered", so both used to collapse into the same
    ledger row and arm the same 30-day retry lock. Raising this instead keeps the
    two apart: ``None`` now means only no-match.

    Raise for 401, 403, 429-after-retries, 5xx, timeouts, DNS and connect errors.
    Do NOT raise for 200-empty, 404, or 400 — those are real answers.
    """

    def __init__(self, provider: str, detail: str = "") -> None:
        self.provider = provider
        self.detail = detail
        super().__init__(f"{provider} unavailable: {detail}" if detail else f"{provider} unavailable")


def safe_failure_detail(exc: BaseException) -> str:
    """A failure description safe to persist: exception type plus HTTP status.

    Never interpolates `str(exc)` or a response body. httpx puts the full request
    URL in `HTTPStatusError.__str__`, and providers pass credentials as query
    params (ipinfo's `?token=`, hunter's `api_key=`) and the visitor IP in the
    path — so the raw message would write a live API token and PII into
    `api_usage_logs.meta`, which is durable and outside the DSAR erase path.
    """
    name = type(exc).__name__
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is not None:
        return f"{name}: HTTP {status}"
    if isinstance(exc, ProviderUnavailableError):
        return f"{name}: {exc.detail}" if exc.detail else name
    return name

# Transient HTTP errors worth retrying (timeouts, rate limits, 5xx server errors).
# 4xx client errors (400, 401, 403, 404) are NOT transient — never retry those.
_TRANSIENT_HTTP_STATUSES = {429, 500, 502, 503, 504}

# How far to walk an exception's __cause__ chain looking for the underlying
# socket error. httpx nests two levels deep; 8 leaves headroom without looping.
_CAUSE_CHAIN_MAX_DEPTH = 8


def _is_dns_resolution_failure(exc: BaseException) -> bool:
    """Return True when a ConnectError was caused by a name that does not resolve.

    A hostname with no DNS record fails identically on every attempt, so retrying
    it just burns the caller's timeout budget. Since
    ``_resolve_identity_graphs_parallel`` gathers all providers, one dead host
    otherwise costs every visitor the full 5s timeout.

    ``socket.gaierror`` is not reachable via ``__cause__`` alone: httpx raises
    ``httpx.ConnectError`` whose cause is ``httpcore.ConnectError``, which carries
    the ``gaierror`` as a positional *argument* rather than a cause. So each link
    in the chain is checked both ways.
    """
    seen = 0
    current: BaseException | None = exc
    while current is not None and seen < _CAUSE_CHAIN_MAX_DEPTH:
        if isinstance(current, socket.gaierror):
            return True
        if any(isinstance(arg, socket.gaierror) for arg in getattr(current, "args", ())):
            return True
        current = current.__cause__
        seen += 1
    return False


def _is_transient_http_error(exc: BaseException) -> bool:
    """Return True for retryable httpx errors (timeouts, connection errors, 5xx/429)."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.ConnectError):
        # Unresolvable hostname is permanent; refused/flaky connections are not.
        return not _is_dns_resolution_failure(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _TRANSIENT_HTTP_STATUSES
    return False


# Retry decorator for external HTTP calls.
# Retries up to 3 attempts (including the first) with exponential backoff 1→2→8s.
_http_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception(_is_transient_http_error),
    reraise=True,
)


def _url_to_host(url: str | None) -> str | None:
    """Bare hostname from a site URL ('https://www.grade.coach/x' -> 'grade.coach').

    Used to scope provider queries to one site's pixel domain.
    """
    if not url:
        return None
    host = urlparse(url if "//" in url else f"//{url}").hostname
    if host and host.startswith("www."):
        host = host[4:]
    return host


class HttpRetryMixin:
    """Shared HTTP-status helper used by every provider mixin."""

    @staticmethod
    def _raise_if_transient(resp: httpx.Response) -> None:
        """Raise HTTPStatusError for transient statuses so tenacity can retry them.

        Intentionally does NOT raise for 400 (bad request / unresolvable IP) or
        404 (no match) — those are legitimate "no result" responses.
        """
        if resp.status_code in _TRANSIENT_HTTP_STATUSES:
            resp.raise_for_status()
