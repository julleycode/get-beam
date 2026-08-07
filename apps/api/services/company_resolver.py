"""IP-to-Company resolution via reverse DNS lookup.

Strategy (same as Clay's approach but using free rDNS):
1. Reverse DNS lookup on the visitor's IP
2. Filter out ISP/residential hostnames (comcast, verizon, att, etc.)
3. Filter out VPN providers (nordvpn, expressvpn, etc.)
4. Filter out cloud/datacenter ranges (amazonaws, googlecloud, azure)
5. Extract root domain from rDNS hostname -> company domain

Accuracy: ~30-50% for corporate IPs (honest estimate).
Residential IPs are correctly filtered out as "unknown".

Results are cached in Redis with 30-day TTL to avoid repeated lookups.
"""

import asyncio
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.company_graph import CompanyGraphNode

logger = structlog.get_logger()

# Cache TTL: 30 days in seconds
CACHE_TTL = 30 * 24 * 3600
CACHE_PREFIX = "company_ip:"

# Private/reserved IP ranges — skip lookup entirely
_PRIVATE_RE = re.compile(
    r"^(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|127\.|0\.|169\.254\.|::1|fe80:)"
)

# Domain-level patterns — match against the extracted domain (e.g. "comcast.net")
# These are ISPs, VPNs, and cloud providers whose domain IS the pattern.
_DOMAIN_PATTERNS: set[str] = {
    # ISPs
    "comcast", "xfinity", "verizon", "fios", "att.net", "sbcglobal",
    "charter", "spectrum", "cox", "centurylink", "lumen", "frontier",
    "windstream", "mediacom", "suddenlink", "optimum", "cablevision",
    "earthlink", "bellsouth", "rr.com", "roadrunner", "twc",
    "t-mobile", "tmobile", "sprint", "boost", "metro-pcs",
    "vodafone", "bt.com", "sky.com", "talktalk", "virgin",
    "telstra", "optus", "tpg", "bigpond",
    "fpt.vn", "vnpt", "viettel", "mobifone", "vinaphone",
    # VPNs
    "nordvpn", "expressvpn", "surfshark", "cyberghost",
    "privateinternetaccess", "mullvad", "protonvpn", "ipvanish",
    "tunnelbear", "hotspotshield", "windscribe", "torproject",
    # Cloud / datacenter
    "amazonaws", "googlecloud", "digitalocean", "linode", "akamai",
    "vultr", "hetzner", "ovh", "scaleway", "contabo",
    "cloudflare", "fastly", "vercel", "netlify", "railway",
    "heroku", "render",
}

# Hostname-level patterns — match against the FULL hostname to catch residential indicators
_HOSTNAME_PATTERNS: set[str] = {
    "dsl", "dial", "cable", "broadband", "dynamic", "dhcp",
    "pool", "residential", "consumer", "hsd1", "myvzw", "mycingular",
    "datacenter", "hosting", "dedicated", "colo",
    "tor-exit", "tor-relay",
}


@lru_cache(maxsize=1)
def _build_domain_filter_regex() -> re.Pattern[str]:
    """Build regex for domain-level filtering (checked against extracted domain)."""
    pattern = "|".join(re.escape(p) for p in sorted(_DOMAIN_PATTERNS, key=len, reverse=True))
    return re.compile(pattern, re.IGNORECASE)


@lru_cache(maxsize=1)
def _build_hostname_filter_regex() -> re.Pattern[str]:
    """Build regex for hostname-level filtering (checked against full rDNS hostname)."""
    pattern = "|".join(re.escape(p) for p in sorted(_HOSTNAME_PATTERNS, key=len, reverse=True))
    return re.compile(pattern, re.IGNORECASE)


