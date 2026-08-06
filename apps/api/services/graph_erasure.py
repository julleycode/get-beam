"""Cross-tenant identity-graph erasure: producer helper + draining sweep.

WHY THIS EXISTS. ``beam_identity_graph`` pools identifications across every
Beam customer. A per-visitor deletion request deletes the requesting tenant's
own rows, but historically never reached the shared graph — so an erased person
stayed live and was still served to every other tenant. This module closes that.

SHAPE. ``enqueue_erasure()`` runs synchronously inside the tenant's DELETE
request and only writes a queue row (never a graph read — see the
existence-oracle rule below). ``run_graph_erasure_sweep()`` drains that queue
out of band on an APScheduler interval.

Only ``_try_acquire_lock`` / ``_release_lock`` / owning our own ``async_session``
are modelled on ``services/referral_activation.py``. NOTHING ELSE is copied from
it: its one-commit-per-row shape is the WRONG shape here. It has no
``processing`` state and no lease, so it is not a state-machine precedent — the
transaction boundaries below are specified from scratch.

THREE BINDING TRANSACTION BOUNDARIES (do not "simplify" these):

1. The claim commits ALONE, before any destructive statement, and its RETURNING
   values are captured into locals. If the claim shared a transaction with the
   work, a crash would roll back the ``attempts`` increment too — so
   ``attempts >= max_attempts`` could never trip, the stale-``processing``
   reclaim would be dead code, and a permanently-failing request would look
   identical to one never attempted.
2. The tombstone INSERT and the graph DELETE share ONE transaction, opened with
   an explicit ``async with db.begin():``, tombstone FIRST, with no intervening
   commit. *Tombstoned-but-not-deleted* is benign (the person is already
   unresolvable and unwritable; the next sweep finishes the job).
   *Deleted-but-not-tombstoned* is the harmful inverse: the rows are gone,
   nothing records the erasure, and the person is silently re-addable.
3. The failure path rolls back and then issues a FRESH update using the
   ``attempts`` captured at claim time (the ORM state is expired by the
   rollback). Without that re-issue every transient error wedges the row at
   ``processing`` for the whole stale window — a 30-minute stall on a ~1-month
   legal clock.

PLAINTEXT-FREE. The queue holds blind indexes and fingerprints only. That is
why ``suppression._cascade_suppress`` is never called here: it needs plaintext
throughout (it matches ``lower(IdentifiedVisitor.email)``), and handing it a
blind index would hash garbage and silently match nothing — false confidence
that a cascade ran. Both tombstone rows are written by the raw insert below,
reusing the stored blind index directly as ``SuppressionEntry.email_hash``
(same HMAC, same key — see ``services/pii_crypto.py``).
"""

import re
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import String, cast, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.beam_identity import BeamIdentityNode
from apps.api.models.database import async_session
from apps.api.models.erasure_request import ERASURE_TARGETS, ErasureRequest
from apps.api.models.suppression import SuppressionEntry
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.models.visitor_email import VisitorEmail
from apps.api.services.pii_crypto import email_hash

logger = structlog.get_logger()

_LOCK_KEY = "beam_graph_erasure"

# Both tombstone scopes. "erased" is the durable audit marker AND the scope the
# write-boundary guard checks (so it alone blocks every future graph write).
# "do_not_process" is written for a different reason: it is the scope the
# pre-existing, unmodified upstream opt-out check asks for.
_TOMBSTONE_SCOPES: tuple[str, ...] = ("erased", "do_not_process")

# Scopes the graph write boundary refuses on. "erased" is already here, which is
# why the erased row alone delivers the no-silent-re-creation guarantee.
GRAPH_WRITE_BLOCKING_SCOPES: tuple[str, ...] = ("erased", "do_not_process")

# Bound on rows drained per pass so one sweep tick can never run unboundedly.
_MAX_ROWS_PER_PASS = 200

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def sanitize_error(exc: BaseException | str) -> str:
    """Render an exception for ``last_error`` with no PII and a hard length cap.

    Provider/driver errors routinely echo the offending row back, so an
    unsanitised message is a realistic way to leak an address into a table that
    exists precisely to hold no addresses.
    """
    raw = str(exc)
    return _EMAIL_RE.sub("[email-redacted]", raw)[:500]


async def _try_acquire_lock(db: AsyncSession) -> bool | None:
    """True = acquired, False = held elsewhere, None = unsupported (SQLite)."""
    try:
        result = await db.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": _LOCK_KEY}
        )
        return bool(result.scalar())
    except Exception as exc:  # noqa: BLE001
        logger.warning("graph_erasure_lock_unavailable", error=str(exc))
        return None


