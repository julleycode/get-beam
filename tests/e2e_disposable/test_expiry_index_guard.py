"""G1/G2/G4/G5 — the F-B index guard and the D4 systemic abort, on real PG.

Index *absence* is structurally untestable in the shared lane (its schema comes
from ``Base.metadata.create_all``, and the ORM mirrors the partial unique index
at ``models/identity_coop.py:141``), so these gates have no other home.

COLD CACHE IS MANDATORY. ``coop_expiry_sweep._index_verified`` is PROCESS
lifetime: without the autouse ``_cold_index_cache`` fixture below, G2 (healthy
schema) poisons it True and G1 then returns early — G1 would go RED for the
wrong reason and its mutation probe would be RED *before* the mutation,
recording a false non-vacuity proof. Every gate in this file assumes a cold
cache at entry.

``at_pre_expire_unique`` is copied from ``test_migration_truth.py:145-166``
(pattern, including the C-11 post-restore assertion) rather than promoted to
conftest, because the plan's Blast Radius mandates zero edits to existing test
files.
"""

import datetime as dt

import pytest
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.services import coop_expiry_sweep
from apps.api.services.coop_expiry_sweep import (
    CoopExpiryIndexMissing,
    run_coop_expiry_sweep,
)
from apps.api.services.identity_coop import CoopExpirySystemicFailure
from tests.e2e_disposable.conftest import (
    alembic_or_raise,
    expire_row_count,
    seed_lapsed_lot,
)
from tests.e2e_disposable.test_migration_truth import (
    _PRE_EXPIRE_UNIQUE,
    _index_exists,
)

pytestmark = pytest.mark.disposable


@pytest.fixture(autouse=True)
def _cold_index_cache(monkeypatch):
    """Every test starts with a COLD positive cache. See the module docstring."""
    monkeypatch.setattr(coop_expiry_sweep, "_index_verified", False)


@pytest.fixture
async def at_pre_expire_unique(disposable_engine, disposable_dsn, clean_coop):
    """Downgrade below b7e4d21a9c58, then ALWAYS restore `upgrade head` (C-11)."""
    alembic_or_raise(disposable_dsn, "downgrade", _PRE_EXPIRE_UNIQUE)
    async with disposable_engine.connect() as conn:
        assert not await _index_exists(conn, "uq_coop_ledger_expire_per_lot")
    try:
        yield
    finally:
        async with disposable_engine.begin() as conn:
            await conn.execute(text("DELETE FROM identity_credit_ledger"))
        alembic_or_raise(disposable_dsn, "upgrade", "head")
        async with disposable_engine.connect() as conn:
            assert await _index_exists(conn, "uq_coop_ledger_expire_per_lot"), (
                "C-11 restore failed — later tests in this session would be vacuous"
            )


async def _seed(engine, site_id: str, amount: int = 1):
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    async with engine.begin() as conn:
        return await seed_lapsed_lot(
            conn,
            site_id,
            expires_at=past,
            spendable_at=past - dt.timedelta(days=1),
            amount=amount,
        )


# ── G1 — the guard FIRES when the index is absent ─────────────────────────────


async def test_g1_guard_raises_and_writes_nothing_when_index_absent(
    disposable_engine, at_pre_expire_unique
):
    """AC-1. Mutation probes (both mandatory, both must go RED):
      1. delete `await assert_expire_index(db)` -> D4 raises the SIBLING type
         `CoopExpirySystemicFailure` and `coop_expiry_index_missing` is absent;
      2. delete that line AND `failures += 1` -> returns 0 (the true pre-fix
         silent behaviour) -> "did not raise".
    The log assertion is load-bearing: with D4 in place, "something raised" no
    longer distinguishes the guard from the systemic abort.
    """
    lot = await _seed(disposable_engine, "g1")
    factory = async_sessionmaker(disposable_engine, class_=AsyncSession)
    with structlog.testing.capture_logs() as logs:
        async with factory() as db:
            with pytest.raises(CoopExpiryIndexMissing):
                await run_coop_expiry_sweep(db)

    assert "coop_expiry_index_missing" in [e.get("event") for e in logs], (
        "the raise must come from the GUARD, not from some other failure"
    )
    async with disposable_engine.connect() as conn:
        assert await expire_row_count(conn, lot) == 0


# ── G2 — the guard does NOT fire on a healthy schema ──────────────────────────


