"""Identity co-op Phase 2a — consumption aggregation + FIFO lot expiry (needs Postgres).

identity-coop Phase 2a (visitors-identity). Covers the gates that only a real
Postgres can prove:

- G-3   per-live-site consumption count; the `provider` AND `site_id` predicates
- G-9   AC-8 ledger reconciliation over >=200 randomized ops, zero drift
- G-17  naive/aware bound normalization + exact in-window count
- G-18  expiry never negative — five mandatory legs incl. the positive leg
- G-19  erased-row exclusion with a non-zero pre-exclusion guard
- G-20  the sweep ENTRYPOINT: lock-release post-condition + forward progress
- G-21  duplicate EXPIRE rejected at the DB tier by uq_coop_ledger_expire_per_lot
- G-22  contribution_count honours excluded_reason
- G-23a spendable_lots FIFO ordering + drawn subtraction

Precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis`.

**Every consumption gate here seeds the `identified_visitors` side of the A2 join
and asserts a NON-ZERO count.** A2's join is INNER: a row with no matching
identity is dropped BEFORE any predicate is evaluated, so an `api_usage_logs`-only
fixture collapses to 0 and a `return 0` stub passes every predicate the fixture
was built to force. Every identity row is ORM-created with a real `email=` value
so the `_sync_identity_pii` before_insert hook populates a non-NULL `email_bidx`;
a NULL `email_bidx` is filtered out by the erasure `NOT IN` under three-valued
logic, which re-vacuums the fixture through a subtler door.
"""

import random
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from apps.api.config import settings
from apps.api.models.api_usage import ApiUsageLog
from apps.api.models.identity_coop import ContributionEvent, CreditLedgerEntry
from apps.api.models.suppression import SuppressionEntry
from apps.api.models.visitor import IdentifiedVisitor
from apps.api.services import identity_coop as coop
from apps.api.services.pii_crypto import email_hash

pytestmark = pytest.mark.integration


# ──────────────────────────────── seeding helpers ────────────────────────────────


def _usage(
    site_id,
    visitor_id,
    provider,
    *,
    category="identity",
    success=True,
    cost_usd=0.0,
    created_at=None,
) -> ApiUsageLog:
    return ApiUsageLog(
        site_id=site_id,
        visitor_id=visitor_id,
        provider=provider,
        category=category,
        success=success,
        cost_usd=cost_usd,
        created_at=created_at or datetime.now(timezone.utc).replace(tzinfo=None),
    )


def _identity(site_id: str, visitor_id: str, email: str) -> IdentifiedVisitor:
    """ORM-created so `_sync_identity_pii` populates a non-NULL `email_bidx`.

    The real `email=` value is mandatory, not cosmetic: the hook writes
    `email_bidx = NULL` for a falsy email, and A2's `NOT IN` then drops the row.
    """
    return IdentifiedVisitor(site_id=site_id, visitor_id=visitor_id, email=email)


def _accrue(site_id: str, amount: int, *, spendable_at, expires_at) -> CreditLedgerEntry:
    return CreditLedgerEntry(
        site_id=site_id,
        entry_type="ACCRUE",
        amount=amount,
        reason="contribution",
        spendable_at=spendable_at,
        expires_at=expires_at,
    )


async def _add_lot(db, site_id: str, amount: int, *, lapsed: bool) -> CreditLedgerEntry:
    """Insert one ACCRUE lot (its own lot_id), lapsed or live."""
    now = datetime.now(timezone.utc)
    lot = _accrue(
        site_id,
        amount,
        spendable_at=now - timedelta(hours=2),
        expires_at=now - timedelta(minutes=1) if lapsed else now + timedelta(days=30),
    )
    db.add(lot)
    await db.flush()
    lot.lot_id = lot.id
    await db.commit()
    return lot


async def _expire_rows(db, lot_id) -> list[CreditLedgerEntry]:
    return list(
        (
            await db.execute(
                select(CreditLedgerEntry).where(
                    CreditLedgerEntry.lot_id == lot_id,
                    CreditLedgerEntry.entry_type == "EXPIRE",
                )
            )
        )
        .scalars()
        .all()
    )


