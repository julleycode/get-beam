"""Run-and-exit entrypoint for the identity-resolution sweep.

For a Railway cron service: runs ONE full sweep across all auto-identify
sites, then exits. This decouples the sweep from the API process's in-loop
APScheduler, whose 30-min interval timer is reset on every deploy/restart
(so it effectively never fired). Cron triggers run independently of whether
the API process is up or just restarted.

Railway setup (separate service, same repo/image):
    Start command:  python -m apps.api.jobs.run_sweep_once
    Cron schedule:  */30 * * * *   (every 30 minutes)

run_resolution_sweep already holds a Postgres advisory lock, so this cron
and the in-process scheduler can't double-run.
"""

import asyncio
import importlib
import pkgutil

import structlog

# Register every ORM model before any query compiles. The running API imports
# these via its routers; this standalone entrypoint must do it explicitly, or
# select(Site) fails resolving relationships like SocialAccount.
import apps.api.models as _models_pkg
for _m in pkgutil.iter_modules(_models_pkg.__path__):
    importlib.import_module(f"apps.api.models.{_m.name}")

from apps.api.services.resolution_runner import run_resolution_sweep

logger = structlog.get_logger()


async def _main() -> None:
    logger.info("cron_resolution_sweep_started")
    try:
        await run_resolution_sweep()
        logger.info("cron_resolution_sweep_done")
    except Exception:
        logger.exception("cron_resolution_sweep_crashed")
        raise


if __name__ == "__main__":
    asyncio.run(_main())
