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


def tool_get_offers(site: Site, profile: AgentProfile) -> dict:
    return build_offers(site, profile).model_dump()


def tool_get_pricing(site: Site, profile: AgentProfile) -> dict:
    """Price-only projection of the offers feed."""
    return {
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


def tool_check_availability(site: Site, profile: AgentProfile) -> dict:
    """Availability-only projection of the offers feed."""
    return {
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


# Strict method allow-list for the JSON-RPC dispatcher. Anything not a key here
# gets -32601 Method not found. Phase 3 adds the action tools; do not widen this
# in Phase 1+2.
MCP_TOOLS = {
    "get_offers": tool_get_offers,
    "get_pricing": tool_get_pricing,
    "check_availability": tool_check_availability,
}