async def seed_api_usage_logs(db, site_id: str, n: int, *, providers: list[str]) -> None:
    """Bulk-seed `api_usage_logs` (+ the joinable identity side) for G-4's EXPLAIN.

    TWO bulk statements, both raw `INSERT ... SELECT generate_series(...)`. A
    100k-row ORM loop is not an acceptable substitute — that is the failure mode
    this helper exists to avoid.

    >=50% of rows land on `site_id` and each of those has a matching
    `identified_visitors` row, so the A2 join path is genuinely exercised rather
    than joining against an empty relation.

    Both statements BYPASS the `_sync_identity_pii` mapper hook, so the seeded
    `email_bidx` is NULL. That is accepted and harmless: G-4 is an EXPLAIN-shape
    gate, not a correctness gate, and A2's erased-row semantics are proven against
    ORM-created rows by G-19.
    """
    provider_sql = ", ".join(f"'{p}'" for p in providers)
    await db.execute(
        text(
            f"""
            INSERT INTO api_usage_logs
                (id, site_id, visitor_id, provider, category, success, cost_usd, created_at)
            SELECT gen_random_uuid(),
                   CASE WHEN i % 2 = 0 THEN :site_id ELSE 'site_other_' || (i % 7) END,
                   'v-seed-' || i,
                   (ARRAY[{provider_sql}])[1 + (i % {len(providers)})],
                   'identity', true, 0.0,
                   now() - (i || ' seconds')::interval
            FROM generate_series(1, :n) AS i
            """
        ),
        {"site_id": site_id, "n": n},
    )
    await db.execute(
        text(
            """
            INSERT INTO identified_visitors
                (id, site_id, visitor_id, email, do_not_email)
            SELECT gen_random_uuid(), :site_id, 'v-seed-' || i,
                   'seed' || i || '@example.com', false
            FROM generate_series(2, :n, 2) AS i
            """
        ),
        {"site_id": site_id, "n": n},
    )
    await db.commit()


# ───────────────────────── D1 / G-3 — consumption count ─────────────────────────


@pytest.mark.asyncio
async def test_coop_consumption_count_per_live_site(test_db):
    """G-3: exactly the graph-served rows of THIS site, and only those.

    Five `api_usage_logs` rows, each excluded (or not) by a different predicate:

    (a) beam_identity_network, probed site       -> COUNTED
    (b) paid provider, cost_usd > 0, probed site -> excluded by `provider`
    (c) form_capture (the nearest confusable —   -> excluded by `provider`
        another OWNED_FREE_PROVIDER, also
        category='identity' with cost_usd=0.0)
    (d) beam_identity_network, SECOND site       -> excluded by `site_id`
    (e) beam_identity_network, site_id = NULL    -> visitor_id-only-join guard

    Rows (b) and (c) share row (a)'s site_id AND visitor_id so they are JOINABLE
    (E-10). An unjoinable (b)/(c) is dropped by the INNER join before the
    `provider` predicate is ever evaluated and therefore forces nothing — a
    provider-less or cost_usd-based implementation would still return 1 and pass.
    Row (d) carries its OWN identity row on site 2, which is what makes it visible
    to an unscoped count (2 != 1) and thus forces the `site_id` predicate.

    Row (e) can NEVER equi-join (`IdentifiedVisitor.site_id`/`.visitor_id` are both
    nullable=False), so it is not tenant-scoping proof. It is retained solely as a
    guard against a `visitor_id`-ALONE join, which would match it against site 1's
    identity row and inflate the count.
    """
    site1, site2 = "site_coop_cons_1", "site_coop_cons_2"
    v1, v2 = "v-cons-1", "v-cons-2"

    test_db.add_all(
        [
            _identity(site1, v1, "cons.one@example.com"),
            _identity(site2, v2, "cons.two@example.com"),
        ]
    )
    test_db.add_all(
        [
            _usage(site1, v1, "beam_identity_network"),                    # (a)
            _usage(site1, v1, "people_data_labs", cost_usd=0.02),          # (b)
            _usage(site1, v1, "form_capture"),                            # (c)
            _usage(site2, v2, "beam_identity_network"),                    # (d)
            _usage(None, v1, "beam_identity_network"),                     # (e)
        ]
    )
    await test_db.commit()

    assert await coop.consumption_count(test_db, site1) == 1
    # Symmetric: site 2 sees its own single row and nothing of site 1's.
    assert await coop.consumption_count(test_db, site2) == 1


