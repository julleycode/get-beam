"""Inactivity lifecycle: remind an absent owner, then auto-pause their tracking.

An owner who installs the pixel and stops logging in still costs money — the
30-minute resolution sweep, the enrichment waterfall, geoip and Gemini
segmentation all keep running for nobody, while the identified visitors pile up
unseen. This module is the ladder that stops that:

    ACTIVE  --7d idle, live pixel-------------> REMINDED
    REMINDED --14d idle, reminder >=3d old----> AUTO-PAUSED (tracking_enabled=F)
    AUTO-PAUSED --any authed request----------> ACTIVE (silent resume)

Auto-pause reuses the existing ``Site.tracking_enabled`` ingest gate (which 204s
before any downstream cost) and is distinguished from a MANUAL pause purely by
``Site.auto_paused_at`` — a manually paused site has a NULL stamp and is never
auto-resumed.

The key predicate trick: ``last_reengagement_sent_at`` is never cleared. "A
reminder is outstanding" means ``last_reengagement_sent_at > last_active_at``,
so logging in (which moves ``last_active_at``) invalidates it for free.

Nothing is ever deleted. Pausing only stops collection going forward, and the
pause email says so plainly.

Trigger-agnostic: the scheduler calls ``run_reengagement_sweep()``; it manages
its own session, single-flights via a Postgres advisory lock, and isolates
per-user failures.

tz convention: one ``now`` is taken per run as timezone-aware for the ``users``
columns, and ``now.replace(tzinfo=None)`` is used for the naive ``sites`` /
``visitors`` / ``events`` tables (daily_digest precedent).
"""

from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional

import structlog
from sqlalchemy import exists, func, or_, select, text, update

from apps.api.config import settings
from apps.api.models.database import async_session
from apps.api.models.event import Event
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services.email_sender import EmailSender

logger = structlog.get_logger()

_LOCK_KEY = "beam_reengagement_sweep"

# How stale `last_active_at` must be before a request pays for a write. The
# steady-state cost of the activity touch is therefore one datetime compare on
# an already-loaded row — no query, no Redis.
_TOUCH_INTERVAL = timedelta(hours=1)

# Fabricated addresses minted by the Clerk auto-create path; never deliverable.
_PLACEHOLDER_EMAIL_SUFFIX = "@clerk.user"


# ─────────────────────────── pure predicates ───────────────────────────
# Extracted so the state machine is testable without a database.


def _remind_due(
    now: datetime,
    last_active_at: datetime,
    last_reengagement_sent_at: Optional[datetime],
) -> bool:
    """True when the owner is idle past the remind threshold and no reminder is
    currently outstanding (i.e. they have logged in since the last one)."""
    if now - last_active_at < timedelta(days=settings.reengagement_remind_after_days):
        return False
    if last_reengagement_sent_at is not None and last_reengagement_sent_at > last_active_at:
        return False
    return True


def _pause_due(
    now: datetime,
    last_active_at: datetime,
    last_reengagement_sent_at: Optional[datetime],
) -> bool:
    """True when the owner is idle past the pause threshold AND has an
    outstanding reminder that is old enough to have plausibly been delivered.

    No pause is ever issued without a warning that had time to land.
    """
    if now - last_active_at < timedelta(days=settings.reengagement_pause_after_days):
        return False
    if last_reengagement_sent_at is None or last_reengagement_sent_at <= last_active_at:
        return False
    warn_gap = timedelta(days=settings.reengagement_pause_warning_min_days)
    if last_reengagement_sent_at > now - warn_gap:
        return False
    return True


def _nudge_due(
    now: datetime,
    oldest_site_created_at: datetime,
    install_nudge_sent_at: Optional[datetime],
) -> bool:
    """True when the account has had a site long enough to have installed the
    pixel, and has never been nudged. The nudge is once-only."""
    if install_nudge_sent_at is not None:
        return False
    grace = timedelta(days=settings.reengagement_install_nudge_after_days)
    return now - oldest_site_created_at >= grace


# ──────────────────────────── email builders ────────────────────────────
# Pure: return (subject, html). No unsubscribe link or footer here —
# EmailSender.send appends both.


def _site_list_html(site_names: list[str]) -> str:
    return ", ".join(f"<strong>{escape(n)}</strong>" for n in site_names)


