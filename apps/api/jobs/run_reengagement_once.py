"""Run-and-exit entrypoint for the inactivity sweep (remind / auto-pause / nudge).

Two uses:

1. Manual dry-run before enabling the feature — see which owners the cohort
   queries actually select right now:
       python -m apps.api.jobs.run_reengagement_once
   (This SENDS REAL EMAIL and REALLY PAUSES SITES unless MOCK_EXTERNAL_APIS=true.
   Run it with mocking on the first time.)
2. A Railway cron service, if the sweep should survive API restarts:
       Start command:  python -m apps.api.jobs.run_reengagement_once
       Cron schedule:  0 14 * * *
   In that setup leave ``reengagement_enabled`` false so the in-process
   APScheduler job stays off — though the advisory lock inside
   ``run_reengagement_sweep`` means running both can't double-send anyway.

Note the install-nudge stage still honors ``reengagement_install_nudge_enabled``;
the remind and pause stages run whenever this entrypoint is invoked.
"""

import asyncio
import importlib
import pkgutil

import structlog

# Register every ORM model before any query compiles. The running API imports
# these via its routers; this standalone entrypoint must do it explicitly, or
# select(Site) fails resolving relationships.
import apps.api.models as _models_pkg
for _m in pkgutil.iter_modules(_models_pkg.__path__):
    importlib.import_module(f"apps.api.models.{_m.name}")

from apps.api.services.reengagement import run_reengagement_sweep

logger = structlog.get_logger()


async def _main() -> None:
    logger.info("cron_reengagement_started")
    try:
        counts = await run_reengagement_sweep()
        logger.info("cron_reengagement_done", **counts)
    except Exception:
        logger.exception("cron_reengagement_crashed")
        raise


if __name__ == "__main__":
    asyncio.run(_main())