# ───────────────────────── D2 / G-17 — tz bound handling ─────────────────────────


@pytest.mark.asyncio
async def test_coop_consumption_naive_tz_bounds(test_db):
    """G-17: identical counts for aware vs naive bounds, AND an exact in-window count.

    The identical-counts leg alone is satisfied trivially by an implementation
    that ignores `since`/`until` entirely — equally wrong on both sides — so the
    exact-count leg is mandatory. Phase 2b's monthly-allowance math consumes
    exactly these windows.

    asyncpg RAISES when a tz-aware value is bound to a `TIMESTAMP WITHOUT TIME
    ZONE` column, so an un-normalized implementation most likely errors rather
    than silently shifting the window; both shapes are failures here.
    """
    site, vid = "site_coop_tz", "v-tz-1"
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    since_naive = now_naive - timedelta(days=2)
    until_naive = now_naive - timedelta(hours=1)

    test_db.add(_identity(site, vid, "tz.one@example.com"))
    test_db.add_all(
        [
            # just OUTSIDE the lower bound
            _usage(site, vid, "beam_identity_network", created_at=since_naive - timedelta(hours=3)),
            # just INSIDE the lower bound
            _usage(site, vid, "beam_identity_network", created_at=since_naive + timedelta(hours=3)),
            # just INSIDE the upper bound
            _usage(site, vid, "beam_identity_network", created_at=until_naive - timedelta(hours=3)),
            # just OUTSIDE the upper bound
            _usage(site, vid, "beam_identity_network", created_at=until_naive + timedelta(hours=3)),
        ]
    )
    await test_db.commit()

    # Non-zero pre-guard: without it the exact-count leg could pass on an empty
    # effective fixture.
    assert await coop.consumption_count(test_db, site) == 4

    naive = await coop.consumption_count(
        test_db, site, since=since_naive, until=until_naive
    )
    aware = await coop.consumption_count(
        test_db,
        site,
        since=since_naive.replace(tzinfo=timezone.utc),
        until=until_naive.replace(tzinfo=timezone.utc),
    )
    assert naive == 2
    assert aware == naive


# ───────────────────── D9 / G-19 — erased-row exclusion (A2/A5) ─────────────────────


@pytest.mark.asyncio
async def test_coop_erased_row_excluded_from_consumption(test_db):
    """G-19: an erased identity's consumption stops being counted."""
    site = "site_coop_erased"
    erased_email = "erased.person@example.com"

    test_db.add_all(
        [
            _identity(site, "v-erased", erased_email),
            _identity(site, "v-kept", "kept.person@example.com"),
        ]
    )
    test_db.add_all(
        [
            _usage(site, "v-erased", "beam_identity_network"),
            _usage(site, "v-kept", "beam_identity_network"),
        ]
    )
    await test_db.commit()

    # Non-zero pre-exclusion guard — the leg cannot pass on an empty fixture.
    assert await coop.consumption_count(test_db, site) == 2

    test_db.add(SuppressionEntry(email_hash=email_hash(erased_email), scope="erased"))
    await test_db.commit()

    assert await coop.consumption_count(test_db, site) == 1


# ────────────────── D11 / G-22 — contribution_count excluded_reason ──────────────────


@pytest.mark.asyncio
async def test_coop_contribution_count_excludes_excluded_reason(test_db):
    """G-22: an excluded event never earned a credit, so it is not contribution."""
    site = "site_coop_contrib"
    today = datetime.now(timezone.utc).date()

    test_db.add_all(
        [
            ContributionEvent(
                site_id=site,
                email_bidx=email_hash("good@example.com"),
                contributed_on=today,
                accrued=True,
                excluded_reason=None,
            ),
            ContributionEvent(
                site_id=site,
                email_bidx=email_hash("dupe@example.com"),
                contributed_on=today,
                accrued=False,
                excluded_reason="duplicate",
            ),
        ]
    )
    await test_db.commit()

    assert await coop.contribution_count(test_db, site) == 1


# ───────────────── D12 / G-23a — FIFO ordering + drawn subtraction ─────────────────