async def _release_lock(db: AsyncSession) -> None:
    try:
        await db.execute(
            text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": _LOCK_KEY}
        )
    except Exception:  # noqa: BLE001
        pass


# ─────────────────────────── producer ───────────────────────────


async def _collect_match_keys(
    db: AsyncSession, site_id: str, visitor_id: str
) -> tuple[list[str], list[str]]:
    """Read the visitor's fingerprints and email blind indexes.

    ORDERING-CRITICAL: this MUST run before the caller's DELETE loop. Those rows
    are the only source of the match keys, so enqueuing afterwards would always
    produce an empty-keyed, useless request. Emails are hashed immediately and
    the plaintext is never returned or persisted.
    """
    fingerprints: list[str] = []
    bidx: list[str] = []

    row = (
        await db.execute(
            select(Visitor.fingerprint, Visitor.fingerprint_v3).where(
                Visitor.site_id == site_id, Visitor.visitor_id == visitor_id
            )
        )
    ).first()
    if row is not None:
        fingerprints.extend(v for v in row if v)

    for stmt in (
        select(IdentifiedVisitor.email).where(
            IdentifiedVisitor.site_id == site_id,
            IdentifiedVisitor.visitor_id == visitor_id,
        ),
        select(VisitorEmail.email).where(
            VisitorEmail.site_id == site_id,
            VisitorEmail.visitor_id == visitor_id,
        ),
    ):
        for email in (await db.execute(stmt)).scalars().all():
            if email:
                bidx.append(email_hash(email))

    # Dedupe, order-stable.
    return list(dict.fromkeys(fingerprints)), list(dict.fromkeys(bidx))


async def _volume_marker_tripped(db: AsyncSession, site_id: str) -> bool:
    """Whether this site's recent enqueue volume exceeded the forensic marker.

    RECORDS, DOES NOT PREVENT (see config's inline note, and the flag column's
    docstring). A trip changes no execution path: the row is written anyway and
    the sweep claims and processes it identically.
    """
    since = datetime.now(timezone.utc) - timedelta(minutes=1)
    recent = (
        await db.execute(
            select(func.count(ErasureRequest.id)).where(
                ErasureRequest.requesting_site_id == site_id,
                ErasureRequest.created_at >= since,
            )
        )
    ).scalar() or 0
    return int(recent) >= settings.graph_erasure_max_per_minute


async def enqueue_erasure(
    db: AsyncSession, *, site_id: str, visitor_id: str
) -> ErasureRequest | None:
    """Queue a cross-tenant graph erasure for one visitor. Returns the row.

    Performs NO graph read: the caller's response must be byte-shape-identical
    whether or not a matching graph row exists, otherwise the deletion endpoint
    becomes a probe for testing whether an arbitrary person is in the shared
    graph — a cross-tenant PII disclosure introduced by a privacy feature.

    Commits its own insert so the queued request survives even if the caller's
    subsequent local deletion partially fails.
    """
    fingerprints, bidx = await _collect_match_keys(db, site_id, visitor_id)

    flagged = await _volume_marker_tripped(db, site_id)
    if flagged:
        # Forensic record only. Never a rejection, never a 429, never a filter.
        logger.warning(
            "erasure_enqueue_throttled", site_id=site_id, visitor_id=visitor_id[:8]
        )

    row = ErasureRequest(
        requesting_site_id=site_id,
        visitor_id=visitor_id,
        email_bidx_list=bidx or None,
        fingerprint_list=fingerprints or None,
        targets=list(ERASURE_TARGETS),
        status="pending",
        attempts=0,
        throttle_flagged=flagged,
    )
    db.add(row)
    await db.commit()
    logger.info(
        "erasure_enqueued",
        site_id=site_id,
        visitor_id=visitor_id[:8],
        fingerprint_count=len(fingerprints),
        email_bidx_count=len(bidx),
        throttle_flagged=flagged,
    )
    return row


# ─────────────────────────── sweep ───────────────────────────


