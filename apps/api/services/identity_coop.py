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

from datetime import date, datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select
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

    NULL ``spendable_at`` / ``expires_at`` (SPEND and EXPIRE rows, which carry
    negative amounts) always count: a spend already happened and must not be
    filtered back into the balance.
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
