"""DE-18 — sweep scale at n = 10,000 lapsed lots.

The sweep selects EVERY lapsed lot globally — no site filter, no LIMIT, no
batching (identity_coop.py:563-576) — then does SELECT + INSERT + commit() PER
LOT (:588-602).

COUNTER SEMANTICS (E-2, load-bearing): SQLAlchemy's ``before_cursor_execute``
fires only for statements executed through the DBAPI **cursor**.
``session.commit()`` goes through the DBAPI connection's ``commit()`` (and
asyncpg's BEGIN through its transaction API), so **COMMIT IS INVISIBLE to that
counter**. The real counted shape is therefore ``1`` set-level SELECT + ``2`` per
lot = **2n + 1**, NOT 3n + 1.

That is why the hard FAIL is **2n + 10**, not 3n + 10: against a 3n + 10 ceiling
an entire EXTRA per-lot round-trip (2n+1 -> 3n+1) still PASSES — which is exactly
the regression this gate names as its RED condition. Commits are counted
SEPARATELY through ``ConnectionEvents.commit`` and asserted at <= n + 5.

Both counters are SCOPED TO THE SWEEP WINDOW (reset immediately before
``run_coop_expiry_sweep``, read immediately after) so the 10k bulk seed and the
assertion queries are not counted.

Wall-clock and max connection hold are RECORDED OBSERVATIONS, not gates —
wall-clock is environment-dependent and the hold equals the whole sweep by
construction (one session throughout).
"""

import datetime as dt
import time
import uuid

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.services.coop_expiry_sweep import run_coop_expiry_sweep

pytestmark = pytest.mark.disposable

N = 10_000
ROUND_TRIP_CEILING = 2 * N + 10  # 20,010 — hard FAIL above this
COMMIT_CEILING = N + 5
WALL_CLOCK_OBSERVATION_CEILING_S = 120.0


async def _bulk_seed(engine, n: int) -> None:
    """Bulk INSERT ... SELECT — never ORM per-row (that would dwarf the sweep)."""
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO identity_credit_ledger
                    (id, site_id, entry_type, amount, reason, lot_id,
                     spendable_at, expires_at, created_at, updated_at)
                SELECT g.id, 'scale', 'ACCRUE', 1, 'contribution', g.id,
                       :past, :past, now(), now()
                FROM (SELECT gen_random_uuid() AS id
                      FROM generate_series(1, :n)) g
                """
            ),
            {"past": past, "n": n},
        )


async def test_de18_sweep_round_trips_and_commits_at_scale(
    disposable_engine, clean_coop, request
):
    await _bulk_seed(disposable_engine, N)

    counts = {"round_trips": 0, "commits": 0}
    sync_engine = disposable_engine.sync_engine

    def _on_cursor(conn, cursor, statement, params, ctx, executemany):
        counts["round_trips"] += 1

    def _on_commit(conn):
        counts["commits"] += 1

    event.listen(sync_engine, "before_cursor_execute", _on_cursor)
    event.listen(sync_engine, "commit", _on_commit)
    try:
        factory = async_sessionmaker(disposable_engine, class_=AsyncSession)
        async with factory() as session:
            counts["round_trips"] = 0  # scope the window: exclude the bulk seed
            counts["commits"] = 0
            t0 = time.perf_counter()
            written = await run_coop_expiry_sweep(session)
            elapsed = time.perf_counter() - t0
        round_trips = counts["round_trips"]
        commits = counts["commits"]
    finally:
        event.remove(sync_engine, "before_cursor_execute", _on_cursor)
        event.remove(sync_engine, "commit", _on_commit)

    print(
        f"\nDE-18 n={N} written={written} round_trips={round_trips} "
        f"commits={commits} wall_clock={elapsed:.1f}s "
        f"max_connection_hold={elapsed:.1f}s (one session throughout)"
    )

    assert written == N
    # HARD GATE.
    assert round_trips <= ROUND_TRIP_CEILING, (
        f"{round_trips} counted round-trips exceeds the 2n+10 ceiling "
        f"({ROUND_TRIP_CEILING}) — a per-lot round-trip was added to the loop"
    )
    assert commits <= COMMIT_CEILING, (
        f"{commits} commits exceeds n+5 ({COMMIT_CEILING})"
    )
    # OBSERVATIONS ONLY — recorded, deliberately generous, not the gate.
    assert elapsed < WALL_CLOCK_OBSERVATION_CEILING_S, (
        f"sweep took {elapsed:.1f}s at n={N} — far outside the recorded "
        "observation ceiling; investigate before treating this as environmental"
    )
