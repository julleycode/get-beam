"""Shared ad-audience push logic — used by the router (sync) and the Celery
task (async).

The contact-resolution and safety-filter chain is NOT reimplemented here: it is
imported verbatim from services/csv_exporter.py (``_get_segment_visitors`` for
the suppression/do-not-email/agent-derived/do-not-sell filter chain, ``_sha256``
for hashing), so a CSV export and an API push always target the exact same
people. csv_exporter.py itself is never modified.

Only SHA256 digests leave this module — the payload builder emits
``HashedContact`` rows and no plaintext identifier ever reaches a provider.
"""

import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.ad_audience_link import AdAudienceLink
from apps.api.models.ad_connection import AdConnection
from apps.api.models.segment import SegmentMember
from apps.api.services.ads.base import HashedContact, sanitize_error
from apps.api.services.ads.factory import get_provider
from apps.api.services.ads.meta import MetaAudienceTermsError
from apps.api.services.csv_exporter import _get_segment_visitors, _sha256
from apps.api.services.encryption import decrypt_token, encrypt_token

logger = structlog.get_logger()

# SPEC OQ5: real per-platform minimum audience sizes are a Phase 2/3 docs-fetch
# item. Until then this placeholder drives the small-segment warning only — it
# never blocks a push.
MIN_AUDIENCE_SIZE = 1000
# Meta's TECHNICAL floor — a smaller audience is accepted but effectively
# unusable for targeting. Surfaced alongside MIN_AUDIENCE_SIZE so the warning
# explains both numbers (D1).
MIN_AUDIENCE_MATCHABLE = 100

# ── Phase 3 / SPEC OQ4 decision (c): blanket EEA exclusion for Google ────────
# Google requires per-user ad_user_data / ad_personalization consent signals for
# EEA-region users and silently drops rows that lack them. Beam has no
# per-visitor consent record today, so v1 never sends an EEA row to Google at
# all. Static ISO-3166 alpha-2 list of the 27 EU member states + the 3 EEA/EFTA
# members (IS, LI, NO); UK is not in the EEA post-Brexit and is not listed here.
# There is no other EEA constant in apps/api/ to reuse — this is the single
# source of truth. Applies to the GOOGLE push path ONLY: Meta's payload path is
# untouched by this filter.
EEA_COUNTRY_CODES = frozenset(
    {
        "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
        "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
        "SI", "ES", "SE",  # EU-27
        "IS", "LI", "NO",  # EEA/EFTA
    }
)


def exclude_eea_rows(rows: list[dict]) -> list[dict]:
    """Drop every row that is — or might be — in the EEA. FAIL CLOSED.

    A null/empty ``country`` means the resolution provider returned no country
    for that visitor (``identity_resolver`` has no guaranteed non-null source).
    An unknown country is treated as EEA-ambiguous and EXCLUDED, never assumed
    safe: failing open would risk shipping a real EEA visitor's hashed PII to
    Google without a meaningful consent determination, which is the exact
    opposite of the blanket-exclusion decision this implements.
    """
    kept: list[dict] = []
    for row in rows:
        country = (row.get("country") or "").strip().upper()
        if not country or country in EEA_COUNTRY_CODES:
            continue
        kept.append(row)
    return kept


@dataclass
class PushSegmentOutcome:
    found: bool
    pushed: int = 0
    failed: int = 0
    skipped: int = 0
    queued: bool = False
    platform_audience_id: str = ""
    warning: str = ""
    # AC7: structured companions to the free-text `warning`, so the UI can
    # render the real threshold instead of hardcoding a number.
    below_minimum: bool = False
    minimum_threshold: int = MIN_AUDIENCE_SIZE
    errors: list[str] = field(default_factory=list)


def build_hashed_contacts(rows: list[dict]) -> list[HashedContact]:
    """Turn visitor rows into hash-only audience members.

    Every field is SHA256(lowercased, stripped) via csv_exporter._sha256 — the
    same digest the Meta CSV export writes. Empty inputs stay empty (never a
    hash of "") so a provider can't match on a constant.
    """
    contacts: list[HashedContact] = []
    for row in rows:
        email = (row.get("email") or "").strip()
        if not email:
            continue

        def h(key: str) -> str:
            value = (row.get(key) or "").strip()
            return _sha256(value) if value else ""

        contacts.append(
            HashedContact(
                email_sha256=_sha256(email),
                phone_sha256=h("phone"),
                first_name_sha256=h("first_name"),
                last_name_sha256=h("last_name"),
                city_sha256=h("city"),
                region_sha256=h("region"),
                country_sha256=h("country"),
            )
        )
    return contacts


