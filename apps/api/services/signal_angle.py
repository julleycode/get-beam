"""Signal-aware creative angle + structured CTA types (pure, deterministic).

Two jobs, both side-effect free:

1. ``dominant_signal(profiles)`` picks ONE creative angle for a segment from the
   raw visitor profiles. The campaign planner then tells the model to write for
   that angle, instead of letting the model invent one from raw visitor data.
2. ``resolve_cta`` / ``cta_url`` turn the owner-stored ``Site.cta_config`` (plus
   ``Site.booking_url`` for ``book_demo``) into the allowed CTA set and the
   stored destination for a given type.

No I/O, no settings reads — callers pass flags/values in. This keeps the module
unit-testable and the flag-OFF paths of its callers untouched.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Iterable, Mapping

from apps.api.services.icp_fit import _STRONG_FIT_AT


class SignalAngle(str, Enum):
    JOB_CHANGE = "job_change"
    PRICING_INTENT = "pricing_intent"
    AI_REFERRAL = "ai_referral"
    HIGH_ICP_FIT = "high_icp_fit"
    REPEAT_VISIT = "repeat_visit"
    GENERAL = "general"


class CtaType(str, Enum):
    BOOK_DEMO = "book_demo"
    FREE_TRIAL = "free_trial"
    PRICING_PAGE = "pricing_page"
    RESOURCE = "resource"
    REPLY = "reply"


# Types whose stored URL must live on the site's own host (re-checked at
# redirect time). book_demo reuses Site.booking_url (cross-domain allowed);
# reply has no link at all.
SITE_HOST_CTA_TYPES: frozenset[CtaType] = frozenset(
    {CtaType.FREE_TRIAL, CtaType.PRICING_PAGE, CtaType.RESOURCE}
)

JOB_CHANGE_WINDOW_DAYS = 30
REPEAT_VISIT_SESSIONS = 3
DOMINANT_SHARE = 0.40
_PRICING_MARKERS = ("/pricing", "/plans")

# Server-constant guidance — never visitor text.
ANGLE_GUIDANCE: dict[SignalAngle, str] = {
    SignalAngle.JOB_CHANGE: (
        "Many of these people recently started a new role. Lead with helping "
        "them make an early win in the new job; do not congratulate by name."
    ),
    SignalAngle.PRICING_INTENT: (
        "These visitors looked at pricing/plans. Address cost and value "
        "directly; make the next step concrete and low-friction."
    ),
    SignalAngle.AI_REFERRAL: (
        "These visitors arrived from an AI assistant's answer. Assume they did "
        "research already; be crisp and confirm why the product fits."
    ),
    SignalAngle.HIGH_ICP_FIT: (
        "These visitors closely match the site's ideal customer profile. Speak "
        "to that audience's specific problem with confidence."
    ),
    SignalAngle.REPEAT_VISIT: (
        "These visitors came back several times. Acknowledge continued interest "
        "lightly and remove the last obstacle to trying it."
    ),
    SignalAngle.GENERAL: (
        "No single strong signal dominates this segment. Write clear, "
        "value-led copy."
    ),
}


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _page_urls(pages: Any) -> Iterable[str]:
    if not isinstance(pages, list):
        return ()
    out = []
    for p in pages:
        if isinstance(p, str):
            out.append(p)
        elif isinstance(p, dict):
            u = p.get("url") or p.get("path") or p.get("page")
            if isinstance(u, str):
                out.append(u)
    return out


def visitor_angle(
    profile: Mapping[str, Any],
    icp_fit: float | None = None,
    *,
    use_icp_fit: bool = False,
    now: datetime | None = None,
) -> SignalAngle:
    """Strongest signal for ONE visitor, per the fixed precedence."""
    now = now or datetime.now(timezone.utc)
    changed = _parse_dt(profile.get("job_changed_at"))
    if changed is not None and now - changed <= timedelta(days=JOB_CHANGE_WINDOW_DAYS):
        return SignalAngle.JOB_CHANGE
    for url in _page_urls(profile.get("pages_visited")):
        low = url.lower()
        if any(m in low for m in _PRICING_MARKERS):
            return SignalAngle.PRICING_INTENT
    if profile.get("ai_source"):
        return SignalAngle.AI_REFERRAL
    if use_icp_fit and icp_fit is not None and icp_fit >= _STRONG_FIT_AT:
        return SignalAngle.HIGH_ICP_FIT
    sessions = profile.get("total_sessions")
    if isinstance(sessions, (int, float)) and sessions >= REPEAT_VISIT_SESSIONS:
        return SignalAngle.REPEAT_VISIT
    return SignalAngle.GENERAL


def dominant_signal(
    profiles: list[Mapping[str, Any]],
    icp_fits: Mapping[str, float | None] | None = None,
    *,
    now: datetime | None = None,
) -> SignalAngle:
    """Segment angle = most common non-general visitor angle when its share of
    ALL visitors is >= 40%, else ``general``. ``icp_fits`` (visitor_id -> score)
    is passed only when ICP fit is enabled; otherwise that rung is skipped.
    Ties break by precedence order (deterministic)."""
    if not profiles:
        return SignalAngle.GENERAL
    use_icp = icp_fits is not None
    counts: Counter[SignalAngle] = Counter()
    for p in profiles:
        fit = icp_fits.get(str(p.get("visitor_id"))) if use_icp else None
        counts[visitor_angle(p, fit, use_icp_fit=use_icp, now=now)] += 1
    order = list(SignalAngle)
    best: SignalAngle | None = None
    for angle in order:
        if angle is SignalAngle.GENERAL or not counts[angle]:
            continue
        if best is None or counts[angle] > counts[best]:
            best = angle
    if best is None or counts[best] / len(profiles) < DOMINANT_SHARE:
        return SignalAngle.GENERAL
    return best


def parse_cta_type(value: Any) -> CtaType | None:
    try:
        return CtaType(value) if isinstance(value, str) else None
    except ValueError:
        return None


def cta_url(
    site_cfg: Mapping[str, Any] | None, cta_type: CtaType, booking_url: str | None
) -> str | None:
    """Owner-stored destination for a CTA type, or None (reply / unset)."""
    if cta_type is CtaType.REPLY:
        return None
    if cta_type is CtaType.BOOK_DEMO:
        return (booking_url or "").strip() or None
    types = (site_cfg or {}).get("types") if isinstance(site_cfg, Mapping) else None
    entry = types.get(cta_type.value) if isinstance(types, Mapping) else None
    url = entry.get("url") if isinstance(entry, Mapping) else None
    return (url.strip() or None) if isinstance(url, str) else None


def available_cta_types(
    site_cfg: Mapping[str, Any] | None, booking_url: str | None
) -> list[CtaType]:
    """CTA types the planner may pick: those with a stored URL, plus reply."""
    out = [t for t in CtaType if t is not CtaType.REPLY and cta_url(site_cfg, t, booking_url)]
    out.append(CtaType.REPLY)
    return out


def resolve_cta(
    site_cfg: Mapping[str, Any] | None,
    requested: Any,
    booking_url: str | None = None,
) -> CtaType:
    """Coerce a model-requested cta_type to an available one: requested if
    available, else the site default if available, else the first available
    linked type, else ``reply``."""
    allowed = available_cta_types(site_cfg, booking_url)
    req = parse_cta_type(requested)
    if req in allowed:
        return req  # type: ignore[return-value]
    default = parse_cta_type((site_cfg or {}).get("default") if isinstance(site_cfg, Mapping) else None)
    if default in allowed:
        return default  # type: ignore[return-value]
    return allowed[0]
