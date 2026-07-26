"""Public agent-facing response shapes (agent-gateway Phase 2).

These are the ONLY shapes rendered on the unauthenticated surface. Every field
here is customer-authored content from ``AgentProfile`` (plus the site's own
public name/url/description). Deliberately absent, and never to be added:
``user_id``, internal UUID primary keys, row counts, visitor/identity data, or
any operational ``Site`` column (budgets, verification state, consent mode,
webhook secrets, watermarks).
"""

from pydantic import BaseModel

# Bumped when the manifest's own shape changes in a non-additive way. Agents
# read this to decide whether they understand the document.
MANIFEST_VERSION = "2026-07-26"

# Reverse-domain namespace for Beam-specific capability names, per the
# /.well-known/ucp convention this manifest is shaped to be compatible with.
CAPABILITY_NAMESPACE = "fyi.getbeam.agent"


class ManifestCapability(BaseModel):
    """One declared capability, reverse-domain namespaced."""

    name: str          # e.g. "fyi.getbeam.agent.request_demo"
    version: str
    # Phase 1+2 publish the DECLARATION only. The endpoint that honors it is
    # Phase 3; until then this is null and agents must not assume a callable URL.
    endpoint: str | None = None


class ManifestSeller(BaseModel):
    name: str
    url: str
    description: str | None = None
    tagline: str | None = None
    contact_email: str | None = None
    privacy_policy_url: str | None = None
    tos_url: str | None = None


class AgentManifest(BaseModel):
    manifest_version: str = MANIFEST_VERSION
    site_id: str
    seller: ManifestSeller
    capabilities: list[ManifestCapability] = []
    primary_cta: str | None = None
    endpoints: dict[str, str] = {}


class AgentOfferOut(BaseModel):
    """ACP-feed-shaped offer entry."""

    item_id: str
    title: str
    description: str | None = None
    url: str | None = None
    price: str | None = None
    currency: str | None = None
    billing_period: str | None = None
    availability: str | None = None
    seller_name: str
    seller_url: str


class AgentOffersFeed(BaseModel):
    site_id: str
    seller_name: str
    seller_url: str
    offers: list[AgentOfferOut] = []
