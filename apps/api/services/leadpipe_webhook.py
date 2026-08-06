"""Ingest one Leadpipe identification pushed over the webhook.

The pull path (`LeadpipeMixin._call_leadpipe_api`) asks "did anyone get
identified on this domain?" and then has to *guess* which of our visitors each
returned record belongs to. The webhook inverts that: Leadpipe tells us at the
moment of identification. What it still does NOT tell us is our own
``visitor_id`` — so attaching the person to a visitor is this module's whole job.

Everything AFTER the attach is delegated to
``IdentityResolver._save_identified``: email validation, the paid-graph
name/email consistency gate, email dedup/merge, and the
``provider_candidate`` status mapping. That is deliberate — a second copy of
those gates written here would drift from the pull path, and the drift would
only ever be discovered by a wrong identity reaching a customer.

Idempotency needs no key of its own: ``uq_identified_site_visitor`` (UNIQUE on
site_id + visitor_id) plus the IntegrityError branch in ``_save_identified``
already collapse a redelivered payload onto the existing row.
"""

from datetime import timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.site import Site
from apps.api.models.visitor import Visitor
from apps.api.models.visitor_email import VisitorEmail
from apps.api.services.company_resolver import is_privacy_relay_ip
from apps.api.services.identity_providers.base import _url_to_host
from apps.api.services.identity_providers.leadpipe import LeadpipeMixin
from apps.api.services.identity_providers.matching import MatchingMixin
from apps.api.services.identity_resolver import IdentityResolver
from apps.api.services.pii_crypto import email_hash

logger = structlog.get_logger()

# The custom param Beam asks the Leadpipe SDK to carry (tracker.js writes it into
# the pixel's globalParams). Whether Leadpipe echoes it back on the webhook is
# unverified — tier 1 simply finds nothing when it doesn't, and the waterfall
# falls through to tier 2. That fall-through is the designed behavior, not a
# failure branch.
MARKER_KEY = "beam_visitor_id"

# Containers the marker may arrive in, checked in order. Deliberately an explicit
# list rather than a recursive search: unbounded recursion over a vendor payload
# is an easy way to pick up a same-named key from somewhere it does not belong.
_MARKER_CONTAINERS = ("static_params", "globalParams", "global_params", "event_data")

# Attach tiers, most trustworthy first. Recorded on the log line so "how did this
# identity get attached" is answerable per row instead of by re-deriving it.
TIER_MARKER = "marker"       # deterministic: our own id came back
TIER_EMAIL = "email"         # deterministic: the visitor typed this address here
TIER_IP_WINDOW = "ip_window"  # probabilistic: same IP, close in time

# Column widths on IdentifiedVisitor. Vendor payloads are untrusted input; a
# value longer than its column raises at flush time and would fail the whole
# request, so cut here instead. `email` is in this list for a second reason:
# _clean also drops non-strings, and every downstream reader of the address
# (here and in _save_identified) calls .strip() on it unguarded — a payload
# sending {"email": {...}} would otherwise raise AttributeError and 500.
_MAX_LEN = {"email": 320, "full_name": 200, "city": 100, "region": 100, "country": 5}


def _clean(value: object, limit: int) -> str | None:
    """Trim an untrusted payload string, drop control characters, cap length."""
    if not isinstance(value, str):
        return None
    cleaned = "".join(ch for ch in value if ch.isprintable()).strip()
    return cleaned[:limit] or None


def _unwrap(payload: dict) -> dict:
    """Return the identification record from whatever envelope it arrived in.

    Observed Leadpipe REST responses wrap rows in ``data``; a webhook may post
    the bare record or the same envelope. Accept both rather than guess.
    """
    inner = payload.get("data")
    if isinstance(inner, dict):
        return inner
    return payload


def _extract_marker(record: dict) -> str | None:
    """Find Beam's own visitor id in the payload, if the vendor echoed it."""
    direct = record.get(MARKER_KEY)
    if isinstance(direct, str) and direct.strip():
        return direct.strip()[:100]
    for container in _MARKER_CONTAINERS:
        blob = record.get(container)
        if not isinstance(blob, dict):
            continue
        found = blob.get(MARKER_KEY)
        if isinstance(found, str) and found.strip():
            return found.strip()[:100]
        # event_data nests static_params one level deeper (the shape the SDK
        # actually sends: {event_data: {static_params: {...}}}).
        nested = blob.get("static_params")
        if isinstance(nested, dict):
            found = nested.get(MARKER_KEY)
            if isinstance(found, str) and found.strip():
                return found.strip()[:100]
    return None


async def _resolve_site(db: AsyncSession, record: dict) -> Site | None:
    """Map the payload to ONE of our sites, or refuse.

    Keyed on ``Site.leadpipe_pixel_id`` first: that id is 1-1 with a domain and
    Beam provisioned it itself, so the mapping is exact. Domain is only a
    fallback. A payload we cannot place is dropped — writing an identity to a
    guessed tenant is worse than losing it.
    """
    pixel_id = record.get("pixel_id") or record.get("pixelId")
    if isinstance(pixel_id, str) and pixel_id.strip():
        site = (
            await db.execute(
                select(Site).where(Site.leadpipe_pixel_id == pixel_id.strip())
            )
        ).scalar_one_or_none()
        if site:
            return site

    domain = record.get("domain") or record.get("website")
    host = _url_to_host(domain if isinstance(domain, str) else None)
    if not host:
        return None
    # Compare host-to-host: Site.url holds a full URL, so a raw LIKE on it would
    # match a site whose PATH happens to contain the domain. The ILIKE is only a
    # prefilter; the equality below is the real check.
    # Escape LIKE wildcards first — `host` comes straight from the payload, and
    # an unescaped "%" would turn the prefilter into "load every site".
    pattern = host.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    candidates = (
        await db.execute(
            select(Site).where(Site.url.ilike(f"%{pattern}%", escape="\\"))
        )
    ).scalars().all()
    for site in candidates:
        if _url_to_host(site.url) == host:
            return site
    return None


