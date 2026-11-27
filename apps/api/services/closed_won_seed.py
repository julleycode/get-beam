"""Closed-won seed audiences + lookalikes (closed-won-lookalikes_27-11-26).

Flow: CRM/webhook/CSV closed-won contacts -> ``crm_closed_won_contacts``
(blind index + ciphertext only) -> exclusions -> decrypt in-process ->
SHA-256 -> ``create_or_update_audience`` (seed) -> ``create_lookalike``.

Safety rules (plan hard stops):
- Only SHA-256 digests leave Beam (``ads_push.build_hashed_contacts``).
- Every ``IdentifiedVisitor.email_bidx`` read is scoped to ``site_id`` (N6).
- Erased people are never ingested (N5) and every seed re-checks suppression.
- No plaintext email is logged or stored.

The seed and lookalike ids live on two sentinel ``AdAudienceLink`` rows per
connection: ``closed_won_seed`` and ``closed_won_lookalike:{COUNTRY}:{param}``
(contract E7 — the spec is encoded in ``segment_id``; no schema change).
"""

from __future__ import annotations

import csv
import io
import re
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.ad_audience_link import AdAudienceLink
from apps.api.models.crm_closed_won import CrmClosedWonContact
from apps.api.models.crm_connection import CrmConnection
from apps.api.models.suppression import SuppressionEntry
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services.ads.base import LookalikeResult, LookalikeSpec, sanitize_error
from apps.api.services.ads.factory import get_provider
from apps.api.services.ads.meta import MetaAudienceTermsError
from apps.api.services.ads_push import (
    EEA_COUNTRY_CODES,
    build_hashed_contacts,
    fresh_access_token,
    get_connection,
)
from apps.api.services.crm.base import ClosedWonDeal
from apps.api.services.identity_classification import is_emailable_identity
from apps.api.services.pii_crypto import decrypt_pii, email_hash, encrypt_pii, normalize_email

logger = structlog.get_logger()

SEED_SEGMENT_ID = "closed_won_seed"
LOOKALIKE_PREFIX = "closed_won_lookalike:"
OAUTH_CRM_PROVIDERS = ("hubspot", "pipedrive", "salesforce")
NEEDS_RECONNECT_ERROR = "needs_reconnect: reconnect to grant deals access"

CSV_MAX_ROWS = 10_000
CSV_DEAL_ID = "csv"

# E7 allow-lists — validated BEFORE any segment_id string is built.
META_RATIOS = ("0.01", "0.02", "0.03", "0.04", "0.05", "0.06", "0.07", "0.08", "0.09", "0.10")
GOOGLE_EXPANSIONS = ("NARROW", "BALANCED", "BROAD")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Suppression scopes that block ad-audience egress (plan step 7a).
SEED_BLOCKING_SCOPES = ("do_not_sell", "all", "erased")


class LookalikeSpecError(ValueError):
    """Country/ratio/expansion outside the fixed allow-list (-> 422)."""


class SeedNotReadyError(RuntimeError):
    """No seed audience has been pushed yet for this connection (-> 409)."""


# ── ingest ───────────────────────────────────────────────


@dataclass
class IngestOutcome:
    upserted: int = 0
    skipped_erased: int = 0
    skipped_invalid: int = 0


def _clean_country(raw: str | None) -> str | None:
    value = (raw or "").strip().upper()
    return value if _COUNTRY_RE.match(value) else None


async def _erased_bidx(db: AsyncSession, bidx_list: list[str]) -> set[str]:
    if not bidx_list:
        return set()
    rows = await db.execute(
        select(SuppressionEntry.email_hash).where(
            SuppressionEntry.email_hash.in_(bidx_list), SuppressionEntry.scope == "erased"
        )
    )
    return set(rows.scalars().all())


