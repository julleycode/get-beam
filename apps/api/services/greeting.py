"""On-site company greeting — eligibility + cache-only company read.

Public, unauthenticated hot path (GET /api/v1/greeting). It must never become
an IP→company oracle, never be person-level, and never spend money:

* Allowed reads ONLY: the ``sites`` / ``visitors`` rows, Redis
  ``ip_privacy:{ip}`` (direct GET, judged with ``is_proxy_or_vpn``), Redis
  ``greeting_company:{ip}`` (this module's own cache) and ``lookup_ip_org``
  (local DB, inert unless ``ip_org_lookup_enabled``).
* FORBIDDEN: ``resolve_company_cached``, ``check_ip_privacy``, ipinfo, PDL,
  rDNS — they make live/paid calls and writes.
* Only the per-IP company lookup is cached. The show decision (flags, site,
  Origin, visitor) is recomputed on every request, so a cached hit for visitor A
  can never leak a greeting to a do_not_resolve visitor B on the same IP.
* The response is owner-template text only; the reason code is for logs only.
"""

from __future__ import annotations

import ipaddress
import json
from typing import Any
from urllib.parse import urlsplit

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.prompt_safety import clean_text
from apps.api.config import settings
from apps.api.models.site import Site
from apps.api.models.visitor import Visitor
from apps.api.services.company_resolver import is_privacy_relay_ip, is_proxy_or_vpn
from apps.api.services.ip_org_lookup import lookup_ip_org

logger = structlog.get_logger()

GREETING_TEXT_MAX = 200
VISITOR_ID_MAX = 100
COMPANY_NAME_MAX = 80
COMPANY_CACHE_TTL_S = 3600
COMPANY_CACHE_PREFIX = "greeting_company:"
DEFAULT_TEMPLATE_TEXT = "Welcome, {company} team!"
# Mock mode only: TEST-NET-3 (RFC 5737) resolves to a deterministic "Acme" so
# dev/demo runs keyless. Replaces ONLY the company lookup step (E8).
_MOCK_NET = ipaddress.ip_network("203.0.113.0/24")
MOCK_COMPANY = "Acme"

_ALLOWED_KEYS = ("show", "template_id", "text", "cta_url")


def hidden() -> dict[str, Any]:
    return {"show": False}


def normalize_host(value: str | None) -> str | None:
    """Origin / Site.url → bare host: lowercase, no port, one leading ``www.`` dropped.

    A schemeless value (``Site.url`` allows it) gets ``https://`` prepended.
    Returns None for missing / ``null`` / unparseable values.
    """
    if not value:
        return None
    v = value.strip()
    if not v or v.lower() == "null":
        return None
    if "://" not in v:
        v = "https://" + v
    try:
        host = urlsplit(v).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host or None


def origin_matches(origin: str | None, site_url: str | None) -> bool:
    o = normalize_host(origin)
    s = normalize_host(site_url)
    return bool(o and s and o == s)


def _sanitize_company(name: str) -> str:
    cleaned = clean_text(name, COMPANY_NAME_MAX)
    # No placeholder smuggling and no markup-ish characters in display text.
    return cleaned.replace("{", "").replace("}", "").strip()


def render(site: Site, company: str) -> dict[str, Any] | None:
    """Default template only (v1). Returns the allow-listed payload or None."""
    tpl = (site.greeting_templates or {}).get("default") if isinstance(
        site.greeting_templates, dict
    ) else None
    text = DEFAULT_TEMPLATE_TEXT
    cta_url = None
    if isinstance(tpl, dict):
        if isinstance(tpl.get("text"), str) and tpl["text"].strip():
            text = tpl["text"]
        if isinstance(tpl.get("cta_url"), str) and tpl["cta_url"].startswith("https://"):
            cta_url = tpl["cta_url"]
    name = _sanitize_company(company)
    if not name:
        return None
    out = text.replace("{company}", name).replace("<", "").replace(">", "")
    out = out.strip()[:GREETING_TEXT_MAX]
    if not out:
        return None
    return {"show": True, "template_id": "default", "text": out, "cta_url": cta_url}


async def _privacy_flagged(redis: Any, ip: str) -> bool:
    """Cached IPinfo privacy only (no live check — U1). Malformed → miss."""
    if redis is None:
        return False
    try:
        raw = await redis.get(f"ip_privacy:{ip}")
    except Exception:
        return False
    if not raw:
        return False
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    return is_proxy_or_vpn(data)


async def _company_for_ip(db: AsyncSession, redis: Any, ip: str) -> str | None:
    """Real-org display name for ``ip`` or None. Cached per IP for 1h."""
    key = f"{COMPANY_CACHE_PREFIX}{ip}"
    if redis is not None:
        try:
            raw = await redis.get(key)
        except Exception:
            raw = None
        if raw:
            try:
                cached = json.loads(raw)
            except (TypeError, ValueError):
                cached = None
            if isinstance(cached, dict):
                name = cached.get("n")
                if cached.get("k") == "org" and isinstance(name, str) and name:
                    return name
                return None

    name: str | None = None
    kind: str | None = None
    match = await lookup_ip_org(db, ip)
    if match:
        kind = match.get("org_kind")
        org_name = match.get("org_name")
        if kind == "org" and isinstance(org_name, str) and org_name.strip():
            name = org_name.strip()

    if redis is not None:
        try:
            await redis.set(
                key, json.dumps({"n": name, "k": kind}), ex=COMPANY_CACHE_TTL_S
            )
        except Exception:
            pass
    return name


async def decide_greeting(
    db: AsyncSession,
    redis: Any,
    site_id: str | None,
    ip: str | None,
    origin: str | None,
    vid: str | None,
) -> tuple[bool, str, dict[str, Any]]:
    """Return ``(show, reason, payload)``. ``payload`` keys ⊆ the allow-list."""
    if not settings.onsite_greeting_enabled:
        return False, "flag_off", hidden()
    if not site_id or len(site_id) > 50:
        return False, "bad_site", hidden()
    if vid is not None and len(vid) > VISITOR_ID_MAX:
        return False, "bad_vid", hidden()

    site = (
        await db.execute(select(Site).where(Site.site_id == site_id))
    ).scalar_one_or_none()
    if site is None:
        return False, "unknown_site", hidden()
    if not site.greeting_enabled:
        return False, "site_off", hidden()
    if not origin_matches(origin, site.url):
        return False, "origin", hidden()

    if vid:
        row = (
            await db.execute(
                select(
                    Visitor.do_not_resolve,
                    Visitor.is_bot_suspect,
                    Visitor.is_abuse_flagged,
                ).where(Visitor.site_id == site_id, Visitor.visitor_id == vid)
            )
        ).first()
        if row is not None and any(bool(x) for x in row):
            return False, "visitor_blocked", hidden()

    if not ip:
        return False, "no_ip", hidden()
    if is_privacy_relay_ip(ip):
        return False, "privacy_relay", hidden()
    if await _privacy_flagged(redis, ip):
        return False, "vpn_proxy", hidden()

    # Step 2d — company lookup (the ONLY step mock mode may replace).
    company: str | None
    try:
        in_mock_net = ipaddress.ip_address(ip) in _MOCK_NET
    except ValueError:
        in_mock_net = False
    if settings.mock_external_apis and in_mock_net:
        company = MOCK_COMPANY
    else:
        company = await _company_for_ip(db, redis, ip)
    if not company:
        return False, "no_company", hidden()

    payload = render(site, company)
    if payload is None:
        return False, "no_company", hidden()
    payload = {k: payload[k] for k in _ALLOWED_KEYS}
    return True, "shown", payload
