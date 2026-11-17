"""Sentry for the Beam API.

The SDK stays off unless ``SENTRY_DSN`` is set. Nothing here reads a
hardcoded DSN, and a missing or bad DSN must not stop the process.
"""

from __future__ import annotations

import os
import warnings
from typing import Any, Optional

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

# Errors plus a low trace sample. Not configurable on purpose.
TRACES_SAMPLE_RATE = 0.1

# Header names (or substrings) that must never leave the process.
_SENSITIVE_HEADER_MARKERS = (
    "authorization",
    "cookie",
    "api-key",
    "api_key",
)


def _clean(value: Optional[str]) -> str:
    return (value or "").strip()


def release_from_env() -> Optional[str]:
    """Commit SHA already injected by the host, when there is one.

    Railway sets ``RAILWAY_GIT_COMMIT_SHA``. ``VERCEL_GIT_COMMIT_SHA`` is
    the same idea if this process is ever started with Vercel's env.
    """
    for name in ("RAILWAY_GIT_COMMIT_SHA", "VERCEL_GIT_COMMIT_SHA"):
        value = _clean(os.environ.get(name))
        if value:
            return value
    return None


def _sensitive_header(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in _SENSITIVE_HEADER_MARKERS)


def strip_query(url: str) -> str:
    """Drop the query string and fragment; they can carry tokens or emails."""
    for sep in ("?", "#"):
        url = url.split(sep, 1)[0]
    return url


def _scrub_breadcrumbs(event: dict) -> None:
    crumbs = event.get("breadcrumbs")
    values = crumbs.get("values") if isinstance(crumbs, dict) else crumbs
    if not isinstance(values, list):
        return
    for crumb in values:
        data = crumb.get("data") if isinstance(crumb, dict) else None
        if not isinstance(data, dict):
            continue
        for key in ("url", "from", "to"):
            if isinstance(data.get(key), str):
                data[key] = strip_query(data[key])
        data.pop("http.query", None)


def scrub_sentry_event(event: dict, _hint: dict | None = None) -> dict:
    """Drop auth material and anything on the user except an id.

    ``send_default_pii=False`` already limits what the SDK attaches. This
    runs as well so a later integration cannot put a cookie, an
    Authorization header, or an email back on the event.
    """
    request = event.get("request")
    if isinstance(request, dict):
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                key: value
                for key, value in headers.items()
                if not _sensitive_header(str(key))
            }
        request.pop("cookies", None)
        # Ingest and dashboard bodies carry visitor emails and other PII.
        request.pop("data", None)
        request.pop("query_string", None)
        if isinstance(request.get("url"), str):
            request["url"] = strip_query(request["url"])
    _scrub_breadcrumbs(event)

    user = event.get("user")
    if isinstance(user, dict):
        user_id = user.get("id")
        if user_id:
            event["user"] = {"id": str(user_id)}
        else:
            event.pop("user", None)
    return event


def init_sentry(
    dsn: Optional[str] = None,
    *,
    environment: Optional[str] = None,
    transport: Any = None,
) -> bool:
    """Enable Sentry when ``dsn`` is non-empty. Returns whether it is on.

    ``dsn=None`` reads ``SENTRY_DSN``. An empty string stays off and does
    not call ``sentry_sdk.init``. Failures are swallowed: monitoring must
    not take the API down.
    """
    if dsn is None:
        dsn = os.environ.get("SENTRY_DSN", "")
    resolved = _clean(dsn)
    if not resolved:
        return False

    env_name = _clean(environment if environment is not None else os.environ.get("APP_ENV"))
    try:
        options: dict[str, Any] = {
            "dsn": resolved,
            "environment": env_name or None,
            "release": release_from_env(),
            # SDK 2.75 still honors this. data_collection below is the
            # explicit off-switch (it wins when both are set) so cookies,
            # request bodies, and local variables are not collected.
            "send_default_pii": False,
            "include_local_variables": False,
            "max_request_body_size": "never",
            "traces_sample_rate": TRACES_SAMPLE_RATE,
            "data_collection": {
                "user_info": False,
                "cookies": {"mode": "off"},
                "http_headers": {
                    "request": {
                        "mode": "denylist",
                        "terms": ["cookie", "authorization", "api-key", "api_key"],
                    }
                },
                "http_bodies": [],
                "stack_frame_variables": False,
                "gen_ai": {"inputs": False, "outputs": False},
                "database_query_data": False,
                "queues": False,
            },
            "integrations": [
                StarletteIntegration(),
                FastApiIntegration(),
                # Do not ship structlog lines. Exceptions still report.
                LoggingIntegration(level=None, event_level=None),
            ],
            "before_send": scrub_sentry_event,
            "before_send_transaction": scrub_sentry_event,
        }
        if transport is not None:
            options["transport"] = transport
        # SDK 2.75 warns that send_default_pii is ignored once data_collection
        # is set. Both stay: the flag is the requested switch, data_collection
        # is what this version actually applies.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=".*send_default_pii.*",
                category=DeprecationWarning,
            )
            sentry_sdk.init(**options)
        return bool(sentry_sdk.is_initialized())
    except Exception:
        return False


def bind_clerk_user(clerk_user_id: Optional[str]) -> None:
    """Attach the Clerk user id only. No email, name, or IP.

    No-op when Sentry is off, so request auth never depends on it.
    """
    if not clerk_user_id:
        return
    try:
        if not sentry_sdk.get_client().is_active():
            return
        sentry_sdk.set_user({"id": clerk_user_id})
    except Exception:
        return