def _reminder_email(
    identified_count: int, new_visitor_count: int, site_names: list[str]
) -> tuple[str, str]:
    """"Beam identified N visitors while you were away" + a quiet auto-pause note."""
    action_url = f"{settings.frontend_url}/dashboard/visitors"
    primary = site_names[0] if site_names else "your site"
    noun = "visitor" if identified_count == 1 else "visitors"
    subject = (
        f"Beam identified {identified_count} {noun} on {primary} while you were away"
    )
    html = (
        f"<p>Hi,</p>"
        f"<p>While you were away, Beam identified "
        f"<strong>{identified_count}</strong> {noun} and saw "
        f"<strong>{new_visitor_count}</strong> new "
        f"{'visitor' if new_visitor_count == 1 else 'visitors'} on "
        f"{_site_list_html(site_names)}.</p>"
        f"<p>They&rsquo;re waiting in your dashboard.</p>"
        f'<p><a href="{escape(action_url, quote=True)}">'
        f"See who visited &rarr;</a></p>"
        f"<p>One housekeeping note: if an account stays idle for "
        f"{settings.reengagement_pause_after_days} days, Beam pauses tracking "
        f"until you come back. Logging in is all it takes to keep it running.</p>"
        f"<p>&mdash; Beam</p>"
    )
    return subject, html


def _paused_email(site_names: list[str]) -> tuple[str, str]:
    """"We paused tracking — log in to resume". States the tradeoff plainly."""
    action_url = f"{settings.frontend_url}/dashboard"
    primary = site_names[0] if site_names else "your site"
    subject = f"We paused tracking on {primary} — log in to resume"
    html = (
        f"<p>Hi,</p>"
        f"<p>Your account has been idle for "
        f"{settings.reengagement_pause_after_days} days, so Beam has paused "
        f"tracking on {_site_list_html(site_names)}.</p>"
        f"<p>What this means: new visits are no longer recorded while tracking "
        f"is paused. Nothing you already have has been deleted &mdash; your "
        f"visitors, identities and history are all exactly where you left them. "
        f"The pixel can stay on your site; you don&rsquo;t need to change "
        f"anything.</p>"
        f"<p><strong>To resume, just log in.</strong> Tracking switches back on "
        f"automatically.</p>"
        f'<p><a href="{escape(action_url, quote=True)}">'
        f"Log in and resume tracking &rarr;</a></p>"
        f"<p>&mdash; Beam</p>"
    )
    return subject, html


def _install_nudge_email(site_name: str) -> tuple[str, str]:
    """"You created a site but the pixel never fired" — one-time nudge."""
    action_url = f"{settings.frontend_url}/dashboard/onboarding"
    subject = f"Finish setting up {site_name} — the Beam pixel isn't live yet"
    html = (
        f"<p>Hi,</p>"
        f"<p>You created <strong>{escape(site_name)}</strong> in Beam, but we "
        f"haven&rsquo;t seen a single event from it yet &mdash; which means the "
        f"tracking snippet isn&rsquo;t on the site.</p>"
        f"<p>It&rsquo;s one line of HTML, pasted before the closing "
        f"<code>&lt;/body&gt;</code> tag. Your snippet (and a copy button) is "
        f"waiting in the dashboard.</p>"
        f'<p><a href="{escape(action_url, quote=True)}">'
        f"Get my snippet &rarr;</a></p>"
        f"<p>Once it&rsquo;s live, Beam starts identifying who&rsquo;s visiting "
        f"within minutes.</p>"
        f"<p>&mdash; Beam</p>"
    )
    return subject, html


# ───────────────────────── activity touch (hot path) ─────────────────────────


async def record_user_activity(user: User) -> None:
    """Refresh ``user.last_active_at`` (at most hourly) and silently resume any
    site this sweep auto-paused.

    Called from ``get_current_user`` on every authed request. Deliberately NOT
    gated on ``reengagement_enabled``: activity data must already be accruing by
    the time the operator flips the flag, otherwise the first sweep would see a
    fleet of users who look idle since the migration.

    Two hard rules:

    * Never touch the request's session. A failed write there would leave the
      caller with a rolled-back session whose attributes are expired, and the
      next ``user.id`` access becomes a sync lazy-load inside an async session
      (MissingGreenlet -> 500 with no CORS header). This uses a throwaway
      session, so that failure mode is impossible by construction.
    * Never raise. A telemetry write must not be able to fail a request.
    """
    now = datetime.now(timezone.utc)
    try:
        last = user.last_active_at
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if now - last < _TOUCH_INTERVAL:
                return  # steady state: one datetime compare, zero queries

        async with async_session() as db:
            await db.execute(
                update(User).where(User.id == user.id).values(last_active_at=now)
            )
            # Silent auto-resume, same transaction. Only sites WE paused: a
            # manual pause has a NULL stamp and must stay paused.
            await db.execute(
                update(Site)
                .where(Site.user_id == user.id, Site.auto_paused_at.is_not(None))
                .values(tracking_enabled=True, auto_paused_at=None)
            )
            await db.commit()
        # Keep the in-memory row consistent so a second dependency call in the
        # same request doesn't write again.
        user.last_active_at = now
    except Exception as exc:
        logger.warning("user_activity_touch_failed", error=str(exc))


