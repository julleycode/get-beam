"""Shared HTTP utilities for identity providers.

Holds the transient-error classifier, the tenacity retry decorator, the
bare-hostname helper, and the Redis cache constants — all formerly defined at
module level in identity_resolver.py. `identity_resolver` re-imports these names
so existing imports (e.g. ``from ...identity_resolver import _url_to_host``) and
patch targets keep working.
"""

from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

REDIS_RESOLUTION_PREFIX = "resolution:"
RESOLUTION_CACHE_TTL = 30 * 86400  # 30 days

# Transient HTTP errors worth retrying (timeouts, rate limits, 5xx server errors).
# 4xx client errors (400, 401, 403, 404) are NOT transient — never retry those.
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