def _extract_domain(hostname: str) -> str | None:
    """Extract the registrable domain from a reverse DNS hostname.

    Examples:
        'mail.google.com' -> 'google.com'
        'vpn-us.apple.com' -> 'apple.com'
        '12-34-56-78.res.spectrum.net' -> None (filtered as ISP)
    """
    if not hostname or hostname.replace(".", "").isdigit():
        return None  # IP address, not a hostname

    # Extract last 2 parts (or 3 for country-code TLDs like .co.uk, .com.au)
    parts = hostname.rstrip(".").split(".")
    if len(parts) < 2:
        return None

    # Handle two-part TLDs: .co.uk, .com.au, .co.jp, .com.br, etc.
    two_part_tlds = {"co.uk", "com.au", "co.jp", "com.br", "co.in", "com.sg", "co.kr", "com.vn"}
    if len(parts) >= 3:
        tld_candidate = f"{parts[-2]}.{parts[-1]}"
        if tld_candidate in two_part_tlds:
            if len(parts) >= 4:
                return f"{parts[-3]}.{parts[-2]}.{parts[-1]}"
            return None

    domain = f"{parts[-2]}.{parts[-1]}"

    # Check domain against ISP/VPN/cloud patterns
    if _build_domain_filter_regex().search(domain):
        return None

    # Check full hostname for residential/dynamic indicators
    if _build_hostname_filter_regex().search(hostname):
        return None

    return domain


async def resolve_company_from_ip(ip: str) -> str | None:
    """Resolve an IP address to a company domain via reverse DNS.

    Returns the company domain (e.g. 'apple.com') or None if:
    - IP is private/reserved
    - rDNS lookup fails
    - Hostname matches ISP/VPN/cloud patterns
    - Could not extract a meaningful domain

    This function does NOT raise exceptions — returns None on any failure.
    """
    if not ip or _PRIVATE_RE.match(ip):
        return None

    try:
        # Run blocking DNS lookup in a thread pool
        loop = asyncio.get_event_loop()
        hostname = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: socket.getfqdn(ip)),
            timeout=5.0,
        )

        # getfqdn returns the IP itself if no rDNS record exists
        if hostname == ip or not hostname:
            return None

        domain = _extract_domain(hostname)
        if domain:
            logger.debug("company_resolved", ip=ip[:8] + "...", hostname=hostname, domain=domain)
        return domain

    except (asyncio.TimeoutError, socket.herror, socket.gaierror, OSError) as e:
        logger.debug("rdns_lookup_failed", ip=ip[:8] + "...", error=str(e))
        return None
    except Exception as e:
        logger.debug("company_resolve_error", ip=ip[:8] + "...", error=str(e))
        return None


_PRIVACY_CACHE_PREFIX = "ip_privacy:"
_PRIVACY_CACHE_TTL = 7 * 24 * 3600


async def check_ip_privacy(ip: str) -> dict | None:
    """Check if IP is VPN/proxy/tor/hosting via IPinfo Privacy Detection API.

    Returns {"vpn": bool, "proxy": bool, "tor": bool, "relay": bool, "hosting": bool}
    or None if check fails/disabled. Cached in Redis with 7-day TTL.
    """
    from apps.api.config import settings

    if not settings.ipinfo_token:
        return None
    if not ip or _PRIVATE_RE.match(ip):
        return None

    cache_key = f"{_PRIVACY_CACHE_PREFIX}{ip}"
    try:
        from apps.api.services.redis_client import get_redis
        import json
        redis = get_redis()
        cached = await redis.get(cache_key)
        if cached is not None:
            return json.loads(cached)
    except Exception:
        pass

    try:
        import httpx
        import json
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"https://ipinfo.io/{ip}/privacy",
                params={"token": settings.ipinfo_token},
            )
            if resp.status_code == 200:
                data = resp.json()
                result = {
                    "vpn": data.get("vpn", False),
                    "proxy": data.get("proxy", False),
                    "tor": data.get("tor", False),
                    "relay": data.get("relay", False),
                    "hosting": data.get("hosting", False),
                }
                try:
                    redis = get_redis()
                    await redis.setex(cache_key, _PRIVACY_CACHE_TTL, json.dumps(result))
                except Exception:
                    pass
                return result
    except Exception as e:
        logger.debug("ip_privacy_check_failed", ip=ip[:10], error=str(e))

    return None


def is_ip_suspicious(privacy: dict | None) -> bool:
    """Return True if any privacy flag is set (VPN/proxy/tor/relay/hosting)."""
    if not privacy:
        return False
    return any(privacy.get(k, False) for k in ("vpn", "proxy", "tor", "relay", "hosting"))


