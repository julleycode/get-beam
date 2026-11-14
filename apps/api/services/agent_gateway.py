"""Agent-gateway assembly layer (agent-gateway Phase 2).

The SINGLE source of truth for every public agent-facing surface. Both the REST
endpoints (``routers/agent_gateway.py``) and the JSON-RPC MCP server
(``routers/agent_mcp.py``) call these functions — nothing re-derives a manifest
or an offers list on its own. That is what keeps the two surfaces from drifting
(acceptance criterion AC9).

Two hard rules, enforced here rather than at each call site:

1. ``resolve_public_profile`` is the ONLY way in. It returns ``None`` for an
   unknown site, a foreign site, a site with no profile, a site whose profile is
   disabled, and for the global flag being off — all five cases are
   indistinguishable to the caller, which then answers 404. Never 403, never a
   different status per case: an attacker must not be able to probe which
   site_ids exist.
2. The assembly functions only ever read customer-authored fields. No
   ``user_id``, no internal UUIDs, no counts, no operational Site columns.

``record_gateway_visit`` is the one write in this module: it logs a recognized
agent's call to a gateway surface into the two agent-only tables, so the surface
built to attract AI agents is visible to Beam's own agent detection.
"""

import hashlib
import json
import re
import uuid

import structlog
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.agent_profile import AgentProfile
from apps.api.models.site import Site
from apps.api.services.agent_classifier import classify_agent, classify_tier
from apps.api.services.agent_visit_persistence import (
    persist_agent_fetch_event,
    persist_agent_visit,
)
from apps.api.services.ip_resolution import resolve_client_ip
from apps.api.schemas.agent_gateway import (
    CAPABILITY_NAMESPACE,
    AgentManifest,
    AgentOfferOut,
    AgentOffersFeed,
    ManifestCapability,
    ManifestSeller,
)

logger = structlog.get_logger()

# Shared with the customer-facing llms.txt / ai-plugin.json routes on the web
# app (apps/web/src/app/llms.txt/route.ts). Same string, different transport.
# The 24h stale-while-revalidate window is an ACCEPTED trade-off: a dashboard
# edit can take up to ~24h to fully propagate. Do not shorten it here in
# isolation — that would diverge the two surfaces.
AGENT_CACHE_CONTROL = "public, max-age=0, s-maxage=3600, stale-while-revalidate=86400"

# Cache posture for offers.json while link markers are enabled. A marker is
# minted per fetch, so a SHARED cache would serve the first agent's marker to
# every agent behind it and attribute the human to the wrong fetch -- a worse
# answer than the temporal guess the marker replaces. Only offers.json carries
# markers, so only offers.json pays this; manifest.json and llms.txt keep
# AGENT_CACHE_CONTROL above.
AGENT_OFFERS_MARKED_CACHE_CONTROL = "private, no-store"

# Surface labels stored as the ``page_path`` of a gateway visit. Fixed literals,
# never the raw request path -- the real path embeds the site_id, which would
# make every row unique and destroy the rollup. The MCP labels carry the tool
# name because "an agent asked for pricing" is a materially stronger signal than
# "an agent called the MCP server".
SURFACE_MANIFEST = "/agent/manifest.json"
SURFACE_OFFERS = "/agent/offers.json"
SURFACE_LLMS_TXT = "/agent/llms.txt"
SURFACE_MCP_TOOLS_LIST = "/agent/mcp/tools-list"


def mcp_tool_surface(tool_name: str) -> str:
    """Surface label for one MCP tool call, e.g. ``/agent/mcp/get_pricing``.

    Callers pass only names already validated against ``MCP_TOOLS``, so the label
    is drawn from a fixed set and never carries caller-controlled text.
    """
    return f"/agent/mcp/{tool_name}"


