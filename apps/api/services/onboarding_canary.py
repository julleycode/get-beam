"""Onboarding canary — "we caught you" data assembly.

Two halves with deliberately different data paths:

| Half                              | Source                          | DB read? |
|-----------------------------------|---------------------------------|----------|
| Where you are (pin, city, network)| the CALLER's own IP             | No       |
| What you did (page list)          | fingerprint join, Beam's site   | Yes      |

Geo is NEVER read from a matched ``Visitor.ip_address``. A fingerprint collision
can therefore never disclose someone else's location — the only IP involved is
the requester's own. It also means the map is not gated on the visit landing, so
adblocker / DNT / VPN users still get a reveal.

``fetch_journey`` is the shared extraction of the query that used to live only
inside ``routers/demo.demo_journey``. The NEW caller passes ``site_id`` (Beam's
own site) — ``/demo/journey`` keeps calling it with ``site_id=None`` so the
static funnel's behaviour is unchanged.
"""

from datetime import datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.event import Event
from apps.api.models.visitor import Visitor
from apps.api.services.company_resolver import (
    classify_org_kind,
    is_privacy_relay_ip,
)

logger = structlog.get_logger()

MAX_PAGES = 8
# Radius drawn when the geo source reports no measured accuracy (ip-api never
# does). Deliberately round: IP geo is city-level at best.
_DEFAULT_ACCURACY_KM = 25
JOURNEY_WINDOW_HOURS = 1
_EVENT_ROW_LIMIT = 60


async def fetch_journey(
    db: AsyncSession,
    fingerprint: str,
    *,
    site_id: str | None = None,
) -> list[dict]:
    """Pages this fingerprint browsed in the last hour, in order, with seconds.

    ``site_id=None`` reproduces the legacy /demo/journey behaviour verbatim (no
    site scoping). Pass a site id on any NEW path — an unscoped fingerprint
    match is cross-tenant by construction.

    Durations live in separate ``time_on_page`` rows keyed by url (the pixel
    fires them on page leave), so those seconds are merged onto each pageview.
    Read-only. Returns [] on any failure — never raises.
    """
    fp = (fingerprint or "").strip()
    if not fp.startswith("fp2_"):
        return []

    # Naive UTC to match Event.created_at (TIMESTAMP WITHOUT TIME ZONE — the
    # ingest path strips tzinfo). An aware datetime would error in asyncpg.
    since = datetime.utcnow() - timedelta(hours=JOURNEY_WINDOW_HOURS)

    try:
        visitor_q = select(Visitor.visitor_id).where(Visitor.fingerprint == fp)
        if site_id:
            visitor_q = visitor_q.where(Visitor.site_id == site_id)
        vids = (await db.execute(visitor_q)).scalars().all()
        if not vids:
            return []

        rows = (
            await db.execute(
                select(
                    Event.event_type,
                    Event.page_path,
                    Event.page_title,
                    Event.url,
                    Event.time_on_page,
                    Event.created_at,
                )
                .where(
                    Event.visitor_id.in_(vids),
                    Event.event_type.in_(("pageview", "time_on_page")),
                    Event.created_at >= since,
                )
                .order_by(Event.created_at.asc())
                .limit(_EVENT_ROW_LIMIT)
            )
        ).all()
    except Exception as e:  # noqa: BLE001 — the reveal never 500s the onboarding
        logger.debug("canary_journey_failed", error=str(e))
        return []

    secs_by_url: dict[str, int] = {}
    for r in rows:
        if r.event_type == "time_on_page" and r.url:
            secs_by_url[r.url] = max(secs_by_url.get(r.url, 0), int(r.time_on_page or 0))

    pages: list[dict] = []
    for r in rows:
        if r.event_type != "pageview":
            continue
        pages.append(
            {
                "path": (r.page_path or r.url or "/"),
                "title": (r.page_title or "").strip(),
                "seconds": int(r.time_on_page or 0) or secs_by_url.get(r.url or "", 0),
                "at": r.created_at.isoformat() if r.created_at else None,
            }
        )
        if len(pages) >= MAX_PAGES:
            break

    return pages


def _strip_as_prefix(as_str: str | None) -> str:
    """"AS15169 Google LLC" -> "Google LLC". Mirrors company_resolver._ASN_RE."""
    from apps.api.services.company_resolver import _ASN_RE

    if not as_str:
        return ""
    return _ASN_RE.sub("", as_str).strip(" ,-")


def build_network(ip: str, geo) -> dict | None:
    """Network label + kind, or None when every rung is empty.

    Ladder (all rungs free, first non-empty wins):
      1. local MaxMind ASN org   (dead when maxmind_asn_db_path is "")
      2. ip-api ``org``          (usually the end org on corporate ranges)
      3. ip-api ``isp``          (the carrier)
      4. ip-api ``as`` minus the ASNNNN prefix
      5. nothing -> omit the line entirely. NEVER render "Unknown ISP"; a blank
         line beats an admission of ignorance in a moment whose job is to look
         omniscient.

    ``check_ip_privacy`` is deliberately NOT called — it needs an ipinfo token
    and a network round-trip for zero display benefit.
    """
    org = (getattr(geo, "org", "") or "").strip() if geo is not None else ""
    isp = (getattr(geo, "isp", "") or "").strip() if geo is not None else ""
    as_str = (getattr(geo, "as_str", "") or "").strip() if geo is not None else ""

    label = ""
    try:
        from apps.api.services.asn_lookup import lookup_asn

        _, asn_org = lookup_asn(ip)
        label = (asn_org or "").strip()
    except Exception:
        label = ""

    if not label:
        label = org or isp or _strip_as_prefix(as_str)

    if not label:
        return None

    # Classify on the richest string available — the ASN prefix in `as_str` is
    # what classify_org_kind matches best; fall back to org/isp names.
    kind = classify_org_kind(as_str or org or isp or label)

    if is_privacy_relay_ip(ip) or kind == "cdn":
        kind = "relay"
    elif kind == "eyeball":
        # A distinct org on an eyeball range is the corporate case: the strongest
        # version of the line ("looks like you're on Acme Corp's network").
        kind = "company" if (org and org.lower() != isp.lower()) else "isp"

    return {"label": label[:120], "kind": kind}


def build_geo(geo) -> dict | None:
    """Public geo payload, or None when unusable.

    Rejects lat==lon==0.0 — Null Island is the classic version of this bug and
    renders as a pin in the Gulf of Guinea.
    """
    if geo is None:
        return None
    lat = getattr(geo, "lat", None)
    lon = getattr(geo, "lon", None)
    if lat is None or lon is None:
        return None
    if float(lat) == 0.0 and float(lon) == 0.0:
        return None
    # The local GeoLite2-City DB reports a real per-IP accuracy_radius; ip-api
    # reports nothing comparable. Prefer the measured radius when the City rung
    # was the source, and keep the fixed honest estimate otherwise — IP geo is
    # city-level at best, so a made-up precise number is worse than a round one.
    measured = getattr(geo, "accuracy_km", None)
    try:
        accuracy_km = max(1, int(measured)) if measured is not None else _DEFAULT_ACCURACY_KM
    except (TypeError, ValueError):
        accuracy_km = _DEFAULT_ACCURACY_KM

    return {
        "lat": float(lat),
        "lng": float(lon),
        "accuracy_km": accuracy_km,
        "city": (getattr(geo, "city", "") or ""),
        "region": (getattr(geo, "region", "") or ""),
        "country_code": (getattr(geo, "country_code", "") or ""),
    }
