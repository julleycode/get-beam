import asyncio
import re
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.database import get_db
from apps.api.models.site import Site
from apps.api.models.site_tombstone import SiteTombstone
from apps.api.models.user import User
from apps.api.dependencies import get_current_user, verify_site_access
from apps.api.schemas.sites import (
    PlatformDetectRequest,
    PlatformDetectResponse,
    PixelVerifyResponse,
    ShopifyConnectRequest,
    SiteCreate,
    SiteOut,
    SitePixelSnippet,
    SiteUpdate,
)
from apps.api.schemas.site_analysis import SiteAnalysisConfirm, SiteAnalysisOut
from apps.api.services.billing import get_effective_plan, get_site_limit
from apps.api.services.site_analysis import (
    STATUS_PENDING,
    STATUS_READY,
    _analysis_inflight,
    derive_message,
    derive_status,
    run_site_analysis,
    sanitize_profile,
)
from apps.api.services.usage_limits import check_site_analysis_budget
from apps.api.services.identity_coop import record_consent_acceptance
from apps.api.services.identity_providers.base import _url_to_host
from apps.api.services.leadpipe_pixels import ensure_pixel_for_domain
from apps.api.services.platform_detector import detect_platform
from apps.api.services.pixel_verifier import verify_pixel
from apps.api.services.wordpress_plugin_generator import generate_plugin_zip

router = APIRouter()
logger = structlog.get_logger()


def _generate_site_id() -> str:
    return f"site_{uuid.uuid4().hex[:12]}"


# Keep strong references to fired analysis tasks so they aren't GC'd mid-run.
_analysis_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]


def _fire_site_analysis(site: Site) -> None:
    """The ONLY place an analysis task is created — never a bare
    asyncio.create_task at a call site.

    It is the sole registrar of the done-callback that discards from BOTH sets. A
    bare create_task breaks three things at once: the site_id is never discarded
    (so every later POST returns already_running forever in-process and the re-run
    path is permanently dead), the task is absent from _analysis_tasks (so a test
    that gathers over that set awaits nothing), and the strong reference is
    dropped (so the task can be garbage-collected mid-run).

    The discards live in the done-callback and NOT in a `finally` inside the
    coroutine: the callback fires on every outcome including cancellation, a
    `finally` never runs if the task is cancelled before it starts.
    """
    site_id = site.site_id
    _analysis_inflight.add(site_id)
    task = asyncio.create_task(run_site_analysis(site_id))
    _analysis_tasks.add(task)

    def _done(t: "asyncio.Task", _sid: str = site_id) -> None:
        _analysis_tasks.discard(t)
        _analysis_inflight.discard(_sid)

    task.add_done_callback(_done)


# ──────────────────────────── Existing CRUD ────────────────────────────


def _normalize_url(raw: str) -> str:
    """Normalize URL for dedup: lowercase, strip trailing /, strip www."""
    url = raw.strip().rstrip("/").lower()
    for prefix in ("https://www.", "http://www."):
        if url.startswith(prefix):
            url = url.replace(prefix, prefix.replace("www.", ""), 1)
    return url