async def record_gateway_visit(
    db: AsyncSession, request: Request, site_id: str, surface: str
) -> uuid.UUID | None:
    """Record a recognized AI agent's call to a public gateway surface.

    Returns the ``agent_fetch_events`` row id when one was written, else ``None``
    (unrecognized UA, or a failed best-effort write). The offers route mints its
    per-fetch link marker from it; every other caller ignores it.

    Without this the gateway is invisible to Beam's own agent detection: an agent
    could read the manifest, pull the offers feed and query the MCP server, and
    none of it would appear on the Agents dashboard -- even though an MCP tool
    call is the most deliberate "an AI is researching this business" signal
    available, stronger than any User-Agent string.

    Only recognized vendor UAs are recorded, matching the ingest and beacon
    paths: an unrecognized caller yields no classification, so there is no vendor
    to attribute the row to and inventing one would corrupt the vendor rollup.
    An MCP client with a generic UA is therefore still invisible -- a known gap,
    not an oversight.

    Writes go to the two agent-only tables via the existing fail-open persistence
    helpers, so this never creates or touches a Visitor or an IdentifiedVisitor.
    Wrapped end to end because these are public unauthenticated read routes: a
    bookkeeping failure must never turn an agent's manifest fetch into a 500.
    """
    try:
        classification = classify_agent(request.headers.get("user-agent"))
        if classification is None:
            return None
        tier = classify_tier(classification.product_or_ua_token)
        ip_address = resolve_client_ip(request)
        await persist_agent_visit(db, site_id, classification, ip_address, surface)
        return await persist_agent_fetch_event(
            db, site_id, classification, tier, ip_address, surface
        )
    except Exception:
        # Keys only -- never the raw UA or the IP (PII/GDPR guard).
        logger.warning(
            "agent_gateway_visit_record_failed", site_id=site_id, surface=surface
        )
        return None

CAPABILITY_VERSION = "1"


async def resolve_public_profile(
    db: AsyncSession, site_id: str
) -> tuple[Site, AgentProfile] | None:
    """Return ``(site, profile)`` iff this site's agent surface is publicly live.

    ``None`` — meaning the caller must answer 404 — for ALL of: global flag off,
    unknown site_id, no profile row, profile disabled. Callers must not
    distinguish between these cases in their response.
    """
    if not settings.agent_gateway_enabled:
        return None

    row = (
        await db.execute(
            select(Site, AgentProfile)
            .join(AgentProfile, AgentProfile.site_id == Site.site_id)
            .where(Site.site_id == site_id)
            .limit(1)
        )
    ).first()
    if row is None:
        return None

    site, profile = row
    if not profile.enabled:
        return None
    return site, profile


def build_manifest(site: Site, profile: AgentProfile) -> AgentManifest:
    """UCP-compatible capability manifest.

    ``endpoint`` stays None on every capability: Phase 1+2 publish the
    declaration only, the action endpoint that honors it is Phase 3. An agent
    must not infer a callable URL from a declaration.
    """
    capabilities = [
        ManifestCapability(
            name=f"{CAPABILITY_NAMESPACE}.{cap}",
            version=CAPABILITY_VERSION,
            endpoint=None,
        )
        for cap in (profile.capabilities or [])
    ]

    base = f"/api/v1/agent/{site.site_id}"
    return AgentManifest(
        site_id=site.site_id,
        seller=ManifestSeller(
            name=site.name,
            url=site.url,
            description=profile.long_description or site.description,
            tagline=profile.tagline,
            contact_email=profile.contact_email,
            privacy_policy_url=profile.privacy_policy_url,
            tos_url=profile.tos_url,
        ),
        capabilities=capabilities,
        primary_cta=profile.primary_cta,
        endpoints={
            "manifest": f"{base}/manifest.json",
            "offers": f"{base}/offers.json",
            "llms_txt": f"{base}/llms.txt",
            "mcp": f"{base}/mcp",
        },
    )


def build_offers(site: Site, profile: AgentProfile) -> AgentOffersFeed:
    """ACP-feed-shaped offers list derived from the customer's ``offers`` JSONB."""
    entries: list[AgentOfferOut] = []
    for index, raw in enumerate(profile.offers or []):
        if not isinstance(raw, dict):
            # Defensive: the schema layer validates on write, but a row written
            # before/outside that path must not 500 a public read.
            continue
        name = raw.get("name")
        if not name:
            continue
        entries.append(
            AgentOfferOut(
                item_id=f"{site.site_id}-offer-{index + 1}",
                title=str(name),
                description=raw.get("billing_period"),
                url=raw.get("url"),
                price=raw.get("price"),
                currency=raw.get("currency"),
                billing_period=raw.get("billing_period"),
                availability=raw.get("availability"),
                seller_name=site.name,
                seller_url=site.url,
            )
        )

    return AgentOffersFeed(
        site_id=site.site_id,
        seller_name=site.name,
        seller_url=site.url,
        offers=entries,
    )


