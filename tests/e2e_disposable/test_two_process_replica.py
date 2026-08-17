"""DE-9a / DE-9b / DE-10 / DE-17 — two real OS processes against one database.

Prod runs N replicas with no ``--workers``, so N containers = N schedulers
against one DB. One process can never observe that.

DE-9a and DE-9b have DIFFERENT RED conditions and must not be conflated (C-2/E-3):

* **DE-9a** (``sum(acquired) == 1``) is falsified by REMOVING THE LOCK.
* **DE-9b** (one EXPIRE row per lot) is falsified by removing
  ``uq_coop_ledger_expire_per_lot`` **while the advisory lock is stubbed out**.
  With the lock intact only one child ever enters ``expire_lapsed_lots``, so the
  loser writes nothing and dropping the index alone changes nothing. The index is
  a BACKSTOP, observable only once the lock is disabled. Removing the lock is NOT
  a DE-9b falsifier — row counts are lock-blind.
"""

import asyncio
import datetime as dt
import sys
import uuid

import pytest
from sqlalchemy import text

from tests.e2e_disposable.conftest import REPO_ROOT, seed_lapsed_lot, seed_site

pytestmark = pytest.mark.disposable

_N_LOTS = 400  # big enough that the critical section outlasts child startup (C-13)


async def _spawn(mode: str, barrier_dir, n_peers: int = 2):
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "tests.e2e_disposable._replica_child",
        mode,
        str(barrier_dir),
        str(n_peers),
        cwd=str(REPO_ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def _run_children(mode: str, barrier_dir, n: int = 2) -> list[str]:
    procs = [await _spawn(mode, barrier_dir, n) for _ in range(n)]
    try:
        results = await asyncio.gather(
            *(asyncio.wait_for(p.communicate(), timeout=300) for p in procs)
        )
    finally:
        for p in procs:
            if p.returncode is None:
                p.terminate()
    lines = []
    for (out, err), p in zip(results, procs):
        assert p.returncode == 0, f"child failed rc={p.returncode}: {err.decode()[-2000:]}"
        lines.append(out.decode().strip().splitlines()[-1])
    return lines


def _parse(line: str) -> dict:
    return dict(part.split("=", 1) for part in line.split())


# ── DE-9a / DE-9b ─────────────────────────────────────────────────────────────


async def test_de9_two_processes_one_winner_and_no_duplicate_rows(
    disposable_engine, clean_coop, tmp_path
):
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    lots = []
    async with disposable_engine.begin() as conn:
        for _ in range(_N_LOTS):
            lots.append(
                await seed_lapsed_lot(
                    conn, "de9", expires_at=past, spendable_at=past - dt.timedelta(1)
                )
            )

    lines = await _run_children("sweep", tmp_path / "barrier")
    parsed = [_parse(ln) for ln in lines]

    assert all(p["acquired"] != "none" for p in parsed), (
        f"a child hit the fail-OPEN None branch — sum(acquired) is meaningless: {lines}"
    )
    # DE-9a — exactly one lock winner.
    assert sum(p["acquired"] == "true" for p in parsed) == 1, lines

    # DE-9b — exactly one EXPIRE row per lot (backstop; see module docstring).
    async with disposable_engine.connect() as conn:
        dupes = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM ("
                    "  SELECT lot_id FROM identity_credit_ledger "
                    "  WHERE entry_type = 'EXPIRE' GROUP BY lot_id HAVING count(*) > 1"
                    ") d"
                )
            )
        ).scalar()
        total = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM identity_credit_ledger "
                    "WHERE entry_type = 'EXPIRE'"
                )
            )
        ).scalar()
    assert dupes == 0, "duplicate EXPIRE rows for a lot"
    assert total == _N_LOTS


# ── DE-10 — two-process accrual race ─────────────────────────────────────────


async def test_de10_two_process_accrual_race_collapses_to_one_row(
    disposable_engine, disposable_db, tmp_path
):
    """`uq_coop_accrued_site_email` is the real enforcement, not service code."""
    await seed_site(disposable_db, "de10")

    lines = await _run_children("accrue", tmp_path / "barrier")
    assert all("accrued=" in ln for ln in lines), lines  # neither process crashed

    async with disposable_engine.connect() as conn:
        accrued = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM identity_credit_ledger "
                    "WHERE site_id = 'de10' AND entry_type = 'ACCRUE'"
                )
            )
        ).scalar()
        events = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM identity_contribution_events "
                    "WHERE site_id = 'de10' AND accrued IS TRUE"
                )
            )
        ).scalar()
    assert accrued == 1, "a site earns at most ONE credit per identity, for all time"
    assert events == 1


# ── DE-17 — site deleted via the REAL router path, then re-created ───────────


async def test_de17_site_delete_then_recreate_same_site_id_has_zero_balance(
    disposable_engine, disposable_db, clean_coop
):
    """EXPECTED GREEN. Calls the REAL `routers/sites.py::delete_site` function
    (not a replica of its SQL — replicating it would make the gate vacuous
    against its own stated RED condition). delete_site explicitly issues
    `DELETE FROM identity_contribution_events` and `DELETE FROM
    identity_credit_ledger` under the "H1: close the site_id-reuse gap" comment,
    so Phase 1's H1 fix is intact. A RED here is a genuine billing-surface
    finding worth escalating immediately.

    Residual (backlog, NOT a live defect): there is no ForeignKey on
    `identity_credit_ledger.site_id`, so any delete path that bypasses
    `delete_site` leaves orphan rows with no DB-level guarantee.
    """
    from apps.api.routers.sites import delete_site
    from apps.api.services.identity_coop import spendable_balance

    site_id = "de17"
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    owner = await seed_site(disposable_db, site_id)
    async with disposable_engine.begin() as conn:
        await seed_lapsed_lot(
            conn,
            site_id,
            expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30),
            spendable_at=past,
        )
    assert await spendable_balance(disposable_db, site_id) == 1, "seed must be spendable"

    await delete_site(site_id, user=owner, db=disposable_db)
    await seed_site(disposable_db, site_id)

    assert await spendable_balance(disposable_db, site_id) == 0, (
        "a re-created site reusing the same site_id must NOT inherit credit"
    )