async def _reclaim_stale(db: AsyncSession) -> int:
    """Return rows abandoned mid-flight (process died) to ``pending``.

    Reachable only because the claim commits separately (Boundary 1) — under a
    shared transaction the claim would simply have rolled back and this step
    would be dead code.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=settings.graph_erasure_stale_processing_minutes
    )
    result = await db.execute(
        update(ErasureRequest)
        .where(
            ErasureRequest.status == "processing",
            ErasureRequest.updated_at < cutoff,
        )
        .values(status="pending", updated_at=func.now())
    )
    await db.commit()
    n = result.rowcount or 0
    if n:
        logger.warning("erasure_stale_reclaimed", count=n)
    return n


async def _claim_next(db: AsyncSession) -> dict | None:
    """Boundary 1: claim ONE pending row and COMMIT that claim on its own.

    The claim query filters on ``status='pending'`` and MUST NOT grow a
    ``throttle_flagged`` filter — a flagged row is claimed and processed exactly
    like any other, by design.
    """
    candidate = (
        await db.execute(
            select(ErasureRequest.id)
            .where(ErasureRequest.status == "pending")
            .order_by(ErasureRequest.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if candidate is None:
        return None

    claimed = (
        await db.execute(
            update(ErasureRequest)
            .where(
                ErasureRequest.id == candidate,
                ErasureRequest.status == "pending",
            )
            .values(
                status="processing",
                attempts=ErasureRequest.attempts + 1,
                updated_at=func.now(),
            )
            .returning(
                ErasureRequest.id,
                ErasureRequest.attempts,
                ErasureRequest.email_bidx_list,
                ErasureRequest.fingerprint_list,
                ErasureRequest.targets,
            )
        )
    ).first()
    # Commit the claim BEFORE any destructive statement, and capture RETURNING
    # into plain locals — they are the only state that survives a work rollback.
    await db.commit()
    if claimed is None:
        return None  # another worker won the race
    return {
        "id": claimed[0],
        "attempts": int(claimed[1] or 0),
        "email_bidx_list": list(claimed[2] or []),
        "fingerprint_list": list(claimed[3] or []),
        "targets": list(claimed[4] or ERASURE_TARGETS),
    }


def _tombstone_stmt(bidx_list: list[str]):
    """Both tombstone rows for every blind index, as ONE raw insert.

    ``_cascade_suppress`` is deliberately not used — it requires plaintext and
    the queue holds none by design.
    """
    values = [
        {
            "email_hash": b,
            "scope": scope,
            "reason": "graph_erasure",
            "requested_by": None,
        }
        for b in bidx_list
        for scope in _TOMBSTONE_SCOPES
    ]
    return (
        pg_insert(SuppressionEntry)
        .values(values)
        .on_conflict_do_nothing(index_elements=["email_hash", "scope"])
    )


def _graph_delete_stmt(bidx_list: list[str], fingerprints: list[str]):
    """Delete matching shared-graph rows. NO ``source_site_id`` filter — that
    absence is the whole cross-tenant mechanism."""
    b = cast(bidx_list, ARRAY(String))
    f = cast(fingerprints, ARRAY(String))
    return BeamIdentityNode.__table__.delete().where(
        or_(
            BeamIdentityNode.email_bidx == func.any(b),
            BeamIdentityNode.fingerprint == func.any(f),
            BeamIdentityNode.fingerprint_v3 == func.any(f),
        )
    )


async def _process_claimed(db: AsyncSession, claimed: dict) -> bool:
    """Run one claimed row's destructive work. Never raises."""
    bidx = claimed["email_bidx_list"]
    fps = claimed["fingerprint_list"]
    try:
        if bidx or fps:
            # Boundary 2: ONE explicit transaction, tombstone-first, no
            # intervening commit. The `async with` makes that structurally
            # obvious at the call site rather than prose-only.
            async with db.begin():
                if bidx:
                    await db.execute(_tombstone_stmt(bidx))
                for target in claimed["targets"]:
                    if target != "beam_identity_graph":
                        logger.warning("erasure_unknown_target", target=target)
                        continue
                    await db.execute(_graph_delete_stmt(bidx, fps))

        await db.execute(
            update(ErasureRequest)
            .where(ErasureRequest.id == claimed["id"])
            .values(
                status="done", processed_at=func.now(), updated_at=func.now()
            )
        )
        await db.commit()
        logger.info("erasure_request_done", request_id=str(claimed["id"]))
        return True
    except Exception as exc:  # noqa: BLE001 — the sweep must never raise out
        # Boundary 3: rollback discards the work only (the claim is already
        # committed), then a FRESH update using the CAPTURED attempts — the ORM
        # attribute is expired by the rollback and must not be read.
        await db.rollback()
        terminal = (
            "failed"
            if claimed["attempts"] >= settings.graph_erasure_max_attempts
            else "pending"
        )
        try:
            await db.execute(
                update(ErasureRequest)
                .where(ErasureRequest.id == claimed["id"])
                .values(
                    status=terminal,
                    last_error=sanitize_error(exc),
                    updated_at=func.now(),
                )
            )
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
            logger.exception("erasure_status_writeback_failed")
        logger.warning(
            "erasure_request_failed",
            request_id=str(claimed["id"]),
            attempts=claimed["attempts"],
            terminal=terminal,
            error=sanitize_error(exc),
        )
        return False