def build_llms_txt(site: Site, profile: AgentProfile) -> str:
    """Narrative form of the same data, for agents that read text not JSON."""
    lines: list[str] = [f"# {site.name}", ""]
    if profile.tagline:
        lines += [f"> {profile.tagline}", ""]

    body = profile.long_description or site.description
    if body:
        lines += [body, ""]

    offers = build_offers(site, profile).offers
    if offers:
        lines += ["## What we offer", ""]
        for offer in offers:
            parts = [f"- **{offer.title}**"]
            if offer.price:
                money = f"{offer.price} {offer.currency}".strip() if offer.currency else offer.price
                period = f" / {offer.billing_period}" if offer.billing_period else ""
                parts.append(f"— {money}{period}")
            if offer.availability:
                parts.append(f"({offer.availability})")
            if offer.url:
                parts.append(f"<{offer.url}>")
            lines.append(" ".join(parts))
        lines.append("")

    if profile.capabilities:
        lines += ["## What you can do here", ""]
        for cap in profile.capabilities:
            lines.append(f"- {cap.replace('_', ' ')}")
        lines.append("")

    if profile.primary_cta:
        lines += ["## Next step", "", profile.primary_cta, ""]

    links = [
        ("Website", site.url),
        ("Contact", profile.contact_email),
        ("Privacy policy", profile.privacy_policy_url),
        ("Terms of service", profile.tos_url),
    ]
    present = [(label, value) for label, value in links if value]
    if present:
        lines += ["## Links", ""]
        lines += [f"- {label}: {value}" for label, value in present]
        lines.append("")

    return "\n".join(lines)


# ── MCP read tools ────────────────────────────────────────────────────
# Deliberately thin wrappers over the SAME builders the REST routes use, so the
# two surfaces cannot drift (AC9).


def _maybe_qualified(profile: AgentProfile, params: dict | None) -> dict | None:
    """Return the customer-authored qualified answer for these params, if any.

    Only consulted when the qualification flag is on AND params are complete
    (the caller has already been gated by then). Reads the SEPARATE
    ``qualified_content`` JSONB column, keyed by ``use_case`` then
    ``evaluating_against``, falling back to a ``"default"`` bucket. Returns None
    when nothing matches — the base offers projection is served alone.
    """
    if not params:
        return None
    content = getattr(profile, "qualified_content", None)
    if not isinstance(content, dict) or not content:
        return None
    for key in (params.get("use_case"), params.get("evaluating_against"), "default"):
        if key and isinstance(content.get(key), (dict, list, str)):
            return {"qualified_answer": content[key]}
    return None


def tool_get_offers(site: Site, profile: AgentProfile, params: dict | None = None) -> dict:
    out = build_offers(site, profile).model_dump()
    extra = _maybe_qualified(profile, params)
    if extra:
        out.update(extra)
    return out


def tool_get_pricing(site: Site, profile: AgentProfile, params: dict | None = None) -> dict:
    """Price-only projection of the offers feed."""
    out = {
        "site_id": site.site_id,
        "pricing": [
            {
                "item_id": offer.item_id,
                "title": offer.title,
                "price": offer.price,
                "currency": offer.currency,
                "billing_period": offer.billing_period,
            }
            for offer in build_offers(site, profile).offers
        ],
    }
    extra = _maybe_qualified(profile, params)
    if extra:
        out.update(extra)
    return out


def tool_check_availability(
    site: Site, profile: AgentProfile, params: dict | None = None
) -> dict:
    """Availability-only projection of the offers feed."""
    out = {
        "site_id": site.site_id,
        "availability": [
            {
                "item_id": offer.item_id,
                "title": offer.title,
                "availability": offer.availability,
            }
            for offer in build_offers(site, profile).offers
        ],
    }
    extra = _maybe_qualified(profile, params)
    if extra:
        out.update(extra)
    return out


# Strict method allow-list for the JSON-RPC read-tool dispatcher. Anything not a
# key here (and not a conversion tool, see CONVERSION_TOOLS) gets -32601. The 3
# read tools now accept an optional ``params`` arg for the WS3 qualification
# gate — signature is (site, profile, params=None).
MCP_TOOLS = {
    "get_offers": tool_get_offers,
    "get_pricing": tool_get_pricing,
    "check_availability": tool_check_availability,
}


# ── WS3 agent-concierge: qualification gating + conversion tools ───────

from apps.api.agents import prompt_safety  # noqa: E402
from apps.api.schemas.agent_gateway import (  # noqa: E402
    REQUIRED_QUALIFICATION_PARAMS,
)

# The 2 zero-click conversion tools. Kept OUT of MCP_TOOLS on purpose: they are
# write-capable and async, dispatched via handle_conversion_tool, and their
# absence from MCP_TOOLS keeps the Phase-2 "no action tool exposed" invariant
# provable by inspecting MCP_TOOLS alone.
CONVERSION_TOOLS = ("request_quote", "book_demo")

