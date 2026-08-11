"""Onboarding canary — the authed "we caught you" moment.

``POST /api/v1/onboarding/canary`` shows a brand-new user Beam working on
*themselves*, before they install anything: Beam's pixel already runs on
getbeam.fyi, so the onboarding sends them there and then replays the visit.

Security posture, all deliberate:

* **The IP is never in the response.** It is logged truncated (``ip[:8]``), as
  the rest of the onboarding surface does. This is a conscious divergence from
  ``/demo/identify``, which returns the full unredacted IP.
* IP comes from ``services/ip_resolution.resolve_client_ip`` — NOT
  ``demo._client_ip``, which reads ``X-Forwarded-For`` first with no trust check
  and is therefore client-spoofable.
* The journey query is scoped to ``settings.beam_self_site_id``. Without that
  predicate a fingerprint collision returns another tenant's pages.
* Flag off => 404 on both routes (dormant, not revealed — the
  ``agent_fetch_beacon_enabled`` posture).

Rate limit is 30/minute, not the 12/minute used elsewhere on the onboarding
surface: the client polls this endpoint for up to 90s while the user reads the
other tab (~27 calls at the 2s->4s backoff cadence). 12/minute would 429
mid-reveal.
"""

from datetime import datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.dependencies import get_current_user, require_admin
from apps.api.models.database import get_db
from apps.api.models.identity_feedback import (
    FEEDBACK_REASONS,
    NOTE_MAX_CHARS,
    IdentityFeedback,
)
from apps.api.models.user import User
from apps.api.services.geoip import resolve_geoip_full
from apps.api.services.ip_resolution import resolve_client_ip
from apps.api.services.onboarding_canary import build_geo, build_network, fetch_journey
from apps.api.services.rate_limiter import limiter

logger = structlog.get_logger()

router = APIRouter(tags=["onboarding"])


def _require_flag() -> None:
    if not settings.location_reveal_enabled:
        # Dormant: do not reveal the endpoint exists when disabled.
        raise HTTPException(status_code=404, detail="Not Found")


class CanaryBody(BaseModel):
    fingerprint: str | None = None


@router.post("/canary")
@limiter.limit("30/minute")
async def onboarding_canary(
    request: Request,
    body: CanaryBody = CanaryBody(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return where the caller is (their own IP) and what they just read.

    Never 500s: a provider failure degrades to ``geo: null`` rather than an
    error, because this runs inside a chat the user cannot retry.
    """
    _require_flag()

    fp = (body.fingerprint or "").strip()
    ip = resolve_client_ip(request)

    # Journey: DB, fingerprint-matched, SCOPED to Beam's own site.
    pages: list[dict] = []
    if fp:
        pages = await fetch_journey(db, fp, site_id=settings.beam_self_site_id)

    # Geo: the caller's own IP only. Never Visitor.ip_address.
    geo_raw = None
    reason: str | None = None
    try:
        geo_raw = await resolve_geoip_full(ip)
    except Exception as e:  # noqa: BLE001 — defensive; resolve_geoip_full swallows already
        logger.debug("canary_geo_failed", ip=ip[:8], error=str(e))
    if geo_raw is None:
        reason = "provider_unavailable"

    geo = build_geo(geo_raw)
    network = build_network(ip, geo_raw) if geo_raw is not None else None

    logger.info(
        "onboarding_canary",
        ip=ip[:8],
        fp=fp[:12],
        pages=len(pages),
        has_geo=geo is not None,
    )

    result: dict = {
        "landed": bool(pages),
        "pages": pages,
        "geo": geo,
        "network": network,
    }
    if reason:
        result["reason"] = reason
    return result


class IdentityFeedbackBody(BaseModel):
    reasons: list[str] = Field(default_factory=list)
    note: str | None = None
    shown: dict = Field(default_factory=dict)
    site_id: str | None = None
    fingerprint: str | None = None


@router.post("/identity-feedback", status_code=204)
@limiter.limit("30/minute")
async def onboarding_identity_feedback(
    request: Request,
    body: IdentityFeedbackBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Record a "not quite" answer. 204 always (the client is optimistic).

    Unknown reasons are dropped rather than stored so the counts stay analysable.
    """
    _require_flag()

    reasons = [r for r in (body.reasons or []) if r in FEEDBACK_REASONS]
    note = (body.note or "").strip()[:NOTE_MAX_CHARS] or None

    db.add(
        IdentityFeedback(
            user_id=user.id,
            site_id=(body.site_id or None),
            fingerprint=(body.fingerprint or None),
            surface="onboarding_canary",
            shown=body.shown or {},
            reasons=reasons,
            note=note,
        )
    )
    await db.commit()

    logger.info("onboarding_identity_feedback", reasons=reasons, has_note=bool(note))
    return Response(status_code=204)


@router.get("/identity-feedback/stats")
async def onboarding_identity_feedback_stats(
    days: int = Query(30, ge=1, le=365),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Counts by reason over the last `days` days. Admin-only, read-only, no PII.

    Closes the write-only loop: Phase 1 created the table and Phase 3 started
    writing to it, but nothing read it. The concrete consumer is the precision
    metric the model's own docstring names — cross-check the ``vpn_or_proxy``
    count against ``company_resolver.check_ip_privacy`` on the same traffic to
    grade relay detection without paying a provider, and read ``wrong_city`` as
    the running error rate of IP geo (the number that says whether the MaxMind
    GeoLite2-City migration actually helped).

    NOT tenant-scoped, unlike ``/sites/{id}/ingest-health``: ``site_id`` is
    nullable here by design — the canary runs BEFORE site creation, so most rows
    have no site and a per-site view would be mostly empty. ``require_admin``
    (the ``request_logs`` precedent) is the gate instead.

    PII posture: aggregate counts only. The ``shown`` JSONB holds place names and
    a rounded lat-lng and is never returned, not even sampled. ``note`` is
    free text so only its presence is counted, never its content.

    Reports ``enabled`` rather than 404ing when the flag is off — an operator
    still needs to read the history of a feature they just switched off, and the
    field distinguishes "nobody complained" from "capture is switched off"
    (the ``request_logs`` /stats convention).
    """
    since = datetime.utcnow() - timedelta(days=days)
    scope = IdentityFeedback.created_at >= since

    total, with_note = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(IdentityFeedback.note.isnot(None)),
            ).where(scope)
        )
    ).one()

    # `reasons` is a text[]; unnest in a subquery so the GROUP BY is over a plain
    # column rather than a set-returning function in the select list.
    unnested = (
        select(func.unnest(IdentityFeedback.reasons).label("reason"))
        .where(scope)
        .subquery()
    )
    reason_counts = dict(
        (
            await db.execute(
                select(unnested.c.reason, func.count()).group_by(unnested.c.reason)
            )
        ).all()
    )

    surface_rows = (
        await db.execute(
            select(IdentityFeedback.surface, func.count())
            .where(scope)
            .group_by(IdentityFeedback.surface)
            .order_by(func.count().desc())
        )
    ).all()

    return {
        "enabled": settings.location_reveal_enabled,
        "window_days": days,
        "total": int(total or 0),
        "with_note": int(with_note or 0),
        # Zero-filled over the known vocabulary so an untouched reason reads as a
        # real 0 rather than a missing key the caller has to guess about.
        "by_reason": [
            {"reason": r, "count": int(reason_counts.get(r, 0))}
            for r in sorted(FEEDBACK_REASONS)
        ],
        "by_surface": [{"surface": s, "count": int(c)} for s, c in surface_rows],
    }
