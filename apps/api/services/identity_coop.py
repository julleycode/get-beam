"""Identity co-op accrual + ledger service. ALL co-op logic lives here.

identity-coop Phase 1 (visitors-identity, 07-08-26). The only change inside
``identity_resolver.py`` is a conditional call to ``record_contribution`` — every
rule below is enforced in this module so the contested resolver keeps a minimal
diff footprint.

Deliberate structural constraints (each one is load-bearing, not style):

* **No module-level import of ``identity_resolver``** — the resolver imports this
  module locally inside its own function, so a module-level import back would be
  a cycle. This module takes a plain ``AsyncSession`` plus already-resolved scalar
  values; it holds no shared state and reads nothing off the resolver.

* **No suppression check here (D-B).** ``record_contribution`` is only ever called
  when ``_upsert_beam_identity`` returned ``True``, which means the resolver's own
  write boundary already cleared ``do_not_resolve`` and every scope in
  ``GRAPH_WRITE_BLOCKING_SCOPES`` + ``"all"``. This module therefore imports no
  ``SuppressionEntry`` and re-lists no scope literal — the single source of truth
  stays inside the resolver's boundary. Consequence: when the graph write was
  blocked, NOTHING is written here (no event, no excluded-reason row, no ledger
  row), which is exactly what makes the co-op tables' absence from
  ``ERASURE_TARGETS`` harmless. See the privacy invariant in ``models/identity_coop``.

* **Blind index only.** Callers pass ``email_bidx`` (from ``pii_crypto.email_hash``);
  a plaintext email never enters this module. ``structlog`` calls log keys/ids only.

* **Best-effort.** The whole body is wrapped in try/except: a co-op failure must
  never break a successful identification.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.identity_coop import (
    ContributionConsentAcceptance,
    ContributionEvent,
    CreditLedgerEntry,
)

logger = structlog.get_logger()


class CoopExpirySystemicFailure(RuntimeError):
    """Every processed lot in one ``expire_lapsed_lots`` batch failed (D4).

    Exists because the per-lot ``except Exception`` (C-1) is load-bearing and
    must NOT be narrowed — narrowing only swaps one silent-failure class for
    another. The systemic case is detected by COUNTING instead: all-failed means
    a systemic cause (missing arbiter index, dead session, exhausted pool) is
    likelier than N individually-bad lots, so we raise rather than return 0.
    """


async def maybe_record_contribution(
    db: AsyncSession,
    visitor,
    data: dict,
    provider: str,
) -> None:
    """Resolver-facing entrypoint: resolve the per-site flag, then record.

    This exists so the contested ``identity_resolver.py`` needs only a two-line
    conditional and holds none of the co-op's logic. The caller has already
    confirmed BOTH that ``settings.identity_coop_enabled`` is True AND that the
    graph write actually succeeded; this function adds the per-site half of the
    gate and translates the resolver's objects into the blind-index-only scalars
    ``record_contribution`` accepts.

    The ``Site.contribution_enabled`` lookup is a single indexed scalar select and
    only ever runs when the global flag is already ON (default OFF ⇒ zero cost)
    and only on the newly-identified path, which is already several round-trips
    deep — never on the ingest hot path. Never raises.
    """
    try:
        from apps.api.models.site import Site
        from apps.api.services.pii_crypto import email_hash

        site_id = visitor.site_id
        enabled = (
            await db.execute(
                select(Site.contribution_enabled).where(Site.site_id == site_id)
            )
        ).scalar_one_or_none()
        if not enabled:
            return

        email = data.get("email")
        if not email:
            return

        await record_contribution(
            db,
            site_id=site_id,
            email_bidx=email_hash(email),
            source_provider=provider,
            is_abuse_flagged=bool(getattr(visitor, "is_abuse_flagged", False)),
            is_bot_suspect=bool(getattr(visitor, "is_bot_suspect", False)),
        )
    except Exception as exc:  # noqa: BLE001 — never break a successful identification
        logger.warning("coop_contribution_failed", error=str(exc))


async def record_contribution(
    db: AsyncSession,
    *,
    site_id: str,
    email_bidx: str,
    source_provider: str | None,
    is_abuse_flagged: bool,
    is_bot_suspect: bool,
    contributed_on: date | None = None,
) -> None:
    """Record one contribution event and accrue a credit if it qualifies.

    Called ONLY after a real ``beam_identity_graph`` write succeeded (the caller
    gates on ``_upsert_beam_identity``'s ``bool`` return), so a contribution here
    always corresponds to an actual graph write — no credit is ever minted for a
    write that did not happen.

    Gate order, and why each gate produces the row it does:

    1. **Merge-awareness (AC-3)** — insert the event with
       ``ON CONFLICT (site_id, email_bidx, contributed_on) DO NOTHING``. The same
       person resolved twice under two ``visitor_id``s on the same day collapses
       to one row; the second attempt is a no-op and returns without accrual.
    2. **Fraud gate (AC-9, D-C)** — ``is_abuse_flagged`` OR ``is_bot_suspect``
       leaves the EVENT recorded (auditability) but sets
       ``excluded_reason='fraud_flagged'`` and writes no ledger row. Only ACCRUAL
       is gated, never the audit trail.
    3. **Once-per-identity accrual (D-E)** — the ACCRUE insert races against the
       ``uq_coop_accrued_site_email`` partial unique index. A repeat resolve of an
       already-credited identity on a later day records an event row with
       ``excluded_reason='duplicate'`` and mints nothing. The DB index (not this
       code) is the real enforcement, so a concurrent race cannot double-credit.

    Never raises. Returns None.
    """
    try:
        contributed_on = contributed_on or datetime.now(timezone.utc).date()
        now = datetime.now(timezone.utc)

        # 1. Merge-aware event insert. RETURNING id is empty on conflict, which is
        #    how we detect the same-day duplicate without a second round-trip.
        stmt = (
            pg_insert(ContributionEvent)
            .values(
                site_id=site_id,
                email_bidx=email_bidx,
                contributed_on=contributed_on,
                source_provider=source_provider,
                accrued=False,
            )
            .on_conflict_do_nothing(
                constraint="uq_coop_contrib_site_email_day",
            )
            .returning(ContributionEvent.id)
        )
        event_id = (await db.execute(stmt)).scalar_one_or_none()
        if event_id is None:
            # Same (site, identity, day) already recorded — one event, one chance.
            await db.commit()
            return

        # 2. Fraud gate. The event stays; only the credit is withheld.
        if is_abuse_flagged or is_bot_suspect:
            await _mark_excluded(db, event_id, "fraud_flagged")
            await db.commit()
            logger.info(
                "coop_contribution_excluded",
                site_id=site_id,
                reason="fraud_flagged",
            )
            return

        # 3. Accrue — one credit per (site, identity) for all time. The partial
        #    unique index is what enforces it; the IntegrityError below IS the
        #    duplicate path, not an error condition.
        try:
            async with db.begin_nested():
                await db.execute(
                    ContributionEvent.__table__.update()
                    .where(ContributionEvent.id == event_id)
                    .values(accrued=True, excluded_reason=None)
                )
        except IntegrityError:
            await _mark_excluded(db, event_id, "duplicate")
            await db.commit()
            logger.info(
                "coop_contribution_excluded", site_id=site_id, reason="duplicate"
            )
            return

        ledger = CreditLedgerEntry(
            site_id=site_id,
            entry_type="ACCRUE",
            amount=settings.coop_credit_per_contribution,
            reason="contribution",
            spendable_at=now + timedelta(hours=settings.coop_credit_hold_hours),
            expires_at=now + timedelta(days=settings.coop_credit_expiry_days),
            contribution_event_id=event_id,
        )
        db.add(ledger)
        await db.flush()
        # An ACCRUE row is its own lot; Phase 2's SPEND/EXPIRE rows point here.
        ledger.lot_id = ledger.id
        await db.commit()
        logger.info(
            "coop_contribution_accrued",
            site_id=site_id,
            amount=settings.coop_credit_per_contribution,
        )
    except Exception as exc:  # noqa: BLE001 — a co-op failure never breaks resolve
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001 — rollback of an already-dead session
            pass
        # Keys/ids only — NEVER PII (email_bidx is a blind index but still an
        # identity key, so it is deliberately not logged here either).
        logger.warning("coop_contribution_failed", error=str(exc))


async def _mark_excluded(db: AsyncSession, event_id, reason: str) -> None:
    """Stamp an already-inserted event as not-accrued with a reason."""
    await db.execute(
        ContributionEvent.__table__.update()
        .where(ContributionEvent.id == event_id)
        .values(accrued=False, excluded_reason=reason)
    )


async def spendable_balance(db: AsyncSession, site_id: str) -> int:
    """Credits this site can spend right now. DERIVED, never a stored column (AC-8).

    ``SUM(amount)`` over ledger rows whose lot has cleared its provisional hold
    (``spendable_at <= now``) and has not expired (``expires_at > now``). Computed
    at read time — same precedent as ``identity_signals.decay_confidence()`` — so
    a lot silently becomes unspendable at its expiry without any sweep having run.
    Phase 2 extends this (spend gate + the explicit EXPIRE sweep row); the Phase 1
    version proves AC-8's shape.

    Held lots are EXCLUDED (``spendable_at > now`` filters them out) — that is
    unchanged Phase 1 behaviour, and it is why the AC-8 reconciliation oracle is
    NOT unconditional: a fresh ACCRUE is inside a raw ``SUM(amount)`` but outside
    this balance. Any reconciliation assert must first put ``now`` past EVERY
    lot's ``spendable_at`` (monkeypatch ``coop_credit_hold_hours`` to 0, or seed
    past ``spendable_at`` values). Surfacing held credit as "pending" is Phase 3.

    A NULL ``spendable_at`` / ``expires_at`` always counts. Phase 2a's write side
    guarantees non-ACCRUE rows are never NULL: ``expire_lapsed_lots`` stamps every
    EXPIRE row with its source lot's window (P2-D5), so the −N enters and leaves
    this filter in lockstep with the +N it zeroes. NULL on a non-ACCRUE row is a
    defect that would drive the balance to −N.

    QUERY SHAPE IS FROZEN (Phase 2a Constraint 11) — covered by shipped tests.
    Phase 2a fixes the negative-balance defect purely on the WRITE side.
    """
    now = datetime.now(timezone.utc)
    stmt = select(func.coalesce(func.sum(CreditLedgerEntry.amount), 0)).where(
        CreditLedgerEntry.site_id == site_id,
        (CreditLedgerEntry.spendable_at.is_(None))
        | (CreditLedgerEntry.spendable_at <= now),
        (CreditLedgerEntry.expires_at.is_(None)) | (CreditLedgerEntry.expires_at > now),
    )
    return int((await db.execute(stmt)).scalar_one() or 0)


async def record_consent_acceptance(
    db: AsyncSession,
    *,
    site_id: str,
    terms_version: str,
    user_id,
) -> None:
    """Append one immutable co-op terms acceptance row (AC-10).

    Append-only by design: there is no update or delete path, so the trail of
    what was accepted and when cannot be rewritten even though the flag it gates
    is freely toggleable. Does NOT commit — the caller writes this in the SAME
    transaction as the flag flip, which is what makes "flag ON implies an
    acceptance row exists" true rather than merely usual.
    """
    db.add(
        ContributionConsentAcceptance(
            site_id=site_id,
            terms_version=terms_version,
            accepted_at=datetime.now(timezone.utc),
            accepted_by_user_id=user_id,
        )
    )
    await db.flush()


# ─────────────────── Phase 2a — consumption + FIFO lot expiry ───────────────────


def _naive_utc(value: datetime | None) -> datetime | None:
    """Normalize a bound to NAIVE UTC for ``api_usage_logs`` comparisons (S-22).

    ``api_usage_logs.created_at`` is a naive ``DateTime`` while the co-op ledger is
    ``DateTime(timezone=True)``. asyncpg RAISES when a tz-aware value is bound to a
    ``TIMESTAMP WITHOUT TIME ZONE`` column, so an un-normalized aware bound is an
    error rather than a silently shifted window. Aware values are converted to UTC
    and stripped; naive values are assumed to already be UTC and passed through.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _aware_utc(value: datetime | None) -> datetime | None:
    """Normalize a bound to AWARE UTC for the co-op tables (tz-aware columns)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def consumption_count(
    db: AsyncSession,
    site_id: str,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> int:
    """Graph-served identity resolutions charged to this site. READ-ONLY (P2-D2).

    A pure on-demand ``COUNT`` — no rollup table, no new column, no write of any
    kind on this path. The consumption event is already recorded: every owned
    graph hit goes ``_log_owned_resolution`` → ``log_api_call`` → an
    ``api_usage_logs`` row with ``provider='beam_identity_network'``,
    ``category='identity'``, ``cost_usd=0.0``, ``success=True``.

    The ``provider`` predicate is load-bearing, not redundant: all four
    ``OWNED_FREE_PROVIDERS`` (``form_capture``, ``fingerprint_match``,
    ``beam_identity_network``, ``svid_reconcile``) write ``category='identity'``
    with ``cost_usd=0.0``, so filtering on category or cost alone would count the
    other three plus every paid provider's mirror row — a co-op overcharge.

    **The join to ``identified_visitors`` is INNER, by design (A2/L-2).** A
    consumption row whose ``IdentifiedVisitor`` no longer exists is EXCLUDED: the
    per-visitor deletion path removes the identity row but leaves the
    ``api_usage_logs`` row, so a LEFT JOIN would keep charging for deleted
    identities. INNER means this counts *currently-attributable* resolutions —
    which is exactly what the co-op is entitled to charge against.

    **Emailless identities are EXCLUDED (decided, C4-2).** ``_sync_identity_pii``
    writes ``email_bidx = NULL`` when the row has no email, and the erased-row
    filter below is a ``NOT IN``, which is NULL under SQL three-valued logic — so
    such a row is dropped. That is the intended behaviour, not an accident: with
    no blind index there is nothing to compare against the erasure tombstones, and
    counting the row would risk billing for someone already erased. The error
    direction is deliberately conservative — this UNDERCOUNTS, never overcharges.
    Do not "rescue" it with ``COALESCE`` or ``OR email_bidx IS NULL``.

    Erased rows are excluded via ``SuppressionEntry(scope='erased')``, which since
    the tombstone-at-enqueue change means "erasure REQUESTED or completed" — so
    this excludes more, sooner. That is the intended direction.

    **Reconciliation invariant (per-live-site, never global):** *for every site
    that currently exists, ``consumption_count(site)`` equals the count of
    graph-served resolutions recorded for that site, excluding erased/deleted
    identities.* The unqualified form is falsified in production by per-visitor
    deletion and by the erasure exclusion; a global/historical form is falsified
    by site delete, which removes the site's ``api_usage_logs`` rows outright.
    """
    from apps.api.models.api_usage import ApiUsageLog
    from apps.api.models.suppression import SuppressionEntry
    from apps.api.models.visitor import IdentifiedVisitor

    erased = select(SuppressionEntry.email_hash).where(
        SuppressionEntry.scope == "erased"
    )

    stmt = (
        select(func.count())
        .select_from(ApiUsageLog)
        .join(
            IdentifiedVisitor,
            (IdentifiedVisitor.site_id == ApiUsageLog.site_id)
            & (IdentifiedVisitor.visitor_id == ApiUsageLog.visitor_id),
        )
        .where(
            ApiUsageLog.site_id == site_id,
            ApiUsageLog.provider == "beam_identity_network",
            ApiUsageLog.category == "identity",
            ApiUsageLog.success.is_(True),
            IdentifiedVisitor.email_bidx.not_in(erased),
        )
    )
    since_n = _naive_utc(since)
    until_n = _naive_utc(until)
    if since_n is not None:
        stmt = stmt.where(ApiUsageLog.created_at >= since_n)
    if until_n is not None:
        stmt = stmt.where(ApiUsageLog.created_at < until_n)

    return int((await db.execute(stmt)).scalar_one() or 0)


async def contribution_count(
    db: AsyncSession,
    site_id: str,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> int:
    """Qualifying contribution events for this site. READ-ONLY.

    ``excluded_reason IS NULL`` is the qualifying filter: a fraud-flagged or
    duplicate event is still recorded for auditability but never earned a credit,
    so counting it would overstate what the site contributed.
    """
    stmt = select(func.count()).select_from(ContributionEvent).where(
        ContributionEvent.site_id == site_id,
        ContributionEvent.excluded_reason.is_(None),
    )
    since_a = _aware_utc(since)
    until_a = _aware_utc(until)
    if since_a is not None:
        stmt = stmt.where(ContributionEvent.created_at >= since_a)
    if until_a is not None:
        stmt = stmt.where(ContributionEvent.created_at < until_a)

    return int((await db.execute(stmt)).scalar_one() or 0)


async def spendable_lots(db: AsyncSession, site_id: str) -> list[CreditLedgerEntry]:
    """Live ACCRUE lots for a site, FIFO by ``expires_at`` ASC (B1).

    FIFO by soonest expiry — draw the credit that would be wasted first. Each
    returned lot carries a non-persisted ``remaining`` attribute: the lot's ACCRUE
    amount minus everything already drawn against that ``lot_id`` (SPEND/EXPIRE
    rows), clamped at ``max(0, ...)`` (S-4) so a lot can never contribute negative
    spendable credit even if its rows have gone net-negative.

    A lot is live when ``spendable_at <= now`` (past its provisional hold) and
    ``expires_at > now``. Lots whose ``remaining`` has reached 0 are still
    returned — the draw caller (Phase 2b) skips them; filtering them here is not
    part of this phase's specified behaviour.
    """
    now = datetime.now(timezone.utc)

    drawn = (
        select(
            CreditLedgerEntry.lot_id.label("lot_id"),
            func.coalesce(func.sum(CreditLedgerEntry.amount), 0).label("net"),
        )
        .where(
            CreditLedgerEntry.site_id == site_id,
            CreditLedgerEntry.entry_type != "ACCRUE",
            CreditLedgerEntry.lot_id.is_not(None),
        )
        .group_by(CreditLedgerEntry.lot_id)
        .subquery()
    )

    stmt = (
        select(CreditLedgerEntry, func.coalesce(drawn.c.net, 0))
        .outerjoin(drawn, drawn.c.lot_id == CreditLedgerEntry.id)
        .where(
            CreditLedgerEntry.site_id == site_id,
            CreditLedgerEntry.entry_type == "ACCRUE",
            CreditLedgerEntry.spendable_at.is_not(None),
            CreditLedgerEntry.spendable_at <= now,
            CreditLedgerEntry.expires_at.is_not(None),
            CreditLedgerEntry.expires_at > now,
        )
        .order_by(CreditLedgerEntry.expires_at.asc())
    )

    lots: list[CreditLedgerEntry] = []
    for lot, net in (await db.execute(stmt)).all():
        # `net` is already negative for SPEND/EXPIRE rows, hence the addition.
        lot.remaining = max(0, int(lot.amount) + int(net or 0))
        lots.append(lot)
    return lots


async def _lot_remaining(db: AsyncSession, lot_id) -> int:
    """WINDOW-BLIND raw ``SUM(amount)`` over every row carrying this ``lot_id``.

    **No time predicate at all — that is load-bearing.** A window-AWARE reading
    would see a lapsed lot's ACCRUE as already outside the balance window, compute
    ``remaining == 0``, hit the skip in ``expire_lapsed_lots``, and write ZERO rows
    forever — while still passing every balance-shaped assertion, because a stamped
    EXPIRE row is balance-invisible by construction. That is the vacuous green this
    definition exists to prevent.
    """
    return int(
        (
            await db.execute(
                select(func.coalesce(func.sum(CreditLedgerEntry.amount), 0)).where(
                    CreditLedgerEntry.lot_id == lot_id
                )
            )
        ).scalar_one()
        or 0
    )


# Written verbatim per plan item B3: the existence check, the insert and the
# conflict clause are ONE statement — never a read-then-insert pair, never an
# insert without the conflict clause.
#
# WHERE EXISTS closes the orphan-EXPIRE window: the sweep loads its lapsed-lot
# set, a concurrent site delete cascades that site's ledger rows away, and a
# plain insert would then mint an EXPIRE for a lot that no longer exists — which
# a same-site_id re-create would inherit and Phase 3's dashboard (no window
# predicate) would report as credits the site never had.
#
# ON CONFLICT infers the E2 partial unique index BY PREDICATE, so a losing racer
# is a silent no-op rather than a 500. The CAST()s are required: a bare parameter
# in an INSERT ... SELECT list has no inferable type for asyncpg, and the `::`
# cast spelling collides with SQLAlchemy's own `:param` bind syntax.
_EXPIRE_INSERT_SQL = """
INSERT INTO identity_credit_ledger
    (id, site_id, entry_type, amount, lot_id, reason, spendable_at, expires_at, created_at)