# Per-field caps for prompt_safety.clean_text (Must-Fix 2). clean_text strips
# angle brackets (the codebase's established email-interpolation mitigation) and
# collapses whitespace, capping length. sanitize_profiles is NOT used here — its
# fixed _TEXT_FIELD_CAPS table does not include these fields and would silently
# no-op them.
_QUALIFICATION_CAPS = {
    "use_case": 200,
    "company_size": 100,
    "evaluating_against": 200,
    "note": 500,
}


def missing_qualification_params(params: dict | None) -> list[str]:
    """Return the required qualification params that are absent or blank."""
    if not isinstance(params, dict):
        return list(REQUIRED_QUALIFICATION_PARAMS)
    missing: list[str] = []
    for name in REQUIRED_QUALIFICATION_PARAMS:
        value = params.get(name)
        if not isinstance(value, str) or not value.strip():
            missing.append(name)
    return missing


def has_malformed_qualification_params(params: dict | None) -> bool:
    """True if any required qualification param is PRESENT but of the wrong type
    (e.g. an int) — the -32602 Invalid params case, distinct from a param being
    absent (which is the graceful needs_more_info case). An absent param is not
    malformed."""
    if not isinstance(params, dict):
        return False
    for name in REQUIRED_QUALIFICATION_PARAMS:
        if name in params and not isinstance(params[name], str):
            return True
    return False


# M2: resolved_company_domain originates from a reverse-DNS PTR record, which is
# controlled by whoever owns the client IP's rDNS — i.e. attacker-influenceable
# input that reaches the owner-notification email. A registrable domain is a
# strict, small grammar; anything that is not a well-formed domain (e.g. an
# injected "<script>…", an overlong blob) is dropped to None rather than stored
# or interpolated. Total length <= 253, labels 1-63 chars of [a-z0-9-] not
# starting/ending with a hyphen, at least two labels.
_DNS_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


def sanitize_resolved_domain(domain: str | None) -> str | None:
    """Return ``domain`` iff it is a well-formed registrable domain, else None.

    Applied at the write boundary (Must-Fix / M2) BEFORE the value is stored on
    AgentLead AND before it is interpolated into the owner email, so a hostile PTR
    can never reach either. Case-normalized; no angle brackets, no whitespace, no
    HTML can survive this grammar."""
    if not isinstance(domain, str):
        return None
    candidate = domain.strip().lower()
    if not candidate or not _DNS_DOMAIN_RE.match(candidate):
        return None
    return candidate


def truncate_ip(ip: str | None) -> str | None:
    """Coarsen an IP before it is stored on a lead: IPv4 -> /24, IPv6 -> /48.

    The full caller IP is personal data with no owner-facing use once the
    company lookup is done, so ``agent_leads.ip_address`` only ever holds the
    network prefix. Unparseable input stores nothing."""
    if not ip:
        return None
    import ipaddress

    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return None
    prefix = 24 if addr.version == 4 else 48
    return str(ipaddress.ip_network(f"{addr}/{prefix}", strict=False).network_address)


def _conversion_idempotency_key(
    site_id: str, tool_name: str, params: dict, caller: str | None
) -> str:
    """Stable hash of (site, tool, caller IP, normalized qualification params).

    The caller component matters: without it, two DIFFERENT agents that happen to
    send identical params inside the window collapse into one lead, silently
    dropping the second buyer. Identical retries from the SAME caller still
    collapse to one lead/one email (M3)."""
    norm = json.dumps(
        {k: params.get(k) for k in sorted(_QUALIFICATION_CAPS)},
        sort_keys=True,
        ensure_ascii=True,
    )
    raw = f"{site_id}|{tool_name}|{caller or '-'}|{norm}"
    return f"agent_conv_idem:{hashlib.sha256(raw.encode()).hexdigest()}"


async def _claim_idempotency_key(key: str) -> bool | None:
    """Atomically claim ``key`` (Redis SET NX EX).

    Returns True when this call claimed it (proceed), False when it was already
    claimed (duplicate), None when idempotency is disabled or Redis failed
    (fail-open: proceed, nothing to release)."""
    ttl = settings.agent_concierge_conversion_idempotency_ttl_seconds
    if ttl <= 0:
        return None
    try:
        from apps.api.services.redis_client import get_redis

        was_set = await get_redis().set(key, "1", nx=True, ex=ttl)
        return bool(was_set)
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_conversion_idempotency_check_failed", error=str(exc))
        return None