async def queue_health(db: AsyncSession) -> dict:
    """Counts and ages only — never a request row, bidx, fingerprint, or email."""
    rows = (
        await db.execute(
            select(ErasureRequest.status, func.count(ErasureRequest.id)).group_by(
                ErasureRequest.status
            )
        )
    ).all()
    counts = {status: int(n) for status, n in rows}

    oldest_pending = (
        await db.execute(
            select(func.min(ErasureRequest.created_at)).where(
                ErasureRequest.status.in_(("pending", "processing"))
            )
        )
    ).scalar()
    oldest_failed = (
        await db.execute(
            select(func.min(ErasureRequest.created_at)).where(
                ErasureRequest.status == "failed"
            )
        )
    ).scalar()
    flagged = (
        await db.execute(
            select(func.count(ErasureRequest.id)).where(
                ErasureRequest.throttle_flagged.is_(True)
            )
        )
    ).scalar() or 0

    return {
        "pending": counts.get("pending", 0),
        "processing": counts.get("processing", 0),
        "done": counts.get("done", 0),
        "failed": counts.get("failed", 0),
        "oldest_pending_age_hours": _age_hours(oldest_pending),
        "oldest_failed_age_hours": _age_hours(oldest_failed),
        "throttle_flagged_count": int(flagged),
    }


def _age_hours(ts: datetime | None) -> float | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - ts).total_seconds() / 3600.0, 2)


async def _emit_queue_health(db: AsyncSession) -> dict:
    """One structlog line per pass. Warns on a stale queue OR any failed row.

    A permanently-``failed`` erasure is the WORST silent outcome, not a lesser
    one: the caller already got an unconditional 200 while the graph rows are
    retained. It must never be reachable only at ``info``.
    """
    health = await queue_health(db)
    oldest = health["oldest_pending_age_hours"]
    stale = oldest is not None and oldest > settings.graph_erasure_stale_alert_hours
    payload = {
        "pending_count": health["pending"],
        "processing_count": health["processing"],
        "failed_count": health["failed"],
        "oldest_pending_age_hours": oldest,
    }
    if health["failed"]:
        payload["oldest_failed_age_hours"] = health["oldest_failed_age_hours"]
    if stale or health["failed"]:
        logger.warning("erasure_queue_health", **payload)
    else:
        logger.info("erasure_queue_health", **payload)
    return health


async def run_graph_erasure_sweep() -> int:
    """Drain the erasure queue. Owns its session; single-flight via advisory lock."""
    if not settings.graph_erasure_sweep_enabled:
        return 0

    processed = 0
    async with async_session() as db:
        got = await _try_acquire_lock(db)
        if got is False:
            logger.info("graph_erasure_locked_elsewhere")
            return 0
        try:
            await _reclaim_stale(db)
            while processed < _MAX_ROWS_PER_PASS:
                claimed = await _claim_next(db)
                if claimed is None:
                    break
                await _process_claimed(db, claimed)
                processed += 1
            await _emit_queue_health(db)
        finally:
            if got:
                await _release_lock(db)

    return processed


# ─────────────────────────── operator lookup ───────────────────────────


async def lookup_graph_identity(
    db: AsyncSession, *, email: str | None = None, fingerprint: str | None = None
) -> dict:
    """Answer "is this person in the shared graph, and who put them there".

    Deliberately an existence oracle — that is its whole purpose — which is why
    every caller must be platform-operator gated. Returns no email, name, or
    ciphertext.
    """
    if bool(email) == bool(fingerprint):
        raise ValueError("exactly one of email or fingerprint is required")

    if email:
        bidx = email_hash(email)
        where = BeamIdentityNode.email_bidx == bidx
        matched_by = "email"
    else:
        bidx = None
        where = or_(
            BeamIdentityNode.fingerprint == fingerprint,
            BeamIdentityNode.fingerprint_v3 == fingerprint,
        )
        matched_by = "fingerprint"

    site_ids = list(
        (
            await db.execute(select(BeamIdentityNode.source_site_id).where(where))
        ).scalars().all()
    )

    erased = False
    if bidx is not None:
        erased = (
            await db.execute(
                select(SuppressionEntry.id)
                .where(
                    SuppressionEntry.email_hash == bidx,
                    SuppressionEntry.scope == "erased",
                )
                .limit(1)
            )
        ).scalar_one_or_none() is not None

    return {
        "exists": bool(site_ids),
        "row_count": len(site_ids),
        "contributing_site_ids": sorted(set(site_ids)),
        "erased_tombstone": erased,
        "matched_by": matched_by,
    }
