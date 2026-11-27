"""Server-side conversions to ad platforms (conversion-apis_27-11-26).

Outbox pattern: ``run_conversion_sweep_once`` (APScheduler, flag-gated)
1. DISCOVERS work past per-(site, platform) watermarks on ``AdConversionConfig``
   — new ``Conversion`` rows (goal) and newly identified first-party visitors
   (lead) — and enqueues ``AdConversionDelivery`` rows (ON CONFLICT DO NOTHING);
2. SENDS due ``pending`` rows per (site, platform) via
   ``AdsProvider.send_conversions``, RE-CHECKING every fail-closed gate per row
   immediately before the batch (5a). A failing row becomes ``skipped_<gate>``
   and is never sent.

Nothing here runs in a request path — ingest and aggregation never call it, so
a provider outage can only ever affect the outbox (AC-6).

PII rules (E4): only SHA-256 digests leave this module; logs and ``last_error``
carry reason codes and counts only — never email, phone, IP, UA or click ids.
"""

from __future__ import annotations

import hashlib
import re
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.ad_conversion import (
    CONVERSION_TYPE_GOAL,
    CONVERSION_TYPE_LEAD,
    DELIVERY_STATUS_FAILED,
    DELIVERY_STATUS_PENDING,
    DELIVERY_STATUS_SENT,
    AdConversionConfig,
    AdConversionDelivery,
)
from apps.api.models.event import Event
from apps.api.models.outcome import Conversion
from apps.api.models.site import Site
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services.ads.base import ConversionEvent, ConversionResult
from apps.api.services.ads_push import EEA_COUNTRY_CODES
from apps.api.services.identity_classification import is_emailable_identity
from apps.api.services.pii_crypto import decrypt_pii

logger = structlog.get_logger()

# D2 / E8 — first-party identity allow-list. EXACT membership is pinned by a unit
# test; widening it is a user decision (D2), never an implementation choice.
#   form_capture       — email the visitor typed into a form on this site
#   pdl_person_enrich  — PDL enrich of an ALREADY-captured email (first-party email)
FIRST_PARTY_PROVIDERS = frozenset({"form_capture", "pdl_person_enrich"})

# Platforms the sweep SENDS to. LinkedIn is CSV-only in v1 (rows stay pending and
# are exported by the router after the same send-time recheck).
SENDABLE_PLATFORMS = ("meta", "google")

# Meta rejects a WHOLE batch if one event is >7 days old; guard at 6 days.
META_STALE_AFTER = timedelta(days=6)

DISCOVERY_BATCH = 500
SEND_BATCH = 500
BACKOFF_CAP_S = 3600

# ── skip reason vocabulary (status = "skipped_<gate>") ──
SKIP_FLAG_OFF = "skipped_flag_off"
SKIP_ERASED = "skipped_erased"
SKIP_DO_NOT_RESOLVE = "skipped_do_not_resolve"
SKIP_AGENT_ORIGIN = "skipped_agent_origin"
SKIP_ABUSE = "skipped_abuse"
SKIP_BOT = "skipped_bot"
SKIP_INTERNAL = "skipped_internal"
SKIP_NOT_FIRST_PARTY = "skipped_not_first_party"
SKIP_DO_NOT_EMAIL = "skipped_do_not_email"
SKIP_SUPPRESSED = "skipped_suppressed"
SKIP_EEA = "skipped_eea"
SKIP_COMPANY_EXCLUDED = "skipped_company_excluded"
SKIP_NO_IDENTIFIER = "skipped_no_identifier"
SKIP_UNMAPPED = "skipped_unmapped"
SKIP_STALE = "skipped_stale"
SKIP_NO_USER_AGENT = "skipped_no_user_agent"
SKIP_NO_CONNECTION = "skipped_no_connection"