@router.post("/", response_model=SiteOut)
async def create_site(
    body: SiteCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SiteOut:
    normalized_url = _normalize_url(body.url)

    # Check if ANY user already created a site for this URL
    result = await db.execute(
        select(Site).where(Site.url == normalized_url).order_by(Site.created_at)
    )
    existing = result.scalars().first()
    if not existing:
        # Also check with www. variant and trailing slash variants
        variants = {body.url.strip().rstrip("/").lower(), normalized_url}
        result = await db.execute(
            select(Site).where(Site.url.in_(variants)).order_by(Site.created_at)
        )
        existing = result.scalars().first()

    if existing:
        if existing.user_id != user.id:
            # Another user already owns this URL — refuse to reassign
            raise HTTPException(
                status_code=409,
                detail="This site URL is already registered to another account.",
            )
        # Same user already has this site — return it as-is (dedup)
        return SiteOut.model_validate(existing)

    # Per-plan website limit. Checked only on the true-create path: the 409 and
    # dedup-200 branches above short-circuit first, so re-POSTing a site you
    # already own always works even at (or over) the limit.
    effective_plan = get_effective_plan(user.plan, user.current_period_end)
    limit = get_site_limit(effective_plan)
    if limit is not None:
        count = (
            await db.execute(
                select(func.count()).select_from(Site).where(Site.user_id == user.id)
            )
        ).scalar_one()
        # `>=` (not `>`) so a grandfathered over-limit user keeps every existing
        # site but cannot add another.
        if count >= limit:
            logger.info(
                "site_limit_blocked",
                user_id=str(user.id),
                plan=effective_plan,
                limit=limit,
                current_count=count,
            )
            raise HTTPException(
                status_code=402,
                detail={
                    "code": "site_limit_reached",
                    "message": (
                        f"Your {effective_plan.capitalize()} plan includes "
                        f"{limit} website{'s' if limit != 1 else ''}. "
                        "Upgrade to add more."
                    ),
                    "plan": effective_plan,
                    "limit": limit,
                    "current_count": count,
                    "upgrade_url": "/pricing",
                },
            )

    # site_id reuse: if THIS user previously deleted a site for THIS normalized
    # url within the reclaim window, re-issue that same site_id so the tracking
    # snippet still installed on their page resumes working with no edit.
    #
    # SECURITY: the owner filter is a SQL WHERE predicate, never a post-fetch
    # Python check — a missing user_id predicate would let one user's re-create
    # silently adopt another user's old id. Mirrors verify_site_access.
    #
    # `variants` (built in the dedup block above and always defined by the time
    # we get here) carries the www/trailing-slash normalization, so the
    # tombstone match uses exactly the same url shapes dedup does.
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.site_id_reclaim_window_days
    )
    tombstone_result = await db.execute(
        select(SiteTombstone)
        .where(
            SiteTombstone.user_id == user.id,
            SiteTombstone.normalized_url.in_(variants),
            SiteTombstone.deleted_at >= cutoff,
        )
        .order_by(SiteTombstone.deleted_at.desc())
        .limit(1)
    )
    tombstone = tombstone_result.scalars().first()

    site = Site(
        site_id=tombstone.site_id if tombstone else _generate_site_id(),
        user_id=user.id,
        name=body.name,
        url=normalized_url,
        description=body.description,
        category=body.category,
    )
    reused_tombstone = tombstone is not None
    try:
        # Savepoint so a unique violation on sites.site_id (concurrent re-create
        # racing for the same reused id) is recoverable instead of poisoning the
        # session.
        async with db.begin_nested():
            db.add(site)
            if tombstone is not None:
                # Consume the tombstone in the same transaction — an id is
                # reclaimed at most once.
                await db.delete(tombstone)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.info("site_id_reuse_collision", attempted_site_id=site.site_id)
        # Retry exactly ONCE with a fresh random id and no tombstone
        # consumption. A second failure propagates (500) — never loop.
        reused_tombstone = False
        site = Site(
            site_id=_generate_site_id(),
            user_id=user.id,
            name=body.name,
            url=normalized_url,
            description=body.description,
            category=body.category,
        )
        db.add(site)
        await db.commit()

    await db.refresh(site)
    logger.info(
        "site_created", site_id=site.site_id, reused_tombstone=reused_tombstone
    )
    if settings.site_analysis_enabled:
        # Fire-and-forget the onboarding analysis. create_site does NO budget work
        # at all — the task owns the single check + increment, so auto-start and a
        # manual re-run consume the counter identically. The dedup-return and 409
        # branches above return before reaching this point and never fire it.
        site.site_profile_status = STATUS_PENDING
        site.site_profile_started_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.commit()
        await db.refresh(site)
        _fire_site_analysis(site)
    return SiteOut.model_validate(site)