# ──────────────────────────────── the sweep ────────────────────────────────


async def _try_acquire_lock(db) -> bool | None:
    """True = acquired, False = held elsewhere, None = unsupported (SQLite)."""
    try:
        result = await db.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": _LOCK_KEY}
        )
        return bool(result.scalar())
    except Exception as exc:
        logger.warning("reengagement_lock_unavailable", error=str(exc))
        return None


async def _release_lock(db) -> None:
    try:
        await db.execute(
            text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": _LOCK_KEY}
        )
    except Exception:
        pass


def _owner_email_filters():
    """Shared cohort exclusions: active, real address, not an admin."""
    return (
        User.is_active.is_(True),
        User.is_admin.is_(False),
        User.email.is_not(None),
        ~User.email.like(f"%{_PLACEHOLDER_EMAIL_SUFFIX}"),
    )


async def _stage_remind(db, sender: EmailSender, now: datetime) -> int:
    """Stage 1 — email owners idle past the remind threshold who have a live
    pixel and something worth coming back for."""
    idle_cutoff = now - timedelta(days=settings.reengagement_remind_after_days)
    rows = (
        await db.execute(
            select(User.id, User.email, User.last_active_at)
            .where(
                *_owner_email_filters(),
                User.last_active_at < idle_cutoff,
                or_(
                    User.last_reengagement_sent_at.is_(None),
                    User.last_reengagement_sent_at < User.last_active_at,
                ),
                exists().where(
                    Site.user_id == User.id,
                    Site.pixel_verified.is_(True),
                    Site.tracking_enabled.is_(True),
                ),
            )
            .order_by(User.created_at)
        )
    ).all()

    sent = 0
    for user_id, email, last_active_at in rows:
        try:
            site_rows = (
                await db.execute(
                    select(Site.site_id, Site.name).where(
                        Site.user_id == user_id,
                        Site.pixel_verified.is_(True),
                        Site.tracking_enabled.is_(True),
                    )
                )
            ).all()
            if not site_rows:
                continue
            site_ids = [r[0] for r in site_rows]
            site_names = [r[1] for r in site_rows]

            # visitors/identified_visitors are naive-UTC tables.
            since = last_active_at
            if since.tzinfo is not None:
                since = since.astimezone(timezone.utc).replace(tzinfo=None)

            identified_count = int(
                (
                    await db.execute(
                        select(func.count())
                        .select_from(IdentifiedVisitor)
                        .where(
                            IdentifiedVisitor.site_id.in_(site_ids),
                            IdentifiedVisitor.resolved_at >= since,
                        )
                    )
                ).scalar()
                or 0
            )
            new_visitor_count = int(
                (
                    await db.execute(
                        select(func.count())
                        .select_from(Visitor)
                        .where(
                            Visitor.site_id.in_(site_ids),
                            Visitor.first_seen >= since,
                        )
                    )
                ).scalar()
                or 0
            )
            if identified_count == 0 and new_visitor_count == 0:
                # Nothing happened while they were away — no email, and NO
                # stamp, so they stay in the cohort and are re-checked tomorrow
                # (and, crucially, are never eligible for the pause that
                # requires an outstanding reminder).
                continue

            subject, html = _reminder_email(
                identified_count, new_visitor_count, site_names
            )
            result = await sender.send(
                to_email=email,
                subject=subject,
                body_html=html,
                db=db,
                branding=True,
            )
            if result is None:
                # Suppressed (unsubscribed/bounced). No stamp -> never a pause,
                # because a pause requires a warning that was actually sent.
                await db.rollback()
                continue
            await db.execute(
                update(User)
                .where(User.id == user_id)
                .values(last_reengagement_sent_at=now)
            )
            await db.commit()
            sent += 1
        except Exception:
            logger.exception("reengagement_remind_failed", user_id=str(user_id))
            await db.rollback()
    return sent