SELECT CAST(:new_id AS uuid), CAST(:site_id AS varchar), 'EXPIRE',
       CAST(:amount AS integer), CAST(:lot_id AS uuid), 'lot_expired',
       CAST(:lot_spendable_at AS timestamptz),
       CAST(:lot_expires_at AS timestamptz), now()
WHERE EXISTS (
    SELECT 1 FROM identity_credit_ledger
    WHERE id = CAST(:lot_id AS uuid)
      AND entry_type = 'ACCRUE'
      AND site_id = CAST(:site_id AS varchar)
)
ON CONFLICT (lot_id) WHERE entry_type = 'EXPIRE' DO NOTHING
"""


async def expire_lapsed_lots(db: AsyncSession) -> int:
    """Write one explicit ``EXPIRE`` row per lapsed lot. Idempotent (AC-7 / B3).

    Owns BOTH the per-lot loop AND the per-lot ``commit()`` (M-2). Its caller,
    ``run_coop_expiry_sweep``, owns only the advisory lock and one call to this
    function — no loop and no commit of its own. Crash semantics that follow: a
    mid-sweep crash leaves every already-processed lot durably expired and every
    unprocessed lot untouched, so the next tick resumes correctly with no
    partial-lot state.

    **Callers (including tests) must note this commits its own work** — do not
    wrap it in an outer transaction you expect to roll back, and re-query rather
    than relying on identity-map caching to observe the written rows.

    Each row is stamped with the SOURCE LOT's ``spendable_at``/``expires_at``
    (S-10b), so the −N leaves ``spendable_balance``'s window together with the +N
    it zeroes rather than driving the balance negative.

    ``amount = -max(0, remaining)`` over a WINDOW-BLIND remainder: the clamp stops
    a lot whose raw SUM has gone negative from producing a POSITIVE EXPIRE row,
    which would violate the ledger's amount contract. A lot with
    ``max(0, remaining) == 0`` is skipped entirely — that skip is what makes
    re-running write zero additional rows.

    Returns the number of EXPIRE rows actually written.

    A single failed lot in a multi-lot batch still rolls back, logs and continues
    (C-1, unchanged); when EVERY *processed* lot failed this raises
    ``CoopExpirySystemicFailure`` instead of returning 0 (D4). ``remaining == 0``
    skips are excluded from BOTH sides of that predicate.
    """
    now = datetime.now(timezone.utc)
    # Plain tuples, not ORM instances: the per-lot commit below would expire ORM
    # objects, and re-reading an expired attribute mid-loop is a lazy refresh on
    # an async session (an error at best, a refresh on an invalidated connection
    # at worst). Snapshotting every field the loop needs removes the class.
    lapsed = (
        await db.execute(
            select(
                CreditLedgerEntry.id,
                CreditLedgerEntry.site_id,
                CreditLedgerEntry.spendable_at,
                CreditLedgerEntry.expires_at,
            ).where(
                CreditLedgerEntry.entry_type == "ACCRUE",
                CreditLedgerEntry.expires_at.is_not(None),
                CreditLedgerEntry.expires_at <= now,
            )
        )
    ).all()

    written = 0
    attempted = skipped = failures = 0
    for lot_id, lot_site_id, lot_spendable_at, lot_expires_at in lapsed:
        # BEFORE the try (D4): the skip lives INSIDE it, so incrementing after
        # it would leave a pre-insert failure counted in `failures`, never in
        # `attempted` — re-opening the silent-sweep hole.
        attempted += 1
        # Snapshot BEFORE the try: if the failing statement is the commit itself,
        # touching lot state inside the except can trigger a lazy refresh on an
        # invalidated connection and RAISE INSIDE THE HANDLER — skipping both the
        # rollback and the continue, aborting the loop, and leaving the session in
        # exactly the aborted state this block exists to prevent (which then
        # defeats the caller's finally-unlock).
        lot_id_str = str(lot_id)
        try:
            remaining = max(0, await _lot_remaining(db, lot_id))
            if remaining == 0:
                skipped += 1
                continue
            result = await db.execute(
                text(_EXPIRE_INSERT_SQL),
                {
                    "new_id": uuid.uuid4(),
                    "site_id": lot_site_id,
                    "amount": -remaining,
                    "lot_id": lot_id,
                    "lot_spendable_at": lot_spendable_at,
                    "lot_expires_at": lot_expires_at,
                },
            )
            await db.commit()
            written += result.rowcount or 0
        except Exception:  # noqa: BLE001 — one bad lot must not wedge the sweep
            await db.rollback()
            logger.exception("coop_expire_lot_failed", lot_id=lot_id_str)
            failures += 1
            continue

    processed = attempted - skipped
    if processed >= 1 and failures == processed:
        logger.error(
            "coop_expiry_all_lots_failed", processed=processed, skipped=skipped
        )
        raise CoopExpirySystemicFailure(
            f"all {processed} processed lot(s) failed to expire — systemic cause "
            "likely (missing uq_coop_ledger_expire_per_lot, dead session, or an "
            "exhausted connection pool). Refusing to report a silent success."
        )

    return written