# iCloud Private Relay egress via Cloudflare. Client IPs in this prefix are shared
# relays — useless (and dangerous) for person-level IP→identity. Checked locally so
# resolution still refuses them when IPinfo is unavailable (fail-closed for this
# known range). Ingest MUST keep these events (real humans); only paid person-ID
# resolution is blocked.
_ICLOUD_PRIVATE_RELAY_V6_PREFIXES = ("2a09:bac3:",)


def is_privacy_relay_ip(ip: str | None) -> bool:
    """True for known privacy-relay *client* IPs (local, no network call).

    Does not drop ingest traffic — only signals that person-level resolution from
    IP must not run.
    """
    if not ip:
        return False
    low = ip.strip().lower()
    return any(low.startswith(prefix) for prefix in _ICLOUD_PRIVATE_RELAY_V6_PREFIXES)


# Ingest DROP signal: proxy / VPN / Tor / hosting — but NOT `relay`. Apple Private
# Relay and Cloudflare WARP set relay=True yet front REAL humans, so relay alone
# must never drop an event (mirrors the CDN/relay carve-out in classify_org_kind).
# This is the narrower cousin of is_ip_suspicious, which DOES count relay and is
# used only to *skip paid identity resolution*, never to discard traffic.
_INGEST_DROP_PRIVACY_FLAGS = ("vpn", "proxy", "tor", "hosting")


def is_proxy_or_vpn(privacy: dict | None) -> bool:
    """True if IPinfo flags the IP as proxy / VPN / Tor / hosting (relay excluded).

    Drives the ingest proxy drop: catches no-PTR commercial proxies (Sprious-style
    scrapers) and VPN egress that hide behind a real-looking UA and an ASN the
    org-token net misses — without dropping mobile CGNAT humans (never flagged
    proxy) or Private Relay users (relay, deliberately not counted here)."""
    if not privacy:
        return False
    return any(privacy.get(k, False) for k in _INGEST_DROP_PRIVACY_FLAGS)


# Cloud COMPUTE providers — these host servers, not consumer eyeballs. CDN/relay
# orgs (Cloudflare, Fastly, Akamai, Gcore) are deliberately EXCLUDED because they
# front real human traffic via Apple Private Relay / Cloudflare WARP.
#
# Two match styles (substring against ipinfo's `org`, e.g. "AS3356 Level 3 Parent, LLC"):
#  - bare org-name tokens for pure-hosting providers whose NAME never fronts eyeballs
#  - "asNNNN " ASN-prefix tokens (note trailing space) for transit/infra ASNs where the
#    company NAME is ambiguous with a residential brand. Matching the ASN with a trailing
#    space pins it to exactly that AS (so "as3356 " ≠ "as33560 ...") and avoids dropping
#    real residential customers of the same parent company.
# Deliberately NOT blocked: residential ISPs that also run datacenters (e.g. Windstream
# AS7029, Comcast, Cox) — name/ASN there carries real home visitors. Fail-open ethos.
_DATACENTER_ORG_TOKENS = (
    "microsoft", "azure", "google", "amazon", "aws", "digitalocean", "ovh",
    "hetzner", "vultr", "choopa", "linode", "alibaba", "tencent", "oracle",
    "scaleway", "leaseweb", "datacamp", "m247", "contabo", "upcloud",
    "ibm", "rackspace", "softlayer", "hostinger", "godaddy", "ionos",
    "constant company", "quadranet", "psychz", "limestone", "cogent",
    "hosting", "datacenter", "data center", "colocation",
    # 2026-06-30: confirmed bot/proxy sources missed by the list above.
    "hostroyale", "as207990 ",        # HostRoyale — bulletproof/cheap hosting
    "as3356 ",                          # Level 3 / Lumen transit core — proxy/SWG/scanner egress
    "facebook", "as32934 ",            # Facebook AS — link-preview crawler, never an eyeball
    # 2026-07-21: commercial proxy / scraper networks seen hitting getbeam.fyi as
    # fake "US visitors". Never a real eyeball. Name-token fallback to the ASN set
    # above (org strings drift; ASN is primary). Sprious PTR = static.sprious.com.
    "sprious", "rayobyte", "blazing seo", "oxylabs", "logicweb", "oculus networks",
)