@router.get("/", response_model=list[SiteOut])
async def list_sites(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SiteOut]:
    result = await db.execute(select(Site).where(Site.user_id == user.id))
    sites = result.scalars().all()
    return [SiteOut.model_validate(s) for s in sites]


@router.get("/{site_id}", response_model=SiteOut)
async def get_site(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SiteOut:
    site = await verify_site_access(db, site_id, user)
    return SiteOut.model_validate(site)


@router.delete("/{site_id}", status_code=204)
async def delete_site(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Permanently delete a site and ALL of its data.

    DESTRUCTIVE + IRREVERSIBLE. Cascades across every site-scoped table before
    removing the site row itself. Owner-scoped (404 for non-owners so we never
    leak which site_ids exist). There is no soft-delete / undo.

    Ordering matters: grandchildren keyed only by a parent id (e.g.
    campaign_touchpoints → campaigns.id) are deleted BEFORE their parent so no
    orphan/FK issue can occur. `blog_posts.site_id` is a real FK with
    ondelete="SET NULL", so those rows are nulled by the DB when the site row
    goes — we never hard-delete blog posts. `events` live in PostgreSQL
    (ClickHouse is dormant at MVP scale), so the raw-event delete below is the
    complete purge. User-owned tables (social_accounts, drafts, messages, etc.
    keyed by user_id) belong to the account, not the site, and are left intact.

    The whole cascade runs inside one transaction: any mid-way failure rolls the
    entire delete back, so a site is never left half-deleted.
    """
    from sqlalchemy import text as sql_text

    site = await verify_site_access(db, site_id, user)

    # Grandchildren first (no site_id of their own; keyed via a parent id), then
    # every table with a direct site_id / source_site_id column, then the site
    # row itself. Site row is deleted last so blog_posts FK SET NULL fires cleanly.
    deleted: dict[str, int] = {}
    try:
        # Grandchild: campaign_touchpoints has no site_id — scope via its campaigns.
        r = await db.execute(
            sql_text(
                "DELETE FROM campaign_touchpoints WHERE campaign_id IN "
                "(SELECT id FROM campaigns WHERE site_id = :sid)"
            ),
            {"sid": site_id},
        )
        deleted["campaign_touchpoints"] = r.rowcount

        # Direct site_id columns (String site_id).
        for table in (
            "events",
            "conversions",
            "campaign_clicks",
            "conversion_goals",
            "resolution_logs",
            "identified_visitors",
            "enrichment_profiles",
            "visitor_emails",
            "segment_members",
            "visitors",
            "segments",
            "campaigns",
            "companies",
            "known_contacts",
            "crm_connections",
            "engagement_attributions",
            "api_usage_logs",
            # Added to close the site_id-reuse data-resurrection gap: these
            # site-scoped tables hold PII (identity_signals, job_change_events)
            # or secrets (ad_connections OAuth tokens) and were previously left
            # behind on delete, so a re-created site reusing the same site_id
            # inherited the old site's rows.
            "identity_signals",
            "job_change_events",
            "agent_visits",
            "agent_fetch_events",
            "agent_handoff_links",
            "request_logs",
            "ad_connections",
            # H1: close the site_id-reuse gap for spendable co-op credit.
            # identity_contribution_consent_acceptances is DELIBERATELY retained
            # (append-only legal audit trail, inert alone) — plan decision H1-D.
            "identity_contribution_events",
            "identity_credit_ledger",
        ):
            r = await db.execute(
                sql_text(f"DELETE FROM {table} WHERE site_id = :sid"),
                {"sid": site_id},
            )
            deleted[table] = r.rowcount

        # beam_identity_graph references the site via source_site_id.
        r = await db.execute(
            sql_text("DELETE FROM beam_identity_graph WHERE source_site_id = :sid"),
            {"sid": site_id},
        )
        deleted["beam_identity_graph"] = r.rowcount

        # Tombstone the site's identity so a later re-create for the same
        # normalized url by the same owner can reuse this site_id and keep the
        # already-installed pixel working. Rides the SAME transaction as the
        # cascade below: if any part of the delete fails and rolls back, the
        # tombstone rolls back too, so a tombstone can never exist for a site
        # that still exists. Id/url/owner/timestamp only — no site data.
        db.add(
            SiteTombstone(
                site_id=site.site_id,
                normalized_url=site.url,
                user_id=site.user_id,
            )
        )

        # The site row last (blog_posts.site_id FK -> SET NULL fires here).
        await db.delete(site)

        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("site_delete_failed", site_id=site_id, error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to delete site")

    logger.info("site_deleted", site_id=site_id, deleted=deleted, tombstoned=True)
    return Response(status_code=204)


@router.patch("/{site_id}", response_model=SiteOut)
async def update_site(
    site_id: str,
    body: SiteUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SiteOut:
    """Partial site update. Owner-scoped; only set fields are applied."""
    site = await verify_site_access(db, site_id, user)

    if body.description is not None:
        site.description = body.description
    if body.category is not None:
        site.category = body.category
    if body.auto_identify_enabled is not None:
        site.auto_identify_enabled = body.auto_identify_enabled
    if body.hot_alert_enabled is not None:
        site.hot_alert_enabled = body.hot_alert_enabled
    if body.tracking_enabled is not None:
        site.tracking_enabled = body.tracking_enabled
        # Any EXPLICIT owner write clears the auto-pause stamp, in both
        # directions. Re-enabling obviously ends the auto-pause; pausing by hand
        # CONVERTS it into a manual pause, so the next login doesn't
        # surprise-resume a site the owner deliberately switched off.
        site.auto_paused_at = None
    if body.internal_damping_enabled is not None:
        site.internal_damping_enabled = body.internal_damping_enabled
    if body.consent_mode is not None:
        site.consent_mode = body.consent_mode
    # Validated in SiteUpdate (http(s) only, no HTML-injection or
    # link-decorator-terminator characters, <=500 chars) — that validator is the
    # security contract, since nothing downstream escapes this value.
    if body.booking_url is not None:
        site.booking_url = body.booking_url

    # Identity co-op opt-in (AC-10). Turning it ON requires accepting the exact
    # currently-pinned terms, and the acceptance row is written in the SAME
    # transaction as the flag flip below — so "flag ON" can never exist without a
    # matching audit row. Turning it OFF is unconditional: opting out of a data
    # co-op must never be gated on anything.
    if body.contribution_enabled is not None:
        if body.contribution_enabled:
            # M2: opting IN is unreachable while the deployment flag is OFF.
            # 422 (not 404) matches the digest guard below; 404 is tenancy-only.
            if not settings.identity_coop_enabled:
                raise HTTPException(
                    status_code=422,
                    detail="identity co-op is not enabled on this deployment",
                )
            tv = body.terms_version
            # Constant-compare against the pinned digest (E4). Phase 3's
            # coop_terms.py replaces this with real version history.
            if (
                not tv
                or len(tv) != 64
                or not all(c in "0123456789abcdef" for c in tv)
                or tv != settings.coop_terms_version
            ):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "contribution_enabled=true requires terms_version to equal "
                        "the current co-op terms version"
                    ),
                )
            await record_consent_acceptance(
                db, site_id=site.site_id, terms_version=tv, user_id=user.id
            )
        site.contribution_enabled = body.contribution_enabled

    # Campaign-benchmark opt-in (marketing-claims-gap Phase 3, D3). Structurally
    # SEPARATE from the co-op block above: no terms_version, no acceptance row,
    # and it neither reads nor writes contribution_enabled. The pooled benchmark
    # data is zero-PII and k-anonymous (>=5 sites per row), so the proportionate
    # consent artifact is this structlog audit line, not an acceptance table.
    # Unconditional in both directions — opting out is never gated.
    if body.benchmark_contribution_enabled is not None:
        site.benchmark_contribution_enabled = body.benchmark_contribution_enabled
        logger.info(
            "benchmark_contribution_toggled",
            site_id=site.site_id,
            user_id=str(user.id),
            enabled=body.benchmark_contribution_enabled,
        )

    await db.commit()
    await db.refresh(site)
    return SiteOut.model_validate(site)


@router.get("/{site_id}/pixel", response_model=SitePixelSnippet)
async def get_pixel_snippet(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SitePixelSnippet:
    site = await verify_site_access(db, site_id, user)

    # Identity-vendor stacking attrs for tracker.js (data-stack + data-stack-<vendor>).
    # Tracker intentionally does NOT parse legacy data-identity-providers JSON.
    # Attr key must match vendorUrls keys in apps/pixel/src/tracker.js.
    stack_vendors: list[tuple[str, str]] = []

    # Leadpipe: each site gets its OWN pixel, because a Leadpipe pixel is bound
    # 1-1 to a domain (the API 409s on duplicates). Provisioned lazily right
    # here — the one point that knows the customer is about to install — rather
    # than at create_site, which would burn a pixel slot for every site created
    # and abandoned. Idempotent: the id is stored, and the API's own 409 covers
    # the race where two snippet fetches land at once.
    leadpipe_pixel_id = site.leadpipe_pixel_id
    if not leadpipe_pixel_id:
        leadpipe_pixel_id = await ensure_pixel_for_domain(_url_to_host(site.url))
        if leadpipe_pixel_id:
            site.leadpipe_pixel_id = leadpipe_pixel_id
            await db.commit()
    if leadpipe_pixel_id:
        stack_vendors.append(("leadpipe", leadpipe_pixel_id))

    if settings.capturify_pixel_id:
        stack_vendors.append(("capturify", settings.capturify_pixel_id))

    if settings.fullcontact_pixel_id:
        stack_vendors.append(("fullcontact", settings.fullcontact_pixel_id))

    if settings.customers_ai_pixel_id:
        # tracker.js vendor key uses a hyphen
        stack_vendors.append(("customers-ai", settings.customers_ai_pixel_id))

    stack_attr = ""
    if stack_vendors:
        parts = ['data-stack="1"']
        for vendor_key, vendor_id in stack_vendors:
            # Escape quotes in ids; pixel ids are UUIDs / opaque tokens
            safe_id = str(vendor_id).replace('"', "")
            parts.append(f'data-stack-{vendor_key}="{safe_id}"')
        stack_attr = " " + " ".join(parts)

    # Only emit data-consent when consent gating is enabled, so "off" sites keep
    # the exact snippet they had before this feature (zero churn for existing users).
    consent_attr = ""
    consent_mode = getattr(site, "consent_mode", "off") or "off"
    if consent_mode != "off":
        consent_attr = f' data-consent="{consent_mode}"'

    snippet = (
        f'<script src="{settings.api_base_url}/pixel/tracker.js" '
        f'data-site="{site.site_id}" data-api="{settings.api_base_url}"'
        f'{stack_attr}{consent_attr} defer></script>'
    )
    return SitePixelSnippet(site_id=site.site_id, snippet=snippet)


# ──────────────────────── Platform Detection ───────────────────────────


@router.post("/detect-platform", response_model=PlatformDetectResponse)
async def detect_platform_endpoint(
    body: PlatformDetectRequest,
    user: User = Depends(get_current_user),
) -> PlatformDetectResponse:
    """Auto-detect which platform a website is built on."""
    result = await detect_platform(body.url)
    return PlatformDetectResponse(
        platform=result["platform"],
        confidence=result["confidence"],
        has_gtm=result["has_gtm"],
        gtm_id=result["gtm_id"],
    )


# ──────────────────────── Site analysis (onboarding) ────────────────────
#
# All three endpoints: flag check FIRST (inside the body, following the
# routers/onboarding.py _require_flag precedent — a Depends resolves AFTER auth
# and so cannot run first), then verify_site_access (404 for foreign ids, never
# 403), then logic. Accepted consequence, matching repo posture everywhere else:
# an UNAUTHENTICATED probe gets 401 from get_current_user before reaching the flag
# check, so flag-off hides the endpoints from authenticated users but not from an
# unauthenticated 401-vs-404 oracle.


def _require_site_analysis_flag() -> None:
    if not settings.site_analysis_enabled:
        # Dormant: do not reveal the endpoint exists when disabled.
        raise HTTPException(status_code=404, detail="Not Found")


async def _analysis_out(
    site: Site, *, already_running: bool = False, budget: dict | None = None
) -> SiteAnalysisOut:
    """Assemble the response. `message` comes from the ONE derivation helper —
    never re-derived per handler."""
    status = derive_status(site)
    if budget is None:
        budget = await check_site_analysis_budget(site.site_id)
    return SiteAnalysisOut(
        site_id=site.site_id,
        status=status,
        profile=site.site_profile,
        candidate=site.site_profile_candidate,
        analyzed_at=(
            site.site_profile_analyzed_at.isoformat()
            if site.site_profile_analyzed_at
            else None
        ),
        message=derive_message(allowed=bool(budget["allowed"]), status=status),
        already_running=already_running,
        budget={
            "used": budget["used"],
            "limit": budget["limit"],
            "allowed": budget["allowed"],
        },
    )


@router.get("/{site_id}/analysis", response_model=SiteAnalysisOut)
async def get_site_analysis(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SiteAnalysisOut:
    _require_site_analysis_flag()
    site = await verify_site_access(db, site_id, user)
    # budget is one plain Redis GET — no user_api_keys SELECT, so a 4 s poll costs
    # zero extra DB round-trips.
    return await _analysis_out(site)


@router.put("/{site_id}/analysis", response_model=SiteAnalysisOut)
async def confirm_site_analysis(
    site_id: str,
    body: SiteAnalysisConfirm,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SiteAnalysisOut:
    _require_site_analysis_flag()
    site = await verify_site_access(db, site_id, user)

    if not body.promote:
        # DISMISS only: NULL the candidate and touch NOTHING else — not the
        # confirmed profile, not the status, neither timestamp, not description
        # or category. "Keep what I have, throw away this re-run."
        site.site_profile_candidate = None
        await db.commit()
        await db.refresh(site)
        return await _analysis_out(site)

    profile = sanitize_profile(body.profile.model_dump())
    profile["meta"]["user_edited"] = True
    site.site_profile = profile
    site.site_profile_candidate = None

    # Never downgrade an in-flight run: a "pending" row still feeds the stale
    # derivation and the cross-process in-flight check, and overwriting it would
    # erase both.
    if derive_status(site) != STATUS_PENDING:
        site.site_profile_status = STATUS_READY
    # site_profile_analyzed_at is deliberately NOT stamped here — it means "when
    # the analysis run that produced the candidate finished" and has exactly one
    # writer, the task.

    if body.apply_description and profile.get("summary"):
        site.description = profile["summary"][:1000]
    if body.apply_category and profile.get("category"):
        site.category = profile["category"][:100]

    await db.commit()
    await db.refresh(site)
    return await _analysis_out(site)


@router.post("/{site_id}/analysis", response_model=SiteAnalysisOut)
async def rerun_site_analysis(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SiteAnalysisOut:
    _require_site_analysis_flag()
    site = await verify_site_access(db, site_id, user)

    # (a) In-flight guard FIRST. No increment, no started_at re-stamp (which would
    # defeat the stale derivation), no second task.
    if derive_status(site) == STATUS_PENDING or site_id in _analysis_inflight:
        return await _analysis_out(site, already_running=True)

    # (b) CHECK only — the task owns the single increment.
    budget = await check_site_analysis_budget(site_id)
    if not budget["allowed"]:
        # HTTP 200 with allowed=false. Never 4xx, never a partial profile.
        return await _analysis_out(site, budget=budget)

    # (c) site_profile is never touched by a re-run — the new run lands in the
    # candidate slot and only PUT promotes it.
    site.site_profile_status = STATUS_PENDING
    site.site_profile_started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(site)

    _fire_site_analysis(site)
    return await _analysis_out(site, budget=budget)


# ──────────────────────── Pixel Verification ───────────────────────────


@router.post("/{site_id}/verify-pixel", response_model=PixelVerifyResponse)
async def verify_pixel_endpoint(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PixelVerifyResponse:
    """Verify that the tracking pixel is installed on the site."""
    site = await verify_site_access(db, site_id, user)

    verify_result = await verify_pixel(site.url, site_id, db=db)

    if verify_result["verified"] and not site.pixel_verified:
        site.pixel_verified = True
        await db.commit()
    elif not verify_result["verified"] and site.pixel_verified:
        site.pixel_verified = False
        await db.commit()

    return PixelVerifyResponse(
        site_id=site_id,
        status=verify_result["status"],
        verified=verify_result["verified"],
        message=verify_result["message"],
        found_site_id=verify_result.get("found_site_id"),
    )


# ──────────────────────── Detection Preview ───────────────────────────


@router.get("/{site_id}/detection-preview")
async def detection_preview(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Scan the installed pixel and report which detection signals are active."""
    site = await verify_site_access(db, site_id, user)

    from apps.api.services.detection_scanner import scan_detection_signals

    signals = await scan_detection_signals(site.url, site_id)

    from apps.api.models.visitor import Visitor
    from sqlalchemy import func

    total_r = await db.execute(
        select(func.count()).select_from(Visitor).where(Visitor.site_id == site_id)
    )
    total_visitors = total_r.scalar() or 0

    return {
        "site_id": site_id,
        "signals": signals,
        "total_visitors": total_visitors,
    }


@router.get("/{site_id}/browser-breakdown")
async def browser_breakdown(
    site_id: str,
    window_days: int = 30,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Per-browser captured/identified counts + a geo-weighted Safari-coverage
    estimate — surfaces whether ITP/content-blockers are eating Safari traffic."""
    await verify_site_access(db, site_id, user)

    from apps.api.services.browser_breakdown import compute_browser_breakdown

    return await compute_browser_breakdown(
        db, site_id, window_days=max(1, min(window_days, 90))
    )


@router.get("/{site_id}/traffic-fit")
async def traffic_fit(
    site_id: str,
    window_days: int = 30,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """US-coverage fit estimate — "what share of this site's traffic can beam
    actually identify?" Person-level identification is US-only, so a mostly
    non-US site will never resolve; this surfaces that up front."""
    await verify_site_access(db, site_id, user)

    from apps.api.services.traffic_fit import compute_traffic_fit

    return await compute_traffic_fit(
        db, site_id, window_days=max(1, min(window_days, 90))
    )


@router.get("/{site_id}/kpis")
async def site_kpis(
    site_id: str,
    days: int = 30,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Per-site KPI funnel — visitors → identified → high-intent → acted-on,
    plus identify/action rates. The numbers a growth marketer reads to judge ROI."""
    await verify_site_access(db, site_id, user)

    from apps.api.services.kpi import compute_kpis

    return await compute_kpis(db, site_id, days=max(1, min(days, 365)))


@router.get("/{site_id}/timeseries")
async def site_timeseries(
    site_id: str,
    days: int = 30,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Per-day funnel series (visitors → identified → high-intent) for the
    "View as graph" widget. Same window + predicates as /kpis, bucketed by day."""
    await verify_site_access(db, site_id, user)

    from apps.api.services.timeseries import compute_timeseries

    return await compute_timeseries(db, site_id, days=max(1, min(days, 365)))


# ──────────────────────── WordPress Plugin ─────────────────────────────


@router.get("/{site_id}/wordpress-plugin")
async def download_wordpress_plugin(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Download auto-generated WordPress plugin with pre-configured site ID."""
    await verify_site_access(db, site_id, user)

    zip_bytes = generate_plugin_zip(site_id, settings.api_base_url)

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=beam-pixel-{site_id}.zip"
        },
    )


# ──────────────────────── Shopify Integration ──────────────────────────


@router.post("/{site_id}/shopify/connect")
async def shopify_connect(
    site_id: str,
    body: ShopifyConnectRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Start Shopify OAuth flow to install pixel automatically."""
    if not settings.shopify_api_key:
        raise HTTPException(
            status_code=501,
            detail="Shopify integration not configured. Please set SHOPIFY_API_KEY.",
        )

    await verify_site_access(db, site_id, user)

    from apps.api.services.shopify_integration import get_install_url

    install_url = get_install_url(body.shop_domain, site_id)
    return {"install_url": install_url}


_SHOPIFY_SHOP_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]*\.myshopify\.com$")


@router.get("/shopify/callback")
async def shopify_callback(
    request: Request,
    shop: str = Query(...),
    code: str = Query(...),
    state: str = Query(...),  # site_id
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Handle Shopify OAuth callback — install ScriptTag and redirect to dashboard."""
    from apps.api.services.shopify_integration import handle_oauth_callback, verify_hmac

    # Verify the HMAC signature so only Shopify-originated callbacks proceed.
    if not verify_hmac(dict(request.query_params)):
        logger.warning("shopify_callback_bad_hmac", shop=shop)
        raise HTTPException(status_code=400, detail="Invalid HMAC signature")

    # Validate the attacker-controlled `shop` param before any outbound call (SSRF guard).
    if not _SHOPIFY_SHOP_RE.match(shop):
        logger.warning("shopify_callback_bad_shop", shop=shop)
        raise HTTPException(status_code=400, detail="Invalid shop domain")

    site_id = state

    # Confirm the referenced site exists before processing.
    result = await db.execute(
        select(Site).where(Site.site_id == site_id)
    )
    site = result.scalar_one_or_none()
    if not site:
        logger.warning("shopify_callback_unknown_site", shop=shop, site_id=site_id)
        raise HTTPException(status_code=400, detail="Invalid state")

    try:
        await handle_oauth_callback(shop, code, site_id)

        # Mark pixel as verified
        site.pixel_verified = True
        site.detected_platform = "shopify"
        await db.commit()

        logger.info("shopify_connected", shop=shop, site_id=site_id)
    except Exception as e:
        logger.error("shopify_callback_failed", error=str(e), shop=shop)
        return RedirectResponse(
            url=f"{settings.frontend_url}/dashboard?shopify=error&site={site_id}"
        )

    return RedirectResponse(
        url=f"{settings.frontend_url}/dashboard?shopify=connected&site={site_id}"
    )


from pydantic import BaseModel  # noqa: E402


class TrackedLinkRequest(BaseModel):
    url: str
    emails: list[str]


@router.post("/{site_id}/tracked-links")
async def build_tracked_links(
    site_id: str,
    body: TrackedLinkRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Build Beam click-tracking links for a recipient list, to paste into the
    customer's OWN ESP (Klaviyo/Mailchimp). Each recipient's email rides as an
    opaque token (never plaintext); a click resolves them deterministically. Only
    links to the site's own host are built (matches the click redirect's guard)."""
    site = await verify_site_access(db, site_id, user)
    from apps.api.routers.click import build_click_url, safe_dest

    dest = safe_dest(body.url, site.url or "")
    links = [
        {"email": e, "link": build_click_url(settings.api_base_url, site_id, dest, e)}
        for e in body.emails[:5000]
        if e and "@" in e
    ]
    return {"dest": dest, "count": len(links), "links": links}