async def ingest_deals(
    db: AsyncSession,
    site_id: str,
    deals: list[ClosedWonDeal],
    *,
    source: str,
    connection_id: _uuid.UUID | None = None,
) -> IngestOutcome:
    """Idempotent upsert on (site_id, external_deal_id, email_bidx). Commits.

    Plaintext email is hashed + encrypted here and then dropped. Rows whose
    blind index carries an ``erased`` tombstone are skipped (N5).
    """
    out = IngestOutcome()
    prepared: list[tuple[str, ClosedWonDeal, str]] = []
    for deal in deals:
        email = normalize_email(deal.email)
        if not email or not _EMAIL_RE.match(email) or not deal.external_deal_id:
            out.skipped_invalid += 1
            continue
        prepared.append((email_hash(email), deal, email))

    erased = await _erased_bidx(db, list({b for b, _, _ in prepared}))
    for bidx, deal, email in prepared:
        if bidx in erased:
            out.skipped_erased += 1
            continue
        stmt = (
            pg_insert(CrmClosedWonContact)
            .values(
                id=_uuid.uuid4(),
                site_id=site_id,
                connection_id=connection_id,
                external_deal_id=str(deal.external_deal_id)[:255],
                email_bidx=bidx,
                email_ciphertext=encrypt_pii(email),
                company_domain=(deal.company_domain or "").strip().lower()[:253] or None,
                country=_clean_country(deal.country),
                closed_at=deal.closed_at,
                source=source,
            )
            .on_conflict_do_update(
                constraint="uq_crm_closed_won_deal_email",
                set_={
                    "closed_at": deal.closed_at,
                    "company_domain": (deal.company_domain or "").strip().lower()[:253] or None,
                    "country": _clean_country(deal.country),
                    "updated_at": func.now(),
                },
            )
        )
        await db.execute(stmt)
        out.upserted += 1
    await db.commit()
    logger.info(
        "closed_won_ingested",
        site_id=site_id,
        source=source,
        upserted=out.upserted,
        skipped_erased=out.skipped_erased,
        skipped_invalid=out.skipped_invalid,
    )
    return out


def parse_closed_won_csv(content: str) -> list[ClosedWonDeal]:
    """CSV with a required ``email`` column, optional ``country``/``company_domain``.

    Raises ValueError for a missing email column or more than CSV_MAX_ROWS rows.
    """
    reader = csv.DictReader(io.StringIO(content))
    headers = {h.strip().lower(): h for h in (reader.fieldnames or [])}
    if "email" not in headers:
        raise ValueError("CSV must have an 'email' column")
    deals: list[ClosedWonDeal] = []
    for i, row in enumerate(reader):
        if i >= CSV_MAX_ROWS:
            raise ValueError(f"CSV has more than {CSV_MAX_ROWS} rows")

        def col(name: str) -> str:
            key = headers.get(name)
            return (row.get(key) or "").strip() if key else ""

        deals.append(
            ClosedWonDeal(
                external_deal_id=CSV_DEAL_ID,
                email=col("email"),
                country=col("country"),
                company_domain=col("company_domain"),
            )
        )
    return deals


# ── poll (APScheduler) ───────────────────────────────────


async def _poll_since(db: AsyncSession, connection_id) -> datetime | None:
    """Re-read from the last ingest minus a 1-day overlap (upsert is idempotent)."""
    last = await db.scalar(
        select(func.max(CrmClosedWonContact.updated_at)).where(
            CrmClosedWonContact.connection_id == connection_id
        )
    )
    if last is None:
        return None
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return last - timedelta(days=1)


async def poll_connection(db: AsyncSession, conn: CrmConnection) -> dict:
    from apps.api.services.crm import get_crm_connector
    from apps.api.services.crm_push import fresh_access_token as crm_fresh_token

    connector = get_crm_connector(conn.provider)
    token = await crm_fresh_token(db, conn)
    since = await _poll_since(db, conn.id)
    try:
        fetched = await connector.fetch_closed_won(
            access_token=token,
            instance_url=conn.external_account_id or "",
            scopes=list(conn.scopes or []),
            since=since,
        )
    except NotImplementedError:
        return {"skipped": "unsupported"}
    except Exception as exc:  # noqa: BLE001 — persist sanitized, PII-free error
        from apps.api.services.crm.base import sanitize_error as crm_sanitize

        conn.last_error = crm_sanitize(exc, "Closed-won read failed")[:500]
        await db.commit()
        logger.warning("closed_won_poll_failed", provider=conn.provider, site_id=conn.site_id)
        return {"error": conn.last_error}
    if fetched.needs_reconnect:
        conn.last_error = NEEDS_RECONNECT_ERROR
        await db.commit()
        return {"needs_reconnect": True}
    if conn.last_error == NEEDS_RECONNECT_ERROR:
        conn.last_error = None
    outcome = await ingest_deals(
        db, conn.site_id, fetched.deals, source="crm", connection_id=conn.id
    )
    return {"upserted": outcome.upserted, "skipped_erased": outcome.skipped_erased}