@pytest.mark.asyncio
async def test_coop_spendable_lots_fifo_order_and_drawn_subtraction(test_db):
    """G-23a: oldest-expiring lot first, and drawn amounts really subtract.

    The three lots are inserted deliberately OUT of expiry order, so an
    implementation that returns insertion order (or any stable-but-wrong order)
    fails. A FIFO bug would otherwise surface first in Phase 2b's draw.
    """
    site = "site_coop_fifo"
    now = datetime.now(timezone.utc)
    past = now - timedelta(hours=2)

    # Inserted middle, latest, earliest — never in expiry order.
    lots = [
        _accrue(site, 10, spendable_at=past, expires_at=now + timedelta(days=20)),
        _accrue(site, 20, spendable_at=past, expires_at=now + timedelta(days=30)),
        _accrue(site, 30, spendable_at=past, expires_at=now + timedelta(days=10)),
    ]
    test_db.add_all(lots)
    await test_db.flush()
    for lot in lots:
        lot.lot_id = lot.id
    await test_db.commit()

    # Partially draw the middle-expiring lot (amount 10, expires in 20 days).
    drawn_lot = lots[0]
    test_db.add(
        CreditLedgerEntry(
            site_id=site,
            entry_type="SPEND",
            amount=-4,
            reason="spend",
            lot_id=drawn_lot.id,
            spendable_at=drawn_lot.spendable_at,
            expires_at=drawn_lot.expires_at,
        )
    )
    await test_db.commit()

    result = await coop.spendable_lots(test_db, site)
    assert [lot.expires_at for lot in result] == sorted(
        lot.expires_at for lot in result
    )
    assert [lot.amount for lot in result] == [30, 10, 20]
    remaining = {lot.amount: lot.remaining for lot in result}
    assert remaining == {30: 30, 10: 6, 20: 20}


# ───────────────────────── D6 — hold window excludes a lot ─────────────────────────


@pytest.mark.asyncio
async def test_coop_hold_window_blocks_spend(test_db):
    """A lot inside its 24h provisional hold is neither listed nor counted."""
    site = "site_coop_hold"
    now = datetime.now(timezone.utc)
    lot = _accrue(
        site,
        11,
        spendable_at=now + timedelta(hours=5),
        expires_at=now + timedelta(days=30),
    )
    test_db.add(lot)
    await test_db.flush()
    lot.lot_id = lot.id
    await test_db.commit()

    assert await coop.spendable_lots(test_db, site) == []
    assert await coop.spendable_balance(test_db, site) == 0


# ─────────────── D3 — expired credit excluded AND an EXPIRE row explains it ───────────────


@pytest.mark.asyncio
async def test_coop_expired_credit_excluded_and_expiry_row_written(test_db):
    """AC-7: the lot is unspendable immediately, and the sweep records WHY."""
    site = "site_coop_expired"
    lot = await _add_lot(test_db, site, 5, lapsed=True)

    # Read-time backstop: unspendable before any sweep has run.
    assert await coop.spendable_balance(test_db, site) == 0

    assert await coop.expire_lapsed_lots(test_db) == 1

    rows = await _expire_rows(test_db, lot.id)
    assert len(rows) == 1
    assert rows[0].amount == -5
    assert rows[0].reason == "lot_expired"
    # The stamped EXPIRE is balance-invisible — it leaves the window with its lot.
    assert await coop.spendable_balance(test_db, site) == 0


# ───────────────────────────── D4 — sweep idempotence ─────────────────────────────


@pytest.mark.asyncio
async def test_coop_expiry_sweep_is_idempotent(test_db):
    """Re-running writes ZERO additional rows (idempotent at N=1, not at N=0)."""
    site = "site_coop_idem"
    lot = await _add_lot(test_db, site, 7, lapsed=True)

    assert await coop.expire_lapsed_lots(test_db) == 1
    assert await coop.expire_lapsed_lots(test_db) == 0
    assert len(await _expire_rows(test_db, lot.id)) == 1


# ─────────────────────── D7 / G-18 — expiry never negative (5 legs) ───────────────────────