# ── ASN-based classification (primary signal; the org-name tokens above are fallback) ──
# Matched on the ASN NUMBER parsed from ipinfo's `org` ("AS20473 The Constant Company,
# LLC" → 20473). ASN numbers are stable identifiers; company NAMES drift and collide with
# residential brands, so the number is the robust primary signal.
#
# This block set was compiled + ADVERSARIALLY VETTED (2026-06-30): a reviewer removed
# ASNs that also carry real human eyeballs — Microsoft corp AS8075/8069/8070/8071 (office
# NAT egress), OVH AS16276 / Hetzner AS24940 (also sell consumer DSL), and Cogent AS174
# (Tier-1 transit). Those host NAMES are still caught by the name-token net above (proven
# status quo for this product), but are kept OUT of the ASN set so the precise ASN layer
# never over-blocks a real corporate/residential visitor.
_DATACENTER_ASNS: frozenset[int] = frozenset({
    14618, 396982, 31898, 45102, 37963, 45090, 132203,    # AWS-AES, GCP, Oracle OCI, Alibaba x2, Tencent
    36351, 14061, 63949, 20473, 12876, 202053, 51167,     # IBM/SoftLayer, DigitalOcean, Linode, Vultr, Scaleway, UpCloud, Contabo
    16265, 30633, 9009, 60068, 212238,                    # Leaseweb x2, M247, Datacamp/CDN77 x2
    207990, 8100, 40676, 46475, 53667, 36352, 63023, 54825,  # HostRoyale, QuadraNet, Psychz, Limestone, BuyVM, ColoCrossing, GTHost, Equinix Metal
    136787,  # PacketHub S.A. — VPN/proxy egress (NordVPN family); caught leaking as "eyeball" 2026-06-30
    # 2026-07-21: commercial proxy / scraper / cheap-hosting ASNs caught hitting
    # getbeam.fyi as fake "US visitors" (pv=1, intent~9-10). IPinfo's privacy
    # detection returns NOTHING for these, so the ASN is the only robust signal.
    64267, 396319, 64286, 398781,  # Sprious LLC, Oxylabs, LogicWeb, Oculus Networks
})

# CDN / edge / privacy-relay ASNs. NOT dropped at ingest — they front REAL humans via
# Apple Private Relay / Cloudflare WARP — but the resolver must NEVER turn them into a
# company domain (that path fabricated "cdurham@fastly.com" from a Fastly edge IP).
_CDN_RELAY_ASNS: frozenset[int] = frozenset({
    714,                          # Apple (Private Relay ingress)
    13335,                        # Cloudflare
    54113,                        # Fastly
    16625, 20940, 36183, 12222,   # Akamai
    199524, 202422,               # Gcore
})
_CDN_RELAY_ORG_TOKENS = ("cloudflare", "fastly", "akamai", "gcore", "g-core")

_ASN_RE = re.compile(r"\bAS(\d+)\b", re.IGNORECASE)


def _parse_asn(org: str | None) -> int | None:
    """Extract the ASN integer from an ipinfo `org` string ("AS3356 Level 3…" → 3356)."""
    if not org:
        return None
    m = _ASN_RE.search(org)
    return int(m.group(1)) if m else None


def classify_org_kind(org: str | None) -> str:
    """Classify an ipinfo `org` string → 'datacenter' | 'cdn' | 'eyeball'.

    ASN number first (stable), then org-name token fallback. 'cdn' is a separate bucket
    from 'datacenter' because CDN/relay nets carry real humans (Apple Private Relay) and
    must be KEPT at ingest, yet must never be resolved to a fabricated company employee.
    """
    asn = _parse_asn(org)
    low = (org or "").lower()
    if asn in _CDN_RELAY_ASNS or any(t in low for t in _CDN_RELAY_ORG_TOKENS):
        return "cdn"
    if asn in _DATACENTER_ASNS or (low and any(t in low for t in _DATACENTER_ORG_TOKENS)):
        return "datacenter"
    return "eyeball"


_DATACENTER_CACHE_PREFIX = "ip_datacenter:"
_DATACENTER_CACHE_TTL = 30 * 24 * 3600  # 30 days


