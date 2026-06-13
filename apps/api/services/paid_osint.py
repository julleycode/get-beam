"""Paid OSINT fallback — OSINT Industries (stage F of the pipeline).

Only invoked when the free stages (OSINT scan + Maigret + rule-base + Gemini)
come up short, AND a system API key is configured, AND the daily paid budget
isn't exhausted. Returns clean social profiles (Instagram, Telegram, LinkedIn,
etc.) with usernames/avatars. 1 credit per lookup.

Cost guards:
  - 30-day Redis cache by email hash → never pay twice for the same email.
  - Per-site/day budget counter (enforced by the caller via usage_limits).

NOTE: the public API docs are gated (403), so the endpoint + response mapping
below follow the community-documented contract (`GET /v2/request`, `api-key`
header, a list of per-module results). Confirm/adjust `_API_URL`, `_AUTH_HEADER`,
and `_parse_response` against a real response once the key is provided — they are
isolated here on purpose.
"""

from __future__ import annotations

import hashlib
import json as jsonlib
from datetime import datetime, timezone

import httpx
import structlog

from apps.api.config import settings
from apps.api.services.osint_scanner import OsintAccount
from apps.api.services.redis_client import get_redis

logger = structlog.get_logger()

# --- API contract (confirm against a live response when the key is available) ---
_API_URL = "https://api.osint.industries/v2/request"
_AUTH_HEADER = "api-key"
_LOOKUP_TIMEOUT = 60.0
PAID_CACHE_TTL_SECONDS = 30 * 86400  # 30 days — never re-pay for the same email
_CACHE_PREFIX = "osint:paid:"


def is_configured() -> bool:
    """True if a paid OSINT Industries key is set."""
    return bool(settings.osint_industries_api_key)


def _cache_key(email: str) -> str:
    digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    return f"{_CACHE_PREFIX}{digest}"


async def _cache_get(email: str) -> dict | None:
    try:
        raw = await get_redis().get(_cache_key(email))
    except Exception:
        return None
    if not raw:
        return None
    try:
        return jsonlib.loads(raw)
    except (ValueError, TypeError):
        return None


async def _cache_set(email: str, blob: dict) -> None:
    try:
        await get_redis().set(
            _cache_key(email), jsonlib.dumps(blob, default=str),
            ex=PAID_CACHE_TTL_SECONDS,
        )
    except Exception:
        logger.debug("paid_osint_cache_set_failed", email_prefix=email[:5])


def _parse_response(payload) -> list[OsintAccount]:
    """Map an OSINT Industries response → OsintAccount list. Defensive: tolerates
    list-of-modules or {"results"/"data": [...]} shapes."""
    items = payload
    if isinstance(payload, dict):
        items = payload.get("results") or payload.get("data") or payload.get("modules") or []
    if not isinstance(items, list):
        return []

    accounts: list[OsintAccount] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        platform = item.get("module") or item.get("schemaModule") or item.get("name") or ""
        status = str(item.get("status", "")).lower()
        data = item.get("data") if isinstance(item.get("data"), dict) else item
        # Skip explicit not-found modules.
        if status in ("not_found", "notfound", "error", "failed"):
            continue
        username = (
            data.get("username") or data.get("handle") or data.get("name")
            or data.get("full_name")
        )
        url = data.get("url") or data.get("profile_url") or data.get("link")
        if not platform and not url:
            continue
        dedup = (str(platform).lower(), str(url or username or "").lower())
        if dedup in seen:
            continue
        seen.add(dedup)
        extra = {
            k: data[k]
            for k in ("username", "full_name", "name", "profile_pic", "picture",
                      "avatar", "creation_date", "account_age", "location", "bio")
            if isinstance(data, dict) and data.get(k)
        }
        accounts.append(
            OsintAccount(
                site_name=str(platform).title() or "OSINT Industries",
                category="social",
                url=url,
                kind="profile",
                confidence="confirmed",
                source_engine="osint-industries",
                extra=extra,
            )
        )
    return accounts


async def lookup(email: str) -> dict:
    """Look up an email via OSINT Industries. Returns:
        {"used": bool, "provider": "osint-industries", "accounts": [...],
         "found": int, "cached": bool, "error": str | None}

    `used=True` means a real (billable) request was made. Cache hits set
    `used=False`. Never raises.
    """
    email = (email or "").strip()
    result = {
        "used": False, "provider": "osint-industries", "accounts": [],
        "found": 0, "cached": False, "error": None,
    }
    if not email:
        result["error"] = "no email"
        return result
    if not is_configured():
        result["error"] = "no api key"
        return result

    cached = await _cache_get(email)
    if cached is not None:
        cached["cached"] = True
        cached["used"] = False
        return cached

    try:
        async with httpx.AsyncClient(timeout=_LOOKUP_TIMEOUT) as client:
            resp = await client.get(
                _API_URL,
                headers={_AUTH_HEADER: settings.osint_industries_api_key},
                params={"type": "email", "query": email, "timeout": 40},
            )
    except Exception as e:
        logger.warning("paid_osint_request_failed", email_prefix=email[:5], err=str(e))
        result["error"] = "request failed"
        return result

    result["used"] = True  # a billable request was made (even if it found nothing)
    if resp.status_code != 200:
        logger.warning("paid_osint_http_error", status=resp.status_code, email_prefix=email[:5])
        result["error"] = f"http {resp.status_code}"
        return result

    try:
        accounts = _parse_response(resp.json())
    except Exception as e:
        logger.warning("paid_osint_parse_failed", err=str(e), email_prefix=email[:5])
        result["error"] = "parse failed"
        return result

    result["accounts"] = [a.to_dict() for a in accounts]
    result["found"] = len(accounts)
    result["fetched_at"] = datetime.now(timezone.utc).isoformat()
    await _cache_set(email, result)  # cache even empty results (don't re-pay)
    logger.info("paid_osint_lookup", email_prefix=email[:5], found=result["found"])
    return result