@pytest.mark.asyncio
async def test_coop_expiry_never_negative(test_db):
    """G-18: five mandatory legs. Legs 1-4 alone pass on a sweep that never fires."""
    now = datetime.now(timezone.utc)

    # ── Leg 5 (the POSITIVE leg) — the only assertion a never-firing sweep fails.
    site5 = "site_coop_g18_positive"
    lot5 = await _add_lot(test_db, site5, 12, lapsed=True)

    # ── Leg 1 — fully unspent lapsed lot.
    site1 = "site_coop_g18_unspent"
    lot1 = await _add_lot(test_db, site1, 8, lapsed=True)

    # ── Leg 2 — partially spent lapsed lot (SPEND seeded directly; spend_credits
    #    does not exist until Phase 2b).
    site2 = "site_coop_g18_partial"
    lot2 = await _add_lot(test_db, site2, 10, lapsed=True)
    test_db.add(
        CreditLedgerEntry(
            site_id=site2,
            entry_type="SPEND",
            amount=-4,
            reason="spend",
            lot_id=lot2.id,
            spendable_at=lot2.spendable_at,
            expires_at=lot2.expires_at,
        )
    )
    await test_db.commit()

    # ── Leg 3 — a lot whose WINDOW-BLIND raw SUM has gone negative, plus a
    #    fully-drawn lot whose remaining is exactly 0.
    site3 = "site_coop_g18_negative"
    lot3 = await _add_lot(test_db, site3, 5, lapsed=True)
    lot3b = await _add_lot(test_db, site3, 5, lapsed=True)
    test_db.add_all(
        [
            CreditLedgerEntry(
                site_id=site3, entry_type="SPEND", amount=-8, reason="spend",
                lot_id=lot3.id, spendable_at=lot3.spendable_at, expires_at=lot3.expires_at,
            ),
            CreditLedgerEntry(
                site_id=site3, entry_type="SPEND", amount=-5, reason="spend",
                lot_id=lot3b.id, spendable_at=lot3b.spendable_at, expires_at=lot3b.expires_at,
            ),
        ]
    )
    await test_db.commit()

    written = await coop.expire_lapsed_lots(test_db)
    # Legs 1, 2 and 5 each produce exactly one row; leg 3's two lots are skipped.
    assert written == 3

    # Leg 5 assertions — exactly ONE row, amount == -N, correct lot/site/stamps.
    rows5 = await _expire_rows(test_db, lot5.id)
    assert len(rows5) == 1
    assert rows5[0].amount == -12
    assert rows5[0].site_id == site5
    assert rows5[0].lot_id == lot5.id
    assert rows5[0].spendable_at == lot5.spendable_at
    assert rows5[0].expires_at == lot5.expires_at
    # Idempotent at N=1, not at N=0.
    assert await coop.expire_lapsed_lots(test_db) == 0
    assert len(await _expire_rows(test_db, lot5.id)) == 1

    # Leg 1 — never -N.
    assert await coop.spendable_balance(test_db, site1) == 0
    assert (await _expire_rows(test_db, lot1.id))[0].amount == -8

    # Leg 2 — the unspent remainder is expired, balance exactly 0.
    assert await coop.spendable_balance(test_db, site2) == 0
    assert (await _expire_rows(test_db, lot2.id))[0].amount == -6

    # Leg 3 — no positive EXPIRE anywhere, and the two skipped lots wrote NOTHING.
    #   `amount < 0` (not `<= 0`): a broken skip writing `-max(0, 0) = 0` rows is
    #   balance-invisible under the stamping rule and would pass `<= 0`.
    all_expire = list(
        (
            await test_db.execute(
                select(CreditLedgerEntry).where(
                    CreditLedgerEntry.entry_type == "EXPIRE"
                )
            )
        )
        .scalars()
        .all()
    )
    assert all_expire
    assert all(row.amount < 0 for row in all_expire)
    assert await _expire_rows(test_db, lot3.id) == []
    assert await _expire_rows(test_db, lot3b.id) == []
    assert await coop.spendable_balance(test_db, site3) == 0

    # ── Leg 4 — stamp assertion (above, on leg 5) + the NULL-stamp NEGATIVE
    #    CONTROL. Written by hand, NOT by the sweep: an unstamped EXPIRE row
    #    "always counts" and drives the balance to -(N-k). This is exactly the
    #    F-1 defect the stamping rule exists to close, so a `balance == 0`
    #    assertion that passes with NULL stamps would prove nothing.
    for row in all_expire:
        assert row.spendable_at is not None
        assert row.expires_at is not None

    site4 = "site_coop_g18_nullstamp"
    lot4 = await _add_lot(test_db, site4, 9, lapsed=True)
    test_db.add(
        CreditLedgerEntry(
            site_id=site4, entry_type="SPEND", amount=-3, reason="spend",
            lot_id=lot4.id, spendable_at=lot4.spendable_at, expires_at=lot4.expires_at,
        )
    )
    await test_db.commit()
    await test_db.execute(
        text(
            """
            INSERT INTO identity_credit_ledger
                (id, site_id, entry_type, amount, lot_id, reason,
                 spendable_at, expires_at, created_at)
            VALUES (:id, :site_id, 'EXPIRE', -6, :lot_id, 'lot_expired',
                    NULL, NULL, now())
            """
        ),
        {"id": uuid.uuid4(), "site_id": site4, "lot_id": lot4.id},
    )
    await test_db.commit()
    assert await coop.spendable_balance(test_db, site4) == -6

    assert now  # (kept: anchors the fixture clock for the reader)


