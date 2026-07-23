"""Hot-visitor alert — email the site owner the moment a high-intent US visitor
is identified, so they can reach out while the visit is still warm.

Gate: US traffic (beam only resolves US person-level) + intent_score >= HIGH_INTENT
+ the site's `hot_alert_enabled` toggle. Deduped once per (site, visitor) via Redis
so a re-resolution never re-pings. Best-effort — never raises into the resolve path.
"""

from html import escape

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services.email_sender import EmailSender
from apps.api.services.identity_classification import is_emailable_identity
from apps.api.services.redis_client import get_redis

logger = structlog.get_logger()

# A visitor is "hot" at the same intent bar the resolution sweep uses (>= 40).
HIGH_INTENT = 40
# One ping per (site, visitor) for a week — survives re-resolutions.
DEDUP_TTL_SECONDS = 7 * 24 * 3600
# Intent alerts (Handoff Detection H3) are meant to RECUR daily rather than
# dedupe for a week, so they use a 24h TTL — distinct from the hot-visitor TTL.
INTENT_ALERT_TTL_SECONDS = 24 * 3600


def should_alert(
    country_code: str | None, intent_score: float | None, enabled: bool
) -> bool:
    """Gate for the hot-visitor ping. Pure (no I/O) so it's unit-testable.

    Only US traffic qualifies — beam can't resolve non-US visitors, so a non-US
    "identification" is a company/IP guess we shouldn't ping about.
    """
    return (
        bool(enabled)
        and (country_code or "").upper() == "US"
        and (intent_score or 0) >= HIGH_INTENT
    )


async def maybe_send_hot_alert(
    db: AsyncSession, visitor: Visitor, identified: IdentifiedVisitor
) -> bool:
    """Email the owner about a freshly-identified hot visitor, if it qualifies.

    Returns True iff an email was sent. Callers wrap in try/except — a failed
    ping must never break identification.
    """
    site = (
        await db.execute(select(Site).where(Site.site_id == visitor.site_id))
    ).scalar_one_or_none()
    if site is None or not should_alert(
        visitor.country_code, visitor.intent_score, site.hot_alert_enabled
    ):
        return False

    # Dedup: one ping per (site, visitor). If Redis is unreachable, fall through
    # and send anyway — a rare duplicate beats a silently dropped alert.
    try:
        first = await get_redis().set(
            f"hot_alert:{visitor.site_id}:{visitor.visitor_id}",
            "1",
            nx=True,
            ex=DEDUP_TTL_SECONDS,
        )
        if not first:
            return False
    except Exception as e:  # noqa: BLE001 — best-effort dedup
        logger.warning("hot_alert_dedup_unavailable", error=str(e))

    owner = (
        await db.execute(select(User).where(User.id == site.user_id))
    ).scalar_one_or_none()
    if owner is None or not owner.email:
        return False

    # Only name/email the visitor when the identity is person-level. A company-
    # level guess (hunter/apollo) is a RANDOM employee, not the visitor — alert
    # that a high-intent visit happened without claiming/exposing a wrong person.
    is_person = is_emailable_identity(identified.resolution_provider)
    name = (
        (identified.full_name or identified.email or "A high-intent visitor")
        if is_person
        else "A high-intent visitor"
    )
    score = int(visitor.intent_score or 0)
    link = (
        f"{settings.frontend_url}/dashboard/visitors/{visitor.visitor_id}"
        f"?site={visitor.site_id}"
    )
    parts = [
        f"<p><b>{escape(name)}</b> just visited <b>{escape(site.name or '')}</b> — "
        f"intent {score}/100, US traffic.</p>"
    ]
    if is_person and identified.email:
        parts.append(f"<p>Email: {escape(identified.email)}</p>")
    parts.append(f'<p><a href="{escape(link, quote=True)}">Open in beam &rarr;</a></p>')

    await EmailSender().send(
        to_email=owner.email,
        subject=f"\U0001f525 Hot visitor on {site.name}: {name}",
        body_html="".join(parts),
        db=db,
        branding=True,
    )
    logger.info(
        "hot_alert_sent",
        site_id=visitor.site_id,
        visitor_id=visitor.visitor_id[:8],
    )
    return True


async def maybe_send_intent_alert(
    db: AsyncSession,
    *,
    site: Site,
    page_path: str,
    vendor: str,
    hit_count: int,
    window_minutes: int,
    is_spike: bool = False,
    multiplier: float | None = None,
) -> bool:
    """Email the owner a live AI-mediated intent signal (Handoff Detection H3).

    SITE-LEVEL only: the copy names the vendor, the page, the hit count, and the
    site — NEVER a person name, company name, email, or IP address (SPEC AC-H3-4).
    Reuses ``maybe_send_hot_alert``'s ``Site`` / ``EmailSender`` / Redis pattern.

    Gated on the existing ``site.hot_alert_enabled`` toggle (no new per-site flag
    this phase). Deduped per (site, page) for 24h so alerts recur daily rather
    than for a week. The spike variant uses a distinct dedup key so a spike and a
    baseline alert for the same page in the same day can both fire.

    Returns True iff an email was sent. Callers wrap in try/except.
    """
    if not site.hot_alert_enabled:
        return False

    # Dedup: base and spike alerts use separate keys so both can fire in a day.
    dedup_scope = "intent_alert:spike" if is_spike else "intent_alert"
    dedup_key = f"{dedup_scope}:{site.site_id}:{page_path}"
    try:
        first = await get_redis().set(
            dedup_key, "1", nx=True, ex=INTENT_ALERT_TTL_SECONDS
        )
        if not first:
            return False
    except Exception as e:  # noqa: BLE001 — best-effort dedup
        logger.warning("intent_alert_dedup_unavailable", error=str(e))

    owner = (
        await db.execute(select(User).where(User.id == site.user_id))
    ).scalar_one_or_none()
    if owner is None or not owner.email:
        return False

    # page_path is attacker-influenceable request-path data and vendor is a
    # classifier-derived label — HTML-escape BOTH before interpolating into the
    # email body, exactly like maybe_send_hot_alert escapes name/site.name. Build
    # the body from escaped fragments, never a raw f-string interpolation.
    safe_vendor = escape(vendor)
    safe_page = escape(page_path)
    safe_site = escape(site.name or "")
    parts = [
        f"<p><b>{safe_vendor}</b> fetched <b>{safe_page}</b> {hit_count}× in the "
        f"last {window_minutes} minutes on <b>{safe_site}</b>.</p>"
    ]
    if is_spike and multiplier is not None:
        parts.append(
            f"<p>This is a {escape(str(multiplier))}x spike over your usual rate.</p>"
        )

    await EmailSender().send(
        to_email=owner.email,
        subject=f"AI intent signal on {site.name}: {page_path}",
        body_html="".join(parts),
        db=db,
        branding=True,
    )
    logger.info(
        "intent_alert_sent",
        site_id=site.site_id,
        is_spike=is_spike,
    )
    return True