async def get_connection(
    db: AsyncSession, site_id: str, provider: str
) -> AdConnection | None:
    result = await db.execute(
        select(AdConnection).where(
            AdConnection.site_id == site_id, AdConnection.provider == provider
        )
    )
    return result.scalar_one_or_none()


async def _get_link(
    db: AsyncSession, connection_id, segment_id: str
) -> AdAudienceLink | None:
    result = await db.execute(
        select(AdAudienceLink).where(
            AdAudienceLink.connection_id == connection_id,
            AdAudienceLink.segment_id == segment_id,
        )
    )
    return result.scalar_one_or_none()


async def fresh_access_token(db: AsyncSession, conn: AdConnection) -> str:
    """Refresh the connection's access token when it is at/past expiry.

    Structurally mirrors ``crm_push.fresh_access_token`` with one deliberate
    difference: ``AdsProvider`` (services/ads/base.py) declares no
    ``refresh_tokens`` method — unlike ``CRMConnector``, which has a concrete
    ABC-level default. Google/LinkedIn providers therefore have no such method
    at all, so the lookup is ``getattr``-guarded: an absent refresher means
    "this provider's token lifecycle isn't managed here", and the push proceeds
    unchanged rather than raising ``AttributeError``.

    Meta note: the refresher takes the CURRENT access token (Meta has no
    separate refresh secret), so this must run BEFORE the stored token expires.

    Google note: the refresher takes the stored REFRESH secret instead — see
    ``GoogleAdsProvider.refresh_tokens``. The two shapes are not
    interchangeable, hence the provider-aware branch below.

    On refresh failure the connection is marked ``status="error"`` with a
    sanitized ``last_error`` — the panel's existing Reconnect affordance
    surfaces it. Never logs or returns a raw token.
    """
    token = decrypt_token(conn.access_token) if conn.access_token else ""
    expires = conn.token_expires_at
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if not (expires and expires <= datetime.now(timezone.utc)):
        return token

    provider_impl = get_provider(conn.provider)
    refresher = getattr(provider_impl, "refresh_tokens", None)
    if refresher is None or not token:
        return token

    # Provider-aware credential selection. Meta's refresher consumes the CURRENT
    # ACCESS token (it has no separate refresh secret); Google's consumes the
    # stored REFRESH secret and would reject an access token outright.
    if conn.provider == "google":
        refresh_secret = decrypt_token(conn.refresh_token) if conn.refresh_token else ""
        if not refresh_secret:
            return token
        credential = refresh_secret
    else:
        credential = token

    try:
        tokens = await refresher(credential)
    except Exception as exc:  # noqa: BLE001 — persist a sanitized, PII-free error
        conn.status = "error"
        conn.is_valid = False
        conn.last_error = sanitize_error(exc, "Token refresh failed")[:500]
        await db.commit()
        logger.warning("ads_token_refresh_failed", provider=conn.provider)
        return token

    conn.access_token = encrypt_token(tokens.access_token)
    if tokens.refresh_token:
        conn.refresh_token = encrypt_token(tokens.refresh_token)
    conn.token_expires_at = tokens.expires_at
    await db.commit()
    logger.info("ads_token_refreshed", provider=conn.provider)
    return tokens.access_token