async def test_g2_healthy_schema_is_unchanged_and_idempotent(
    disposable_engine, clean_coop
):
    """AC-2. RED when the pg_indexes predicate is wrong or its branches flipped."""
    lot = await _seed(disposable_engine, "g2", amount=7)
    factory = async_sessionmaker(disposable_engine, class_=AsyncSession)
    async with factory() as db:
        assert await run_coop_expiry_sweep(db) == 1
    async with disposable_engine.connect() as conn:
        assert await expire_row_count(conn, lot) == 1
        amount = (
            await conn.execute(
                text(
                    "SELECT amount FROM identity_credit_ledger "
                    "WHERE lot_id = :l AND entry_type = 'EXPIRE'"
                ),
                {"l": lot},
            )
        ).scalar()
        assert amount == -7

    async with factory() as db:  # idempotence preserved
        assert await run_coop_expiry_sweep(db) == 0
    async with disposable_engine.connect() as conn:
        assert await expire_row_count(conn, lot) == 1


# ── G4 — the two layers are independent ───────────────────────────────────────


async def test_g4_systemic_abort_fires_with_the_guard_neutralised(
    disposable_engine, at_pre_expire_unique, monkeypatch
):
    """AC-4. The guard is no-op'd at a NAMED site, so only D4 can raise.

    Asserting the exception TYPE is what catches a wrong patch site (a
    mis-patched guard raises the sibling `CoopExpiryIndexMissing` -> RED).
    Mandatory mutation probe: remove `failures += 1` -> MUST go RED.
    """

    async def _noop(db):
        return None

    monkeypatch.setattr(coop_expiry_sweep, "assert_expire_index", _noop)

    await _seed(disposable_engine, "g4a")
    await _seed(disposable_engine, "g4b")
    factory = async_sessionmaker(disposable_engine, class_=AsyncSession)
    with structlog.testing.capture_logs() as logs:
        async with factory() as db:
            with pytest.raises(CoopExpirySystemicFailure):
                await run_coop_expiry_sweep(db)

    assert "coop_expiry_all_lots_failed" in [e.get("event") for e in logs]


# ── G5 — no scheduler wedge, and the miss is not cached ───────────────────────


async def test_g5a_wrapper_swallows_the_guard_raise(
    disposable_dsn, at_pre_expire_unique, coop_on
):
    """AC-5 leg (a). E3: the wrapper takes its session from scheduler's OWN
    module-level `async_session`, a binding no other gate here uses — assert it
    resolves to the disposable DSN before invoking it (an unpinned DATABASE_URL
    reaches Supabase PROD in this repo).

    Both events are required: `coop_expiry_index_missing` proves the guard fired
    (not that the flag failed to take, not that the guard was deleted), and
    `coop_expiry_sweep_crashed` proves the wrapper caught it rather than
    short-circuiting at its `if not settings.identity_coop_enabled: return`.
    """
    from apps.api.jobs import scheduler

    bound = str(scheduler.async_session.kw["bind"].url)
    assert str(disposable_dsn.rsplit("@", 1)[-1]) in bound, (
        f"scheduler.async_session is bound to {bound!r}, NOT the disposable DSN — "
        "refusing to run a real sweep against an unknown database"
    )

    try:
        with structlog.testing.capture_logs() as logs:
            await scheduler._coop_expiry_sweep_job()  # must return normally
    finally:
        # This is the only test in the lane that touches the app's GLOBAL engine
        # from its own event loop. Leaving a pooled asyncpg connection bound to
        # this (about-to-close) loop makes the next file's global-session test
        # die with "Event loop is closed" — measured: DE-3 went red exactly this
        # way. Disposing here keeps the pollution inside this test.
        from apps.api.models import database

        await database.engine.dispose()

    events = [e.get("event") for e in logs]
    assert "coop_expiry_index_missing" in events
    assert "coop_expiry_sweep_crashed" in events


async def test_g5b_negative_result_is_not_cached_so_the_guard_self_heals(
    disposable_engine, disposable_dsn, at_pre_expire_unique
):
    """AC-5 leg (b). RED if the miss is cached: the post-upgrade call keeps raising."""
    lot = await _seed(disposable_engine, "g5b")
    factory = async_sessionmaker(disposable_engine, class_=AsyncSession)
    async with factory() as db:
        with pytest.raises(CoopExpiryIndexMissing):
            await run_coop_expiry_sweep(db)
        await db.rollback()  # release any lock before the DDL below

    alembic_or_raise(disposable_dsn, "upgrade", "head")

    async with factory() as db:
        assert await run_coop_expiry_sweep(db) == 1, (
            "same process, index restored — a cached MISS would still raise"
        )
    async with disposable_engine.connect() as conn:
        assert await expire_row_count(conn, lot) == 1
