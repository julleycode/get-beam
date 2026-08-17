"""DE-2 / DE-11 / DE-12 — migration truth against a disposable container.

The shared lane builds its schema with ``Base.metadata.create_all``, so a model
that declares an index the migration never creates is UNDETECTABLE there: the
model IS the schema under test. Everything here runs against a schema built by
``alembic upgrade head`` and nothing else.

Mutation probe for DE-2 (mandatory): delete ``op.create_index(
"uq_coop_ledger_expire_per_lot", ...)`` from ``b7e4d21a9c58`` and re-run — both
the ``pg_indexes`` leg and the behavioural duplicate-rejection leg must go RED.
"""

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from tests.e2e_disposable.conftest import alembic_or_raise, live_head

pytestmark = pytest.mark.disposable

# Chained directly below b7e4d21a9c58 (add_coop_expire_unique).
_PRE_EXPIRE_UNIQUE = "a8c2f47e91b6"
_EXPIRE_UNIQUE = "b7e4d21a9c58"

_INSERT_LEDGER = text(
    """
    INSERT INTO identity_credit_ledger (id, site_id, entry_type, amount, reason, lot_id)
    VALUES (:id, :site_id, :entry_type, :amount, :reason, :lot_id)
    """
)


async def _index_exists(conn, name: str) -> bool:
    row = await conn.execute(
        text("SELECT 1 FROM pg_indexes WHERE indexname = :n"), {"n": name}
    )
    return row.scalar() is not None


async def _current_revision(conn) -> str | None:
    row = await conn.execute(text("SELECT version_num FROM alembic_version"))
    return row.scalar()


# ── DE-2 ──────────────────────────────────────────────────────────────────────


async def test_de2_coop_indexes_exist_after_alembic_upgrade(
    disposable_engine, disposable_schema
):
    """Both coop unique indexes are created by MIGRATIONS, not by the ORM."""
    assert disposable_schema, "schema build must return a head revision"
    async with disposable_engine.connect() as conn:
        assert await _index_exists(conn, "uq_coop_ledger_expire_per_lot")
        assert await _index_exists(conn, "uq_coop_accrued_site_email")


async def test_de2_expire_unique_rejects_duplicate_behaviourally(
    disposable_engine, clean_coop
):
    """Presence in pg_indexes is not enough — prove it actually rejects."""
    lot = uuid.uuid4()
    async with disposable_engine.begin() as conn:
        await conn.execute(
            _INSERT_LEDGER,
            {
                "id": lot,
                "site_id": "de2",
                "entry_type": "ACCRUE",
                "amount": 1,
                "reason": "contribution",
                "lot_id": lot,
            },
        )
        await conn.execute(
            _INSERT_LEDGER,
            {
                "id": uuid.uuid4(),
                "site_id": "de2",
                "entry_type": "EXPIRE",
                "amount": -1,
                "reason": "lot_expired",
                "lot_id": lot,
            },
        )

    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        async with disposable_engine.begin() as conn:
            await conn.execute(
                _INSERT_LEDGER,
                {
                    "id": uuid.uuid4(),
                    "site_id": "de2",
                    "entry_type": "EXPIRE",
                    "amount": -1,
                    "reason": "lot_expired",
                    "lot_id": lot,
                },
            )


async def test_de2_accrued_site_email_rejects_duplicate_behaviourally(
    disposable_engine, clean_coop
):
    from sqlalchemy.exc import IntegrityError

    ins = text(
        """
        INSERT INTO identity_contribution_events
            (id, site_id, email_bidx, contributed_on, accrued)
        VALUES (:id, :site_id, :bidx, :day, TRUE)
        """
    )
    async with disposable_engine.begin() as conn:
        await conn.execute(
            ins,
            {
                "id": uuid.uuid4(),
                "site_id": "de2b",
                "bidx": "b" * 64,
                "day": dt.date(2026, 8, 17),
            },
        )
    with pytest.raises(IntegrityError):
        async with disposable_engine.begin() as conn:
            await conn.execute(
                ins,
                {
                    "id": uuid.uuid4(),
                    "site_id": "de2b",
                    "bidx": "b" * 64,
                    # different day, same (site, email) — still one credit
                    "day": dt.date(2026, 8, 18),
                },
            )


# ── DE-11 / DE-12 — migration on a NON-EMPTY database ─────────────────────────


@pytest.fixture
async def at_pre_expire_unique(disposable_engine, disposable_dsn, clean_coop):
    """Downgrade below b7e4d21a9c58, then ALWAYS restore `upgrade head` (C-11).

    `disposable_schema` builds ONCE per session, so a test that leaves the DB
    downgraded would silently strip `uq_coop_ledger_expire_per_lot` from every
    later test — turning DE-2/DE-9b/DE-10-shaped assertions vacuous. The restore
    is stated here explicitly and never left to collection order.
    """
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


async def test_de11_migration_aborts_cleanly_on_violating_rows(
    disposable_engine, disposable_dsn, at_pre_expire_unique
):
    """Two EXPIRE rows on one lot exist BEFORE the unique index is added.

    The upgrade must fail and leave NO partial state: index absent, rows intact,
    alembic_version unchanged.
    """
    lot = uuid.uuid4()
    async with disposable_engine.begin() as conn:
        for entry_type, amount in (("ACCRUE", 1), ("EXPIRE", -1), ("EXPIRE", -1)):
            await conn.execute(
                _INSERT_LEDGER,
                {
                    "id": uuid.uuid4(),
                    "site_id": "de11",
                    "entry_type": entry_type,
                    "amount": amount,
                    "reason": "seed",
                    "lot_id": lot,
                },
            )

    with pytest.raises(RuntimeError) as exc:
        alembic_or_raise(disposable_dsn, "upgrade", "head")
    assert "uq_coop_ledger_expire_per_lot" in str(exc.value) or "unique" in str(
        exc.value
    ).lower()

    async with disposable_engine.connect() as conn:
        assert not await _index_exists(conn, "uq_coop_ledger_expire_per_lot")
        assert await _current_revision(conn) == _PRE_EXPIRE_UNIQUE
        rows = await conn.execute(
            text(
                "SELECT count(*) FROM identity_credit_ledger "
                "WHERE lot_id = :l AND entry_type = 'EXPIRE'"
            ),
            {"l": lot},
        )
        assert rows.scalar() == 2, "violating rows must be untouched"


async def test_de12_populated_but_valid_db_migrates_cleanly(
    disposable_engine, disposable_dsn, at_pre_expire_unique
):
    """Legitimate data (one EXPIRE per lot) must NOT be rejected."""
    for i in range(3):
        lot = uuid.uuid4()
        async with disposable_engine.begin() as conn:
            for entry_type, amount in (("ACCRUE", 1), ("EXPIRE", -1)):
                await conn.execute(
                    _INSERT_LEDGER,
                    {
                        "id": uuid.uuid4(),
                        "site_id": f"de12-{i}",
                        "entry_type": entry_type,
                        "amount": amount,
                        "reason": "seed",
                        "lot_id": lot,
                    },
                )

    alembic_or_raise(disposable_dsn, "upgrade", "head")

    async with disposable_engine.connect() as conn:
        assert await _index_exists(conn, "uq_coop_ledger_expire_per_lot")
        assert await _current_revision(conn) == live_head(disposable_dsn)
        rows = await conn.execute(
            text("SELECT count(*) FROM identity_credit_ledger WHERE reason = 'seed'")
        )
        assert rows.scalar() == 6, "valid rows must survive the migration"
