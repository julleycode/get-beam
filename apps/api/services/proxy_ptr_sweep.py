"""Offline reverse-DNS sweep for proxy traffic the ingest ASN filter can't catch.

Some commercial proxies announce their pool from a RESIDENTIAL parent ASN — e.g.
Sprious rents IPs that IPinfo attributes to "AS20001 Charter Communications", so
`is_datacenter_ip` (ASN/org based) classifies them as a real eyeball and keeps
them. The ONLY signal that unmasks these is the reverse-DNS hostname
(`host-….static.sprious.com`). We deliberately keep rDNS OFF the hot ingest path
(a blocking lookup per real visitor is too costly), so this offline sweep does it
in bulk instead.

Trigger-agnostic core (memory: job-architecture-preferences), mirroring
`retention.py`: a Postgres advisory lock keeps it single-flight across replicas,
`dry_run` reports without mutating, and it returns a status dict. Run it on
demand via `scripts/sweep_proxy_ptr.py` or wire it to the daily scheduler.

For every matched IP the sweep ALSO seeds the shared `ip_datacenter:<ip>` Redis
key that `is_datacenter_ip` reads first — so the next event from a known proxy IP
is dropped at ingest for free (no rDNS, no ASN call) for the cache's 30-day TTL.
"""

import asyncio

import dns.exception
import dns.resolver
import dns.reversename
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.database import async_session
from apps.api.services.company_resolver import (
    _DATACENTER_CACHE_PREFIX,
    _DATACENTER_CACHE_TTL,
    _PRIVATE_RE,
)

logger = structlog.get_logger()

# Registrable domains of commercial proxy / scraper vendors. A reverse-DNS
# hostname ending in one of these is proxy egress regardless of the announcing
# ASN — the residential-ASN case the ingest datacenter filter structurally
# misses. Matched on a DOT-anchored suffix so "sprious.com" hits
# "host-1.static.sprious.com" but never "notsprious.com".
_PROXY_PTR_SUFFIXES: frozenset[str] = frozenset({
    "sprious.com",          # Sprious LLC (a.k.a. Rayobyte / Blazing SEO)
    "rayobyte.com",
    "blazingseollc.com",
    "oxylabs.io",           # Oxylabs proxy pool
    "smartproxy.com",
    "iproyal.com",
    "packetstream.io",
    "luminati.io",          # Bright Data (legacy PTR)
    "brightdata.com",
})

# Advisory-lock key keeping the sweep single-flight across replicas.
_SWEEP_LOCK_KEY = "beam_proxy_ptr_sweep"

# Bounds concurrent DNS lookups.
_DNS_CONCURRENCY = 16
_DNS_TIMEOUT = 5.0
_DNS_RETRIES = 3          # total PTR attempts before giving up on an IP
_DNS_RETRY_BACKOFF = 0.5  # seconds between attempts

# Query PUBLIC recursive resolvers directly rather than the OS stub. The system
# stub (macOS mDNSResponder especially) throttles bulk reverse lookups and starts
# returning timeouts, which silently drops real proxy hits from the sweep. Going
# straight to public resolvers is deterministic across dev/CI/prod and handles the
# volume. Rebuilt lazily so a fork/event-loop swap never shares a stale socket.
_PUBLIC_NAMESERVERS = ["8.8.8.8", "1.1.1.1", "9.9.9.9"]
_resolver: dns.resolver.Resolver | None = None


def _get_resolver() -> dns.resolver.Resolver:
    global _resolver
    if _resolver is None:
        r = dns.resolver.Resolver(configure=False)
        r.nameservers = _PUBLIC_NAMESERVERS
        r.timeout = _DNS_TIMEOUT
        r.lifetime = _DNS_TIMEOUT
        _resolver = r
    return _resolver


class _TransientDNSError(Exception):
    """A retryable DNS failure (timeout / no reachable nameserver)."""


def _hostname_is_proxy(hostname: str | None) -> bool:
    """True if `hostname` ends in a known proxy vendor domain (dot-anchored)."""
    if not hostname:
        return False
    h = hostname.rstrip(".").lower()
    return any(h == s or h.endswith("." + s) for s in _PROXY_PTR_SUFFIXES)