# Minimal E.164 dial-code table for the default-country fallback. A number with
# an unknown default country and no explicit "+" prefix is OMITTED (never guessed).
_DIAL_CODES = {
    "US": "1", "CA": "1", "GB": "44", "AU": "61", "NZ": "64", "IN": "91",
    "SG": "65", "VN": "84", "JP": "81", "KR": "82", "CN": "86", "HK": "852",
    "BR": "55", "MX": "52", "ZA": "27", "AE": "971", "IL": "972", "PH": "63",
    "ID": "62", "MY": "60", "TH": "66", "CH": "41",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _naive_utc(dt: datetime) -> datetime:
    """For comparisons against TIMESTAMP WITHOUT TIME ZONE columns."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def sha256_email(email: str | None) -> str:
    value = (email or "").strip().lower()
    return hashlib.sha256(value.encode()).hexdigest() if value else ""


def normalize_phone_e164(raw: str | None, default_country: str | None) -> str | None:
    """Digits-only E.164 (no "+") or None. Rejects <8 or >15 digits."""
    if not raw:
        return None
    text = str(raw).strip()
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    if text.startswith("+"):
        pass
    elif digits.startswith("00"):
        digits = digits[2:]
    else:
        code = _DIAL_CODES.get((default_country or "").strip().upper())
        if not code:
            return None
        digits = code + digits.lstrip("0")
    if len(digits) < 8 or len(digits) > 15:
        return None
    return digits


def sha256_phone(raw: str | None, default_country: str | None) -> str:
    e164 = normalize_phone_e164(raw, default_country)
    return hashlib.sha256(e164.encode()).hexdigest() if e164 else ""


def backoff_seconds(attempts: int) -> int:
    return int(min((2 ** max(attempts, 0)) * 60, BACKOFF_CAP_S))


# ── gate matrix (pure) ───────────────────────────────────


@dataclass
class GateContext:
    flag_enabled: bool
    site_exists: bool
    visitor_exists: bool
    identity_exists: bool
    provider: str | None = None
    identity_status: str | None = None
    source_agent_visit_id: str | None = None
    is_abuse_flagged: bool = False
    do_not_resolve: bool = False
    is_bot_suspect: bool = False
    internal_override: str | None = None
    is_internal_suspect: bool = False
    do_not_email: bool = False
    suppressed: bool = False
    country: str | None = None
    has_email: bool = False
    company_excluded: bool = False


def is_internal_traffic(internal_override: str | None, is_internal_suspect: bool) -> bool:
    """E9: explicit "internal" OR (auto-suspect AND not explicitly cleared)."""
    if internal_override == "internal":
        return True
    return bool(is_internal_suspect) and internal_override != "not_internal"


def is_first_party_identity(
    provider: str | None,
    identity_status: str | None,
    source_agent_visit_id: str | None,
    is_abuse_flagged: bool,
) -> bool:
    """E8 lead predicate: allow-listed provider AND identified AND emailable."""
    return (
        provider in FIRST_PARTY_PROVIDERS
        and identity_status == "identified"
        and is_emailable_identity(provider, source_agent_visit_id, is_abuse_flagged)
    )


def evaluate_gates(ctx: GateContext) -> str | None:
    """First failing fail-closed gate as a ``skipped_*`` status, else None."""
    if not ctx.flag_enabled:
        return SKIP_FLAG_OFF
    if not (ctx.site_exists and ctx.visitor_exists and ctx.identity_exists):
        return SKIP_ERASED
    if ctx.do_not_resolve:
        return SKIP_DO_NOT_RESOLVE
    if ctx.source_agent_visit_id is not None:
        return SKIP_AGENT_ORIGIN
    if ctx.is_abuse_flagged:
        return SKIP_ABUSE
    if ctx.is_bot_suspect:
        return SKIP_BOT
    if is_internal_traffic(ctx.internal_override, ctx.is_internal_suspect):
        return SKIP_INTERNAL
    if not is_first_party_identity(
        ctx.provider, ctx.identity_status, ctx.source_agent_visit_id, ctx.is_abuse_flagged
    ):
        return SKIP_NOT_FIRST_PARTY
    if ctx.do_not_email:
        return SKIP_DO_NOT_EMAIL
    if ctx.suppressed:
        return SKIP_SUPPRESSED
    country = (ctx.country or "").strip().upper()
    if not country or country in EEA_COUNTRY_CODES:  # D3: EEA + unknown, both platforms
        return SKIP_EEA
    if ctx.company_excluded:
        return SKIP_COMPANY_EXCLUDED
    if not ctx.has_email:
        return SKIP_NO_IDENTIFIER
    return None


# ── context loading ──────────────────────────────────────


@dataclass
class _Identity:
    visitor: Visitor | None
    identity: IdentifiedVisitor | None
    email: str | None


async def _load_identity(db: AsyncSession, site_id: str, visitor_id: str) -> _Identity:
    visitor = (
        await db.execute(
            select(Visitor).where(Visitor.site_id == site_id, Visitor.visitor_id == visitor_id)
        )
    ).scalar_one_or_none()
    identity = (
        await db.execute(
            select(IdentifiedVisitor).where(
                IdentifiedVisitor.site_id == site_id, IdentifiedVisitor.visitor_id == visitor_id
            )
        )
    ).scalar_one_or_none()
    email = None
    if identity is not None:
        email = identity.email or decrypt_pii(getattr(identity, "email_ciphertext", None))
    return _Identity(visitor=visitor, identity=identity, email=email)


async def _company_excluded(db: AsyncSession, site_id: str, visitor_id: str) -> bool:
    """Company-exclusion check — OPTIONAL until company-exclusion-list lands.

    The company_exclusion module is a sibling plan; when absent this gate is a
    no-op. When present it fails CLOSED on error (treat as excluded).
    """
    if not settings.company_exclusion_enabled:
        return False
    try:
        from apps.api.services.company_exclusion import excluded_visitor_ids
    except ImportError:
        return False
    try:
        return visitor_id in await excluded_visitor_ids(db, site_id, [visitor_id])
    except Exception:  # noqa: BLE001 — fail closed
        logger.warning("ad_conversion_company_exclusion_check_failed", site_id=site_id)
        return True


async def build_gate_context(db: AsyncSession, site_id: str, visitor_id: str) -> tuple[GateContext, _Identity]:
    from apps.api.services.suppression import is_email_suppressed_any

    site_exists = (
        await db.execute(select(Site.id).where(Site.site_id == site_id))
    ).scalar_one_or_none() is not None
    loaded = await _load_identity(db, site_id, visitor_id)
    v, iv = loaded.visitor, loaded.identity
    suppressed = False
    if loaded.email:
        suppressed = await is_email_suppressed_any(
            db, loaded.email, ("do_not_email", "do_not_process", "do_not_sell", "erased")
        )
    ctx = GateContext(
        flag_enabled=bool(settings.ad_conversions_enabled),
        site_exists=site_exists,
        visitor_exists=v is not None,
        identity_exists=iv is not None,
        provider=iv.resolution_provider if iv else None,
        identity_status=v.identity_status if v else None,
        source_agent_visit_id=iv.source_agent_visit_id if iv else None,
        is_abuse_flagged=bool((v and v.is_abuse_flagged) or (iv and iv.is_abuse_flagged)),
        do_not_resolve=bool(v and v.do_not_resolve),
        is_bot_suspect=bool((v and v.is_bot_suspect) or (iv and iv.is_bot_suspect)),
        internal_override=v.internal_override if v else None,
        is_internal_suspect=bool(v and v.is_internal_suspect),
        do_not_email=bool(iv and iv.do_not_email),
        suppressed=suppressed,
        country=((iv.country if iv else None) or (v.country_code if v else None)),
        has_email=bool(loaded.email),
        company_excluded=(
            await _company_excluded(db, site_id, visitor_id) if (v is not None) else False
        ),
    )
    return ctx, loaded


# ── enqueue ──────────────────────────────────────────────


async def enqueue_conversion(
    db: AsyncSession,
    site_id: str,
    visitor_id: str,
    conversion_type: str,
    *,
    platform: str,
    dedup_id: str,
    occurred_at: datetime,
    goal_id: str | None = None,
    mapped: bool = True,
) -> str | None:
    """Insert one outbox row (ON CONFLICT DO NOTHING). Does NOT commit.

    Returns the row status written (``pending`` / ``skipped_*``), or None when
    nothing was written (flag OFF — zero rows, by contract — or a dedup hit).
    """
    if not settings.ad_conversions_enabled:
        return None
    if not mapped:
        status = SKIP_UNMAPPED
    else:
        ctx, _ = await build_gate_context(db, site_id, visitor_id)
        status = evaluate_gates(ctx) or DELIVERY_STATUS_PENDING
    result = await db.execute(
        pg_insert(AdConversionDelivery)
        .values(
            id=_uuid.uuid4(),
            site_id=site_id,
            visitor_id=visitor_id,
            platform=platform,
            conversion_type=conversion_type,
            goal_id=goal_id,
            dedup_id=str(dedup_id),
            occurred_at=_aware(occurred_at),
            status=status,
            attempts=0,
            last_error=None if status == DELIVERY_STATUS_PENDING else status,
        )
        .on_conflict_do_nothing(constraint="uq_ad_conv_delivery_dedup")
    )
    return status if (result.rowcount or 0) > 0 else None


# ── discovery ────────────────────────────────────────────


async def _discover_for_config(db: AsyncSession, cfg: AdConversionConfig) -> dict:
    stats = {"goal": 0, "lead": 0}
    event_map = dict(cfg.goal_event_map or {})
    floor = _aware(cfg.created_at) or _utcnow()

    # goal — Conversion rows past the goal watermark.
    goal_wm = _aware(cfg.goal_watermark_at) or floor
    rows = (
        await db.execute(
            select(Conversion.id, Conversion.visitor_id, Conversion.goal_id,
                   Conversion.occurred_at, Conversion.created_at)
            .where(Conversion.site_id == cfg.site_id, Conversion.created_at > _naive_utc(goal_wm))
            .order_by(Conversion.created_at.asc())
            .limit(DISCOVERY_BATCH)
        )
    ).all()
    for conv_id, visitor_id, goal_id, occurred_at, created_at in rows:
        gid = str(goal_id)
        status = await enqueue_conversion(
            db, cfg.site_id, visitor_id, CONVERSION_TYPE_GOAL,
            platform=cfg.platform, dedup_id=str(conv_id), occurred_at=occurred_at,
            goal_id=gid, mapped=bool(event_map.get(gid)),
        )
        if status:
            stats["goal"] += 1
        goal_wm = max(goal_wm, _aware(created_at))
    cfg.goal_watermark_at = goal_wm

    # lead — newly identified FIRST-PARTY visitors past the lead watermark.
    lead_wm = _aware(cfg.lead_watermark_at) or floor
    lead_ts = func.coalesce(IdentifiedVisitor.confirmed_at, IdentifiedVisitor.resolved_at)
    lrows = (
        await db.execute(
            select(IdentifiedVisitor, Visitor.identity_status, lead_ts.label("ts"))
            .join(
                Visitor,
                and_(Visitor.site_id == IdentifiedVisitor.site_id,
                     Visitor.visitor_id == IdentifiedVisitor.visitor_id),
            )
            .where(IdentifiedVisitor.site_id == cfg.site_id, lead_ts > _naive_utc(lead_wm))
            .order_by(lead_ts.asc())
            .limit(DISCOVERY_BATCH)
        )
    ).all()
    lead_enabled = bool(event_map.get(CONVERSION_TYPE_LEAD))
    for iv, identity_status, ts in lrows:
        lead_wm = max(lead_wm, _aware(ts))
        if not lead_enabled:
            continue
        if not is_first_party_identity(
            iv.resolution_provider, identity_status, iv.source_agent_visit_id, iv.is_abuse_flagged
        ):
            continue
        status = await enqueue_conversion(
            db, cfg.site_id, iv.visitor_id, CONVERSION_TYPE_LEAD,
            platform=cfg.platform, dedup_id=str(iv.id), occurred_at=ts,
        )
        if status:
            stats["lead"] += 1
    cfg.lead_watermark_at = lead_wm
    return stats


# ── send ─────────────────────────────────────────────────


async def _latest_event(db: AsyncSession, site_id: str, visitor_id: str, at: datetime):
    """URL + UA of the visitor's latest non-abuse event at/before ``at``."""
    row = (
        await db.execute(
            select(Event.url, Event.user_agent)
            .where(
                Event.site_id == site_id,
                Event.visitor_id == visitor_id,
                Event.is_flagged_abuse.is_(False),
                Event.created_at <= _naive_utc(at),
            )
            .order_by(Event.created_at.desc())
            .limit(1)
        )
    ).first()
    return (row[0] or "", row[1] or "") if row else ("", "")


async def prepare_event(
    db: AsyncSession,
    row: AdConversionDelivery,
    cfg: AdConversionConfig | None,
    now: datetime,
) -> tuple[ConversionEvent | None, str | None]:
    """Send-time recheck (5a/5b) + event build. Returns (event, skip_status)."""
    if cfg is None:
        return None, SKIP_UNMAPPED
    ctx, loaded = await build_gate_context(db, row.site_id, row.visitor_id)
    skip = evaluate_gates(ctx)
    if skip:
        return None, skip

    event_map = dict(cfg.goal_event_map or {})
    key = CONVERSION_TYPE_LEAD if row.conversion_type == CONVERSION_TYPE_LEAD else (row.goal_id or "")
    event_name = event_map.get(key)
    if not event_name:
        return None, SKIP_UNMAPPED
    if row.platform == "meta" and not (cfg.meta_dataset_id or "").strip():
        return None, SKIP_UNMAPPED
    if row.platform == "google" and not (
        (cfg.google_operating_account_id or "").strip()
        and (cfg.google_product_destination_id or "").strip()
    ):
        return None, SKIP_UNMAPPED

    occurred = _aware(row.occurred_at)
    url, ua = await _latest_event(db, row.site_id, row.visitor_id, occurred)
    if row.platform == "meta":
        if now - occurred > META_STALE_AFTER:
            return None, SKIP_STALE
        if not ua:
            return None, SKIP_NO_USER_AGENT

    iv = loaded.identity
    v = loaded.visitor
    country = (iv.country if iv else None) or (v.country_code if v else None)
    event = ConversionEvent(
        delivery_id=str(row.id),
        dedup_id=row.dedup_id,
        conversion_type=row.conversion_type,
        event_name=str(event_name),
        event_time=occurred,
        email_sha256=sha256_email(loaded.email),
        phone_sha256=sha256_phone(iv.phone if iv else None, country),
        click_ids=dict((v.click_ids if v else None) or {}),
        user_agent=ua,
        event_source_url=url,
    )
    return event, None


def _apply_result(row: AdConversionDelivery, res: ConversionResult, now: datetime) -> str:
    if res.ok:
        row.status = DELIVERY_STATUS_SENT
        row.sent_at = now
        row.last_error = None
        row.next_attempt_at = None
        return "sent"
    row.attempts = (row.attempts or 0) + 1
    row.last_error = (res.error or "send_failed")[:200]
    if (not res.transient) or row.attempts >= settings.ad_conversions_max_attempts:
        row.status = DELIVERY_STATUS_FAILED
        row.next_attempt_at = None
        return "failed"
    row.next_attempt_at = now + timedelta(seconds=backoff_seconds(row.attempts))
    return "retry"


async def _send_group(
    db: AsyncSession,
    site_id: str,
    platform: str,
    rows: list[AdConversionDelivery],
    now: datetime,
    stats: dict,
) -> None:
    from apps.api.services.ads.factory import get_provider
    from apps.api.services.ads_push import fresh_access_token, get_connection

    cfg = (
        await db.execute(
            select(AdConversionConfig).where(
                AdConversionConfig.site_id == site_id, AdConversionConfig.platform == platform
            )
        )
    ).scalar_one_or_none()
    conn = await get_connection(db, site_id, platform)

    ready: list[tuple[AdConversionDelivery, ConversionEvent]] = []
    for row in rows:
        event, skip = await prepare_event(db, row, cfg, now)
        if skip:
            row.status = skip
            row.last_error = skip
            row.next_attempt_at = None
            stats["skipped"] += 1
            continue
        ready.append((row, event))
    if not ready:
        return
    if conn is None or conn.status != "connected":
        for row, _ in ready:
            row.status = SKIP_NO_CONNECTION
            row.last_error = SKIP_NO_CONNECTION
            stats["skipped"] += 1
        return

    by_id = {str(r.id): r for r, _ in ready}
    try:
        if not settings.mock_external_apis:
            await fresh_access_token(db, conn)
        provider = get_provider(platform)
        results = await provider.send_conversions(conn, cfg, [e for _, e in ready])
    except Exception as exc:  # noqa: BLE001 — never propagate; reason code only
        logger.warning(
            "ad_conversion_send_crashed", site_id=site_id, platform=platform,
            error_type=type(exc).__name__,
        )
        results = [
            ConversionResult(delivery_id=d, ok=False, error="send_error", transient=True)
            for d in by_id
        ]
    seen: set[str] = set()
    for res in results:
        row = by_id.get(res.delivery_id)
        if row is None:
            continue
        seen.add(res.delivery_id)
        stats[_apply_result(row, res, now)] += 1
    for did, row in by_id.items():  # a provider that dropped a result → transient retry
        if did not in seen:
            stats[_apply_result(row, ConversionResult(did, False, "no_result", True), now)] += 1


async def run_conversion_sweep_once(db: AsyncSession, now: datetime | None = None) -> dict:
    """One discovery + send pass. Runtime flag check (N6). Commits."""
    stats = {"discovered": 0, "sent": 0, "failed": 0, "retry": 0, "skipped": 0}
    if not settings.ad_conversions_enabled:
        return stats
    now = _aware(now) or _utcnow()

    configs = (
        await db.execute(select(AdConversionConfig).order_by(AdConversionConfig.site_id))
    ).scalars().all()
    for cfg in configs:
        found = await _discover_for_config(db, cfg)
        stats["discovered"] += found["goal"] + found["lead"]
    await db.commit()

    due = (
        await db.execute(
            select(AdConversionDelivery)
            .where(
                AdConversionDelivery.status == DELIVERY_STATUS_PENDING,
                AdConversionDelivery.platform.in_(SENDABLE_PLATFORMS),
                or_(
                    AdConversionDelivery.next_attempt_at.is_(None),
                    AdConversionDelivery.next_attempt_at <= now,
                ),
            )
            .order_by(AdConversionDelivery.created_at.asc())
            .limit(SEND_BATCH)
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    groups: dict[tuple[str, str], list[AdConversionDelivery]] = {}
    for row in due:
        groups.setdefault((row.site_id, row.platform), []).append(row)
    for (site_id, platform), rows in groups.items():
        await _send_group(db, site_id, platform, rows, now, stats)
    await db.commit()
    logger.info("ad_conversion_sweep_done", **stats)
    return stats


async def linkedin_export_events(db: AsyncSession, site_id: str) -> list[ConversionEvent]:
    """Pending LinkedIn rows that pass the same send-time recheck (CSV-only v1)."""
    cfg = (
        await db.execute(
            select(AdConversionConfig).where(
                AdConversionConfig.site_id == site_id, AdConversionConfig.platform == "linkedin"
            )
        )
    ).scalar_one_or_none()
    rows = (
        await db.execute(
            select(AdConversionDelivery).where(
                AdConversionDelivery.site_id == site_id,
                AdConversionDelivery.platform == "linkedin",
                AdConversionDelivery.status == DELIVERY_STATUS_PENDING,
            ).order_by(AdConversionDelivery.created_at.asc()).limit(5000)
        )
    ).scalars().all()
    out: list[ConversionEvent] = []
    now = _utcnow()
    for row in rows:
        event, skip = await prepare_event(db, row, cfg, now)
        if event is not None and not skip:
            out.append(event)
    return out


__all__ = [
    "FIRST_PARTY_PROVIDERS",
    "GateContext",
    "evaluate_gates",
    "enqueue_conversion",
    "normalize_phone_e164",
    "run_conversion_sweep_once",
]
