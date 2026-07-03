"""Async client for the phantommm sidecar (LinkedIn outreach automation).

Beam NEVER talks to LinkedIn directly and NEVER stores the raw LinkedIn session
cookie. The cookie is POSTed once to phantommm's ``/api/connections/linkedin``
endpoint, which stores it encrypted and returns an opaque ``connection_id``.
Every later call references that id — Beam only ever holds the reference.

Security rules (enforced here, do not relax):
  * The session cookie, user agent, api key and outreach note bodies are
    SECRETS/PII — they are NEVER logged. Log counts, ids and status only.
  * Every request carries the ``x-api-key`` header (== phantommm's ``API_KEY``).
  * 10s timeout, 3 attempts with exponential backoff on transient errors,
    mirroring services/crm/base.py and services/enricher.py per CLAUDE.md.

If ``phantommm_base_url`` or ``phantommm_api_key`` is unset, every call raises
``PhantommmNotConfigured`` so routers can translate it to a clean HTTP 503
("LinkedIn outreach not configured"), mirroring the Lemon Squeezy 503 pattern.
"""

from typing import Any, Literal

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from apps.api.config import settings

logger = structlog.get_logger()

HTTP_TIMEOUT = 10.0

_TRANSIENT_HTTP_STATUSES = {429, 500, 502, 503, 504}

OutreachAction = Literal["connect", "message"]


class PhantommmError(Exception):
    """Base error for phantommm sidecar failures (network, non-2xx, bad body)."""


class PhantommmNotConfigured(PhantommmError):
    """Raised when phantommm_base_url / phantommm_api_key are unset.

    Routers catch this and return HTTP 503 "LinkedIn outreach not configured".
    """


def _is_transient_http_error(exc: BaseException) -> bool:
    """Return True for retryable httpx errors (timeouts, conn errors, 5xx/429)."""
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
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


class PhantommmClient:
    """Thin async wrapper over the phantommm HTTP contract."""

    def __init__(self) -> None:
        base = settings.phantommm_base_url
        key = settings.phantommm_api_key
        if not base or not key:
            raise PhantommmNotConfigured("LinkedIn outreach not configured")
        # Strip a trailing slash so path joins are predictable.
        self._base_url = base.rstrip("/")
        self._api_key = key

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key, "Content-Type": "application/json"}

    @_http_retry
    async def _request(
        self, method: str, path: str, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Issue one request, raising PhantommmError on failure.

        NEVER logs the request body — it may contain the session cookie, user
        agent or note. Only the method, path and status code are logged.
        """
        url = f"{self._base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.request(
                    method, url, headers=self._headers, json=json_body
                )
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Re-raised by tenacity for transient statuses after retries exhaust;
            # non-transient statuses fall straight through. Log status only.
            logger.warning(
                "phantommm_http_error",
                method=method,
                path=path,
                status=exc.response.status_code,
            )
            raise PhantommmError(
                f"phantommm {method} {path} failed: HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("phantommm_network_error", method=method, path=path)
            raise PhantommmError(
                f"phantommm {method} {path} failed: {type(exc).__name__}"
            ) from exc

        try:
            return resp.json()
        except ValueError as exc:
            logger.warning("phantommm_bad_json", method=method, path=path)
            raise PhantommmError(
                f"phantommm {method} {path} returned non-JSON body"
            ) from exc

    async def register_linkedin_connection(
        self, session_cookie: str, user_agent: str, label: str | None = None
    ) -> dict[str, Any]:
        """Register a LinkedIn session cookie → opaque connection.

        Returns the ``connection`` object (``{id, platform, label, status, ...}``).
        The session_cookie / user_agent are secrets and are never logged.
        """
        body: dict[str, Any] = {
            "sessionCookie": session_cookie,
            "userAgent": user_agent,
        }
        if label:
            body["label"] = label
        data = await self._request("POST", "/api/connections/linkedin", body)
        connection = data.get("connection")
        if not isinstance(connection, dict) or not connection.get("id"):
            raise PhantommmError("phantommm register returned no connection id")
        logger.info(
            "phantommm_connection_registered",
            connection_id=connection.get("id"),
            status=connection.get("status"),
        )
        return connection

    async def verify_connection(self, connection_id: str) -> dict[str, Any]:
        """Verify a stored connection is still valid.

        Returns the ``result`` object (``{valid, name, url}``).
        """
        data = await self._request(
            "POST", f"/api/connections/{connection_id}/verify"
        )
        result = data.get("result")
        if not isinstance(result, dict):
            raise PhantommmError("phantommm verify returned no result")
        logger.info(
            "phantommm_connection_verified",
            connection_id=connection_id,
            valid=bool(result.get("valid")),
        )
        return result

    async def start_outreach(
        self,
        *,
        connection_id: str,
        urls: list[str],
        note: str,
        action: OutreachAction = "connect",
        dry_run: bool = True,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Start an async outreach job. Returns ``{jobId, accepted, dryRun, action}``.

        phantommm scrapes each profile's name and templates ``#firstName#`` /
        ``#lastName#`` / ``#fullName#`` in ``note``, paces sends 25–55s apart and
        honors LinkedIn weekly caps. The ``note`` body is NOT logged (personal).
        """
        body: dict[str, Any] = {
            "connectionId": connection_id,
            "urls": urls,
            "note": note,
            "action": action,
            "dryRun": dry_run,
            "limit": limit,
        }
        data = await self._request("POST", "/api/outreach", body)
        logger.info(
            "phantommm_outreach_started",
            connection_id=connection_id,
            job_id=data.get("jobId"),
            action=action,
            dry_run=bool(data.get("dryRun", dry_run)),
            url_count=len(urls),
            accepted=data.get("accepted"),
        )
        return data

    async def get_outreach_job(self, job_id: str) -> dict[str, Any]:
        """Fetch job status. Returns the ``job`` object
        (``{id, status, done, total, sent, results:[...]}``)."""
        data = await self._request("GET", f"/api/outreach/{job_id}")
        job = data.get("job")
        if not isinstance(job, dict):
            raise PhantommmError("phantommm job status returned no job")
        return job