def _ptr_and_confirm_sync(ip: str) -> str | None:
    """Blocking PTR lookup + forward-confirm for `ip` via public resolvers.

    Reverse DNS alone is attacker-controllable (anyone can point a PTR at
    `x.sprious.com`), and this sweep DELETES rows — so a proxy PTR is only trusted
    once the hostname forward-resolves back to the same IP (the check Google
    publishes for verifying Googlebot). Returns the hostname on a confirmed proxy,
    None on an authoritative negative (no PTR / not a proxy / forward mismatch),
    and raises _TransientDNSError on a retryable timeout."""
    resolver = _get_resolver()
    rev = dns.reversename.from_address(ip)
    try:
        ptr_answers = resolver.resolve(rev, "PTR")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return None  # authoritative: no PTR record
    except (dns.exception.Timeout, dns.resolver.NoNameservers) as exc:
        raise _TransientDNSError(str(exc)) from exc
    except dns.exception.DNSException:
        return None

    host = next(
        (str(r).rstrip(".") for r in ptr_answers if _hostname_is_proxy(str(r))), None
    )
    if host is None:
        return None

    # Forward-confirm: the proxy hostname must resolve back to this exact IP.
    try:
        a_answers = resolver.resolve(host, "A")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return None
    except (dns.exception.Timeout, dns.resolver.NoNameservers) as exc:
        raise _TransientDNSError(str(exc)) from exc
    except dns.exception.DNSException:
        return None

    return host if ip in {str(r) for r in a_answers} else None


async def _reverse_ptr_confirmed(ip: str) -> str | None:
    """Async wrapper: forward-confirmed proxy PTR for `ip`, retrying transients.

    Only timeouts / unreachable-nameserver failures are retried — an authoritative
    "no PTR" returns None immediately. Fail-safe: an IP that never resolves is
    never swept."""
    if not ip or _PRIVATE_RE.match(ip):
        return None
    loop = asyncio.get_event_loop()
    for attempt in range(_DNS_RETRIES):
        try:
            return await loop.run_in_executor(None, _ptr_and_confirm_sync, ip)
        except _TransientDNSError:
            if attempt + 1 < _DNS_RETRIES:
                await asyncio.sleep(_DNS_RETRY_BACKOFF)
        except Exception:
            return None
    return None  # exhausted retries on transient failures → treat as unverifiable


async def _distinct_visitor_ips(db: AsyncSession) -> list[str]:
    """All non-empty visitor IP addresses, across every site."""
    result = await db.execute(
        text(
            "SELECT DISTINCT ip_address FROM visitors "
            "WHERE ip_address IS NOT NULL AND ip_address <> ''"
        )
    )
    return [row[0] for row in result.fetchall()]


async def _find_proxy_ips(ips: list[str]) -> dict[str, str]:
    """Map each proxy IP → its confirmed PTR hostname (bounded concurrency)."""
    sem = asyncio.Semaphore(_DNS_CONCURRENCY)

    async def check(ip: str) -> tuple[str, str | None]:
        async with sem:
            return ip, await _reverse_ptr_confirmed(ip)

    results = await asyncio.gather(*(check(ip) for ip in ips))
    return {ip: host for ip, host in results if host is not None}


async def _seed_datacenter_cache(proxy_ips: list[str]) -> None:
    """Mark each proxy IP as datacenter in Redis so ingest drops it cheaply.

    Reuses the exact key + TTL `is_datacenter_ip` reads first, so future events
    short-circuit to a drop with no rDNS/ASN lookup. Best-effort: a Redis outage
    never fails the sweep (the DB scrub already happened)."""
    try:
        from apps.api.services.redis_client import get_redis

        redis = get_redis()
        for ip in proxy_ips:
            await redis.setex(f"{_DATACENTER_CACHE_PREFIX}{ip}", _DATACENTER_CACHE_TTL, "1")
    except Exception as exc:
        logger.warning("proxy_ptr_sweep_cache_seed_failed", error=str(exc))


async def _try_acquire_lock(db: AsyncSession) -> bool | None:
    """True = acquired, False = held elsewhere, None = unsupported (SQLite)."""
    try:
        result = await db.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"),
            {"key": _SWEEP_LOCK_KEY},
        )
        return bool(result.scalar())
    except Exception as exc:
        logger.warning("proxy_ptr_sweep_lock_unavailable", error=str(exc))
        return None


