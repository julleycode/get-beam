"""Standalone child entrypoint for the two-process replica gate (DE-9a/b, DE-10).

Production runs N container replicas with NO ``--workers``, so N containers means
N ``AsyncIOScheduler`` instances against ONE database. That is the only item in
this lane that genuinely cannot be simulated in-process.

Usage:  python -m tests.e2e_disposable._replica_child <sweep|accrue> <barrier_dir> <n_peers>

Prints exactly one machine-readable line on stdout:
    sweep  -> ``acquired=<true|false|none> written=<n>``
    accrue -> ``accrued=<true|false>``

``acquired`` maps ``_try_acquire_lock``'s tri-state directly: True = won the
lock, False = another session held it, ``none`` = the lock query itself was
unsupported/errored (the fail-OPEN case the sweep proceeds on). The test asserts
no child ever prints ``none`` — a ``none`` would make ``sum(acquired) == 1``
meaningless.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SITE = "de10"
EMAIL_BIDX = "d" * 64


def _barrier(barrier_dir: str, n_peers: int, timeout: float = 60.0) -> None:
    """File-based start barrier so the children genuinely overlap (C-13)."""
    d = Path(barrier_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"ready-{os.getpid()}").write_text("1")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if len(list(d.glob("ready-*"))) >= n_peers:
            return
        time.sleep(0.02)
    raise SystemExit("barrier timeout")


async def _run(mode: str) -> str:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from apps.api.config import settings

    settings.identity_coop_enabled = True
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_size=3, max_overflow=2)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        if mode == "sweep":
            from apps.api.services import coop_expiry_sweep as ces

            observed: list = []
            real = ces._try_acquire_lock

            async def _watching(db):
                got = await real(db)
                observed.append(got)
                return got

            ces._try_acquire_lock = _watching
            async with factory() as db:
                written = await ces.run_coop_expiry_sweep(db)
            got = observed[0] if observed else None
            acquired = "none" if got is None else str(bool(got)).lower()
            return f"acquired={acquired} written={written}"

        from apps.api.services.identity_coop import record_contribution

        async with factory() as db:
            await record_contribution(
                db,
                site_id=SITE,
                email_bidx=EMAIL_BIDX,
                source_provider="e2e",
                is_abuse_flagged=False,
                is_bot_suspect=False,
            )
            from sqlalchemy import text

            row = await db.execute(
                text(
                    "SELECT count(*) FROM identity_credit_ledger "
                    "WHERE site_id = :s AND entry_type = 'ACCRUE'"
                ),
                {"s": SITE},
            )
            return f"accrued={str(bool(row.scalar())).lower()}"
    finally:
        await engine.dispose()


def main() -> None:
    mode, barrier_dir, n_peers = sys.argv[1], sys.argv[2], int(sys.argv[3])
    _barrier(barrier_dir, n_peers)
    print(asyncio.run(_run(mode)), flush=True)


if __name__ == "__main__":
    main()