async def _release_idempotency_key(key: str) -> None:
    """Undo a claim when the lead write failed, so the caller's retry is not
    swallowed as a 'duplicate' of a lead that never existed."""
    try:
        from apps.api.services.redis_client import get_redis

        await get_redis().delete(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_conversion_idempotency_release_failed", error=str(exc))


def sanitize_qualification_params(params: dict | None) -> dict:
    """Sanitize the qualification params at the earliest point they enter the
    system (Must-Fix 2). Every string value passes through clean_text with its
    cap, so a sanitized value is what flows through the rest of the pipeline
    (needs_more_info echo, qualified-content lookup, lead-row write, email body).
    Non-string values are dropped, not reflected."""
    if not isinstance(params, dict):
        return {}
    cleaned: dict = {}
    for key, cap in _QUALIFICATION_CAPS.items():
        value = params.get(key)
        if isinstance(value, str):
            cleaned[key] = prompt_safety.clean_text(value, cap)
    return cleaned


async def handle_conversion_tool(
    db: "AsyncSession",
    site: Site,
    profile: AgentProfile,
    tool_name: str,
    params: dict | None,
    ip_address: str | None,
) -> tuple[dict, str | None]:
    """Zero-click conversion (request_quote / book_demo): ACCEPT-AND-RETURN.

    Returns ``(result, lead_id)``. ``lead_id`` is the id of a NEWLY written lead
    (None for needs_more_info or a collapsed duplicate); the caller schedules
    ``process_new_lead`` for it as a background task AFTER the response.

    The request path is DB-only and fast:
    1. Gate on the 3 qualification params (missing => needs_more_info RESULT).
    2. Sanitize params (defense-in-depth at the write boundary).
    3. Idempotency claim keyed on (site, tool, caller IP, params); released if
       the write fails so a retry is not swallowed.
    4. Write the AgentLead row with a TRUNCATED IP and no company yet.

    Company lookup and owner email happen off the request path
    (``process_new_lead``) — this unauthenticated call never does rDNS inline
    and never writes the cross-tenant company_graph.
    """
    from apps.api.models.agent_lead import AgentLead
    from apps.api.schemas.agent_gateway import AgentLeadOut

    missing = missing_qualification_params(params)
    if missing:
        from apps.api.schemas.agent_gateway import NeedsMoreInfoOut

        return NeedsMoreInfoOut(missing_params=missing).model_dump(), None

    clean = sanitize_qualification_params(params)
    ack = AgentLeadOut(tool_name=tool_name).model_dump()

    key = _conversion_idempotency_key(site.site_id, tool_name, clean, ip_address)
    claimed = await _claim_idempotency_key(key)
    if claimed is False:
        # Duplicate within the window: same ack, no second row, no second email.
        return ack, None

    lead = AgentLead(
        site_id=site.site_id,
        tool_name=tool_name,
        use_case=clean.get("use_case"),
        company_size=clean.get("company_size"),
        evaluating_against=clean.get("evaluating_against"),
        note=clean.get("note"),
        resolved_company_domain=None,
        ip_address=truncate_ip(ip_address),
        notified=False,
    )
    try:
        db.add(lead)
        await db.commit()
    except Exception:
        if claimed:
            await _release_idempotency_key(key)
        raise
    return ack, str(lead.id)


async def process_new_lead(lead_id: str, ip_address: str | None) -> None:
    """Background task (runs after the MCP response is sent).

    Opens its OWN session (the request session is closed by then), resolves the
    company via the Redis-cached free rDNS path WITHOUT a db (so nothing is
    written to the cross-tenant company_graph from an unauthenticated call),
    then notifies the owner. Fully fail-open: every failure is logged by key
    only and swallowed."""
    import uuid as _uuid

    from apps.api.models.agent_lead import AgentLead
    from apps.api.models.database import async_session
    from apps.api.services.agent_lead_notify import notify_owner_of_lead

    try:
        async with async_session() as db:
            lead = await db.get(AgentLead, _uuid.UUID(lead_id))
            if lead is None:
                return
            site = (
                await db.execute(select(Site).where(Site.site_id == lead.site_id))
            ).scalar_one_or_none()
            if site is None:
                return
            if ip_address:
                try:
                    from apps.api.services.company_resolver import (
                        resolve_company_cached,
                    )

                    domain = await resolve_company_cached(ip_address, db=None)
                except Exception:
                    domain = None
                # M2: rDNS PTR is attacker-influenceable — strict grammar or None.
                lead.resolved_company_domain = sanitize_resolved_domain(domain)
            sent = await notify_owner_of_lead(db, site, lead)
            lead.notified = bool(sent)
            await db.commit()
    except Exception:
        logger.warning("agent_lead_background_failed", lead_id=lead_id)