async def _release_lock(db: AsyncSession) -> None:
    try:
        await db.execute(
            text("SELECT pg_advisory_unlock(hashtext(:key))"),
            {"key": _SWEEP_LOCK_KEY},
        )
    except Exception:
        pass


async def _delete_proxy_visitors(db: AsyncSession, proxy_ips: list[str]) -> int:
    """Delete visitors on the proxy IPs plus their events, identifications and
    resolution logs (anchored on the matched site_id/visitor_id). Returns the
    number of visitor rows removed."""
    # Anchor set: the (site_id, visitor_id) pairs on the flagged IPs.
    matched = await db.execute(
        text(
            "SELECT site_id, visitor_id FROM visitors WHERE ip_address = ANY(:ips)"
        ),
        {"ips": proxy_ips},
    )
    keys = [(r[0], r[1]) for r in matched.fetchall()]
    if not keys:
        return 0

    # Events carry their own ip_address — clear every event from these IPs
    # (covers sessions whose visitor row was already aggregated away).
    await db.execute(
        text("DELETE FROM events WHERE ip_address = ANY(:ips)"), {"ips": proxy_ips}
    )
    # Child rows keyed by (site_id, visitor_id).
    site_ids = [k[0] for k in keys]
    visitor_ids = [k[1] for k in keys]
    for table in ("identified_visitors", "resolution_logs"):
        await db.execute(
            text(
                f"DELETE FROM {table} "
                "WHERE (site_id, visitor_id) IN "
                "(SELECT UNNEST(CAST(:sids AS text[])), UNNEST(CAST(:vids AS text[])))"
            ),
            {"sids": site_ids, "vids": visitor_ids},
        )
    result = await db.execute(
        text("DELETE FROM visitors WHERE ip_address = ANY(:ips)"), {"ips": proxy_ips}
    )
    await db.commit()
    return result.rowcount or 0


async def sweep_proxy_visitors(dry_run: bool = True) -> dict:
    """Reverse-DNS every stored visitor IP and scrub confirmed proxy traffic.

    dry_run=True (default) resolves + reports but deletes nothing. Returns:
    - {"status": "dry_run", "proxy_ips": N, "matches": {ip: host}, "would_delete_visitors": M}
    - {"status": "ok", "proxy_ips": N, "deleted_visitors": M, "matches": {...}}
    - {"status": "locked"}                 (another replica holds the lock)
    - {"status": "no_ips"}                  (no visitor IPs to check)
    """
    async with async_session() as lock_db:
        acquired = await _try_acquire_lock(lock_db)
        if acquired is False:
            logger.info("proxy_ptr_sweep_lock_busy")
            return {"status": "locked"}
        try:
            async with async_session() as db:
                ips = await _distinct_visitor_ips(db)
                if not ips:
                    return {"status": "no_ips"}

                matches = await _find_proxy_ips(ips)
                proxy_ips = sorted(matches)
                logger.info(
                    "proxy_ptr_sweep_scanned",
                    scanned=len(ips),
                    proxy_ips=len(proxy_ips),
                )

                if dry_run:
                    would = 0
                    if proxy_ips:
                        r = await db.execute(
                            text(
                                "SELECT count(*) FROM visitors WHERE ip_address = ANY(:ips)"
                            ),
                            {"ips": proxy_ips},
                        )
                        would = r.scalar() or 0
                    return {
                        "status": "dry_run",
                        "proxy_ips": len(proxy_ips),
                        "matches": matches,
                        "would_delete_visitors": would,
                    }

                deleted = 0
                if proxy_ips:
                    deleted = await _delete_proxy_visitors(db, proxy_ips)
                    await _seed_datacenter_cache(proxy_ips)
                logger.info(
                    "proxy_ptr_sweep_complete",
                    proxy_ips=len(proxy_ips),
                    deleted_visitors=deleted,
                )
                return {
                    "status": "ok",
                    "proxy_ips": len(proxy_ips),
                    "deleted_visitors": deleted,
                    "matches": matches,
                }
        finally:
            if acquired:
                await _release_lock(lock_db)
