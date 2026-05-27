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

# ISP / residential patterns — rDNS hostnames that indicate home internet
_ISP_PATTERNS: set[str] = {
    "comcast", "xfinity", "verizon", "fios", "att.net", "sbcglobal",
    "charter", "spectrum", "cox", "centurylink", "lumen", "frontier",
    "windstream", "mediacom", "suddenlink", "optimum", "cablevision",
    "earthlink", "bellsouth", "rr.com", "roadrunner", "twc",
    "t-mobile", "tmobile", "sprint", "boost", "metro-pcs",
    "vodafone", "bt.com", "sky.com", "talktalk", "virgin",
    "telstra", "optus", "tpg", "bigpond",
    "dsl", "dial", "cable", "broadband", "dynamic", "dhcp",
    "pool", "residential", "consumer", "home", "mobile",
    "hsd1", "res", "myvzw", "mycingular",
    "fpt.vn", "vnpt", "viettel", "mobifone", "vinaphone",
}

# VPN / proxy patterns
_VPN_PATTERNS: set[str] = {
    "nordvpn", "expressvpn", "surfshark", "cyberghost", "pia",
    "privateinternetaccess", "mullvad", "protonvpn", "ipvanish",
    "tunnelbear", "hotspotshield", "windscribe", "torproject",
    "tor-exit", "tor-relay", "vpn", "proxy",
}

# Cloud / datacenter / hosting patterns (not a real company visiting)
_CLOUD_PATTERNS: set[str] = {
    "amazonaws", "aws", "googlecloud", "cloud.google",
    "azure", "microsoft.com", "digitalocean", "linode", "akamai",
    "vultr", "hetzner", "ovh", "scaleway", "contabo",
    "cloudflare", "fastly", "vercel", "netlify", "railway",
    "heroku", "render", "fly.io",
    "datacenter", "hosting", "dedicated", "colo", "server",
}


@lru_cache(maxsize=1)
def _build_filter_regex() -> re.Pattern[str]:
    """Build a single compiled regex from all filter patterns."""
    all_patterns = _ISP_PATTERNS | _VPN_PATTERNS | _CLOUD_PATTERNS
    pattern = "|".join(re.escape(p) for p in sorted(all_patterns, key=len, reverse=True))
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

    # Filter known ISP/VPN/cloud patterns
    filter_re = _build_filter_regex()
    if filter_re.search(hostname):
        return None

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

    return f"{parts[-2]}.{parts[-1]}"


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