# ─────────────── D8 / G-20 — the sweep ENTRYPOINT (lock release + progress) ───────────────


@pytest.mark.asyncio
async def test_coop_expiry_sweep_entrypoint_runs_twice(test_db):
    """G-20: two mandatory legs against `run_coop_expiry_sweep`, not the service fn.

    SINGLE-SESSION PRECONDITION (mandatory): every database operation in this test
    — both lot seeds, both sweep calls, the unlock probe and every count — goes
    through the ONE `test_db` session. Opening a second AsyncSession, a second
    engine, or doing a fresh-session read-back materializes a SECOND pooled
    connection and VOIDS leg (a): the probe would then run on a connection that
    never held the lock and return False unconditionally — a permanently-passing
    assertion. The fresh-session read-back pattern is endorsed elsewhere in this
    program for Phase 2b, so this trap is live.

    Do NOT "simplify" this to a same-`db` double call with a flat row count. PG
    advisory locks are RE-ENTRANT within a session, and a single-tasked test never
    populates the pool with more than one connection (this is NOT LIFO ordering —
    SQLAlchemy's pool defaults to FIFO), so call 2's `pg_try_advisory_lock` returns
    TRUE even after a leak. And a flat count cannot separate a CORRECT call 2
    (remaining == 0 -> skip -> 0 rows) from a LOCK-BLOCKED one (early return -> 0
    rows). That form was the cycle-2 vacuous-green FAIL.
    """
    from apps.api.services.coop_expiry_sweep import _LOCK_KEY, run_coop_expiry_sweep

    # KEY-DRIFT FORCING FUNCTION: `pg_advisory_unlock` on a key nobody holds
    # returns False — the PASSING value — so any drift between the implementation's
    # key and the probe's literal would make leg (a) pass forever, silently.
    assert _LOCK_KEY == "coop_expiry_sweep"

    site = "site_coop_sweep_entry"
    lot_one = await _add_lot(test_db, site, 4, lapsed=True)

    assert await run_coop_expiry_sweep(test_db) == 1

    # ── Leg (a): the lock-release POST-CONDITION. PG returns false (plus a
    #    warning) when the session holds nothing, so a LEAKED lock returns True.
    #    Scope note: this gates the post-condition only — an implementation that
    #    takes no lock at all also passes. It fails the defect it exists for: an
    #    acquire WITHOUT a release.
    held = (
        await test_db.execute(
            text("SELECT pg_advisory_unlock(hashtext('coop_expiry_sweep'))")
        )
    ).scalar()
    assert held is False

    # ── Leg (b): forward progress. A second lapsed lot seeded BEFORE call 2 must
    #    produce a second EXPIRE row; a wedged or inert entrypoint writes none.
    lot_two = await _add_lot(test_db, site, 6, lapsed=True)
    assert await run_coop_expiry_sweep(test_db) == 1

    total = (
        await test_db.execute(
            select(func.count())
            .select_from(CreditLedgerEntry)
            .where(CreditLedgerEntry.entry_type == "EXPIRE")
        )
    ).scalar_one()
    assert total == 2
    assert len(await _expire_rows(test_db, lot_one.id)) == 1
    assert len(await _expire_rows(test_db, lot_two.id)) == 1


# ─────────────── D10 / G-21 — duplicate EXPIRE rejected at the DB tier ───────────────


