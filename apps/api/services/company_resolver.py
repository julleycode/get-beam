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
from functools import lru_cache

import structlog

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


# Cloud COMPUTE providers — these host servers, not consumer eyeballs. CDN/relay
# orgs (Cloudflare, Fastly, Akamai, Gcore) are deliberately EXCLUDED because they
# front real human traffic via Apple Private Relay / Cloudflare WARP.
_DATACENTER_ORG_TOKENS = (
    "microsoft", "azure", "google", "amazon", "aws", "digitalocean", "ovh",
    "hetzner", "vultr", "choopa", "linode", "alibaba", "tencent", "oracle",
    "scaleway", "leaseweb", "datacamp", "m247", "contabo", "upcloud",
    "ibm", "rackspace", "softlayer", "hostinger", "godaddy", "ionos",
    "constant company", "quadranet", "psychz", "limestone", "cogent",
    "hosting", "datacenter", "data center", "colocation",
)
_DATACENTER_CACHE_PREFIX = "ip_datacenter:"
_DATACENTER_CACHE_TTL = 30 * 24 * 3600  # 30 days


async def is_datacenter_ip(ip: str) -> bool:
    """True if `ip` belongs to a cloud-compute provider (server/bot traffic).

    Uses IPinfo's standard endpoint `org` (ASN) field — available on the free
    token (unlike the paid /privacy module). Cached in Redis 30 days. Fail-open:
    returns False on private IP, missing token, or any error, so a real visitor's
    events are NEVER dropped because of a lookup hiccup.
    """
    from apps.api.config import settings

    if not ip or _PRIVATE_RE.match(ip):
        return False
    if not settings.ipinfo_token:
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

    is_dc = bool(org) and any(tok in org.lower() for tok in _DATACENTER_ORG_TOKENS)
    try:
        if redis is not None:
            await redis.setex(cache_key, _DATACENTER_CACHE_TTL, "1" if is_dc else "0")
    except Exception:
        pass
    if is_dc:
        logger.info("datacenter_ip_blocked", ip=ip[:8] + "...", org=org)
    return is_dc


async def resolve_company_cached(ip: str) -> str | None:
    """Resolve IP to company domain with Redis caching (30-day TTL).

    Returns cached result if available, otherwise resolves and caches.
    Falls back to uncached resolution if Redis is unavailable.
    """
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

        return domain

    except Exception:
        # Redis unavailable — resolve without caching
        return await resolve_company_from_ip(ip)
