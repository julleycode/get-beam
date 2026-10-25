"""Thin async client for the TinyFish Search + Fetch APIs.

Used only by ``tinyfish_reader`` (enricher Step 4c). Two calls:

- ``search(query)``  -> list of ``{"url", "title", "snippet"}``
- ``fetch(urls)``    -> ``(results, errors)``; a 200 can still carry per-URL
  ``errors[]`` (e.g. a site that blocks fetching) — those are returned, never
  raised, so one blocked page doesn't sink the others.

Every call is logged to the cost ledger via ``log_api_call`` under providers
``tinyfish_search`` / ``tinyfish_fetch``. Logs never contain the query, URLs,
or page text (PII / hostile content) — ids, counts and status only.

``MOCK_EXTERNAL_APIS=true`` returns deterministic fakes with no network.

NOTE (KG-2): request/response shapes follow docs.tinyfish.ai; not yet confirmed
by a live call. Parsing stays tolerant of missing/renamed keys.
"""
from __future__ import annotations

import time
from typing import Any

import httpx
import structlog
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from apps.api.config import settings
from apps.api.services.usage_logger import log_api_call

logger = structlog.get_logger()

# Documented endpoints (docs.tinyfish.ai, verified 25-10-26) — no path suffix.
TINYFISH_SEARCH_URL = "https://api.search.tinyfish.ai"
TINYFISH_FETCH_URL = "https://api.fetch.tinyfish.ai"

_TRANSIENT_HTTP_STATUSES = {429, 500, 502, 503, 504}


class TinyFishError(Exception):
    """Non-transient TinyFish failure (bad key, 4xx, unparseable body)."""


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _TRANSIENT_HTTP_STATUSES
    return False


_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception(_is_transient),
    reraise=True,
)


def _headers(json_body: bool = False) -> dict[str, str]:
    h = {"X-API-Key": settings.tinyfish_api_key or "", "Accept": "application/json"}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


# ───────────────────────────── mock fixtures ──────────────────────────────


def _mock_search(query: str) -> list[dict[str, str]]:
    # Deterministic: derived from the query only. Hosts are example.* so no
    # real person is ever implied.
    slug = "-".join(query.lower().split())[:60] or "unknown"
    words = query.split()
    company = words[-1] if words else ""
    return [
        {
            "url": f"https://www.linkedin.com/in/{slug}",
            "title": f"{query} | LinkedIn",
            "snippet": f"Head of Growth at {company}.",
        },
        {
            "url": f"https://example.com/team/{slug}",
            "title": f"Team — {company}",
            "snippet": f"{query} leads growth at {company}.",
        },
    ]


def _mock_fetch(urls: list[str]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    results = [
        {"url": u, "text": f"Profile page. Title: Head of Growth. Source: {u}"}
        for u in urls
    ]
    return results, []


# ───────────────────────────── response parsing ───────────────────────────


def _parse_search(body: Any) -> list[dict[str, str]]:
    items = body.get("results") if isinstance(body, dict) else body
    out: list[dict[str, str]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("link")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        out.append({
            "url": url,
            "title": str(item.get("title") or ""),
            "site_name": str(item.get("site_name") or ""),
            "snippet": str(item.get("snippet") or item.get("description") or ""),
        })
    return out


def _parse_fetch(body: Any) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if not isinstance(body, dict):
        raise TinyFishError("fetch: unexpected body type")
    results: list[dict[str, str]] = []
    for item in body.get("results") or []:
        if not isinstance(item, dict):
            continue
        text = item.get("text") or item.get("content") or item.get("markdown")
        url = item.get("url")
        final_url = item.get("final_url") or url
        if isinstance(url, str) and isinstance(text, str) and text.strip():
            results.append({"url": url, "final_url": str(final_url), "text": text})
    errors: list[dict[str, str]] = []
    for item in body.get("errors") or []:
        if isinstance(item, dict):
            errors.append({
                "url": str(item.get("url") or ""),
                "error": str(item.get("error") or item.get("message") or "error")[:200],
            })
    return results, errors


# ───────────────────────────── HTTP calls ─────────────────────────────────


@_retry
async def _http_search(query: str, domain_type: str) -> Any:
    async with httpx.AsyncClient(timeout=settings.tinyfish_timeout_s) as client:
        resp = await client.get(
            TINYFISH_SEARCH_URL,
            params={"query": query, "domain_type": domain_type},
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


@_retry
async def _http_fetch(urls: list[str]) -> Any:
    async with httpx.AsyncClient(timeout=settings.tinyfish_timeout_s) as client:
        resp = await client.post(
            TINYFISH_FETCH_URL,
            json={"urls": urls[:10], "format": "markdown"},
            headers=_headers(json_body=True),
        )
        resp.raise_for_status()
        return resp.json()


async def search(
    query: str,
    *,
    domain_type: str = "web",
    site_id: str | None = None,
    visitor_id: str | None = None,
) -> list[dict[str, str]]:
    """Web search. Raises on HTTP failure (after retries) — callers are non-fatal."""
    if settings.mock_external_apis:
        return _mock_search(query)

    started = time.monotonic()
    success = False
    try:
        body = await _http_search(query, domain_type)
        results = _parse_search(body)
        success = True
        return results
    except ValueError as exc:  # JSON decode
        raise TinyFishError("search: invalid json") from exc
    finally:
        await log_api_call(
            provider="tinyfish_search",
            category="enrichment",
            operation=f"search:{domain_type}",
            success=success,
            site_id=site_id,
            visitor_id=visitor_id,
            response_time_ms=int((time.monotonic() - started) * 1000),
        )


async def fetch(
    urls: list[str],
    *,
    site_id: str | None = None,
    visitor_id: str | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Fetch page text for ``urls``. Returns ``(results, errors)``."""
    if not urls:
        return [], []
    if settings.mock_external_apis:
        return _mock_fetch(urls)

    started = time.monotonic()
    success = False
    try:
        body = await _http_fetch(urls)
        results, errors = _parse_fetch(body)
        success = True
        if errors:
            logger.info("tinyfish_fetch_partial_errors", ok=len(results), errors=len(errors))
        return results, errors
    except ValueError as exc:
        raise TinyFishError("fetch: invalid json") from exc
    finally:
        await log_api_call(
            provider="tinyfish_fetch",
            category="enrichment",
            operation="fetch",
            success=success,
            units=len(urls),
            site_id=site_id,
            visitor_id=visitor_id,
            response_time_ms=int((time.monotonic() - started) * 1000),
        )