async def push_segment_to_ads(
    db: AsyncSession, site_id: str, provider: str, segment_id: str
) -> PushSegmentOutcome:
    """Push one segment's safety-cleared, hashed contacts to one ad connection.

    No rate-limit check here — callers reserve a slot before invoking (so the
    Celery task and the request path don't double-count), matching crm_push.
    """
    conn = await get_connection(db, site_id, provider)
    if conn is None:
        return PushSegmentOutcome(found=False)

    member_count = (
        await db.scalar(
            select(func.count())
            .select_from(SegmentMember)
            .where(SegmentMember.segment_id == segment_id)
        )
        or 0
    )

    # Offload big segments to a worker ONLY when one is actually consuming the
    # broker. One condition, two flags — resolved truth table:
    #
    #   ads_async_push | celery_worker_enabled | behavior
    #   ---------------|-----------------------|----------------------------------
    #   False (default)| False (default)       | inline (today's exact behavior)
    #   False          | True                  | inline (async is opt-in per surface)
    #   True           | False                 | inline + warning (NEVER .delay():
    #                  |                       | no consumer = silent drop)
    #   True           | True                  | .delay(), return queued=True
    #
    # The inline fallback is the rest of this function — the same safety-filter
    # chain and tenant scoping the task body would have run.
    _async_requested = (
        settings.ads_async_push and member_count > settings.ads_async_push_threshold
    )
    if _async_requested and not settings.celery_worker_enabled:
        logger.warning(
            "async_push_requested_without_worker",
            surface="ads",
            site_id=site_id,
            provider=provider,
            members=member_count,
        )
    if _async_requested and settings.celery_worker_enabled:
        from apps.api.tasks.ads_tasks import push_segment_to_ads_task

        push_segment_to_ads_task.delay(site_id, provider, segment_id)
        logger.info(
            "ads_push_queued", site_id=site_id, provider=provider, members=member_count
        )
        return PushSegmentOutcome(found=True, queued=True)

    # Identical safety-filter chain to the CSV export and the CRM push:
    # do_not_email, non-emailable identity (incl. agent-derived), do_not_sell.
    rows = await _get_segment_visitors(db, segment_id, exclude_known=False)
    # Phase 3, Google ONLY: drop EEA (and unknown-country) rows after the shared
    # safety-filter chain above. Excluded rows fall out as ordinary "skipped".
    if provider == "google":
        rows = exclude_eea_rows(rows)
    contacts = build_hashed_contacts(rows)
    skipped = max(0, member_count - len(contacts))

    link = await _get_link(db, conn.id, segment_id)

    provider_impl = get_provider(provider)
    # Refresh first so a long-running/queued push doesn't fail on a stale token.
    await fresh_access_token(db, conn)
    try:
        result = await provider_impl.create_or_update_audience(conn, link, contacts)
    except NotImplementedError:
        raise
    except MetaAudienceTermsError as exc:
        # AC13: keep this message verbatim — it names the specific precondition
        # and carries the per-account remediation URL, unlike the generic
        # sanitized branch below. Contains no PII (account id + static URL only).
        conn.status = "error"
        conn.is_valid = False
        conn.last_error = str(exc)[:500]
        await db.commit()
        logger.warning("ads_push_blocked_tos", site_id=site_id, provider=provider)
        return PushSegmentOutcome(
            found=True, failed=len(contacts), skipped=skipped, errors=[conn.last_error]
        )
    except Exception as exc:  # noqa: BLE001 — persist a sanitized, PII-free error
        conn.status = "error"
        conn.is_valid = False
        conn.last_error = sanitize_error(exc, "Audience push failed")[:500]
        await db.commit()
        logger.warning("ads_push_failed", site_id=site_id, provider=provider)
        return PushSegmentOutcome(
            found=True, failed=len(contacts), skipped=skipped, errors=[conn.last_error]
        )

    now = datetime.now(timezone.utc)
    # Upsert the (connection_id, segment_id) link so a repeat push reuses the
    # same platform audience instead of creating a second one. ON CONFLICT keeps
    # two simultaneous pushes race-safe.
    stmt = (
        pg_insert(AdAudienceLink)
        .values(
            id=_uuid.uuid4(),
            connection_id=conn.id,
            segment_id=segment_id,
            platform_audience_id=result.platform_audience_id,
            last_pushed_at=now,
            last_push_count=result.pushed,
        )
        .on_conflict_do_update(
            constraint="uq_ad_audience_link",
            set_={
                "platform_audience_id": result.platform_audience_id,
                "last_pushed_at": now,
                "last_push_count": result.pushed,
            },
        )
    )
    await db.execute(stmt)

    conn.last_pushed_at = now
    if result.failed and not result.pushed:
        conn.status = "error"
        conn.is_valid = False
        conn.last_error = "; ".join(result.errors)[:500] or "Push failed"
    else:
        conn.status = "connected"
        conn.last_error = None
    await db.commit()

    below_minimum = len(contacts) < MIN_AUDIENCE_SIZE
    warning = ""
    if below_minimum:
        warning = (
            f"This audience has {len(contacts)} matched contacts. Ad platforms "
            f"accept audiences from about {MIN_AUDIENCE_MATCHABLE} contacts, but "
            f"typically need around {MIN_AUDIENCE_SIZE} before matching and "
            "targeting quality is reliable — the push still went through."
        )

    logger.info(
        "ads_push_completed",
        site_id=site_id,
        provider=provider,
        segment_id=segment_id,
        pushed=result.pushed,
        failed=result.failed,
        skipped=skipped,
    )
    return PushSegmentOutcome(
        found=True,
        pushed=result.pushed,
        failed=result.failed,
        skipped=skipped,
        platform_audience_id=result.platform_audience_id,
        warning=warning,
        below_minimum=below_minimum,
        minimum_threshold=MIN_AUDIENCE_SIZE,
        errors=result.errors,
    )
