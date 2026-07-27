"""Decide whether a request is worth logging, and persist it off the hot path.

Split from the middleware on purpose: the middleware owns ASGI plumbing (buffering
bodies, wrapping send), this module owns the POLICY (what counts as a
drop/flag) and the WRITE. That keeps the policy unit-testable without an ASGI
scope, matching how ``ingest_velocity.evaluate_velocity`` is a pure function with
a thin I/O wrapper around it.

Write posture: ``persist_log`` is dispatched as a detached asyncio task with its
OWN session. A logging failure must never turn a successful request into a 500,
so every path here swallows its exceptions after recording them via structlog.
"""

import json
import random
from typing import Any

import structlog

from apps.api.config import settings
from apps.api.services.log_redaction import redact, redact_headers

logger = structlog.get_logger()

# Reason codes. Ordered by precedence in `classify` — the first match wins, so a
# bot-dropped request that also 4xx'd is reported as the drop, which is the more
# specific fact.
REASON_EXCEPTION = "exception"
REASON_BOT_DROP = "bot_drop"
REASON_ABUSE_FLAG = "abuse_flag"
REASON_RATE_LIMITED = "rate_limited"
REASON_HTTP_ERROR = "http_error"
REASON_SAMPLED = "sampled"

# Marker used when a body is not JSON (or was cut short). Keeps the JSONB column
# a single uniform shape so the viewer renders one thing.
_RAW_KEY = "__raw__"


def excluded_paths() -> frozenset[str]:
    """Path PREFIXES the middleware never logs, from the comma-separated setting."""
    raw = settings.request_log_exclude_paths or ""
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def is_excluded(path: str) -> bool:
    """Prefix match, not exact match.

    Exact matching would exclude the log list endpoint but still capture its own
    ``/stats`` and ``/{log_id}`` sub-routes — so browsing the viewer would
    generate the very rows being browsed. A prefix covers the whole router in one
    entry.
    """
    return any(path.startswith(prefix) for prefix in excluded_paths())


def classify(
    status_code: int,
    *,
    explicit_reason: str | None = None,
    sample_roll: float | None = None,
) -> str | None:
    """Return a reason code, or ``None`` when this request should not be logged.

    ``explicit_reason`` is what a route set on ``request.state.log_reason`` — the
    only way to capture a "silent" drop, since the ingest bot filter returns a
    perfectly ordinary 204 that is indistinguishable from success by status alone.

    ``sample_roll`` is injected rather than drawn here so the function stays pure
    and testable; the caller passes ``random.random()``.
    """
    if explicit_reason:
        return explicit_reason
    if status_code >= 500:
        return REASON_EXCEPTION
    if status_code == 429:
        return REASON_RATE_LIMITED
    if status_code >= 400:
        return REASON_HTTP_ERROR

    rate = settings.request_log_sample_rate
    if rate > 0 and sample_roll is not None and sample_roll < rate:
        return REASON_SAMPLED
    return None


def should_log(status_code: int, path: str, explicit_reason: str | None = None) -> str | None:
    """Full gate: flag on, path not excluded, and `classify` returns a reason."""
    if not settings.request_log_enabled:
        return None
    if is_excluded(path):
        return None
    return classify(
        status_code,
        explicit_reason=explicit_reason,
        sample_roll=random.random(),
    )


def decode_body(raw: bytes | None, max_bytes: int) -> tuple[Any, bool]:
    """Decode captured bytes into a redacted JSON-serializable value.

    Returns ``(value, truncated)``. A body that is not valid JSON — form posts,
    plain text, binary — is preserved as ``{"__raw__": "<decoded text>"}`` rather
    than dropped, because a malformed body is often exactly what is being
    debugged.
    """
    if not raw:
        return None, False

    truncated = len(raw) > max_bytes
    chunk = raw[:max_bytes]

    try:
        text = chunk.decode("utf-8", errors="replace")
    except Exception:
        return {_RAW_KEY: "<undecodable bytes>"}, truncated

    if truncated:
        # A cut-short body cannot parse as JSON; keep the prefix as text so the
        # operator still sees the beginning of the payload.
        return {_RAW_KEY: text}, True

    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return {_RAW_KEY: redact(text)}, truncated

    redacted = redact(parsed)
    # JSONB accepts objects and arrays; a bare scalar is wrapped so the column
    # shape stays uniform.
    if not isinstance(redacted, (dict, list)):
        return {_RAW_KEY: redacted}, truncated
    return redacted, truncated


async def persist_log(
    *,
    method: str,
    path: str,
    query_params: dict[str, str] | None,
    status_code: int,
    duration_ms: float,
    reason: str,
    reason_detail: str | None,
    site_id: str | None,
    user_id: Any | None,
    client_ip: str | None,
    user_agent: str | None,
    headers: dict[str, str] | None,
    request_body_raw: bytes | None,
    response_body_raw: bytes | None,
) -> None:
    """Write one RequestLog row. Never raises — logging must not break a request."""
    try:
        from apps.api.models.database import async_session
        from apps.api.models.request_log import RequestLog

        max_bytes = settings.request_log_max_body_bytes
        req_body, req_trunc = decode_body(request_body_raw, max_bytes)
        res_body, res_trunc = decode_body(response_body_raw, max_bytes)

        async with async_session() as db:
            db.add(
                RequestLog(
                    method=method,
                    path=path[:500],
                    query_params=redact(query_params) if query_params else None,
                    status_code=status_code,
                    duration_ms=round(duration_ms, 2),
                    reason=reason[:40],
                    reason_detail=reason_detail,
                    site_id=site_id[:50] if site_id else None,
                    user_id=user_id,
                    client_ip=client_ip[:45] if client_ip else None,
                    user_agent=user_agent,
                    request_headers=redact_headers(headers) if headers else None,
                    request_body=req_body,
                    response_body=res_body,
                    truncated=req_trunc or res_trunc,
                )
            )
            await db.commit()
    except Exception as exc:
        # Deliberately swallowed: a full disk or a schema drift on the log table
        # must degrade observability, never availability.
        logger.warning("request_log_write_failed", error=str(exc), path=path)