@pytest.mark.asyncio
async def test_coop_duplicate_expire_rejected_by_db(test_db):
    """G-21: the partial unique index, not service code, is the enforcement.

    Inserted via raw SQL, bypassing service code entirely (Phase 1 precedent for
    proving a DB-level constraint). Duplicates are BALANCE-INVISIBLE under the
    stamping rule, so no balance assertion at any tier could catch them — while
    Phase 3's dashboard, which omits the window predicate, would report 2N credits
    lost.
    """
    site = "site_coop_dupe_expire"
    lot = await _add_lot(test_db, site, 3, lapsed=True)

    insert = text(
        """
        INSERT INTO identity_credit_ledger
            (id, site_id, entry_type, amount, lot_id, reason,
             spendable_at, expires_at, created_at)
        VALUES (:id, :site_id, 'EXPIRE', -3, :lot_id, 'lot_expired',
                :sa, :ea, now())
        """
    )
    params = {
        "site_id": site,
        "lot_id": lot.id,
        "sa": lot.spendable_at,
        "ea": lot.expires_at,
    }
    await test_db.execute(insert, {"id": uuid.uuid4(), **params})
    await test_db.commit()

    with pytest.raises(IntegrityError) as exc:
        await test_db.execute(insert, {"id": uuid.uuid4(), **params})
        await test_db.commit()
    assert "uq_coop_ledger_expire_per_lot" in str(exc.value)
    await test_db.rollback()


# ───────────────────── D5 / G-9 — AC-8 exact reconciliation ─────────────────────


@pytest.mark.asyncio
async def test_coop_ledger_reconciles_exactly(test_db, monkeypatch):
    """AC-8: >=200 randomized accrue/expire ops, zero drift.

    ORACLE PRECONDITION (Constraint 13 — the oracle is NEVER unconditional):
    `spendable_balance` EXCLUDES held lots, so a fresh ACCRUE sits inside a raw
    SUM but outside the balance. Before every assert, `now` must be past EVERY
    lot's `spendable_at`. Both sanctioned mechanisms are used: the hold setting is
    monkeypatched to 0 for the whole function, and every lot is seeded with an
    explicitly past `spendable_at`.

    TWO independent expected values, because one is not enough:
      * a HARNESS-TRACKED running total, maintained in Python from the test's own
        intent and never from any repo query — an oracle sharing the lot-window
        predicate with the implementation is skewed identically by a wrong-window
        stamp and would stay green;
      * a raw SQL `SUM(amount)` oracle written here, independent of
        `spendable_balance`'s own helper.
    """
    monkeypatch.setattr(settings, "coop_credit_hold_hours", 0)

    site = "site_coop_reconcile"
    rng = random.Random(1337)
    expected = 0          # harness-tracked, from intent only
    live: list[tuple] = []  # (lot_id, amount)
    harness_checks = 0

    oracle_sql = text(
        """
        SELECT COALESCE(SUM(amount), 0) FROM identity_credit_ledger
        WHERE site_id = :site
          AND (spendable_at IS NULL OR spendable_at <= now())
          AND (expires_at IS NULL OR expires_at > now())
        """
    )

    for op_index in range(200):
        if not live or rng.random() < 0.6:
            amount = rng.randint(1, 9)
            lot = await _add_lot(test_db, site, amount, lapsed=False)
            live.append((lot.id, amount))
            expected += amount
        else:
            lot_id, amount = live.pop(rng.randrange(len(live)))
            # Lapse the lot, then let the sweep write its stamped EXPIRE row.
            await test_db.execute(
                text(
                    "UPDATE identity_credit_ledger SET expires_at = now() - interval '1 minute' "
                    "WHERE id = :id"
                ),
                {"id": lot_id},
            )
            await test_db.commit()
            await coop.expire_lapsed_lots(test_db)
            # ACCRUE and its stamped EXPIRE leave the window together -> net 0.
            expected -= amount

        balance = await coop.spendable_balance(test_db, site)
        assert balance == expected, f"drift at op {op_index}"
        harness_checks += 1

        oracle = int((await test_db.execute(oracle_sql, {"site": site})).scalar_one())
        assert oracle == balance, f"oracle drift at op {op_index}"

    assert harness_checks >= 50
    assert await coop.spendable_balance(test_db, site) == expected