async def _attach_visitor(
    db: AsyncSession, site: Site, record: dict, person: dict
) -> tuple[Visitor | None, str | None]:
    """Find the visitor this identification belongs to. Returns (visitor, tier).

    ``person`` is the already-parsed and sanitized identity (see
    ``ingest_identification``) — parsed once by the caller so the two functions
    cannot disagree about what the payload said, and so every string here has
    already been through ``_clean``.
    """

    # ── Tier 1: our own id, echoed back ──────────────────────────────────
    marker = _extract_marker(record)
    if marker:
        visitor = (
            await db.execute(
                select(Visitor).where(
                    Visitor.site_id == site.site_id,
                    Visitor.visitor_id == marker,
                )
            )
        ).scalar_one_or_none()
        if visitor:
            return visitor, TIER_MARKER
        # A marker that matches no visitor is a stale or forged id — fall
        # through rather than trust it.
        logger.info("leadpipe_webhook_marker_unknown", site_id=site.site_id)

    # ── Tier 2: an address this visitor typed on this site ───────────────
    email = (person.get("email") or "").strip().lower()
    if email:
        visitor_id = (
            await db.execute(
                select(VisitorEmail.visitor_id)
                .where(
                    VisitorEmail.site_id == site.site_id,
                    # Blind index is the indexed path; the plaintext comparison
                    # covers rows written before the dual-write landed.
                    (VisitorEmail.email_bidx == email_hash(email))
                    | (func.lower(VisitorEmail.email) == email),
                )
                .order_by(VisitorEmail.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if visitor_id:
            visitor = (
                await db.execute(
                    select(Visitor).where(
                        Visitor.site_id == site.site_id,
                        Visitor.visitor_id == visitor_id,
                    )
                )
            ).scalar_one_or_none()
            if visitor:
                return visitor, TIER_EMAIL

    # ── Tier 3: same IP, close in time — probabilistic ───────────────────
    ip = record.get("ip") or record.get("ipAddress")
    if not isinstance(ip, str) or not ip.strip():
        return None, None

    record_ts = MatchingMixin._parse_record_timestamp(record)
    if record_ts is None:
        # Same refusal the pull path makes: office and CGNAT IPs are shared by
        # many people, so IP equality without a time bound could be anyone.
        logger.info("leadpipe_webhook_no_timestamp_skipped", site_id=site.site_id)
        return None, None

    if is_privacy_relay_ip(ip):
        # Only tier 3 checks this. Tiers 1 and 2 do not derive the identity from
        # the IP at all, so refusing them on a masked IP would drop real people.
        logger.info("leadpipe_webhook_privacy_relay_skipped", site_id=site.site_id)
        return None, None

    window = MatchingMixin._IDENTITY_MATCH_WINDOW
    naive_ts = record_ts.astimezone(timezone.utc).replace(tzinfo=None)
    visitor = (
        await db.execute(
            select(Visitor)
            .where(
                Visitor.site_id == site.site_id,
                Visitor.ip_address == ip.strip(),
                Visitor.last_seen >= naive_ts - window,
                Visitor.last_seen <= naive_ts + window,
            )
            .order_by(Visitor.last_seen.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if visitor:
        return visitor, TIER_IP_WINDOW
    return None, None


async def ingest_identification(db: AsyncSession, payload: dict) -> str:
    """Process one webhook identification. Returns a short outcome keyword.

    Outcomes: ``saved`` / ``unknown_site`` / ``no_identity_data`` /
    ``no_visitor_match`` / ``rejected`` (a quality gate refused it).
    """
    record = _unwrap(payload)
    if not isinstance(record, dict):
        return "no_identity_data"

    site = await _resolve_site(db, record)
    if not site:
        logger.info("leadpipe_webhook_unknown_site")
        return "unknown_site"

    person = LeadpipeMixin._parse_leadpipe_person(record)
    for field, limit in _MAX_LEN.items():
        person[field] = _clean(person.get(field), limit)
    if not person.get("email") and not person.get("full_name"):
        return "no_identity_data"

    visitor, tier = await _attach_visitor(db, site, record, person)
    if not visitor:
        logger.info("leadpipe_webhook_no_visitor_match", site_id=site.site_id)
        return "no_visitor_match"

    if tier == TIER_IP_WINDOW:
        # Same ceiling the pull path puts on a weak match. An identity attached
        # by IP proximity is a guess, and the webhook does not make the guess
        # any better than the poll did.
        person["confidence_score"] = min(
            person.get("confidence_score") or 0.0,
            MatchingMixin._WEAK_MATCH_MAX_CONFIDENCE,
        )

    # Read the ids out now: on a redelivery _save_identified hits the unique
    # index, rolls back, and every instance in the session is expired — touching
    # site.* or visitor.* after that would lazy-load from a sync context.
    log_ctx = {
        "site_id": site.site_id,
        "visitor_id": visitor.visitor_id[:8],
        "tier": tier,
    }

    # One shared write path with the pull resolver: every P0 quality gate and the
    # provider_candidate status mapping live in there, not here.
    row = await IdentityResolver(db)._save_identified(visitor, person, "leadpipe")
    if row is None:
        logger.info("leadpipe_webhook_rejected", **log_ctx)
        return "rejected"

    logger.info("leadpipe_webhook_identity_saved", **log_ctx)
    return "saved"
