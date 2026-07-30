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
"""

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.agent_profile import AgentProfile
from apps.api.models.site import Site
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
) -> dict:
    """Zero-click conversion (request_quote / book_demo): ACCEPT-AND-RETURN.

    Contract (AC-WS3-2 / Must-Fix 1/2/3):
    1. Gate on the 3 qualification params (a quote/demo without context is not a
       useful lead) — missing => needs_more_info RESULT.
    2. Sanitize params (defense-in-depth: already sanitized at the dispatcher,
       re-sanitized here at the write boundary).
    3. FREE-ONLY company lookup (Must-Fix 3): rDNS + cached company_graph via
       company_resolver's free path — ZERO paid-provider call, never the
       synchronous identity-resolution waterfall. Null when no free hit.
    4. Write the AgentLead row synchronously (fast, DB-only), then fire the
       owner-notification email FAIL-OPEN (never blocks/500s the response).
    """
    from apps.api.models.agent_lead import AgentLead
    from apps.api.services.company_resolver import resolve_company_cached

    missing = missing_qualification_params(params)
    if missing:
        from apps.api.schemas.agent_gateway import NeedsMoreInfoOut

        return NeedsMoreInfoOut(missing_params=missing).model_dump()

    clean = sanitize_qualification_params(params)

    # Must-Fix 3: FREE-ONLY resolution. resolve_company_cached(ip, db) reads the
    # cached company_graph then falls back to free rDNS — it NEVER calls
    # IdentityResolver.resolve() / the paid provider waterfall. Fail-open.
    resolved_domain: str | None = None
    if ip_address:
        try:
            resolved_domain = await resolve_company_cached(ip_address, db=db)
        except Exception:
            resolved_domain = None

    lead = AgentLead(
        site_id=site.site_id,
        tool_name=tool_name,
        use_case=clean.get("use_case"),
        company_size=clean.get("company_size"),
        evaluating_against=clean.get("evaluating_against"),
        note=clean.get("note"),
        resolved_company_domain=resolved_domain,
        ip_address=ip_address,
        notified=False,
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    # Capture the id as a plain string NOW: a later rollback in the fail-open
    # path expires ORM attributes, and re-reading lead.id would trigger a lazy
    # refresh (async IO) from a sync logging call → MissingGreenlet.
    lead_id_str = str(lead.id)
    site_id_str = site.site_id  # captured before any rollback expires ORM attrs

    # Fire-and-forget-shaped but awaited: fail-open so email trouble never
    # touches the already-committed lead or the response.
    from apps.api.services.agent_lead_notify import notify_owner_of_lead

    try:
        await notify_owner_of_lead(db, site, lead)
        lead.notified = True
        await db.commit()
    except Exception:
        # Fail-open: the lead is already committed. Deliberately NO db.rollback()
        # here — the notify path only issued read-only SELECTs (no write to undo),
        # and a rollback would expire every ORM object still shared with the
        # caller (site/profile), breaking their attribute access downstream. Any
        # genuinely aborted transaction is re-established by the next commit.
        logger.warning(
            "agent_lead_notify_failed", site_id=site_id_str, lead_id=lead_id_str
        )

    from apps.api.schemas.agent_gateway import AgentLeadOut

    return AgentLeadOut(tool_name=tool_name).model_dump()