async def is_datacenter_ip(ip: str) -> bool:
    """True if `ip` belongs to a cloud-compute / hosting provider (server/bot traffic).

    Resolves the IP's ASN + org, then classifies via `classify_org_kind` (ASN-number
    match first, org-name token fallback). CDN/relay orgs (Cloudflare/Fastly/Akamai)
    classify as 'cdn', NOT 'datacenter', so they are NEVER dropped here — they front
    real humans behind Apple Private Relay / Cloudflare WARP.

    ASN source, in order: (1) a local MaxMind GeoLite2-ASN DB when configured —
    free, unlimited, sub-ms, no network; (2) the IPinfo API otherwise. Cached in
    Redis 30 days. Fail-open: returns False on a private IP, no ASN source, or any
    error, so a real visitor's events are never dropped because of a lookup hiccup.
    """
    from apps.api.config import settings

    if not ip or _PRIVATE_RE.match(ip):
        return False

    cache_key = f"{_DATACENTER_CACHE_PREFIX}{ip}"
    try:
        from apps.api.services.redis_client import get_redis
        redis = get_redis()
        cached = await redis.get(cache_key)
        if cached is not None:
            return cached == "1"
    except Exception:
        redis = None

    org: str | None = None

    # (1) Local MaxMind GeoLite2-ASN — preferred: free, unlimited, no network.
    from apps.api.services.asn_lookup import lookup_asn
    asn, asn_org = lookup_asn(ip)
    if asn is not None:
        # Rebuild the "AS<num> <Org>" shape classify_org_kind parses, so the same
        # ASN set + org tokens drive both the MaxMind and IPinfo paths.
        org = f"AS{asn} {asn_org or ''}".strip()

    # (2) Fallback: IPinfo API (needs a token). Skipped entirely when MaxMind answered.
    if org is None:
        if not settings.ipinfo_token:
            return False  # no local DB and no token → fail-open
        try:
            import httpx
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(
                    f"https://ipinfo.io/{ip}", params={"token": settings.ipinfo_token}
                )
                if resp.status_code == 200:
                    org = resp.json().get("org")
        except Exception as exc:
            logger.debug("datacenter_check_failed", ip=ip[:8] + "...", error=str(exc))
            return False  # fail-open

    is_dc = classify_org_kind(org) == "datacenter"
    try:
        if redis is not None:
            await redis.setex(cache_key, _DATACENTER_CACHE_TTL, "1" if is_dc else "0")
    except Exception:
        pass
    if is_dc:
        logger.info("datacenter_ip_blocked", ip=ip[:8] + "...", org=org)
    return is_dc


# ─── Durable cross-tenant company graph (owned-data-layer, flag-gated) ───


@dataclass
class CompanyGraphReadResult:
    """A company_graph read hit plus whether the row is past its staleness
    window (lazy read-time re-validation signal — no cron)."""

    node: CompanyGraphNode
    needs_revalidation: bool


def _company_graph_is_stale(
    last_verified: datetime | None,
    staleness_days: int,
    now: datetime | None = None,
) -> bool:
    """Pure staleness check: True when last_verified is older than the window
    (or missing). Timezone-tolerant so naive server_default timestamps compare
    correctly."""
    if last_verified is None:
        return True
    now = now or datetime.now(timezone.utc)
    if last_verified.tzinfo is None:
        last_verified = last_verified.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - last_verified) > timedelta(days=staleness_days)