async def _stage_pause(db, sender: EmailSender, now: datetime) -> int:
    """Stage 2 — pause tracking for owners still idle after a delivered warning.

    The pause and its notice are atomic: the email is sent BEFORE the commit, so
    a send failure rolls the pause back and the sites stay live until tomorrow.
    Nobody is ever paused silently.
    """
    now_naive = now.replace(tzinfo=None)
    idle_cutoff = now - timedelta(days=settings.reengagement_pause_after_days)
    warn_cutoff = now - timedelta(days=settings.reengagement_pause_warning_min_days)

    rows = (
        await db.execute(
            select(User.id, User.email)
            .where(
                *_owner_email_filters(),
                User.last_active_at < idle_cutoff,
                User.last_reengagement_sent_at.is_not(None),
                User.last_reengagement_sent_at > User.last_active_at,
                User.last_reengagement_sent_at <= warn_cutoff,
                exists().where(
                    Site.user_id == User.id,
                    Site.tracking_enabled.is_(True),
                ),
            )
            .order_by(User.created_at)
        )
    ).all()

    paused = 0
    for user_id, email in rows:
        try:
            # Guarded UPDATE: re-checks inactivity at write time, closing the
            # race with a login that happened between the SELECT above and now.
            # Only tracking_enabled IS TRUE rows are touched, so a site the
            # owner paused by hand is never restamped as an auto-pause.
            result = await db.execute(
                update(Site)
                .where(
                    Site.user_id == user_id,
                    Site.tracking_enabled.is_(True),
                    exists().where(
                        User.id == user_id,
                        User.last_active_at < idle_cutoff,
                    ),
                )
                .values(tracking_enabled=False, auto_paused_at=now_naive)
                .returning(Site.name)
            )
            site_names = [r[0] for r in result.all()]
            if not site_names:
                await db.rollback()
                continue

            subject, html = _paused_email(site_names)
            sent = await sender.send(
                to_email=email,
                subject=subject,
                body_html=html,
                db=db,
                branding=True,
            )
            if sent is None:
                # Suppressed recipient: roll the pause back. A confirmed
                # decision — no pause without a deliverable notice.
                await db.rollback()
                logger.info("reengagement_pause_skipped_suppressed", user_id=str(user_id))
                continue
            await db.commit()
            paused += 1
        except Exception:
            logger.exception("reengagement_pause_failed", user_id=str(user_id))
            await db.rollback()
    return paused


async def _stage_install_nudge(db, sender: EmailSender, now: datetime) -> int:
    """Stage 3 — one-time nudge for accounts that created a site and never
    installed the pixel (no verification, no events at all)."""
    grace_cutoff = now.replace(tzinfo=None) - timedelta(
        days=settings.reengagement_install_nudge_after_days
    )

    rows = (
        await db.execute(
            select(User.id, User.email)
            .where(
                *_owner_email_filters(),
                User.install_nudge_sent_at.is_(None),
                # Has at least one site old enough to have been installed...
                exists().where(
                    Site.user_id == User.id,
                    Site.created_at < grace_cutoff,
                ),
                # ...and no site of theirs is verified.
                ~exists().where(
                    Site.user_id == User.id,
                    Site.pixel_verified.is_(True),
                ),
            )
            .order_by(User.created_at)
        )
    ).all()

    nudged = 0
    for user_id, email in rows:
        try:
            site_rows = (
                await db.execute(
                    select(Site.site_id, Site.name)
                    .where(Site.user_id == user_id)
                    .order_by(Site.created_at)
                )
            ).all()
            if not site_rows:
                continue
            site_ids = [r[0] for r in site_rows]
            has_events = bool(
                (
                    await db.execute(
                        select(Event.id).where(Event.site_id.in_(site_ids)).limit(1)
                    )
                ).first()
            )
            if has_events:
                # The pixel did fire at some point — this is not an install
                # problem, so don't nudge (and don't burn the once-only stamp).
                continue

            subject, html = _install_nudge_email(site_rows[0][1])
            sent = await sender.send(
                to_email=email,
                subject=subject,
                body_html=html,
                db=db,
                branding=True,
            )
            if sent is None:
                await db.rollback()
                continue
            await db.execute(
                update(User).where(User.id == user_id).values(install_nudge_sent_at=now)
            )
            await db.commit()
            nudged += 1
        except Exception:
            logger.exception("reengagement_nudge_failed", user_id=str(user_id))
            await db.rollback()
    return nudged


async def run_reengagement_sweep() -> dict[str, int]:
    """Run the three-stage inactivity sweep. Returns per-stage counts.

    Single-flighted across replicas by a Postgres advisory lock (fail-open on a
    DB that doesn't support it). Per-user failures are isolated by rollback so
    one bad row can't abort the run.
    """
    now = datetime.now(timezone.utc)
    counts = {"reminded": 0, "paused": 0, "nudged": 0}

    async with async_session() as db:
        got = await _try_acquire_lock(db)
        if got is False:
            logger.info("reengagement_locked_elsewhere")
            return counts
        try:
            sender = EmailSender()
            counts["reminded"] = await _stage_remind(db, sender, now)
            counts["paused"] = await _stage_pause(db, sender, now)
            if settings.reengagement_install_nudge_enabled:
                counts["nudged"] = await _stage_install_nudge(db, sender, now)
        finally:
            if got:
                await _release_lock(db)

    if any(counts.values()):
        logger.info("reengagement_sweep_done", **counts)
    return counts