async def poll_closed_won_once(db: AsyncSession) -> dict:
    """One poll over every connected OAuth CRM. Flag-gated; never raises per row."""
    if not settings.closed_won_lookalikes_enabled:
        return {"skipped": "flag_off"}
    conns = (
        await db.execute(
            select(CrmConnection).where(
                CrmConnection.provider.in_(OAUTH_CRM_PROVIDERS),
                CrmConnection.status == "connected",
            )
        )
    ).scalars().all()
    polled = 0
    for conn in conns:
        try:
            await poll_connection(db, conn)
            polled += 1
        except Exception:  # noqa: BLE001 — one bad connection never stops the sweep
            await db.rollback()
            logger.exception("closed_won_poll_connection_crashed", provider=conn.provider)
    logger.info("closed_won_poll_done", connections=polled)
    return {"connections": polled}


# ── seed build ───────────────────────────────────────────


@dataclass
class SeedRow:
    email: str
    country: str | None
    matched: bool


@dataclass
class SeedBuild:
    rows: list[SeedRow] = field(default_factory=list)
    total: int = 0
    matched: int = 0
    excluded: int = 0


async def _company_excluded_domains(db: AsyncSession, site_id: str, domains: set[str]) -> set[str]:
    """Sibling company-exclusion (domain-keyed, every reason except ``customer``).

    Import-guarded: absent module = no-op. Present but erroring = fail closed
    (every domain excluded).
    """
    if not domains:
        return set()
    try:
        from apps.api.services.company_exclusion import (  # type: ignore
            load_exclusions,
            match_excluded,
        )
    except ImportError:
        return set()
    try:
        exclusions = await load_exclusions(db, site_id)
        excluded: set[str] = set()
        for domain in domains:
            hit = match_excluded(exclusions, domain=domain)
            reason = getattr(hit, "reason", hit) if hit else None
            if hit and reason != "customer":
                excluded.add(domain)
        return excluded
    except Exception:  # noqa: BLE001 — fail closed
        logger.warning("closed_won_company_exclusion_failed", site_id=site_id)
        return set(domains)


async def build_seed(db: AsyncSession, site_id: str, *, google: bool = False) -> SeedBuild:
    """Exclusion-filtered seed rows for one site. Plaintext stays in-process."""
    contacts = (
        await db.execute(
            select(CrmClosedWonContact).where(CrmClosedWonContact.site_id == site_id)
        )
    ).scalars().all()
    build = SeedBuild()
    if not contacts:
        return build
    bidx_list = list({c.email_bidx for c in contacts})
    build.total = len(bidx_list)

    # N6: site-scoped match only; bidx is cross-tenant-equal.
    matches = (
        await db.execute(
            select(IdentifiedVisitor, Visitor.do_not_resolve, Visitor.is_abuse_flagged)
            .outerjoin(
                Visitor,
                (Visitor.site_id == IdentifiedVisitor.site_id)
                & (Visitor.visitor_id == IdentifiedVisitor.visitor_id),
            )
            .where(
                IdentifiedVisitor.site_id == site_id,
                IdentifiedVisitor.email_bidx.in_(bidx_list),
            )
        )
    ).all()
    by_bidx: dict[str, list] = {}
    for iv, dnr, v_abuse in matches:
        by_bidx.setdefault(iv.email_bidx, []).append((iv, bool(dnr), bool(v_abuse)))

    suppressed = set(
        (
            await db.execute(
                select(SuppressionEntry.email_hash).where(
                    SuppressionEntry.email_hash.in_(bidx_list),
                    SuppressionEntry.scope.in_(SEED_BLOCKING_SCOPES),
                )
            )
        ).scalars().all()
    )
    domains = {c.company_domain for c in contacts if c.company_domain}
    excluded_domains = await _company_excluded_domains(db, site_id, domains)

    seen: set[str] = set()
    for c in contacts:
        if c.email_bidx in seen:
            continue
        seen.add(c.email_bidx)
        visitors = by_bidx.get(c.email_bidx, [])
        blocked = c.email_bidx in suppressed or (
            c.company_domain is not None and c.company_domain in excluded_domains
        )
        for iv, dnr, v_abuse in visitors:
            if (
                iv.do_not_email
                or dnr
                or iv.source_agent_visit_id is not None
                or iv.is_abuse_flagged
                or v_abuse
                or not is_emailable_identity(
                    iv.resolution_provider, iv.source_agent_visit_id, iv.is_abuse_flagged
                )
            ):
                blocked = True
                break
        if blocked:
            build.excluded += 1
            continue
        email = decrypt_pii(c.email_ciphertext) or ""
        if not email or "@" not in email:
            build.excluded += 1
            continue
        country = c.country or next(
            (iv.country for iv, _, _ in visitors if iv.country), None
        )
        if google:
            cc = (country or "").strip().upper()
            if not cc or cc in EEA_COUNTRY_CODES:  # UD3: fail closed
                build.excluded += 1
                continue
        matched = bool(visitors)
        build.matched += int(matched)
        build.rows.append(SeedRow(email=email, country=country, matched=matched))
    return build