async def _read_company_graph(
    db: AsyncSession, ip: str
) -> CompanyGraphReadResult | None:
    """Read the highest-confidence company_graph row for an IP, tagged with a
    staleness flag. Returns None on no row or any error (fail-open)."""
    if not ip:
        return None
    try:
        row = (
            await db.execute(
                select(CompanyGraphNode)
                .where(CompanyGraphNode.ip == ip)
                .order_by(CompanyGraphNode.confidence.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    except Exception as exc:
        logger.debug("company_graph_read_failed", error=str(exc))
        return None
    if row is None:
        return None
    stale = _company_graph_is_stale(row.last_verified, settings.company_graph_staleness_days)
    return CompanyGraphReadResult(node=row, needs_revalidation=stale)


async def _write_through_company_graph(
    db: AsyncSession,
    ip: str,
    domain: str | None,
    company_name: str | None,
    source: str,
    confidence: float,
) -> None:
    """Upsert a resolved (ip, source) into the durable company_graph. Best-effort:
    a write failure never breaks the caller's resolution. Logs keys only."""
    if not ip:
        return
    try:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(CompanyGraphNode).values(
            ip=ip,
            domain=domain,
            company_name=company_name,
            source=source,
            confidence=confidence,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["ip", "source"],
            set_={
                "domain": stmt.excluded.domain,
                "company_name": stmt.excluded.company_name,
                "confidence": stmt.excluded.confidence,
                "last_verified": func.now(),
                "updated_at": func.now(),
            },
        )
        await db.execute(stmt)
        await db.commit()
        logger.info("company_graph_upserted", source=source)
    except Exception as exc:
        try:
            await db.rollback()
        except Exception:
            pass
        logger.debug("company_graph_write_failed", error=str(exc))


async def resolve_company_cached(
    ip: str, db: AsyncSession | None = None
) -> str | None:
    """Resolve IP to company domain with Redis caching (30-day TTL).

    Returns cached result if available, otherwise resolves and caches.
    Falls back to uncached resolution if Redis is unavailable.

    ``db`` (owned-data-layer): when provided AND ``company_graph_enabled`` is
    True, a fresh (non-stale) company_graph row is read first (skipping rDNS),
    and every successful rDNS resolution is persisted write-through to the
    durable cross-tenant company_graph. When ``db is None`` OR the flag is off,
    behavior is byte-identical to the Redis-only path (existing callers pass no
    db → unchanged).
    """
    graph_on = db is not None and settings.company_graph_enabled

    # ── Graph read-first (flag-gated): a fresh row short-circuits rDNS ──
    if graph_on:
        read = await _read_company_graph(db, ip)
        if read is not None and not read.needs_revalidation:
            return read.node.domain

    cache_key = f"{CACHE_PREFIX}{ip}"

    try:
        from apps.api.services.redis_client import get_redis
        redis = get_redis()

        # Check cache first
        cached = await redis.get(cache_key)
        if cached is not None:
            return cached if cached != "__none__" else None

        # Resolve
        domain = await resolve_company_from_ip(ip)

        # Cache result (store "__none__" for negative results to avoid re-lookups)
        await redis.setex(cache_key, CACHE_TTL, domain or "__none__")

        # Write-through to the durable graph on a successful free rDNS hit.
        if graph_on and domain:
            await _write_through_company_graph(db, ip, domain, None, "rdns", 0.5)

        if domain is None:
            return await _resolve_via_local_ip_org(db, ip)
        return domain

    except Exception:
        # Redis unavailable — resolve without caching
        domain = await resolve_company_from_ip(ip)
        if graph_on and domain:
            await _write_through_company_graph(db, ip, domain, None, "rdns", 0.5)
        if domain is None:
            return await _resolve_via_local_ip_org(db, ip)
        return domain


async def _resolve_via_local_ip_org(
    db: AsyncSession | None, ip: str
) -> str | None:
    """Last free rung of the ladder: the self-hosted ip_org_prefixes table.

    Runs only AFTER rDNS has missed. rDNS deliberately stays first because a
    resolving PTR is the more specific signal — it yields an actual domain,
    whereas a prefix match yields an organization NAME and (until Phase 3) no
    domain at all.

    On a hit the result is persisted to company_graph as ``source="rir_asn"``
    with ``confidence=0.45`` — below rDNS (0.5) and the paid path (0.7), because
    a whole-prefix attribution is coarser than either. The graph read orders by
    ``confidence.desc()``, so a later rDNS or paid resolution naturally shadows
    this row rather than being blocked by it. This is also the first source ever
    to populate ``company_graph.company_name``: the column has existed unwritten
    since the table was created, and an org name with no domain is exactly what
    it is for.

    Returns the row's domain, which today is ``None`` — the VALUE of the hit is
    the persisted company_name, and the caller's contract (a domain or None) is
    unchanged. Fail-open: any error yields None.
    """
    if db is None or not settings.ip_org_lookup_enabled:
        return None
    from apps.api.services.ip_org_lookup import lookup_ip_org

    match = await lookup_ip_org(db, ip)
    if match is None:
        return None
    if settings.company_graph_enabled:
        await _write_through_company_graph(
            db, ip, match["domain"], match["org_name"], "rir_asn", 0.45
        )
    return match["domain"]