async def seed_summary(db: AsyncSession, site_id: str) -> dict:
    build = await build_seed(db, site_id)
    reconnect = await db.scalar(
        select(func.count())
        .select_from(CrmConnection)
        .where(CrmConnection.site_id == site_id, CrmConnection.last_error == NEEDS_RECONNECT_ERROR)
    )
    return {
        "total": build.total,
        "matched": build.matched,
        "eligible": len(build.rows),
        "excluded": build.excluded,
        "needs_reconnect": bool(reconnect),
    }


# ── seed push ────────────────────────────────────────────


@dataclass
class SeedPushOutcome:
    found: bool
    pushed: int = 0
    matched: int = 0
    excluded: int = 0
    platform_audience_id: str = ""
    warning: str = ""
    errors: list[str] = field(default_factory=list)


async def _get_link(db: AsyncSession, connection_id, segment_id: str, *, lock: bool = False):
    q = select(AdAudienceLink).where(
        AdAudienceLink.connection_id == connection_id, AdAudienceLink.segment_id == segment_id
    )
    if lock:
        q = q.with_for_update()
    return (await db.execute(q)).scalar_one_or_none()


async def push_seed(db: AsyncSession, site_id: str, provider: str) -> SeedPushOutcome:
    """Push the closed-won seed. Caller has reserved the per-site push slot.

    Deliberately NOT ``push_segment_to_ads`` (needs a Segment + members).
    """
    from apps.api.services.ads.google import google_seed_warning
    from apps.api.services.ads.meta import meta_seed_warning

    conn = await get_connection(db, site_id, provider)
    if conn is None:
        return SeedPushOutcome(found=False)
    build = await build_seed(db, site_id, google=(provider == "google"))
    contacts = build_hashed_contacts(
        [{"email": r.email, "country": r.country or ""} for r in build.rows]
    )
    link = await _get_link(db, conn.id, SEED_SEGMENT_ID)
    provider_impl = get_provider(provider)
    await fresh_access_token(db, conn)
    try:
        result = await provider_impl.create_or_update_audience(conn, link, contacts)
    except NotImplementedError:
        raise
    except MetaAudienceTermsError as exc:
        conn.last_error = str(exc)[:500]
        await db.commit()
        return SeedPushOutcome(found=True, errors=[conn.last_error])
    except Exception as exc:  # noqa: BLE001 — sanitized, PII-free
        conn.last_error = sanitize_error(exc, "Seed push failed")[:500]
        await db.commit()
        logger.warning("closed_won_seed_push_failed", site_id=site_id, provider=provider)
        return SeedPushOutcome(found=True, errors=[conn.last_error])

    now = datetime.now(timezone.utc)
    await db.execute(
        pg_insert(AdAudienceLink)
        .values(
            id=_uuid.uuid4(),
            connection_id=conn.id,
            segment_id=SEED_SEGMENT_ID,
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
    await db.commit()
    warning = meta_seed_warning(len(contacts)) if provider == "meta" else (
        google_seed_warning(len(contacts)) if provider == "google" else ""
    )
    logger.info(
        "closed_won_seed_pushed",
        site_id=site_id,
        provider=provider,
        pushed=result.pushed,
        excluded=build.excluded,
    )
    return SeedPushOutcome(
        found=True,
        pushed=result.pushed,
        matched=build.matched,
        excluded=build.excluded,
        platform_audience_id=result.platform_audience_id,
        warning=warning,
        errors=result.errors,
    )


# ── lookalike (contract E7) ──────────────────────────────


def validate_spec(provider: str, country: str, ratio: str | None, expansion: str | None) -> tuple[LookalikeSpec, str]:
    """Allow-list validation, THEN build the sentinel segment_id. Raises LookalikeSpecError."""
    cc = (country or "").strip().upper()
    if not _COUNTRY_RE.match(cc):
        raise LookalikeSpecError("country must be a 2-letter ISO code")
    if provider == "meta":
        r = (ratio or "").strip()
        if r not in META_RATIOS:
            raise LookalikeSpecError(f"ratio must be one of {', '.join(META_RATIOS)}")
        return LookalikeSpec(country=cc, ratio=float(r)), f"{LOOKALIKE_PREFIX}{cc}:{r}"
    if provider == "google":
        e = (expansion or "").strip().upper()
        if e not in GOOGLE_EXPANSIONS:
            raise LookalikeSpecError(f"expansion must be one of {', '.join(GOOGLE_EXPANSIONS)}")
        return LookalikeSpec(country=cc, expansion=e), f"{LOOKALIKE_PREFIX}{cc}:{e}"
    raise LookalikeSpecError(f"{provider} does not support lookalikes")


@dataclass
class LookalikeOutcome:
    found: bool
    audience_id: str = ""
    status: str = ""
    reused: bool = False
    previous_lookalike_id: str | None = None
    warning: str = ""
    error: str = ""


async def create_or_reuse_lookalike(
    db: AsyncSession,
    site_id: str,
    provider: str,
    spec: LookalikeSpec,
    segment_key: str,
) -> LookalikeOutcome:
    """Same spec -> stored id, zero adapter calls. Different -> new provider
    lookalike, same row updated, ``previous_lookalike_id`` returned. One
    lookalike row per connection, serialized by FOR UPDATE on the seed link.
    """
    conn = await get_connection(db, site_id, provider)
    if conn is None:
        return LookalikeOutcome(found=False)
    seed = await _get_link(db, conn.id, SEED_SEGMENT_ID, lock=True)
    if seed is None:
        await db.rollback()
        raise SeedNotReadyError("Push the closed-won seed audience first.")

    existing = (
        await db.execute(
            select(AdAudienceLink).where(
                AdAudienceLink.connection_id == conn.id,
                AdAudienceLink.segment_id.like(f"{LOOKALIKE_PREFIX}%"),
            )
        )
    ).scalars().first()
    if existing is not None and existing.segment_id == segment_key:
        await db.commit()
        return LookalikeOutcome(
            found=True, audience_id=existing.platform_audience_id, status="exists", reused=True
        )

    result: LookalikeResult = await get_provider(provider).create_lookalike(
        conn, seed.platform_audience_id, spec
    )
    if result.status == "error" or not result.audience_id:
        await db.commit()
        return LookalikeOutcome(
            found=True,
            status=result.status,
            audience_id=existing.platform_audience_id if existing else "",
            warning=result.warning,
            error=result.error,
        )

    now = datetime.now(timezone.utc)
    previous = None
    if existing is not None:
        previous = existing.platform_audience_id
        existing.segment_id = segment_key
        existing.platform_audience_id = result.audience_id
        existing.last_pushed_at = now
    else:
        db.add(
            AdAudienceLink(
                id=_uuid.uuid4(),
                connection_id=conn.id,
                segment_id=segment_key,
                platform_audience_id=result.audience_id,
                last_pushed_at=now,
            )
        )
    await db.commit()
    logger.info("closed_won_lookalike_saved", site_id=site_id, provider=provider, replaced=bool(previous))
    seed_size = seed.last_push_count or 0
    from apps.api.services.ads.google import google_seed_warning
    from apps.api.services.ads.meta import meta_seed_warning

    size_warning = meta_seed_warning(seed_size) if provider == "meta" else google_seed_warning(seed_size)
    return LookalikeOutcome(
        found=True,
        audience_id=result.audience_id,
        status=result.status,
        previous_lookalike_id=previous,
        warning=" ".join(w for w in (size_warning, result.warning) if w),
    )
